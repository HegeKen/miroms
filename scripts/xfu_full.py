"""
通过国际版全量 ROM 接口获取 Fastboot 包，并用增量号探测 OTA 更新。
来源: HyperOS.fans XfuFull.py
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import common
from miroms.constants import branches


INCREMENT = ["1", "100", "200"]
ONE_DEVICES = ['warm']
BASE_URL = "https://update.intl.miui.com/updates/miota-fullrom.php?d="


def get_xfu_branches():
	"""从 constants.py 的 branches 定义中提取 F 分支"""
	xfu_branches = []
	for br in branches:
		if br['branch'] == 'F':
			xfu_branches.append(br)
	return xfu_branches


def main() -> None:
	print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始 XFU 全量检测...")

	# 合并稳定版和未发布设备
	devices = list(dict.fromkeys(common.currentStable + common.unreleased))
	xfu_branches = get_xfu_branches()

	for device in devices:
		# 从数据库获取设备信息
		info = common.DatabaseManager.query_one(
			"SELECT code, region FROM devices WHERE device = %s LIMIT 1",
			params=(device,)
		)
		if not info:
			continue

		dev_code = info[0] or device
		android_versions = common.DatabaseManager.query_all(
			"SELECT DISTINCT android FROM roms WHERE device = %s AND android IS NOT NULL AND android != ''",
			params=(device,)
		)
		android_list = [row[0] for row in android_versions if row[0]]
		if not android_list:
			android_list = ['14.0']

		os_versions = common.DatabaseManager.query_all(
			"SELECT DISTINCT version FROM roms WHERE device = %s AND version IS NOT NULL AND version != '' "
			"ORDER BY id DESC LIMIT 5",
			params=(device,)
		)
		os_list = [row[0] for row in os_versions if row[0]]

		for br in xfu_branches:
			for os_ver in os_list:
				for andv in android_list:
					devcode = dev_code + br['code']

					for carrier in br['carrier']:
						if device in ONE_DEVICES:
							url = BASE_URL + devcode + "&b=F&r=&n=" + carrier
						else:
							url = BASE_URL + devcode + "&b=F&r=" + br['region'] + "&n=" + carrier
						print(f"\r{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {url}", end="", flush=True)
						common.NetworkClient.get_fastboot_info(url)

					for inc in INCREMENT:
						code_suffix = br['tag']
						if code_suffix:
							code_val = common.DatabaseManager.query_one(
								"SELECT code FROM devices WHERE device = %s AND tag = %s",
								params=(device, code_suffix)
							)
							code_str = code_val[0].split('_')[0] if code_val and code_val[0] else ''
						else:
							code_str = dev_code

						if code_str:
							android_code = common.VersionUtils.android_code(andv)
							version = os_ver + "." + inc + ".0." + android_code + code_str + br['tag']

							# 检查是否已存在
							existing = common.DatabaseManager.query_one(
								"SELECT id FROM roms WHERE device = %s AND version = %s",
								params=(device, version)
							)
							if existing:
								continue

							print(f"\r{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} 正在检测 {device} {devcode} {version}", end="", flush=True)
							region = '' if device in ONE_DEVICES else br['region']
							form_json = common.FirmwareParser.build_ota_form(device, devcode, region, 'F', br['zone'], andv, version)
							encrypted = common.CryptoManager.encrypt(form_json)
							common.NetworkClient.fetch_and_check(encrypted)

	print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] XFU 全量检测完成")


if __name__ == '__main__':
	main()
