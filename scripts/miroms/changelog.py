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
										 version: str) -> Optional[Dict]:
				"""获取更新日志 + 卡刷包信息用于数据库存储"""
				result = NetworkClient.call_api(encrypted_data)
				if not result:
						return None

				log = None
				recovery = None

				# 优先匹配 CurrentRom，其次 LatestRom
				for key in ["CurrentRom", "LatestRom"]:
						if key in result and result[key].get("version") == version:
								rom = result[key]
								log = rom.get("changelog")
								recovery = rom.get("filename", "")
								break

				# 兜底：取 LatestRom 的 recovery（即使版本不完全匹配）
				if not recovery and "LatestRom" in result:
						recovery = result["LatestRom"].get("filename", "")

				cleaned_log = None
				if log:
						cleaned = cls._clean_log(log)
						stripped = cls._strip_log(cleaned)
						cleaned_log = json.dumps(stripped, ensure_ascii=False)

				return {"changelog": cleaned_log, "recovery": recovery or ""}

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
				"""打印日志内容"""
				for module, entries in log.items():
						print(module)
						for entry in (entries if isinstance(entries, list) else [entries]):
								print(entry)
