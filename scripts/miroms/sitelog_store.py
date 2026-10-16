"""sitelog 表写入：把「某站点的一批日志条目」幂等地同步进数据库。

站点日志的三种来源都汇到这里落库：

* ``import_sitelog.py``      —— 两个参考站点的 sitelog.json（v1 = nuxtmr、v2 = hyperos.fans）
* ``import_hub_sitelog.py``  —— hub 自身的 web / admin，条目由 git 记录推导

写入策略（``upsert_site``）：按唯一键 ``(kind, ver, log_date)`` 认领已有行，命中就原地
``UPDATE``，只 ``INSERT`` 新行、``DELETE`` 已被移除的行。既不能「先整体删再整体插」，
也不能 ``INSERT … ON DUPLICATE KEY UPDATE`` —— 两者都会推进 ``AUTO_INCREMENT``，
反复导入会烧出 id 空档（`roms` / `dev` 都踩过，见 README「自增 id 空档」）。
"""

import json
import logging
from datetime import date
from typing import Any, Dict, List, Optional

from miroms.database import DatabaseManager

logger = logging.getLogger(__name__)

# 行内字段（logs / icons 在写库前序列化为 JSON 文本）
_ROW_FIELDS = (
	'kind', 'ver', 'icon', 'log_date', 'devices_zh', 'devices_en',
	'logs', 'icons', 'sort_order',
)

_INSERT_SQL = (
	'INSERT INTO sitelog '
	'(site, kind, ver, icon, log_date, devices_zh, devices_en, logs, icons, sort_order, insdate) '
	'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)'
)

_UPDATE_SQL = (
	'UPDATE sitelog SET icon = %s, devices_zh = %s, devices_en = %s, logs = %s, '
	'icons = %s, sort_order = %s, insdate = %s WHERE id = %s'
)


def make_row(
	kind: str = 'entry',
	ver: str = '',
	icon: Optional[str] = None,
	log_date: Optional[date] = None,
	devices_zh: Optional[str] = None,
	devices_en: Optional[str] = None,
	logs: Optional[List[Dict[str, str]]] = None,
	icons: Optional[List[str]] = None,
	sort_order: int = 0,
) -> Dict[str, Any]:
	"""构造一行 sitelog 数据（logs / icons 传 Python 对象，落库时再序列化）。"""
	return {
		'kind': kind, 'ver': ver or '', 'icon': icon, 'log_date': log_date,
		'devices_zh': devices_zh, 'devices_en': devices_en,
		'logs': logs, 'icons': icons, 'sort_order': sort_order,
	}


def _json_text(value: Any) -> Optional[str]:
	if value in (None, '', [], {}):
		return None
	if isinstance(value, str):
		return value
	return json.dumps(value, ensure_ascii=False)


def upsert_site(site: str, rows: List[Dict[str, Any]], dry_run: bool = False) -> Dict[str, int]:
	"""把 ``rows`` 同步为 ``site`` 在 sitelog 表的全部数据，返回写入统计。

	``rows`` 里未出现的既有行会被删除，因此调用方需要传该站点的**全量**条目
	（含 ``kind='meta'`` 的站点级元信息行）。
	"""
	if dry_run:
		return {'inserted': 0, 'updated': 0, 'removed': 0, 'planned': len(rows)}

	existing = DatabaseManager.query_all(
		'SELECT id, kind, ver, log_date FROM sitelog WHERE site = %s',
		params=(site,),
	) or []
	existing_map: Dict[tuple, int] = {}
	for row_id, kind, ver, log_date in existing:
		existing_map[(kind, ver or '', log_date)] = int(row_id)

	today = date.today()
	seen = set()
	inserted = updated = 0
	for row in rows:
		key = (row.get('kind') or 'entry', row.get('ver') or '', row.get('log_date'))
		seen.add(key)
		logs_text = _json_text(row.get('logs'))
		icons_text = _json_text(row.get('icons'))
		row_id = existing_map.get(key)
		if row_id:
			DatabaseManager.execute(_UPDATE_SQL, params=(
				row.get('icon'), row.get('devices_zh'), row.get('devices_en'), logs_text,
				icons_text, int(row.get('sort_order') or 0), today, row_id,
			), raise_on_error=True)
			updated += 1
		else:
			DatabaseManager.execute(_INSERT_SQL, params=(
				site, key[0], key[1], row.get('icon'), key[2],
				row.get('devices_zh'), row.get('devices_en'), logs_text, icons_text,
				int(row.get('sort_order') or 0), today,
			), raise_on_error=True)
			inserted += 1

	removed = 0
	for key, row_id in existing_map.items():
		if key not in seen:
			DatabaseManager.execute('DELETE FROM sitelog WHERE id = %s', params=(row_id,), raise_on_error=True)
			removed += 1

	logger.info(f"sitelog[{site}]：新增 {inserted}、更新 {updated}、删除 {removed}")
	return {'inserted': inserted, 'updated': updated, 'removed': removed, 'planned': len(rows)}
