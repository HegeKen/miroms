"""
批量从 ROM 的 recovery CDN 下载链接中提取 Android 安全补丁级别（aspatch），
并更新到数据库。
来源: HyperOS.fans test.py (aspatch)
"""
import sys
import time
import zipfile
import io
import requests
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import common

START_ID = 0


def get_ota_metadata(url: str, file_type: str = 'recovery', timeout: int = 30):
	"""从 OTA 文件中提取元数据（security_patch_level 等）"""
	try:
		response = requests.get(url, stream=True, timeout=timeout)
		if response.status_code != 200:
			return None

		# 对于 recovery 包，读取前 50MB 足以获取 metadata
		content = b''
		total_read = 0
		for chunk in response.iter_content(chunk_size=1024 * 1024):
			content += chunk
			total_read += len(chunk)
			if total_read >= 50 * 1024 * 1024:
				break

		# 尝试从 ZIP 中读取 metadata
		try:
			with zipfile.ZipFile(io.BytesIO(content)) as zf:
				for name in zf.namelist():
					if 'metadata' in name.lower():
						with zf.open(name) as meta_file:
							meta_content = meta_file.read().decode('utf-8', errors='replace')
							for line in meta_content.split('\n'):
								if 'security_patch_level' in line:
									patch_level = line.split('=')[1].strip()
									return patch_level
		except zipfile.BadZipFile:
			pass

		return None
	except requests.exceptions.RequestException:
		return None


def get_security_patch_from_url(url: str, file_type: str = 'recovery', timeout: int = 30):
	"""从 URL 获取安全补丁级别"""
	patch_level = get_ota_metadata(url, file_type, timeout)
	if patch_level:
		# 格式化为日期格式
		try:
			parts = patch_level.split('-')
			if len(parts) == 3:
				return f"{parts[0]}-{parts[1]}-{parts[2]}"
		except (IndexError, ValueError):
			pass
	return None


def fill_security_patches():
	"""批量填充安全补丁信息"""
	# 查询需要处理的记录（recovery 不为空且 aspatch 为空的记录，id 超过 46000）
	sql = (
		"SELECT id, device, code, version, recovery FROM roms "
		"WHERE id >= %s AND id >= 46000 AND recovery IS NOT NULL AND recovery != '' "
		"AND aspatch IS NULL ORDER BY id DESC"
	)
	rows = common.DatabaseManager.execute(sql, params=(START_ID,), fetch_one=False)
	if not rows:
		print("没有需要处理的记录")
		return

	total = len(rows)
	success = 0
	failed = 0

	print(f"共找到 {total} 条记录需要处理")

	for idx, row in enumerate(rows, 1):
		rom_id, device, code, version, recovery = row
		url = common.FileUtils.build_ota_url(recovery, version)

		link_text = f"\x1b]8;;{url}\x07{version}\x1b]8;;\x07"
		print(f"\r[{idx}/{total}] ID={rom_id} {device} {link_text} ...  ", end="", flush=True)

		try:
			asp = get_security_patch_from_url(url, 'recovery', timeout=30)
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
		asp = get_security_patch_from_url(url, 'recovery', timeout=30)
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
	if len(sys.argv) > 1 and sys.argv[1] == 'test':
		test_single()
	else:
		fill_security_patches()
