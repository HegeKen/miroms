"""
批量从 ROM 的 recovery 包中提取 Android 安全补丁级别（aspatch），并更新到数据库。
来源: HyperOS.fans test.py (aspatch)

实现说明：
recovery 包（A/B OTA zip，通常 5GB 以上）的元数据固定存放在包首部的
META-INF/com/android/metadata，且为明文存储（stored 不压缩），其中
post-security-patch-level 即安全补丁级别。因此对每个包只需发起一次
约 8KB 的 HTTP Range 请求即可取到，无需下载整个包。
"""
import re
import struct
import sys
import time
import zlib
from pathlib import Path
from typing import Iterator, Optional, Tuple

import requests

sys.path.insert(0, str(Path(__file__).parent))

import common

# 单次 Range 请求读取的字节数（metadata 恒为包首部的第一个条目，约 700 字节）
HEAD_SIZE = 8192
LOCAL_HEADER_SIZE = 30
# 默认只处理 id 不低于该值的记录，见 fill_security_patches
MIN_ID = 46000
DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def _iter_head_entries(head: bytes) -> Iterator[Tuple[str, bytes]]:
	"""遍历包首部缓冲区内的 zip 本地头条目，产出 (条目名, 解密后的数据)"""
	pos = 0
	while pos + LOCAL_HEADER_SIZE <= len(head) and head[pos:pos + 4] == b'PK\x03\x04':
		method = struct.unpack('<H', head[pos + 8:pos + 10])[0]
		csize = struct.unpack('<I', head[pos + 18:pos + 22])[0]
		name_len, extra_len = struct.unpack('<HH', head[pos + 26:pos + 30])
		name = head[pos + LOCAL_HEADER_SIZE:pos + LOCAL_HEADER_SIZE + name_len].decode('utf-8', errors='replace')
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
	"""从 metadata 内容中解析安全补丁级别（post-security-patch-level=YYYY-MM-DD）"""
	for line in metadata.splitlines():
		key, sep, value = line.partition('=')
		if not sep:
			continue
		# metadata 中的键为连字符形式，同时兼容下划线写法
		if key.strip().lower().replace('_', '-') not in ('security-patch-level', 'post-security-patch-level'):
			continue
		value = value.strip()
		if DATE_PATTERN.match(value):
			return value
	return None


def get_security_patch(url: str, session: requests.Session, timeout: int = 30) -> Optional[str]:
	"""只取包首部的 metadata，返回安全补丁级别（失败或无该字段时返回 None）"""
	headers = {'Range': f'bytes=0-{HEAD_SIZE - 1}'}
	try:
		with session.get(url, headers=headers, stream=True, timeout=(5, timeout)) as response:
			if response.status_code not in (200, 206):
				return None

			# 服务端不支持 Range 时也不会读完整个包
			head = b''
			for chunk in response.iter_content(HEAD_SIZE):
				head += chunk
				if len(head) >= HEAD_SIZE:
					break

			return _parse_patch_level(_extract_metadata(head))
	except requests.exceptions.RequestException:
		return None


def fill_security_patches(limit: Optional[int] = None, min_id: int = MIN_ID):
	"""批量填充安全补丁信息

	Args:
		limit: 本次最多处理的记录数，None 为不限制（便于分批运行）
		min_id: 只处理 id 不低于该值的记录。默认 46000 —— 更早的包大多已从
			CDN 下线（抽样 404 居多），放开会带来大量无效请求
	"""
	sql = (
		"SELECT id, device, code, version, recovery FROM roms "
		"WHERE id >= %s AND recovery IS NOT NULL AND recovery != '' "
		"AND aspatch IS NULL ORDER BY id DESC"
	)
	params = [min_id]
	if limit:
		sql += " LIMIT %s"
		params.append(limit)
	params = tuple(params)

	rows = common.DatabaseManager.execute(sql, params=params, fetch_one=False)
	if not rows:
		print("没有需要处理的记录")
		return

	total = len(rows)
	success = 0
	failed = 0

	print(f"共找到 {total} 条记录需要处理")

	session = requests.Session()
	try:
		for idx, row in enumerate(rows, 1):
			rom_id, device, code, version, recovery = row
			url = common.FileUtils.build_ota_url(recovery, version)

			link_text = f"\x1b]8;;{url}\x07{version}\x1b]8;;\x07"
			print(f"\r[{idx}/{total}] ID={rom_id} {device} {link_text} ...  ", end="", flush=True)

			try:
				asp = get_security_patch(url, session)
				if asp:
					common.DatabaseManager.execute(
						"UPDATE roms SET aspatch = %s WHERE id = %s",
						params=(asp, rom_id)
					)
					print(f"\r[{idx}/{total}] {device} {version} -> {asp}  ", end="", flush=True)
					success += 1
				else:
					print(f"\r[{idx}/{total}] {device} {version} -> 无补丁信息  ", end="", flush=True)
					failed += 1
			except Exception as e:
				print(f"\r[{idx}/{total}] {device} {version} -> {e}  ", end="", flush=True)
				failed += 1

			if idx % 50 == 0:
				time.sleep(1)
	finally:
		session.close()

	print(f"\n处理完成：成功 {success}，失败 {failed}，共 {total}")


def test_single(rom_id: int = 52763):
	"""测试单条记录的安全补丁获取"""
	sql = "SELECT id, device, code, version, recovery FROM roms WHERE id = %s"
	rows = common.DatabaseManager.execute(sql, params=(rom_id,), fetch_one=True)
	if not rows:
		print("没有找到指定记录")
		return

	rom_id, device, code, version, recovery = rows
	url = common.FileUtils.build_ota_url(recovery, version)

	print(f"测试记录: ID={rom_id}, device={device}, version={version}")
	print(f"recovery: {recovery}")
	print(f"URL: {url}")
	print()

	print("=== 获取安全补丁 ===")
	try:
		with requests.Session() as session:
			asp = get_security_patch(url, session)
		if asp:
			common.DatabaseManager.execute(
				"UPDATE roms SET aspatch = %s WHERE id = %s",
				params=(asp, rom_id)
			)
			print(f"已写入数据库: aspatch = {asp}")
		else:
			print("未获取到补丁信息")
	except Exception as e:
		print(f"异常: {e}")
		import traceback
		traceback.print_exc()


if __name__ == "__main__":
	args = sys.argv[1:]
	if args and args[0] == 'test':
		test_single(int(args[1]) if len(args) > 1 else 52763)
	else:
		# 用法: aspatch.py [limit] [min_id]
		#   limit  —— 本次最多处理的记录数，省略为不限制
		#   min_id —— 只处理 id 不低于该值的记录，省略则用 MIN_ID(46000)；
		#             传 0 可放开下限，一次性补齐更早的历史记录
		fill_security_patches(
			limit=int(args[0]) if len(args) > 0 else None,
			min_id=int(args[1]) if len(args) > 1 else MIN_ID,
		)
