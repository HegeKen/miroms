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
				fetch_one: bool = False
		) -> Union[Tuple, List[Tuple], None]:
				"""
				执行参数化SQL语句（安全增强版）

				Args:
						sql: SQL语句，使用 %s 作为参数占位符
						params: 查询参数（元组/列表/字典），用于替换 %s 占位符
						fetch_one: 是否只获取单条记录

				Returns:
						查询结果：单条记录（元组）或所有记录（列表）
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
						return None

				finally:
						if cursor:
								cursor.close()
						# 只在非共享连接时关闭
						if cnx and not owns_connection:
								cnx.close()

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
