from pathlib import Path
from datetime import datetime

from miroms.firmware import FirmwareParser
from miroms.database import DatabaseManager


# 日志文件路径（相对于项目根目录）
_LOG_DIR = Path(__file__).resolve().parent.parent.parent
_NEW_ROMS_LOG = _LOG_DIR / "new_roms.txt"
_NEW_FLAGS_LOG = _LOG_DIR / "new_flags.txt"


def _log_append(path: Path, line: str):
	"""追加一行到日志文件"""
	path.parent.mkdir(parents=True, exist_ok=True)
	with open(path, 'a', encoding='utf-8') as f:
		f.write(line + "\n")


class DataRecorder:
		"""
		新数据记录管理（V3 数据库驱动）

		所有数据以 V3 数据库为基准，同时写入本地日志供后续处理。
		"""

		@classmethod
		def record_flag_mapping(cls, flag: str, device: str):
				"""记录设备标志映射到 devices 表"""
				if not flag or not device:
						return
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

				ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

				# 未收录，解析并写入数据库
				device_code = FirmwareParser.get_device_code(filename)
				if not device_code:
						flag = FirmwareParser.extract_flag(filename) or ""
						if flag:
								cls.record_flag_mapping(flag, "")
								_log_append(_NEW_FLAGS_LOG, f"{ts}\t{flag}\t{filename}")
						_log_append(_NEW_ROMS_LOG, f"{ts}\t\t{filename}")
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
							_log_append(_NEW_ROMS_LOG, f"{ts}\t{parsed['device']}\t{parsed['version']}\t{filename}")
							print(f"新 ROM 已入库: {parsed['device']}\t{parsed['version']}")
							return "New ROM"

				return "Parse Error"
