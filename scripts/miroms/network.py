import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Optional

from miroms.constants import _const
from miroms.crypto import CryptoManager
from miroms.recorder import DataRecorder


class NetworkClient:
		"""
		网络请求管理

		合并原函数:
		- getFromApi() -> fetch_and_check() / call_api()
		- getFastboot() -> get_fastboot_info()
		"""

		_headers = {
				"user-agent": "Dalvik/2.1.0 (Linux; U; Android 13; MI 9 Build/TKQ1.220829.002)",
				"Connection": "Keep-Alive",
				"Content-Type": "application/x-www-form-urlencoded",
				"Cache-Control": "no-cache",
				"Host": "update.miui.com",
				"Accept-Encoding": "gzip",
				"Cookie": "serviceToken=;"
		}

		@classmethod
		def _create_session(cls, retries: int = 5) -> requests.Session:
				"""创建带重试机制的Session"""
				session = requests.Session()
				retry = Retry(total=retries, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
				session.mount('http://', HTTPAdapter(max_retries=retry))
				session.mount('https://', HTTPAdapter(max_retries=retry))
				return session

		@classmethod
		def call_api(cls, encrypted_data: str) -> Optional[Dict]:
				"""调用MIUI API基础方法"""
				data = f"q={encrypted_data}&s=1&t="
				session = cls._create_session()
				try:
						response = session.post(
								_const.CHECK_URL,
								headers=cls._headers,
								data=data,
								timeout=(5, 10)
						)
						if "code" not in response.text:
								return CryptoManager.decrypt(response.text.split("q=")[0])
				except requests.exceptions.RequestException as e:
						print(f"请求失败: {e}")
				finally:
						session.close()
				return None

		@classmethod
		def fetch_and_check(cls, encrypted_data: str) -> bool:
				"""获取API数据并检查ROM (原: getFromApi)"""
				result = cls.call_api(encrypted_data)
				if not result:
						return False

				for key in ["LatestRom", "CrossRom"]:
						if key in result:
								package = result[key]["filename"].split("?")[0]
								DataRecorder.check_exists(package)
								return True
				return False

		@classmethod
		def get_fastboot_info(cls, url: str):
				"""获取Fastboot信息 (原: getFastboot)"""
				session = cls._create_session(retries=3)
				headers = {
						'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
						'Connection': 'close'
				}
				try:
						response = session.post(url, headers=headers, timeout=(5, 10))
						if response.status_code == 200:
								data = json.loads(response.content.decode('utf8'))
								roms = data.get('LatestFullRom', [])
								if roms:
										DataRecorder.check_exists(roms[0]['filename'])
				except (requests.exceptions.RequestException, json.JSONDecodeError):
						pass
				finally:
						session.close()
