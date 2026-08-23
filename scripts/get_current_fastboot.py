"""
遍历所有稳定版设备的每个分支，通过国际版全量 ROM 接口获取当前最新的 Fastboot 包信息。
来源: HyperOS.fans getCurrentFastboot.py + NuxtMR getCurrentFastboot.py
"""
import sys
import ast
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import common

BASE_URL = "https://update.intl.miui.com/updates/miota-fullrom.php?d="


def parse_carriers(value: str | None) -> list[str]:
	"""解析 devices.carrier 字段（字符串形式列表，如 "['','chinatelecom','chinamobile']"）"""
	if not value:
		return ['']
	try:
		parsed = ast.literal_eval(value.strip())
		if isinstance(parsed, (list, tuple)):
			return list(parsed)
	except (ValueError, SyntaxError):
		pass
	# 兜底：按逗号拆分并去除引号与方括号
	return [c.strip().strip("'\"[] ") for c in value.split(',')]


def get_device_branches(device: str):
	"""从数据库获取设备的所有分支"""
	rows = common.DatabaseManager.query_all(
		"SELECT d.code, d.tag, d.region, d.carrier "
		"FROM devices d WHERE d.device = %s AND d.code IS NOT NULL AND d.code != ''",
		params=(device,)
	)
	branches = []
	for row in rows:
		code, tag, region, carrier = row
		if not code:
			continue
		# 获取分支信息
		rom = common.DatabaseManager.query_one(
			"SELECT branch, zone FROM roms "
			"WHERE device = %s AND code = %s ORDER BY id DESC LIMIT 1",
			params=(device, code)
		)
		branches.append({
			'devcode': code,
			'region': region or 'cn',
			'branchtag': rom[0] if rom else 'F',
			'zone': rom[1] if rom else (1 if region == 'cn' else 2),
			'carrier': parse_carriers(carrier),
		})
	return branches


def main() -> None:
	print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始获取当前 Fastboot 信息...")

	devices = common.currentStable

	for device in devices:
		branches = get_device_branches(device)
		for br in branches:
			code = br['devcode']
			if not code:
				print(f"请修补机型: {device} 未指定的区域代码")
				continue

			btag = br['branchtag']
			region = br['region']
			carriers = br['carrier']

			if not carriers or carriers == ['']:
				url = BASE_URL + code + "&b=" + btag + "&r=" + region + "&n="
				print(f"\r{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {url}                           ", end="", flush=True)
				common.NetworkClient.get_fastboot_info(url)
			else:
				for carrier in carriers:
					url = BASE_URL + code + "&b=" + btag + "&r=" + region + "&n=" + carrier
					print(f"\r{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {url}"                           , end="", flush=True)
					common.NetworkClient.get_fastboot_info(url)

	print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Fastboot 信息获取完成")


if __name__ == '__main__':
	main()
