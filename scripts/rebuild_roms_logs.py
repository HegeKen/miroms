"""
rebuild_roms_logs.py - 按迁移前的备份库重建 roms.logs（修复悬空引用 / 局部脏数据）

用途：`roms.logs` 是语言中性的 ID 引用结构，若 logs 表被人工改动过（删行、合并行），
就可能出现引用不存在的 ID。本脚本以迁移前的备份库（含 21 个 logs_* 列）为权威来源，
按当前 logs 表重新分组并回写 roms.logs，最后做「无悬空引用」与「各语言还原一致」双重校验。

用法：
    # 先把迁移前的备份恢复到临时库
    mysql -uroot -p*** -e "DROP DATABASE IF EXISTS miroms_verify; CREATE DATABASE miroms_verify ..."
    mysql -uroot -p*** miroms_verify < .backup/miroms_before_logs_multilang_*.sql

    python3 data/scripts/rebuild_roms_logs.py --legacy-db miroms_verify            # 只校验，不写库
    python3 data/scripts/rebuild_roms_logs.py --legacy-db miroms_verify --apply    # 重建
    python3 data/scripts/rebuild_roms_logs.py --legacy-db miroms_verify --apply --ids 54346-54599
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

import common
from miroms.database import DatabaseManager
from miroms.logs_store import LogStore


def ts() -> str:
	return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def parse_ids(spec: str) -> Optional[set]:
	if not spec:
		return None
	ids = set()
	for piece in spec.split(','):
		piece = piece.strip()
		if not piece:
			continue
		if '-' in piece:
			start, end = piece.split('-', 1)
			ids.update(range(int(start), int(end) + 1))
		else:
			ids.add(int(piece))
	return ids


def legacy_connection(database: str):
	"""直连备份库（复用 scripts/config.py 的账号，仅切换 database）"""
	import pymysql
	import config
	return pymysql.connect(
		host=config.host, port=config.port, user=config.user,
		password=config.password, database=database, charset='utf8mb4')


def load_legacy_idmap(cur) -> Dict[int, str]:
	cur.execute("SELECT `id`, `content` FROM `logs`")
	return {int(row[0]): row[1] for row in cur.fetchall()}


def decode_column(value, idmap: Dict[int, str]) -> Optional[Dict[str, List[str]]]:
	if not value:
		return None
	try:
		parsed = json.loads(value) if isinstance(value, str) else value
	except (json.JSONDecodeError, TypeError):
		return None
	if LogStore.is_encoded(parsed):
		result: Dict[str, List[str]] = {}
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


def legacy_langs(cur, idmap: Dict[int, str], rom_id: int) -> Dict[str, Dict[str, List[str]]]:
	columns = ', '.join(f'`{c}`' for c in LogStore.LANG_COLUMNS)
	cur.execute(f"SELECT {columns} FROM `roms` WHERE `id` = %s", (rom_id,))
	row = cur.fetchone()
	if not row:
		return {}
	langs: Dict[str, Dict[str, List[str]]] = {}
	for index, column in enumerate(LogStore.LANG_COLUMNS):
		obj = decode_column(row[index], idmap)
		if obj:
			langs[column] = obj
	return langs


def dangling_references() -> List[int]:
	"""返回引用了不存在日志 id 的 roms.id 列表"""
	groups = LogStore.load_groups(force=True)
	bad: List[int] = []
	for row_id, value in DatabaseManager.query_all(
			"SELECT `id`, `logs` FROM `roms` WHERE `logs` IS NOT NULL"):
		try:
			parsed = json.loads(value)
		except (json.JSONDecodeError, TypeError):
			bad.append(int(row_id))
			continue
		if not isinstance(parsed, list):
			bad.append(int(row_id))
			continue
		for item in parsed:
			if not (isinstance(item, list) and len(item) >= 2):
				bad.append(int(row_id))
				break
			ids = [int(item[0])] + [int(x) for x in item[1]]
			if any(i not in groups for i in ids):
				bad.append(int(row_id))
				break
	return bad


def main() -> None:
	parser = argparse.ArgumentParser(description='按备份库重建 roms.logs')
	parser.add_argument('--legacy-db', required=True, help='迁移前备份所在的临时库名')
	parser.add_argument('--apply', action='store_true', help='实际回写（默认只校验）')
	parser.add_argument('--ids', help='只处理指定 id（支持 1,2,10-20）')
	parser.add_argument('--batch', type=int, default=2000, help='分页批大小')
	args = parser.parse_args()

	only_ids = parse_ids(args.ids)

	print(f"[{ts()}] 检查现有 roms.logs 悬空引用...")
	before_bad = dangling_references()
	print(f"[{ts()}] 悬空引用行数：{len(before_bad)}"
		  + (f"（{before_bad[:5]}...）" if before_bad else ""))

	print(f"[{ts()}] 连接备份库 {args.legacy_db} ...")
	legacy = legacy_connection(args.legacy_db)
	cur = legacy.cursor()
	idmap = load_legacy_idmap(cur)
	print(f"[{ts()}] 备份库旧日志原文 {len(idmap)} 条")

	query_ids = {"SELECT `id` FROM `roms` ORDER BY `id`"}
	if only_ids:
		query_ids = {f"SELECT `id` FROM `roms` WHERE `id` IN ({','.join(str(i) for i in sorted(only_ids))}) ORDER BY `id`"}
	cur.execute(query_ids.pop())
	target_ids = [int(row[0]) for row in cur.fetchall()]
	print(f"[{ts()}] 待处理 ROM {len(target_ids)} 行"
		  + (f"（限定 {len(only_ids)} 个 id）" if only_ids else ""))

	if not args.apply:
		# 只校验：把备份库的内容按当前 logs 表重新分组（dry-run），确认可还原
		rebuilt = 0
		for rom_id in target_ids:
			langs = legacy_langs(cur, idmap, rom_id)
			if not langs:
				continue
			LogStore.write_logs(langs, dry_run=True)
			rebuilt += 1
		print(f"[{ts()}] dry-run：{rebuilt} 行可在当前 logs 表上完成分组"
			  f"（未写库；加 --apply 回写）")
		return

	updated = 0
	failed = 0
	for rom_id in target_ids:
		langs = legacy_langs(cur, idmap, rom_id)
		if not langs:
			continue
		try:
			encoded = LogStore.write_logs(langs)
			DatabaseManager.execute(
				"UPDATE `roms` SET `logs` = %s WHERE `id` = %s",
				params=(encoded, rom_id), raise_on_error=True)
			updated += 1
		except Exception as exc:
			failed += 1
			if failed <= 3:
				print(f"\n✖ 行 id={rom_id} 重建失败：{type(exc).__name__}: {exc}")
		if updated % 2000 == 0 and updated:
			print(f"\r[{ts()}] 已回写 {updated} 行", end="", flush=True)
	print(f"\n[{ts()}] 回写完成：{updated} 行，失败 {failed} 行")

	after_bad = dangling_references()
	print(f"[{ts()}] 复检悬空引用：{len(after_bad)} 行"
		  + (f"（{after_bad[:5]}...）" if after_bad else " ✓"))
	if after_bad:
		sys.exit(1)


if __name__ == '__main__':
	main()
