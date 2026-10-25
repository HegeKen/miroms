"""
miroms/xms.py - XMS（SOTA 系统应用更新）解析与入库

小米 OTA 接口（miotaV3.php）在 LatestRom / CurrentRom 之外还会返回 xmsUpdateInfo，
即系统应用级的增量更新（SOTA，接口内部叫 XMS）：

    hasXmsUpdate  1 = 当前系统版本上还有一批系统应用可以更新
    lstVer        最新 XMS 版本号（如 C11）
    curVer        请求带 xv 时回显的当前 XMS 版本号
    pkgCnt        本次覆盖的包数量
    prio          推送优先级
    pkgs          包名列表
    gentleNotice  注意事项（HTML 片段）
    changeLog     更新日志：仅当请求带 xv=<lstVer> 时返回，按「模块名」分组，
                  条目里可能带 package（包名）/ versionCode（应用版本号）/ txt

解析方式参照 YuKongA/Updater-KMP：
    data/RomInfoHelper.kt 的 XmsUpdateInfo
    data/repository/RomInfoRepositoryImpl.kt 的 getRecoveryRomInfo（xv 参数）/ getXmsVerInfo
    domain/.../FetchRomInfoUseCase.kt 的 fetchXmsBlock（二次请求拿 changeLog）

落库：xms（一次推送）+ xms_app（推送里的应用），表结构见 db_structure/xms.sql、
db_structure/xms_app.sql。

is_latest 规则（与需求一致）：查询时当前系统版本 == 接口返回的 LatestRom 时，
该次 XMS 推送标记为最新；接口没返回 LatestRom（探测出来的未发布版本等）时
一律标 0，不做「库内最新版本」兜底，避免 ota_full 多版本探测时标志来回翻转。
同一分支同时只有一行为 1。

只抓 OS3 及以上系统版本的 XMS：接口约定 XMS 版本号首字母对应大版本
（C → HyperOS 3、D → HyperOS 4……），OS1/OS2 与 MIUI 版本直接跳过。
"""
import json
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from miroms.constants import _const
from miroms.database import DatabaseManager
from miroms.network import NetworkClient
from miroms.utils import beijing_now


class XmsStore:
		"""XMS 推送的解析、去重与落库"""

		# XMS（SOTA）只存在于 HyperOS 3 及以上：C 开头适配 OS3、D 开头适配 OS4……
		# 更老的 OS1/OS2 与 MIUI 不再抓取（接口即便回 hasXmsUpdate=1 也跳过）。
		MIN_OS_MAJOR = 3

		# 同一次运行里，同一分支的同一 XMS 版本只请求一次日志：
		# ota_former / ota_full 会探测多个系统版本，它们命中的是同一份 XMS。
		_changelog_cache: Dict[Tuple[str, str], Tuple[Dict, Dict]] = {}
		_version_cache: Dict[Tuple[str, str, str], Dict[str, str]] = {}

		# ==================== 入口 ====================

		@classmethod
		def record(cls, form: Dict[str, Any], result: Dict[str, Any]) -> Optional[Dict[str, Any]]:
				"""解析一次 OTA 响应里的 xmsUpdateInfo 并落库

				form 为本次 OTA 请求表单（含 d/c/b/r/l/ov/options 等字段），
				result 为解密后的响应。没有 XMS 更新时直接返回 None。
				"""
				info = result.get("xmsUpdateInfo") or {}
				xms_version = str(info.get("lstVer") or "").strip()
				if str(info.get("hasXmsUpdate") or "0") != "1" or not xms_version:
						return None

				code = str(form.get("d") or "").strip()
				if not code:
						return None
				device = str(form.get("p") or "").strip() or code
				region = cls._region_of(form.get("r"))
				zone = cls._zone_of(form)
				android = str(form.get("c") or "").strip()
				# changeLog 里描述的是「当前系统版本」上的应用更新，优先用接口回显的 CurrentRom
				rom_version = str((result.get("CurrentRom") or {}).get("version")
													or form.get("ov") or "").strip()
				if not rom_version:
						return None
				if cls._os_major(rom_version) < cls.MIN_OS_MAJOR:
						# 只需要 OS3 及以上的 XMS（OS1/OS2 与 MIUI 版本不抓）
						return None

				rom = DatabaseManager.query_one(
						"SELECT id FROM roms WHERE code = %s AND version = %s ORDER BY id DESC LIMIT 1",
						params=(code, rom_version)
				)
				if not rom:
						# 系统版本还没入库（多见于探测出来的未发布版本），等它进了 roms 再记录
						return None
				rom_id = int(rom[0])

				is_latest = cls._is_latest(result, rom_version)

				zh_log, en_log = cls._fetch_changelogs(form, xms_version)
				apps = cls._build_apps(info.get("pkgs") or [], zh_log, en_log)
				# APK 信息（版本号 / 文件名 / 体积 / 校验值）来自 getXmsVer，缺失时用 changeLog 的 versionCode
				apks = cls._fetch_apks(
						form, xms_version, [app["pkg"] for app in apps if app["pkg"]]
				)
				for app in apps:
						meta = apks.get(app["pkg"]) or {}
						if not app["pkg_ver"]:
								app["pkg_ver"] = meta.get("version", "")
						app["apk_name"] = meta.get("apk_name", "")
						app["file_name"] = meta.get("file_name", "")
						app["size"] = meta.get("size", 0)
						app["md5"] = meta.get("md5", "")
						app["sha256"] = meta.get("sha256", "")
				notice = cls._notice_text(info.get("gentleNotice"))

				xms_id = cls._store_bundle(
						device=device, code=code, region=region, zone=zone, android=android,
						xms_version=xms_version, rom_version=rom_version, rom_id=rom_id,
						pkg_cnt=cls._int(info.get("pkgCnt")), prio=cls._int(info.get("prio")),
						notice=notice, is_latest=is_latest
				)
				if not xms_id:
						return None
				cls._store_apps(xms_id, apps)

				print(f"XMS 已入库: {device} {rom_version} → {xms_version}，"
							f"{len(apps)} 个应用{'（最新）' if is_latest else ''}")
				return {"id": xms_id, "version": xms_version, "rom_version": rom_version,
								"apps": len(apps), "is_latest": is_latest}

		# ==================== 接口请求 ====================

		@classmethod
		def _fetch_changelogs(cls, form: Dict[str, Any],
													xms_version: str) -> Tuple[Dict, Dict]:
				"""取同一份 XMS 的中文 / 英文更新日志

				接口只在请求带 xv=<lstVer> 时才回 changeLog，且按 l 参数返回对应语种，
				所以中英文各请求一次。失败时返回空字典，不影响主流程。
				"""
				key = (str(form.get("d") or ""), xms_version)
				if key in cls._changelog_cache:
						return cls._changelog_cache[key]

				logs: List[Dict] = []
				for lang in ("zh_CN", "en_US"):
						payload = dict(form)
						payload["xv"] = xms_version
						payload["l"] = lang
						try:
								result = NetworkClient.call_api_form(payload)
						except Exception:
								result = None
						logs.append(cls._changelog_of(result))

				cached = (logs[0], logs[1])
				cls._changelog_cache[key] = cached
				return cached

		@classmethod
		def _fetch_apks(cls, form: Dict[str, Any], xms_version: str,
										pkgs: List[str]) -> Dict[str, Dict[str, Any]]:
				"""取每个应用的安装包信息（接口 getXmsVer）

				返回 {包名: {version, apk_name, file_name, size, md5, sha256}}。
				该接口在版本 / 区域不匹配时会返回空 desc（没有 apkLists），
				因此这里只做「有就用」：拿不到时版本号回落到 changeLog 里的 versionCode。
				签名下载地址不落库（带时效签名），下载时由站点服务端现取（见 web 的 /api/xms/download）。
				"""
				if not pkgs:
						return {}
				cache_key = ("ver", str(form.get("d") or ""), xms_version)
				cached = cls._version_cache.get(cache_key)
				if cached is not None:
						return cached

				android = str(form.get("c") or "").strip()
				if android.endswith(".0"):
						android = android[:-2]
				payload: Dict[str, Any] = {
						"b": form.get("b") or "F",
						"c": android,
						"d": form.get("d") or "",
						"f": "1",
						"l": form.get("l") or "zh_CN",
						"lsv": xms_version,
						"r": form.get("r") or "",
						"id": "",
						"pkgs": [{"pkg": pkg, "pkgVer": "1"} for pkg in pkgs],
				}
				rom_version = str(form.get("ov") or "").strip()
				if rom_version:
						payload["rv"] = rom_version
				try:
						result = NetworkClient.call_api_form(
								payload, url=_const.XMS_VER_URL,
								extra={"n": str(uuid.uuid4()),
											 "ts": str(int(beijing_now().timestamp() * 1000))}
						)
				except Exception:
						result = None
				if not isinstance(result, dict):
						return {}
				apks: Dict[str, Dict[str, Any]] = {}
				for apk in result.get("apkLists") or []:
						if not isinstance(apk, dict):
								continue
						pkg = str(apk.get("packName") or "").strip()
						if not pkg:
								continue
						apks[pkg] = {
								"version": str(apk.get("lastVerCode") or "").strip(),
								"apk_name": str(apk.get("name") or "").strip(),
								"file_name": str(apk.get("fileName") or "").strip(),
								"size": cls._int(apk.get("size")),
								"md5": str(apk.get("md5") or "").strip(),
								"sha256": str(apk.get("sha256") or "").strip(),
						}
				cls._version_cache[cache_key] = apks
				return apks

		# ==================== 解析 ====================

		@classmethod
		def _changelog_of(cls, result: Optional[Dict[str, Any]]) -> Dict:
				if not isinstance(result, dict):
						return {}
				info = result.get("xmsUpdateInfo") or {}
				log = info.get("changeLog") or {}
				return log if isinstance(log, dict) else {}

		@classmethod
		def _flatten(cls, log: Dict) -> List[Dict[str, str]]:
				"""把 {模块名: [条目]} 摊平成条目列表"""
				entries: List[Dict[str, str]] = []
				if not isinstance(log, dict):
						return entries
				for module, items in log.items():
						if not isinstance(items, list):
								continue
						for item in items:
								if not isinstance(item, dict):
										continue
								txt = str(item.get("txt") or "").strip()
								if not txt:
										continue
								entries.append({
										"module": str(module or "").strip(),
										"pkg": str(item.get("package") or "").strip(),
										"ver": str(item.get("versionCode") or "").strip(),
										"txt": txt,
								})
				return entries

		@staticmethod
		def _group(entries: List[Dict[str, str]]) -> Dict[Tuple[str, str], List[Dict[str, str]]]:
				"""按包名分组；没有包名的条目按模块名单独分组"""
				groups: Dict[Tuple[str, str], List[Dict[str, str]]] = {}
				for entry in entries:
						key = ("pkg", entry["pkg"]) if entry["pkg"] else ("module", entry["module"])
						groups.setdefault(key, []).append(entry)
				return groups

		@classmethod
		def _build_apps(cls, pkgs: List[str], zh_log: Dict, en_log: Dict) -> List[Dict[str, Any]]:
				"""合并包名列表与中英文日志，得到 xms_app 的行数据"""
				zh_groups = cls._group(cls._flatten(zh_log))
				en_groups = cls._group(cls._flatten(en_log))
				apps: List[Dict[str, Any]] = []
				seen = set()

				def add(pkg: str, zh_items: List[Dict[str, str]], en_items: List[Dict[str, str]]):
						pkg = str(pkg or "").strip()
						if pkg in seen:
								return
						if pkg:
								seen.add(pkg)
						apps.append(cls._make_app(pkg, zh_items, en_items))

				# 1) 接口给的包名列表（即使没有日志也保留，说明本次覆盖范围）
				for pkg in pkgs:
						add(pkg, zh_groups.get(("pkg", str(pkg or "").strip()), []),
								en_groups.get(("pkg", str(pkg or "").strip()), []))

				# 2) 日志里有、但包名列表没提到的包
				for (kind, key), items in zh_groups.items():
						if kind == "pkg":
								add(key, items, en_groups.get(("pkg", key), []))
						else:
								# 没有包名的模块（如「小米相册-编辑」），中英文模块名对不上，只存中文
								apps.append(cls._make_app("", items, []))
				if not zh_groups:
						for (kind, key), items in en_groups.items():
								if kind == "pkg":
										add(key, [], items)
								else:
										apps.append(cls._make_app("", [], items))

				return apps

		@classmethod
		def _make_app(cls, pkg: str, zh_items: List[Dict[str, str]],
									en_items: List[Dict[str, str]]) -> Dict[str, Any]:
				name = zh_items[0]["module"] if zh_items else (
						en_items[0]["module"] if en_items else "")
				name_en = en_items[0]["module"] if en_items else ""
				pkg_ver = next((i["ver"] for i in zh_items if i["ver"]), "")
				if not pkg_ver:
						pkg_ver = next((i["ver"] for i in en_items if i["ver"]), "")
				return {
						"pkg": pkg,
						"name": name,
						"name_en": name_en,
						"pkg_ver": pkg_ver,
						"apk_name": "",
						"file_name": "",
						"size": 0,
						"md5": "",
						"sha256": "",
						"logs": cls._pair_logs(zh_items, en_items),
				}

		@staticmethod
		def _pair_logs(zh_items: List[Dict[str, str]],
									 en_items: List[Dict[str, str]]) -> List[Dict[str, str]]:
				"""中英文条目按序号对齐；数量不一致时只保留中文，避免错配"""
				if not zh_items:
						return [{"en": item["txt"]} for item in en_items]
				if not en_items or len(zh_items) != len(en_items):
						return [{"zh": item["txt"]} for item in zh_items]
				return [{"zh": zh["txt"], "en": en["txt"]} for zh, en in zip(zh_items, en_items)]

		@staticmethod
		def _notice_text(gentle: Optional[Dict[str, Any]]) -> str:
				"""把注意事项的 HTML 片段转成纯文本（与 Updater-KMP 的清理方式一致）"""
				text = str((gentle or {}).get("text") or "")
				if not text:
						return ""
				text = (text.replace("<li>", "\n· ").replace("</li>", "")
								.replace("<p>", "\n").replace("</p>", "\n"))
				text = re.sub(r"<[^>]+>", "", text)
				text = text.replace("&nbsp;", " ").replace("&#160;", "")
				lines = [line.strip() for line in text.splitlines() if line.strip()]
				# 第一行是标题（注意事项 / Notes），去掉
				if lines and not lines[0].startswith("·"):
						lines = lines[1:]
				return "\n".join(lines)

		# ==================== 落库 ====================

		@classmethod
		def _store_bundle(cls, device: str, code: str, region: str, zone: int, android: str,
											xms_version: str, rom_version: str, rom_id: int,
											pkg_cnt: int, prio: int, notice: str,
											is_latest: int) -> int:
				"""写入 / 更新一条 XMS 推送，返回 xms.id"""
				now = beijing_now()
				timestamp = int(now.timestamp())
				existing = DatabaseManager.query_one(
						"SELECT id FROM xms WHERE code = %s AND version = %s AND rom_version = %s",
						params=(code, xms_version, rom_version)
				)

				if existing:
						xms_id = int(existing[0])
						DatabaseManager.execute(
								"UPDATE xms SET device = %s, region = %s, zone = %s, android = %s, "
								"rom_id = %s, pkg_cnt = %s, prio = %s, notice = %s, is_latest = %s, "
								"update_date = %s WHERE id = %s",
								params=(device, region, zone, android, rom_id, pkg_cnt, prio, notice,
												is_latest, timestamp, xms_id),
								raise_on_error=True
						)
				else:
						# 同一份 XMS 挂在不同系统版本上时，沿用最早那天的推送日期
						sibling = DatabaseManager.query_one(
								"SELECT push_date FROM xms WHERE code = %s AND version = %s "
								"ORDER BY id LIMIT 1",
								params=(code, xms_version)
						)
						push_date = sibling[0] if sibling and sibling[0] else now.date()
						xms_id = DatabaseManager.insert(
								"INSERT INTO xms(device, code, region, zone, android, version, rom_version, "
								"rom_id, pkg_cnt, prio, notice, is_latest, push_date, update_date) "
								"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
								params=(device, code, region, zone, android, xms_version, rom_version, rom_id,
												pkg_cnt, prio, notice, is_latest, push_date, timestamp),
								raise_on_error=True
						)
						if not xms_id:
								return 0

				if is_latest:
						# 同一分支只保留一条「最新」
						DatabaseManager.execute(
								"UPDATE xms SET is_latest = 0 WHERE code = %s AND id <> %s",
								params=(code, xms_id),
								raise_on_error=True
						)
				return xms_id

		@classmethod
		def _store_apps(cls, xms_id: int, apps: List[Dict[str, Any]]) -> None:
				"""按（xms_id, pkg, name）幂等写入应用行，并清掉本次已不存在的行"""
				rows = DatabaseManager.query_all(
						"SELECT id, pkg, name FROM xms_app WHERE xms_id = %s",
						params=(xms_id,)
				)
				existing = {(row[1] or "", row[2] or ""): int(row[0]) for row in rows}
				keep = set()

				for app in apps:
						key = (app["pkg"], app["name"] or "")
						keep.add(key)
						logs = json.dumps(app["logs"], ensure_ascii=False) if app["logs"] else None
						if key in existing:
								DatabaseManager.execute(
										"UPDATE xms_app SET name_en = %s, pkg_ver = %s, apk_name = %s, "
										"file_name = %s, size = %s, md5 = %s, sha256 = %s, logs = %s "
										"WHERE id = %s",
										params=(app["name_en"], app["pkg_ver"], app["apk_name"], app["file_name"],
														app["size"] or None, app["md5"], app["sha256"], logs,
														existing[key]),
										raise_on_error=True
								)
						else:
								DatabaseManager.insert(
										"INSERT INTO xms_app(xms_id, pkg, name, name_en, pkg_ver, apk_name, "
										"file_name, size, md5, sha256, logs) "
										"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
										params=(xms_id, app["pkg"], app["name"], app["name_en"], app["pkg_ver"],
														app["apk_name"], app["file_name"], app["size"] or None,
														app["md5"], app["sha256"], logs),
										raise_on_error=True
								)

				stale = [rid for key, rid in existing.items() if key not in keep]
				if stale:
						placeholders = ",".join(["%s"] * len(stale))
						DatabaseManager.execute(
								f"DELETE FROM xms_app WHERE xms_id = %s AND id IN ({placeholders})",
								params=(xms_id, *stale),
								raise_on_error=True
						)

		# ==================== 工具 ====================

		@staticmethod
		def _is_latest(result: Dict[str, Any], rom_version: str) -> int:
				"""当前系统版本是否就是接口给出的最新版本（LatestRom）

				以接口为准：没返回 LatestRom（探测出来的未发布版本、接口不认的版本）时
				一律标 0，避免「用库内最新版本兜底」导致 ota_full 多版本探测时标志来回翻转。
				"""
				latest = str((result.get("LatestRom") or {}).get("version") or "").strip()
				return 1 if latest and latest == rom_version else 0

		@staticmethod
		def _os_major(rom_version: str) -> int:
				"""系统版本号的大版本：OS3.0.304.0.xxx -> 3，MIUI 的 V816.x -> 0"""
				match = re.match(r'^OS(\d+)', str(rom_version or '').strip())
				return int(match.group(1)) if match else 0

		@staticmethod
		def _region_of(field: Any) -> str:
				"""把请求表单的 r 字段还原成数据库里的区域代号"""
				raw = str(field or "").strip().lower()
				if raw in ("cn", "zh_cn"):
						return "cn"
				if raw in ("gl", "global"):
						return "global"
				return raw

		@staticmethod
		def _zone_of(form: Dict[str, Any]) -> int:
				options = form.get("options") or {}
				zone = options.get("zone")
				try:
						return int(zone)
				except (TypeError, ValueError):
						return 1 if XmsStore._region_of(form.get("r")) == "cn" else 2

		@staticmethod
		def _int(value: Any) -> int:
				try:
						return int(value)
				except (TypeError, ValueError):
						return 0
