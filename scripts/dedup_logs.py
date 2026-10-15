"""
dedup_logs.py - 合并 logs 表中「同一日志」的重复行

背景：logs 表按内容跨 ROM 复用分组，但历史上写入侧只按 content_hash 找候选行，
当同一条日志的两行主内容不同（例如 #25 content=相册、#27 content=Gallery，其实是
同一个「相册 / Gallery」模块）时就永远匹配不上，于是同一日志被拆成多行。

本脚本把「类型相同、各语言文本互不冲突、且至少共享一门语言文本」的行合并为一行：
  * 代表行取语言覆盖最全（其次 id 最小）的那一行；
  * 各语言文本取并集，content 按「中文 > 英文 > 任一」重建，content_hash 同步刷新；
  * 同步重写 roms.logs / dev.logs 里的 ID 引用（[[模块ID,[条目ID,...],掩码],...]）；
  * 语言掩码保持不变，因此各 ROM 的导出结果与合并前逐字一致。

用法：
    python3 data/scripts/dedup_logs.py              # 只统计并打印样本（默认 dry-run）
    python3 data/scripts/dedup_logs.py --apply      # 实际合并
    python3 data/scripts/dedup_logs.py --apply --batch 500
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))

import common
from miroms.database import DatabaseManager
from miroms.logs_store import LogStore

REFERENCE_TABLES = ('roms', 'dev')


def ts() -> str:
	return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# ==================== 载入 ====================


def load_rows() -> Dict[int, Dict[str, Any]]:
	columns = ', '.join(f'`{c}`' for c in LogStore.LANG_COLUMNS)
	rows = DatabaseManager.query_all(
		f"SELECT `id`, `type`, `content`, {columns} FROM `logs`")
	result: Dict[int, Dict[str, Any]] = {}
	for row in rows or []:
		texts = {column: row[3 + i] for i, column in enumerate(LogStore.LANG_COLUMNS) if row[3 + i]}
		result[int(row[0])] = {'type': row[1], 'content': row[2], 'texts': texts}
	return result


def build_buckets(rows: Dict[int, Dict[str, Any]]) -> Dict[Tuple[str, str, str], List[int]]:
	"""按 (类型, 语言列, 文本) 建桶：桶内任意两行都共享同一门语言的同一段文本"""
	buckets: Dict[Tuple[str, str, str], List[int]] = defaultdict(list)
	for group_id, row in rows.items():
		for column, value in row['texts'].items():
			buckets[(row['type'], column, value)].append(group_id)
	return buckets


def compatible(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
	if left['type'] != right['type']:
		return False
	for column in LogStore.LANG_COLUMNS:
		a, b = left['texts'].get(column), right['texts'].get(column)
		if a and b and a != b:
			return False
	return True


def union_groups(rows: Dict[int, Dict[str, Any]]) -> Dict[int, int]:
	"""返回 {id: 代表 id}（未合并的行指向自身）"""
	parent = {group_id: group_id for group_id in rows}
	texts: Dict[int, Dict[str, str]] = {group_id: dict(row['texts']) for group_id, row in rows.items()}

	def find(node: int) -> int:
		while parent[node] != node:
			parent[node] = parent[parent[node]]
			node = parent[node]
		return node

	def compatible_with(root: int, other: int) -> bool:
		if rows[root]['type'] != rows[other]['type']:
			return False
		for column in LogStore.LANG_COLUMNS:
			a, b = texts[root].get(column), texts[other].get(column)
			if a and b and a != b:
				return False
		return True

	buckets = build_buckets(rows)
	# 反复扫描直到不再产生合并：一次扫描可能因合并改变根节点而漏掉传递关系
	while True:
		merged_any = False
		for key, members in buckets.items():
			if len(members) < 2:
				continue
			roots = []
			for member in members:
				root = find(member)
				if root not in roots:
					roots.append(root)
			if len(roots) < 2:
				continue
			base = roots[0]
			for other in roots[1:]:
				base_root = find(base)
				other_root = find(other)
				if base_root == other_root:
					continue
				if not compatible_with(base_root, other_root):
					continue
				parent[other_root] = base_root
				merged = dict(texts[other_root])
				merged.update(texts[base_root])
				texts[base_root] = merged
				merged_any = True
		if not merged_any:
			break

	return {group_id: find(group_id) for group_id in rows}


# ==================== 计划 ====================


def build_plan(rows: Dict[int, Dict[str, Any]]) -> Tuple[Dict[int, int], Dict[int, Dict[str, Any]]]:
	"""返回 (old_id -> 代表 id, 代表 row -> 合并后的行)

	代表行取「语言覆盖最全，其次 id 最小」的那一行。
	"""
	root_of = union_groups(rows)
	members: Dict[int, List[int]] = defaultdict(list)
	for group_id, root in root_of.items():
		members[root].append(group_id)

	mapping: Dict[int, int] = {}
	merged_rows: Dict[int, Dict[str, Any]] = {}
	for root, ids in members.items():
		if len(ids) == 1:
			mapping[ids[0]] = ids[0]
			continue
		ordered = sorted(ids, key=lambda gid: (-len(rows[gid]['texts']), gid))
		representative = ordered[0]
		texts: Dict[str, str] = {}
		for gid in reversed(ordered):  # 语言多的先写入，冲突时以覆盖更全的为准
			for column, value in rows[gid]['texts'].items():
				if not texts.get(column):
					texts[column] = value
		content = LogStore._primary(texts)
		merged_rows[representative] = {
			'type': rows[representative]['type'],
			'content': content,
			'texts': texts,
		}
		for gid in ids:
			mapping[gid] = representative
	return mapping, merged_rows


def remap_structure(value: Optional[str], mapping: Dict[int, int]) -> Optional[str]:
	"""重写 [[模块ID,[条目ID,...],掩码],...] 里的 ID；无变化时返回 None"""
	if not value:
		return None
	try:
		parsed = json.loads(value)
	except (json.JSONDecodeError, TypeError):
		return None
	if not isinstance(parsed, list):
		return None
	changed = False
	output = []
	for item in parsed:
		if not (isinstance(item, list) and len(item) >= 2):
			output.append(item)
			continue
		module_id = int(item[0])
		new_module = mapping.get(module_id, module_id)
		entry_ids = []
		for entry_id in item[1]:
			new_entry = mapping.get(int(entry_id), int(entry_id))
			entry_ids.append(new_entry)
		new_item = [new_module, entry_ids] + list(item[2:])
		if new_module != module_id or entry_ids != list(item[1]):
			changed = True
		output.append(new_item)
	return json.dumps(output, ensure_ascii=False) if changed else None


# ==================== 执行 ====================


def referenced_ids(batch: int = 500) -> set:
	"""扫描 roms.logs / dev.logs，收集被引用的日志 id"""
	used = set()
	for table in REFERENCE_TABLES:
		last_id = 0
		while True:
			rows = DatabaseManager.query_all(
				f"SELECT `id`, `logs` FROM `{table}` WHERE `id` > %s AND `logs` IS NOT NULL "
				f"ORDER BY `id` LIMIT %s", params=(last_id, batch))
			if not rows:
				break
			last_id = rows[-1][0]
			for _, value in rows:
				try:
					parsed = json.loads(value)
				except (json.JSONDecodeError, TypeError):
					continue
				if not isinstance(parsed, list):
					continue
				for item in parsed:
					if not (isinstance(item, list) and len(item) >= 2):
						continue
					used.add(int(item[0]))
					for entry_id in item[1]:
						used.add(int(entry_id))
	return used


def prune_unused(batch: int = 500) -> int:
	"""删除没有任何 ROM / 开发版周报引用的日志行（例如解析器修好后遗留的脏数据）"""
	used = referenced_ids(batch)
	rows = DatabaseManager.query_all("SELECT `id` FROM `logs`")
	dead = [int(row[0]) for row in rows or [] if int(row[0]) not in used]
	for i in range(0, len(dead), batch):
		chunk = dead[i:i + batch]
		DatabaseManager.execute(
			f"DELETE FROM `logs` WHERE `id` IN ({','.join(['%s'] * len(chunk))})",
			params=tuple(chunk), raise_on_error=True)
	if dead:
		LogStore.refresh_cache()
	return len(dead)


def apply_plan(mapping: Dict[int, int], merged_rows: Dict[int, Dict[str, Any]],
			   batch: int = 500) -> Dict[str, int]:
	stats = {'updated_groups': 0, 'deleted_groups': 0, 'updated_roms': 0, 'updated_dev': 0}

	# 1) 代表行：刷新 content / content_hash / 各语言文本
	columns = ['`content`', '`content_hash`'] + [f'`{c}`' for c in LogStore.LANG_COLUMNS]
	for representative, row in merged_rows.items():
		params: List[Any] = [row['content'], LogStore._hash(row['content'])]
		params.extend([row['texts'].get(c) or None for c in LogStore.LANG_COLUMNS])
		DatabaseManager.execute(
			f"UPDATE `logs` SET {', '.join(c + ' = %s' for c in columns)} WHERE `id` = %s",
			params=tuple(params + [representative]), raise_on_error=True,
		)
		stats['updated_groups'] += 1

	# 2) 重写引用
	for table in REFERENCE_TABLES:
		last_id = 0
		while True:
			rows = DatabaseManager.query_all(
				f"SELECT `id`, `logs` FROM `{table}` WHERE `id` > %s AND `logs` IS NOT NULL "
				f"ORDER BY `id` LIMIT %s",
				params=(last_id, batch))
			if not rows:
				break
			last_id = rows[-1][0]
			updates = []
			for row_id, value in rows:
				remapped = remap_structure(value, mapping)
				if remapped is not None:
					updates.append((remapped, row_id))
			if updates:
				DatabaseManager.execute_many(
					f"UPDATE `{table}` SET `logs` = %s WHERE `id` = %s", updates, raise_on_error=True)
				stats['updated_roms' if table == 'roms' else 'updated_dev'] += len(updates)
			print(f"\r[{ts()}] 重写 {table} 引用 id<={last_id}：已更新 "
				  f"{stats['updated_roms'] if table == 'roms' else stats['updated_dev']} 行",
				  end="", flush=True)
		print()

	# 3) 删除被合并掉的行
	dead = [gid for gid, representative in mapping.items() if representative != gid]
	for i in range(0, len(dead), batch):
		chunk = dead[i:i + batch]
		DatabaseManager.execute(
			f"DELETE FROM `logs` WHERE `id` IN ({','.join(['%s'] * len(chunk))})",
			params=tuple(chunk), raise_on_error=True)
		stats['deleted_groups'] += len(chunk)

	LogStore.refresh_cache()
	return stats


def main() -> None:
	parser = argparse.ArgumentParser(description='合并 logs 表中同一日志的重复行')
	parser.add_argument('--apply', action='store_true', help='实际合并（默认只统计）')
	parser.add_argument('--batch', type=int, default=500, help='分页批大小（默认 500）')
	parser.add_argument('--samples', type=int, default=5, help='打印多少组样本')
	parser.add_argument('--prune-unused', action='store_true',
						help='同时删除没有被任何 ROM / 开发版周报引用的日志行')
	args = parser.parse_args()

	print(f"[{ts()}] 载入 logs 表...")
	rows = load_rows()
	print(f"[{ts()}] 共 {len(rows)} 行，正在计算可合并分组...")
	mapping, merged_rows = build_plan(rows)

	groups = Counter(mapping.values())
	duplicate_groups = {root: size for root, size in groups.items() if size > 1}
	removable = sum(size - 1 for size in duplicate_groups.values())
	print(f"[{ts()}] 重复分组 {len(duplicate_groups)} 组，涉及 {sum(duplicate_groups.values())} 行，"
		  f"合并后可减少 {removable} 行")

	for root, size in list(sorted(duplicate_groups.items(), key=lambda item: -item[1]))[:args.samples]:
		ids = [gid for gid, rep in mapping.items() if rep == root]
		print(f"\n--- 代表 #{root}（{size} 行合并）")
		for gid in sorted(ids):
			mark = '→' if gid == root else ' '
			print(f"  {mark} #{gid} content={rows[gid]['content'][:28]!r} "
				  f"语言={sorted(rows[gid]['texts'])}")

	if not removable:
		print(f"\n[{ts()}] 没有需要合并的重复行。")
		if args.prune_unused and args.apply:
			removed = prune_unused(args.batch)
			print(f"[{ts()}] 清理未被引用的日志行 {removed} 行，剩余 "
				  f"{len(load_rows())} 行")
		return

	if not args.apply:
		print(f"\n[{ts()}] dry-run 结束（未写库）。确认无误后加 --apply 执行合并。")
		return

	print(f"\n[{ts()}] 开始合并...")
	stats = apply_plan(mapping, merged_rows, args.batch)
	print(f"[{ts()}] 完成：刷新代表行 {stats['updated_groups']} 行，"
		  f"删除重复行 {stats['deleted_groups']} 行，"
		  f"重写 roms {stats['updated_roms']} 行 / dev {stats['updated_dev']} 行")

	after = load_rows()
	print(f"[{ts()}] 合并后 logs 表 {len(after)} 行"
		  f"（合并前 {len(rows)} 行，减少 {len(rows) - len(after)} 行）")

	remaining, _ = build_plan(after)
	left = Counter(remaining.values())
	left_dupes = sum(1 for size in left.values() if size > 1)
	print(f"[{ts()}] 复检：仍有重复分组 {left_dupes} 组")

	if args.prune_unused:
		removed = prune_unused(args.batch)
		print(f"[{ts()}] 清理未被引用的日志行 {removed} 行，剩余 {len(load_rows())} 行")
		after = load_rows()
		remaining, _ = build_plan(after)
		left = Counter(remaining.values())
		print(f"[{ts()}] 清理后复检：重复分组 "
			  f"{sum(1 for size in left.values() if size > 1)} 组")
	store_dupes = LogStore.duplicate_report()
	print(f"[{ts()}] LogStore.duplicate_report 复检：重复分组 {len(store_dupes)} 组")
	if store_dupes:
		sys.exit(1)


if __name__ == '__main__':
	main()
