"""
批量获取 ROM 的更新日志（changelog），分别处理中文和英文。
对 cn 区域的记录同时写入 release_date。
同时从 API 响应中提取卡刷包（recovery）文件名写入数据库。
来源: HyperOS.fans test2.py (Changelog)
"""
import sys
import json
from pathlib import Path
from datetime import date, datetime

sys.path.insert(0, str(Path(__file__).parent))

import common


def os_replace(ver: str) -> str:
	"""版本号 OS1 替换为 V816"""
	if 'OS1' in ver:
		return ver.replace('OS1', 'V816')
	return ver


def get_changelog_for_device(info: dict, lang: str) -> str | None:
	"""为单个设备获取指定语言的 changelog"""
	form = dict(common.HyperOSForm)

	# 填充表单字段
	form['d'] = info['code']
	form['R'] = info['region']
	form['b'] = info['branch']
	form['pn'] = info['code'].split('_global')[0] if '_global' in info['code'] else info['code']
	form['c'] = info['android']
	form['sdk'] = common.sdk.get(info['android'], '36')
	form['p'] = info['device']
	form['options'] = dict(form.get('options', {}))
	form['options']['zone'] = info['zone']
	form['options']['cv'] = os_replace(info['version'])
	form['v'] = os_replace(info['version'])
	form['ov'] = os_replace(info['version'])
	form['l'] = lang

	encrypted_form = common.CryptoManager.encrypt(json.dumps(form))
	return common.ChangelogManager.fetch_for_db(encrypted_form, info['device'], info['version'])


def fetch_changelogs(lang: str, label: str):
	"""获取指定语言的 changelog + 卡刷包"""
	lang_code = 'zh_CN' if lang == 'zh' else 'en_US'

	# 查询缺失 changelog 的记录
	if lang == 'zh':
		sql = "SELECT id FROM roms WHERE logs_zh IS NULL AND branch != 'X'"
	else:
		sql = "SELECT id FROM roms WHERE logs_en IS NULL AND branch != 'X'"

	result = common.DatabaseManager.execute(sql, fetch_one=False)
	if not result:
		print(f"没有需要处理的 {label} 记录")
		return

	ids = [x[0] for x in result]
	ids.reverse()
	start = 46000
	total = len(ids)

	print(f"共找到 {total} 条 {label} 记录需要处理")

	for idx, rom_id in enumerate(ids, 1):
		if start != 0 and rom_id <= start:
			continue

		info_row = common.DatabaseManager.query_one(
			"SELECT device, code, region, branch, android, version, zone FROM roms WHERE id = %s",
			params=(rom_id,)
		)
		if not info_row:
			continue

		info = {
			'device': info_row[0],
			'code': info_row[1],
			'region': info_row[2],
			'branch': info_row[3],
			'android': info_row[4],
			'version': info_row[5],
			'zone': info_row[6],
		}

		print(f"\r{rom_id} {info['version']} {info['device']} {idx}/{total} {label}", end="", flush=True)

		api_result = get_changelog_for_device(info, lang_code)
		if not api_result:
			continue

		log = api_result.get("changelog")
		recovery = api_result.get("recovery", "")

		# 更新 changelog
		log_column = f'logs_{lang}'
		if log:
			if info['region'] == 'cn':
				common.DatabaseManager.execute(
					f"UPDATE roms SET {log_column} = %s, release_date = %s WHERE id = %s",
					params=(log, date.today().strftime('%Y-%m-%d'), rom_id)
				)
			else:
				common.DatabaseManager.execute(
					f"UPDATE roms SET {log_column} = %s WHERE id = %s",
					params=(log, rom_id)
				)

		# 更新 recovery 卡刷包（仅当数据库中为空时）
		if recovery:
			common.DatabaseManager.execute(
				"UPDATE roms SET recovery = %s WHERE id = %s AND (recovery IS NULL OR recovery = '')",
				params=(recovery, rom_id)
			)

	print(f"\n{label} changelog 处理完成")


def main() -> None:
	print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始获取 changelog...")

	print("\n--- 中文 changelog ---")
	fetch_changelogs('zh', 'zh_CN')

	print("\n--- 英文 changelog ---")
	fetch_changelogs('en', 'en_US')

	print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] changelog 获取完成")


if __name__ == '__main__':
	main()
