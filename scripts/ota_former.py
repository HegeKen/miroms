"""
遍历所有稳定版设备的每个分支，通过 OTA API 检测是否有新版本。
对非特殊分支额外探测后续版本号。
来源: HyperOS.fans OTAFormer.py + NuxtMR OTAFormer.py
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import common


def get_branch_rom_info(device: str, branch_code: str):
	"""从数据库获取指定设备分支的最新 ROM 信息"""
	# 尝试通过 devices 表获取 branchcode 对应的 code
	info = common.DatabaseManager.query_one(
		"SELECT code FROM devices WHERE code = %s OR branchcode = %s",
		params=(branch_code, branch_code)
	)
	if not info:
		return None, None, None

	code = info[0]

	# 获取该 code 的最新 ROM
	rom = common.DatabaseManager.query_one(
		"SELECT version, android, region, tag, zone, branch FROM roms "
		"WHERE code = %s ORDER BY id DESC LIMIT 1",
		params=(code,)
	)
	if not rom:
		return code, None, None

	return code, rom, {
		'version': rom[0],
		'android': rom[1],
		'region': rom[2],
		'tag': rom[3],
		'zone': rom[4],
		'branch': rom[5],
	}


def get_device_branches(device: str):
	"""从数据库获取设备的所有分支信息"""
	rows = common.DatabaseManager.query_all(
		"SELECT DISTINCT d.code, d.tag, d.region, "
		"COALESCE(d.branchcode, ''), d.branchcode "
		"FROM devices d WHERE d.device = %s",
		params=(device,)
	)
	branches = []
	for row in rows:
		code, tag, region, branch_code, branchcode = row
		if not code:
			continue
		# 获取该分支的最新 ROM
		rom = common.DatabaseManager.query_one(
			"SELECT version, android, zone, branch FROM roms "
			"WHERE device = %s AND code = %s ORDER BY id DESC LIMIT 1",
			params=(device, code)
		)
		branches.append({
			'code': code,
			'tag': tag or '',
			'region': region or 'cn',
			'branchCode': branchcode or '',
			'zone': rom[2] if rom else (1 if region == 'cn' else 2),
			'branchtag': rom[3] if rom else 'F',
			'version': rom[0] if rom else '',
			'android': rom[1] if rom else '',
		})
	return branches


def is_special_branch(branch_info: dict) -> bool:
	"""判断是否为特殊分支（开发版/企业版等）"""
	btag = branch_info.get('branchtag', '')
	name_en = branch_info.get('name_en', '')
	return (btag == 'X' or btag == 'D' or
			'Enterprise' in name_en or 'EP' in name_en)


def main() -> None:
	print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始 OTA 检测...")
	devices = common.currentStable

	for device in devices:
		branches = get_device_branches(device)
		for br in branches:
			code = br['code']
			region = br['region']
			zone = br['zone']
			btag = br['branchtag']
			version = br['version']
			android = br['android']

			if not version and not android:
				continue

			is_special = (btag == 'X' or btag == 'D')

			if is_special:
				print(f"\r{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 正在检测 {device} {code} {version}", end="", flush=True)
				form_json = common.FirmwareParser.build_ota_form(device, code, region, btag, zone, android, version)
				encrypted = common.CryptoManager.encrypt(form_json)
				common.NetworkClient.fetch_and_check(encrypted)
			else:
				print(f"\r{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 正在检测 {device} {code} {version}", end="", flush=True)
				form_json = common.FirmwareParser.build_ota_form(device, code, region, btag, zone, android, version)
				encrypted = common.CryptoManager.encrypt(form_json)
				common.NetworkClient.fetch_and_check(encrypted)

				if version:
					for i in range(1, 5):
						new_ver = common.VersionUtils.increment(version, i)
						print(f"\r{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 正在检测 {device} {code} {new_ver}", end="", flush=True)
						form_json = common.FirmwareParser.build_ota_form(device, code, region, btag, zone, android, new_ver)
						encrypted = common.CryptoManager.encrypt(form_json)
						common.NetworkClient.fetch_and_check(encrypted)

	print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] OTA 检测完成")


if __name__ == '__main__':
	main()
