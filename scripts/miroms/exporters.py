import json
import logging
from pathlib import Path
from typing import Set, List, Tuple, Dict, Any

from miroms.database import DatabaseManager
from miroms.constants import branches
from miroms.data import unreleased, DEVICE_NAME_ALIASES
from miroms.utils import FileUtils

# 导出目录基准路径（使用绝对路径，避免 cwd 依赖）
_EXPORT_BASE = Path(FileUtils.get_base_path()) / "data" / "api"


def normalize_bigver(bigver: Any) -> str:
		"""将数据库 bigver 原始值标准化为大版本格式（与 V2 一致）。

		例如: "HyperOS 3" -> "OS3", "MIUI 14" -> "V14", "STAN 15" -> "STAN"。
		"""
		if not bigver:
				return ""
		if str(bigver).startswith("STAN"):
				return "STAN"
		return (
				str(bigver)
				.replace("MIUI ", "V")
				.replace("HyperOS ", "OS")
				.replace("VV", "V")
		)


# ==================== 共享 btag 分支消岐 ====================
# 同一 btag 可能被多条 constants 记录共用（如印度地区 btag=INSO 下同时定义了
# INXM 标准版与 INFK FK 变体）。此时设备实际归属哪个子分支，由设备 code 约定决定：
# code 含 _fk_ 的为 FK 变体（tag=INFK），否则为标准版（tag=INXM）。
# 这里预先统计出所有被共享的 btag，仅在共享时做过滤，避免误伤单一 btag 的分支。
_shared_btags: Set[str] | None = None


def _get_shared_btags() -> Set[str]:
		"""返回在 constants 中被多条记录共用的 btag 集合（如 INSO）。"""
		global _shared_btags
		if _shared_btags is None:
				seen: Set[str] = set()
				_shared_btags = set()
				for branch in branches:
						btag = branch.get("btag")
						if not btag:
								continue
						if btag in seen:
								_shared_btags.add(btag)
						seen.add(btag)
		return _shared_btags


def _should_keep_sub_branch(branch: Dict[str, Any], branch_code: str) -> bool:
		"""判断共享 btag 下的某条子分支（如 INXM / INFK）是否应保留。

		仅在 btag 被共享时调用。约定：设备 code 含 _fk_ 表示 FK 变体（tag=INFK），
		否则为标准版（tag=INXM），据此只保留匹配的子分支，避免同一 btag 重复输出。
		"""
		device_is_fk = "_fk_" in (branch_code or "")
		branch_tag = (branch.get("tag") or "").upper()
		branch_is_fk = "FK" in branch_tag
		if device_is_fk:
				return branch_is_fk
		return not branch_is_fk


# ==================== 设备系列（series）排序 ====================
# 品牌排序权重：Xiaomi > REDMI > POCO
_BRAND_ORDER: Dict[str, int] = {"xiaomi": 0, "redmi": 1, "poco": 2}

# series 数据缓存（惰性加载，避免每台设备导出时重复查询）
_series_cache: Dict[str, Any] | None = None


def _brand_key(full_name: str) -> str:
		"""品牌全称/简称 → 品牌 key（xiaomi/redmi/poco），无法识别返回空串"""
		v = (full_name or "").lower()
		if "xiaomi" in v:
				return "xiaomi"
		if "redmi" in v:
				return "redmi"
		if "poco" in v:
				return "poco"
		return ""


def _series_row_key(row: Tuple) -> Tuple[int, int, int]:
		"""series 行排序 key：(品牌顺序, sort_order, id)"""
		brand = row[1] or ""
		return (
				_BRAND_ORDER.get(brand, 99),
				int(row[5] or 0),
				int(row[0] or 0),
		)


def load_series_data() -> Dict[str, Any]:
		"""读取 series 表并结合设备基准行 id，解析出全局设备排序顺序。

		返回:
		- order: 全局有序的设备代号列表（入系列设备按品牌→系列→系列内序号去重排序，
		  未入系列的设备按品牌顺序+代号拼接到末尾）
		- devices: {代号: {brand, zh, en}}，每台设备归属的「主系列」（品牌+名称）
		- device_series: {代号: [{brand, zh, en}, ...]}，每台设备归属的全部系列
		- series: series 表原始行（含解析后的 codenames 列表）
		"""
		global _series_cache
		if _series_cache is not None:
				return _series_cache

		# 1. 设备代号 -> 基准行 id（优先 tag='CnOO'，否则最小 id）
		device_sql = """SELECT d.device,
				COALESCE(MAX(CASE WHEN d.tag = 'CnOO' THEN d.id END), MIN(d.id)) AS ref_id
				FROM devices d GROUP BY d.device"""
		device_rows = DatabaseManager.execute(device_sql, params=(), fetch_one=False) or []
		device_to_ref: Dict[str, int] = {}
		ref_to_device: Dict[int, str] = {}
		for row in device_rows:
				if not row or len(row) < 2 or not row[0]:
						continue
				device, ref_id = row[0], row[1]
				device_to_ref[device] = ref_id
				if ref_id is not None and ref_id not in ref_to_device:
						ref_to_device[ref_id] = device

		# 2. 读取 series 表并按（品牌 -> sort_order -> id）排序
		# 若 series 表尚未建表/读取失败，DatabaseManager.execute 会返回 None，
		# 这里需兜底为空列表，避免 .sort() 抛错中断整个导出流程。
		series_rows = DatabaseManager.execute(
				"""SELECT id, brand, name_zh, name_en, device_ids, sort_order
					 FROM series ORDER BY sort_order, id""",
				params=(), fetch_one=False,
		) or []
		series_rows = [r for r in series_rows if r]
		series_rows.sort(key=_series_row_key)

		all_series_devices: List[str] = []          # 全局有序（保序 + 去重）
		seen: Set[str] = set()
		device_series: Dict[str, List[Dict[str, str]]] = {}
		parsed_series: List[Dict[str, Any]] = []

		def _add_device(dev: str, meta: Dict[str, str]) -> None:
				if not dev:
						return
				if dev not in seen:
						seen.add(dev)
						all_series_devices.append(dev)
				device_series.setdefault(dev, []).append(meta)

		for row in series_rows:
				if not row or len(row) < 5:
						continue
				sid, brand, name_zh, name_en = row[0], row[1], row[2], row[3]
				dev_ids_raw = row[4]
				brand_key = (brand or "").lower() or ""
				codenames: List[str] = []
				parsed_ids: List[int] = []
				if dev_ids_raw:
						try:
								parsed = json.loads(dev_ids_raw) if isinstance(dev_ids_raw, str) else dev_ids_raw
								if isinstance(parsed, list):
										for rid in parsed:
												try:
														i = int(rid)
												except (TypeError, ValueError):
														continue
												if i not in parsed_ids:
														parsed_ids.append(i)
												dev = ref_to_device.get(i)
												if dev and dev not in codenames:
														codenames.append(dev)
						except (json.JSONDecodeError, TypeError):
								pass
				for dev in codenames:
						_add_device(dev, {
								"brand": brand_key,
								"zh": str(name_zh or ""),
								"en": str(name_en or ""),
						})
				parsed_series.append({
						"id": int(sid or 0),
						"brand": brand_key,
						"name_zh": str(name_zh or ""),
						"name_en": str(name_en or ""),
						"sort_order": int(row[5] or 0),
						"device_ids": parsed_ids,
						"codenames": codenames,
				})

		# 3. 未入系列的设备按「品牌顺序 + 代号」拼接到末尾
		tail_devices = sorted(
				[d for d in device_to_ref if d not in seen],
				key=lambda d: (_BRAND_ORDER.get(_brand_key(d), 99), d),
		)
		order = all_series_devices + tail_devices

		# 4. 每台设备的主系列（取品牌排序最靠前的那个）
		devices: Dict[str, Dict[str, str]] = {}
		for dev in all_series_devices:
				entries = device_series.get(dev, [])
				if entries:
						entries_sorted = sorted(entries, key=lambda e: _BRAND_ORDER.get(e["brand"], 99))
						devices[dev] = entries_sorted[0]

		_series_cache = {
				"order": order,
				"devices": devices,
				"device_series": device_series,
				"series": parsed_series,
		}
		return _series_cache


def export_series_index() -> Dict[str, Any]:
		"""将 series 排序结果写入 data/api/v3/series.json，供前端与 generate-index 消费。"""
		data = load_series_data()
		index_struct: Dict[str, Any] = {
				"order": data["order"],
				"devices": data["devices"],
				"series": data["series"],
		}
		out_dir = _EXPORT_BASE / 'v3'
		out_dir.mkdir(parents=True, exist_ok=True)
		file_path = out_dir / 'series.json'
		temp_path = file_path.with_suffix('.tmp')
		try:
				with open(temp_path, 'w', encoding='utf-8') as f:
						json.dump(index_struct, f, ensure_ascii=False, indent=2)
				temp_path.replace(file_path)
		except (IOError, OSError) as e:
				logger.error(f"series 索引写入失败 {file_path}: {e}")
				if temp_path.exists():
						temp_path.unlink(missing_ok=True)
				raise IOError(f"无法写入 series 索引 {file_path}: {e}")
		return index_struct


def export_statistics() -> Dict[str, Any]:
		"""将数据库真实统计写入 data/api/v3/statistics.json，供官网首页展示。
		
		口径与后台一致：
		- deviceCount: devices 表 device 列去重后的数量
		- branchCount: devices 表的实际行数
		- romCount: roms 表的实际行数
		- todayNewRoms: roms 表今日新增（insdate >= CURDATE()）
		"""
		logger = logging.getLogger(__name__)
		
		def _count(sql: str) -> int:
				row = DatabaseManager.query_one(sql)
				return int(row[0]) if row else 0
		
		stats: Dict[str, Any] = {
				"deviceCount": _count("SELECT COUNT(DISTINCT device) FROM devices"),
				"branchCount": _count("SELECT COUNT(*) FROM devices"),
				"romCount": _count("SELECT COUNT(*) FROM roms"),
				"todayNewRoms": _count("SELECT COUNT(*) FROM roms WHERE insdate >= CURDATE()"),
		}
		out_dir = _EXPORT_BASE / 'v3'
		out_dir.mkdir(parents=True, exist_ok=True)
		file_path = out_dir / 'statistics.json'
		temp_path = file_path.with_suffix('.tmp')
		try:
				with open(temp_path, 'w', encoding='utf-8') as f:
						json.dump(stats, f, ensure_ascii=False, indent=2)
				temp_path.replace(file_path)
		except (IOError, OSError) as e:
				logger.error(f"statistics 写入失败 {file_path}: {e}")
				if temp_path.exists():
						temp_path.unlink(missing_ok=True)
				raise IOError(f"无法写入 statistics {file_path}: {e}")
		return stats


def exportV1(device: str) -> Dict[str, Any]:
		if device in unreleased:
				return None
		else:
				type_sql = "SELECT type FROM roms WHERE device = %s"
				types = DatabaseManager.execute(type_sql, params=(device,), fetch_one=False)
				if "MIUI" not in str(types):
						return None
				else:
						logger = logging.getLogger(__name__)

						# 输入验证
						if not device or not isinstance(device, str):
										raise ValueError("设备代号必须是有效的非空字符串")

						# 清理输入，防止路径遍历
						device = device.strip().replace("/", "").replace("\\", "")
						device = DEVICE_NAME_ALIASES.get(device, device)

						try:
										# ==================== 阶段1: 批量获取设备基础信息 ====================
										logger.info(f"开始导出设备数据: {device}")

										# 使用参数化查询（%s占位符）防止SQL注入
										device_sql = "SELECT code, full_names, devtag FROM devices WHERE device = %s"
										device_data = DatabaseManager.execute(device_sql, params=(device,), fetch_one=True)

										if not device_data:
														raise ValueError(f"设备 '{device}' 在数据库中不存在")

										# 安全解析设备名称JSON
										device_code = device_data[0] if len(device_data) > 1 else device
										name_json_str = device_data[1] if len(device_data) > 2 else '{}'
										dev_code = device_data[2] if len(device_data) > 2 else '""'

										try:
														device_names = json.loads(name_json_str) if isinstance(name_json_str, str) else {}
														if not isinstance(device_names, dict):
																		device_names = {}
										except json.JSONDecodeError as e:
														logger.warning(f"设备 {device} 的名称JSON解析失败: {e}, 使用默认值")
														device_names = {}

										# ==================== 阶段2: 批量获取版本信息（单次查询） ====================
										ver_sql = """
														SELECT DISTINCT android, bigver
														FROM roms
														WHERE device = %s AND type = 'MIUI'
														ORDER BY
																		CAST(SUBSTRING_INDEX(android, '.', 1) AS UNSIGNED) DESC,
																		CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(android, '.', 2), '.', -1) AS UNSIGNED) DESC
										"""
										ver_data = DatabaseManager.execute(ver_sql, params=(device,), fetch_one=False)

										android_versions: List[str] = []
										miui_versions: List[str] = []

										for row in ver_data or []:
														android_ver = row[0] if row else None
														bigver = row[1] if len(row) > 1 else None

														if android_ver and android_ver not in android_versions:
																		android_versions.append(android_ver)

														if bigver:
																		miui_ver = bigver.replace("MIUI ", "V").replace("VV", "V")
																		if "." not in miui_ver:
																						miui_ver = f"{miui_ver}.0"
																		if miui_ver not in miui_versions:
																						miui_versions.append(miui_ver)

										android_versions.reverse()
										miui_versions.reverse()

										# ==================== 阶段3: 批量获取分支代码映射（单次查询） ====================
										branch_codes_sql = """
														SELECT tag, code, region
														FROM devices
														WHERE device = %s AND tag IS NOT NULL AND tag != ''
										"""
										branch_codes_data = DatabaseManager.execute(branch_codes_sql, params=(device,), fetch_one=False)

										branch_code_map: Dict[str, Dict[str, str]] = {}
										for row in branch_codes_data or []:
														if row and len(row) >= 3:
																		tag, code, region = row[0], row[1], row[2]
																		if tag:
																						branch_code_map[tag] = {"code": code or "", "region": region or ""}

										# ==================== 阶段4: 批量获取所有ROM数据（带运营商字段） ====================
										roms_sql = """SELECT id, version, android, beta_date, recovery, fastboot, tag, code, ctelecom, cmobile, cunicom, aspatch FROM roms WHERE device = %s AND type = 'MIUI' ORDER BY id DESC"""
										all_roms = DatabaseManager.execute(roms_sql, params=(device,), fetch_one=False)

										roms_by_tag: Dict[str, List[Tuple]] = {}
										for rom in all_roms or []:
														if len(rom) > 6:
																		tag = rom[6]
																		if tag:
																						roms_by_tag.setdefault(tag, []).append(rom)

										# ==================== 阶段5: 构建输出结构 ====================
										device_struct: Dict[str, Any] = {
														"codename": device,
														"zh-cn": device_names.get("zh") or device_names.get("zh-cn") or device,
														"en-us": device_names.get("en") or device_names.get("en-us") or device,
														"ismiui": "",
														"code": dev_code,
														"android": android_versions,
														"miui": miui_versions,
														"branches": []
										}

										# ==================== 阶段6: 处理每个分支 ====================
										processed_branches = 0
										total_roms = 0

										for branch in branches:
														btag = branch.get("btag")
														if not btag:
																		continue

														branch_info = branch_code_map.get(btag)
														if not branch_info or not branch_info.get("code"):
																		continue

														branch_code = branch_info["code"]

														# 共享 btag（如 INSO）下存在多条子分支（INXM / INFK），
														# 按设备 code 约定只保留匹配的那一条，避免重复输出。
														if btag in _get_shared_btags() and not _should_keep_sub_branch(branch, branch_code):
																		continue

														branch_roms = roms_by_tag.get(btag, [])
														if not branch_roms:
																		continue

														new_branch: Dict[str, Any] = {
																		"code": branch_code,
																		"btag": branch.get("branch", "F"),
																		"region": branch_info.get("region") or branch.get("region", ""),
																		"carrier": branch.get("carrier", []),
																		"branch": btag,
																		"tag": branch.get("tag", ""),
																		"zone": branch.get("zone", 1),
																		"show": branch.get("visibility", 1),
																		"ep": branch.get("ep", 0),
																		"zh-cn": branch.get("name_zh", ""),
																		"en-us": branch.get("name_en", ""),
																		"links": []
														}

														# 检查是否需要添加运营商字段到 links
														has_ctelecom = any(len(rom) > 8 and rom[8] for rom in branch_roms)
														has_cmobile = any(len(rom) > 9 and rom[9] for rom in branch_roms)
														has_cunicom = any(len(rom) > 10 and rom[10] for rom in branch_roms)

														# 修复原逻辑错误：使用Set追踪已添加的版本
														added_versions: Set[str] = set()

														for rom in branch_roms:
																		if len(rom) < 6:
																						continue

																		(rom_id, version, android, beta_date, recovery, fastboot,
														 tag, code, ctelecom, cmobile, cunicom, aspatch) = rom[:12] if len(rom) >= 12 else (*rom[:8], None, None, None, None)

																		version_str = str(version) if version is not None else ""
																		if not version_str or version_str in added_versions:
																						continue

																		# EP（企业版）ROM 不应出现在非 EP 分支
																		is_ep_rom = ".EP." in version_str or "_ep_" in (str(recovery) + str(fastboot))
																		is_ep_branch = branch.get("ep", 0) == 1
																		if is_ep_rom and not is_ep_branch:
																						continue

																		added_versions.add(version_str)

																		rom_meta: Dict[str, Any] = {
																						"miui": version_str,
																						"android": str(android) if android is not None else "",
																						"release": str(beta_date) if beta_date is not None else "",
																						"aspatch": str(aspatch) if aspatch is not None else "",
																						"recovery": str(recovery) if recovery is not None else "",
																						"fastboot": str(fastboot) if fastboot is not None else ""
																		}

																		# 添加运营商定制包（如果有）
																		if has_ctelecom and ctelecom:
																						rom_meta["ctelecom"] = str(ctelecom)
																		if has_cmobile and cmobile:
																						rom_meta["cmobile"] = str(cmobile)
																		if has_cunicom and cunicom:
																						rom_meta["cunicom"] = str(cunicom)

																		new_branch["links"].append(rom_meta)
																		total_roms += 1

														if new_branch["links"]:
																		device_struct["branches"].append(new_branch)
																		processed_branches += 1

										# ==================== 阶段7: 安全写入文件 ====================
										if processed_branches == 0:
												logger.info(f"设备 {device} 无 MIUI 分支数据，跳过生成 JSON")
												return None

										device_dir = _EXPORT_BASE / 'v1' / 'devices'
										device_dir.mkdir(parents=True, exist_ok=True)

										file_path = device_dir / f'{device}.json'
										temp_path = file_path.with_suffix('.tmp')

										try:
														with open(temp_path, 'w', encoding='utf-8') as f:
																		json.dump(device_struct, f, ensure_ascii=False, indent=2)

														temp_path.replace(file_path)		# 原子重命名

										except (IOError, OSError) as e:
														logger.error(f"文件写入失败 {file_path}: {e}")
														if temp_path.exists():
																		temp_path.unlink(missing_ok=True)
														raise IOError(f"无法写入设备文件 {file_path}: {e}")

										logger.info(f"成功导出设备 {device}: {processed_branches} 分支, {total_roms} ROMs")
										return device_struct

						except ValueError:
										raise
						except Exception as e:
										logger.error(f"导出设备 {device} 失败: {e}", exc_info=True)
										raise RuntimeError(f"导出设备 {device} 失败: {str(e)}") from e


def exportV2(device: str) -> Dict[str, Any]:
		if device in unreleased:
				return None
		# 检查是否为 HyperOS/STAN 设备（STAN = 现代原生安卓/AOSP）
		type_sql = "SELECT DISTINCT type FROM roms WHERE device = %s"
		type_rows = DatabaseManager.execute(type_sql, params=(device,), fetch_one=False)
		device_types = [row[0] for row in (type_rows or []) if row]
		if not any(t in ('HyperOS', 'STAN') for t in device_types):
			return None
		else:
			logger = logging.getLogger(__name__)

			# 输入验证
			if not device or not isinstance(device, str):
					raise ValueError("设备代号必须是有效的非空字符串")

			# 清理输入，防止路径遍历
			device = device.strip().replace("/", "").replace("\\", "")
			device = DEVICE_NAME_ALIASES.get(device, device)

			try:
					# ==================== 阶段1: 获取设备基础信息 ====================
					logger.info(f"开始导出设备数据(V2): {device}")

					device_sql = """SELECT code, full_names, devtag, brands, full_brands FROM devices WHERE device = %s"""
					device_data = DatabaseManager.execute(device_sql, params=(device,), fetch_one=True)
					if not device_data:
							raise ValueError(f"设备 '{device}' 在数据库中不存在")

					device_code = device_data[0] if len(device_data) > 0 else ""
					name_json_str = device_data[1] if len(device_data) > 1 else '{}'
					dev_tag = device_data[2] if len(device_data) > 2 else '""'
					# brands: "\"REDMI, POCO\"" -> ["REDMI", "POCO"]
					raw_brand = device_data[3] if len(device_data) > 3 else ""
					device_brand = [b.strip().strip('"') for b in raw_brand.strip().strip('"').split(',')] if raw_brand else []
					# full_brands: "[\"REDMI\", \"POCO\"]" -> ["REDMI", "POCO"]
					raw_full_brand = device_data[4] if len(device_data) > 4 else ""
					try:
						device_full_brand = json.loads(raw_full_brand) if raw_full_brand else []
					except (json.JSONDecodeError, TypeError):
						device_full_brand = [b.strip().strip('"') for b in raw_full_brand.strip().strip('"').split(',')] if raw_full_brand else []

					# 解析设备名称
					try:
							device_names = json.loads(name_json_str) if isinstance(name_json_str, str) else {}
							if not isinstance(device_names, dict):
									device_names = {}
					except json.JSONDecodeError:
							device_names = {}

					# ==================== 阶段2: 获取支持的版本信息 ====================
					# 获取 Android 版本列表
					android_sql = """
							SELECT DISTINCT android
							FROM roms
							WHERE device = %s
							ORDER BY CAST(SUBSTRING_INDEX(android, '.', 1) AS UNSIGNED) DESC,
											CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(android, '.', 2), '.', -1) AS UNSIGNED) DESC
					"""
					android_rows = DatabaseManager.execute(android_sql, params=(device,), fetch_one=False)
					android_versions = [row[0] for row in android_rows if row] if android_rows else []

					# 获取 HyperOS/MIUI 大版本支持列表（如 OS1.0, OS2.0, V14.0）
					supports_sql = """
							SELECT DISTINCT bigver
							FROM roms
							WHERE device = %s AND bigver IS NOT NULL
							ORDER BY bigver DESC
					"""
					supports_rows = DatabaseManager.execute(supports_sql, params=(device,), fetch_one=False)
					supports_versions = []
					for row in supports_rows or []:
							if row and row[0]:
									# 标准化为大版本格式
									bigver = normalize_bigver(row[0])
									if bigver and bigver not in supports_versions:
											supports_versions.append(bigver)

					# ==================== 阶段3: 获取分支代码映射 ====================
					branch_codes_sql = """
							SELECT tag, code, region, devtag
							FROM devices
							WHERE device = %s AND tag IS NOT NULL AND tag != ''
					"""
					branch_codes_data = DatabaseManager.execute(branch_codes_sql, params=(device,), fetch_one=False)

					branch_code_map: Dict[str, Dict[str, str]] = {}
					for row in branch_codes_data or []:
							if row and len(row) >= 3:
									tag, code, region = row[0], row[1], row[2]
									devtag = row[3] if len(row) > 3 else ""
									if tag:
											branch_code_map[tag] = {
													"code": code or "",
													"region": region or "",
													"devtag": devtag
											}

					# ==================== 阶段4: 批量获取所有ROM数据 ====================
					roms_sql = """
							SELECT id, version, android, beta_date, recovery, fastboot,
										tag, code, ctelecom, cmobile, cunicom, aspatch
							FROM roms
							WHERE device = %s
							ORDER BY id DESC
					"""
					all_roms = DatabaseManager.execute(roms_sql, params=(device,), fetch_one=False)

					# 按 tag 分组 ROM
					roms_by_tag: Dict[str, List[Tuple]] = {}
					for rom in all_roms or []:
							if len(rom) > 6:
									tag = rom[6]
									if tag:
											roms_by_tag.setdefault(tag, []).append(rom)

					# ==================== 阶段5: 构建 V2 输出结构 ====================
					device_struct: Dict[str, Any] = {
							"device": device,
							"name": {
									"zh": device_names.get("zh") or device_names.get("zh-cn") or device,
									"en": device_names.get("en") or device_names.get("en-us") or device
							},
							"code": dev_tag,
							"brand": device_full_brand or "",
							"miui": "yes" if 'HyperOS' in device_types else "no",
							"merged": "no",	# V2 新增字段，默认no
							"android": android_versions,
							"supports": supports_versions,	# V2 使用 supports 而非 miui
							"branches": []
					}

					# ==================== 阶段6: 处理每个分支 ====================
					for branch in branches:
							btag = branch.get("btag")
							if not btag:
									continue

							branch_info = branch_code_map.get(btag)
							if not branch_info or not branch_info.get("code"):
									continue

							branch_code = branch_info["code"]

							# 共享 btag（如 INSO）下存在多条子分支（INXM / INFK），
							# 按设备 code 约定只保留匹配的那一条，避免重复输出。
							if btag in _get_shared_btags() and not _should_keep_sub_branch(branch, branch_code):
									continue

							branch_roms = roms_by_tag.get(btag, [])
							if not branch_roms:
									continue

							# 构建 V2 风格的分支结构
							new_branch: Dict[str, Any] = {
									"branchCode": branch_code,	# V2: branchCode 而非 code
									"brand": device_brand or "",
									"device": {
											"zh": device_names.get("zh") or device_names.get("zh-cn") or device,
											"en": device_names.get("en") or device_names.get("en-us") or device
									},
									"idtag": btag,	# V2: idtag 对应 btag
									"tag": branch.get("tag", ""),
									"branchtag": branch.get("branch", "F"),	# V2: branchtag 对应 branch
									"name": {
											"zh": branch.get("name_zh", ""),
											"en": branch.get("name_en", "")
									},
									"table": ["os", "android", "release", "recovery", "fastboot"],	# V2 基础表头
									"show": str(branch.get("visibility", 1)),
									"carrier": branch.get("carrier", []),
									"region": branch_info.get("region") or branch.get("region", ""),
									"zone": str(branch.get("zone", 1)),
									"ep": str(branch.get("ep", 0)),
									"roms": {}	# V2: roms 字典而非 links 数组
							}

							# 检查是否需要添加运营商字段到 table
							has_ctelecom = any(len(rom) > 8 and rom[8] for rom in branch_roms)
							if has_ctelecom:
									new_branch["table"].append("ctelecom")

							# 处理每个 ROM，构建 V2 格式的 roms 字典
							for rom in branch_roms:
									if len(rom) < 7:
											continue

									(rom_id, version, android, beta_date, recovery,
								fastboot, tag, code, ctelecom, cmobile, cunicom, aspatch) = rom[:12]

									version_str = str(version) if version is not None else ""
									if not version_str:
											continue

									# EP（企业版）ROM 不应出现在非 EP 分支
									is_ep_rom = ".EP." in version_str or "_ep_" in (str(recovery) + str(fastboot))
									is_ep_branch = branch.get("ep", 0) == 1
									if is_ep_rom and not is_ep_branch:
											continue

									# V2: 版本号作为 key，值为详细信息对象
									rom_entry: Dict[str, Any] = {
											"os": version_str,	# V2: os 而非 miui
											"android": str(android) if android is not None else "",
											"release": str(beta_date) if beta_date is not None else "",
											"aspatch": str(aspatch) if aspatch is not None else "",
											"recovery": str(recovery) if recovery is not None else "",
											"fastboot": str(fastboot) if fastboot is not None else ""
									}

									# 添加运营商定制包（如果有）
									if ctelecom:
											rom_entry["ctelecom"] = str(ctelecom)
									# 可扩展其他运营商字段 cmobile, cunicom 等

									# 使用版本号作为 key 存入 roms 字典
									new_branch["roms"][version_str] = rom_entry

							if new_branch["roms"]:
									device_struct["branches"].append(new_branch)

					# ==================== 阶段7: 安全写入文件 ====================
					device_dir = _EXPORT_BASE / 'v2' / 'devices'
					device_dir.mkdir(parents=True, exist_ok=True)

					file_path = device_dir / f'{device}.json'
					temp_path = file_path.with_suffix('.tmp')

					try:
							with open(temp_path, 'w', encoding='utf-8') as f:
									json.dump(device_struct, f, ensure_ascii=False, indent=2)

							temp_path.replace(file_path)	# 原子重命名

					except (IOError, OSError) as e:
							logger.error(f"文件写入失败 {file_path}: {e}")
							if temp_path.exists():
									temp_path.unlink(missing_ok=True)
							raise IOError(f"无法写入设备文件 {file_path}: {e}")

					logger.info(f"成功导出设备 {device} (V2): {len(device_struct['branches'])} 分支")
					return device_struct

			except ValueError:
					raise
			except Exception as e:
					logger.error(f"导出设备 {device} 失败(V2): {e}", exc_info=True)
					raise RuntimeError(f"导出设备 {device} 失败(V2): {str(e)}") from e


def exportV3(device: str) -> Dict[str, Any]:
		if device in unreleased:
				return None

		logger = logging.getLogger(__name__)

		# 输入验证
		if not device or not isinstance(device, str):
				raise ValueError("设备代号必须是有效的非空字符串")

		# 清理输入，防止路径遍历
		device = device.strip().replace("/", "").replace("\\", "")
		device = DEVICE_NAME_ALIASES.get(device, device)

		try:
				# ==================== 阶段1: 批量获取设备基础信息 ====================
				logger.info(f"开始导出设备数据(V3): {device}")

				device_sql = """SELECT code, full_names, devtag, brands, full_brands FROM devices WHERE device = %s"""
				device_data = DatabaseManager.execute(device_sql, params=(device,), fetch_one=True)

				if not device_data:
						raise ValueError(f"设备 '{device}' 在数据库中不存在")

				device_code = device_data[0] if len(device_data) > 0 else ""
				name_json_str = device_data[1] if len(device_data) > 1 else '{}'
				dev_tag = device_data[2] if len(device_data) > 2 else '""'
				# brands: "\"REDMI, POCO\"" -> ["REDMI", "POCO"]
				raw_brand = device_data[3] if len(device_data) > 3 else ""
				device_brand = [b.strip().strip('"') for b in raw_brand.strip().strip('"').split(',')] if raw_brand else []
				# full_brands: "[\"REDMI\", \"POCO\"]" -> ["REDMI", "POCO"]
				raw_full_brand = device_data[4] if len(device_data) > 4 else ""
				try:
					device_full_brand = json.loads(raw_full_brand) if raw_full_brand else []
				except (json.JSONDecodeError, TypeError):
					device_full_brand = [b.strip().strip('"') for b in raw_full_brand.strip().strip('"').split(',')] if raw_full_brand else []

				# 安全解析设备名称JSON（只解析一次，后续复用）
				try:
						device_names = json.loads(name_json_str) if isinstance(name_json_str, str) else {}
						if not isinstance(device_names, dict):
								device_names = {}
				except json.JSONDecodeError:
						device_names = {}

				# 预计算设备名称（避免重复计算）
				device_name_zh = device_names.get("zh") or device_names.get("zh-cn") or device
				device_name_en = device_names.get("en") or device_names.get("en-us") or device

				# ==================== 阶段2: 检查是否为 MIUI/HyperOS 设备 ====================
				type_sql = "SELECT DISTINCT type FROM roms WHERE device = %s"
				types_result = DatabaseManager.execute(type_sql, params=(device,), fetch_one=False)
				device_types = [row[0] for row in types_result if row] if types_result else []

				has_miui = any(t in ('MIUI', 'HyperOS', 'STAN') for t in device_types)
				if not has_miui:
						return None

				# ==================== 阶段3: 批量获取所有分支代码映射 ====================
				branch_codes_sql = """
						SELECT tag, code, region, devtag
						FROM devices
						WHERE device = %s AND tag IS NOT NULL AND tag != ''
				"""
				branch_codes_data = DatabaseManager.execute(branch_codes_sql, params=(device,), fetch_one=False)

				branch_code_map: Dict[str, Dict[str, str]] = {}
				for row in branch_codes_data or []:
						if row and len(row) >= 3:
								tag, code, region = row[0], row[1], row[2]
								devtag_val = row[3] if len(row) > 3 else ""
								if tag:
										branch_code_map[tag] = {
												"code": code or "",
												"region": region or "",
												"devtag": devtag_val
										}

				# ==================== 阶段4: 批量获取所有 ROM 数据（带运营商字段）====================
				roms_sql = """
						SELECT id, version, android, beta_date, recovery, fastboot,
									 tag, code, type, bigver, ctelecom, cmobile, cunicom, aspatch,
									 logs_zh, logs_en, region
						FROM roms
						WHERE device = %s
						ORDER BY id DESC
				"""
				all_roms = DatabaseManager.execute(roms_sql, params=(device,), fetch_one=False)

				# 按 tag 分组 ROM（使用字典setdefault，效率更高）
				roms_by_tag: Dict[str, List[Tuple]] = {}
				for rom in all_roms or []:
						if len(rom) > 6:
								tag = rom[6]
								if tag:
										if tag not in roms_by_tag:
												roms_by_tag[tag] = []
										roms_by_tag[tag].append(rom)

				# ==================== 阶段4.5: 从 ROM 数据中收集版本统计 ====================
				# 收集 android 版本列表（归一化到 major.minor）
				android_set: Set[str] = set()
				for rom in all_roms or []:
						if len(rom) > 2 and rom[2]:
								parts = str(rom[2]).split('.')
								android_set.add('.'.join(parts[:2]))
				android_versions = sorted(
						android_set,
						key=lambda x: tuple(
								int(p) if p.isdigit() else 0
								for p in x.split('.')[:2]
						),
						reverse=True
				)

				# 收集 UI/OS 大版本支持列表（从 index 9=bigver 字段）
				bigver_set: Set[str] = set()
				for rom in all_roms or []:
						if len(rom) > 9 and rom[9]:
								bigver_set.add(str(rom[9]))
				os_versions = []
				ui_versions = []
				for bigver in bigver_set:
						# 标准化为大版本格式（与 V2 一致）
						normalized = normalize_bigver(bigver)
						if normalized.startswith("OS"):
								if normalized not in os_versions:
										os_versions.append(normalized)
						else:
								if normalized not in ui_versions:
										ui_versions.append(normalized)
				os_versions.sort(reverse=True)
				ui_versions.sort(reverse=True)
				supports_versions = os_versions + ui_versions

				# ==================== 阶段5: 构建 V3 输出结构 ====================
				device_struct: Dict[str, Any] = {
						"device": device,
						"name": {
								"zh": device_name_zh,
								"en": device_name_en
						},
						"code": dev_tag,
						"brand": device_full_brand or "",
						"series": [dict(s) for s in (load_series_data().get("device_series", {}).get(device, []))],
						"android": android_versions,
						"supports": supports_versions,
						"branches": []
				}

				# ==================== 阶段6: 处理每个分支（添加 device 字段）====================
				rom_logs: Dict[str, Dict[str, str]] = {}  # key: "{region}/{version}" -> {logs_zh, logs_en}
				for branch in branches:
						btag = branch.get("btag")
						if not btag:
								continue

						branch_info = branch_code_map.get(btag)
						if not branch_info or not branch_info.get("code"):
								continue

						branch_code = branch_info["code"]

						# 共享 btag（如 INSO）下存在多条子分支（INXM / INFK），
						# 按设备 code 约定只保留匹配的那一条，避免重复输出。
						if btag in _get_shared_btags() and not _should_keep_sub_branch(branch, branch_code):
								continue

						branch_roms = roms_by_tag.get(btag, [])
						if not branch_roms:
								continue

						# 使用 devices 表中的 code 字段作为分支 ID
						branch_id = branch_code

						# V3 风格的分支结构（添加 device 字段）
						new_branch: Dict[str, Any] = {
								"id": branch_id,
								"brand": device_brand,
								"device": {
										"zh": device_name_zh,
										"en": device_name_en
								},
								"name": {
										"zh": branch.get("name_zh", ""),
										"en": branch.get("name_en", "")
								},
								"region": branch_info.get("region") or branch.get("region", ""),
								"carrier": branch.get("carrier", []),
								"tags": {
										"branch": btag,
										"tag": branch.get("tag", ""),
										"branchtag": branch.get("branch", "F"),
										"btag": branch.get("branch", "F")
								},
								"zone": str(branch.get("zone", 1)),
								"show": str(branch.get("visibility", 1)),
								"ep": str(branch.get("ep", 0)),
								"roms": []
						}

						# 检查该分支是否有运营商定制包（使用any提前计算，避免重复检查）
						has_ctelecom = has_cmobile = has_cunicom = False
						for rom in branch_roms:
								if len(rom) > 10 and rom[10]:
										has_ctelecom = True
								if len(rom) > 11 and rom[11]:
										has_cmobile = True
								if len(rom) > 12 and rom[12]:
										has_cunicom = True
								if has_ctelecom and has_cmobile and has_cunicom:
										break

						# 处理每个 ROM，构建 roms 数组（使用 Set 去重）
						added_versions: Set[str] = set()

						for rom in branch_roms:
								if len(rom) < 7:
										continue

								# 安全解包（处理不同长度的rom数据）
								rom_id = rom[0]
								version = rom[1]
								android = rom[2]
								beta_date = rom[3]
								recovery = rom[4]
								fastboot = rom[5]
								tag = rom[6] if len(rom) > 6 else None
								code = rom[7] if len(rom) > 7 else None
								rom_type = rom[8] if len(rom) > 8 else None
								bigver = rom[9] if len(rom) > 9 else None
								ctelecom = rom[10] if len(rom) > 10 else None
								cmobile = rom[11] if len(rom) > 11 else None
								cunicom = rom[12] if len(rom) > 12 else None
								aspatch = rom[13] if len(rom) > 13 else None
								logs_zh = rom[14] if len(rom) > 14 else None
								logs_en = rom[15] if len(rom) > 15 else None
								rom_region = rom[16] if len(rom) > 16 else None

								version_str = str(version) if version is not None else ""
								if not version_str or version_str in added_versions:
										continue

								# EP（企业版）ROM 不应出现在非 EP 分支
								is_ep_rom = ".EP." in version_str or "_ep_" in (str(recovery) + str(fastboot))
								is_ep_branch = branch.get("ep", 0) == 1
								if is_ep_rom and not is_ep_branch:
										continue

								added_versions.add(version_str)

								# 构建 roms 条目（与 V1 links 结构一致）
								roms_entry: Dict[str, Any] = {
										"miui": version_str,
										"os": normalize_bigver(bigver),
										"bigver": str(bigver) if bigver is not None else "",
										"android": str(android) if android is not None else "",
										"release": str(beta_date) if beta_date is not None else "",
										"aspatch": str(aspatch) if aspatch is not None else "",
										"recovery": str(recovery) if recovery is not None else "",
										"fastboot": str(fastboot) if fastboot is not None else ""
								}

								# 条件添加运营商定制包（只在存在时添加，减少输出体积）
								if has_ctelecom and ctelecom:
										roms_entry["ctelecom"] = str(ctelecom)
								if has_cmobile and cmobile:
										roms_entry["cmobile"] = str(cmobile)
								if has_cunicom and cunicom:
										roms_entry["cunicom"] = str(cunicom)

								new_branch["roms"].append(roms_entry)

								# 收集日志数据（按 ROM 自身 region/version 去重）
								if (logs_zh or logs_en) and version_str:
										log_key = f"{rom_region}/{version_str}" if rom_region else version_str
										if log_key not in rom_logs:
												try:
														parsed_zh = json.loads(logs_zh) if isinstance(logs_zh, str) else logs_zh
												except (json.JSONDecodeError, TypeError):
														parsed_zh = logs_zh
												try:
														parsed_en = json.loads(logs_en) if isinstance(logs_en, str) else logs_en
												except (json.JSONDecodeError, TypeError):
														parsed_en = logs_en
												rom_logs[log_key] = {
														"logs_zh": parsed_zh,
														"logs_en": parsed_en
												}

						if new_branch["roms"]:
								device_struct["branches"].append(new_branch)

				# ==================== 阶段7: 安全写入文件 ====================
				device_dir = _EXPORT_BASE / 'v3' / 'devices'
				device_dir.mkdir(parents=True, exist_ok=True)

				file_path = device_dir / f'{device}.json'
				temp_path = file_path.with_suffix('.tmp')

				try:
						with open(temp_path, 'w', encoding='utf-8') as f:
								json.dump(device_struct, f, ensure_ascii=False, indent=2)

						temp_path.replace(file_path)

				except (IOError, OSError) as e:
						logger.error(f"文件写入失败 {file_path}: {e}")
						if temp_path.exists():
								temp_path.unlink(missing_ok=True)
						raise IOError(f"无法写入设备文件 {file_path}: {e}")

				# ==================== 阶段8: 导出日志到独立文件 ====================
				if rom_logs:
						logs_base = _EXPORT_BASE / 'v3' / 'logs' / device
						logs_saved = 0
						for log_key, log_data in rom_logs.items():
								if '/' in log_key:
										# 有 region: logs/device/region/version.json
										log_region, log_version = log_key.split('/', 1)
										log_dir = logs_base / log_region
								else:
										# 无 region: logs/device/version.json
										log_version = log_key
										log_dir = logs_base
								log_dir.mkdir(parents=True, exist_ok=True)
								log_file = log_dir / f'{log_version}.json'
								try:
										with open(log_file, 'w', encoding='utf-8') as f:
												json.dump(log_data, f, ensure_ascii=False, indent=2)
										logs_saved += 1
								except (IOError, OSError) as e:
										logger.warning(f"日志文件写入失败 {log_file}: {e}")
						logger.info(f"  日志导出: {logs_saved}/{len(rom_logs)} 条")

				logger.info(f"成功导出设备 {device} (V3): {len(device_struct['branches'])} 分支")
				return device_struct

		except ValueError:
				raise
		except Exception as e:
				logger.error(f"导出设备 {device} 失败(V3): {e}", exc_info=True)
				raise RuntimeError(f"导出设备 {device} 失败(V3): {str(e)}") from e
