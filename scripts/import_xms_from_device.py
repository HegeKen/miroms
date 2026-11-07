#!/usr/bin/env python3
"""从内测实机导入 XMS（SOTA 系统应用更新）推送

OS4 的内测 XMS 在接口侧按账号授权下发：爬虫的无账号请求对这类版本
hasXmsUpdate=0（甚至不回 LatestRom/CurrentRom），`XmsStore.record` 因此拿不到数据。
本脚本改为读取实机 updater 已缓存的响应（需 root），再复用 `XmsStore` 的规则写库：

    /data/data/com.android.updater/shared_prefs/version_json.xml

  * xms_new_version      -> hasXmsUpdate / curVer / lstVer / pkgs / pkgCnt / prio / gentleNotice
  * xms_dto_new_version  -> apkLists（版本号、文件名、体积、md5、sha256、签名下载链接）
                            与 changeLog（按模块名分组的更新日志）

changeLog 里不带 package，脚本按「模块名 → 包名」在 `xms_app` 里查同名记录
（要求唯一命中）回填 package / versionCode；找不到的模块保持无包名，落 `xms.changelog`。
APK 的 release_date 用签名下载链接的 Last-Modified 立即回填（链接有时效）。

用法：
    python3 scripts/import_xms_from_device.py
    python3 scripts/import_xms_from_device.py --serial <serial>
    python3 scripts/import_xms_from_device.py --file /tmp/version_json.xml
    python3 scripts/import_xms_from_device.py --skip-release-dates
"""
import argparse
import html
import json
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
from miroms.firmware import FirmwareParser  # noqa: E402
from miroms.xms import XmsStore  # noqa: E402

PREFS_PATH = "/data/data/com.android.updater/shared_prefs/version_json.xml"


def read_device_prefs(serial: str = "") -> str:
    """adb 读取 updater 的 version_json.xml（需要 root）"""
    prefix = ["adb"] + (["-s", serial] if serial else [])
    for command in (f"su -c 'cat {PREFS_PATH}'", f"cat {PREFS_PATH}"):
        try:
            proc = subprocess.run(prefix + ["shell", command], capture_output=True, text=True)
        except FileNotFoundError:
            raise SystemExit("未找到 adb，请确认已安装并加入 PATH")
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout
    raise SystemExit(f"读取 {PREFS_PATH} 失败：请确认实机已连接且已 root")


def load_payload(raw: str):
    prefs = dict(re.findall(r'<string name="([^"]+)">(.*?)</string>', raw, re.S))
    missing = [key for key in ("xms_new_version", "xms_dto_new_version") if key not in prefs]
    if missing:
        raise SystemExit(f"实机缓存里没有 {', '.join(missing)}：请先在实机系统更新里打开 SOTA 详情")

    def parse(key):
        return json.loads(html.unescape(prefs[key]))

    info = parse("xms_new_version")
    dto = parse("xms_dto_new_version")
    # current_version 的 LatestRom / CurrentRom 是表单与 is_latest 的依据
    current = parse("current_version") if "current_version" in prefs else {}
    return info, dto, current


def resolve_rom(code: str, rom_version: str):
    """从 roms 取 branch / region / tag，保证 record() 能找到 rom_id"""
    return common.DatabaseManager.query_one(
        "SELECT id, region, tag, branch FROM roms "
        "WHERE code = %s AND version = %s ORDER BY id DESC LIMIT 1",
        params=(code, rom_version)
    )


def module_packages(modules):
    """模块名 -> 包名：只接受库内同名且唯一命中的映射"""
    if not modules:
        return {}
    placeholders = ",".join(["%s"] * len(modules))
    rows = common.DatabaseManager.query_all(
        f"SELECT DISTINCT name, pkg FROM xms_app WHERE name IN ({placeholders})",
        params=tuple(modules)
    )
    grouped = {}
    for name, pkg in rows:
        grouped.setdefault(name, set()).add(pkg)
    return {name: next(iter(pkgs)) for name, pkgs in grouped.items() if len(pkgs) == 1}


def build_apks(dto):
    apks = {}
    for apk in dto.get("apkLists") or []:
        pkg = str(apk.get("packName") or "").strip()
        if not pkg:
            continue
        apks[pkg] = {
            "version": str(apk.get("lastVerCode") or "").strip(),
            "apk_name": str(apk.get("name") or "").strip(),
            "file_name": str(apk.get("fileName") or "").strip(),
            "size": int(apk.get("size") or 0),
            "md5": str(apk.get("md5") or "").strip(),
            "sha256": str(apk.get("sha256") or "").strip(),
            "download_urls": [str(url) for url in (apk.get("downloadUrls") or []) if url],
        }
    return apks


def build_changelog(dto, apks):
    """给 changeLog 每个条目补上 package / versionCode"""
    mapping = module_packages(list((dto.get("changeLog") or {}).get("lightList") or {}))
    log = {}
    for module, items in ((dto.get("changeLog") or {}).get("lightList") or {}).items():
        pkg = mapping.get(module, "")
        entries = []
        for item in items:
            entry = dict(item)
            if pkg:
                entry["package"] = pkg
                entry["versionCode"] = apks.get(pkg, {}).get("version", "")
            entries.append(entry)
        log[module] = entries
    if mapping:
        print(f"模块映射：{len(mapping)} 个 "
              + "、".join(f"{name}→{pkg}" for name, pkg in list(mapping.items())[:5])
              + ("…" if len(mapping) > 5 else ""))
    missing = [name for name in log if name not in mapping]
    if missing:
        print(f"未映射模块（落 xms.changelog）：{'、'.join(missing)}")
    return log


def apk_release_date(apk):
    """签名下载链接的 Last-Modified -> 北京时间日期"""
    for url in apk.get("download_urls") or []:
        try:
            response = requests.head(url, allow_redirects=True, timeout=15)
            last_modified = response.headers.get("Last-Modified")
            if last_modified:
                return (datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S %Z")
                        + timedelta(hours=8)).strftime("%Y-%m-%d")
        except (requests.RequestException, ValueError):
            continue
    return ""


def main() -> int:
    parser = argparse.ArgumentParser(description="从内测实机导入 XMS 推送")
    parser.add_argument("--serial", default="", help="adb 设备序列号（多设备时指定）")
    parser.add_argument("--file", default="", help="改为读取本地的 version_json.xml")
    parser.add_argument("--skip-release-dates", action="store_true",
                        help="不请求签名链接回填 xms_app.release_date")
    args = parser.parse_args()

    raw = Path(args.file).read_text(encoding="utf-8", errors="ignore") if args.file \
        else read_device_prefs(args.serial)
    info, dto, current = load_payload(raw)

    if str(info.get("hasXmsUpdate") or "0") != "1":
        print("实机当前没有可用的 XMS 更新（hasXmsUpdate=0）")
        return 0

    xms_version = str(info.get("lstVer") or "").strip()
    dto_version = str((dto.get("xmsVersion") or {}).get("lastVer") or "").strip()
    if dto_version and dto_version != xms_version:
        raise SystemExit(f"缓存不一致：xms_new_version 的 lstVer={xms_version}，"
                         f"xms_dto_new_version 的 lastVer={dto_version}")

    latest_rom = current.get("LatestRom") or {}
    code = str(latest_rom.get("device") or "").strip()
    rom_version = str((current.get("CurrentRom") or {}).get("version")
                      or latest_rom.get("version") or "").strip()
    if not code or not rom_version:
        raise SystemExit("实机缓存里缺少机型 / 当前系统版本")
    if XmsStore._os_major(rom_version) < XmsStore.MIN_OS_MAJOR:
        print(f"{rom_version} 低于 HyperOS 3，XMS 无需入库")
        return 0

    rom = resolve_rom(code, rom_version)
    if not rom:
        raise SystemExit(f"roms 里没有 {code} / {rom_version}，请等该版本入库后再导入")
    _rom_id, region, tag, branch = rom
    zone = 1 if region == "cn" else 2
    android = str(latest_rom.get("codebase") or "17.0")

    form = FirmwareParser.build_ota_form(code, code, region, branch, zone, android, rom_version)

    apks = build_apks(dto)
    zh_log = build_changelog(dto, apks)
    result = {
        "LatestRom": {"version": str(latest_rom.get("version") or rom_version)},
        "CurrentRom": {"version": rom_version},
        "xmsUpdateInfo": {**info, "changeLog": zh_log},
    }
    # 预置缓存，避免 record() 去请求需要内测授权的接口
    XmsStore._changelog_cache[(code, xms_version)] = (zh_log, {})
    XmsStore._version_cache[("ver", code, xms_version)] = apks

    record = XmsStore.record(form, result)
    if not record:
        print("未入库：接口缓存与 roms 不匹配，或该版本低于 HyperOS 3")
        return 3
    print(f"写入 xms id={record['id']}：{code} {rom_version} → {xms_version}，"
          f"{record['apps']} 个应用")

    if not args.skip_release_dates:
        tasks = [(pkg, apk) for pkg, apk in apks.items()]
        with ThreadPoolExecutor(max_workers=8) as pool:
            dated = list(pool.map(lambda task: (task[0], apk_release_date(task[1])), tasks))
        updated = 0
        for pkg, date_text in dated:
            if not date_text:
                continue
            common.DatabaseManager.execute(
                "UPDATE xms_app SET release_date = %s WHERE xms_id = %s AND pkg = %s",
                params=(date_text, record["id"], pkg), raise_on_error=True
            )
            updated += 1
        print(f"release_date 回填：{updated}/{len(tasks)} 个安装包")
        if updated:
            XmsStore.normalize_push_dates(apply=True)

    print(common.DatabaseManager.query_all(
        "SELECT x.version, x.rom_version, x.pkg_cnt, x.prio, x.is_latest, x.push_date, "
        "COUNT(a.id), MIN(a.release_date), MAX(a.release_date) "
        "FROM xms x LEFT JOIN xms_app a ON a.xms_id = x.id "
        "WHERE x.code = %s AND x.version = %s GROUP BY x.id",
        params=(code, xms_version)
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
