import logging
from pymysql import Connection
from typing import Set, List, Tuple, Dict, Any, Optional, Union
import config

logger = logging.getLogger(__name__)


class DatabaseManager:
		"""
		数据库操作管理（安全增强版 + 连接复用）

		改进：
		1. 所有查询使用参数化占位符 %s，禁止f-string拼接SQL
		2. 连接复用：批量操作期间共享单个连接，避免反复创建/销毁
		3. 使用上下文管理器确保连接正确关闭
		4. 添加连接超时设置
		"""

		_shared_connection = None

		@classmethod
		def _get_connection(cls) -> Connection:
				"""获取数据库连接（复用共享连接）"""
				if cls._shared_connection is not None:
						try:
								cls._shared_connection.ping(reconnect=True)
								return cls._shared_connection
						except Exception:
								cls._shared_connection = None
				cls._shared_connection = Connection(
						user=config.user,
						password=config.password,
						host=config.host,
						port=config.port,
						database=config.database,
						autocommit=True,
						connect_timeout=10,
						read_timeout=30,
						write_timeout=30
				)
				return cls._shared_connection

		@classmethod
		def _close_shared(cls):
				"""关闭共享连接"""
				if cls._shared_connection is not None:
						try:
								cls._shared_connection.close()
						except Exception:
								pass
						cls._shared_connection = None

		@classmethod
		def execute(
				cls,
				sql: str,
				params: Optional[Union[Tuple, List, Dict]] = None,
				fetch_one: bool = False,
				raise_on_error: bool = False
		) -> Union[Tuple, List[Tuple], None]:
				"""
				执行参数化SQL语句（安全增强版）

				Args:
						sql: SQL语句，使用 %s 作为参数占位符
						params: 查询参数（元组/列表/字典），用于替换 %s 占位符
						fetch_one: 是否只获取单条记录
						raise_on_error: 出错时是否抛出异常。默认 False 保持历史行为（只记日志并返回 None，调用方无法区分
								「失败」与「空结果」）；写入类调用建议传 True，避免写失败被静默忽略。

				Returns:
						查询结果：单条记录（元组）或所有记录（列表）；出错且 raise_on_error=False 时返回 None
				"""
				cnx = None
				cursor = None
				owns_connection = False

				try:
						cnx = cls._get_connection()
						owns_connection = (cnx is cls._shared_connection)
						cursor = cnx.cursor()

						cursor.execute(sql, params or ())

						if fetch_one:
								return cursor.fetchone()
						else:
								return cursor.fetchall()

				except Exception as e:
						logger.error(f"SQL执行错误: {sql[:100]}..., 错误: {type(e).__name__}: {e}")
						if raise_on_error:
								raise
						return None

				finally:
						if cursor:
								cursor.close()
						# 只在非共享连接时关闭
						if cnx and not owns_connection:
								cnx.close()

		@classmethod
		def insert(
				cls,
				sql: str,
				params: Optional[Union[Tuple, List, Dict]] = None,
				raise_on_error: bool = False
		) -> int:
				"""执行 INSERT 并返回自增主键（lastrowid）

				用途：先查后写时拿到新行 id。不要用 `INSERT ... ON DUPLICATE KEY UPDATE`
				做「有则更新」——命中重复键时 InnoDB 同样会推进 AUTO_INCREMENT，
				反复导入会把 id 烧出一堆空档（dev 表就踩过）。
				"""
				cnx = None
				try:
						cnx = cls._get_connection()
						cursor = cnx.cursor()
						cursor.execute(sql, params or ())
						return int(cursor.lastrowid or 0)
				except Exception as e:
						logger.error(f"SQL执行错误: {sql[:100]}..., 错误: {type(e).__name__}: {e}")
						if raise_on_error:
								raise
						return 0

		@classmethod
		def execute_many(
				cls,
				sql: str,
				seq_params,
				raise_on_error: bool = False
		) -> int:
				"""批量执行同一条参数化 SQL（executemany），返回受影响行数

				适合批量 INSERT / UPDATE（如迁移脚本逐行回写、批量插入 logs）。
				"""
				cnx = None
				cursor = None
				try:
						cnx = cls._get_connection()
						cursor = cnx.cursor()
						cursor.executemany(sql, seq_params)
						return cursor.rowcount if cursor.rowcount and cursor.rowcount > 0 else 0
				except Exception as e:
						logger.error(f"SQL批量执行错误: {sql[:100]}..., 错误: {type(e).__name__}: {e}")
						if raise_on_error:
								raise
						return 0
				finally:
						if cursor:
								cursor.close()

		@classmethod
		def query_one(cls, sql: str, params: Optional[Union[Tuple, List, Dict]] = None) -> Optional[Tuple]:
				"""查询单条记录（参数化安全版）"""
				return cls.execute(sql, params=params, fetch_one=True)

		@classmethod
		def query_all(cls, sql: str, params: Optional[Union[Tuple, List, Dict]] = None) -> List[Tuple]:
				"""查询所有记录（参数化安全版）"""
				result = cls.execute(sql, params=params, fetch_one=False)
				return result if result else []

		@classmethod
		def check_and_update(
				cls,
				filename: str,
				filetype: str,
				device: str,
				code: str,
				android: str,
				version: str,
				rom_type: str,
				bigver: str,
				region: str,
				tag: str,
				zone: int,
				branch: str
		) -> None:
				"""检查 ROM 是否已存在，不存在则插入新记录"""
				existing = cls.query_one(
						"SELECT id FROM roms WHERE code = %s AND version = %s",
						params=(code, version)
				)
				if existing:
						return
				cls.execute(
						"INSERT INTO roms(device, code, type, bigver, region, tag, branch, zone, "
						"version, android, insdate) "
						"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURDATE())",
						params=(device, code, rom_type, bigver, region, tag, branch, zone, version, android)
				)
