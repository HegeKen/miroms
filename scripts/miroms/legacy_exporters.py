"""v1 / v2 附属导出 —— NuxtMR（api/v1）与 HyperOS.fans（api/v2）两个参考站点的接口文件。

`exportV1` / `exportV2` / `exportV3` 只负责每台设备的 ``devices/<codename>.json``；
两个参考站点还有一批站点级接口文件（首页、机型列表、周更页、站点日志等），
原先由各自仓库里的手写脚本生成。把站点迁移到 ``hub.miuier.com/data/api/`` 后，
这些文件统一从 miroms 库导出，因此集中在本模块：

api/v1（NuxtMR，MIUI）
  * ``index.json``              首页「本周正式版更新」，按 ISO 周聚合 roms（type=MIUI, branch=F）
  * ``weekly.json``             周更索引：大版本 -> 周数列表（dev 表 region=cn 的 MIUI 周）
  * ``weekly/week-<week>-cn.json``  单周公告 + 机型清单 + 更新日志（dev 表全部 MIUI 周，不限来源）
  * ``devlist.json``            机型列表目录（手写目录 + 从 devices/*.json 回填 android/miui）
  * ``sitelog.json``            站点日志（sitelog 表 site='nuxtmr'）

api/v2（HyperOS.fans，HyperOS）
  * ``index.json``              首页「近 6 天新增」，按 roms.insdate 聚合（type=HyperOS）
  * ``dev.json``                开发版周更索引：大版本 -> 周数列表（dev.source='hyperos.fans'）
  * ``dev/<week>.json``         单周公告 + ROM 清单 + 多语言日志
  * ``devices.json``            机型列表目录（手写目录 + 从 devices/*.json 回填 supports/android）
  * ``sitelog.json``            站点日志（sitelog 表 site='hyperos.fans'）

**未纳入本模块的文件**为历史遗留产物 / 手写内容，随仓库直接维护（不参与重生成）：
v1 的 ``tools.json``、``thanks.json``、``devices.json``、``log.json``、``stable.json``、
``update.json``、``update_full.json``、``newrom.json``；v2 的 ``updates.json``、
``new-rom.json``、``assets/images/**``。它们要么是纯手写内容，要么是生成脚本早已废弃、
一次性归档的旧结构（详见 data/README.md）。
"""

import json
import logging
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from miroms.database import DatabaseManager
from miroms.logs_store import LogStore
from miroms.utils import FileUtils

logger = logging.getLogger(__name__)

# 导出目录基准路径（与 exporters.py 保持一致）
_EXPORT_BASE = Path(FileUtils.get_base_path()) / "data" / "api"

# 站点日志：site -> 导出到哪个 api 版本
SITELOG_SITES: Dict[str, str] = {
	'nuxtmr': 'v1',
	'hyperos.fans': 'v2',
}

# NuxtMR 周更公告里的固定 addons 分节（源文件 54 周全部如此）
_WEEKLY_ADDON_ATTENTION = ('升级说明', 'Update instruction')
_WEEKLY_ADDON_DESCRIPTION = ('版本说明', 'Version Information')

# v2 首页「近 N 天新增」的统计窗口（与源站点 push/index 脚本一致）
_RECENT_DAYS = 6

# HyperOS 大版本标签：dev.bigver「HyperOS 1」-> dev.json 的 bigVer「HyperOS1.0」
_HYPEROS_BIGVER_RE = re.compile(r'^\s*HyperOS\s*(\d+)(?:\.(\d+))?\s*$', re.I)

# v1 周更索引沿用 NuxtMR 的历史大版本写法：dev.bigver 已统一成「MIUI V6」，
# 但参考站点第 218-238 周的标签写的是「MIUI 6」，迁移后保持原样避免站点文案变化。
_V1_BIGVER_ALIASES = {'MIUI V6': 'MIUI 6'}


# ==================== 通用工具 ====================

def _read_json(path: Path, default: Any = None) -> Any:
	try:
		with open(path, 'r', encoding='utf-8') as f:
			return json.load(f)
	except (IOError, OSError, json.JSONDecodeError):
		return default


def _write_json(path: Path, data: Any, indent: int = 2) -> None:
	"""原子写入 JSON（先写 .tmp 再 rename），避免导出中途失败留下半个文件。"""
	path.parent.mkdir(parents=True, exist_ok=True)
	temp_path = path.with_suffix('.tmp')
	try:
		with open(temp_path, 'w', encoding='utf-8') as f:
			json.dump(data, f, ensure_ascii=False, indent=indent)
		temp_path.replace(path)
	except (IOError, OSError) as e:
		logger.error(f"文件写入失败 {path}: {e}")
		temp_path.unlink(missing_ok=True)
		raise IOError(f"无法写入文件 {path}: {e}")


def _parse_json_column(value: Any, default: Any) -> Any:
	"""longtext 列（JSON 字符串）-> Python 对象；已是对象或空值时原样/兜底返回。"""
	if value in (None, ''):
		return default
	if isinstance(value, (list, dict)):
		return value
	try:
		return json.loads(value)
	except (json.JSONDecodeError, TypeError):
		return default


def _format_datetime(value: Any) -> str:
	"""datetime -> 站点沿用的 ``YYYY.MM.DD HH:MM:SS`` 文本。"""
	if isinstance(value, datetime):
		return value.strftime('%Y.%m.%d %H:%M:%S')
	if isinstance(value, date):
		return value.strftime('%Y.%m.%d')
	return '' if value is None else str(value)


def _format_date(value: Any) -> str:
	"""date/datetime -> ``YYYY.MM.DD`` 文本。"""
	if isinstance(value, datetime):
		return value.strftime('%Y.%m.%d')
	if isinstance(value, date):
		return value.strftime('%Y.%m.%d')
	return '' if value is None else str(value)


def _format_weekly_update(value: Any) -> str:
	"""v1 周更公告的 ``update`` 字段。

	NuxtMR 源文件里同一字段有两种写法：有具体发布时间的用 ``YYYY.MM.DD HH:MM:SS``，
	只精确到日的用 ``YYYY.MM.DD``（库里对应 00:00:00）。按时间是否为午夜还原。
	"""
	if isinstance(value, datetime):
		if (value.hour, value.minute, value.second) == (0, 0, 0):
			return value.strftime('%Y.%m.%d')
		return value.strftime('%Y.%m.%d %H:%M:%S')
	if isinstance(value, date):
		return value.strftime('%Y.%m.%d')
	return '' if value is None else str(value)


def _device_name_map() -> Dict[str, Dict[str, str]]:
	"""设备代号 -> {zh, en}：每台设备取代表行（优先 tag='CnOO'，否则最小 id）。"""
	name_map: Dict[str, Dict[str, str]] = {}
	rows = DatabaseManager.query_all(
		"SELECT d.`device`, d.`full_names`, d.`names` FROM `devices` d "
		"JOIN (SELECT `device`, COALESCE(MAX(CASE WHEN `tag` = 'CnOO' THEN `id` END), MIN(`id`)) AS ref_id "
		"      FROM `devices` GROUP BY `device`) ref "
		"  ON ref.`device` = d.`device` AND ref.ref_id = d.`id`"
	)
	for device, full_names, names in rows or []:
		label = {'zh': '', 'en': ''}
		for raw in (full_names, names):
			parsed = _parse_json_column(raw, None)
			if isinstance(parsed, dict):
				label['zh'] = label['zh'] or str(parsed.get('zh') or '')
				label['en'] = label['en'] or str(parsed.get('en') or '')
		name_map[str(device)] = label
	return name_map


def _roms_by_dev_week() -> Dict[Tuple[int, int], List[Tuple]]:
	"""已绑定周次的开发版 ROM，按 (week, zone) 归组（与 export_dev 同口径）。"""
	rows = DatabaseManager.query_all(
		"SELECT `dev_week`, `zone`, `device`, `version`, `android`, `release_date`, "
		"`recovery`, `fastboot` FROM `roms` WHERE `dev_week` IS NOT NULL "
		"ORDER BY `release_date` IS NULL, `release_date`, `id`"
	)
	grouped: Dict[Tuple[int, int], List[Tuple]] = {}
	for row in rows or []:
		grouped.setdefault((int(row[0]), int(row[1] or 1)), []).append(row)
	return grouped


def _paired_modules(logs_value: Any) -> List[Tuple[str, str, List[Tuple[str, str]]]]:
	"""dev.logs 的 ID 引用结构 -> 按位置对齐的 [(模块zh, 模块en, [(条目zh, 条目en), ...]), ...]。

	直接按引用位置同时取中英文原文：位置的语言掩码未声明英文、或该行没有英文文本时，
	英文返回空字符串，不再用中文兜底（否则英文位会重复出现中文，模块也可能错配）。
	"""
	if not logs_value:
		return []
	try:
		pairs = json.loads(logs_value)
	except (json.JSONDecodeError, TypeError):
		return []

	en_bit = 1 << LogStore.LANG_INDEX[LogStore.EN_COLUMN]
	paired: List[Tuple[str, str, List[Tuple[str, str]]]] = []
	for module, entries, mask in LogStore.decode_structure(pairs):
		module_zh = module['texts'].get(LogStore.ZH_COLUMN) or ''
		if not module_zh:
			continue
		has_en = bool(mask & en_bit)
		module_en = (module['texts'].get(LogStore.EN_COLUMN) or '') if has_en else ''
		changes: List[Tuple[str, str]] = []
		for entry in entries:
			entry_zh = entry['texts'].get(LogStore.ZH_COLUMN) or ''
			if not entry_zh:
				continue
			entry_en = (entry['texts'].get(LogStore.EN_COLUMN) or '') if has_en else ''
			changes.append((entry_zh, entry_en))
		paired.append((module_zh, module_en, changes))
	return paired


# ==================== sitelog ====================

def export_sitelog(site: str) -> Optional[Dict[str, Any]]:
	"""导出单个站点的站点日志到 api/<v1|v2>/sitelog.json。

	两个站点的结构不同，由 ``site`` 决定还原成哪一种：

	* ``nuxtmr``       -> ``{"log": [{sudate, ver, zh-cn, en-us, log: [{zh-cn, en-us}]}]}``
	* ``hyperos.fans`` -> ``{"icons": [...], "logs": [{siteVer, icon, date, log: [{zh, en}]}]}``
	"""
	version = SITELOG_SITES.get(site)
	if not version:
		raise ValueError(f"未知站点: {site}")

	entry_rows = DatabaseManager.query_all(
		"SELECT `ver`, `icon`, `log_date`, `devices_zh`, `devices_en`, `logs` "
		"FROM `sitelog` WHERE `site` = %s AND `kind` = 'entry' ORDER BY `sort_order`, `id`",
		params=(site,),
	)
	if not entry_rows:
		logger.warning(f"站点日志为空，跳过导出: {site}")
		return None

	if site == 'nuxtmr':
		entries: List[Dict[str, Any]] = []
		for ver, _icon, log_date, devices_zh, devices_en, logs in entry_rows:
			entries.append({
				'sudate': _format_date(log_date),
				'ver': ver or '',
				'zh-cn': devices_zh or '',
				'en-us': devices_en or '',
				'log': [
					{'zh-cn': item.get('zh', ''), 'en-us': item.get('en', '')}
					for item in _parse_json_column(logs, [])
				],
			})
		payload: Dict[str, Any] = {'log': entries}
	else:
		meta_rows = DatabaseManager.query_all(
			"SELECT `icons` FROM `sitelog` WHERE `site` = %s AND `kind` = 'meta' ORDER BY `id` LIMIT 1",
			params=(site,),
		)
		icons = _parse_json_column(meta_rows[0][0], []) if meta_rows else []
		logs_list: List[Dict[str, Any]] = []
		for ver, icon, log_date, _devices_zh, _devices_en, logs in entry_rows:
			logs_list.append({
				'siteVer': ver or '',
				'icon': icon or '',
				'date': _format_date(log_date),
				'log': [
					{'zh': item.get('zh', ''), 'en': item.get('en', '')}
					for item in _parse_json_column(logs, [])
				],
			})
		payload = {'icons': icons, 'logs': logs_list}

	out_path = _EXPORT_BASE / version / 'sitelog.json'
	_write_json(out_path, payload)
	logger.info(f"站点日志导出完成: {site} -> {out_path}")
	return payload


# ==================== v1（NuxtMR） ====================

def _v1_week_bounds(year: int, week: int) -> Tuple[date, date]:
	"""ISO 周 -> (周一, 周日)。"""
	return date.fromisocalendar(year, week, 1), date.fromisocalendar(year, week, 7)


def _v1_stable_weeks() -> List[Dict[str, Any]]:
	"""按 ISO 周聚合 MIUI 正式版（branch=F）发布记录，新周在前。

	每条记录形如 ``{year, week, period, stable: [{code, zh-cn, en-us, date, rom}]}``，
	与 NuxtMR ``index.json`` / ``log.json`` 的历史结构一致（同一机型当周多个分支的
	ROM 以 ``"; "`` 连接）。
	"""
	rows = DatabaseManager.query_all(
		"SELECT `device`, `version`, `release_date` FROM `roms` "
		"WHERE `type` = 'MIUI' AND `branch` = 'F' AND `release_date` IS NOT NULL "
		"AND `version` NOT LIKE '%%.EP.%%' "
		"ORDER BY `release_date` DESC, `id` DESC"
	)
	names = _device_name_map()

	weeks: Dict[Tuple[int, int], Dict[str, Any]] = {}
	for device, version, release_date in rows or []:
		if not device or not version:
			continue
		iso = release_date.isocalendar()
		bucket = weeks.setdefault((iso[0], iso[1]), {})
		item = bucket.setdefault(device, {'date': release_date, 'versions': []})
		if version not in item['versions']:
			item['versions'].append(str(version))

	result: List[Dict[str, Any]] = []
	for (year, week), devices in weeks.items():
		monday, sunday = _v1_week_bounds(year, week)
		stable: List[Dict[str, Any]] = []
		for device, item in devices.items():
			name = names.get(device) or {'zh': '', 'en': ''}
			stable.append({
				'code': device,
				'zh-cn': name['zh'],
				'en-us': name['en'],
				'date': item['date'].isoformat(),
				'rom': '; '.join(item['versions']),
			})
		result.append({
			'year': str(year),
			'week': f'{week:02d}',
			'period': f'{monday}-{sunday}',
			'stable': stable,
		})
	return result


def export_v1_index() -> Optional[Dict[str, Any]]:
	"""导出 api/v1/index.json：NuxtMR 首页的「本周正式版更新」卡片。"""
	weeks = _v1_stable_weeks()
	if not weeks:
		logger.warning("没有 MIUI 正式版发布记录，跳过 v1/index.json")
		return None

	latest = weeks[0]
	year, week = int(latest['year']), int(latest['week'])
	next_monday = date.fromisocalendar(year, week, 1) + timedelta(days=7)
	next_sunday = next_monday + timedelta(days=6)

	payload = {
		'year': latest['year'],
		'week': latest['week'],
		'period': latest['period'],
		'nextperiod': f'{next_monday}-{next_sunday}',
		'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
		'stable': latest['stable'],
	}
	_write_json(_EXPORT_BASE / 'v1' / 'index.json', payload)
	logger.info(f"v1 首页索引导出完成：{year} 第 {week} 周，{len(latest['stable'])} 台机型")
	return payload


def export_v1_weekly_index() -> Optional[Dict[str, Any]]:
	"""导出 api/v1/weekly.json：周更大版本 -> 周数列表。

	周次取 ``dev`` 表里全部 MIUI 周（``bigver LIKE 'MIUI%'``），不区分来源
	（miuiroms / nuxtmr 等）；这些周次都会导出单周详情页，因此 ``oldest`` 直接取最早一周。
	"""
	rows = DatabaseManager.query_all(
		"SELECT `week`, `bigver` FROM `dev` "
		"WHERE `region` = 'cn' AND `show` = 1 AND `bigver` LIKE 'MIUI%%' "
		"ORDER BY `week` DESC"
	)
	if not rows:
		logger.warning("dev 表没有 MIUI 周更记录，跳过 v1/weekly.json")
		return None

	versions: Dict[str, List[str]] = {}
	for week, bigver in rows:
		key = _V1_BIGVER_ALIASES.get(bigver or '', bigver or 'MIUI')
		versions.setdefault(key, []).append(str(int(week)))

	payload = {
		'latest': str(max(int(w) for weeks in versions.values() for w in weeks)),
		'oldest': str(min(int(w) for weeks in versions.values() for w in weeks)),
		'versions': [
			{'version': name, 'period': '', 'weeks': weeks}
			for name, weeks in versions.items()
		],
	}
	_write_json(_EXPORT_BASE / 'v1' / 'weekly.json', payload)
	logger.info(f"v1 周更索引导出完成：{len(versions)} 个大版本，{sum(len(v) for v in versions.values())} 个周次")
	return payload


def export_v1_weekly_weeks() -> int:
	"""导出 api/v1/weekly/week-<week>-cn.json（dev 表 region='cn'、show=1 的全部 MIUI 周次）。

	只要 ``bigver`` 是 MIUI 就导出，不再要求 ``source='nuxtmr'``：早期周次来自
	miuiroms，nuxtmr 只覆盖第 560 周之后，按来源过滤会丢掉大量 MIUI 周更日志。
	"""
	rows = DatabaseManager.query_all(
		"SELECT `week`, `zone`, `versions`, `title_zh`, `title_en`, `post_id`, `update_time`, "
		"`description`, `attention`, `suspended`, `logs` FROM `dev` "
		"WHERE `region` = 'cn' AND `show` = 1 AND `bigver` LIKE 'MIUI%%' ORDER BY `week`"
	)
	if not rows:
		logger.warning("dev 表没有 MIUI 周更记录，跳过 v1/weekly/**")
		return 0

	names = _device_name_map()
	by_week = _roms_by_dev_week()
	out_dir = _EXPORT_BASE / 'v1' / 'weekly'
	saved = 0

	for week, zone, versions, title_zh, title_en, post_id, update_time, description, attention, suspended, logs in rows:
		week = int(week)
		zone = int(zone) if zone is not None else 1

		devices: List[Dict[str, Any]] = []
		seen = set()
		for rom in by_week.get((week, zone), []):
			device = str(rom[2] or '')
			version = str(rom[3] or '')
			# 同一机型当周可能有多条开发版记录（固件版本不同，如 fuxi 的 23.8.22 与 23.8.21），
			# 源站会逐条列出，因此按 (机型, 版本) 去重而不是按机型。
			if not device or (device, version) in seen:
				continue
			seen.add((device, version))
			name = names.get(device) or {'zh': '', 'en': ''}
			devices.append({
				'code': device,
				'zh-cn': name['zh'],
				'en-us': name['en'],
				'miui': version,
				'android': str(rom[4] or ''),
				'recovery': str(rom[6] or ''),
				'fastboot': str(rom[7] or ''),
			})

		modules = []
		for module_zh, module_en, changes in _paired_modules(logs):
			modules.append({
				'zh-cn': module_zh,
				'en-us': module_en,
				'changes': [
					{'zh-cn': zh, 'en-us': en}
					for zh, en in changes
				],
			})

		attention_items = _parse_json_column(attention, [])
		description_items = _parse_json_column(description, [])
		payload = {
			'zh-cn': title_zh or '',
			'en-us': title_en or '',
			'CnBBSID': '',
			'CnComID': post_id or '',
			'GbBBSID': '',
			'update': _format_weekly_update(update_time),
			'versions': versions or '',
			'showdevices': '1',
			'vid': '',
			'no': '',
			'devices': devices,
			'tpd': _parse_json_column(suspended, []),
			'addons': [
				{
					'zh-cn': _WEEKLY_ADDON_ATTENTION[0],
					'en-us': _WEEKLY_ADDON_ATTENTION[1],
					'details': [
						{'zh-cn': item.get('zh', ''), 'en-us': item.get('en', '')}
						for item in attention_items
					],
				},
				{
					'zh-cn': _WEEKLY_ADDON_DESCRIPTION[0],
					'en-us': _WEEKLY_ADDON_DESCRIPTION[1],
					'details': [
						{'zh-cn': item.get('zh', ''), 'en-us': item.get('en', '')}
						for item in description_items
					],
				},
			],
			'logs': [{'zh-cn': title_zh or '', 'en-us': title_en or '', 'log': modules}] if modules else [],
		}
		_write_json(out_dir / f'week-{week}-cn.json', payload)
		saved += 1

	logger.info(f"v1 周更详情导出完成：{saved} 个周次")
	return saved


def _iter_catalog_devices(catalog: Dict[str, Any]):
	"""遍历机型目录里的设备对象。

	两个站点的目录层级不同：

	* v1 ``devlist.json``：``{brands: [{brand, series: [{series, devices: [...]}]}]}``
	* v2 ``devices.json``：``{<brand_key>: {brand, devices: [...]}}``
	"""
	if isinstance(catalog.get('brands'), list):
		for brand in catalog['brands']:
			if not isinstance(brand, dict):
				continue
			for series in brand.get('series', []) or []:
				if not isinstance(series, dict):
					continue
				for device in series.get('devices', []) or []:
					if isinstance(device, dict):
						yield device
		return

	for brand in catalog.values():
		if not isinstance(brand, dict):
			continue
		for device in brand.get('devices', []) or []:
			if isinstance(device, dict):
				yield device


def _refresh_catalog_versions(
	catalog_path: Path,
	device_dir: Path,
	fields: Tuple[str, ...],
) -> Optional[Dict[str, Any]]:
	"""机型列表目录（手写）-> 用同一版本的 devices/*.json 回填派生字段后写回。

	目录本身（品牌 / 系列 / 顺序 / 图片）是人工维护的，库里没有对应表；
	``android`` / ``miui``（v1）与 ``supports`` / ``android``（v2）则来自设备文件，
	设备文件不存在时保留目录里的原值，避免丢失仅存于参考仓库的老机型。
	"""
	catalog = _read_json(catalog_path)
	if not catalog:
		logger.warning(f"机型目录不存在，跳过：{catalog_path}")
		return None

	cache: Dict[str, Dict[str, Any]] = {}

	def device_data(code: str) -> Optional[Dict[str, Any]]:
		if code not in cache:
			cache[code] = _read_json(device_dir / f'{code}.json') or {}
		return cache[code] or None

	updated = 0
	for device in _iter_catalog_devices(catalog):
		code = device.get('code')
		if not code:
			continue
		data = device_data(str(code))
		if not data:
			continue
		changed = False
		for field in fields:
			if field in data:
				if device.get(field) != data[field]:
					device[field] = data[field]
					changed = True
		if changed:
			updated += 1

	_write_json(catalog_path, catalog)
	logger.info(f"机型目录已刷新：{catalog_path.name}（{updated} 台机型字段有更新）")
	return catalog


def export_v1_devlist() -> Optional[Dict[str, Any]]:
	"""导出 api/v1/devlist.json：机型列表页 / sitemap 的设备目录（回填 android、miui）。"""
	return _refresh_catalog_versions(
		_EXPORT_BASE / 'v1' / 'devlist.json',
		_EXPORT_BASE / 'v1' / 'devices',
		('android', 'miui'),
	)


# ==================== v2（HyperOS.fans） ====================

def _hyperos_bigver_label(bigver: str) -> str:
	"""dev.bigver「HyperOS 1」-> dev.json 的 ``bigVer``「HyperOS1.0」；无法识别时原样返回。"""
	match = _HYPEROS_BIGVER_RE.match(bigver or '')
	if not match:
		return bigver or ''
	major, minor = match.group(1), match.group(2) or '0'
	return f'HyperOS{major}.{minor}'


def export_v2_dev_index() -> Optional[Dict[str, Any]]:
	"""导出 api/v2/dev.json：开发版（HyperOS）大版本 -> 周数列表。"""
	rows = DatabaseManager.query_all(
		"SELECT `week`, `bigver` FROM `dev` "
		"WHERE `source` = 'hyperos.fans' AND `show` = 1 ORDER BY `week` DESC"
	)
	if not rows:
		logger.warning("dev 表没有 HyperOS.fans 周更记录，跳过 v2/dev.json")
		return None

	groups: Dict[str, List[str]] = {}
	for week, bigver in rows:
		groups.setdefault(_hyperos_bigver_label(bigver), []).append(str(int(week)))

	payload = {
		'HyperOS': [
			{
				'bigVer': name,
				'start': min(weeks, key=int),
				'latest': max(weeks, key=int),
				'weeks': weeks,
			}
			for name, weeks in groups.items()
		]
	}
	_write_json(_EXPORT_BASE / 'v2' / 'dev.json', payload)
	logger.info(f"v2 开发版索引导出完成：{len(groups)} 个大版本")
	return payload


def export_v2_dev_weeks() -> int:
	"""导出 api/v2/dev/<week>.json（dev 表 source='hyperos.fans' 的全部周次）。"""
	rows = DatabaseManager.query_all(
		"SELECT `week`, `zone`, `versions`, `title_zh`, `title_en`, `post_id`, `update_time`, "
		"`description`, `attention`, `suspended`, `logs`, `show` FROM `dev` "
		"WHERE `source` = 'hyperos.fans' AND `region` = 'cn' ORDER BY `week`"
	)
	if not rows:
		logger.warning("dev 表没有 HyperOS.fans 周更记录，跳过 v2/dev/**")
		return 0

	names = _device_name_map()
	by_week = _roms_by_dev_week()
	out_dir = _EXPORT_BASE / 'v2' / 'dev'
	saved = 0

	for week, zone, versions, title_zh, title_en, post_id, update_time, description, attention, suspended, logs, show in rows:
		week = int(week)
		zone = int(zone) if zone is not None else 1

		roms: List[Dict[str, Any]] = []
		for rom in by_week.get((week, zone), []):
			device = str(rom[2] or '')
			if not device:
				continue
			name = names.get(device) or {'zh': '', 'en': ''}
			roms.append({
				'device': device,
				'name': name,
				'rom': {
					'os': str(rom[3] or ''),
					'android': str(rom[4] or ''),
					'release': str(rom[5] or '')[:10],
					'recovery': str(rom[6] or ''),
					'fastboot': str(rom[7] or ''),
				},
			})

		log_groups = []
		for module_zh, module_en, changes in _paired_modules(logs):
			log_groups.append({
				'module': {'zh': module_zh, 'en': module_en},
				'log': [
					{'zh': zh, 'en': en}
					for zh, en in changes
				],
			})

		payload = {
			'week': str(week),
			'title': {'zh': title_zh or '', 'en': title_en or ''},
			'postId': post_id or '',
			'update': _format_datetime(update_time),
			'versions': versions or '',
			'description': _parse_json_column(description, []),
			'attention': _parse_json_column(attention, []),
			'logs': log_groups,
			'show': 'yes' if show else 'no',
			'roms': roms,
			'suspended': _parse_json_column(suspended, []),
		}
		_write_json(out_dir / f'{week}.json', payload)
		saved += 1

	logger.info(f"v2 开发版详情导出完成：{saved} 个周次")
	return saved


def export_v2_index() -> Optional[Dict[str, Any]]:
	"""导出 api/v2/index.json：HyperOS.fans 首页的「近 6 天新增」。"""
	rows = DatabaseManager.query_all(
		"SELECT `device`, `version`, `insdate` FROM `roms` "
		"WHERE `type` = 'HyperOS' AND `insdate` IS NOT NULL "
		"AND `insdate` >= CURDATE() - INTERVAL %s DAY "
		"ORDER BY `insdate` DESC, `id` DESC",
		params=(_RECENT_DAYS,),
	)
	names = _device_name_map()

	roms: Dict[str, Dict[str, Any]] = {}
	for device, version, insdate in rows or []:
		device = str(device or '')
		if not device or not version:
			continue
		info = roms.setdefault(device, {
			'name': names.get(device) or {'zh': '', 'en': ''},
			'versions': [],
		})
		text = insdate.isoformat() if hasattr(insdate, 'isoformat') else str(insdate or '')
		if not any(item['version'] == str(version) for item in info['versions']):
			info['versions'].append({'insert_date': text, 'version': str(version)})

	# 机型按「最新一条版本的录入日期」倒序；同一机型内的版本按录入日期倒序
	for info in roms.values():
		info['versions'].sort(key=lambda item: item['insert_date'], reverse=True)
	sorted_roms = dict(sorted(
		roms.items(),
		key=lambda item: max((v['insert_date'] for v in item[1]['versions']), default=''),
		reverse=True,
	))

	payload = {
		'recent': {
			'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
			'developing': 'no',
			'roms': sorted_roms,
		}
	}
	_write_json(_EXPORT_BASE / 'v2' / 'index.json', payload)
	logger.info(f"v2 首页索引导出完成：近 {_RECENT_DAYS} 天 {len(sorted_roms)} 台机型")
	return payload


def export_v2_devices() -> Optional[Dict[str, Any]]:
	"""导出 api/v2/devices.json：机型列表页 / sitemap 的目录（回填 supports、android）。"""
	return _refresh_catalog_versions(
		_EXPORT_BASE / 'v2' / 'devices.json',
		_EXPORT_BASE / 'v2' / 'devices',
		('supports', 'android'),
	)


# ==================== hub 自身（api/v3） ====================

# hub 自身的两个站点：web（本站）与 admin（管理后台），各自一条独立的更新日志
HUB_SITES: Tuple[str, ...] = ('hub.web', 'hub.admin')


def export_hub_sitelog() -> Optional[Dict[str, Any]]:
	"""导出 api/v3/sitelog.json：hub 自身 web / admin 的站点日志。

	条目来自 ``sitelog`` 表（由 ``scripts/import_hub_sitelog.py`` 按 git 记录导入）：

	``{"generatedAt": ..., "sites": {"hub.web": {"site", "latest", "count", "logs": [...]}, ...}}``

	每条形如 ``{"ver": "V0.17.0", "date": "2026-10-16", "log": [{"zh": ..., "en": ...}]}``，
	按 ``sort_order`` 升序（最新一版在前）。web 只读 ``sites['hub.web']``，
	admin 直连数据库读 ``site='hub.admin'``，两边共用同一份条目格式。
	"""
	sites: Dict[str, Any] = {}
	for site in HUB_SITES:
		rows = DatabaseManager.query_all(
			"SELECT `ver`, `log_date`, `logs` FROM `sitelog` "
			"WHERE `site` = %s AND `kind` = 'entry' ORDER BY `sort_order`, `id`",
			params=(site,),
		)
		if not rows:
			logger.warning(f"站点日志为空，跳过导出: {site}")
			continue
		logs: List[Dict[str, Any]] = []
		for ver, log_date, raw in rows:
			logs.append({
				'ver': ver or '',
				'date': log_date.isoformat() if hasattr(log_date, 'isoformat') else str(log_date or ''),
				'log': [
					{'zh': item.get('zh', ''), 'en': item.get('en', '')}
					for item in _parse_json_column(raw, [])
				],
			})
		sites[site] = {
			'site': site,
			'latest': logs[0]['ver'] if logs else '',
			'count': len(logs),
			'logs': logs,
		}

	if not sites:
		return None

	payload: Dict[str, Any] = {
		'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
		'sites': sites,
	}
	_write_json(_EXPORT_BASE / 'v3' / 'sitelog.json', payload)
	logger.info('hub 站点日志导出完成：' + '、'.join(f'{s} {v["latest"]}' for s, v in sites.items()))
	return payload


def export_tools() -> Optional[Dict[str, Any]]:
	"""导出 api/v3/tools.json：刷机工具下载（供官网「工具下载」页）。

	``api/v1/tools.json``（NuxtMR 遗留、人工维护）是**唯一手写源**，这里转成 hub 约定：
	工具名与日志条目由 ``zh-cn`` / ``en-us`` 改成 ``zh`` / ``en``（与 v3 其它数据一致，
	前端按当前语言在 zh / en 之间取用），``FileName`` 统一成小写 ``filename``。
	"""
	source = _read_json(_EXPORT_BASE / 'v1' / 'tools.json')
	if not source or not isinstance(source.get('tools'), list):
		logger.warning(f"工具源文件不存在或结构异常，跳过：{_EXPORT_BASE / 'v1' / 'tools.json'}")
		return None

	def pair(item: Any) -> Dict[str, str]:
		if not isinstance(item, dict):
			return {'zh': '', 'en': ''}
		zh = str(item.get('zh-cn') or item.get('zh') or '')
		return {'zh': zh, 'en': str(item.get('en-us') or item.get('en') or zh)}

	tools: List[Dict[str, Any]] = []
	for tool in source['tools']:
		if not isinstance(tool, dict):
			continue
		packages: List[Dict[str, Any]] = []
		for package in tool.get('packages') or []:
			if not isinstance(package, dict):
				continue
			packages.append({
				'version': str(package.get('version') or ''),
				'date': str(package.get('date') or ''),
				'filename': str(package.get('FileName') or package.get('filename') or ''),
				'url': str(package.get('url') or ''),
				'attentions': [pair(item) for item in package.get('attentions') or []],
				'logs': [pair(item) for item in package.get('logs') or []],
			})
		tools.append({
			'tool': str(tool.get('tool') or ''),
			'name': {'zh': str(tool.get('zh-cn') or tool.get('tool') or ''),
					 'en': str(tool.get('en-us') or tool.get('tool') or '')},
			'packages': packages,
		})

	payload: Dict[str, Any] = {
		'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
		'source': 'api/v1/tools.json',
		'tools': tools,
	}
	_write_json(_EXPORT_BASE / 'v3' / 'tools.json', payload)
	logger.info(f"工具下载导出完成：{len(tools)} 个工具，"
				f"{sum(len(t['packages']) for t in tools)} 个版本")
	return payload


# ==================== 汇总入口 ====================

def export_v1_extras() -> Dict[str, Any]:
	"""api/v1 全部附属接口（设备文件由 exportV1 单独导出）。"""
	logger.info("--- 导出 v1 附属接口 ---")
	return {
		'index': export_v1_index(),
		'weeklyIndex': export_v1_weekly_index(),
		'weeklyWeeks': export_v1_weekly_weeks(),
		'devlist': export_v1_devlist(),
		'sitelog': export_sitelog('nuxtmr'),
	}


def export_v2_extras() -> Dict[str, Any]:
	"""api/v2 全部附属接口（设备文件由 exportV2 单独导出）。"""
	logger.info("--- 导出 v2 附属接口 ---")
	return {
		'index': export_v2_index(),
		'devIndex': export_v2_dev_index(),
		'devWeeks': export_v2_dev_weeks(),
		'devices': export_v2_devices(),
		'sitelog': export_sitelog('hyperos.fans'),
	}


def export_hub_extras() -> Dict[str, Any]:
	"""api/v3 中由 hub 自身维护的附属接口：站点日志（web / admin）+ 工具下载。"""
	logger.info("--- 导出 hub 附属接口 ---")
	return {
		'sitelog': export_hub_sitelog(),
		'tools': export_tools(),
	}
