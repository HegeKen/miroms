"""
miroms.logs_store - 更新日志的分组存储（同一日志的多语言版本共用一行）

背景：roms 表的更新日志原先「一门语言一列」（logs_zh / logs_en / logs_ja ... 共 21 列），
同一句日志的不同语言版本各自去重、互不关联，既无法互相补全，也让 roms 表列数不断膨胀。

现在改为「同一日志的各语言版本 = logs 表的一行」：

    logs
    ├─ id            自增主键（一个日志分组一个 id）
    ├─ type          module = 模块名 / log = 日志条目
    ├─ content       主内容（简体中文；无中文时取英文，再取最早出现的原文）
    ├─ content_hash  md5(content)，查专用索引（同内容可能出现多行，见下「冲突拆行」）
    ├─ logs_zh       简体中文
    ├─ logs_zh_tw    繁体中文
    ├─ logs_en       英文
    └─ logs_xx       ...其余语种各一列（见 constants.CHANGELOG_LOCALES）

roms 表只保留一列 `logs`，存 ID 引用结构：

    [[模块ID, [条目ID, ...], 语言掩码], ...]   如 [[3, [6, 8], 5], [32, [45, 48], 8]]

语言掩码是 21 位整数（第 i 位对应 constants.CHANGELOG_LOCALES 第 i 个语言列），
表示「这个模块位置属于本 ROM 的哪几门语言」。

两个关键设计
------------
1. **结构指纹聚类**：中文日志的模块 / 条目序号并不总和其他语言对应（例如某 ROM 的中文是
   电话 / 联系人 / 短信 / 便签 四个模块，而日文、德文只返回一个「其他」模块）。
   因此只有**结构指纹完全一致**（模块数、每个模块条目数都相同）的语言才按序号合并成同一组；
   指纹不同的语言各自成组，作为附加模块并入总日志——即「其他语言提到、但中英文没提到的
   日志也一并加进总日志」。

2. **语言掩码 + 冲突拆行**：logs 表按内容跨 ROM 去重，同一分组会被多个 ROM 引用。
   掩码让导出时只输出该位置在本 ROM 真正拥有的语言，避免 A 语言的模块被 B 语言输出带出去；
   若同一主内容在不同 ROM 出现互相冲突的译文（同一句中文的两种外文写法），
   则另起一行保存（logs 表的 (type, content_hash) 只是普通索引，不是唯一键），
   保证每个 ROM 的日志都能原样还原，不会「先到先得」覆盖别人。

典型用法：
    写入：LogStore.write_logs({'logs_zh': zh_obj, 'logs_en': en_obj})   # -> roms.logs 的值
    导出：LogStore.build_localized(parsed)                              # -> {'logs_zh': {...}, 'logs_en': {...}}
"""
import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Sequence, Tuple

from miroms.constants import CHANGELOG_LOCALES
from miroms.database import DatabaseManager

logger = logging.getLogger(__name__)


class _RowIndex:
	"""内存中的 logs 行池：按语言文本做兼容性去重，冲突则拆成新行

	- `buckets[(type, 语言列, 文本hash)]` -> 行下标列表，用于快速找到「已有该语言文本」的行；
	- 只有在**所有语言都不冲突**（该行对应语言为空或文本相同）时才复用同一行。
	"""

	__slots__ = ('rows', 'buckets', 'by_content', 'splits', 'conflicts')

	def __init__(self) -> None:
		self.rows: List[Dict[str, Any]] = []
		self.buckets: Dict[Tuple[str, str, str], List[int]] = {}
		self.by_content: Dict[Tuple[str, str], List[int]] = {}
		self.splits = 0
		self.conflicts: List[Tuple[str, str, str, str, str]] = []

	def _register(self, index: int) -> None:
		row = self.rows[index]
		for column, value in row['texts'].items():
			key = (row['type'], column, LogStore._hash(value))
			bucket = self.buckets.setdefault(key, [])
			if index not in bucket:
				bucket.append(index)
		key = (row['type'], LogStore._hash(row['content']))
		bucket = self.by_content.setdefault(key, [])
		if index not in bucket:
			bucket.append(index)

	def lookup(self, log_type: str, texts: Dict[str, str]) -> Optional[int]:
		"""只读查找：返回**已包含**这些语言文本的行下标（不复用、不新建）

		用于「行池已建好后」的第二遍遍历（如批量迁移回写 roms.logs），
		保证写出的 id 一定落在已入库的行上。
		"""
		texts = {column: LogStore.normalize(value) for column, value in (texts or {}).items()
				 if column in LogStore.LANG_COLUMNS and LogStore.normalize(value)}
		if not texts:
			return None
		primary = LogStore._primary(texts)
		candidates: List[int] = []
		seen = set()
		for index in self.by_content.get((log_type, LogStore._hash(primary)), ()):
			seen.add(index)
			candidates.append(index)
		for column, value in texts.items():
			for index in self.buckets.get((log_type, column, LogStore._hash(value)), ()):
				if index not in seen:
					seen.add(index)
					candidates.append(index)
		for index in candidates:
			row = self.rows[index]
			if all(row['texts'].get(column) == value for column, value in texts.items()):
				return index
		return None

	def resolve(self, log_type: str, texts: Dict[str, str]) -> Optional[int]:
		texts = {column: LogStore.normalize(value) for column, value in (texts or {}).items()
				 if column in LogStore.LANG_COLUMNS and LogStore.normalize(value)}
		if not texts:
			return None
		primary = LogStore._primary(texts)

		candidates: List[int] = []
		seen = set()
		for index in self.by_content.get((log_type, LogStore._hash(primary)), ()):
			seen.add(index)
			candidates.append(index)
		for column, value in texts.items():
			for index in self.buckets.get((log_type, column, LogStore._hash(value)), ()):
				if index not in seen:
					seen.add(index)
					candidates.append(index)

		for index in candidates:
			row = self.rows[index]
			if all(row['texts'].get(column) in (None, value) for column, value in texts.items()):
				for column, value in texts.items():
					if not row['texts'].get(column):
						row['texts'][column] = value
				# 补上中文后主内容以中文为准（保证 content 始终是中文优先）
				zh_text = row['texts'].get(LogStore.ZH_COLUMN)
				if zh_text and row['content'] != zh_text:
					row['content'] = zh_text
					if len(self.conflicts) < 200:
						self.conflicts.append((log_type, primary, LogStore.ZH_COLUMN,
											   row['content'], zh_text))
				self._register(index)
				return index

		if candidates:
			# 主内容相同但译文冲突：另起一行（保证两个 ROM 的日志都能原样还原）
			self.splits += 1
		row = {'type': log_type, 'content': primary, 'texts': dict(texts)}
		self.rows.append(row)
		index = len(self.rows) - 1
		self._register(index)
		return index


class LogStore:
	TYPE_MODULE = 'module'
	TYPE_LOG = 'log'

	# 语言列（logs_zh 在最前，其余顺序与 CHANGELOG_LOCALES 一致）
	LANG_COLUMNS: Tuple[str, ...] = tuple(item['column'] for item in CHANGELOG_LOCALES)
	LANG_INDEX: Dict[str, int] = {column: i for i, column in enumerate(LANG_COLUMNS)}
	ZH_COLUMN = 'logs_zh'
	EN_COLUMN = 'logs_en'

	_LANG_COMMENTS: Dict[str, str] = {
		item['column']: f"{item['zh']}（{item['api']}）" for item in CHANGELOG_LOCALES
	}

	_table_ensured = False
	# 行签名 -> id，避免同一进程内重复查库
	_sig_cache: Dict[Tuple[str, str], int] = {}
	# id -> {'type', 'texts'}，导出侧缓存
	_groups: Optional[Dict[int, Dict[str, Any]]] = None
	# 最近一次写入的冲突拆行统计
	last_conflicts: List[Tuple[str, str, str, str, str]] = []

	# ==================== 基础 ====================

	@classmethod
	def create_sql(cls, table: str = 'logs') -> str:
		"""生成 logs 建表语句（列随 CHANGELOG_LOCALES 自动增减）"""
		langs = "\n".join(
			f"  `{column}` longtext COLLATE utf8mb4_bin COMMENT '{cls._LANG_COMMENTS[column]}',"
			for column in cls.LANG_COLUMNS
		)
		return (
			f"CREATE TABLE IF NOT EXISTS `{table}` (\n"
			f"  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键（同一日志的各语言版本共用一行）',\n"
			f"  `type` varchar(8) COLLATE utf8mb4_bin NOT NULL COMMENT '日志类型：module=模块名 / log=日志条目',\n"
			f"  `content` text COLLATE utf8mb4_bin NOT NULL COMMENT '主内容（简体中文；无中文时取英文，再取最早出现的原文）',\n"
			f"  `content_hash` char(32) COLLATE utf8mb4_bin NOT NULL COMMENT 'content 的 MD5（hex），查专用索引（同内容可因译文冲突存在多行）',\n"
			f"{langs}\n"
			f"  PRIMARY KEY (`id`),\n"
			f"  KEY `idx_type_hash` (`type`, `content_hash`)\n"
			f") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin"
		)

	@classmethod
	def ensure_table(cls) -> None:
		if cls._table_ensured:
			return
		DatabaseManager.execute(cls.create_sql(), raise_on_error=True)
		cls._table_ensured = True

	@staticmethod
	def normalize(content: Any) -> str:
		"""主内容归一化：去掉首尾空白（接口原文常带前导空格与尾随空格，归一化后才能正确去重）"""
		return str(content if content is not None else '').strip()

	@staticmethod
	def _hash(content: str) -> str:
		return hashlib.md5(content.encode('utf-8')).hexdigest()

	@classmethod
	def signature(cls, log_type: str, content: str, texts: Dict[str, str]) -> str:
		"""一行日志的完整签名（类型 + 主内容 + 各语言文本），用于精确匹配已有行"""
		parts = [log_type, content]
		for column in cls.LANG_COLUMNS:
			value = texts.get(column) or ''
			if value:
				parts.append(f'{column}={value}')
		return hashlib.md5('\x1f'.join(parts).encode('utf-8')).hexdigest()

	@staticmethod
	def is_encoded(parsed: Any) -> bool:
		"""判断解析后的值是否为 ID 引用结构 [[mid, [lids...], mask?], ...]"""
		if not isinstance(parsed, list):
			return False
		for item in parsed:
			if not (isinstance(item, list) and len(item) in (2, 3)
					and isinstance(item[0], int) and isinstance(item[1], list)):
				return False
			if len(item) == 3 and not isinstance(item[2], int):
				return False
		return True

	@staticmethod
	def mask_of(columns: Sequence[str]) -> int:
		"""语言列集合 -> 语言掩码"""
		mask = 0
		for column in columns:
			mask |= 1 << LogStore.LANG_INDEX[column]
		return mask

	@classmethod
	def columns_of(cls, mask: int) -> List[str]:
		"""语言掩码 -> 语言列列表（按 LANG_COLUMNS 顺序）"""
		return [column for i, column in enumerate(cls.LANG_COLUMNS) if (mask >> i) & 1]

	# ==================== 写入侧 ====================

	@staticmethod
	def _primary(texts: Dict[str, str]) -> str:
		"""一个分组的「主内容」：优先简体中文，其次英文，最后任一语言"""
		for column in (LogStore.ZH_COLUMN, LogStore.EN_COLUMN):
			value = LogStore.normalize(texts.get(column))
			if value:
				return value
		for value in texts.values():
			value = LogStore.normalize(value)
			if value:
				return value
		return ''

	@classmethod
	def _items(cls, obj: Any) -> List[Tuple[str, List[str]]]:
		"""把一个语言结构规整为 [(模块, [条目, ...]), ...]（去掉空模块）"""
		items: List[Tuple[str, List[str]]] = []
		for module, lines in (obj or {}).items():
			if not str(module or '').strip():
				continue
			if not isinstance(lines, list):
				lines = [lines]
			items.append((str(module).strip(), [str(x) for x in lines]))
		return items

	@classmethod
	def shape(cls, obj: Any) -> Tuple[int, ...]:
		"""结构指纹：(模块数, 各模块条目数...)，用于判断两门语言能否按序号对齐"""
		items = cls._items(obj)
		return tuple([len(items)] + [len(lines) for _, lines in items])

	@classmethod
	def cluster_languages(cls, langs: Dict[str, Any]) -> List[List[str]]:
		"""把各语言按结构指纹聚类；只有指纹完全相同的语言才允许按序号对齐

		返回的簇按「含简体中文 → 含英文 → 语言数降序」排序，
		保证总日志以中文结构为主、其余结构作为附加模块追加在后。
		"""
		groups: Dict[Tuple[int, ...], List[str]] = {}
		for column in cls.LANG_COLUMNS:
			obj = (langs or {}).get(column)
			if not obj:
				continue
			groups.setdefault(cls.shape(obj), []).append(column)

		def rank(item: Tuple[Tuple[int, ...], List[str]]) -> Tuple[int, int]:
			_, cols = item
			if cls.ZH_COLUMN in cols:
				priority = 0
			elif cls.EN_COLUMN in cols:
				priority = 1
			else:
				priority = 2
			return (priority, -len(cols))

		clusters = [cols for _, cols in sorted(groups.items(), key=rank)]
		for cols in clusters:
			cols.sort(key=lambda c: cls.LANG_INDEX[c])
		return clusters

	@classmethod
	def compose(cls, langs: Dict[str, Any]) -> List[Dict[str, Any]]:
		"""把多语言结构按「结构指纹聚类 → 簇内按序号对齐」组合成一组分组位置

		返回 [{'texts': {列名: 模块文本}, 'entries': [{'texts': {列名: 条目文本}}, ...],
		       'mask': 语言掩码}, ...]
		"""
		positions: List[Dict[str, Any]] = []
		for columns in cls.cluster_languages(langs or {}):
			items = {column: cls._items(langs[column]) for column in columns}
			canonical = columns[0]
			mask = cls.mask_of(columns)
			for index, (_, lines) in enumerate(items[canonical]):
				texts: Dict[str, str] = {}
				for column in columns:
					module = items[column][index][0].strip()
					if module:
						texts[column] = module
				entries: List[Dict[str, Any]] = []
				for j in range(len(lines)):
					item: Dict[str, str] = {}
					for column in columns:
						line = items[column][index][1][j]
						if str(line).strip():
							item[column] = str(line).strip()
					entries.append({'texts': item})
				positions.append({'texts': texts, 'entries': entries, 'mask': mask})
		return positions

	@classmethod
	def new_index(cls) -> '_RowIndex':
		"""新建一个可跨多次调用共享的内存行池（批量迁移用）"""
		return _RowIndex()

	@classmethod
	def build_rows(cls, positions: List[Dict[str, Any]],
				   index: Optional['_RowIndex'] = None,
				   mutate: bool = True) -> Tuple[List[Dict[str, Any]], List[List[Any]]]:
		"""把分组位置解析成行池与引用关系

		传入 index 可在多次调用间共享行池（如批量迁移时跨 ROM 去重）。
		mutate=False 时只做只读查找（不再补全 / 新建行），用于行池建好后的第二遍遍历。
		返回 (rows, refs)：rows 为待写入行列表；refs 为
		[(模块行下标, [条目行下标, ...], 语言掩码), ...]。
		"""
		index = index if index is not None else _RowIndex()
		resolver = index.resolve if mutate else index.lookup
		refs: List[List[Any]] = []
		for position in positions:
			module_index = resolver(cls.TYPE_MODULE, position['texts'])
			if module_index is None:
				if mutate:
					continue
				raise RuntimeError(f"行池中找不到模块分组: {position['texts']}")
			entry_indices = []
			for entry in position['entries']:
				entry_index = resolver(cls.TYPE_LOG, entry['texts'])
				if entry_index is not None:
					entry_indices.append(entry_index)
			refs.append([module_index, entry_indices, int(position.get('mask', 0))])
		cls.last_conflicts = index.conflicts
		return index.rows, refs

	@classmethod
	def _fetch_rows(cls, hashes: Sequence[str], batch: int = 500) -> List[Dict[str, Any]]:
		"""按 content_hash 批量取候选行（含各语言文本），用于精确签名匹配"""
		columns = ', '.join(f'`{c}`' for c in cls.LANG_COLUMNS)
		found: List[Dict[str, Any]] = []
		hashes = list(hashes)
		for i in range(0, len(hashes), batch):
			chunk = hashes[i:i + batch]
			placeholders = ','.join(['%s'] * len(chunk))
			rows = DatabaseManager.query_all(
				f"SELECT `id`, `type`, `content`, `content_hash`, {columns} FROM `logs` "
				f"WHERE `content_hash` IN ({placeholders})",
				params=tuple(chunk),
			)
			for row in rows or []:
				texts = {column: row[4 + i] for i, column in enumerate(cls.LANG_COLUMNS) if row[4 + i]}
				found.append({
					'id': int(row[0]), 'type': row[1], 'content': row[2],
					'texts': texts, 'sig': cls.signature(row[1], row[2], texts),
				})
		return found

	@classmethod
	def ensure_ids(cls, rows: List[Dict[str, Any]]) -> List[int]:
		"""保证所有待写入行在 logs 表中存在，返回与 rows 等长的 id 列表

		匹配规则：类型 + 主内容 + 各语言文本完全一致才算同一行（签名一致）；
		语言文本不同的同内容行会各自保留。
		"""
		if not rows:
			return []
		cls.ensure_table()

		result: List[Optional[int]] = [None] * len(rows)
		pending: List[int] = []
		need_fetch: List[int] = []
		fill_map: Dict[int, Dict[str, str]] = {}
		for i, row in enumerate(rows):
			row['sig'] = cls.signature(row['type'], row['content'], row['texts'])
			cached = cls._sig_cache.get((row['type'], row['sig']))
			if cached is not None:
				result[i] = cached
			else:
				need_fetch.append(i)

		if need_fetch:
			# 候选行：content_hash 命中「本行主内容」或「本行任一语言文本」的行
			# （后者让英文-only 的行能反查到已含中文的同一条日志，实现合并）
			hashes = set()
			for i in need_fetch:
				row = rows[i]
				hashes.add(cls._hash(row['content']))
				for value in row['texts'].values():
					if value:
						hashes.add(cls._hash(value))
			existing = cls._fetch_rows(sorted(hashes))
			for i in need_fetch:
				row = rows[i]
				match = cls._match_row(row, existing)
				if match is None:
					pending.append(i)
				else:
					result[i] = match['id']
					cls._sig_cache[(row['type'], row['sig'])] = match['id']
					cls._collect_missing(fill_map, row, match)

		if pending:
			columns = ['`type`', '`content`', '`content_hash`'] + [f'`{c}`' for c in cls.LANG_COLUMNS]
			column_sql = ', '.join(columns)
			batch = 200
			for i in range(0, len(pending), batch):
				chunk = pending[i:i + batch]
				placeholders = ', '.join(['(' + ', '.join(['%s'] * len(columns)) + ')'] * len(chunk))
				params: List[Any] = []
				for index in chunk:
					row = rows[index]
					params.extend([row['type'], row['content'], cls._hash(row['content'])])
					params.extend([row['texts'].get(c) or None for c in cls.LANG_COLUMNS])
				DatabaseManager.execute(
					f"INSERT INTO `logs` ({column_sql}) VALUES {placeholders}",
					params=tuple(params), raise_on_error=True,
				)
			# 回查新插入的行
			inserted = cls._fetch_rows(sorted({cls._hash(rows[i]['content']) for i in pending}))
			for i in pending:
				row = rows[i]
				match = cls._match_row(row, inserted)
				if match is None:
					raise RuntimeError(
						f"logs 表写入后未查到记录: type={row['type']} content={row['content'][:40]!r}")
				result[i] = match['id']
				cls._sig_cache[(row['type'], row['sig'])] = match['id']
				cls._collect_missing(fill_map, row, match)

		# 复用了库中已有分组但该行缺少某些语言时补齐（COALESCE，不覆盖已有译文）
		for group_id, texts in fill_map.items():
			sets = [c for c in cls.LANG_COLUMNS if texts.get(c)]
			if not sets:
				continue
			DatabaseManager.execute(
				"UPDATE `logs` SET " + ', '.join(f'`{c}` = COALESCE(`{c}`, %s)' for c in sets)
				+ " WHERE `id` = %s",
				params=tuple([texts[c] for c in sets] + [group_id]), raise_on_error=True,
			)

		if cls._groups is not None:
			cls._groups = None
		return [int(value) for value in result]

	@classmethod
	def _collect_missing(cls, fill_map: Dict[int, Dict[str, str]], row: Dict[str, Any],
						 match: Dict[str, Any]) -> None:
		"""记录「复用已有分组时需要补写的语言」，并同步到内存候选，避免重复写"""
		missing = {column: value for column, value in row['texts'].items()
				   if value and not match['texts'].get(column)}
		zh_text = match['texts'].get(cls.ZH_COLUMN)
		if zh_text and match['content'] != zh_text:
			# 复用的行主内容与中文列不一致（历史上由英文占位创建）——一并纠正，
			# 保证 content 始终是中文优先的主内容
			match['content'] = zh_text
			DatabaseManager.execute(
				"UPDATE `logs` SET `content` = %s, `content_hash` = %s WHERE `id` = %s",
				params=(zh_text, cls._hash(zh_text), match['id']), raise_on_error=True,
			)
		if not missing:
			match['sig'] = cls.signature(match['type'], match['content'], match['texts'])
			return
		fill_map.setdefault(int(match['id']), {}).update(missing)
		match['texts'].update(missing)
		match['sig'] = cls.signature(match['type'], match['content'], match['texts'])

	@classmethod
	def _match_row(cls, row: Dict[str, Any], candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
		"""在候选行里为待写入行找归属

		先看签名完全一致的行；没有则接受「语言不冲突」的候选（已有行可能带着更多语言，
		例如库里的同一条日志已经补齐了日文、德文，此时应当复用而不是另起一行），
		并优先选择语言覆盖最全的那一行。
		"""
		same_type = [item for item in candidates if item['type'] == row['type']]
		key = (row['type'], row['sig'])
		for item in same_type:
			if item['sig'] == row['sig']:
				return item
		best: Optional[Dict[str, Any]] = None
		best_len = -1
		texts = row['texts']
		for item in same_type:
			if all(item['texts'].get(column) in (None, value) for column, value in texts.items()):
				size = len(item['texts'])
				if size > best_len:
					best, best_len = item, size
		return best

	@classmethod
	def encode_refs(cls, refs: List[List[Any]], ids: Sequence[int]) -> str:
		"""refs（行下标引用）+ id 列表 -> roms.logs 的值：[[模块ID,[条目ID,...],掩码],...]"""
		pairs: List[List[Any]] = []
		for module_index, entry_indices, mask in refs:
			pairs.append([ids[module_index], [ids[i] for i in entry_indices], int(mask)])
		return json.dumps(pairs, ensure_ascii=False)

	@classmethod
	def write_logs(cls, langs: Dict[str, Any], dry_run: bool = False,
				   expand_mask: bool = False) -> str:
		"""写入一个 ROM / 一周开发版的多语言日志，返回 ID 引用结构 JSON 字符串

		langs = {语言列: 该语言结构}，结构指纹一致的语言会自动合并为一组；
		已存在且语言不冲突的分组直接复用（并补齐缺失语言），不覆盖已有译文。

		expand_mask=True 时语言掩码取「模块分组与全部条目的公共语言」，
		这样复用了库里已有多语言分组时，能顺带拿到中英文之外的其他译文。
		"""
		positions = cls.compose(langs or {})
		rows, refs = cls.build_rows(positions)
		ids = list(range(1, len(rows) + 1)) if dry_run else cls.ensure_ids(rows)
		if not expand_mask:
			return cls.encode_refs(refs, ids)

		pairs: List[List[Any]] = []
		for module_index, entry_indices, mask in refs:
			common = set(rows[module_index]['texts'])
			for index in entry_indices:
				common &= set(rows[index]['texts'])
			new_mask = cls.mask_of([c for c in cls.LANG_COLUMNS if c in common])
			pairs.append([ids[module_index], [ids[i] for i in entry_indices], new_mask or mask])
		return json.dumps(pairs, ensure_ascii=False)

	@classmethod
	def encode_value(cls, value: Any, canonical_column: str = ZH_COLUMN) -> Any:
		"""待写入列的值：原文 JSON -> ID 结构 JSON；已是 ID 结构则原样返回（幂等）

		canonical_column 指定原文 JSON 属于哪门语言（默认简体中文）。
		"""
		if not value:
			return value
		try:
			parsed = json.loads(value) if isinstance(value, str) else value
		except (json.JSONDecodeError, TypeError):
			return value
		if cls.is_encoded(parsed):
			return value
		if isinstance(parsed, dict):
			return cls.write_logs({canonical_column: parsed})
		return value

	# ==================== 导出侧 ====================

	@classmethod
	def load_groups(cls, force: bool = False) -> Dict[int, Dict[str, Any]]:
		"""全量载入 logs 表（id -> {'type', 'texts'}），导出时纯内存映射"""
		if cls._groups is not None and not force:
			return cls._groups
		cls.ensure_table()
		columns = ', '.join(f'`{c}`' for c in cls.LANG_COLUMNS)
		rows = DatabaseManager.query_all(f"SELECT `id`, `type`, `content`, {columns} FROM `logs`")
		groups: Dict[int, Dict[str, Any]] = {}
		for row in rows or []:
			texts = {column: row[3 + i] for i, column in enumerate(cls.LANG_COLUMNS) if row[3 + i]}
			if not texts.get(cls.ZH_COLUMN) and row[2]:
				texts[cls.ZH_COLUMN] = row[2]
			groups[int(row[0])] = {'type': row[1], 'texts': texts}
		cls._groups = groups
		logger.info(f"logs 表已载入内存: {len(groups)} 条")
		return groups

	@classmethod
	def decode_structure(cls, pairs: Any) -> List[Tuple[Dict[str, Any], List[Dict[str, Any]], int]]:
		"""ID 引用结构 -> [(模块分组, [条目分组, ...], 语言掩码), ...]（缺失 id 跳过）"""
		if not isinstance(pairs, list):
			return []
		groups = cls.load_groups()
		result = []
		for item in pairs:
			if not (isinstance(item, list) and len(item) in (2, 3)):
				continue
			module = groups.get(int(item[0]))
			if module is None:
				continue
			entries = [groups[int(lid)] for lid in item[1]
					   if isinstance(lid, int) and int(lid) in groups]
			if len(item) == 3 and isinstance(item[2], int):
				mask = int(item[2])
			else:
				mask = cls.mask_of([c for c in cls.LANG_COLUMNS if module['texts'].get(c)])
			result.append((module, entries, mask))
		return result

	@classmethod
	def _entry_text(cls, group: Dict[str, Any], column: str) -> Optional[str]:
		"""条目文本：该语言缺失时回落英文、再回落中文；简体中文自身不回落"""
		text = group['texts'].get(column)
		if text:
			return text
		if column == cls.ZH_COLUMN:
			return None
		return group['texts'].get(cls.EN_COLUMN) or group['texts'].get(cls.ZH_COLUMN) or None

	@classmethod
	def build_localized(cls, pairs: Any) -> Dict[str, Dict[str, Any]]:
		"""ID 引用结构 -> {语言列: {模块: [条目, ...]}}（导出格式）

		只输出语言掩码里包含的语言，避免跨 ROM 复用分组时把别的语言带出来。
		"""
		result: Dict[str, Dict[str, Any]] = {}
		for module, entries, mask in cls.decode_structure(pairs):
			for index, column in enumerate(cls.LANG_COLUMNS):
				if not (mask >> index) & 1:
					continue
				module_text = module['texts'].get(column)
				if not module_text:
					continue
				lines = []
				for entry in entries:
					text = cls._entry_text(entry, column)
					if text:
						lines.append(text)
				# 空条目的模块也保留（上游日志里确实存在 {"基础体验": []} 这类空模块）
				result.setdefault(column, {}).setdefault(module_text, []).extend(lines)
		# 语言键按 LANG_COLUMNS 顺序输出，保证导出文件稳定、diff 友好
		return {column: result[column] for column in cls.LANG_COLUMNS if column in result}

	@classmethod
	def localized_value(cls, pairs: Any, column: str) -> Optional[Dict[str, Any]]:
		"""只要某一门语言的日志（缺失返回 None）"""
		return cls.build_localized(pairs).get(column)

	@classmethod
	def decode(cls, pairs: Any) -> Dict[str, Any]:
		"""ID 引用结构 -> 简体中文原文对象（兼容旧接口）"""
		return cls.build_localized(pairs).get(cls.ZH_COLUMN) or {}

	@classmethod
	def decode_value(cls, parsed: Any) -> Any:
		"""解析后的列值：ID 结构 -> 多语言对象；其余（旧格式/异常值）原样返回"""
		if cls.is_encoded(parsed):
			return cls.build_localized(parsed)
		return parsed

	@classmethod
	def normalize_json(cls, value: Any) -> Any:
		"""比较用归一化：ID 结构解码为多语言对象，其余原样返回解析结果"""
		if not value or not isinstance(value, str):
			return value
		try:
			parsed = json.loads(value)
		except (json.JSONDecodeError, TypeError):
			return value
		return cls.decode_value(parsed)

	# ==================== 反查 / 维护 ====================

	@classmethod
	def find_group(cls, log_type: str, column: str, text: str) -> Optional[Tuple[int, Dict[str, Any]]]:
		"""按「某门语言的文本」反查已存在的分组（人工录入时用于复用已有译文）

		先按该语言列精确匹配，再按主内容精确匹配。
		"""
		if column not in cls.LANG_COLUMNS:
			raise ValueError(f"未知语言列: {column}")
		text = cls.normalize(text)
		if not text:
			return None
		for sql, params in (
			(f"SELECT `id` FROM `logs` WHERE `type` = %s AND `{column}` = %s LIMIT 1", (log_type, text)),
			("SELECT `id` FROM `logs` WHERE `type` = %s AND `content_hash` = %s LIMIT 1",
			 (log_type, cls._hash(text))),
		):
			row = DatabaseManager.query_one(sql, params=params)
			if row:
				group_id = int(row[0])
				return group_id, cls.load_groups().get(group_id, {})
		return None

	@classmethod
	def fill_missing(cls, group_id: int, texts: Dict[str, str]) -> int:
		"""给已有分组补齐缺失的语言列（不覆盖已有值），返回实际补写的列数"""
		sets, params = [], []
		for column, value in texts.items():
			if column not in cls.LANG_COLUMNS:
				continue
			value = cls.normalize(value)
			if not value:
				continue
			sets.append(f"`{column}` = COALESCE(`{column}`, %s)")
			params.append(value)
		if not sets:
			return 0
		DatabaseManager.execute(
			f"UPDATE `logs` SET {', '.join(sets)} WHERE `id` = %s",
			params=tuple(params + [group_id]), raise_on_error=True,
		)
		cls._groups = None
		cls._sig_cache = {}
		return len(sets)

	@classmethod
	def refresh_cache(cls) -> None:
		"""全量刷新缓存"""
		cls._sig_cache = {}
		cls._groups = None

	@classmethod
	def count(cls) -> int:
		row = DatabaseManager.query_one("SELECT COUNT(*) FROM `logs`")
		return int(row[0]) if row else 0
