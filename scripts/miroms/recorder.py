from typing import List

from miroms.firmware import FirmwareParser
from miroms.database import DatabaseManager


class DataRecorder:
		"""
		新数据记录管理（V3 数据库驱动）

		所有数据以 V3 数据库为基准，不再依赖本地文件。
		"""

		@classmethod
		def record_flag_mapping(cls, flag: str, device: str):
				"""记录设备标志映射到 devices 表"""
				if not flag or not device:
						return
				# 检查是否已存在
				existing = DatabaseManager.query_one(
						"SELECT id FROM devices WHERE code = %s AND device = %s",
						params=(flag, device)
				)
				if existing:
						return
				DatabaseManager.execute(
						"INSERT INTO devices(code, device, region, tag) VALUES (%s, %s, '', '')",
						params=(flag, device)
				)

		@classmethod
		def check_exists(cls, filename: str) -> str:
				"""检查ROM是否已存在（基于 V3 数据库 roms 表）"""
				# 快速过滤
				if not ("OS" in filename or "A1" in filename):
						return "UI Maybe"

				if "blockota" in filename:
						return "OTA ROM"

				# 解析文件名获取版本号
				parsed = FirmwareParser.parse_filename(filename)
				version = parsed.get("version", "") if parsed else ""
				code = parsed.get("code", "") if parsed else ""

				# 按 version + code 去重
				if version and code:
						existing = DatabaseManager.query_one(
								"SELECT id FROM roms WHERE version = %s AND code = %s LIMIT 1",
								params=(version, code)
						)
						if existing:
								return "Already Exist"

				# 按 recovery/fastboot 文件名去重
				if version:
						existing = DatabaseManager.query_one(
								"SELECT id FROM roms WHERE (recovery = %s OR fastboot = %s) AND version = %s LIMIT 1",
								params=(filename, filename, version)
						)
						if existing:
								return "Already Exist"

				# 未收录，解析并写入数据库
				device_code = FirmwareParser.get_device_code(filename)
				if not device_code:
						flag = FirmwareParser.extract_flag(filename) or ""
						if flag:
								cls.record_flag_mapping(flag, "")
						print(f"发现未收录的新设备标志: {flag}\t{filename}")
						return "New ROM"

				if parsed and parsed.get("code"):
						DatabaseManager.check_and_update(
								filename, parsed["filetype"], parsed["device"],
								parsed["code"], parsed["android"], parsed["version"],
								parsed["type"], parsed["bigver"], parsed["region"],
								parsed["tag"], parsed["zone"], parsed["branch"]
						)
						flag = parsed.get("code", "")
						device = parsed.get("device", "")
						if flag and device:
								cls.record_flag_mapping(flag, device)
						print(f"新 ROM 已入库: {parsed['device']}\t{parsed['version']}")
						return "New ROM"

				return "Parse Error"
