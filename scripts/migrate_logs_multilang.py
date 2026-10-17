"""
migrate_logs_multilang.py - 把 roms 的 21 个 logs_xx 列迁移为「logs 多语言分组 + roms.logs 单列」

背景
----
原结构：roms.logs_zh / logs_en / logs_ja / ... 一共 21 列，每列各自存一份 ID 引用结构
（指向 logs 表里该语言的模块名与条目原文）。同一句日志的不同语言版本互不关联。

新结构：
  * logs 表 = 同一日志的各语言版本共用一行（id / type / content / content_hash /
    logs_zh / logs_zh_tw / logs_en / ... / logs_bo，见 db_structure/logs.sql）；
  * roms.logs = 单一的语言中性 ID 引用结构 [[模块ID,[条目ID,...],语言掩码],...]。

迁移过程
--------
1. 读旧 logs 表（id -> content），用于把 roms.logs_xx 里的 ID 解回原文；
2. 旧 logs 表改名 logs_legacy，建新 logs 表，roms 加 logs / dev_week 列；
3. 分批扫 roms：每行把各语言结构按「结构指纹聚类 → 簇内按序号对齐」重新分组写入新 logs 表，
   并把结果回写到 roms.logs；
4. 删掉 21 个旧列与旧 CHECK → 加新的 json_valid(logs) → 修正自增计数（AUTO_INCREMENT = MAX(id)+1）。

用法
----
    python3 data/scripts/migrate_logs_multilang.py --dry-run   # 只统计，不写库
    python3 data/scripts/migrate_logs_multilang.py             # 正式迁移
    python3 data/scripts/migrate_logs_multilang.py --verify 20 # 迁移后抽查 N 条

注意：迁移前请先备份数据库（mysqldump），脚本会保留 logs_legacy 表以便回滚 / 核对。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import common
from miroms.database import DatabaseManager
from miroms.logs_store import LogStore

LEGACY_TABLE = 'logs_legacy'


def ts() -> str:
	return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# ==================== 读取旧结构 ====================


def load_legacy_map_from(table: str) -> dict:
	"""指定 logs 表 id -> content（把 roms.logs_xx 里的 ID 解回原文）"""
	rows = DatabaseManager.query_all(f"SELECT `id`, `content` FROM `{table}`")
	return {int(row[0]): row[1] for row in rows or []}


def decode_column(value, idmap: dict):
	"""把 roms.logs_xx 的值解成 {模块: [条目, ...]}

	兼容两种历史格式：
	- 已是 ID 引用结构 [[mid,[lids...]],...]
	- 最早期的原文 JSON {"模块": ["条目", ...]}
	"""
	if not value:
		return None
	try:
		parsed = json.loads(value) if isinstance(value, str) else value
	except (json.JSONDecodeError, TypeError):
		return None
	if LogStore.is_encoded(parsed):
		result = {}
		for item in parsed:
			module = idmap.get(int(item[0]))
			if module is None:
				continue
			result[module] = [idmap[int(x)] for x in item[1] if int(x) in idmap]
		return result
	if isinstance(parsed, dict):
		result = {}
		for module, lines in parsed.items():
			if not str(module or '').strip():
				continue
			if not isinstance(lines, list):
				lines = [lines]
			result[str(module)] = [str(x) for x in lines]
		return result
	return None


def rom_langs(row, idmap: dict) -> dict:
	"""一行 roms 的各语言日志结构 {语言列: {模块: [条目, ...]}}（空语言省略）"""
	langs = {}
	for index, column in enumerate(LogStore.LANG_COLUMNS):
		obj = decode_column(row[1 + index], idmap)
		if obj:
			langs[column] = obj
	return langs


def scan_roms(batch: int = 2000):
	"""按键集分页读取 roms 的 id + 21 个日志列"""
	columns = ', '.join(f'`{c}`' for c in LogStore.LANG_COLUMNS)
	last_id = 0
	while True:
		rows = DatabaseManager.query_all(
			f"SELECT `id`, {columns} FROM `roms` WHERE `id` > %s ORDER BY `id` LIMIT %s",
			params=(last_id, batch),
		)
		if not rows:
			break
		last_id = rows[-1][0]
		yield rows


# ==================== DDL 辅助 ====================


def column_exists(table: str, column: str) -> bool:
	row = DatabaseManager.query_one(
		"SELECT COUNT(*) FROM information_schema.COLUMNS "
		"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s",
		params=(table, column),
	)
	return bool(row and row[0])


def table_exists(table: str) -> bool:
	row = DatabaseManager.query_one(
		"SELECT COUNT(*) FROM information_schema.TABLES "
		"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s",
		params=(table,),
	)
	return bool(row and row[0])


def check_constraints(table: str) -> list:
	rows = DatabaseManager.query_all(
		"SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS "
		"WHERE CONSTRAINT_SCHEMA = DATABASE() AND TABLE_NAME = %s AND CONSTRAINT_TYPE = 'CHECK'",
		params=(table,),
	)
	return [row[0] for row in rows or []]


# ==================== 迁移主流程 ====================


def build_pool(idmap: dict, batch: int):
	"""第一遍：扫全部 roms，在内存行池里按语言结构完成跨 ROM 去重，返回行池

	先用共享行池把全部 ROM 的分组算出来（此时不写库），再统一入库；
	这样跨 ROM 的去重完全在内存完成，避免逐行查库。
	"""
	index = LogStore.new_index()
	roms_with_logs = 0
	for rows in scan_roms(batch):
		for row in rows:
			langs = rom_langs(row, idmap)
			if not langs:
				continue
			roms_with_logs += 1
			positions = LogStore.compose(langs)
			LogStore.build_rows(positions, index)
		print(f"\r[{ts()}] 第一遍扫描 id<={rows[-1][0]}：有日志 {roms_with_logs} 行，"
			  f"唯一日志 {len(index.rows)} 条（冲突拆行 {index.splits}）", end="", flush=True)
	print()
	return index, roms_with_logs


def rewrite_roms(idmap: dict, batch: int, index, ids: list) -> tuple:
	"""第二遍：重新计算分组位置（只读查找行池）并回写 roms.logs"""
	updated = 0
	failed = 0
	for rows in scan_roms(batch):
		updates = []
		for row in rows:
			langs = rom_langs(row, idmap)
			if not langs:
				continue
			try:
				positions = LogStore.compose(langs)
				refs = LogStore.build_rows(positions, index, mutate=False)[1]
				updates.append((LogStore.encode_refs(refs, ids), row[0]))
			except Exception as exc:
				failed += 1
				if failed <= 3:
					print(f"\n✖ 行 id={row[0]} 回写失败：{type(exc).__name__}: {exc}")
				continue
		if updates:
			DatabaseManager.execute_many(
				"UPDATE `roms` SET `logs` = %s WHERE `id` = %s", updates, raise_on_error=True,
			)
			updated += len(updates)
		print(f"\r[{ts()}] 第二遍回写 id<={rows[-1][0]}：已更新 {updated} 行", end="", flush=True)
	print()
	return updated, failed


def apply_ddl(dry_run: bool = False) -> None:
	"""roms 表结构改动：加 logs / dev_week"""
	if dry_run:
		print("[dry-run] 将执行：ALTER TABLE roms ADD COLUMN logs / dev_week")
		return
	if not column_exists('roms', 'logs'):
		DatabaseManager.execute(
			"ALTER TABLE `roms` ADD COLUMN `logs` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin "
			"COMMENT '更新日志（语言中性）的 logs 表 ID 引用结构（见 logs.sql）："
			"[[模块ID,[条目ID,...],语言掩码],...]；具体语言在 logs 表按列存放' AFTER `update_date`",
			raise_on_error=True,
		)
		print(f"[{ts()}] roms.logs 已新增")
	if not column_exists('roms', 'dev_week'):
		DatabaseManager.execute(
			"ALTER TABLE `roms` ADD COLUMN `dev_week` int DEFAULT NULL "
			"COMMENT '开发版周数：该 ROM 属于哪一周的开发版（仅 branch=X 有意义，见 dev 表）' "
			"AFTER `logs`",
			raise_on_error=True,
		)
		print(f"[{ts()}] roms.dev_week 已新增")


def drop_legacy_columns(dry_run: bool = False) -> None:
	"""删除 21 个 logs_xx 列与旧 CHECK，加新的 json_valid(logs)"""
	present = [c for c in LogStore.LANG_COLUMNS if column_exists('roms', c)]
	if not present:
		print(f"[{ts()}] roms 已无旧语言列，跳过")
		return
	if dry_run:
		print(f"[dry-run] 将删除 roms 的 {len(present)} 个旧语言列并替换 CHECK 约束")
		return

	old_checks = [name for name in check_constraints('roms') if name.startswith('roms_chk_')]
	if old_checks:
		DatabaseManager.execute(
			"ALTER TABLE `roms` " + ', '.join(f'DROP CHECK `{name}`' for name in old_checks),
			raise_on_error=True,
		)
	DatabaseManager.execute(
		"ALTER TABLE `roms` " + ', '.join(f'DROP COLUMN `{name}`' for name in present),
		raise_on_error=True,
	)
	DatabaseManager.execute(
		"ALTER TABLE `roms` ADD CONSTRAINT `roms_chk_1` CHECK (json_valid(`logs`))",
		raise_on_error=True,
	)
	print(f"[{ts()}] 已删除 {len(present)} 个旧语言列并加上 json_valid(logs) 约束")


def fix_auto_increment(dry_run: bool = False) -> int:
	row = DatabaseManager.query_one("SELECT MAX(`id`) FROM `roms`")
	max_id = int(row[0]) if row and row[0] else 0
	if dry_run:
		print(f"[dry-run] 将把 roms AUTO_INCREMENT 修正为 {max_id + 1}")
		return max_id + 1
	if max_id:
		DatabaseManager.execute(
			f"ALTER TABLE `roms` AUTO_INCREMENT = {max_id + 1}", raise_on_error=True,
		)
		print(f"[{ts()}] roms AUTO_INCREMENT 已修正为 {max_id + 1}（原表计数落后于最大 id）")
	return max_id + 1


# ==================== 校验 ====================


def verify(limit: int, idmap: dict) -> int:
	"""抽查新 roms.logs 解出的中英文日志是否与旧列一致"""
	LogStore.refresh_cache()
	has_zh = column_exists('roms', 'logs_zh')
	select = "SELECT `id`, `logs`, `logs_zh`, `logs_en` FROM `roms`" if has_zh else \
		"SELECT `id`, `logs`, NULL, NULL FROM `roms`"
	rows = DatabaseManager.query_all(
		f"{select} WHERE `logs` IS NOT NULL ORDER BY `id` DESC LIMIT %s", params=(limit,))
	bad = 0
	for row in rows or []:
		new = LogStore.build_localized(json.loads(row[1]) if row[1] else None)
		for offset, column in ((2, 'logs_zh'), (3, 'logs_en')):
			if not row[offset]:
				continue
			old = decode_column(row[offset], idmap) or {}
			old = {str(k).strip(): [str(x).strip() for x in v] for k, v in old.items()}
			if old != (new.get(column) or {}):
				bad += 1
				if bad <= 3:
					print(f"\n⚠ id={row[0]} {column} 不一致\n  旧: {json.dumps(old, ensure_ascii=False)[:200]}"
						  f"\n  新: {json.dumps(new.get(column) or {}, ensure_ascii=False)[:200]}")
	print(f"[{ts()}] 抽查 {len(rows or [])} 行，中英文日志不一致 {bad} 项")
	return bad


def main() -> None:
	parser = argparse.ArgumentParser(description='roms 多语言日志列迁移为 logs 分组 + roms.logs 单列')
	parser.add_argument('--dry-run', action='store_true', help='只统计，不写库')
	parser.add_argument('--batch', type=int, default=2000, help='分页批大小（默认 2000）')
	parser.add_argument('--verify', type=int, default=0, metavar='N', help='迁移后抽查 N 行中英文日志是否一致')
	args = parser.parse_args()

	print(f"[{ts()}] 开始迁移多语言日志结构...")
	legacy_exists = table_exists(LEGACY_TABLE)
	old_columns = [c for c in LogStore.LANG_COLUMNS if column_exists('roms', c)]
	if not legacy_exists and not old_columns and column_exists('roms', 'logs'):
		print("roms 已是单列结构且没有旧语言列，无需迁移。")
		return

	# 1) 读取旧 logs 表（首次运行直接读 logs，重跑时读 logs_legacy）
	source_table = LEGACY_TABLE if legacy_exists else 'logs'
	idmap = load_legacy_map_from(source_table)
	print(f"[{ts()}] 旧日志原文来源 {source_table}：{len(idmap)} 条")

	if args.dry_run:
		total = 0
		for rows in scan_roms(args.batch):
			for row in rows:
				if rom_langs(row, idmap):
					total += 1
		print(f"[dry-run] 有日志的 ROM {total} 行；将重建 logs 表并按语言结构分组")
		apply_ddl(dry_run=True)
		drop_legacy_columns(dry_run=True)
		fix_auto_increment(dry_run=True)
		return

	# 2) 旧表改名 + 建新表 + roms 加列
	if source_table != LEGACY_TABLE:
		DatabaseManager.execute(f"RENAME TABLE `logs` TO `{LEGACY_TABLE}`", raise_on_error=True)
		print(f"[{ts()}] 旧 logs 表已改名为 {LEGACY_TABLE}")
	LogStore.ensure_table()
	print(f"[{ts()}] 新 logs 表就绪")
	apply_ddl()

	# 3) 第一遍：内存行池去重
	index, roms_with_logs = build_pool(idmap, args.batch)
	modules = sum(1 for r in index.rows if r['type'] == LogStore.TYPE_MODULE)
	print(f"[{ts()}] 分组完成：有日志的 ROM {roms_with_logs} 行，唯一日志 {len(index.rows)} 条"
		  f"（模块 {modules} / 条目 {len(index.rows) - modules}，冲突拆行 {index.splits}）")
	if index.conflicts:
		print(f"       语言冲突样本：{index.conflicts[:2]}")

	# 4) 写入 logs 表
	print(f"[{ts()}] 批量写入 logs 表...")
	ids = LogStore.ensure_ids(index.rows)
	print(f"[{ts()}] logs 表写入完成，共 {LogStore.count()} 条")

	# 5) 第二遍：回写 roms.logs
	updated, failed = rewrite_roms(idmap, args.batch, index, ids)
	print(f"[{ts()}] roms.logs 回写完成：{updated} 行，失败 {failed} 行")

	if args.verify:
		verify(args.verify, idmap)
	drop_legacy_columns()
	fix_auto_increment()

	dupes = LogStore.duplicate_report()
	print(f"[{ts()}] 去重体检：重复分组 {len(dupes)} 组"
		  + (f"（如 {dupes[0]}）" if dupes else " ✓"))
	if dupes:
		print("    ✖ 存在重复日志分组，请运行：python3 data/scripts/dedup_logs.py --apply")

	print(f"\n[{ts()}] 迁移完成，logs 表共 {LogStore.count()} 条。"
		  f"核对无误后可执行：DROP TABLE `{LEGACY_TABLE}`;")
	if failed or dupes:
		sys.exit(1)


if __name__ == '__main__':
	main()
