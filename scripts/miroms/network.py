import json
import logging
from typing import Dict, Optional, Union
from urllib.parse import urlencode, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from miroms.constants import _const
from miroms.crypto import CryptoManager
from miroms.recorder import DataRecorder

logger = logging.getLogger(__name__)


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
		def call_api(cls, encrypted_data: str, url: Optional[str] = None,
								 extra: Optional[Dict[str, str]] = None) -> Optional[Dict]:
				"""调用MIUI API基础方法

				encrypted_data 为 CryptoManager.encrypt() 的结果（已 URL 编码）；
				url 缺省为 OTA 检查接口，extra 用于补充分页 / 随机参数（如 getXmsVer 的 n、ts）。
				"""
				data = f"q={encrypted_data}&s=1&t="
				if extra:
						data = f"{data}&{urlencode(extra)}"
				target = url or _const.CHECK_URL
				headers = dict(cls._headers)
				headers["Host"] = urlparse(target).netloc
				session = cls._create_session()
				try:
						response = session.post(
								target,
								headers=headers,
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
		def call_api_form(cls, form: Union[Dict, str], url: Optional[str] = None,
											extra: Optional[Dict[str, str]] = None) -> Optional[Dict]:
				"""用明文表单（字典或 JSON 字符串）调用接口，内部完成加密"""
				return cls.call_api(CryptoManager.encrypt(form), url=url, extra=extra)

		@classmethod
		def fetch_and_check(cls, form: Union[Dict, str]) -> bool:
				"""获取API数据并检查ROM (原: getFromApi)

				form 为 FirmwareParser.build_ota_form() 的表单字典（也兼容旧的加密字符串）。
				找到 LatestRom / CrossRom 时录入 ROM，并顺带解析 XMS（SOTA 应用更新）。
				"""
				if isinstance(form, str):
						try:
								form = json.loads(form)
						except (TypeError, ValueError):
								return False
				result = cls.call_api_form(form)
				if not result:
						return False

				found = False
				for key in ["LatestRom", "CrossRom"]:
						rom = result.get(key) or {}
						filename = rom.get("filename")
						if not filename:
								continue
						package = filename.split("?")[0]
						DataRecorder.check_exists(package)
						found = True

				# XMS 解析失败不应影响 ROM 录入
				try:
						from miroms.xms import XmsStore
						XmsStore.record(form, result)
				except Exception as exc:  # noqa: BLE001 - 抓取流水线不能因新增数据源中断
						logger.warning("XMS 解析失败（%s）：%s: %s",
													 form.get("d"), type(exc).__name__, exc)
				return found

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
								if isinstance(roms, dict):
										# 单个包：直接是字典
										if 'filename' in roms:
												DataRecorder.check_exists(roms['filename'])
								elif isinstance(roms, list) and roms:
										# 包列表：取第一个
										if 'filename' in roms[0]:
												DataRecorder.check_exists(roms[0]['filename'])
				except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError, IndexError):
						pass
				finally:
						session.close()
