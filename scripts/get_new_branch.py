"""
遍历所有设备和分支，通过 Fastboot API 和 OTA API 检测未收录的 ROM。
合并自 HyperOS.fans getNewBranch.py + NuxtMR findNewBranches.py
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import common

INCREMENT = ["1", "100", "200", "300"]
ONE_DEVICES = ['warm']
BASE_URL = "https://update.intl.miui.com/updates/miota-fullrom.php?d="


def get_device_info(device: str) -> dict | None:
	"""从数据库获取设备信息"""
	info = common.DatabaseManager.query_one(
		"SELECT code FROM devices WHERE device = %s LIMIT 1",
		params=(device,)
	)
	if not info:
		return None

	code = info[0] or device

	# Android 版本列表
	android_rows = common.DatabaseManager.query_all(
		"SELECT DISTINCT android FROM roms WHERE device = %s AND android IS NOT NULL AND android != ''",
		params=(device,)
	)
	andvs = [row[0] for row in android_rows if row[0]]
	if not andvs:
		andvs = ['14.0']

	# OS 大版本列表
	os_rows = common.DatabaseManager.query_all(
		"SELECT DISTINCT bigver FROM roms WHERE device = %s AND bigver IS NOT NULL AND bigver != ''",
		params=(device,)
	)
	oss = [row[0] for row in os_rows if row[0]]
	if not oss:
		oss = ['OS2.0']

	# 已知版本号集合
	ver_rows = common.DatabaseManager.query_all(
		"SELECT version FROM roms WHERE device = %s AND version IS NOT NULL",
		params=(device,)
	)
	known_versions = {row[0] for row in ver_rows if row[0]}

	return {
		'device': device,
		'code': code,
		'android': andvs,
		'supports': oss,
		'known': known_versions,
	}


def get_known_branch_codes() -> set:
	"""获取数据库中已知的 device+code 组合"""
	known = set()
	rows = common.DatabaseManager.query_all(
		"SELECT device, code FROM devices WHERE code IS NOT NULL AND code != ''"
	)
	for row in rows:
		known.add((row[0], row[1]))
	return known


def main() -> None:
	print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始新分支检测...")

	devices = list(dict.fromkeys(common.currentStable + common.unreleased))
	known_codes = get_known_branch_codes()

	for device in devices:
		devdata = get_device_info(device)
		if not devdata:
			continue

		code = devdata['code']

		for br in common.branches:
			devcode = device + br['code']

			# === 阶段1: Fastboot 查询 ===
			for carrier in br['carrier']:
				if device in ONE_DEVICES:
					url = BASE_URL + devcode + "&b=F&r=&n=" + carrier
				else:
					url = BASE_URL + devcode + "&b=F&r=" + br['region'] + "&n=" + carrier
				print(f"\r{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {url}", end="", flush=True)
				common.NetworkClient.get_fastboot_info(url)

			# === 阶段2: OTA 增量号探测（已知设备） ===
			if code:
				for os_ver in devdata['supports']:
					for andv in devdata['android']:
						for inc in INCREMENT:
							android_code = common.VersionUtils.android_code(andv)
							version = os_ver + "." + inc + ".0." + android_code + code + br['tag']
							if version in devdata['known']:
								continue
							print(f"\r{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 正在检测 {device} {devcode} {version}", end="", flush=True)
							region = '' if device in ONE_DEVICES else br['region']
							form_json = common.FirmwareParser.build_ota_form(device, devcode, region, 'F', br['zone'], andv, version)
							encrypted = common.CryptoManager.encrypt(form_json)
							common.NetworkClient.fetch_and_check(encrypted)

			# === 阶段3: 未知 device+code 组合的 OTA 探测 ===
			elif (device, devcode) not in known_codes:
				if device not in ONE_DEVICES:
					form_json = common.FirmwareParser.build_ota_form(
						device, devcode, br['region'], 'F', br['zone'], '14.0', ''
					)
					encrypted = common.CryptoManager.encrypt(form_json)
					common.NetworkClient.fetch_and_check(encrypted)

	print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 新分支检测完成")


if __name__ == '__main__':
	main()
