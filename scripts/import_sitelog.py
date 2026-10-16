#!/usr/bin/env python3
"""把两个参考站点的站点日志（sitelog.json）导入 sitelog 表。

站点日志原先各自手写在参考仓库里，结构不同：

* NuxtMR（api/v1） ``NuxtMR/public/MRData/data/sitelog.json``::

      {"log": [{"sudate": "2024.02.18", "ver": "V1.5.0",
                "zh-cn": "新增机型…", "en-us": "New Devices…",
                "log": [{"zh-cn": "…", "en-us": "…"}]}]}

* HyperOS.fans（api/v2） ``HyperOS.fans/public/data/sitelog.json``::

      {"icons": ["mdi-web", …],
       "logs": [{"siteVer": "V0.9.6", "icon": "mdi-plus-box", "date": "2026.09.23",
                 "log": [{"zh": "…", "en": "…"}]}]}

导入后统一存 sitelog 表（见 db_structure/sitelog.sql），用 ``site`` 列区分站点；
站点级元信息（hyperos.fans 的 icons 调色板）存 ``kind='meta'`` 的一行，
其余每个日志条目存 ``kind='entry'`` 的若干行，``sort_order`` 保留源文件顺序。

用法::

    python3 scripts/import_sitelog.py --all            # 导入两个站点（默认）
    python3 scripts/import_sitelog.py --source nuxtmr  # 只导入 NuxtMR
    python3 scripts/import_sitelog.py --dry-run        # 只统计不写库
    python3 scripts/import_sitelog.py --root /path/to/sitelog.json  # 指定单个文件

导入是幂等的：按 ``(kind, ver, log_date)`` 认领已有行，命中就原地 ``UPDATE``，
只 ``INSERT`` 新行、``DELETE`` 被删掉的行。不能「先整体删再整体插」或
``INSERT … ON DUPLICATE KEY UPDATE``——两者都会推进 ``AUTO_INCREMENT``，
反复导入会烧出一堆 id 空档（`roms` / `dev` 都踩过这个坑，见 README「自增 id 空档」）。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from miroms.sitelog_store import make_row, upsert_site  # noqa: E402

# 参考仓库里的 sitelog.json 位置（与 import_dev_week.py 的 DEFAULT_ROOTS 同风格）
DEFAULT_ROOTS: Dict[str, Path] = {
	'nuxtmr': Path('/Users/hegeken/Desktop/Codes/NuxtMR/public/MRData/data/sitelog.json'),
	'hyperos': Path('/Users/hegeken/Desktop/Codes/HyperOS.fans/public/data/sitelog.json'),
}

# 站点标识（写库值）与来源目录名的对应关系，站点标识同时决定导出到哪个 api 版本
SITE_IDS: Dict[str, str] = {
	'nuxtmr': 'nuxtmr',
	'hyperos': 'hyperos.fans',
}


def parse_date(value: Any) -> Optional[date]:
	"""把源文件里的日期字符串解析成 date（支持 2024.02.18 / 2024-02-18）。"""
	if not value:
		return None
	text = str(value).strip()
	if not text:
		return None
	for fmt in ('%Y.%m.%d', '%Y-%m-%d', '%Y/%m/%d'):
		try:
			return datetime.strptime(text, fmt).date()
		except ValueError:
			continue
	return None


def normalize_logs(items: Any) -> List[Dict[str, str]]:
	"""把各站点的日志条目统一成 [{"zh": ..., "en": ...}, ...]。"""
	result: List[Dict[str, str]] = []
	if not isinstance(items, list):
		return result
	for item in items:
		if not isinstance(item, dict):
			continue
		zh = item.get('zh', item.get('zh-cn', '')) or ''
		en = item.get('en', item.get('en-us', '')) or ''
		result.append({'zh': str(zh), 'en': str(en)})
	return result


def load_nuxtmr(path: Path) -> Dict[str, Any]:
	"""解析 NuxtMR 版 sitelog.json。"""
	data = json.loads(path.read_text(encoding='utf-8'))
	entries = data.get('log') or []
	rows: List[Dict[str, Any]] = []
	for index, entry in enumerate(entries):
		if not isinstance(entry, dict):
			continue
		rows.append({
			'kind': 'entry',
			'ver': str(entry.get('ver') or ''),
			'icon': None,
			'log_date': parse_date(entry.get('sudate')),
			'devices_zh': entry.get('zh-cn') or None,
			'devices_en': entry.get('en-us') or None,
			'logs': normalize_logs(entry.get('log')),
			'icons': None,
			'sort_order': index,
		})
	return {'rows': rows, 'meta': None}


def load_hyperos(path: Path) -> Dict[str, Any]:
	"""解析 HyperOS.fans 版 sitelog.json。"""
	data = json.loads(path.read_text(encoding='utf-8'))
	entries = data.get('logs') or []
	rows: List[Dict[str, Any]] = []
	for index, entry in enumerate(entries):
		if not isinstance(entry, dict):
			continue
		rows.append({
			'kind': 'entry',
			'ver': str(entry.get('siteVer') or ''),
			'icon': entry.get('icon') or None,
			'log_date': parse_date(entry.get('date')),
			'devices_zh': None,
			'devices_en': None,
			'logs': normalize_logs(entry.get('log')),
			'icons': None,
			'sort_order': index,
		})
	meta = {'icons': list(data.get('icons') or [])}
	return {'rows': rows, 'meta': meta}


LOADERS = {
	'nuxtmr': load_nuxtmr,
	'hyperos': load_hyperos,
}


def import_source(source: str, path: Path, dry_run: bool = False) -> int:
	"""导入单个站点，返回写入的条目数。"""
	site = SITE_IDS[source]
	if not path.exists():
		print(f'  ⚠ 文件不存在，跳过：{path}', file=sys.stderr)
		return 0

	parsed = LOADERS[source](path)
	rows = parsed['rows']
	meta = parsed['meta']
	print(f'  {site}：{len(rows)} 条日志' + (f'，调色板 {len(meta["icons"])} 项' if meta else ''))

	if dry_run:
		for row in rows[:3]:
			print(f'    · {row["log_date"]} {row["ver"]} {str(row["logs"])[:60]}')
		print('  （--dry-run，未写库）')
		return len(rows)

	# 幂等落库：按 (kind, ver, log_date) 认领已有行，命中原地 UPDATE，
	# 只 INSERT 新行、DELETE 被移除的行（实现见 miroms/sitelog_store.py）。
	planned: List[Dict[str, Any]] = []
	if meta and meta.get('icons'):
		planned.append(make_row(kind='meta', icons=meta['icons']))
	planned.extend(make_row(**row) for row in rows)

	stats = upsert_site(site, planned)
	print(f"    写入：新增 {stats['inserted']} 行、更新 {stats['updated']} 行、删除 {stats['removed']} 行")
	return len(rows)


def main() -> None:
	parser = argparse.ArgumentParser(description='导入站点日志（sitelog.json）到 sitelog 表')
	parser.add_argument('--source', choices=sorted(DEFAULT_ROOTS), help='数据来源站点')
	parser.add_argument('--all', action='store_true', help='导入全部站点（默认行为）')
	parser.add_argument('--root', help='指定 sitelog.json 路径（配合 --source 使用）')
	parser.add_argument('--dry-run', action='store_true', help='只统计与预览，不写库')
	args = parser.parse_args()

	if args.root:
		if not args.source:
			parser.error('--root 需要同时指定 --source')
		sources = [args.source]
		paths = {args.source: Path(args.root)}
	else:
		sources = [args.source] if args.source else sorted(DEFAULT_ROOTS)
		paths = dict(DEFAULT_ROOTS)

	total = 0
	for source in sources:
		print(f'--- 导入 {SITE_IDS[source]} ({source}) ---')
		total += import_source(source, paths[source], dry_run=args.dry_run)

	print(f'\n完成：共 {total} 条站点日志' + ('（未写库）' if args.dry_run else '已写入 sitelog 表'))


if __name__ == '__main__':
	main()
