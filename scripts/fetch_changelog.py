"""
批量获取 ROM 的更新日志（changelog），按语种分别写入 roms 表对应的 logs_* 列。

语种与列名的对应关系集中在 miroms/constants.py 的 CHANGELOG_LOCALES，
新增语种只需在那里登记 + 给 roms 表加同名列（见 db_structure/migrations/）。

运行逻辑（按 ROM id 批量，而非按语种逐遍扫表）：
1. 每个语种各查一次 `WHERE logs_<lang> IS NULL`，把待补的 id 存进该语种的数组；
2. 遍历所有 id 的并集（由新到旧，id 从大到小），同一个 id 只查一次数据库拿到 ROM 信息、
   只构建一次请求表单；命中的多个语种共用这份表单，仅替换 l 参数各请求一次；
3. 每个语种处理完就把该 id 从对应数组中删除，处理下一个 id；
4. 接口没有该语种译文时会回落英文，检测到与 logs_en 完全相同即跳过（列保持 NULL），
   需要强制写入时加 --force。
5. 对 cn 区域的记录同时写入 release_date，并从响应中提取卡刷包（recovery）文件名。

写入是逐条 UPDATE 且连接为 autocommit，执行即落库（不会攒到最后统一提交）；
写入失败不再被静默忽略——会计入 write_failed 并打印首个错误。

用法：
    python3 data/scripts/fetch_changelog.py                     # 依次补全所有语种
    python3 data/scripts/fetch_changelog.py --langs ja,ko,ru    # 只处理指定语种
    python3 data/scripts/fetch_changelog.py --probe 5           # 探测接口对哪些语种真的返回了译文
    python3 data/scripts/fetch_changelog.py --dry-run --limit 5 # 只看会写什么，不落库
    python3 data/scripts/fetch_changelog.py --min-id 0 --limit 50
    python3 data/scripts/fetch_changelog.py --force --sleep 0.3

来源: HyperOS.fans test2.py (Changelog)
"""
import argparse
import json
import sys
import time
from pathlib import Path
from datetime import date, datetime

sys.path.insert(0, str(Path(__file__).parent))

import common

# 单个 ROM 的数据库字段（一次查询供该 id 的所有语种复用）
ROM_INFO_SQL = (
	"SELECT device, code, region, branch, android, version, zone, logs_en "
	"FROM roms WHERE id = %s"
)

# 请求表单里接口真正读取的区域字段是小写 r（HyperOSForm 模板默认 "CN"）。
# 历史实现误写成大写 R，导致所有请求都按 CN 查询、国际/EEA 机型拿不到日志。
# 取值：CN / GL 沿用接口模板与 miroms/firmware.py 的 OTA 请求，其余区域用 roms.region 原值
# （如 mist_eea_global → eea）。若接口要求大写，只需改这张表：
REGION_FIELD_OVERRIDES = {'cn': 'CN', 'global': 'GL'}


def region_field(region: str) -> str:
	"""把数据库 roms.region 映射为请求表单的 r 字段"""
	code = str(region or '').strip().lower()
	return REGION_FIELD_OVERRIDES.get(code, code)


# 补充新列用到的迁移脚本（缺列时提示）
MIGRATION_FILE = 'db_structure/migrations/20260919_add_roms_changelog_locales.sql'


def os_replace(ver: str) -> str:
	"""版本号 OS1 替换为 V816"""
	if 'OS1' in ver:
		return ver.replace('OS1', 'V816')
	return ver


def print_target() -> None:
	"""打印实际连接的数据库，避免「脚本跑完但看的是另一个库」"""
	try:
		import config as db_config
		print(f"数据库：{db_config.user}@{db_config.host}:{db_config.port}/{db_config.database}"
			  f"（autocommit，逐条 UPDATE，执行即落库）")
	except Exception as exc:  # config 缺失/导入失败不应中断主流程
		print(f"（无法读取数据库配置：{type(exc).__name__}: {exc}）")


def verify_columns(locales: list[dict]) -> None:
	"""确认 roms 表已有各语言列；缺列时给出迁移指引并退出

	否则 `WHERE logs_ja IS NULL` 会被 DatabaseManager 静默吞掉，
	表现为「待补 0 条、什么都没写」。
	"""
	try:
		rows = common.DatabaseManager.execute(
			"SHOW COLUMNS FROM roms", fetch_one=False, raise_on_error=True
		)
	except Exception as exc:
		print(f"✖ 无法读取 roms 表结构：{type(exc).__name__}: {exc}")
		print("  请检查 scripts/config.py 里的 host / database 是否正确、数据库是否可连")
		sys.exit(1)

	existing = {row[0] for row in rows or []}
	missing = [cfg['column'] for cfg in locales if cfg['column'] not in existing]
	if missing:
		print(f"✖ roms 表缺少以下列：{', '.join(missing)}")
		print(f"  请先执行迁移：mysql <库名> < {MIGRATION_FILE}")
		print("  （或直接执行 db_structure/roms.sql 中对应的 ADD COLUMN 语句）")
		sys.exit(1)


def build_changelog_form(info: dict) -> dict:
	"""构造与语种无关的请求表单；同一 ROM 的多个语种复用同一份，仅替换 l"""
	form = dict(common.HyperOSForm)

	form['d'] = info['code']
	# 接口读取的是小写 r（区域）；大写 R 是历史误加字段，已移除
	form['r'] = region_field(info['region'])
	form['b'] = info['branch']
	form['pn'] = info['code'].split('_global')[0] if '_global' in info['code'] else info['code']
	form['c'] = info['android']
	form['sdk'] = common.sdk.get(info['android'], '36')
	form['p'] = info['device']
	form['options'] = dict(form.get('options', {}))
	# zone 直接取数据库 roms.zone（1=中国、2=国际），不按 region 推断
	form['options']['zone'] = info['zone']
	form['options']['cv'] = os_replace(info['version'])
	form['v'] = os_replace(info['version'])
	form['ov'] = os_replace(info['version'])

	return form


def get_changelog_for_device(info: dict, lang: str, form: dict | None = None) -> dict | None:
	"""获取单个设备指定语言的 changelog

	form 为 build_changelog_form() 的结果；同一 ROM 请求多个语种时传入复用即可，
	此时只替换 l 参数，其余字段完全一致。
	"""
	if form is None:
		form = build_changelog_form(info)

	payload = dict(form)
	payload['l'] = lang
	# print(f"请求 {lang}：",json.dumps(payload))

	encrypted_form = common.CryptoManager.encrypt(json.dumps(payload))
	return common.ChangelogManager.fetch_for_db(encrypted_form, info['device'], info['version'])


def is_same_log(left: str | None, right: str | None) -> bool:
	"""比较两条日志 JSON 是否等价（用于判断接口是否回落到英文）"""
	if not left or not right:
		return False
	try:
		return json.loads(left) == json.loads(right)
	except (json.JSONDecodeError, TypeError):
		return str(left).strip() == str(right).strip()


def write_log_column(rom_id: int, column: str, log: str, region: str,
					 stats: dict, per_locale: dict, dry_run: bool = False) -> bool:
	"""写入单个语种的日志（cn 区域同时写 release_date）

	DatabaseManager.execute 默认会把 SQL 异常吞成 None，这里用 raise_on_error=True
	让失败显形：计入 write_failed 并打印首个错误，避免「报告写入 N 但库里没有」。
	"""
	prefix = "[dry-run] " if dry_run else ""
	if dry_run:
		stats['updated'] += 1
		per_locale[column]['updated'] += 1
		if stats['updated'] <= 3:
			print(f"\n{prefix}将写入 {column} id={rom_id}: {str(log)[:80]}...")
		return True

	try:
		if region == 'cn':
			common.DatabaseManager.execute(
				f"UPDATE roms SET {column} = %s, release_date = %s WHERE id = %s",
				params=(log, date.today().strftime('%Y-%m-%d'), rom_id),
				raise_on_error=True
			)
		else:
			common.DatabaseManager.execute(
				f"UPDATE roms SET {column} = %s WHERE id = %s",
				params=(log, rom_id),
				raise_on_error=True
			)
	except Exception as exc:
		stats['write_failed'] += 1
		per_locale[column]['write_failed'] += 1
		if stats['write_failed'] == 1:
			print(f"\n✖ 写入失败（{column} id={rom_id}）：{type(exc).__name__}: {exc}")
		return False

	stats['updated'] += 1
	per_locale[column]['updated'] += 1
	if stats['updated'] == 1:
		print(f"\n✓ 首次写入成功：{column} id={rom_id} {str(log)[:80]}...")
	return True


def select_locales(names: list[str] | None) -> list[dict]:
	"""按 --langs 解析语种配置；不传则返回全部语种"""
	if not names:
		return list(common.CHANGELOG_LOCALES)

	selected = []
	unknown = []
	for name in names:
		item = common.find_changelog_locale(name)
		if item:
			selected.append(item)
		else:
			unknown.append(name)
	if unknown:
		valid = ', '.join(f"{i['column']}({i['api']})" for i in common.CHANGELOG_LOCALES)
		raise SystemExit(f"未知语种: {', '.join(unknown)}\n可选: {valid}")
	return selected


def collect_pending_ids(locales: list[dict], min_id: int = 0, limit: int = 0) -> dict:
	"""每个语种查一次库，返回 {列名: [待补 id...]}（由新到旧）"""
	pending: dict[str, list[int]] = {}
	for cfg in locales:
		column = cfg['column']
		try:
			result = common.DatabaseManager.execute(
				f"SELECT id FROM roms WHERE logs_zh IS NULL AND branch != 'X' AND (tag != 'CnOB' OR tag IS NULL) ORDER BY id DESC",
				fetch_one=False, raise_on_error=True
			)
		except Exception as exc:
			print(f"✖ 查询 {column} 待补记录失败：{type(exc).__name__}: {exc}")
			sys.exit(1)

		# SQL 已按 id DESC 返回，这里保持「由新到旧」，--limit 截断的就是最新的 N 条
		ids = [row[0] for row in result or []]
		raw_total = len(ids)
		if min_id:
			ids = [rom_id for rom_id in ids if rom_id > min_id]
		if limit:
			ids = ids[:limit]
		pending[column] = ids
		note = ''
		if min_id or limit:
			note = f"（共 {raw_total} 条"
			if min_id:
				note += f"，--min-id {min_id} 后 {len(ids)} 条"
			if limit:
				note += f"，--limit {limit} 截断"
			note += '）'
		print(f"{cfg['name']:<16} {cfg['api']:<6} → {column:<12} 待补 {len(ids)} 条{note}")
	return pending


def fetch_changelogs(locales: list[dict], min_id: int = 46000, limit: int = 0,
					 force: bool = False, sleep: float = 0.0, dry_run: bool = False,
					 print_form: bool = False) -> dict:
	"""按 ROM id 遍历，同一个 id 命中的多个语种只查一次库、只构建一次表单"""
	pending = collect_pending_ids(locales, min_id=min_id, limit=limit)

	# 待补集合：{列名: set(id)}，处理完一个语种就从对应集合里删掉该 id
	pending_sets = {column: set(ids) for column, ids in pending.items()}
	# reverse=True：所有语种并集后仍按 id 从大到小，主循环从最新的 ROM 开始请求
	all_ids = sorted(set().union(*pending_sets.values()), reverse=True) if pending_sets else []

	stats = {
		'total_ids': len(all_ids),
		'updated': 0, 'fallback': 0, 'empty': 0, 'failed': 0, 'missing': 0,
		'write_failed': 0, 'dry_run': dry_run,
		'print_form': print_form, '_first_form': None,
	}
	per_locale = {
		cfg['column']: {'updated': 0, 'fallback': 0, 'empty': 0, 'failed': 0, 'write_failed': 0}
		for cfg in locales
	}

	if not all_ids:
		print("没有需要处理的记录（各语种待补数组都为空）")
		stats['per_locale'] = per_locale
		return stats

	print(f"\n共 {len(all_ids)} 个 ROM 需要补日志，开始处理..."
		  f"{'（dry-run：不会写库）' if dry_run else ''}")

	# 英文列自身与中文列不需要做「回落英文」判断
	check_fallback = {
		cfg['column']: cfg['column'] not in ('logs_zh', common.CHANGELOG_BASE_COLUMN)
		for cfg in locales
	}

	for idx, rom_id in enumerate(all_ids, 1):
		# 命中该 id 的语种（存在时只替换 locale 重新请求）
		targets = [cfg for cfg in locales if rom_id in pending_sets[cfg['column']]]
		if not targets:
			continue

		# 每个 id 只查一次库、只构建一次表单
		info_row = common.DatabaseManager.query_one(ROM_INFO_SQL, params=(rom_id,))
		if not info_row:
			stats['missing'] += 1
			for cfg in targets:
				pending_sets[cfg['column']].discard(rom_id)
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
		logs_en = info_row[7]
		form = build_changelog_form(info)

		columns = ','.join(cfg['column'] for cfg in targets)
		if len(stats) and stats.get('_first_form') is None:
			stats['_first_form'] = dict(form, l=targets[0]['api'])
			print(f"首个请求：d={form['d']} pn={form['pn']} r={form['r']} zone={form['options']['zone']} "
				  f"v={form['v']} l={targets[0]['api']}")
			if stats.get('print_form'):
				print(json.dumps(stats['_first_form'], ensure_ascii=False, indent=2))
		print(f"\r{rom_id} {info['version']} {info['device']} {idx}/{len(all_ids)} [{columns}]",
			  end="", flush=True)

		for cfg in targets:
			column = cfg['column']
			# 同一份表单，仅替换 l
			api_result = get_changelog_for_device(info, cfg['api'], form=form)
			pending_sets[column].discard(rom_id)

			if not api_result:
				stats['failed'] += 1
				per_locale[column]['failed'] += 1
				if sleep:
					time.sleep(sleep)
				continue

			log = api_result.get("changelog")
			recovery = api_result.get("recovery", "")

			if log:
				if check_fallback[column] and not force and is_same_log(log, logs_en):
					# 接口没有该语种译文，返回了与英文相同的文本，跳过写入以免存一堆英文副本
					stats['fallback'] += 1
					per_locale[column]['fallback'] += 1
				else:
					write_log_column(rom_id, column, log, info['region'], stats, per_locale, dry_run)
			else:
				stats['empty'] += 1
				per_locale[column]['empty'] += 1

			# 更新 recovery 卡刷包（仅当数据库中为空时）
			if recovery and not dry_run:
				try:
					common.DatabaseManager.execute(
						"UPDATE roms SET recovery = %s WHERE id = %s AND (recovery IS NULL OR recovery = '')",
						params=(recovery, rom_id), raise_on_error=True
					)
				except Exception as exc:
					if stats['write_failed'] == 0:
						print(f"\n✖ 更新 recovery 失败（id={rom_id}）：{type(exc).__name__}: {exc}")

			if sleep:
				time.sleep(sleep)

	print()
	print("\n各语种处理结果（写入 / 回落英文跳过 / 无日志 / 请求失败 / 写入失败）：")
	for cfg in locales:
		s = per_locale[cfg['column']]
		print(f"    {cfg['column']:<12} {cfg['api']:<6} {s['updated']} / {s['fallback']} / "
			  f"{s['empty']} / {s['failed']} / {s['write_failed']}")

	if stats['updated'] == 0 and not dry_run:
		print("\n⚠ 本次没有任何写入，常见原因：")
		print("   1) 接口对所有语种都返回英文原文（回落）→ 先跑 `--probe 5` 确认；确需写入加 `--force`")
		print(f"   2) 待补数组为空（如 --min-id {min_id} 过滤掉了全部记录）→ 用 `--min-id 0` 重试")
		print("   3) 写入被数据库拒绝 → 看上面的 write_failed 计数与首个报错")

	stats['per_locale'] = per_locale
	return stats


def probe(locales: list[dict], limit: int = 3, sleep: float = 0.0) -> None:
	"""探测接口对各语种的返回情况：拿最近若干条已有英文日志的记录逐语种比对。"""
	rows = common.DatabaseManager.execute(
		"SELECT id, device, code, region, branch, android, version, zone, logs_en FROM roms "
		"WHERE logs_en IS NOT NULL AND logs_en != '' AND branch != 'X' ORDER BY id DESC LIMIT %s",
		params=(limit,), fetch_one=False
	)
	if not rows:
		print("没有可用于探测的记录（需要已有 logs_en 的记录）")
		return

	print(f"用最近 {len(rows)} 条记录探测 {len(locales)} 个语种：\n")

	summary = {cfg['column']: {'translated': 0, 'fallback': 0, 'empty': 0, 'failed': 0} for cfg in locales}

	for row in rows:
		info = {
			'device': row[1], 'code': row[2], 'region': row[3], 'branch': row[4],
			'android': row[5], 'version': row[6], 'zone': row[7],
		}
		logs_en = row[8]
		print(f"--- {info['device']} {info['version']} ({info['region']})")

		form = build_changelog_form(info)
		for cfg in locales:
			api_result = get_changelog_for_device(info, cfg['api'], form=form)
			if api_result is None:
				status = '请求失败'
				summary[cfg['column']]['failed'] += 1
			else:
				log = api_result.get('changelog')
				if not log:
					status = '接口无日志'
					summary[cfg['column']]['empty'] += 1
				elif is_same_log(log, logs_en):
					status = '与英文相同（无译文）'
					summary[cfg['column']]['fallback'] += 1
				else:
					parsed = json.loads(log)
					status = f'有独立译文：{next(iter(parsed), "")}'
					summary[cfg['column']]['translated'] += 1
			print(f"    {cfg['column']:12} {cfg['api']:6} {status}")
			if sleep:
				time.sleep(sleep)

	print('\n汇总（有译文 / 回落英文 / 接口无日志 / 失败）：')
	for cfg in locales:
		s = summary[cfg['column']]
		print(f"    {cfg['column']:12} {cfg['api']:6} {s['translated']} / {s['fallback']} / {s['empty']} / {s['failed']}")
	print('\n提示：若能拿到译文的语种很少，说明小米接口只提供少数语言的更新日志。')


def main() -> None:
	parser = argparse.ArgumentParser(description='获取 ROM 更新日志（多语种，按 ROM id 批量）')
	parser.add_argument('--langs', help='只处理指定语种，逗号分隔（可用列名 logs_ja / api locale ja_JP / 站点 locale ja / 语言名）')
	parser.add_argument('--min-id', type=int, default=46000, help='只处理 id 大于该值的记录，默认 46000；传 0 处理全表')
	parser.add_argument('--limit', type=int, default=0, help='每个语种最多收集多少条待补记录（按 id 从大到小，即最新的 N 条），0 表示不限')
	parser.add_argument('--force', action='store_true', help='接口回落英文时也写入（默认跳过，列保持 NULL）')
	parser.add_argument('--dry-run', action='store_true', help='只打印将要写入的内容，不落库')
	parser.add_argument('--print-form', action='store_true', help='打印首个请求的完整表单 JSON（核对 r / pn / zone 等字段）')
	parser.add_argument('--sleep', type=float, default=0.0, help='每次接口请求后的间隔秒数，默认 0')
	parser.add_argument('--probe', type=int, nargs='?', const=3, default=None,
						metavar='N', help='探测接口语种支持情况（默认取最近 3 条记录），不写库')
	args = parser.parse_args()

	locales = select_locales([x.strip() for x in args.langs.split(',')] if args.langs else None)

	print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始获取 changelog...")
	print_target()
	# 探测只需要 logs_en 列，方便在补列之前先确认接口支持哪些语种
	verify_columns([common.find_changelog_locale(common.CHANGELOG_BASE_COLUMN)]
				   if args.probe is not None else locales)

	if args.probe is not None:
		probe(locales, limit=args.probe, sleep=args.sleep)
		print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 探测完成")
		return

	stats = fetch_changelogs(locales, min_id=args.min_id, limit=args.limit,
							 force=args.force, sleep=args.sleep, dry_run=args.dry_run,
							 print_form=args.print_form)

	print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] changelog 获取完成："
		  f"{stats['total_ids']} 个 ROM，写入 {stats['updated']}，回落英文跳过 {stats['fallback']}，"
		  f"无日志 {stats['empty']}，请求失败 {stats['failed']}，写入失败 {stats['write_failed']}，"
		  f"记录缺失 {stats['missing']}")


if __name__ == '__main__':
	main()
