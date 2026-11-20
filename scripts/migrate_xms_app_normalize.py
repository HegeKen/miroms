#!/usr/bin/env python3
"""把 xms_app 归一化为「xms_app_release（发布物）+ xms_app（关联表）」。

背景：旧 xms_app 每个推送里每个应用一行，同一 (pkg, pkg_ver) 会被数十次推送重复
录入（实测 pkg_ver=1306003100 有 36 行，全表 2983 行仅 83 个真实 APK）。同一
(pkg, pkg_ver) 的 md5 / file_name / apk_name / logs / release_date 恒等，故抽离到
xms_app_release（唯一键 (pkg, pkg_ver)），xms_app 只保留 xms_id ↔ release_id 关联。

执行步骤：
  1. 预检：确认 xms_app 还是旧宽表；校验同一 (pkg, pkg_ver) 的宽列无冲突
  2. 建 xms_app_release（IF NOT EXISTS），从旧表按 (pkg,pkg_ver) 选「最完整」行回填
  3. 在临时表 xms_app_new 生成关联行（保留原 id / xms_id / pkg）
  4. RENAME 原子切换：xms_app → xms_app_archive，xms_app_new → xms_app
  5. 校验行数无损；默认保留 xms_app_archive 作为回滚备份

用法：
    python3 scripts/migrate_xms_app_normalize.py            # 执行迁移
    python3 scripts/migrate_xms_app_normalize.py --check    # 只预检，不改库
    python3 scripts/migrate_xms_app_normalize.py --drop-archive  # 迁移后删除归档表
回滚：
    DROP TABLE xms_app; RENAME TABLE xms_app_archive TO xms_app; DROP TABLE xms_app_release;
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
from miroms.database import DatabaseManager  # noqa: E402


def canonical_json(value) -> str:
    """把 names / logs 这类 JSON 文本归一化为紧凑、确定的字符串。

    历史数据里同一 (pkg, pkg_ver) 的 logs 可能出现两种序列化（紧凑 vs 带空格），
    逻辑内容完全一致；归一化后即可合并到同一 release。解析失败时原样返回。
    """
    if not value:
        return value
    try:
        return json.dumps(json.loads(value), ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return value


def _table_exists(table: str) -> bool:
    row = DatabaseManager.query_one(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_name = %s", (table,))
    return bool(row and row[0])


def _col_exists(table: str, col: str) -> bool:
    row = DatabaseManager.query_one(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = %s AND column_name = %s",
        (table, col))
    return bool(row and row[0])


def detect_state() -> str:
    """返回 'old'（宽表待迁移）/'migrated'（已关联表）/'archive-only'（仅剩归档）/'unknown'。"""
    if _table_exists("xms_app") and _col_exists("xms_app", "release_id"):
        return "migrated"
    if _table_exists("xms_app") and _col_exists("xms_app", "md5"):
        return "old"
    if _table_exists("xms_app_archive") and _col_exists("xms_app_archive", "md5"):
        return "archive-only"
    return "unknown"


def safety_check(source: str) -> list:
    """校验同一 (pkg, pkg_ver) 内各宽列归一化后只有一个值。

    names / logs 先做 JSON 归一化（消除紧凑/带空格的序列化差异）再比较；
    其它列直接比较。返回 [(列名, [(pkg, pkg_ver), ...]), ...]。
    """
    rows = DatabaseManager.query_all(
        f"SELECT pkg, IFNULL(pkg_ver,''), name, name_en, names, apk_name, file_name, "
        f"size, md5, sha256, logs, release_date FROM {source} "
        f"WHERE pkg <> '' AND pkg_ver <> ''")
    col_names = ["name", "name_en", "names", "apk_name", "file_name",
                 "size", "md5", "sha256", "logs", "release_date"]
    groups: dict = {}
    for r in rows:
        key = (r[0], r[1])
        groups.setdefault(key, []).append(r)
    bad = []
    for ci, col in enumerate(col_names, start=2):
        conflicting = []
        for key, lst in groups.items():
            vals = set()
            for r in lst:
                v = r[ci]
                if v is None or v == "":
                    continue  # 空值视为「未回填」，不算冲突；取非空的那一份即可
                if col in ("names", "logs"):
                    v = canonical_json(v)
                vals.add(v)
            if len(vals) > 1:
                conflicting.append(key)
        if conflicting:
            bad.append((col, conflicting[:10]))
    return bad


def _coalesced_row_per_group(source: str) -> dict:
    """按 (pkg, pkg_ver) 分组，每组合并出一行「最完整」数据。

    对每个宽列，取组内第一个非空值（names / logs 先做 JSON 归一化）。
    因为预检已保证同一组内非空值彼此一致，所以「取任一非空值」即等价于
    取该列的真实值，且能把散落在不同行的回填结果（如 release_date 只在部分行有）
    合并到同一 release，避免丢数据。返回值的列顺序与 SELECT 一致（含 id=组内最小 id）。
    """
    rows = DatabaseManager.query_all(
        f"SELECT id, pkg, pkg_ver, name, name_en, names, apk_name, file_name, "
        f"size, md5, sha256, logs, release_date FROM {source} "
        f"WHERE pkg <> '' AND pkg_ver <> ''")
    json_idx = {5, 11}  # names, logs
    groups: dict = {}
    for r in rows:
        key = (r[1], r[2] or "")
        groups.setdefault(key, []).append(r)
    merged = {}
    for key, lst in groups.items():
        lst.sort(key=lambda r: r[0])  # 按 id 升序，稳定
        acc = [None] * 13
        acc[0] = lst[0][0]  # 最小 id（仅作参考，不写入）
        acc[1] = lst[0][1]  # pkg
        acc[2] = lst[0][2] or ""  # pkg_ver
        for r in lst:
            for i in range(3, 13):
                if acc[i] in (None, ""):
                    v = r[i]
                    if i in json_idx:
                        v = canonical_json(v)
                    acc[i] = v if v not in (None, "") else acc[i]
        merged[key] = tuple(acc)
    return merged


def backfill_releases(source: str) -> dict:
    """从 source（旧宽表）回填 xms_app_release，返回 {(pkg,pkg_ver): release_id}。"""
    best = _coalesced_row_per_group(source)
    rel_map: dict = {}
    insert_sql = (
        "INSERT INTO xms_app_release "
        "(pkg, pkg_ver, name, name_en, names, apk_name, file_name, size, "
        "md5, sha256, logs, release_date) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)")
    for (pkg, pkg_ver), r in best.items():
        existing = DatabaseManager.query_one(
            "SELECT id FROM xms_app_release WHERE pkg = %s AND pkg_ver <=> %s",
            (pkg, pkg_ver))
        if existing:
            rel_map[(pkg, pkg_ver)] = int(existing[0])
            continue
        rid = DatabaseManager.insert(
            insert_sql,
            (r[1], r[2] or "", r[3], r[4], canonical_json(r[5]), r[6], r[7], r[8],
             r[9], r[10], canonical_json(r[11]), r[12]),
            raise_on_error=True)
        rel_map[(pkg, pkg_ver)] = rid
    return rel_map


def build_membership(source: str, rel_map: dict) -> int:
    """在 xms_app_new 生成关联行（保留原 id），返回行数。"""
    DatabaseManager.execute(
        "DROP TABLE IF EXISTS xms_app_new", raise_on_error=True)
    DatabaseManager.execute(
        "CREATE TABLE `xms_app_new` ("
        "`id` bigint NOT NULL, "
        "`xms_id` bigint NOT NULL, "
        "`release_id` bigint NOT NULL, "
        "`pkg` varchar(128) COLLATE utf8mb4_bin NOT NULL DEFAULT '', "
        "PRIMARY KEY (`id`), "
        "UNIQUE KEY `uq_xms_app_xms_pkg` (`xms_id`,`pkg`), "
        "UNIQUE KEY `uq_xms_app_xms_release` (`xms_id`,`release_id`), "
        "KEY `idx_xms_app_release` (`release_id`), "
        "KEY `idx_xms_app_pkg` (`pkg`)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC",
        raise_on_error=True)

    old_rows = DatabaseManager.query_all(
        f"SELECT id, xms_id, pkg, pkg_ver FROM {source}")
    params = []
    missing = 0
    for oid, xms_id, pkg, pkg_ver in old_rows:
        rid = rel_map.get((pkg, pkg_ver or ""))
        if rid is None:
            missing += 1
            continue
        params.append((oid, xms_id, rid, pkg))
    if missing:
        raise RuntimeError(f"{missing} 行旧数据找不到对应 release，迁移中止")
    DatabaseManager.execute_many(
        "INSERT INTO xms_app_new (id, xms_id, release_id, pkg) VALUES (%s,%s,%s,%s)",
        params, raise_on_error=True)
    return len(params)


def verify(source: str, expected_membership: int) -> None:
    release_cnt = DatabaseManager.query_one("SELECT COUNT(*) FROM xms_app_release")[0]
    member_cnt = DatabaseManager.query_one("SELECT COUNT(*) FROM xms_app")[0]
    print(f"  xms_app_release: {release_cnt} 行（期望约 83）")
    print(f"  xms_app:         {member_cnt} 行（期望 {expected_membership}）")
    if member_cnt != expected_membership:
        raise RuntimeError(f"关联表行数 {member_cnt} != 旧表 {expected_membership}，迁移不完整")

    # 无损校验（Python 侧，names / logs 做 JSON 归一化后再比）：
    # 旧表每行应能在「新关联 JOIN release」中找到同 id 且宽列一致的行。
    cols = ["pkg", "pkg_ver", "name", "name_en", "names", "apk_name", "file_name",
            "size", "md5", "sha256", "logs", "release_date"]
    old = {r[0]: r for r in DatabaseManager.query_all(
        f"SELECT id, {', '.join(cols)} FROM {source}")}
    new = {r[0]: r for r in DatabaseManager.query_all(
        "SELECT m.id, m.pkg, r.pkg_ver, r.name, r.name_en, r.names, r.apk_name, "
        "r.file_name, r.size, r.md5, r.sha256, r.logs, r.release_date "
        "FROM xms_app m JOIN xms_app_release r ON r.id = m.release_id")}
    json_cols = {"names", "logs"}
    diff = 0
    for oid, o in old.items():
        n = new.get(oid)
        if n is None:
            diff += 1
            continue
        for i, col in enumerate(cols):
            ov = o[i + 1]
            if ov in (None, ""):
                continue  # 旧值为空：release 可取其它行的非空值（合并回填），不算丢失
            nv = n[i + 1]
            if col in json_cols:
                ov, nv = canonical_json(ov), canonical_json(nv)
            if (ov or None) != (nv or None):
                diff += 1
                break
    print(f"  旧表 vs 新关联 JOIN release 差异行数：{diff}（期望 0）")
    if diff != 0:
        raise RuntimeError("迁移后数据与旧表不一致，请排查")


def main() -> int:
    parser = argparse.ArgumentParser(description="xms_app 归一化迁移")
    parser.add_argument("--check", action="store_true", help="只预检，不改库")
    parser.add_argument("--drop-archive", action="store_true",
                        help="迁移成功后删除 xms_app_archive 归档表")
    args = parser.parse_args()

    state = detect_state()
    print(f"当前状态: {state}")

    if state == "migrated":
        print("xms_app 已是关联表结构，迁移已完成。")
        if _table_exists("xms_app_archive"):
            print(f"  归档表 xms_app_archive 仍保留（共 "
                  f"{DatabaseManager.query_one('SELECT COUNT(*) FROM xms_app_archive')[0]} 行），"
                  f"确认无误后可加 --drop-archive 删除。")
        return 0

    if state not in ("old", "archive-only"):
        print("错误：找不到可迁移的旧宽表（xms_app 或 xms_app_archive）。", file=sys.stderr)
        return 2

    source = "xms_app" if state == "old" else "xms_app_archive"
    print(f"数据源表: {source}")

    # 预检：同一 (pkg,pkg_ver) 内宽列无冲突
    print("预检：校验同一 (pkg, pkg_ver) 的宽列一致性...")
    bad = safety_check(source)
    if bad:
        print("发现同一 (pkg, pkg_ver) 内存在不一致的列，中止迁移：", file=sys.stderr)
        for col, rows in bad:
            print(f"  列 {col}: {rows}", file=sys.stderr)
        return 3
    print("  通过。")

    old_cnt = DatabaseManager.query_one(f"SELECT COUNT(*) FROM {source}")[0]
    distinct = DatabaseManager.query_one(
        f"SELECT COUNT(DISTINCT CONCAT(pkg,'|',IFNULL(pkg_ver,''))) FROM {source} "
        f"WHERE pkg <> '' AND pkg_ver <> ''")[0]
    print(f"旧表 {old_cnt} 行，去重后 {distinct} 个 (pkg, pkg_ver)。")

    if args.check:
        print("--check：预检通过，未改动数据库。")
        return 0

    # 1) 建 release 表
    print("步骤 1：创建 xms_app_release...")
    DatabaseManager.execute(
        "CREATE TABLE IF NOT EXISTS `xms_app_release` ("
        "`id` bigint NOT NULL AUTO_INCREMENT, "
        "`pkg` varchar(128) COLLATE utf8mb4_bin NOT NULL DEFAULT '', "
        "`pkg_ver` varchar(64) COLLATE utf8mb4_bin NOT NULL DEFAULT '', "
        "`name` varchar(128) COLLATE utf8mb4_bin DEFAULT NULL, "
        "`name_en` varchar(128) COLLATE utf8mb4_bin DEFAULT NULL, "
        "`names` longtext COLLATE utf8mb4_bin, "
        "`apk_name` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL, "
        "`file_name` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL, "
        "`size` bigint DEFAULT NULL, "
        "`md5` char(32) COLLATE utf8mb4_bin DEFAULT NULL, "
        "`sha256` char(64) COLLATE utf8mb4_bin DEFAULT NULL, "
        "`logs` longtext COLLATE utf8mb4_bin, "
        "`release_date` date DEFAULT NULL, "
        "PRIMARY KEY (`id`), "
        "UNIQUE KEY `uq_release_pkg_ver` (`pkg`,`pkg_ver`), "
        "KEY `idx_release_pkg` (`pkg`), "
        "KEY `idx_release_md5` (`md5`)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC",
        raise_on_error=True)

    # 2) 回填 release
    print("步骤 2：回填 xms_app_release...")
    rel_map = backfill_releases(source)
    print(f"  release 行数：{len(rel_map)}")

    # 3) 生成关联行到 xms_app_new
    print("步骤 3：生成关联行到 xms_app_new...")
    member_cnt = build_membership(source, rel_map)
    print(f"  关联行数：{member_cnt}")

    # 4) 原子切换
    print("步骤 4：RENAME 切换（xms_app → xms_app_archive，xms_app_new → xms_app）...")
    if state == "old":
        DatabaseManager.execute(
            "RENAME TABLE xms_app TO xms_app_archive, xms_app_new TO xms_app",
            raise_on_error=True)
    else:
        # archive-only：旧 xms_app 已被归档，直接把 new 改名为 xms_app
        DatabaseManager.execute("RENAME TABLE xms_app_new TO xms_app", raise_on_error=True)

    # 5) 校验
    print("步骤 5：校验...")
    verify("xms_app_archive", old_cnt)

    if args.drop_archive:
        print("删除归档表 xms_app_archive...")
        DatabaseManager.execute("DROP TABLE xms_app_archive", raise_on_error=True)
    else:
        print("已保留归档表 xms_app_archive 作为回滚备份；确认无误后可加 --drop-archive 删除。")

    print("迁移完成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
