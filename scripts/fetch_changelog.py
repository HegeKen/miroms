"""
批量获取 ROM 的更新日志（changelog），按语种写入 logs 表的多语言分组，并回写 roms.logs。

更新日志已改为「同一日志的多语言版本共用一行」的 logs 表 + roms 单列 logs
（详见 db_structure/logs.sql 与 miroms/logs_store.py）；语种与列名的对应关系集中在
miroms/constants.py 的 CHANGELOG_LOCALES，新增语种只需在那里登记 + 给 logs 表加同名列，
roms 表不再需要改动。

运行逻辑（按 ROM id 批量，而非按语种逐遍扫表）：
1. 把候选 ROM 的 logs 解回各语言，找出缺少该语种的 id 存进该语种的待补数组；
   加 --verify 时，还会把「已有该语种」的 id 存进待校验数组（--verify-only 只校验不补缺）。
2. 遍历所有 id 的并集（由新到旧，id 从大到小），同一个 id 只查一次数据库拿到 ROM 信息、
   只构建一次请求表单；命中的多个语种共用这份表单，仅替换 l 参数各请求一次；
3. 每个语种处理完就把该 id 从对应数组中删除，处理下一个 id；
4. 补缺时，接口没有该语种译文会回落英文，检测到与 logs_en 完全相同即跳过（该语种不写入），
   需要强制写入时加 --force。
5. --verify 校验已有日志：以官方接口返回为准。官方给出该语种的独立译文且与库中不同时，
   回写官方文本（AI 补译的措辞差异会被纠正、缺失/多余的条目会以官方结构为准）；
   官方只是回落英文、或接口没有日志时，保留库中现有译文，避免把 AI 译文冲成英文。
6. 对 cn 区域的记录，首次补到日志时同时写入 release_date；已有日志只补语种或校验修正时
   不改 release_date。并从响应中提取卡刷包（recovery）文件名（仅当库中为空时回填）。

写入是逐条 UPDATE 且连接为 autocommit，执行即落库（不会攒到最后统一提交）；
写入失败不再被静默忽略——会计入 write_failed 并打印首个错误。

用法：
    python3 data/scripts/fetch_changelog.py                     # 依次补全所有语种
    python3 data/scripts/fetch_changelog.py --langs ja,ko,ru    # 只处理指定语种
    python3 data/scripts/fetch_changelog.py --probe 5           # 探测接口对哪些语种真的返回了译文
    python3 data/scripts/fetch_changelog.py --dry-run --limit 5 # 只看会写什么，不落库
    python3 data/scripts/fetch_changelog.py --min-id 0 --limit 50
    python3 data/scripts/fetch_changelog.py --force --sleep 0.3

    # 校验并纠正已有日志（全量很慢，建议按语种 / id 范围 / 条数分批）
    python3 data/scripts/fetch_changelog.py --verify --langs ja,ko,ru --verify-limit 200
    python3 data/scripts/fetch_changelog.py --verify-only --min-id 0 --max-id 30000
    python3 data/scripts/fetch_changelog.py --verify --dry-run --limit 5 --verify-limit 5

来源: HyperOS.fans test2.py (Changelog)
"""
import argparse
import json
import sys
import time
from pathlib import Path
from datetime import date, datetime
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))

import common

# 单个 ROM 的数据库字段（一次查询供该 id 的所有语种复用）
# logs 列为语言中性的 ID 引用结构（[[模块ID,[条目ID,...],语言掩码],...]），
# 各语言原文在 logs 表按列存放，经 LogStore.build_localized 还原为 {语言列: {...}}
ROM_INFO_SQL = (
	"SELECT device, code, region, branch, android, version, zone, logs "
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
	"""确认 logs 表已有各语言列；缺列时给出迁移指引并退出

	语言列已从 roms 表搬到 logs 表（见 db_structure/logs.sql），
	缺列会导致写入静默失败，所以先检查。
	"""
	try:
		rows = common.DatabaseManager.execute(
			"SHOW COLUMNS FROM logs", fetch_one=False, raise_on_error=True
		)
	except Exception as exc:
		print(f"✖ 无法读取 logs 表结构：{type(exc).__name__}: {exc}")
		print("  请检查 scripts/config.py 里的 host / database 是否正确、数据库是否可连")
		sys.exit(1)

	existing = {row[0] for row in rows or []}
	if 'content' not in existing:
		print("✖ logs 表仍是旧结构（缺少多语言列），请先执行迁移：")
		print("  python3 data/scripts/migrate_logs_multilang.py")
		sys.exit(1)

	missing = [cfg['column'] for cfg in locales if cfg['column'] not in existing]
	if missing:
		print(f"✖ logs 表缺少以下语言列：{', '.join(missing)}")
		print("  请先执行迁移：python3 data/scripts/migrate_logs_multilang.py")
		print("  （或直接执行 db_structure/logs.sql 中对应的 ADD COLUMN 语句）")
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


def _canonical_value(value: Any) -> Any:
	"""比较用归一化：去掉首尾空白、丢弃空项、合并同名模块、列表去重并排序

	只对顶层做一次 ID 结构解码；递归时不再把普通文本当 JSON 解析，
	避免正文里恰好长得像 JSON 的日志被误改。

	列表排序是为了让「同一组条目只是顺序不同」不被当成差异：库里的日志按
	LogStore 的结构指纹聚类后会跟随主语言（中文/英文）的条目顺序，若按官方原始
	顺序比较，官方顺序与主语言不同就会每轮都重复回写。
	"""
	if isinstance(value, str):
		return value.strip()
	if isinstance(value, list):
		result = []
		for item in value:
			norm = _canonical_value(item)
			if norm in (None, '', [], {}):
				continue
			if norm not in result:
				result.append(norm)
		result.sort(key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True))
		return result
	if isinstance(value, dict):
		result = {}
		for key, item in value.items():
			name = str(key or '').strip()
			if not name:
				continue
			norm = _canonical_value(item)
			if norm in (None, '', [], {}):
				continue
			if name in result and isinstance(result[name], list) and isinstance(norm, list):
				# 归一化后重名模块（如 "System" 与 " System "）合并条目
				result[name].extend(line for line in norm if line not in result[name])
			else:
				result[name] = norm
		return result
	return value


def is_same_log(left: Any, right: Any) -> bool:
	"""比较两条日志是否等价（用于判断接口是否回落到英文 / 是否需要修正）

	left 为接口返回的原文 JSON；right 为库中现值（可能是 ID 引用结构），
	比较前统一归一化为原文对象。空白、空条目、重复条目、模块顺序、条目顺序
	差异都不算不同。
	"""
	if not left or not right:
		return False
	lval = _canonical_value(common.LogStore.normalize_json(left))
	rval = _canonical_value(common.LogStore.normalize_json(right))
	return lval == rval


def parse_official_log(log: Any) -> dict | None:
	"""把接口返回的 changelog JSON 解析为字典；空日志 / 非字典返回 None"""
	if not log:
		return None
	try:
		parsed = json.loads(log)
	except (json.JSONDecodeError, TypeError):
		return None
	if not isinstance(parsed, dict) or not parsed:
		return None
	return parsed



def write_rom_logs(rom_id: int, langs: dict, region: str, stats: dict, per_locale: dict,
				   dry_run: bool = False, set_release_date: bool = True) -> bool:
	"""写入一个 ROM 的多语言日志（cn 区域且首次补到日志时同时写 release_date）

	langs 已是 {语言列: 原文对象}，由 LogStore.write_logs 重新分组写入 logs 表并返回
	roms.logs 的 ID 引用结构。DatabaseManager.execute 默认会把 SQL 异常吞成 None，
	这里用 raise_on_error=True 让失败显形：计入 write_failed 并打印首个错误。

	set_release_date=False 用于「已有日志只补语种」或「只校验并修正已有日志」：
	此时 release_date 不应被改成今天。
	"""
	prefix = "[dry-run] " if dry_run else ""
	if dry_run:
		stats['updated'] += 1
		print(f"\n{prefix}将写入 id={rom_id} 的语言：{', '.join(sorted(langs))}")
		return True

	try:
		encoded = common.LogStore.write_logs(langs)
	except Exception as exc:
		stats['write_failed'] += 1
		if stats['write_failed'] == 1:
			print(f"\n✖ 日志分组写入失败（id={rom_id}）：{type(exc).__name__}: {exc}")
		return False

	try:
		if region == 'cn' and set_release_date:
			common.DatabaseManager.execute(
				"UPDATE roms SET logs = %s, release_date = %s WHERE id = %s",
				params=(encoded, date.today().strftime('%Y-%m-%d'), rom_id),
				raise_on_error=True,
			)
		else:
			common.DatabaseManager.execute(
				"UPDATE roms SET logs = %s WHERE id = %s",
				params=(encoded, rom_id), raise_on_error=True,
			)
	except Exception as exc:
		stats['write_failed'] += 1
		if stats['write_failed'] == 1:
			print(f"\n✖ 写入失败（id={rom_id}）：{type(exc).__name__}: {exc}")
		return False

	stats['updated'] += 1
	if stats['updated'] == 1:
		print(f"\n✓ 首次写入成功：id={rom_id} 语言 {', '.join(sorted(langs))}")
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


def collect_pending_ids(locales: list[dict], min_id: int = 0, limit: int = 0,
						max_id: int = 0, verify: bool = False,
						verify_limit: int = 0, verify_only: bool = False) -> tuple[dict, dict]:
	"""每个语种查一次待补 / 待校验 id，返回 ({列名: [待补 id...]}, {列名: [待校验 id...]})

	更新日志已改为「同一日志多语言一行」的 logs 表 + roms 单列日志结构，
	因此不再能用 `WHERE logs_ja IS NULL` 判断，改为把候选 ROM 的 logs 解回各语言，
	再挑出缺少该语言的 id。--verify 时同一份解析结果还会挑出「已有该语言」的 id，
	交给 fetch_changelogs 重新请求官方做对照。
	"""
	try:
		rows = common.DatabaseManager.execute(
			"SELECT id, logs FROM roms "
			"WHERE branch != 'X' AND (tag != 'CnOB' OR tag IS NULL) ORDER BY id DESC",
			fetch_one=False, raise_on_error=True,
		)
	except Exception as exc:
		print(f"✖ 查询待补记录失败：{type(exc).__name__}: {exc}")
		sys.exit(1)

	present: dict[int, set] = {}
	for row in rows or []:
		rom_id, value = row[0], row[1]
		if not value:
			present[rom_id] = set()
			continue
		try:
			parsed = json.loads(value)
			present[rom_id] = set(common.LogStore.build_localized(parsed).keys())
		except (json.JSONDecodeError, TypeError):
			present[rom_id] = set()

	pending: dict[str, list[int]] = {}
	existing: dict[str, list[int]] = {}
	for cfg in locales:
		column = cfg['column']
		ids = [] if verify_only else [rom_id for rom_id, langs in present.items()
									  if column not in langs]
		raw_total = len(ids)
		ids = _filter_ids(ids, min_id=min_id, max_id=max_id, limit=limit)
		pending[column] = ids

		verify_ids: list[int] = []
		verify_total = 0
		if verify:
			verify_ids = [rom_id for rom_id, langs in present.items() if column in langs]
			verify_total = len(verify_ids)
			verify_ids = _filter_ids(verify_ids, min_id=min_id, max_id=max_id,
									 limit=verify_limit)
			existing[column] = verify_ids

		if verify_only:
			line = f"{cfg['name']:<16} {cfg['api']:<6} → {column:<12} 待校验 {len(verify_ids)} 条"
			note = _filter_note(verify_total, len(verify_ids), min_id, max_id, verify_limit,
								limit_label='--verify-limit')
		else:
			line = f"{cfg['name']:<16} {cfg['api']:<6} → {column:<12} 待补 {len(ids)} 条"
			note = _filter_note(raw_total, len(ids), min_id, max_id, limit)
			if verify:
				line += f"，待校验 {len(verify_ids)} 条"
				note += _filter_note(verify_total, len(verify_ids), min_id, max_id,
									 verify_limit, limit_label='--verify-limit')
		print(line + note)

	return pending, existing


def _filter_ids(ids: list[int], min_id: int = 0, max_id: int = 0, limit: int = 0) -> list[int]:
	"""按 id 范围与条数截断（ids 已按 id 从大到小）"""
	result = ids
	if min_id:
		result = [rom_id for rom_id in result if rom_id > min_id]
	if max_id:
		result = [rom_id for rom_id in result if rom_id < max_id]
	if limit:
		result = result[:limit]
	return result


def _filter_note(raw_total: int, kept: int, min_id: int, max_id: int, limit: int,
				 limit_label: str = '--limit') -> str:
	"""--min-id / --max-id / --limit 真正过滤掉记录时补充说明"""
	if kept == raw_total:
		return ''
	scope = []
	if min_id:
		scope.append(f'--min-id {min_id}')
	if max_id:
		scope.append(f'--max-id {max_id}')
	note = f"（共 {raw_total} 条"
	if scope:
		note += f"，{' / '.join(scope)} 后 {kept} 条"
	if limit:
		note += f"，{limit_label} {limit} 截断"
	return note + '）'


def fetch_changelogs(locales: list[dict], min_id: int = 46000, limit: int = 0,
					 force: bool = False, sleep: float = 0.0, dry_run: bool = False,
					 print_form: bool = False, max_id: int = 0, verify: bool = False,
					 verify_limit: int = 0, verify_only: bool = False) -> dict:
	"""按 ROM id 遍历，同一个 id 命中的多个语种只查一次库、只构建一次表单

	verify=True 时，除补缺外还会重新请求官方接口校验已有日志：官方有该语种的独立
	译文且与库中不同则回写官方文本；官方回落英文或没有日志时保留库中现有译文。
	verify_only=True 时只做校验、不补缺。
	"""
	pending, existing = collect_pending_ids(
		locales, min_id=min_id, limit=limit, max_id=max_id,
		verify=verify, verify_limit=verify_limit, verify_only=verify_only,
	)
	if verify_only:
		pending = {column: [] for column in pending}

	# 待补 / 待校验集合：{列名: set(id)}，处理完一个语种就从对应集合里删掉该 id
	pending_sets = {column: set(ids) for column, ids in pending.items()}
	verify_sets = {column: set(existing.get(column, [])) for column in pending}
	# reverse=True：所有语种并集后仍按 id 从大到小，主循环从最新的 ROM 开始请求
	all_ids = sorted(set().union(*pending_sets.values(), *verify_sets.values()), reverse=True)

	stats = {
		'total_ids': len(all_ids),
		'updated': 0, 'fallback': 0, 'empty': 0, 'failed': 0, 'missing': 0,
		'verified': 0, 'corrected': 0, 'verify_fallback': 0, 'verify_empty': 0,
		'verify_failed': 0,
		'write_failed': 0, 'dry_run': dry_run,
		'print_form': print_form, '_first_form': None,
	}
	per_locale = {
		cfg['column']: {
			'updated': 0, 'filled': 0, 'corrected': 0, 'verified': 0,
			'fallback': 0, 'fallback_kept': 0, 'empty': 0, 'verify_empty': 0,
			'failed': 0, 'verify_failed': 0, 'write_failed': 0,
		}
		for cfg in locales
	}

	if not all_ids:
		print("没有需要处理的记录（各语种待补 / 待校验数组都为空）")
		stats['per_locale'] = per_locale
		return stats

	action = '补日志'
	if verify:
		action = '校验并补日志' if not verify_only else '校验日志'
	print(f"\n共 {len(all_ids)} 个 ROM 需要{action}，开始处理..."
		  f"{'（dry-run：不会写库）' if dry_run else ''}")

	# 英文列自身与中文列不需要做「回落英文」判断
	check_fallback = {
		cfg['column']: cfg['column'] not in ('logs_zh', common.CHANGELOG_BASE_COLUMN)
		for cfg in locales
	}
	en_locale = common.find_changelog_locale(common.CHANGELOG_BASE_COLUMN)
	en_api = en_locale['api'] if en_locale else 'en_US'

	for idx, rom_id in enumerate(all_ids, 1):
		# 命中该 id 的语种（存在时只替换 locale 重新请求）
		targets = [cfg for cfg in locales
				   if rom_id in pending_sets[cfg['column']] or rom_id in verify_sets[cfg['column']]]
		if not targets:
			continue
		# 英文先请求，后面的语种可以用官方英文判断「接口是否只是回落英文」
		targets.sort(key=lambda cfg: (cfg['column'] != common.CHANGELOG_BASE_COLUMN,
									  common.CHANGELOG_COLUMNS.index(cfg['column'])))

		# 每个 id 只查一次库、只构建一次表单
		info_row = common.DatabaseManager.query_one(ROM_INFO_SQL, params=(rom_id,))
		if not info_row:
			stats['missing'] += 1
			for cfg in targets:
				pending_sets[cfg['column']].discard(rom_id)
				verify_sets[cfg['column']].discard(rom_id)
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
		# 该 ROM 现有的各语言日志（语言列 -> 原文对象），新抓到的语种合并进去后整体回写
		merged: dict = {}
		if info_row[7]:
			try:
				merged = dict(common.LogStore.build_localized(json.loads(info_row[7])))
			except (json.JSONDecodeError, TypeError):
				merged = {}
		logs_en = merged.get(common.CHANGELOG_BASE_COLUMN)
		# 该 ROM 在本次处理前是否已有日志：只有「从无到有」才写 release_date，
		# 给老 ROM 补语种 / 校验修正都不应把发布日期改成今天
		had_logs = bool(merged)
		# 校验非英文语种时优先用官方英文做回落基准；没有本次抓到的官方英文时，
		# 遇到差异再补请求一次 en_US（库里的 logs_en 本身也可能是 AI 补译 / 不完整）。
		baseline_en = logs_en
		baseline_is_official = False
		baseline_fetched = False
		form = build_changelog_form(info)

		columns = ','.join(cfg['column'] for cfg in targets)
		if stats.get('_first_form') is None:
			stats['_first_form'] = dict(form, l=targets[0]['api'])
			print(f"首个请求：d={form['d']} pn={form['pn']} r={form['r']} zone={form['options']['zone']} "
				  f"v={form['v']} l={targets[0]['api']}")
			if stats.get('print_form'):
				print(json.dumps(stats['_first_form'], ensure_ascii=False, indent=2))
		print(f"\r{rom_id} {info['version']} {info['device']} {idx}/{len(all_ids)} [{columns}]",
			  end="", flush=True)

		fetched: dict = {}
		filled_columns: set = set()
		for cfg in targets:
			column = cfg['column']
			if column == common.CHANGELOG_BASE_COLUMN:
				# 本次已经请求过英文（成功与否都算），不再为回落判断重复请求
				baseline_fetched = True
			is_missing = rom_id in pending_sets[column]
			is_verify = rom_id in verify_sets[column]
			if not (is_missing or is_verify):
				continue
			# 库里的结构解析不出该语种时按补缺处理
			if is_verify and not merged.get(column):
				is_missing, is_verify = True, False

			# 同一份表单，仅替换 l
			api_result = get_changelog_for_device(info, cfg['api'], form=form)
			pending_sets[column].discard(rom_id)
			verify_sets[column].discard(rom_id)

			if not api_result:
				if is_missing:
					stats['failed'] += 1
					per_locale[column]['failed'] += 1
				if is_verify:
					stats['verify_failed'] += 1
					per_locale[column]['verify_failed'] += 1
				if sleep:
					time.sleep(sleep)
				continue

			log = api_result.get("changelog")
			recovery = api_result.get("recovery", "")

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

			official = parse_official_log(log)
			if official is None:
				if is_missing:
					stats['empty'] += 1
					per_locale[column]['empty'] += 1
				if is_verify:
					stats['verify_empty'] += 1
					per_locale[column]['verify_empty'] += 1
				if sleep:
					time.sleep(sleep)
				continue

			# 官方英文：既是最权威的英文日志，也是判断其它语种是否回落英文的基准
			if column == common.CHANGELOG_BASE_COLUMN:
				baseline_en = official
				baseline_is_official = True
				baseline_fetched = True

			if is_missing:
				fallback_base = baseline_en or logs_en
				if check_fallback[column] and not force and is_same_log(official, fallback_base):
					# 接口没有该语种译文，返回了与英文相同的文本，跳过写入以免存一堆英文副本
					stats['fallback'] += 1
					per_locale[column]['fallback'] += 1
				else:
					fetched[column] = official
					filled_columns.add(column)
					per_locale[column]['filled'] += 1
			else:
				stored = merged.get(column)
				if is_same_log(official, stored):
					# 库中译文与官方一致，无需改动
					stats['verified'] += 1
					per_locale[column]['verified'] += 1
				else:
					if check_fallback[column] and not baseline_is_official and not baseline_fetched:
						# 只校验 ug / bo 等语种时不会请求 en_US，这里补一次官方英文，
						# 避免把「接口回落的英文」误当成该语种的独立译文写回去
						baseline_fetched = True
						en_result = get_changelog_for_device(info, en_api, form=form)
						en_official = parse_official_log(
							en_result.get('changelog') if en_result else None)
						if en_official:
							baseline_en = en_official
							baseline_is_official = True
						if sleep:
							time.sleep(sleep)

					if (check_fallback[column]
							and is_same_log(official, baseline_en)):
						# 官方对该语种没有独立译文（回落英文），保留库中 AI 补译，避免被英文覆盖。
						# 校验模式不受 --force 影响：--force 只用于补缺时强行写入英文占位。
						stats['verify_fallback'] += 1
						per_locale[column]['fallback_kept'] += 1
					else:
						# 以官方接口为准修正库中译文（AI 补译的措辞差异 / 条目增减都在这里纠正）
						fetched[column] = official
						stats['corrected'] += 1
						per_locale[column]['corrected'] += 1

			if sleep:
				time.sleep(sleep)

		if fetched:
			merged.update(fetched)
			# 只有「原本没有日志、这次首次补到」才写 release_date；
			# 给老 ROM 补语种或纯校验修正都不动发布日期
			ok = write_rom_logs(rom_id, merged, info['region'], stats, per_locale,
								dry_run, set_release_date=bool(filled_columns) and not had_logs)
			for column in fetched:
				per_locale[column]['updated' if ok else 'write_failed'] += 1

	print()
	print("\n各语种处理结果（补写 / 修正 / 已核对 / 回落跳过或保留 / 无日志 / 请求失败 / 写入失败）：")
	for cfg in locales:
		s = per_locale[cfg['column']]
		print(f"    {cfg['column']:<12} {cfg['api']:<6} {s['filled']} / {s['corrected']} / "
			  f"{s['verified']} / {s['fallback'] + s['fallback_kept']} / "
			  f"{s['empty'] + s['verify_empty']} / {s['failed'] + s['verify_failed']} / "
			  f"{s['write_failed']}")

	if stats['updated'] == 0 and not dry_run:
		if verify:
			print("\n提示：本次没有需要修正的日志（已核对一致的记录不会重复写入）。")
		else:
			print("\n⚠ 本次没有任何写入，常见原因：")
			print("   1) 接口对所有语种都返回英文原文（回落）→ 先跑 `--probe 5` 确认；确需写入加 `--force`")
			print(f"   2) 待补数组为空（如 --min-id {min_id} 过滤掉了全部记录）→ 用 `--min-id 0` 重试")
			print("   3) 写入被数据库拒绝 → 看上面的 write_failed 计数与首个报错")

	stats['per_locale'] = per_locale
	return stats


def probe(locales: list[dict], limit: int = 3, sleep: float = 0.0) -> None:
	"""探测接口对各语种的返回情况：拿最近若干条已有英文日志的记录逐语种比对。"""
	rows = common.DatabaseManager.execute(
		"SELECT id, device, code, region, branch, android, version, zone, logs FROM roms "
		"WHERE logs IS NOT NULL AND logs != '' AND branch != 'X' ORDER BY id DESC LIMIT %s",
		params=(limit,), fetch_one=False
	)
	if not rows:
		print("没有可用于探测的记录（需要已有日志的记录）")
		return

	print(f"用最近 {len(rows)} 条记录探测 {len(locales)} 个语种：\n")

	summary = {cfg['column']: {'translated': 0, 'fallback': 0, 'empty': 0, 'failed': 0} for cfg in locales}

	for row in rows:
		info = {
			'device': row[1], 'code': row[2], 'region': row[3], 'branch': row[4],
			'android': row[5], 'version': row[6], 'zone': row[7],
		}
		try:
			current = common.LogStore.build_localized(json.loads(row[8])) if row[8] else {}
		except (json.JSONDecodeError, TypeError):
			current = {}
		logs_en = current.get(common.CHANGELOG_BASE_COLUMN)
		print(f"--- {info['device']} {info['version']} ({info['region']})")

		form = build_changelog_form(info)
		for cfg in locales:
			api_result = get_changelog_for_device(info, cfg['api'], form=form)
			if api_result is None:
				status = '请求失败'
				summary[cfg['column']]['failed'] += 1
			else:
				log = api_result.get('changelog')
				parsed = parse_official_log(log)
				if parsed is None:
					status = '接口无日志'
					summary[cfg['column']]['empty'] += 1
				elif is_same_log(parsed, logs_en):
					status = '与英文相同（无译文）'
					summary[cfg['column']]['fallback'] += 1
				else:
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
	parser.add_argument('--min-id', type=int, default=None,
						help='只处理 id 大于该值的记录，默认 46000（指定 --max-id 时默认 0 处理全表）；传 0 处理全表')
	parser.add_argument('--max-id', type=int, default=0, help='只处理 id 小于该值的记录，默认 0 表示不限（配合 --min-id 分批）')
	parser.add_argument('--limit', type=int, default=0, help='每个语种最多收集多少条待补记录（按 id 从大到小，即最新的 N 条），0 表示不限')
	parser.add_argument('--verify', action='store_true',
						help='校验已有日志：重新请求官方接口，官方有该语种的独立译文且与库中不同则以官方为准回写')
	parser.add_argument('--verify-only', action='store_true',
						help='只校验已有日志，不补缺失语种（隐含 --verify）')
	parser.add_argument('--verify-limit', type=int, default=0,
						help='每个语种最多校验多少条已有记录（按 id 从大到小），0 表示不限；建议配合 --langs 分批')
	parser.add_argument('--force', action='store_true',
						help='补缺时接口回落英文也写入（默认跳过，列保持 NULL）；校验模式不受影响')
	parser.add_argument('--dry-run', action='store_true', help='只打印将要写入的内容，不落库')
	parser.add_argument('--print-form', action='store_true', help='打印首个请求的完整表单 JSON（核对 r / pn / zone 等字段）')
	parser.add_argument('--sleep', type=float, default=0.0, help='每次接口请求后的间隔秒数，默认 0')
	parser.add_argument('--probe', type=int, nargs='?', const=3, default=None,
						metavar='N', help='探测接口语种支持情况（默认取最近 3 条记录），不写库')
	args = parser.parse_args()

	if args.verify_only:
		args.verify = True
	if args.verify_limit and not args.verify:
		parser.error('--verify-limit 需要配合 --verify / --verify-only 使用')
	if args.min_id is None:
		args.min_id = 0 if args.max_id else 46000
	if args.max_id and args.max_id <= args.min_id:
		parser.error('--max-id 必须大于 --min-id')

	locales = select_locales([x.strip() for x in args.langs.split(',')] if args.langs else None)

	print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始获取 changelog...")
	print_target()
	# 探测只需要英文列，方便在补列之前先确认接口支持哪些语种
	verify_columns([common.find_changelog_locale(common.CHANGELOG_BASE_COLUMN)]
				   if args.probe is not None else locales)

	if args.probe is not None:
		probe(locales, limit=args.probe, sleep=args.sleep)
		print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 探测完成")
		return

	stats = fetch_changelogs(locales, min_id=args.min_id, limit=args.limit,
							 force=args.force, sleep=args.sleep, dry_run=args.dry_run,
							 print_form=args.print_form, max_id=args.max_id,
							 verify=args.verify, verify_limit=args.verify_limit,
							 verify_only=args.verify_only)

	print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] changelog 获取完成："
		  f"{stats['total_ids']} 个 ROM，写入 {stats['updated']}，回落英文跳过 {stats['fallback']}，"
		  f"无日志 {stats['empty']}，请求失败 {stats['failed']}，写入失败 {stats['write_failed']}，"
		  f"记录缺失 {stats['missing']}")
	if args.verify:
		print(f"校验结果：已核对 {stats['verified']}，修正 {stats['corrected']}，"
			  f"官方回落保留 {stats['verify_fallback']}，官方无日志 {stats['verify_empty']}，"
			  f"校验失败 {stats['verify_failed']}")


if __name__ == '__main__':
	main()
