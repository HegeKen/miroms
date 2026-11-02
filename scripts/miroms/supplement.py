"""写入后完整性检查与补录

所有抓取脚本最终都经由 DataRecorder.check_exists → DatabaseManager.check_and_update
写入 roms 表。新行只有版本元数据，exporter 需要导出的 recovery / fastboot / aspatch /
各类日期 / 日志等字段要么等后续脚本逐条补，要么一直为空。这里在写入成功后立刻做一次
主动检查：只补空字段、不覆盖已有值，任一步失败只记日志，不影响主写入流程。
"""
import json
import logging
import re
import struct
import zlib
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterator, Optional, Tuple

import requests

from miroms.database import DatabaseManager
from miroms.utils import FileUtils

logger = logging.getLogger(__name__)

# Fastboot 全量包查询接口（与 get_current_fastboot.py 一致）
FASTBOOT_API = "https://update.intl.miui.com/updates/miota-fullrom.php?d="
# 单次 Range 请求读取的字节数：metadata 恒为 zip 首部第一个条目
HEAD_SIZE = 8192
LOCAL_HEADER_SIZE = 30
PATCH_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _blank(value: Any) -> bool:
	"""空值判断：None / 空串 / 空 JSON 数组 / 字面量 null"""
	if value is None:
		return True
	text = str(value).strip()
	return text in ('', '[]') or text.lower() == 'null'


def _today() -> str:
	return date.today().strftime('%Y-%m-%d')


def _header_date(value: Optional[str]) -> Optional[str]:
	"""Last-Modified（GMT）→ 北京时间日期（YYYY-MM-DD）"""
	if not value:
		return None
	try:
		dt = parsedate_to_datetime(value)
	except (TypeError, ValueError):
		return None
	if dt.tzinfo is None:
		dt = dt.replace(tzinfo=timezone.utc)
	return (dt.astimezone(timezone.utc) + timedelta(hours=8)).strftime('%Y-%m-%d')


def _last_modified(url: str, session: requests.Session,
				   timeout: int = 30) -> Optional[str]:
	"""取包文件的 Last-Modified（上传时间）

	HEAD 不可用时退回 8KB Range GET，只读响应头，不下载整个包。
	不能用 FileUtils.get_url_last_modified：它在失败时回落今天，补录时不能写错日期。
	"""
	try:
		response = session.head(url, allow_redirects=True, timeout=(5, timeout))
		if response.status_code == 200:
			value = _header_date(response.headers.get('Last-Modified'))
			if value:
				return value
	except requests.RequestException:
		pass

	try:
		headers = {'Range': f'bytes=0-{HEAD_SIZE - 1}'}
		with session.get(url, headers=headers, stream=True,
						 timeout=(5, timeout)) as response:
			if response.status_code in (200, 206):
				return _header_date(response.headers.get('Last-Modified'))
	except requests.RequestException:
		return None
	return None


def _fetch_fastboot(code: str, branch: str, region: str,
					version: str) -> str:
	"""请求 Fastboot 全量包接口，返回与当前 version 匹配的包名（无匹配返回空串）"""
	url = (FASTBOOT_API + str(code or '') + '&b=' + str(branch or 'F')
		   + '&r=' + str(region or 'cn') + '&n=')
	headers = {
		'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
		'Connection': 'close',
	}
	try:
		response = requests.post(url, headers=headers, timeout=(5, 10))
		if response.status_code != 200:
			return ''
		data = json.loads(response.content.decode('utf8') or '{}')
	except (requests.RequestException, ValueError):
		return ''

	roms = data.get('LatestFullRom')
	if isinstance(roms, dict):
		roms = [roms]
	if not isinstance(roms, list):
		return ''
	for rom in roms:
		filename = (rom or {}).get('filename') or ''
		if filename and version and version in filename:
			return filename
	return ''


def _iter_head_entries(head: bytes) -> Iterator[Tuple[str, bytes]]:
	"""遍历包首部缓冲区内的 zip 本地头条目，产出 (条目名, 解密后的数据)"""
	pos = 0
	while pos + LOCAL_HEADER_SIZE <= len(head) and head[pos:pos + 4] == b'PK\x03\x04':
		method = struct.unpack('<H', head[pos + 8:pos + 10])[0]
		csize = struct.unpack('<I', head[pos + 18:pos + 22])[0]
		name_len, extra_len = struct.unpack('<HH', head[pos + 26:pos + 30])
		name = head[pos + LOCAL_HEADER_SIZE:pos + LOCAL_HEADER_SIZE + name_len].decode(
			'utf-8', errors='replace')
		data = head[pos + LOCAL_HEADER_SIZE + name_len + extra_len:]
		data = data[:csize] if csize else data

		if method == 0:
			yield name, data
		elif method == 8:
			try:
				yield name, zlib.decompressobj(-15).decompress(data)
			except zlib.error:
				yield name, b''
		else:
			yield name, b''

		# 无压缩大小信息时（如 data descriptor）无法继续向后遍历
		if not csize:
			return
		pos += LOCAL_HEADER_SIZE + name_len + extra_len + csize


def _extract_metadata(head: bytes) -> str:
	"""从包首部取出 META-INF/com/android/metadata 的明文内容"""
	for name, data in _iter_head_entries(head):
		if name.lower().endswith('/metadata'):
			return data.decode('utf-8', errors='replace')
	return ''


def _parse_patch_level(metadata: str) -> Optional[str]:
	"""从 metadata 中解析安全补丁级别（post-security-patch-level=YYYY-MM-DD）"""
	for line in metadata.splitlines():
		key, sep, value = line.partition('=')
		if not sep:
			continue
		if key.strip().lower().replace('_', '-') not in (
				'security-patch-level', 'post-security-patch-level'):
			continue
		value = value.strip()
		if PATCH_PATTERN.match(value):
			return value
	return None


def _fetch_security_patch(url: str, timeout: int = 30) -> Optional[str]:
	"""只取 recovery 包首部的 metadata，返回安全补丁级别（失败返回 None）

	与 data/scripts/aspatch.py 同一实现；这里内联是为了不依赖脚本目录
	（aspatch.py import common，会拉起整套重依赖）。
	"""
	headers = {'Range': f'bytes=0-{HEAD_SIZE - 1}'}
	try:
		with requests.get(url, headers=headers, stream=True,
						  timeout=(5, timeout)) as response:
			if response.status_code not in (200, 206):
				return None
			head = b''
			for chunk in response.iter_content(HEAD_SIZE):
				head += chunk
				if len(head) >= HEAD_SIZE:
					break
			return _parse_patch_level(_extract_metadata(head))
	except requests.RequestException:
		return None


class RomSupplement:
	"""写入后完整性检查与补录（只补空字段）"""

	ROM_SQL = (
		'SELECT device, code, region, branch, android, version, zone, '
		'recovery, fastboot, beta_date, release_date, public_date, insdate, logs, aspatch '
		'FROM roms WHERE id = %s'
	)

	@classmethod
	def supplement(cls, rom_id: Optional[int]) -> None:
		"""检查并补录指定 ROM；任何异常都只记日志，不向调用方抛出"""
		if not rom_id:
			return
		try:
			cls._supplement(int(rom_id))
		except Exception as exc:
			logger.warning('ROM 补录失败（id=%s）：%s: %s',
						   rom_id, type(exc).__name__, exc)

	@classmethod
	def _supplement(cls, rom_id: int) -> None:
		row = DatabaseManager.query_one(cls.ROM_SQL, params=(rom_id,))
		if not row:
			return

		(device, code, region, branch, android, version, zone, recovery, fastboot,
		 beta_date, release_date, public_date, insdate, logs, aspatch) = row

		need_recovery = _blank(recovery)
		need_logs = _blank(logs)
		need_fastboot = _blank(fastboot)
		need_aspatch = _blank(aspatch)
		need_beta = _blank(beta_date)
		need_public = _blank(public_date)
		need_insdate = _blank(insdate)
		need_release = _blank(release_date)

		if not any((need_recovery, need_logs, need_fastboot, need_aspatch,
					need_beta, need_public, need_insdate, need_release)):
			return

		updates: Dict[str, Any] = {}

		# 1. 更新日志 + 卡刷包：接口一次返回，能补则一起补
		if need_recovery or need_logs:
			changelog = ''
			try:
				result = cls._fetch_changelog(
					device, code, region, branch, zone, android, version)
				changelog = result.get('changelog') or ''
				latest = (result.get('recovery') or '').split('?')[0]
				if need_recovery and latest and version and version in latest:
					recovery = latest
					updates['recovery'] = latest
			except Exception as exc:
				logger.warning('更新日志请求失败（id=%s）：%s: %s',
							   rom_id, type(exc).__name__, exc)
			if need_logs and changelog:
				try:
					from miroms.logs_store import LogStore
					column = LogStore.ZH_COLUMN if region == 'cn' else LogStore.EN_COLUMN
					updates['logs'] = LogStore.write_logs({column: json.loads(changelog)})
				except Exception as exc:
					logger.warning('日志入库失败（id=%s）：%s: %s',
								   rom_id, type(exc).__name__, exc)

		# 2. 线刷包
		if need_fastboot:
			filename = _fetch_fastboot(code, branch, region, version)
			if filename:
				fastboot = filename
				updates['fastboot'] = filename

		# 3. 安全补丁
		if need_aspatch and not _blank(recovery):
			try:
				asp = _fetch_security_patch(FileUtils.build_ota_url(recovery, version))
				if asp:
					updates['aspatch'] = asp
			except Exception as exc:
				logger.warning('安全补丁获取失败（id=%s）：%s: %s',
							   rom_id, type(exc).__name__, exc)

		# 4. 各类日期（只补空值）
		if need_beta or need_public:
			try:
				with requests.Session() as session:
					if need_beta and not _blank(recovery):
						value = _last_modified(
							FileUtils.build_ota_url(recovery, version), session)
						if value:
							updates['beta_date'] = value
					if need_public and not _blank(fastboot):
						value = _last_modified(
							FileUtils.build_ota_url(fastboot, version), session)
						if value:
							updates['public_date'] = value
			except Exception as exc:
				logger.warning('日期获取失败（id=%s）：%s: %s',
							   rom_id, type(exc).__name__, exc)
		if need_insdate:
			updates['insdate'] = _today()
		if need_release:
			updates['release_date'] = _today()

		if not updates:
			return

		updates['update_date'] = int(datetime.now().timestamp())
		assignments = ', '.join(f'{column} = %s' for column in updates)
		try:
			DatabaseManager.execute(
				f'UPDATE roms SET {assignments} WHERE id = %s',
				params=tuple(updates.values()) + (rom_id,), raise_on_error=True)
			logger.info('ROM 补录完成（id=%s）：%s', rom_id, ', '.join(updates))
		except Exception as exc:
			logger.warning('ROM 补录写库失败（id=%s）：%s: %s',
						   rom_id, type(exc).__name__, exc)

	@classmethod
	def _fetch_changelog(cls, device: str, code: str, region: str, branch: str,
						 zone: Any, android: str, version: str) -> Dict[str, Any]:
		"""请求 OTA 接口，返回 {'changelog': json 字符串, 'recovery': 包名}"""
		from miroms.changelog import ChangelogManager
		from miroms.crypto import CryptoManager
		from miroms.firmware import FirmwareParser

		form = FirmwareParser.build_ota_form(
			device, code, region, branch, zone, android, version)
		encrypted = CryptoManager.encrypt(json.dumps(form))
		return ChangelogManager.fetch_for_db(encrypted, device, version) or {}
