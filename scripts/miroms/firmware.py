import json
from typing import Set, List, Tuple, Dict, Any, Optional, Union

from miroms.constants import _const
from miroms.utils import VersionUtils
from miroms.database import DatabaseManager
from miroms.data import flags


class FirmwareParser:
		"""
		固件文件名解析

		合并原函数:
		- getDeviceCode() -> get_device_code()
		- getBranchcode() -> extract_flag()
		- getData() -> parse_filename()
		- OTAFormer() -> build_ota_form()
		"""

		# 设备标志映射（简化展示，实际需要完整映射）
		FLAGS_MAP: Dict[str, str] = {}

		@classmethod
		def _load_flags(cls):
			pass

		@classmethod
		def extract_flag(cls, filename: str) -> Optional[str]:
				"""从文件名提取设备标志 (原: getBranchcode)"""
				if filename.endswith(".zip"):
						if filename.startswith("miui"):
								return filename.split("_")[1]
						else:
								return filename.split("-")[0] if "-ota_full" in filename else filename.split("_")[0]
				elif filename.endswith(".tgz"):
						sep = "-images" if "-images" in filename else "_images"
						return filename.split(sep)[0]
				return None

		@classmethod
		def get_device_code(cls, filename: str) -> Optional[str]:
				"""获取设备代码 (原: getDeviceCode)"""
				flag = cls.extract_flag(filename)
				if not flag:
						return None
				# 从miroms.data.flags查找
				return flags.get(flag)

		@classmethod
		def parse_filename(cls, filename: str) -> Optional[Dict[str, Any]]:
				"""完整解析文件名信息 (原: getData)"""
				result = {
						"filename": filename, "filetype": "", "android": "",
						"version": "", "code": "", "device": "",
						"type": "", "bigver": "", "region": "",
						"tag": "", "zone": 1, "branch": "F"
				}

				if "miui" in filename and filename.endswith(".zip"):
						result["filetype"] = "recovery"
						parts = filename.split("_")
						result["android"] = parts[4].replace(".zip", "")
						result["version"] = parts[2]

						# 查询数据库
						branch_code = parts[1]
						data = DatabaseManager.query_one(
								"SELECT code, device FROM devices WHERE branchcode = %s",
								params=(branch_code,)
						)
						if data:
								result["code"], result["device"] = data[0], data[1]
						else:
								# 处理新设备
								result = cls._handle_new_device(filename, parts, result)

				elif filename.endswith(".tgz"):
						result["filetype"] = "fastboot"
						if "-images" in filename:
								parts = filename.split("images-")[1].split("-")
								result["android"] = parts[3]
								result["version"] = parts[0]
								result["code"] = filename.split("-images")[0]
						else:
								parts = filename.split("images_")[1].split("_")
								result["android"] = parts[2]
								result["version"] = parts[0]
								result["code"] = filename.split("_images")[0]

				elif filename.endswith(".zip"):
						result["filetype"] = "recovery"
						if "PRE-" in filename:
								result["android"] = filename.split("ota_full-")[1].split("-")[3]
						else:
								result["android"] = filename.split("ota_full-")[1].split("-")[2]
						result["version"] = filename.split("ota_full-")[1].split("-user")[0]
						result["code"] = filename.split("-ota_full")[0]

				# 查询补充信息
				if result["code"]:
						data = DatabaseManager.query_one(
								"SELECT device FROM roms WHERE code = %s",
								params=(result['code'],)
						)
						if not data:
								data = DatabaseManager.query_one(
										"SELECT device FROM devices WHERE code = %s",
										params=(result['code'],)
								)
						if data:
								result["device"] = data[0]

				# 提取类型信息
				if result["version"]:
						result["type"], result["bigver"] = VersionUtils.extract_type(result["version"])

				# 确定区域信息
				if "CNXM" in result.get("version", ""):
						result["region"] = "cn"
						result["zone"] = 1
						ver_parts = result["version"].split(".")
						result["tag"] = "CnOO" if len(ver_parts) > 3 and ver_parts[3] in ["0", 0] else "CnOB"
				else:
						info = DatabaseManager.query_one(
								"SELECT region, tag, zone FROM roms WHERE code = %s",
								params=(result['code'],)
						)
						if info:
								result["region"], result["tag"], result["zone"] = info
						else:
								info = DatabaseManager.query_one(
										"SELECT region, tag FROM devices WHERE code = %s",
										params=(result['code'],)
								)
								if info:
										result["region"], result["tag"] = info
										result["zone"] = 1 if result["region"] == "cn" else 2

				return result

		@classmethod
		def _handle_new_device(cls, filename: str, parts: List[str],
													 result: Dict) -> Dict:
				"""处理新设备逻辑"""
				version = parts[2]
				if ".EP" in filename:
						devtag = parts[1].split("EPS")[0].lower()
				else:
						devtag = version.split(".")[4][1:3] if len(version.split(".")) > 4 else ""
				ver_code = version[-4:] if len(version) >= 4 else ""

				info = DatabaseManager.query_one(
						"SELECT tag, code, region FROM branches WHERE vercode = %s",
						params=(ver_code,)
				)
				if info:
						tag, code, region = info
						device_info = DatabaseManager.query_one(
								"SELECT device FROM devices WHERE devtag = %s",
								params=(devtag,)
						)
						if device_info:
								device = device_info[0]
								result["device"] = device
								result["code"] = device + (code if code else "")
								result["region"] = region
								# 插入新设备记录
								DatabaseManager.execute(
										"INSERT INTO devices(device, devtag, code, tag, region, devcode, branchcode) "
										"VALUES (%s, %s, %s, %s, %s, %s, %s)",
										params=(device, devtag, result['code'], tag, region, version[-6:], parts[1])
								)
				return result

		@classmethod
		def build_ota_form(cls, device: str, code: str, region: str,
											 branch: str, zone: Union[str, int],
											 android: str, version: str) -> str:
				"""构建OTA请求表单 (原: OTAFormer)"""
				android_ver = android.split(".")[0] if android else "14"

				form = {
						"d": code,
						"obv": version[:5],
						"b": branch,
						"options": {"zone": int(zone) if isinstance(zone, str) else zone},
						"c": android_ver,
						"sdk": VersionUtils.sdk_version(android_ver),
				}

				if region == 'cn':
						form["pn"] = code
						form["r"] = 'CN'
				else:
						form["r"] = 'GL'
						form["pn"] = code if code == f"{device}_global" else code.split('_global')[0]

				form["v"] = 'MIUI-' + version.replace('OS1', 'V816') if "OS1" in version else version

				return json.dumps(form)
