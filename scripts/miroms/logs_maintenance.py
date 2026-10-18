"""
miroms.logs_maintenance - logs 表维护（去重 / 引用重写 / 内容一致性 / 语言掩码 / id 压缩）

背景：logs 表按内容跨 ROM 复用分组，roms / dev 只存 ID 引用结构，
所以任何「合并行、删行、压缩 id」的维护动作都必须同时改写引用与语言掩码。
这些操作原先散落在 dedup_logs.py / fix_non_zh_logs.py / resequence_ids.py 及若干一次性
脚本里，规则容易漂移；这里统一收敛成 LogMaintenance，脚本只负责参数解析与打印。

三类数据结构
------------
- rows：``{id: {'id', 'type', 'content', 'texts'}}``，texts 只含非空语言列（与 LogStore 一致）
- owners：``{(表名, 行 id): [[模块ID, [条目ID, ...], 掩码], ...]}``，只含合法的 ID 引用结构
- mapping：``{旧 id: 新 id}``，合并 / 压缩后用于重写引用

主要能力
--------
- 去重：``duplicate_plan``（以中文日志分桶 + 逐对兼容合并）→ ``apply_duplicates``
- 引用：``iter_refs`` / ``remap_structure`` / ``rewrite_refs``
- 内容：``content_issues`` / ``repair_content``（以 logs_zh 为准重建 content）
- 掩码：``mask_issues`` / ``fill_masks``（只增不减，新掩码 = 原掩码 | 公共语言掩码）
- id：``table_stats`` / ``id_gaps`` / ``auto_increment`` / ``fix_auto_increment`` / ``compact_ids``
- 清理：``prune_unused``（无人引用的行）/ ``prune_dangling``（指向已删除行的引用）
- 对比：``export_snapshot`` / ``compare_snapshots``（维护前后导出逐字对比，检测内容丢失）
- 体检：``audit``（重复 / 悬空引用 / 坏 JSON / 孤儿行 / 内容不一致 / 掩码 / id 空档）

典型用法：
    rows = LogMaintenance.load_rows()
    mapping, merged = LogMaintenance.duplicate_plan(rows)
    LogMaintenance.apply_duplicates(mapping, merged)
    LogMaintenance.fill_masks(apply=True)
    LogMaintenance.compact_ids(apply=True)
    before = LogMaintenance.export_snapshot()
    ...
    print(LogMaintenance.compare_snapshots(before, LogMaintenance.export_snapshot()))
    print(LogMaintenance.audit())
"""
import copy
import gzip
import json
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple

from miroms.database import DatabaseManager
from miroms.logs_store import LogStore
from miroms.logs_text import LogText

# 引用 logs.id 的表；重写引用、统计孤儿行都要覆盖这些表
REFERENCE_TABLES: Tuple[str, ...] = ('roms', 'dev')
# 压缩 id 时的临时偏移量（两段式更新，避免主键中途撞号）
ID_OFFSET = 1_000_000


class LogMaintenance:
	"""logs 表维护工具（全部为类方法，无需实例化）"""

	# ==================== 载入 ====================

	@classmethod
	def load_rows(cls) -> Dict[int, Dict[str, Any]]:
		"""载入 logs 全表：{id: {'id', 'type', 'content', 'texts'}}

		texts 只保留非空语言列；content 原样返回（不把 content 回填进 texts），
		这样「补中文」逻辑能区分「只有 content」和「logs_zh 已有中文」。
		"""
		columns = ', '.join(f'`{c}`' for c in LogStore.LANG_COLUMNS)
		rows = DatabaseManager.query_all(
			f"SELECT `id`, `type`, `content`, `proofed`, `complete`, `lang_issues`, {columns} "
			f"FROM `logs`") or []
		result: Dict[int, Dict[str, Any]] = {}
		for row in rows:
			texts = {column: row[6 + i] for i, column in enumerate(LogStore.LANG_COLUMNS)
					 if row[6 + i]}
			result[int(row[0])] = {
				'id': int(row[0]),
				'type': row[1],
				'content': row[2] or '',
				'proofed': bool(row[3]),
				'complete': bool(row[4]),
				'lang_issues': cls._parse_lang_issues(row[5]),
				'texts': texts,
			}
		return result

	@staticmethod
	def _parse_lang_issues(raw: Any) -> Dict[str, Any]:
		if not raw:
			return {}
		try:
			data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
		except (json.JSONDecodeError, TypeError):
			return {}
		return data if isinstance(data, dict) else {}

	@classmethod
	def record_lang_issues(cls, issues_by_id: Dict[int, Dict[str, Any]],
						   clear_ids: Sequence[int] = (), apply: bool = True) -> int:
		"""写入 / 清除语言不符标注；有标注的行会把 proofed 重置为 0

		- issues_by_id：{logs.id: {语言列: {detected, confidence, reason}}}
		- clear_ids：本次 AI 判为全部一致的行（清空旧标注，不动 proofed）
		"""
		valid: List[Tuple[str, int]] = []
		for row_id, issues in issues_by_id.items():
			clean = {column: detail for column, detail in (issues or {}).items()
					 if column in LogStore.LANG_COLUMNS}
			if clean:
				valid.append((json.dumps(clean, ensure_ascii=False), int(row_id)))
		clears = sorted({int(item) for item in clear_ids})
		if not apply:
			return len(valid) + len(clears)
		for index in range(0, len(valid), 200):
			DatabaseManager.execute_many(
				"UPDATE `logs` SET `lang_issues` = %s, `proofed` = 0, `complete` = 0 "
				"WHERE `id` = %s",
				valid[index:index + 200], raise_on_error=True)
		for index in range(0, len(clears), 500):
			chunk = clears[index:index + 500]
			DatabaseManager.execute(
				f"UPDATE `logs` SET `lang_issues` = NULL "
				f"WHERE `id` IN ({','.join(['%s'] * len(chunk))})",
				params=tuple(chunk), raise_on_error=True)
		return len(valid) + len(clears)

	@classmethod
	def mark_proofed(cls, ids: Sequence[int], value: bool = True, apply: bool = True) -> int:
		"""把一批 logs.id 的 proofed 标记为 True/False，返回处理的 id 数

		apply=False 时只返回将要处理的数量（不写库）。
		"""
		unique = sorted({int(item) for item in ids})
		if not unique:
			return 0
		if not apply:
			return len(unique)
		for index in range(0, len(unique), 500):
			chunk = unique[index:index + 500]
			if value:
				all_langs = ' AND '.join(
					f"`{column}` IS NOT NULL AND `{column}` <> ''"
					for column in LogStore.LANG_COLUMNS)
				DatabaseManager.execute(
					f"UPDATE `logs` SET `proofed` = 1, "
					f"`complete` = IF(({all_langs}), 1, 0) "
					f"WHERE `id` IN ({','.join(['%s'] * len(chunk))})",
					params=tuple(chunk), raise_on_error=True)
			else:
				DatabaseManager.execute(
					f"UPDATE `logs` SET `proofed` = 0, `complete` = 0 "
					f"WHERE `id` IN ({','.join(['%s'] * len(chunk))})",
					params=tuple(chunk), raise_on_error=True)
		return len(unique)

	@classmethod
	def scan_owners(cls, tables: Sequence[str] = REFERENCE_TABLES
					) -> Tuple[Dict[Tuple[str, int], List[Any]], int]:
		"""扫描引用表，返回 (合法引用结构, 无法解析的行数)

		只保留 ``[[模块ID, [条目ID, ...], 掩码?], ...]`` 这种 ID 结构；
		空值、坏 JSON、旧格式（多语言对象）都计入 bad，避免误改历史数据。
		"""
		owners: Dict[Tuple[str, int], List[Any]] = {}
		bad = 0
		for table in tables:
			rows = DatabaseManager.query_all(
				f"SELECT `id`, `logs` FROM `{table}` WHERE `logs` IS NOT NULL AND `logs` != ''"
			) or []
			for owner_id, value in rows:
				try:
					parsed = json.loads(value)
				except (json.JSONDecodeError, TypeError):
					bad += 1
					continue
				if LogStore.is_encoded(parsed):
					owners[(table, int(owner_id))] = parsed
				else:
					bad += 1
		return owners, bad

	@classmethod
	def load_owners(cls, tables: Sequence[str] = REFERENCE_TABLES
					) -> Dict[Tuple[str, int], List[Any]]:
		"""载入引用结构：{(表名, 行 id): refs}（只含合法 ID 结构）"""
		return cls.scan_owners(tables)[0]

	# ==================== 引用工具 ====================

	@staticmethod
	def iter_refs(refs: Any) -> Iterator[Tuple[int, List[int], int]]:
		"""遍历引用结构中的 (模块ID, [条目ID, ...], 掩码)

		跳过坏结构；缺掩码时返回 0（由调用方决定如何补）。
		"""
		for item in refs or []:
			if not (isinstance(item, list) and len(item) >= 2):
				continue
			try:
				module_id = int(item[0])
				entries = [int(x) for x in item[1]]
			except (TypeError, ValueError):
				continue
			mask = int(item[2]) if len(item) > 2 and isinstance(item[2], int) else 0
			yield module_id, entries, mask

	@classmethod
	def structure_ids(cls, refs: Any) -> Iterator[int]:
		"""引用结构涉及的全部 logs 行 id（模块 + 条目）"""
		for module_id, entries, _ in cls.iter_refs(refs):
			yield module_id
			yield from entries

	@classmethod
	def referenced_ids(cls, owners: Optional[Dict[Tuple[str, int], List[Any]]] = None) -> Set[int]:
		"""被任何 roms.logs / dev.logs 引用的 logs id 集合"""
		owners = owners if owners is not None else cls.load_owners()
		used: Set[int] = set()
		for refs in owners.values():
			used.update(cls.structure_ids(refs))
		return used

	@classmethod
	def remap_structure(cls, value: Any, mapping: Dict[int, int]) -> Optional[str]:
		"""重写 ``[[模块ID,[条目ID,...],掩码],...]`` 里的 ID；无变化时返回 None

		返回值是可直接写回列的 JSON 字符串，便于调用方判断「是否需要 UPDATE」。
		"""
		if not value or not mapping:
			return None
		try:
			parsed = json.loads(value) if isinstance(value, str) else value
		except (json.JSONDecodeError, TypeError):
			return None
		if not isinstance(parsed, list):
			return None
		changed = False
		output: List[Any] = []
		for item in parsed:
			if not (isinstance(item, list) and len(item) >= 2):
				output.append(item)
				continue
			try:
				module_id = int(item[0])
				entries = [int(x) for x in item[1]]
			except (TypeError, ValueError):
				output.append(item)
				continue
			new_module = mapping.get(module_id, module_id)
			new_entries = [mapping.get(entry_id, entry_id) for entry_id in entries]
			if new_module != module_id or new_entries != entries:
				changed = True
			output.append([new_module, new_entries] + list(item[2:]))
		return json.dumps(output, ensure_ascii=False) if changed else None

	@classmethod
	def rewrite_refs(cls, mapping: Dict[int, int],
					 tables: Sequence[str] = REFERENCE_TABLES,
					 batch: int = 500,
					 on_progress=None) -> Dict[str, int]:
		"""按 mapping 批量重写引用表里的 logs 引用，返回 {表名: 更新行数}

		mapping 为空时直接返回；只更新真正变了 id 的行（没变化的行不写库）。
		"""
		stats = {table: 0 for table in tables}
		if not mapping:
			return stats
		for table in tables:
			last_id = 0
			while True:
				rows = DatabaseManager.query_all(
					f"SELECT `id`, `logs` FROM `{table}` WHERE `id` > %s AND `logs` IS NOT NULL "
					f"ORDER BY `id` LIMIT %s", params=(last_id, batch)) or []
				if not rows:
					break
				last_id = int(rows[-1][0])
				updates = []
				for row_id, value in rows:
					remapped = cls.remap_structure(value, mapping)
					if remapped is not None:
						updates.append((remapped, row_id))
				if updates:
					DatabaseManager.execute_many(
						f"UPDATE `{table}` SET `logs` = %s WHERE `id` = %s",
						updates, raise_on_error=True)
					stats[table] += len(updates)
				if on_progress:
					on_progress(table, last_id, stats[table])
		if any(stats.values()):
			LogStore.refresh_cache()
		return stats

	@classmethod
	def prune_dangling(cls, rows: Optional[Dict[int, Dict[str, Any]]] = None,
					   apply: bool = False,
					   batch: int = 500,
					   backup: bool = True,
					   backup_path: Optional[str] = None) -> Dict[str, Any]:
		"""删除引用里指向已不存在 logs 行的模块 / 条目

		prune_unused 处理的是「没人引用」的行；这里处理相反方向：历史维护曾直接
		删行却没改写引用，留下指向不存在 id 的悬空位置。导出侧 build_localized
		本来就静默跳过这些 id，因此清理不改变现有导出内容，只是让引用结构与
		logs 表重新对齐。

		模块 id 不存在时删除整个位置；条目 id 不存在时只删除对应条目；
		位置被删空的 owner 写回 NULL。
		"""
		rows = rows if rows is not None else cls.load_rows()
		owners = cls.load_owners()
		stats: Dict[str, Any] = {
			'owners': 0,
			'positions': 0,
			'entries': 0,
			'owners_empty': 0,
			'missing_ids': 0,
			'refs': {table: 0 for table in REFERENCE_TABLES},
			'backup': None,
		}
		missing_ids: Set[int] = set()
		updates: Dict[str, List[Tuple[Optional[str], int]]] = {
			table: [] for table in REFERENCE_TABLES}
		for (table, owner_id), refs in owners.items():
			output: List[Any] = []
			dropped_positions = 0
			dropped_entries = 0
			for item in refs:
				if not (isinstance(item, list) and len(item) >= 2):
					output.append(item)
					continue
				try:
					module_id = int(item[0])
					entries = [int(x) for x in item[1]]
				except (TypeError, ValueError):
					output.append(item)
					continue
				if module_id not in rows:
					missing_ids.add(module_id)
					dropped_positions += 1
					continue
				kept: List[int] = []
				for entry_id in entries:
					if entry_id in rows:
						kept.append(entry_id)
					else:
						missing_ids.add(entry_id)
						dropped_entries += 1
				output.append([module_id, kept] + list(item[2:]))
			if not (dropped_positions or dropped_entries):
				continue
			stats['owners'] += 1
			stats['positions'] += dropped_positions
			stats['entries'] += dropped_entries
			if not output:
				stats['owners_empty'] += 1
			if apply and table in updates:
				updates[table].append((
					json.dumps(output, ensure_ascii=False) if output else None, owner_id))
		stats['missing_ids'] = len(missing_ids)
		if not apply or not stats['owners']:
			return stats
		if backup:
			stats['backup'] = cls.backup(backup_path)
		for table, items in updates.items():
			if table not in REFERENCE_TABLES:
				continue
			stats['refs'][table] = len(items)
			for index in range(0, len(items), batch):
				DatabaseManager.execute_many(
					f"UPDATE `{table}` SET `logs` = %s WHERE `id` = %s",
					items[index:index + batch], raise_on_error=True)
		LogStore.refresh_cache()
		return stats

	# ==================== 去重 ====================

	@classmethod
	def build_buckets(cls, rows: Dict[int, Dict[str, Any]]
					  ) -> Dict[Tuple[str, str, str], List[int]]:
		"""以中文日志为依据建桶：同类型且中文文本相同（归一化后）才可能是同一行

		中文取 logs_zh；缺失时回退 content（导出侧同样把 content 当作中文主内容）。
		其余语言不参与分桶，只在桶内的兼容性校验里看是否冲突，
		避免「中文不同但某门外语恰好相同」的行被误合并。
		"""
		buckets: Dict[Tuple[str, str, str], List[int]] = defaultdict(list)
		for group_id, row in rows.items():
			zh = LogStore.normalize(row['texts'].get(LogStore.ZH_COLUMN) or row['content'])
			if zh:
				buckets[(row['type'], LogStore.ZH_COLUMN, zh)].append(group_id)
		return buckets

	@classmethod
	def union_groups(cls, rows: Dict[int, Dict[str, Any]]) -> Dict[int, int]:
		"""返回 {id: 代表 id}（未合并的行指向自身）

		桶内**逐对**尝试合并：只跟首个基准行比，会把「与基准冲突、但彼此兼容」的行永久拆开。
		反复扫描直到不再产生合并，避免一次扫描因根节点变化而漏掉传递关系。
		"""
		parent = {group_id: group_id for group_id in rows}
		texts: Dict[int, Dict[str, str]] = {
			group_id: dict(row['texts']) for group_id, row in rows.items()}

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

		buckets = cls.build_buckets(rows)
		while True:
			merged_any = False
			for members in buckets.values():
				if len(members) < 2:
					continue
				while True:
					roots: List[int] = []
					for member in members:
						root = find(member)
						if root not in roots:
							roots.append(root)
					pair = None
					for i in range(len(roots)):
						for j in range(i + 1, len(roots)):
							if compatible_with(roots[i], roots[j]):
								pair = (roots[i], roots[j])
								break
						if pair:
							break
					if pair is None:
						break
					base_root, other_root = pair
					parent[other_root] = base_root
					merged = dict(texts[other_root])
					merged.update(texts[base_root])
					texts[base_root] = merged
					merged_any = True
			if not merged_any:
				break
		return {group_id: find(group_id) for group_id in rows}

	@classmethod
	def duplicate_plan(cls, rows: Optional[Dict[int, Dict[str, Any]]] = None
					   ) -> Tuple[Dict[int, int], Dict[int, Dict[str, Any]]]:
		"""返回 (old_id -> 代表 id, 代表 id -> 合并后的行)

		代表行取「语言覆盖最全，其次 id 最小」的那一行；
		各语言文本取并集，content 按「中文 > 英文 > 任一」重建。
		"""
		if rows is None:
			rows = cls.load_rows()
		root_of = cls.union_groups(rows)
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
			merged_rows[representative] = {
				'type': rows[representative]['type'],
				'content': LogStore.primary_text(texts),
				'texts': texts,
			}
			for gid in ids:
				mapping[gid] = representative
		return mapping, merged_rows

	@classmethod
	def apply_duplicates(cls, mapping: Dict[int, int], merged_rows: Dict[int, Dict[str, Any]],
						 batch: int = 500, on_progress=None) -> Dict[str, int]:
		"""执行合并计划：刷新代表行 → 重写引用 → 删除被合并的行

		整段在跨进程写锁内执行，避免与抓取脚本交错插入。
		"""
		stats = {'updated_groups': 0, 'deleted_groups': 0, 'updated_roms': 0, 'updated_dev': 0}
		columns = ['`content`', '`content_hash`'] + [f'`{c}`' for c in LogStore.LANG_COLUMNS]
		with LogStore.write_lock():
			for representative, row in merged_rows.items():
				params: List[Any] = [row['content'], LogStore.hash_text(row['content'])]
				params.extend([row['texts'].get(c) or None for c in LogStore.LANG_COLUMNS])
				DatabaseManager.execute(
					f"UPDATE `logs` SET {', '.join(c + ' = %s' for c in columns)}, "
					f"`proofed` = 0, `complete` = 0, `lang_issues` = NULL WHERE `id` = %s",
					params=tuple(params + [representative]), raise_on_error=True,
				)
				stats['updated_groups'] += 1

			ref_stats = cls.rewrite_refs(mapping, on_progress=on_progress)
			stats['updated_roms'] = ref_stats.get('roms', 0)
			stats['updated_dev'] = ref_stats.get('dev', 0)

			dead = [gid for gid, representative in mapping.items() if representative != gid]
			for i in range(0, len(dead), batch):
				chunk = dead[i:i + batch]
				DatabaseManager.execute(
					f"DELETE FROM `logs` WHERE `id` IN ({','.join(['%s'] * len(chunk))})",
					params=tuple(chunk), raise_on_error=True)
				stats['deleted_groups'] += len(chunk)
		LogStore.refresh_cache()
		return stats

	@classmethod
	def fallback_columns(cls, row: Dict[str, Any]) -> Set[str]:
		"""返回「值等于本行 logs_en」的非英文语言列

		这类值通常不是真实译文，而是接口按英文回落写进来的副本
		（例如 id=1 的 de/ug/bo 都是 'Other'）。合并时它们不应与
		「Sonstiges / ئۈسكۈنە ...」这类真实译文视为冲突。
		"""
		en = LogStore.normalize(row['texts'].get(LogStore.EN_COLUMN))
		if not en:
			return set()
		return {column for column, value in row['texts'].items()
				if column != LogStore.EN_COLUMN and LogStore.normalize(value) == en}

	@classmethod
	def merge_groups(cls, groups: Sequence[Sequence[int]],
					 rows: Optional[Dict[int, Dict[str, Any]]] = None,
					 apply: bool = False, backup: bool = True,
					 backup_path: Optional[str] = None) -> Dict[str, Any]:
		"""按显式给定的分组合并日志行（真实译文优先，英文回落只在没有真实译文时保留）

		适用于自动去重无法判定的场景：两行中文相同、一方只有英文回落、另一方有真实译文
		（如 `id=1` 的 de='Other' 与 `id=11040` 的 de='Sonstiges'），
		严格规则会把回落值当冲突而漏合并；这里由调用方确认「它们是同一日志」。

		代表行取「真实译文最多，其次语言最多，最后 id 最小」的一行；
		引用按 representative 重写，被合并的行删除。
		"""
		rows = rows if rows is not None else cls.load_rows()
		mapping: Dict[int, int] = {}
		merged_rows: Dict[int, Dict[str, Any]] = {}
		groups_out: List[Dict[str, Any]] = []
		for group in groups:
			ids = sorted({int(item) for item in group if int(item) in rows})
			if len(ids) < 2:
				continue
			ordered = sorted(ids, key=lambda gid: (
				-(len(rows[gid]['texts']) - len(cls.fallback_columns(rows[gid]))),
				-len(rows[gid]['texts']), gid))
			representative = ordered[0]
			texts: Dict[str, str] = {}
			# 先收真实译文，再用英文回落补空缺（不覆盖真实译文）
			for gid in ordered:
				fallback = cls.fallback_columns(rows[gid])
				for column, value in rows[gid]['texts'].items():
					if column not in fallback:
						texts.setdefault(column, value)
			for gid in ordered:
				for column, value in rows[gid]['texts'].items():
					texts.setdefault(column, value)
			merged_rows[representative] = {
				'type': rows[representative]['type'],
				'content': LogStore.primary_text(texts),
				'texts': texts,
			}
			for gid in ids:
				mapping[gid] = representative
			groups_out.append({'ids': ids, 'representative': representative,
							   'content': merged_rows[representative]['content'],
							   'texts': texts})
		result: Dict[str, Any] = {
			'applied': False, 'groups': groups_out, 'mapping': mapping,
			'merged_rows': merged_rows, 'stats': {}, 'backup': None,
		}
		if not merged_rows:
			return result
		if not apply:
			return result
		if backup:
			result['backup'] = cls.backup(backup_path)
		result['stats'] = cls.apply_duplicates(mapping, merged_rows)
		result['applied'] = True
		return result

	# ==================== 内容一致性 ====================

	@classmethod
	def content_issues(cls, rows: Optional[Dict[int, Dict[str, Any]]] = None
					   ) -> List[Dict[str, Any]]:
		"""找出 content 与 logs_zh 不一致 / 不是简体中文的行

		判定顺序（reason）：
		- ``empty``：content 为空
		- ``content_differs``：两边都是可用中文但不一致（以 logs_zh 为准）
		- ``content_not_zh``：logs_zh 可用，但 content 是外文
		- ``zh_missing``：logs_zh 不可用，但 content 本身是简体中文
		- ``no_zh``：两边都没有可用简体中文（交给补译脚本）
		"""
		rows = rows if rows is not None else cls.load_rows()
		issues: List[Dict[str, Any]] = []
		for row_id, row in rows.items():
			content = LogStore.normalize(row['content'])
			zh = LogStore.normalize(row['texts'].get(LogStore.ZH_COLUMN))
			zh_ok = LogText.is_chinese(zh)
			content_ok = LogText.is_chinese(content) and LogText.looks_simplified(content, row['texts'])
			if not content:
				reason = 'empty'
			elif zh_ok and content != zh:
				reason = 'content_not_zh' if not content_ok else 'content_differs'
			elif not zh_ok and content_ok:
				reason = 'zh_missing'
			elif not zh_ok:
				reason = 'no_zh'
			else:
				continue
			issues.append({
				'id': row_id,
				'type': row['type'],
				'content': content,
				'logs_zh': zh,
				'reason': reason,
				'languages': [c for c in LogStore.LANG_COLUMNS if row['texts'].get(c)],
			})
		return issues

	@classmethod
	def stale_hashes(cls, rows: Optional[Dict[int, Dict[str, Any]]] = None) -> List[int]:
		"""content_hash 与 md5(content) 不一致的行 id（SQL 侧无法直接算，需逐行校验）"""
		rows = rows if rows is not None else cls.load_rows()
		hashes = {int(row[0]): row[1] for row in DatabaseManager.query_all(
			"SELECT `id`, `content_hash` FROM `logs`") or []}
		return [row_id for row_id, row in rows.items()
				if hashes.get(row_id) != LogStore.hash_text(row['content'])]

	@classmethod
	def repair_content(cls, rows: Optional[Dict[int, Dict[str, Any]]] = None,
					   apply: bool = False, batch: int = 500) -> Dict[str, Any]:
		"""以 logs_zh 为准重建 content / content_hash，并回填「只有 content 有中文」的行

		- 可用中文的 logs_zh 与 content 不一致 → content := logs_zh（同步 hash）
		- logs_zh 不可用但 content 是简体中文 → logs_zh := content
		- 其余（no_zh / empty）不动，报告里列出
		"""
		rows = rows if rows is not None else cls.load_rows()
		issues = cls.content_issues(rows)
		content_updates: List[Tuple[str, str, int]] = []
		zh_updates: List[Tuple[str, int]] = []
		unresolved: List[Dict[str, Any]] = []
		for issue in issues:
			row_id = issue['id']
			if issue['reason'] in ('content_differs', 'content_not_zh'):
				zh = issue['logs_zh']
				content_updates.append((zh, LogStore.hash_text(zh), row_id))
			elif issue['reason'] == 'zh_missing':
				zh_updates.append((issue['content'], row_id))
			else:
				unresolved.append(issue)
		result = {
			'applied': apply,
			'candidates': len(issues),
			'content_updates': len(content_updates),
			'zh_updates': len(zh_updates),
			'unresolved': len(unresolved),
			'by_reason': _count_by(issues, 'reason'),
			'samples': [issue for issue in issues if issue['reason'] != 'no_zh'][:5],
			'unresolved_samples': unresolved[:5],
		}
		if not apply:
			return result
		if content_updates:
			for i in range(0, len(content_updates), batch):
				DatabaseManager.execute_many(
					"UPDATE `logs` SET `content` = %s, `content_hash` = %s, `proofed` = 0, "
					"`complete` = 0, `lang_issues` = NULL WHERE `id` = %s",
					content_updates[i:i + batch], raise_on_error=True)
		if zh_updates:
			for i in range(0, len(zh_updates), batch):
				DatabaseManager.execute_many(
					"UPDATE `logs` SET `logs_zh` = %s, `proofed` = 0, `complete` = 0, "
					"`lang_issues` = NULL WHERE `id` = %s",
					zh_updates[i:i + batch], raise_on_error=True)
		if content_updates or zh_updates:
			LogStore.refresh_cache()
		return result

	# ==================== 语言掩码 ====================

	@classmethod
	def mask_issues(cls, rows: Optional[Dict[int, Dict[str, Any]]] = None,
					owners: Optional[Dict[Tuple[str, int], List[Any]]] = None
					) -> Dict[str, List[Dict[str, Any]]]:
		"""检查引用结构里的悬空 id、可补语言位、无效语言位

		- ``dangling``：引用了 logs 表里不存在的 id（合并 / 删行后的悬空引用）
		- ``extendable``：模块与全部条目都有某门语言，但掩码没声明该语言
		  （导出侧会因此漏掉这门语言；补法：新掩码 = 原掩码 | 公共语言掩码）
		- ``invalid``：掩码声明了某门语言，但模块行没有该语言文本（导出时该位无意义）
		"""
		rows = rows if rows is not None else cls.load_rows()
		owners = owners if owners is not None else cls.load_owners()
		result: Dict[str, List[Dict[str, Any]]] = {
			'dangling': [], 'extendable': [], 'invalid': []}
		for (table, owner_id), refs in owners.items():
			# 本 ROM / 开发版自己声明过的语言并集；补位不得越过它
			# （行池里的行可能被别的 ROM 补齐了全部译文，越界补位会把别人的语言写进掩码）
			owner_mask = 0
			for item in refs:
				if isinstance(item, list) and len(item) > 2 and isinstance(item[2], int):
					owner_mask |= int(item[2])
			for position, item in enumerate(refs):
				if not (isinstance(item, list) and len(item) >= 2):
					continue
				try:
					module_id = int(item[0])
					entries = [int(x) for x in item[1]]
				except (TypeError, ValueError):
					continue
				mask = int(item[2]) if len(item) > 2 and isinstance(item[2], int) else None
				missing = [row_id for row_id in [module_id] + entries if row_id not in rows]
				if missing:
					result['dangling'].append({
						'table': table, 'id': owner_id, 'position': position, 'missing': missing})
					continue
				module = rows[module_id]
				module_mask = LogStore.mask_of(module['texts'])
				# 缺掩码时导出侧按「模块行有的语言」输出，这里沿用同一口径，避免误判可补位
				effective = module_mask if mask is None else mask
				common: Set[str] = set(module['texts'])
				for entry_id in entries:
					common &= set(rows[entry_id]['texts'])
				common_mask = LogStore.mask_of(common)
				if owner_mask:
					common_mask &= owner_mask
				if common_mask & ~effective:
					result['extendable'].append({
						'table': table, 'id': owner_id, 'position': position,
						'old_mask': effective, 'new_mask': effective | common_mask,
						'added': LogStore.columns_of(common_mask & ~effective)})
				invalid = mask & ~module_mask if mask is not None else 0
				if invalid:
					result['invalid'].append({
						'table': table, 'id': owner_id, 'position': position,
						'mask': mask, 'bits': LogStore.columns_of(invalid)})
		return result

	@classmethod
	def refresh_complete(cls, apply: bool = False) -> Dict[str, Any]:
		"""按「全部语言列非空且 proofed=1」重算 complete"""
		all_langs = ' AND '.join(
			f"`{column}` IS NOT NULL AND `{column}` <> ''"
			for column in LogStore.LANG_COLUMNS)
		rows = DatabaseManager.query_all(
			f"SELECT `id`, `proofed`, `complete`, ({all_langs}) AS full FROM `logs`") or []
		should = {int(row[0]) for row in rows if int(row[1]) and int(row[3])}
		changed = [int(row[0]) for row in rows
				   if (int(row[2]) == 1) != (int(row[0]) in should)]
		result = {'should': len(should), 'changed': len(changed),
				  'applied': False, 'ids': sorted(changed)[:20]}
		if not apply:
			return result
		DatabaseManager.execute(
			f"UPDATE `logs` SET `complete` = IF(`proofed` = 1 AND ({all_langs}), 1, 0)",
			raise_on_error=True)
		result['applied'] = True
		return result

	@classmethod
	def clean_invalid_masks(cls, rows: Optional[Dict[int, Dict[str, Any]]] = None,
							owners: Optional[Dict[Tuple[str, int], List[Any]]] = None,
							apply: bool = False, batch: int = 500) -> Dict[str, Any]:
		"""清理引用掩码里「模块行已经没有该语言文本」的无效位（只删不加）

		典型场景：按 lang_issues 清空某语言列后，掩码仍声明该语言。
		只处理 module 行存在的引用；悬空引用跳过。
		"""
		rows = rows if rows is not None else cls.load_rows()
		owners = owners if owners is not None else cls.load_owners()
		updates: Dict[str, List[Tuple[str, int]]] = {table: [] for table in REFERENCE_TABLES}
		items = 0
		bits = 0
		for (table, owner_id), refs in owners.items():
			changed = None
			for position, item in enumerate(refs):
				if not (isinstance(item, list) and len(item) >= 3):
					continue
				try:
					module_id = int(item[0])
					mask = int(item[2])
				except (TypeError, ValueError):
					continue
				module = rows.get(module_id)
				if not module:
					continue
				invalid = mask & ~LogStore.mask_of(module['texts'])
				if not invalid:
					continue
				if changed is None:
					changed = copy.deepcopy(refs)
				changed[position][2] = mask & ~invalid
				items += 1
				bits += len(LogStore.columns_of(invalid))
			if changed is not None:
				updates.setdefault(table, []).append(
					(json.dumps(changed, ensure_ascii=False), owner_id))
		result = {
			'applied': apply,
			'owners': sum(len(entries) for entries in updates.values()),
			'items': items,
			'bits': bits,
			'by_table': {table: len(entries) for table, entries in updates.items()},
		}
		if not apply or not items:
			return result
		with LogStore.write_lock():
			for table, entries in updates.items():
				for index in range(0, len(entries), batch):
					DatabaseManager.execute_many(
						f"UPDATE `{table}` SET `logs` = %s WHERE `id` = %s",
						entries[index:index + batch], raise_on_error=True)
		if items:
			LogStore.refresh_cache()
		return result

	@classmethod
	def fill_masks(cls, rows: Optional[Dict[int, Dict[str, Any]]] = None,
				   owners: Optional[Dict[Tuple[str, int], List[Any]]] = None,
				   apply: bool = False, batch: int = 500) -> Dict[str, Any]:
		"""补齐引用掩码里「模块与全部条目都已有」的语言位（只增不减）

		只加位、不减位，因此不会让任何 ROM 的导出结果回退；
		悬空引用无法判断公共语言，跳过（先修引用再补掩码）。
		"""
		rows = rows if rows is not None else cls.load_rows()
		owners = owners if owners is not None else cls.load_owners()
		updates: Dict[str, List[Tuple[str, int]]] = {table: [] for table in REFERENCE_TABLES}
		added_items = 0
		added_bits = 0
		samples: List[Dict[str, Any]] = []
		for (table, owner_id), original in owners.items():
			# 本 ROM / 开发版自己声明过的语言并集；补位不得越过它，避免把别的 ROM 的译文带进掩码
			owner_mask = 0
			for item in original:
				if isinstance(item, list) and len(item) > 2 and isinstance(item[2], int):
					owner_mask |= int(item[2])
			# 只在真的要改时才复制，避免改到调用方传进来的 owners（dry-run 必须无副作用）
			refs = None
			for position, item in enumerate(original):
				if not (isinstance(item, list) and len(item) >= 2):
					continue
				try:
					module_id = int(item[0])
					entries = [int(x) for x in item[1]]
				except (TypeError, ValueError):
					continue
				if module_id not in rows or any(entry_id not in rows for entry_id in entries):
					continue
				# 没有掩码的历史引用按「模块行有的语言」输出，本来就不会漏语言，无需补
				if len(item) < 3 or not isinstance(item[2], int):
					continue
				mask = int(item[2])
				common = set(rows[module_id]['texts'])
				for entry_id in entries:
					common &= set(rows[entry_id]['texts'])
				common_mask = LogStore.mask_of(common)
				missing = common_mask & ~mask
				if owner_mask:
					missing &= owner_mask
				if not missing:
					continue
				if refs is None:
					refs = copy.deepcopy(original)
				new_mask = mask | missing
				refs[position][2] = new_mask
				added_items += 1
				added_bits += len(LogStore.columns_of(missing))
				if len(samples) < 5:
					samples.append({
						'table': table, 'id': owner_id, 'position': position,
						'old_mask': mask, 'new_mask': new_mask,
						'added': LogStore.columns_of(missing)})
			if refs is not None:
				updates.setdefault(table, []).append(
					(json.dumps(refs, ensure_ascii=False), owner_id))
		result = {
			'applied': apply,
			'owners': sum(len(items) for items in updates.values()),
			'items': added_items,
			'bits': added_bits,
			'by_table': {table: len(items) for table, items in updates.items()},
			'samples': samples,
		}
		if not apply:
			return result
		with LogStore.write_lock():
			for table, items in updates.items():
				for i in range(0, len(items), batch):
					DatabaseManager.execute_many(
						f"UPDATE `{table}` SET `logs` = %s WHERE `id` = %s",
						items[i:i + batch], raise_on_error=True)
		if any(updates.values()):
			LogStore.refresh_cache()
		return result

	# ==================== id / 自增计数器 ====================

	@classmethod
	def id_gaps(cls, table: str = 'logs') -> List[Tuple[int, int, int]]:
		"""返回 [(前一个 id, 当前 id, 空档数), ...]（MySQL 8 窗口函数）"""
		return [(int(row[0]), int(row[1]), int(row[2])) for row in DatabaseManager.query_all(
			"SELECT prev_id, id, id - prev_id - 1 AS gap FROM ("
			f"  SELECT `id`, LAG(`id`) OVER (ORDER BY `id`) AS prev_id FROM `{table}`"
			") t WHERE id - prev_id > 1 ORDER BY id") or []]

	@classmethod
	def table_stats(cls, table: str = 'logs') -> Dict[str, int]:
		"""表的行数 / id 范围 / 空档统计"""
		row = DatabaseManager.query_one(
			f"SELECT COUNT(*), MIN(`id`), MAX(`id`) FROM `{table}`")
		count = int(row[0] or 0) if row else 0
		low = int(row[1] or 0) if row else 0
		high = int(row[2] or 0) if row else 0
		gaps = cls.id_gaps(table) if count else []
		return {
			'rows': count, 'min': low, 'max': high,
			'gaps': len(gaps), 'missing': sum(item[2] for item in gaps),
		}

	@classmethod
	def auto_increment(cls, table: str = 'logs') -> int:
		"""读取表的真实 AUTO_INCREMENT（information_schema 统计默认缓存 24h，先关掉）"""
		DatabaseManager.execute("SET SESSION information_schema_stats_expiry = 0")
		row = DatabaseManager.query_one(
			"SELECT AUTO_INCREMENT FROM information_schema.TABLES "
			"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s", params=(table,))
		return int(row[0] or 0) if row else 0

	@classmethod
	def fix_auto_increment(cls, table: str = 'logs') -> Tuple[int, int]:
		"""把 AUTO_INCREMENT 归位到 MAX(id)+1，返回 (前, 后)

		注意：只有「id 已经连续」时它才等于行数 + 1；有历史空档时它仍会停在旧最大值附近。
		想彻底消除空档请用 ``compact_ids``。
		"""
		row = DatabaseManager.query_one(f"SELECT MAX(`id`) FROM `{table}`")
		expected = (int(row[0]) if row and row[0] is not None else 0) + 1
		before = cls.auto_increment(table)
		if before != expected:
			DatabaseManager.execute(
				f"ALTER TABLE `{table}` AUTO_INCREMENT = {expected}", raise_on_error=True)
		return before, cls.auto_increment(table)

	@classmethod
	def compact_ids(cls, apply: bool = False, backup: bool = True,
					backup_path: Optional[str] = None, batch: int = 500,
					on_progress=None) -> Dict[str, Any]:
		"""把 logs.id 压成连续 1..N，并同步重写 roms.logs / dev.logs 的引用

		logs.id 被引用，不能像 roms / dev 那样直接重排；这里在同一个事务里
		先整体 +OFFSET 再赋 ROW_NUMBER()，随后按旧→新映射重写全部引用。
		整段在跨进程写锁内执行，抓取脚本的写入会排在锁外；映射与备份也在锁内重算，
		因此期间新插入的行同样会被纳入映射。

		apply=False 时只返回将变化的数量与样例（不写库）。
		"""
		before = cls.table_stats('logs')
		counter = cls.auto_increment('logs')
		result: Dict[str, Any] = {
			'applied': False, 'before': before, 'auto_increment': counter,
			'changed': 0, 'mapping_sample': {}, 'backup': None, 'refs': {},
		}
		if not before['rows']:
			return result

		def current_mapping() -> Dict[int, int]:
			rows = DatabaseManager.query_all(
				"SELECT `id`, ROW_NUMBER() OVER (ORDER BY `id`) FROM `logs` ORDER BY `id`") or []
			return {old: new for old, new in
					((int(old), int(new)) for old, new in rows) if old != new}

		changed = current_mapping()
		result['changed'] = len(changed)
		result['mapping_sample'] = dict(list(changed.items())[:10])
		if not changed or not apply:
			return result

		with LogStore.write_lock():
			# 锁内重算：preview 之后可能有抓取脚本插入新行
			changed = current_mapping()
			result['changed'] = len(changed)
			result['mapping_sample'] = dict(list(changed.items())[:10])
			if not changed:
				return result
			if backup:
				result['backup'] = cls.backup(backup_path)
			with DatabaseManager.transaction():
				DatabaseManager.execute(
					f"UPDATE `logs` SET `id` = `id` + {ID_OFFSET}", raise_on_error=True)
				DatabaseManager.execute(
					"UPDATE `logs` r JOIN ("
					"  SELECT `id`, ROW_NUMBER() OVER (ORDER BY `id`) AS rn FROM `logs`"
					") m ON m.`id` = r.`id` SET r.`id` = m.rn", raise_on_error=True)
				result['refs'] = cls.rewrite_refs(changed, batch=batch, on_progress=on_progress)
			cls.fix_auto_increment('logs')
			LogStore.refresh_cache()
		result['after'] = cls.table_stats('logs')
		result['auto_increment_after'] = cls.auto_increment('logs')
		result['applied'] = True
		return result

	# ==================== 清理 / 备份 ====================

	@classmethod
	def prune_unused(cls, rows: Optional[Dict[int, Dict[str, Any]]] = None,
					 owners: Optional[Dict[Tuple[str, int], List[Any]]] = None,
					 apply: bool = False, batch: int = 500) -> Dict[str, Any]:
		"""删除没有被任何 roms.logs / dev.logs 引用的日志行

		apply=False 时只返回候选（含样例），不删库。
		"""
		rows = rows if rows is not None else cls.load_rows()
		used = cls.referenced_ids(owners)
		dead = sorted(set(rows) - used)
		result = {
			'applied': apply, 'candidates': len(dead),
			'rows_before': len(rows), 'rows_after': len(rows),
			'samples': [
				{'id': row_id, 'type': rows[row_id]['type'],
				 'content': LogStore.normalize(rows[row_id]['content'])[:80]}
				for row_id in dead[:5]
			],
		}
		if not apply or not dead:
			return result
		for i in range(0, len(dead), batch):
			chunk = dead[i:i + batch]
			DatabaseManager.execute(
				f"DELETE FROM `logs` WHERE `id` IN ({','.join(['%s'] * len(chunk))})",
				params=tuple(chunk), raise_on_error=True)
		LogStore.refresh_cache()
		result['rows_after'] = cls.table_stats('logs')['rows']
		return result

	@classmethod
	def backup(cls, path: Optional[str] = None) -> str:
		"""把 logs 全表与全部引用结构落盘（破坏性操作前的回滚依据）"""
		payload = {
			'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
			'rows': cls.load_rows(),
			'refs': {f'{table}:{owner_id}': refs
					 for (table, owner_id), refs in cls.load_owners().items()},
		}
		if path is None:
			stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
			path = str(Path(tempfile.gettempdir()) / f'miroms_logs_backup_{stamp}.json')
		target = Path(path)
		target.parent.mkdir(parents=True, exist_ok=True)
		target.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
		return str(target)

	# ==================== 导出对比 ====================

	@classmethod
	def export_snapshot(cls, owners: Optional[Dict[Tuple[str, int], List[Any]]] = None
						) -> Dict[str, Dict[str, Any]]:
		"""把每个 roms / dev 行解出的多语言日志拍成快照

		快照形如 ``{"roms:123": {"logs_zh": {模块: [条目, ...]}, ...}, ...}``，
		是「维护前 / 维护后导出结果是否逐字一致」的对比基准。
		"""
		owners = owners if owners is not None else cls.load_owners()
		return {f'{table}:{owner_id}': LogStore.build_localized(refs)
				for (table, owner_id), refs in sorted(owners.items())}

	@classmethod
	def _localized_diff(cls, before: Dict[str, Any], after: Dict[str, Any],
						samples: int = 3) -> Dict[str, Any]:
		"""对比两份 build_localized 结果：语言增减 + 条目文本的多重集差"""
		added_languages: List[str] = []
		removed_languages: List[str] = []
		added_lines = 0
		removed_lines = 0
		modules_added = 0
		modules_removed = 0
		sample_items: List[Dict[str, Any]] = []
		for column in LogStore.LANG_COLUMNS:
			old_map = before.get(column) or {}
			new_map = after.get(column) or {}
			if old_map == new_map:
				continue
			if not old_map:
				added_languages.append(column)
			elif not new_map:
				removed_languages.append(column)
			# 模块名变化（例如英文回落的 'Other' 被真实译文 'Sonstiges' 取代）
			added_names = sorted(set(new_map) - set(old_map))
			removed_names = sorted(set(old_map) - set(new_map))
			modules_added += len(added_names)
			modules_removed += len(removed_names)
			for name in added_names[:samples]:
				sample_items.append({'change': 'module_added', 'column': column, 'text': str(name)[:80]})
			for name in removed_names[:samples]:
				sample_items.append({'change': 'module_removed', 'column': column, 'text': str(name)[:80]})
			old_counter = Counter(line for lines in old_map.values() for line in lines)
			new_counter = Counter(line for lines in new_map.values() for line in lines)
			gained = new_counter - old_counter
			lost = old_counter - new_counter
			added_lines += sum(gained.values())
			removed_lines += sum(lost.values())
			for line in list(gained)[:samples]:
				sample_items.append({'change': 'added', 'column': column, 'text': str(line)[:80]})
			for line in list(lost)[:samples]:
				sample_items.append({'change': 'removed', 'column': column, 'text': str(line)[:80]})
		return {
			'added_languages': added_languages,
			'removed_languages': removed_languages,
			'added_lines': added_lines,
			'removed_lines': removed_lines,
			'modules_added': modules_added,
			'modules_removed': modules_removed,
			'samples': sample_items,
		}

	@classmethod
	def compare_snapshots(cls, before: Dict[str, Dict[str, Any]],
						  after: Dict[str, Dict[str, Any]], samples: int = 5
						  ) -> Dict[str, Any]:
		"""对比两份导出快照，返回变化明细与汇总

		``lost_content`` 为 True 表示有条目文本在这次维护后消失（需要人工确认）；
		语言掩码补全、合并去重都应只增不减，正常情况下 lost_content 为 False。
		"""
		changed: List[Dict[str, Any]] = []
		for key in sorted(set(before) | set(after)):
			old = before.get(key)
			new = after.get(key)
			if old == new:
				continue
			detail = cls._localized_diff(old or {}, new or {}, samples=samples)
			detail['key'] = key
			detail['existed_before'] = old is not None
			detail['exists_after'] = new is not None
			changed.append(detail)
		added_lines = sum(item['added_lines'] for item in changed)
		removed_lines = sum(item['removed_lines'] for item in changed)
		modules_added = sum(item['modules_added'] for item in changed)
		modules_removed = sum(item['modules_removed'] for item in changed)
		lost_languages = sorted({column for item in changed
								 for column in item['removed_languages']})
		return {
			'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
			'before_keys': len(before),
			'after_keys': len(after),
			'added_keys': sorted(set(after) - set(before)),
			'removed_keys': sorted(set(before) - set(after)),
			'changed': len(changed),
			'added_lines': added_lines,
			'removed_lines': removed_lines,
			'modules_added': modules_added,
			'modules_removed': modules_removed,
			'lost_languages': lost_languages,
			'lost_content': removed_lines > 0 or bool(lost_languages) or bool(set(before) - set(after)),
			'samples': changed[:samples],
		}

	@classmethod
	def save_snapshot(cls, snapshot: Dict[str, Dict[str, Any]], path: Optional[str] = None) -> str:
		"""把导出快照写入 JSON，返回文件路径

		快照很大（全部 ROM × 21 种语言的展开文本，几百 MB），因此默认写 ``.json.gz``；
		显式传 ``.json`` 则写未压缩文本。``load_snapshot`` 按文件头自动识别两种格式。
		"""
		if path is None:
			stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
			path = str(Path(tempfile.gettempdir()) / f'miroms_logs_export_{stamp}.json.gz')
		target = Path(path)
		target.parent.mkdir(parents=True, exist_ok=True)
		payload = {'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
				   'rows': snapshot}
		if target.suffix == '.gz':
			with gzip.open(target, 'wt', encoding='utf-8', compresslevel=5) as handle:
				json.dump(payload, handle, ensure_ascii=False)
		else:
			target.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
		return str(target)

	@classmethod
	def load_snapshot(cls, path: str) -> Dict[str, Dict[str, Any]]:
		"""读取 save_snapshot 写出的快照（按 gzip 文件头自动识别是否压缩）"""
		target = Path(path)
		with open(target, 'rb') as handle:
			compressed = handle.read(2) == b'\x1f\x8b'
		if compressed:
			with gzip.open(target, 'rt', encoding='utf-8') as handle:
				payload = json.load(handle)
		else:
			payload = json.loads(target.read_text(encoding='utf-8'))
		return payload.get('rows', payload)

	# ==================== 体检 ====================

	@classmethod
	def audit(cls, samples: int = 3) -> Dict[str, Any]:
		"""一次性体检 logs 表与引用（只读）

		覆盖：重复分组、悬空引用、坏 JSON、孤儿行、content 不一致 / 哈希过期、
		掩码可补位 / 无效位、id 空档与自增计数器。
		"""
		rows = cls.load_rows()
		owners, bad_refs = cls.scan_owners()
		used = cls.referenced_ids(owners)
		mapping, merged_rows = cls.duplicate_plan(rows)
		duplicates: Dict[int, List[int]] = defaultdict(list)
		for group_id, representative in mapping.items():
			duplicates[representative].append(group_id)
		duplicate_groups = [sorted(ids) for ids in duplicates.values() if len(ids) > 1]
		store_duplicates = LogStore.duplicate_report(rows=list(rows.values()))
		content = cls.content_issues(rows)
		masks = cls.mask_issues(rows, owners)
		content_ids = {issue['id'] for issue in content}
		hashes = cls.stale_hashes(rows)
		stats = cls.table_stats('logs')
		counter = cls.auto_increment('logs')
		return {
			'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
			'rows': len(rows),
			'proofed': sum(1 for row in rows.values() if row.get('proofed')),
			'complete': sum(1 for row in rows.values() if row.get('complete')),
			'lang_issues': sum(1 for row in rows.values() if row.get('lang_issues')),
			'refs': {'owners': len(owners), 'bad': bad_refs,
					 'dangling_items': len(masks['dangling']),
					 'dangling_ids': len({row_id for detail in masks['dangling']
										  for row_id in detail['missing']})},
			'duplicates': {'groups': len(duplicate_groups),
						   'rows': sum(len(ids) for ids in duplicate_groups),
						   'store_groups': len(store_duplicates)},
			'unused': {'rows': len(set(rows) - used), 'ids': sorted(set(rows) - used)[:samples]},
			'content': {'issues': len(content), 'by_reason': _count_by(content, 'reason'),
						'ids': sorted(content_ids)[:samples]},
			'hash': {'stale': len(hashes), 'ids': hashes[:samples]},
			'masks': {'extendable': len(masks['extendable']),
					  'invalid': len(masks['invalid']),
					  'invalid_bits': sorted({column for detail in masks['invalid']
											  for column in detail['bits']})},
			'mergeable': {'groups': len(merged_rows),
						  'ids': [sorted(ids) for ids in duplicate_groups[:samples]]},
			'ids': {'rows': stats['rows'], 'min': stats['min'], 'max': stats['max'],
					'gaps': stats['gaps'], 'missing': stats['missing'],
					'auto_increment': counter,
					'counter_ok': counter == stats['max'] + 1},
		}


def _count_by(items: List[Dict[str, Any]], field: str) -> Dict[str, int]:
	"""按字段计数（体检报告用）"""
	counts: Dict[str, int] = defaultdict(int)
	for item in items:
		counts[str(item.get(field))] += 1
	return dict(counts)
