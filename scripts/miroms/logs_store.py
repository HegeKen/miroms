import hashlib
import json
import logging
from typing import Any, Dict, List, Optional, Set, Tuple

from miroms.database import DatabaseManager

logger = logging.getLogger(__name__)


class LogStore:
		"""
		更新日志字典化存储（logs 表）

		背景：roms 表 20 个 logs_* 列的原文 JSON（{"模块": ["条目", ...]}）在多设备、
		多版本间大量重复（模块名 ~370x、条目 ~66x 重复）。现将模块名与条目原文
		字典化到 logs 表，roms.logs_* 列只存 ID 引用结构：

		    [[模块ID, [条目ID, ...]], ...]   如 [[3, [6, 8]], [32, [45, 48]]]

		- 模块/条目顺序由数组顺序保证（不依赖 JSON 对象键序）
		- 去重键为 (type, content_hash)，content_hash = md5(content)
		- 本类提供：写入侧 encode（get-or-create）与导出侧 decode（内存映射回原文）

		典型用法：
		    写入：LogStore.encode_value(log_json_str)  # 原文 JSON -> ID 结构 JSON
		    导出：LogStore.decode_value(parsed)        # ID 结构 -> {"模块": ["条目"]}
		"""

		TYPE_MODULE = 'module'
		TYPE_LOG = 'log'

		CREATE_SQL = """
				CREATE TABLE IF NOT EXISTS `logs` (
				  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
				  `type` varchar(8) COLLATE utf8mb4_bin NOT NULL COMMENT '日志类型：module=模块名 / log=日志条目',
				  `content` text COLLATE utf8mb4_bin NOT NULL COMMENT '原文内容',
				  `content_hash` char(32) COLLATE utf8mb4_bin NOT NULL COMMENT 'content 的 MD5（hex），用于去重查找',
				  PRIMARY KEY (`id`),
				  UNIQUE KEY `uq_type_hash` (`type`, `content_hash`)
				) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
		"""

		_table_ensured = False
		# (type, content) -> id，写入侧缓存
		_id_cache: Dict[Tuple[str, str], int] = {}
		# id -> content，导出侧缓存（全量一次载入，约几万行）
		_content_map: Optional[Dict[int, str]] = None

		# ---------------- 基础 ----------------

		@classmethod
		def ensure_table(cls) -> None:
				if cls._table_ensured:
						return
				DatabaseManager.execute(cls.CREATE_SQL, raise_on_error=True)
				cls._table_ensured = True

		@staticmethod
		def _hash(content: str) -> str:
				return hashlib.md5(content.encode('utf-8')).hexdigest()

		# ---------------- 结构判定 ----------------

		@staticmethod
		def is_encoded(parsed: Any) -> bool:
				"""判断解析后的值是否为 ID 引用结构 [[mid, [lids...]], ...]"""
				if not isinstance(parsed, list):
						return False
				for item in parsed:
						if not (isinstance(item, list) and len(item) == 2
										and isinstance(item[0], int) and isinstance(item[1], list)):
								return False
				return True

		# ---------------- 写入侧：get-or-create + encode ----------------

		@classmethod
		def get_or_create(cls, log_type: str, content: str) -> int:
				"""按 (type, content) 获取 ID，不存在则插入。进程内缓存避免重复查询。"""
				key = (log_type, content)
				if key in cls._id_cache:
						return cls._id_cache[key]
				cls.ensure_table()
				DatabaseManager.execute(
						"INSERT IGNORE INTO `logs` (`type`, `content`, `content_hash`) VALUES (%s, %s, %s)",
						params=(log_type, content, cls._hash(content)),
						raise_on_error=True,
				)
				row = DatabaseManager.query_one(
						"SELECT `id` FROM `logs` WHERE `type` = %s AND `content_hash` = %s",
						params=(log_type, cls._hash(content)),
				)
				if not row:
						raise RuntimeError(f"logs 表写入后未查到记录: type={log_type} content={content[:50]!r}")
				log_id = int(row[0])
				cls._id_cache[key] = log_id
				if cls._content_map is not None:
						cls._content_map[log_id] = content
				return log_id

		@classmethod
		def encode(cls, log_obj: Dict[str, Any]) -> str:
				"""原文日志对象 {"模块": ["条目", ...]} -> ID 结构 JSON 字符串"""
				pairs: List[List[Any]] = []
				for module, lines in log_obj.items():
						if not isinstance(module, str) or not module:
								continue
						if not isinstance(lines, list):
								lines = [lines]
						line_ids = [cls.get_or_create(cls.TYPE_LOG, str(line)) for line in lines]
						pairs.append([cls.get_or_create(cls.TYPE_MODULE, module), line_ids])
				return json.dumps(pairs, ensure_ascii=False)

		@classmethod
		def encode_value(cls, value: str) -> str:
				"""待写入列的值：原文 JSON -> ID 结构 JSON；已是 ID 结构则原样返回（幂等）"""
				if not value:
						return value
				try:
						parsed = json.loads(value)
				except (json.JSONDecodeError, TypeError):
						return value
				if cls.is_encoded(parsed):
						return value
				if isinstance(parsed, dict):
						return cls.encode(parsed)
				return value

		# ---------------- 导出侧：decode ----------------

		@classmethod
		def load_map(cls) -> Dict[int, str]:
				"""全量载入 logs 表（id -> content），导出时纯内存映射，零额外查询"""
				if cls._content_map is None:
						cls.ensure_table()
						rows = DatabaseManager.query_all("SELECT `id`, `content` FROM `logs`")
						cls._content_map = {int(r[0]): r[1] for r in rows}
						logger.info(f"logs 表已载入内存: {len(cls._content_map)} 条")
				return cls._content_map

		@classmethod
		def decode(cls, pairs: List[List[Any]]) -> Dict[str, Any]:
				"""ID 结构 -> 原文日志对象（缺失 ID 跳过，保持顺序）"""
				id_map = cls.load_map()
				result: Dict[str, Any] = {}
				for item in pairs:
						if not (isinstance(item, list) and len(item) == 2):
								continue
						module = id_map.get(int(item[0]))
						if module is None:
								continue
						lines = [id_map[int(lid)] for lid in item[1]
										 if isinstance(lid, int) and int(lid) in id_map]
						result[module] = lines
				return result

		@classmethod
		def decode_value(cls, parsed: Any) -> Any:
				"""解析后的列值：ID 结构 -> 原文对象；其余（旧格式/异常值）原样返回"""
				if cls.is_encoded(parsed):
						return cls.decode(parsed)
				return parsed

		@classmethod
		def normalize_json(cls, value: Any) -> Any:
				"""比较用归一化：ID 结构解码为原文对象，其余原样返回解析结果"""
				if not value or not isinstance(value, str):
						return value
				try:
						parsed = json.loads(value)
				except (json.JSONDecodeError, TypeError):
						return value
				return cls.decode_value(parsed)

		# ---------------- 迁移辅助：批量 ----------------

		@classmethod
		def bulk_prime(cls, contents: Set[Tuple[str, str]], batch: int = 1000) -> int:
				"""批量插入 (type, content) 集合并刷新缓存，返回新增条数（近似）"""
				if not contents:
						return 0
				cls.ensure_table()
				items = sorted(contents)
				before = cls._count()
				for i in range(0, len(items), batch):
						chunk = items[i:i + batch]
						placeholders = ",".join(["(%s, %s, %s)"] * len(chunk))
						params: List[str] = []
						for log_type, content in chunk:
								params.extend([log_type, content, cls._hash(content)])
						DatabaseManager.execute(
								f"INSERT IGNORE INTO `logs` (`type`, `content`, `content_hash`) VALUES {placeholders}",
								params=tuple(params),
								raise_on_error=True,
						)
				cls.refresh_cache()
				return max(0, cls._count() - before)

		@classmethod
		def refresh_cache(cls) -> None:
				"""全量刷新两个方向的缓存"""
				rows = DatabaseManager.query_all("SELECT `id`, `type`, `content` FROM `logs`")
				cls._id_cache = {(r[1], r[2]): int(r[0]) for r in rows}
				cls._content_map = {int(r[0]): r[2] for r in rows}

		@classmethod
		def _count(cls) -> int:
				row = DatabaseManager.query_one("SELECT COUNT(*) FROM `logs`")
				return int(row[0]) if row else 0
