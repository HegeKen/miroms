"""
全量 OTA 检测：对非特殊分支在版本号第三段尝试 -3 到 +2 偏移，遍历每个 ROM 条目。
来源: HyperOS.fans OTAFull.py + NuxtMR OTAFull.py
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import common


def get_device_branches_with_roms(device: str):
	"""从数据库获取设备所有分支及其 ROM 列表"""
	branch_rows = common.DatabaseManager.query_all(
		"SELECT DISTINCT d.code, d.tag, d.region, d.branchcode "
		"FROM devices d WHERE d.device = %s",
		params=(device,)
	)

	branches = []
	for row in branch_rows:
		code, tag, region, branchcode = row
		if not code:
			continue

		# 获取该分支所有 ROM 版本
		roms = common.DatabaseManager.query_all(
			"SELECT version, android, zone, branch FROM roms "
			"WHERE device = %s AND code = %s ORDER BY id DESC",
			params=(device, code)
		)

		rom_list = {}
		for rom in roms:
			ver = rom[0]
			if ver and ver not in rom_list:
				rom_list[ver] = {
					'android': rom[1],
					'zone': rom[2],
					'branch': rom[3],
				}

		# 获取最新 ROM 信息
		latest = roms[0] if roms else None

		branches.append({
			'code': code,
			'tag': tag or '',
			'region': region or 'cn',
			'branchCode': branchcode or '',
			'zone': latest[2] if latest else (1 if region == 'cn' else 2),
			'branchtag': latest[3] if latest else 'F',
			'version': latest[0] if latest else '',
			'android': latest[1] if latest else '',
			'rom_list': rom_list,
		})
	return branches


def get_existing_versions(device: str):
	"""获取设备所有已知版本号"""
	versions = set()
	rows = common.DatabaseManager.query_all(
		"SELECT version FROM roms WHERE device = %s AND version IS NOT NULL",
		params=(device,)
	)
	for row in rows:
		if row[0]:
			versions.add(row[0])
	return versions


def main() -> None:
	print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始全量 OTA 检测...")
	devices = common.currentStable

	for device in devices:
		branches = get_device_branches_with_roms(device)
		existing_versions = get_existing_versions(device)

		for br in branches:
			code = br['code']
			region = br['region']
			zone = br['zone']
			btag = br['branchtag']
			version = br['version']
			android = br['android']

			is_special = (btag == 'X' or btag == 'D')

			if is_special:
				if version:
					print(f"\r{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 正在检测 {device} {code} {version}", end="", flush=True)
					form_json = common.FirmwareParser.build_ota_form(device, code, region, btag, zone, android, version)
					encrypted = common.CryptoManager.encrypt(form_json)
					common.NetworkClient.fetch_and_check(encrypted)
			else:
				# 遍历每个已知 ROM 版本，尝试偏移
				for rom_ver in br['rom_list']:
					if not rom_ver:
						continue
					try:
						ver_parts = rom_ver.split('.')
						if len(ver_parts) >= 3:
							base_num = int(ver_parts[2])
						else:
							continue
					except (ValueError, IndexError):
						continue

					for offset in range(-3, 3):
						new_num = base_num + offset
						if new_num <= 0:
							continue

						# 构建新版本号
						ver_parts_copy = rom_ver.split('.')
						ver_parts_copy[2] = str(new_num)
						new_ver = '.'.join(ver_parts_copy)

						if new_ver in existing_versions:
							continue

						print(f"\r{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 正在检测 {device} {code} {new_ver}", end="", flush=True)
						form_json = common.FirmwareParser.build_ota_form(device, code, region, btag, zone, android, new_ver)
						encrypted = common.CryptoManager.encrypt(form_json)
						common.NetworkClient.fetch_and_check(encrypted)

	print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 全量 OTA 检测完成")


if __name__ == '__main__':
	main()
