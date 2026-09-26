"""
migrate_logs_ids.py - 将 roms 表 logs_* 列的原文 JSON 迁移为 logs 表 ID 引用结构

背景：logs_* 列原格式 {"模块": ["条目", ...]} 在多设备/多版本间大量重复
（模块名 ~370x、条目 ~66x 重复）。迁移后列内容为 [[模块ID, [条目ID, ...]], ...]，
模块与条目原文存入 logs 表（按 (type, md5(content)) 去重）。

用法：
    python3 data/scripts/migrate_logs_ids.py              # 全量迁移
    python3 data/scripts/migrate_logs_ids.py --dry-run    # 只统计，不写库
    python3 data/scripts/migrate_logs_ids.py --batch 500 --max-id 47000

幂等：已是 ID 结构的列自动跳过，可安全重复执行。
"""
import argparse
import json
import sys
from datetime import datetime

import common
from miroms.logs_store import LogStore

COLUMNS = list(common.CHANGELOG_COLUMNS)


def ts() -> str:
	return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def scan_batch(last_id: int, batch: int, max_id: int) -> list:
	"""按键集分页读取一批 roms 的日志列"""
	sql = f"SELECT id, {', '.join(COLUMNS)} FROM roms WHERE id > %s"
	params: list = [last_id]
	if max_id:
		sql += " AND id <= %s"
		params.append(max_id)
	sql += " ORDER BY id LIMIT %s"
	params.append(batch)
	return common.DatabaseManager.query_all(sql, params=tuple(params))


def collect_pass(batch: int, max_id: int) -> tuple:
	"""第一遍：收集全部唯一 (type, content)，并统计待迁移行数"""
	uniques: set = set()
	rows_pending = 0
	rows_done = 0
	skipped_values = 0
	last_id = 0
	while True:
		rows = scan_batch(last_id, batch, max_id)
		if not rows:
			break
		last_id = rows[-1][0]
		for row in rows:
				row_old = False
				for value in row[1:]:
						if not value:
								continue
						try:
								parsed = json.loads(value)
						except (json.JSONDecodeError, TypeError):
								skipped_values += 1
								continue
						if LogStore.is_encoded(parsed):
								continue
						if not isinstance(parsed, dict) or not parsed:
								skipped_values += 1
								continue
						row_old = True
						for module, lines in parsed.items():
								if not isinstance(module, str) or not module:
										continue
								uniques.add((LogStore.TYPE_MODULE, module))
								if not isinstance(lines, list):
										lines = [lines]
								for line in lines:
										uniques.add((LogStore.TYPE_LOG, str(line)))
				if row_old:
						rows_pending += 1
				else:
						rows_done += 1
		print(f"\r[{ts()}] 扫描中 id<={last_id}，待迁移 {rows_pending} 行，唯一内容 {len(uniques)} 条",
					end="", flush=True)
	print()
	return uniques, rows_pending, rows_done, skipped_values


def rewrite_pass(batch: int, max_id: int, dry_run: bool) -> tuple:
	"""第二遍：逐行把旧格式列重写为 ID 结构"""
	updated_rows = 0
	updated_cols = 0
	failed = 0
	last_id = 0
	while True:
		rows = scan_batch(last_id, batch, max_id)
		if not rows:
			break
		last_id = rows[-1][0]
		for row in rows:
				sets: list = []
				params: list = []
				for column, value in zip(COLUMNS, row[1:]):
						if not value:
								continue
						try:
								parsed = json.loads(value)
						except (json.JSONDecodeError, TypeError):
								continue
						if LogStore.is_encoded(parsed) or not isinstance(parsed, dict) or not parsed:
								continue
						sets.append(f"{column} = %s")
						params.append(LogStore.encode(parsed))
				if not sets:
						continue
				if dry_run:
						updated_rows += 1
						updated_cols += len(sets)
						continue
				try:
						common.DatabaseManager.execute(
								f"UPDATE roms SET {', '.join(sets)} WHERE id = %s",
								params=tuple(params + [row[0]]),
								raise_on_error=True,
						)
						updated_rows += 1
						updated_cols += len(sets)
				except Exception as exc:
						failed += 1
						if failed <= 3:
								print(f"\n✖ 行 id={row[0]} 回写失败：{type(exc).__name__}: {exc}")
		print(f"\r[{ts()}] 回写中 id<={last_id}，已更新 {updated_rows} 行（{updated_cols} 列）",
					end="", flush=True)
	print()
	return updated_rows, updated_cols, failed


def main() -> None:
	parser = argparse.ArgumentParser(description="roms.logs_* 列迁移为 logs 表 ID 引用结构")
	parser.add_argument("--dry-run", action="store_true", help="只统计，不写库")
	parser.add_argument("--batch", type=int, default=1000, help="分页批大小（默认 1000）")
	parser.add_argument("--max-id", type=int, default=0, help="只处理 id <= 该值的行（0 为全部）")
	args = parser.parse_args()

	LogStore.ensure_table()
	print(f"[{ts()}] logs 表就绪，开始第一遍扫描...")
	uniques, rows_pending, rows_done, skipped = collect_pass(args.batch, args.max_id)
	print(f"[{ts()}] 扫描完成：待迁移 {rows_pending} 行，已是新结构/空 {rows_done} 行，"
				f"异常值跳过 {skipped} 个，唯一内容 {len(uniques)} 条")

	if not uniques:
		print("没有需要迁移的内容。")
		return

	if args.dry_run:
		modules = sum(1 for t, _ in uniques if t == LogStore.TYPE_MODULE)
		print(f"[dry-run] 将写入 logs 表：模块 {modules} 条、条目 {len(uniques) - modules} 条；"
					f"随后回写 {rows_pending} 行。")
		return

	print(f"[{ts()}] 批量写入 logs 表...")
	inserted = LogStore.bulk_prime(uniques)
	print(f"[{ts()}] logs 表新增约 {inserted} 条，开始回写 roms...")

	updated_rows, updated_cols, failed = rewrite_pass(args.batch, args.max_id, args.dry_run)
	print(f"[{ts()}] 迁移完成：回写 {updated_rows} 行（{updated_cols} 列），失败 {failed} 行。")
	if failed:
		sys.exit(1)


if __name__ == "__main__":
	main()
