import json
from typing import Dict, Any, Optional

from miroms.network import NetworkClient


class ChangelogManager:
		"""
		更新日志管理

		合并原函数:
		- getChangelog() -> fetch() + print_log()
		- getChangelog2DB() -> fetch_for_db()
		- remove_spaces() -> _clean_log()
		- strip_log() -> _strip_log()
		- print_log() -> print_log()
		"""

		@classmethod
		def fetch(cls, encrypted_data: str, device: str) -> Optional[Dict]:
				"""获取更新日志 (原: getChangelog)"""
				result = NetworkClient.call_api(encrypted_data)
				if not result:
						return None

				logs = {}
				if "LatestRom" in result:
						logs["latest"] = cls._strip_log(result["LatestRom"].get("changelog", {}))
				if "CurrentRom" in result:
						logs["current"] = cls._strip_log(result["CurrentRom"].get("changelog", {}))
				return logs

		@classmethod
		def fetch_for_db(cls, encrypted_data: str, device: str,
										 version: str) -> Optional[str]:
				"""获取更新日志用于数据库存储 (原: getChangelog2DB)"""
				result = NetworkClient.call_api(encrypted_data)
				if not result:
						return None

				log = None
				if "CurrentRom" in result and result["CurrentRom"].get("version") == version:
						log = result["CurrentRom"].get("changelog")
				elif "LatestRom" in result and result["LatestRom"].get("version") == version:
						log = result["LatestRom"].get("changelog")

				if log:
						cleaned = cls._clean_log(log)
						stripped = cls._strip_log(cleaned)
						return json.dumps(stripped, ensure_ascii=False)
				return None

		@staticmethod
		def _strip_log(data: Dict) -> Dict:
				"""提取日志文本内容 (原: strip_log)"""
				result = {}
				for key, value in data.items():
						if isinstance(value, dict) and 'txt' in value:
								result[key] = value['txt']
						else:
								result[key] = value
				return result

		@staticmethod
		def _clean_log(d: Any) -> Any:
				"""清理日志中的特殊字符 (原: remove_spaces)"""
				if isinstance(d, dict):
						return {
								k: ChangelogManager._clean_log(v)
								for k, v in d.items()
								if v and not (isinstance(v, str) and v.isspace())
						}
				elif isinstance(d, list):
						return [
								ChangelogManager._clean_log(v)
								for v in d
								if v and not (isinstance(v, str) and v.isspace())
						]
				elif isinstance(d, str):
						return d.replace('\b', '').replace('\t', '').replace('%', '$$')\
										 .replace('"', '^').replace("'", "^").replace('\n', '')
				return d

		@staticmethod
		def print_log(log: Dict):
				"""打印日志内容 (原: print_log)"""
				for module, entries in log.items():
						print(module)
						for entry in (entries if isinstance(entries, list) else [entries]):
								print(entry)
