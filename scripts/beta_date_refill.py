#!/usr/bin/env python3
"""补充 / 修正 roms.beta_date

beta_date 取 recovery 包下载链接的 HTTP `Last-Modified`（文件上传时间，北京时间），
和 XMS 安装包的 release_date 口径一致。只需要一次 HEAD 请求；HEAD 不可用时退回
8KB Range GET 读响应头，不下载整个包。

取不到包时间时可用 --source db 回退到库里已有的 public_date / release_date。

用法：
    python3 scripts/beta_date_refill.py                     # 预演（只处理 beta_date 为空的行）
    python3 scripts/beta_date_refill.py --apply             # 写入
    python3 scripts/beta_date_refill.py --apply --source auto   # Last-Modified 失败时回退 db 日期
    python3 scripts/beta_date_refill.py --apply --source db     # 只用库内日期
    python3 scripts/beta_date_refill.py --apply --ids 1,2,3     # 指定 id（可覆盖已有 beta_date）
    python3 scripts/beta_date_refill.py --limit 20 --apply      # 分批
"""
import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common
from aspatch import HEAD_SIZE

DATE_FORMAT = '%a, %d %b %Y %H:%M:%S %Z'


def _header_date(value: Optional[str]) -> Optional[str]:
	"""Last-Modified（GMT）→ 北京时间日期（YYYY-MM-DD）"""
	if not value:
		return None
	try:
		dt = parsedate_to_datetime(value)
	except (TypeError, ValueError):
		try:
			dt = datetime.strptime(value, DATE_FORMAT)
		except ValueError:
			return None
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=timezone.utc)
	return (dt.astimezone(timezone.utc) + timedelta(hours=8)).strftime('%Y-%m-%d')


def get_last_modified(url: str, session: requests.Session, timeout: int = 30) -> Optional[str]:
	"""取 ROM 包的 HTTP Last-Modified（文件上传时间）"""
	try:
		response = session.head(url, allow_redirects=True, timeout=(5, timeout))
		if response.status_code == 200:
			value = _header_date(response.headers.get('Last-Modified'))
			if value:
				return value
	except requests.RequestException:
		pass

	# 部分 CDN 对 HEAD 不友好：退回 8KB Range GET，只读响应头
	try:
		headers = {'Range': f'bytes=0-{HEAD_SIZE - 1}'}
		with session.get(url, headers=headers, stream=True, timeout=(5, timeout)) as response:
			if response.status_code in (200, 206):
				return _header_date(response.headers.get('Last-Modified'))
	except requests.RequestException:
		return None
	return None


def db_fallback(row) -> Optional[str]:
	"""Last-Modified 拿不到时的库内回退：public_date → release_date"""
	public_date, release_date = row[4], row[5]
	for value in (public_date, release_date):
		if value:
			return value.strftime('%Y-%m-%d') if hasattr(value, 'strftime') else str(value)
	return None


def fill_beta_dates(limit: Optional[int] = None, min_id: int = 0,
									 apply: bool = False, source: str = 'last-modified',
									 ids: Optional[list] = None) -> None:
	"""批量补 / 修 beta_date

	Args:
		limit: 本次最多处理多少条（便于分批），None 为不限制
		min_id: 只处理 id 不低于该值的记录，默认 0（全部）
		apply: 是否写库；默认 False 只预演
		source: last-modified（包上传时间） / db（public→release） / auto（先 Last-Modified 再 db）
		ids: 指定 roms.id，给定后不再限制 beta_date 是否为空（用于覆盖修正）
	"""
	if ids:
		placeholders = ','.join(['%s'] * len(ids))
		sql = (
			"SELECT id, device, version, recovery, public_date, release_date "
			f"FROM roms WHERE id IN ({placeholders}) ORDER BY id DESC"
		)
		params = tuple(ids)
	else:
		sql = (
			"SELECT id, device, version, recovery, public_date, release_date "
			"FROM roms WHERE beta_date IS NULL AND id >= %s ORDER BY id DESC"
		)
		params = (min_id,)
		if limit:
			sql += " LIMIT %s"
			params = params + (limit,)

	rows = common.DatabaseManager.execute(sql, params=params, fetch_one=False) or []
	if not rows:
		print("没有需要补充 beta_date 的记录")
		return

	total = len(rows)
	print(f"共 {total} 条记录（source={source}，apply={apply}）")

	remote_count = 0
	db_count = 0
	failed = 0
	updated = 0
	session = requests.Session()
	try:
		for idx, row in enumerate(rows, 1):
			rom_id, device, version, recovery = row[0], row[1], row[2], row[3]
			value = None
			origin = ''

			if source in ('last-modified', 'auto') and recovery:
				url = common.FileUtils.build_ota_url(recovery, version)
				value = get_last_modified(url, session)
				if value:
					origin = 'last-modified'
			if not value and source in ('db', 'auto'):
				value = db_fallback(row)
				if value:
					origin = 'db'

			if value:
				if origin == 'last-modified':
					remote_count += 1
				else:
					db_count += 1
				if apply:
					common.DatabaseManager.execute(
						"UPDATE roms SET beta_date = %s WHERE id = %s",
						params=(value, rom_id), raise_on_error=True
					)
					updated += 1
				print(f"\r[{idx}/{total}] ID={rom_id} {device} {version} -> {value} ({origin})  ", end='', flush=True)
			else:
				failed += 1
				print(f"\r[{idx}/{total}] ID={rom_id} {device} {version} -> 无可用日期  ", end='', flush=True)

			if idx % 20 == 0:
				time.sleep(0.3)
	finally:
		session.close()

	print()
	print(f"完成：Last-Modified {remote_count} 条，db 回退 {db_count} 条，失败 {failed} 条"
				+ (f"，已写入 {updated} 条" if apply else "（预演，未写库）"))


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description='补充 / 修正 roms.beta_date（Last-Modified）')
	parser.add_argument('--apply', action='store_true', help='写库（默认只预演）')
	parser.add_argument('--limit', type=int, default=None, help='本次最多处理多少条')
	parser.add_argument('--min-id', type=int, default=0, help='只处理 id 不低于该值的记录')
	parser.add_argument('--source', choices=('last-modified', 'db', 'auto'), default='last-modified',
											help='last-modified=包上传时间；db=public_date→release_date；auto=先 Last-Modified 再 db')
	parser.add_argument('--ids', type=str, default='', help='指定 roms.id（逗号分隔），可覆盖已有 beta_date')
	args = parser.parse_args()

	id_list = [int(part.strip()) for part in args.ids.split(',') if part.strip()] if args.ids else None
	fill_beta_dates(limit=args.limit, min_id=args.min_id, apply=args.apply,
									source=args.source, ids=id_list)
