"""
从小米社区 (Mi Community) API 获取各地区线刷包列表。
来源: NuxtMR MGCGetFastboot.py
"""
import sys
import json
import requests
from pathlib import Path
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

sys.path.insert(0, str(Path(__file__).parent))

import common

DOMAINS = [
	'https://sgp-api.buy.mi.com/bbs/api/',
	'https://ams-api.buy.mi.com/bbs/api/',
]
PARAMS = '/phone/getlinepackagelist'
REGIONS = [
	'global', 'rs', 'bd', 'id', 'my', 'pk', 'ph', 'tr', 'vn', 'th',
	'de', 'es', 'fr', 'it', 'pl', 'uk', 'ru', 'ua', 'mie', 'br',
	'co', 'mx', 'pe', 'cl', 'ng', 'eg',
]
HEADERS = {'Connection': 'close'}


def main() -> None:
	print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始从小米社区获取线刷包...")

	# 生成所有 URL
	urls = []
	for region in REGIONS:
		for domain in DOMAINS:
			url = domain + region + PARAMS
			if url not in urls:
				urls.append(url)

	for url in urls:
		session = requests.Session()
		retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
		session.mount('http://', HTTPAdapter(max_retries=retries))
		session.mount('https://', HTTPAdapter(max_retries=retries))

		print(f"\r{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {url}", end="", flush=True)
		try:
			response = session.post(url, headers=HEADERS, timeout=(5, 10))
			if response.status_code != 404:
				content = response.content.decode('utf8')
				packages = json.loads(content).get('data')
				if packages and packages != "null":
					for package in packages:
						fastboot = package['package_url'].split('/')[4].split('?')[0]
						common.DataRecorder.check_exists(fastboot)
		except (requests.exceptions.RequestException, json.JSONDecodeError, IndexError, KeyError):
			pass
		finally:
			session.close()

	print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 小米社区线刷包检测完成")


if __name__ == '__main__':
	main()
