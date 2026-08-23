from typing import Dict, List


class DataValidator:
		"""
		设备数据完整性校验

		合并原函数:
		- entryChecker() -> validate_device_entry()
		"""

		@classmethod
		def validate_device_entry(cls, data: Dict, device: str) -> bool:
				"""校验设备数据条目 (原: entryChecker)"""
				errors = []
				code = data.get('code', '')
				branches = data.get('branches', [])

				if not branches:
						return True

				for branch in branches:
						if device not in branch.get('branchCode', ''):
								errors.append(f"{device} 机型与分支不配: {branch.get('branchCode', '')}")
								continue

						roms = branch.get('roms', {})
						menu_items = branch.get('table', [])
						bname = branch.get('name', {}).get('zh', 'Unknown')

						# 校验菜单项
						if roms:
								first_rom = roms.get(next(iter(roms)), [])
								if len(menu_items) != len(first_rom):
										errors.append(f"{device} {bname} 菜单项与ROM实际不符")

								if len(menu_items) != len(set(menu_items)):
										errors.append(f"{device} {bname} 菜单项重复")

						# 校验每个ROM
						for os_version, rom_info in roms.items():
								errors.extend(cls._validate_rom(
										device, bname, os_version, rom_info,
										data.get('supports', []),
										data.get('android', []),
										code, branch
								))

				if errors:
						for error in errors:
								print(error)
						return False
				return True

		@classmethod
		def _validate_rom(cls, device: str, bname: str, os_version: str,
											rom_info: Dict, supports: List, android_versions: List,
											code: str, branch: Dict) -> List[str]:
				"""校验单个ROM信息"""
				errors = []

				# 跳过分支检查
				is_dev = "Developer" in branch.get('name', {}).get('en', '')
				is_ep = branch.get('ep') == "1" or branch.get('branchtag') == 'X'

				# 校验大版本
				if os_version[:5] not in supports and not is_dev:
						errors.append(f"{device} {bname} {os_version[:5]} 大版本号没有记录")

				# 校验Android版本
				rom_android = rom_info.get('android', '')
				if rom_android not in android_versions:
						errors.append(f"{device} {bname} {rom_android} Android版本号没有记录")

				# 校验recovery包
				recovery = rom_info.get('recovery', '')
				if recovery and recovery.endswith(".zip"):
						if not any(x in recovery for x in ["EP.", "EPSTDE", ".PRE-"]):
								try:
										if "miui" in recovery:
												file_android = recovery.split("_")[4].replace(".zip", "")
										else:
												file_android = recovery.split("ota_full-")[1].split("-")[2]

										if rom_android != file_android:
												errors.append(f"{device} {bname} {os_version} Android版本号不匹配")
								except (IndexError, AttributeError):
										pass

								# 校验包名格式
								if not is_ep:
										expected = code + branch.get('tag', '')
										if not (recovery.startswith("OS1") and expected in recovery):
												if branch.get('branchCode') not in recovery:
														errors.append(f"{device} {bname} {os_version} 卡刷包信息不对")

				# 校验版本号
				if os_version != rom_info.get('os', ''):
						errors.append(f"{device} {bname} 版本号不匹配")
				elif not is_ep:
						if code + branch.get('tag', '') not in os_version:
								errors.append(f"{device} {bname} {os_version} 版本号不匹配")

				return errors
