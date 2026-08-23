"""
从数据库中的设备信息生成 OTA/Fastboot 查询 URL，检测未知的设备+分支组合。
来源: NuxtMR findNewBranches.py
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import common

BASE_URL = "https://update.intl.miui.com/updates/miota-fullrom.php?d="

# 未发布设备不参与检测
ONE_DEVICES = ['klein', 'blue', 'tissot', 'jasmine', 'laurel', 'tiare', 'ice', 'water']


def get_all_branch_codes():
	"""从 constants.py 的 branches 定义中提取所有分支 code"""
	from miroms.constants import branches
	all_codes = []
	for br in branches:
		if br['branch'] == 'F':
			all_codes.append({
				'code': br['code'],
				'region': br['region'],
				'zone': br['zone'],
				'carrier': br['carrier'],
			})
	return all_codes


def main() -> None:
	print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始查找新分支...")

	branch_defs = get_all_branch_codes()
	devices = common.currentStable

	# 获取数据库中已知的 device+code 组合
	known_codes = set()
	rows = common.DatabaseManager.query_all(
		"SELECT device, code FROM devices WHERE code IS NOT NULL AND code != ''"
	)
	for row in rows:
		known_codes.add((row[0], row[1]))

	for device in devices:
		for br in branch_defs:
			dev_code = device + br['code']

			# 检查是否已知
			if (device, dev_code) in known_codes:
				continue

			for carrier in br['carrier']:
				url = BASE_URL + dev_code + "&b=F&r=" + br['region'] + "&n=" + carrier
				print(f"\r{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {url}", end="", flush=True)
				common.NetworkClient.get_fastboot_info(url)

			# 对未知分支也尝试 OTA 查询
			if device not in ONE_DEVICES:
				android_ver = '14.0'
				form_json = common.FirmwareParser.build_ota_form(
					device, dev_code, br['region'], 'F', br['zone'], android_ver, ''
				)
				encrypted = common.CryptoManager.encrypt(form_json)
				common.NetworkClient.fetch_and_check(encrypted)

	print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 新分支检测完成")


if __name__ == '__main__':
	main()
