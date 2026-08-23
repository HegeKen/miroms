from typing import List

from miroms.utils import FileUtils
from miroms.firmware import FirmwareParser
from miroms.database import DatabaseManager


class DataRecorder:
		"""
		新数据记录管理

		合并原函数:
		- writeData() -> record_new_rom()
		- writeFlag() -> record_flag_mapping()
		- checkExist() -> check_exists()
		"""

		@classmethod
		def record_new_rom(cls, filename: str, flag: str = ""):
				"""记录新发现的ROM (原: writeData)"""
				FileUtils.append_to_file("NewROMs.txt", filename)
				if ".zip" in filename or ".tgz" in filename:
						actual_flag = flag or FirmwareParser.extract_flag(filename) or "unknown"
						print(f"发现\t{actual_flag}\t分支有未收录的新版本")

		@classmethod
		def record_flag_mapping(cls, flag: str, device: str):
				"""记录标志映射 (原: writeFlag)"""
				content = f'"{flag}":"{device}",'
				FileUtils.append_to_file("Flags.json", content)

		@classmethod
		def check_exists(cls, filename: str) -> str:
				"""检查ROM是否已存在 (原: checkExist)"""
				# 快速过滤
				if not ("OS" in filename or "A1" in filename):
						return "UI Maybe"

				if "blockota" in filename:
						return "OTA ROM"

				# 读取现有记录
				base = FileUtils.get_base_path()
				existing = ""
				try:
						with open(f"{base}scripts/NewROMs.txt", 'r', encoding='utf-8') as f:
								existing = f.read()
				except FileNotFoundError:
						pass

				# 检查设备代码
				device_code = FirmwareParser.get_device_code(filename)
				if not device_code:
						cls.record_new_rom(filename)
						cls.record_flag_mapping(FirmwareParser.extract_flag(filename) or "", "")
						return "New ROM"

				# 检查是否已存在
				try:
						device_data = FileUtils.load_device_data(device_code)
						if filename in str(device_data) or filename in existing:
								return "Already Exist"
				except FileNotFoundError:
						pass

				# 解析并记录新ROM
				parsed = FirmwareParser.parse_filename(filename)
				if parsed and parsed.get("code"):
						cls.record_new_rom(filename, parsed["code"])
						DatabaseManager.check_and_update(
								filename, parsed["filetype"], parsed["device"],
								parsed["code"], parsed["android"], parsed["version"],
								parsed["type"], parsed["bigver"], parsed["region"],
								parsed["tag"], parsed["zone"], parsed["branch"]
						)
						return "New ROM"

				return "Parse Error"
