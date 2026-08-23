"""
遍历所有设备和分支，通过 Fastboot API 获取最新包信息，同时通过 OTA API 检测新版本。
来源: NuxtMR NewBranches.py
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import common

BASE_URL = "https://update.intl.miui.com/updates/miota-fullrom.php?d="


def get_device_branches(device: str):
	"""从数据库获取设备的分支信息"""
	rows = common.DatabaseManager.query_all(
		"SELECT d.code, d.tag, d.region, d.branchcode, d.carrier "
		"FROM devices d WHERE d.device = %s AND d.code IS NOT NULL AND d.code != ''",
		params=(device,)
	)
	branches = []
	for row in rows:
		code, tag, region, branchcode, carrier = row
		# 获取分支类型
		rom = common.DatabaseManager.query_one(
			"SELECT branch, zone, android FROM roms "
			"WHERE device = %s AND code = %s ORDER BY id DESC LIMIT 1",
			params=(device, code)
		)
		branches.append({
			'code': branchcode or '',
			'devcode': code,
			'tag': tag or '',
			'region': region or 'cn',
			'zone': rom[1] if rom else (1 if region == 'cn' else 2),
			'branchtag': rom[0] if rom else 'F',
			'android': rom[2] if rom else '14.0',
			'carrier': carrier.split(',') if carrier else [''],
		})
	return branches


def is_special_branch(branch: dict) -> bool:
	"""判断是否为特殊分支"""
	btag = branch['branchtag']
	name = branch.get('devcode', '')
	return btag == 'X' or btag == 'D'


def main() -> None:
	print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始新分支检测...")

	devices = common.currentStable

	for device in devices:
		branches = get_device_branches(device)
		if not branches:
			continue

		# 获取设备已知版本
		existing_versions = set()
		ver_rows = common.DatabaseManager.query_all(
			"SELECT version FROM roms WHERE device = %s AND version IS NOT NULL",
			params=(device,)
		)
		for row in ver_rows:
			if row[0]:
				existing_versions.add(row[0])

		for br in branches:
			devcode = br['devcode']
			code = br['code']
			region = br['region']
			zone = br['zone']
			btag = br['branchtag']
			android = br['android']

			if is_special_branch(br):
				continue

			# Fastboot 查询
			for carrier in br['carrier']:
				url = BASE_URL + devcode + "&b=F&r=" + region + "&n=" + carrier
				print(f"\r{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {url}", end="", flush=True)
				common.NetworkClient.get_fastboot_info(url)

			# OTA 查询 - 尝试已知的 os 版本 + 偏移
			os_rows = common.DatabaseManager.query_all(
				"SELECT version FROM roms WHERE device = %s AND code = %s "
				"AND version IS NOT NULL ORDER BY id DESC LIMIT 3",
				params=(device, devcode)
			)
			for os_row in os_rows:
				os_ver = os_row[0]
				if not os_ver:
					continue
				try:
					parts = os_ver.split('.')
					if len(parts) >= 3:
						base_num = int(parts[2])
					else:
						continue
				except (ValueError, IndexError):
					continue

				for offset in range(0, 5):
					new_num = base_num + offset
					parts_copy = os_ver.split('.')
					parts_copy[2] = str(new_num)
					new_ver = '.'.join(parts_copy)

					if new_ver in existing_versions:
						continue

					print(f"\r{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {device} {code} {region} F {zone} {android} {new_ver}", end="", flush=True)
					form_json = common.FirmwareParser.build_ota_form(device, code, region, btag, zone, android, new_ver)
					encrypted = common.CryptoManager.encrypt(form_json)
					common.NetworkClient.fetch_and_check(encrypted)

	print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 新分支检测完成")


if __name__ == '__main__':
	main()
