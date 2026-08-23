import json
import requests
from sys import platform
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import List, Tuple, Dict, Optional

from miroms.constants import _const


# ==================== 1. 版本处理工具类 ====================

class VersionUtils:
		"""
		版本号处理工具集合

		合并原函数:
		- android() -> android_code()
		- ver_in_order() -> sort_versions()
		- parse_version() -> parse()
		- compare()
		- versionAdd() -> increment()
		"""

		@classmethod
		def android_code(cls, version: str) -> str:
				"""Android版本号转字母代号 (原: android)"""
				return _const.ANDROID_CODES.get(version, "W")

		@classmethod
		def sdk_version(cls, version: str) -> str:
				"""获取SDK版本号"""
				return _const.SDK_VERSIONS.get(version, "36")

		@staticmethod
		def sort_versions(versions: str) -> List[str]:
				"""对分号分隔的版本号进行排序 (原: ver_in_order)"""
				ver_list = versions.split("; ")
				return sorted(ver_list)

		@staticmethod
		def parse(version: str) -> Optional[Tuple[int, ...]]:
				"""解析版本号为元组用于比较 (原: parse_version)"""
				try:
						if version.startswith("OS"):
								body = version[2:]
						elif version.startswith("A"):
								body = version[1:]
						else:
								return None
						parts = body.split(".")
						return tuple(map(int, parts[:4]))
				except Exception:
						return None

		@classmethod
		def compare(cls, v1: str, v2: str) -> bool:
				"""比较两个版本号，v1 > v2 返回True (原: compare)"""
				p1, p2 = cls.parse(v1), cls.parse(v2)
				if p1 is None or p2 is None:
						return False
				return p1 > p2

		@staticmethod
		def increment(version: str, add: int = 1) -> str:
				"""版本号递增 (原: versionAdd)"""
				parts = version.split(".")
				if len(parts) >= 3:
						parts[2] = str(int(parts[2]) + add)
				if len(parts) > 4:
						return ".".join(parts[:4]) + "." + parts[4]
				return ".".join(parts)

		@staticmethod
		def extract_type(version: str) -> Tuple[str, str]:
				"""从版本号提取系统类型和主版本"""
				if version.startswith('V'):
						return "MIUI", f"MIUI {version.split('V')[1].split('.')[0]}"
				elif version.startswith('OS'):
						return "HyperOS", f"HyperOS {version.split('OS')[1].split('.')[0]}"
				elif version.startswith('A'):
						return "STAN", f"STAN {version.split('.')[0]}"
				return "Unknown", "Unknown"


# ==================== 2. 文件操作工具类 ====================

class FileUtils:
		"""
		文件和路径操作工具

		合并原函数:
		- localData() -> load_device_data()
		- form_url() -> build_ota_url()
		- get_time() -> get_url_last_modified()
		- writeData/writeFlag -> append_to_file()
		"""

		@staticmethod
		def get_base_path() -> str:
				"""获取项目根目录的绝对路径（hub.miuier.com 项目）"""
				return str(Path(__file__).resolve().parent.parent.parent.parent)

		@classmethod
		def load_device_data(cls, codename: str) -> Dict:
				"""加载设备JSON数据 (原: localData)"""
				base = Path(cls.get_base_path()) / "data" / "devices"
				path = base / f"{codename}.json"
				with open(path, 'r', encoding='utf-8') as f:
						return json.load(f)

		@classmethod
		def append_to_file(cls, filename: str, content: str, subdir: str = "scripts/"):
				"""追加内容到文件"""
				base = Path(cls.get_base_path()) / "data"
				path = base / subdir / filename
				path.parent.mkdir(parents=True, exist_ok=True)
				with open(path, 'a', encoding='utf-8') as f:
						f.write(content + "\n")

		@staticmethod
		def get_url_last_modified(url: str) -> str:
				"""获取URL文件的最后修改时间 (原: get_time)"""
				try:
						response = requests.head(url, allow_redirects=True, timeout=10)
						if 'Last-Modified' in response.headers:
								lm = response.headers['Last-Modified']
								dt = datetime.strptime(lm, "%a, %d %b %Y %H:%M:%S %Z") + timedelta(hours=8)
								return dt.strftime("%Y-%m-%d")
				except requests.RequestException:
						pass
				return date.today().strftime("%Y-%m-%d")

		@classmethod
		def build_ota_url(cls, filename: str, version: str) -> str:
				"""构建OTA文件URL (原: form_url)"""
				base = "https://bkt-sgp-miui-ota-update-alisgp.oss-ap-southeast-1.aliyuncs.com"
				return f"{base}/{version}/{filename}"
