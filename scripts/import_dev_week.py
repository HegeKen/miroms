"""
import_dev_week.py - 把参考仓库的开发版（周更）数据导入 dev 表，并回填 roms.dev_week

数据来源（三个参考仓库，可用 --root 覆盖）：
  1. hyperos         HyperOS.fans/public/data/dev/<week>.json
                     （HyperOS 时代大陆开发版，含中英对照公告 + 日志 + 机型清单）
  2. nuxtmr          NuxtMR/public/MRData/data/weekly/week-<week>-cn.json
                     （MIUI 时代大陆开发版，结构同上但字段名不同）
  3. miuiroms        MIUIROMS/weekly/logs/week-<week>-CN.html
                     （更早的 MIUI 周日志 HTML，只有中文）

开发版分两种，同一周数会有两条记录：
  * 大陆版 region=cn     zone=1
  * 国际版 region=global zone=2

日志按现有方法存档（见 db_structure/logs.sql 与 miroms/logs_store.py）：
以中文结构为依据重新分组写入 logs 表，roms/dev 只存语言中性的 ID 引用结构。
元数据里的英文是人工翻译、与官方有出入，因此会先在 logs 表里按中文反查官方英文，
命中官方译文就用官方英文，未命中才保留元数据里的翻译。

用法：
    python3 data/scripts/import_dev_week.py --source hyperos
    python3 data/scripts/import_dev_week.py --source nuxtmr --weeks 560-618
    python3 data/scripts/import_dev_week.py --source miuiroms --weeks 1-299
    python3 data/scripts/import_dev_week.py --all
    python3 data/scripts/import_dev_week.py --source hyperos --dry-run
    python3 data/scripts/import_dev_week.py --backfill-roms      # 只按日期回填 roms.dev_week
"""
import argparse
import html as html_module
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))

import common
from miroms.database import DatabaseManager
from miroms.logs_store import LogStore

# 参考仓库默认路径（可通过 --root 覆盖）
DEFAULT_ROOTS = {
	'hyperos': Path('/Users/hegeken/Desktop/Codes/HyperOS.fans/public/data/dev'),
	'nuxtmr': Path('/Users/hegeken/Desktop/Codes/NuxtMR/public/MRData/data/weekly'),
	'miuiroms': Path('/Users/hegeken/Desktop/Codes/MIUIROMS/weekly/logs'),
}

REGION_INFO = {
	'cn': {'zone': 1, 'label': '大陆开发版'},
	'global': {'zone': 2, 'label': '国际开发版'},
}

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS `dev` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `week` int NOT NULL COMMENT '开发版周数',
  `region` varchar(16) COLLATE utf8mb4_bin NOT NULL DEFAULT 'cn' COMMENT 'cn=大陆版 / global=国际版',
  `zone` tinyint DEFAULT NULL,
  `bigver` varchar(64) COLLATE utf8mb4_bin DEFAULT NULL,
  `versions` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL,
  `title_zh` varchar(512) COLLATE utf8mb4_bin DEFAULT NULL,
  `title_en` varchar(512) COLLATE utf8mb4_bin DEFAULT NULL,
  `post_id` varchar(64) COLLATE utf8mb4_bin DEFAULT NULL,
  `update_time` datetime DEFAULT NULL,
  `release_date` date DEFAULT NULL,
  `description` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `attention` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `suspended` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `devices` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `roms` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `logs` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin,
  `source` varchar(32) COLLATE utf8mb4_bin DEFAULT NULL,
  `show` tinyint NOT NULL DEFAULT '1',
  `insdate` date DEFAULT NULL,
  `update_date` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_dev_week_region` (`week`,`region`),
  KEY `idx_dev_week` (`week`),
  KEY `idx_dev_region` (`region`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
"""


def ts() -> str:
	return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


# ==================== 通用小工具 ====================


def clean(value: Any) -> str:
	return str(value if value is not None else '').strip()


def pair(zh: Any, en: Any) -> Dict[str, str]:
	"""中英对照对象；英文缺失时留空，前端自行回落中文"""
	return {'zh': clean(zh), 'en': clean(en)}


def infer_bigver(version: str) -> str:
	"""从版本号推断大版本：OS1.0.24.7.28.DEV -> HyperOS 1、V14.0.23.10.15.DEV -> MIUI 14"""
	match = re.match(r'^(OS|V)(\d+)', clean(version), re.I)
	if not match:
		return ''
	prefix, number = match.group(1).upper(), int(match.group(2))
	if prefix == 'OS':
		return f'HyperOS {number}'
	return f'MIUI {number}'


def parse_datetime(value: str) -> Optional[str]:
	"""'2024.08.02 20:15:52' / '2022.08.12' -> 'YYYY-MM-DD HH:MM:SS' / 'YYYY-MM-DD 00:00:00'"""
	text = clean(value)
	if not text:
		return None
	match = re.match(r'^(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?', text)
	if not match:
		return None
	year, month, day = int(match.group(1)), int(match.group(2)), int(match.group(3))
	hour, minute, second = int(match.group(4) or 0), int(match.group(5) or 0), int(match.group(6) or 0)
	try:
		return datetime(year, month, day, hour, minute, second).strftime('%Y-%m-%d %H:%M:%S')
	except ValueError:
		return None


def parse_date(value: str) -> Optional[str]:
	text = clean(value)
	match = re.match(r'^(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})', text)
	if not match:
		return None
	try:
		return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
	except ValueError:
		return None


def parse_weeks(spec: str) -> Optional[Tuple[int, int]]:
	if not spec:
		return None
	match = re.match(r'^\s*(\d+)\s*(?:-\s*(\d+))?\s*$', spec)
	if not match:
		raise SystemExit(f'无法解析周数范围：{spec}（示例：1-299 或 619-652）')
	start = int(match.group(1))
	end = int(match.group(2) or start)
	return (min(start, end), max(start, end))


# ==================== 各来源解析 ====================


def load_hyperos(path: Path) -> Dict[str, Any]:
	"""HyperOS.fans/public/data/dev/<week>.json"""
	data = json.loads(path.read_text(encoding='utf-8'))
	logs_zh: Dict[str, List[str]] = {}
	logs_en: Dict[str, List[str]] = {}
	for group in data.get('logs') or []:
		module = group.get('module') or {}
		module_zh = clean(module.get('zh'))
		module_en = clean(module.get('en'))
		if not module_zh:
			continue
		logs_zh[module_zh] = []
		logs_en[module_en or module_zh] = []
		for entry in group.get('log') or []:
			zh, en = clean(entry.get('zh')), clean(entry.get('en'))
			if zh:
				logs_zh[module_zh].append(zh)
				logs_en[module_en or module_zh].append(en or zh)

	roms = []
	for item in data.get('roms') or []:
		rom = item.get('rom') or {}
		roms.append({
			'device': clean(item.get('device')),
			'name': pair((item.get('name') or {}).get('zh'), (item.get('name') or {}).get('en')),
			'version': clean(rom.get('os')),
			'android': clean(rom.get('android')),
			'release': clean(rom.get('release')),
			'recovery': clean(rom.get('recovery')),
			'fastboot': clean(rom.get('fastboot')),
		})

	return {
		'week': int(clean(data.get('week')) or path.stem),
		'region': 'cn',
		'title_zh': clean((data.get('title') or {}).get('zh')),
		'title_en': clean((data.get('title') or {}).get('en')),
		'post_id': clean(data.get('postId')),
		'update_time': parse_datetime(data.get('update')),
		'versions': clean(data.get('versions')),
		'description': [pair(x.get('zh'), x.get('en')) for x in (data.get('description') or [])],
		'attention': [pair(x.get('zh'), x.get('en')) for x in (data.get('attention') or [])],
		'suspended': data.get('suspended') or [],
		'devices': [{'device': r['device'], 'name': r['name']} for r in roms if r['device']],
		'roms': roms,
		'logs_zh': logs_zh,
		'logs_en': logs_en,
		'source': 'hyperos.fans',
	}


def load_nuxtmr(path: Path) -> Dict[str, Any]:
	"""NuxtMR/public/MRData/data/weekly/week-<week>-cn.json"""
	data = json.loads(path.read_text(encoding='utf-8'))
	logs_zh: Dict[str, List[str]] = {}
	logs_en: Dict[str, List[str]] = {}
	for group in data.get('logs') or []:
		for module in group.get('log') or []:
			module_zh = clean(module.get('zh-cn'))
			module_en = clean(module.get('en-us'))
			if not module_zh:
				continue
			logs_zh[module_zh] = []
			logs_en[module_en or module_zh] = []
			for entry in module.get('changes') or []:
				zh, en = clean(entry.get('zh-cn')), clean(entry.get('en-us'))
				if zh:
					logs_zh[module_zh].append(zh)
					logs_en[module_en or module_zh].append(en or zh)

	roms = []
	devices = []
	for item in data.get('devices') or []:
		roms.append({
			'device': clean(item.get('code')),
			'name': pair(item.get('zh-cn'), item.get('en-us')),
			'version': clean(item.get('miui')),
			'android': clean(item.get('android')),
			'release': '',
			'recovery': clean(item.get('recovery')),
			'fastboot': clean(item.get('fastboot')),
		})
		devices.append({'device': clean(item.get('code')), 'name': pair(item.get('zh-cn'), item.get('en-us'))})

	attention: List[Dict[str, str]] = []
	description: List[Dict[str, str]] = []
	for addon in data.get('addons') or []:
		title_zh = clean(addon.get('zh-cn'))
		for detail in addon.get('details') or []:
			item = pair(detail.get('zh-cn'), detail.get('en-us'))
			if title_zh == '升级说明':
				attention.append(item)
			else:
				description.append(item)

	week = int(re.search(r'week-(\d+)', path.stem).group(1))
	return {
		'week': week,
		'region': 'cn',
		'title_zh': clean(data.get('zh-cn')),
		'title_en': clean(data.get('en-us')),
		'post_id': clean(data.get('CnBBSID') or data.get('CnComID') or data.get('GbBBSID')),
		'update_time': parse_datetime(data.get('update')),
		'versions': clean(data.get('versions')) or (roms[0]['version'] if roms else ''),
		'description': description,
		'attention': attention,
		'suspended': data.get('tpd') or [],
		'devices': devices,
		'roms': roms,
		'logs_zh': logs_zh,
		'logs_en': logs_en,
		'source': 'nuxtmr',
	}


SECTION_RE = re.compile(r'^▍\s*(.+)$')
MODULE_RE = re.compile(r'^【(.+)】$')


def load_miuiroms(path: Path) -> Dict[str, Any]:
	"""MIUIROMS/weekly/logs/week-<week>-CN.html（正文只有中文）"""
	raw = path.read_text(encoding='utf-8', errors='replace')
	title_match = re.search(r'<title>([^<]*)</title>', raw)
	title = clean(html_module.unescape(title_match.group(1))) if title_match else ''
	title = re.sub(r'\s*-\s*MIUI官方ROM仓库\s*$', '', title)

	body = raw.split('<body', 1)[-1]
	body = re.sub(r'<script.*?</script>', '', body, flags=re.S)
	body = re.sub(r'<style.*?</style>', '', body, flags=re.S)
	body = re.sub(r'<br\s*/?>', '\n', body, flags=re.I)
	body = re.sub(r'</(p|div|li|h\d|tr)>', '\n', body, flags=re.I)
	text = html_module.unescape(re.sub(r'<[^>]+>', '\n', body))
	lines = [line.strip() for line in text.split('\n')]
	lines = [line for line in lines if line and line not in ('>', 'menu', 'MIUI官方ROM仓库')]

	attention: List[str] = []
	logs_zh: Dict[str, List[str]] = {}
	versions = ''
	section = ''
	current: Optional[str] = None
	for line in lines:
		heading = SECTION_RE.match(line)
		if heading:
			section = clean(heading.group(1))
			current = None
			continue
		module = MODULE_RE.match(line)
		if module:
			current = clean(module.group(1))
			logs_zh.setdefault(current, [])
			continue
		if section.startswith('发布时间'):
			if not versions:
				versions = line
			continue
		if section.startswith('升级说明') or section.startswith('注意事项'):
			attention.append(line)
			continue
		if section.startswith('更新日志'):
			if current is None:
				# 【本周推荐】等标题会被上面的 MODULE_RE 捕获；兜底放进「其他」
				current = '其他'
				logs_zh.setdefault(current, [])
			logs_zh[current].append(line)

	week = int(re.search(r'week-(\d+)', path.stem).group(1))
	return {
		'week': week,
		'region': 'cn',
		'title_zh': title,
		'title_en': '',
		'post_id': '',
		'update_time': None,
		'versions': versions,
		'description': [pair(x, '') for x in attention[:0]],
		'attention': [pair(x, '') for x in attention],
		'suspended': [],
		'devices': [],
		'roms': [],
		'logs_zh': logs_zh,
		'logs_en': {},
		'source': 'miuiroms',
	}


# ==================== 英文修正（以中文为依据反查官方译文） ====================


class OfficialEnglish:
	"""按中文反查 logs 表里已有的官方英文译文"""

	def __init__(self) -> None:
		self.cache: Dict[Tuple[str, str], Optional[str]] = {}
		self.hits = 0

	def get(self, log_type: str, zh_text: str) -> Optional[str]:
		key = (log_type, zh_text)
		if key in self.cache:
			return self.cache[key]
		row = DatabaseManager.query_one(
			"SELECT `logs_en` FROM `logs` WHERE `type` = %s AND `logs_en` IS NOT NULL "
			"AND (`logs_zh` = %s OR `content` = %s) LIMIT 1",
			params=(log_type, zh_text, zh_text),
		)
		value = clean(row[0]) if row and row[0] else None
		if value:
			self.hits += 1
		self.cache[key] = value
		return value


def correct_english(zh_obj: Dict[str, List[str]], en_obj: Dict[str, List[str]],
					official: OfficialEnglish) -> Dict[str, List[str]]:
	"""以中文结构为准修正英文：库里有官方译文就用官方，否则用元数据里的人工翻译"""
	zh_items = [(m, list(v)) for m, v in (zh_obj or {}).items() if clean(m)]
	en_items = [(m, list(v)) for m, v in (en_obj or {}).items() if clean(m)]
	if len(zh_items) != len(en_items):
		# 结构对不上时不做位置对齐，直接沿用元数据英文
		return {m: list(v) for m, v in en_items}

	result: Dict[str, List[str]] = {}
	for index, (module, lines) in enumerate(zh_items):
		en_module, en_lines = en_items[index]
		official_module = official.get(LogStore.TYPE_MODULE, module)
		en_module_final = official_module or en_module
		out_lines: List[str] = []
		for j, line in enumerate(lines):
			fallback = clean(en_lines[j]) if j < len(en_lines) else ''
			out_lines.append(official.get(LogStore.TYPE_LOG, line) or fallback or line)
		result[en_module_final] = out_lines
	return result


# ==================== 入库 ====================


def ensure_table() -> None:
	DatabaseManager.execute(CREATE_SQL, raise_on_error=True)


def upsert_dev(meta: Dict[str, Any], logs_value: str, dry_run: bool = False) -> Optional[int]:
	row = {
		'week': meta['week'],
		'region': meta['region'],
		'zone': REGION_INFO.get(meta['region'], {}).get('zone', 1),
		'bigver': meta.get('bigver') or infer_bigver(meta.get('versions', '')),
		'versions': meta.get('versions') or '',
		'title_zh': meta.get('title_zh') or '',
		'title_en': meta.get('title_en') or '',
		'post_id': meta.get('post_id') or '',
		'update_time': meta.get('update_time'),
		'release_date': meta.get('release_date'),
		'description': json.dumps(meta.get('description') or [], ensure_ascii=False),
		'attention': json.dumps(meta.get('attention') or [], ensure_ascii=False),
		'suspended': json.dumps(meta.get('suspended') or [], ensure_ascii=False),
		'devices': json.dumps(meta.get('devices') or [], ensure_ascii=False),
		'roms': json.dumps(meta.get('roms') or [], ensure_ascii=False),
		'logs': logs_value,
		'source': meta.get('source') or '',
		'show': 1 if meta.get('show', 'yes') not in (0, '0', 'no', False) else 0,
		'insdate': date.today().isoformat(),
		'update_date': int(datetime.now().timestamp()),
	}
	if dry_run:
		return None

	columns = list(row.keys())
	placeholders = ', '.join(['%s'] * len(columns))
	updates = ', '.join(f'`{c}` = VALUES(`{c}`)' for c in columns if c not in ('week', 'region'))
	DatabaseManager.execute(
		f"INSERT INTO `dev` ({', '.join(f'`{c}`' for c in columns)}) VALUES ({placeholders}) "
		f"ON DUPLICATE KEY UPDATE {updates}",
		params=tuple(row[c] for c in columns),
		raise_on_error=True,
	)
	found = DatabaseManager.query_one(
		"SELECT `id` FROM `dev` WHERE `week` = %s AND `region` = %s",
		params=(row['week'], row['region']),
	)
	return int(found[0]) if found else None


def backfill_roms(meta: Dict[str, Any], dev_id: Optional[int], dry_run: bool = False) -> int:
	"""把 roms.dev_week 标到本周的开发版记录上

	优先按元数据里的 device + version 精确匹配；没有机型清单时（如 HTML 来源）
	按 branch='X' + 区域 + 发布日期 匹配。
	"""
	zone = REGION_INFO.get(meta['region'], {}).get('zone', 1)
	updated = 0
	pairs = [(r['device'], r['version']) for r in (meta.get('roms') or []) if r.get('device') and r.get('version')]
	if pairs and not dry_run:
		for device, version in pairs:
			result = DatabaseManager.execute(
				"UPDATE `roms` SET `dev_week` = %s WHERE `device` = %s AND `version` = %s AND `zone` = %s",
				params=(meta['week'], device, version, zone), raise_on_error=True,
			)
			updated += 1
		return updated
	if pairs:
		return len(pairs)

	if not meta.get('release_date'):
		return 0
	if dry_run:
		return 0
	DatabaseManager.execute(
		"UPDATE `roms` SET `dev_week` = %s WHERE `branch` = 'X' AND `zone` = %s AND `release_date` = %s "
		"AND `dev_week` IS NULL",
		params=(meta['week'], zone, meta['release_date']), raise_on_error=True,
	)
	return 0


def import_meta(meta: Dict[str, Any], official: OfficialEnglish, dry_run: bool = False,
				verbose: bool = True) -> Dict[str, Any]:
	"""归档一周开发版：修正英文 → 写入 logs → upsert dev → 回填 roms.dev_week"""
	zh_obj = meta.get('logs_zh') or {}
	en_obj = meta.get('logs_en') or {}
	corrected = correct_english(zh_obj, en_obj, official)

	dates = [parse_date(r.get('release')) for r in (meta.get('roms') or [])]
	dates = [d for d in dates if d]
	if dates:
		meta['release_date'] = min(dates)
	elif meta.get('update_time'):
		meta['release_date'] = meta['update_time'][:10]

	logs_value = '[]'
	if zh_obj:
		# expand_mask：复用到库里已有多语言分组时，顺带把日文、德文等译文一并带出来
		logs_value = LogStore.write_logs({'logs_zh': zh_obj, 'logs_en': corrected},
									   dry_run=dry_run, expand_mask=True)

	dev_id = upsert_dev(meta, logs_value, dry_run=dry_run)
	rom_rows = backfill_roms(meta, dev_id, dry_run=dry_run)

	stat = {
		'week': meta['week'],
		'region': meta['region'],
		'source': meta.get('source'),
		'modules': len(zh_obj),
		'entries': sum(len(v) for v in zh_obj.values()),
		'official_hits': official.hits,
		'roms': rom_rows,
		'dev_id': dev_id,
	}
	if verbose:
		print(f"  [{stat['source']}] 第 {stat['week']} 周 {stat['region']}："
			  f"模块 {stat['modules']} / 条目 {stat['entries']}，"
			  f"官方英文命中 {stat['official_hits']}，机型 {stat['roms']}，dev.id={dev_id}")
	return stat


# ==================== 入口 ====================


def iter_sources(source: str, root: Path, weeks: Optional[Tuple[int, int]]):
	if source == 'hyperos':
		files = sorted(root.glob('*.json'), key=lambda p: int(p.stem) if p.stem.isdigit() else 0)
		loader = load_hyperos
	elif source == 'nuxtmr':
		files = sorted(root.glob('week-*-cn.json'), key=lambda p: int(re.search(r'(\d+)', p.stem).group(1)))
		loader = load_nuxtmr
	elif source == 'miuiroms':
		files = sorted(root.glob('week-*-CN.html'), key=lambda p: int(re.search(r'(\d+)', p.stem).group(1)))
		loader = load_miuiroms
	else:
		raise SystemExit(f'未知数据来源：{source}')

	seen = set()
	for path in files:
		match = re.search(r'(\d+)', path.stem)
		if not match:
			continue
		week = int(match.group(1))
		if week in seen:
			continue
		if weeks and not (weeks[0] <= week <= weeks[1]):
			continue
		seen.add(week)
		try:
			yield path, loader(path)
		except Exception as exc:  # 单个文件异常不应中断整体导入
			print(f"  ✖ {path.name} 解析失败：{type(exc).__name__}: {exc}")


def main() -> None:
	parser = argparse.ArgumentParser(description='导入开发版（周更）数据到 dev 表并回填 roms.dev_week')
	parser.add_argument('--source', choices=['hyperos', 'nuxtmr', 'miuiroms'], help='数据来源')
	parser.add_argument('--all', action='store_true', help='依次导入全部来源')
	parser.add_argument('--root', help='数据目录（默认取参考仓库路径）')
	parser.add_argument('--weeks', help='只导入指定周数范围，如 619-652、1-299')
	parser.add_argument('--region', default='cn', help='开发版区域：cn（默认）/ global')
	parser.add_argument('--dry-run', action='store_true', help='只统计与预览，不写库')
	parser.add_argument('--backfill-roms', action='store_true',
						help='不做导入，仅按 dev 表的发布日期回填 roms.dev_week')
	args = parser.parse_args()

	weeks = parse_weeks(args.weeks)
	if not args.dry_run:
		ensure_table()

	if args.backfill_roms:
		rows = DatabaseManager.query_all(
			"SELECT `week`, `region`, `release_date` FROM `dev` WHERE `release_date` IS NOT NULL")
		total = 0
		for week, region, release_date in rows or []:
			zone = REGION_INFO.get(region, {}).get('zone', 1)
			result = DatabaseManager.execute(
				"UPDATE `roms` SET `dev_week` = %s WHERE `branch` = 'X' AND `zone` = %s "
				"AND `release_date` = %s AND `dev_week` IS NULL",
				params=(week, zone, release_date), raise_on_error=True,
			)
			total += 1
		print(f"[{ts()}] 按日期回填完成，处理 {total} 个周次")
		return

	sources = ['hyperos', 'nuxtmr', 'miuiroms'] if args.all else ([args.source] if args.source else [])
	if not sources:
		raise SystemExit('请指定 --source 或 --all')

	official = OfficialEnglish()
	stats = []
	for source in sources:
		root = Path(args.root) if args.root else DEFAULT_ROOTS[source]
		if not root.exists():
			print(f"⚠ 跳过 {source}：目录不存在 {root}")
			continue
		print(f"\n[{ts()}] 导入 {source}：{root}")
		for path, meta in iter_sources(source, root, weeks):
			meta['region'] = args.region
			before = official.hits
			stats.append(import_meta(meta, official, dry_run=args.dry_run))
			official.hits = official.hits  # 保持累计

	print(f"\n[{ts()}] 完成：{len(stats)} 个周次，"
		  f"{'（dry-run 未写库）' if args.dry_run else ''}")
	if stats:
		print(f"    官方英文命中累计 {official.hits} 条，元数据命中 {len(official.cache)} 个键")


if __name__ == '__main__':
	main()
