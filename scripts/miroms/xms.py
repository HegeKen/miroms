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

两条与业务约定相关的规则：
* 应用名按包名统一 —— 同一个 pkg 在所有推送里共用一份 name / name_en / names，
  译文优先取 logs 表里同名的 module 行（官方 21 语种），见 canonicalize()。
* 没有 package 的日志模块（如「小米超级岛」）不是应用，存到 xms.changelog，
  不按模块名塞进 xms_app —— 模块名会随请求语种变化，按名字当键会重复录入。

XMS 只存在于 HyperOS 3 及以上：接口约定 XMS 版本号首字母对应大版本
（C → HyperOS 3、D → HyperOS 4……），OS1/OS2 与 MIUI 版本直接跳过。
"""
import hashlib
import json
import logging
import re
import uuid
from collections import Counter
from datetime import datetime, timedelta

import requests
from typing import Any, Dict, List, Optional, Tuple

from miroms.constants import _const, CHANGELOG_COLUMNS
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
		_version_cache: Dict[Tuple[str, str, str], Dict[str, Dict[str, Any]]] = {}
		_release_cache: Dict[str, str] = {}
		# logs 表的多语言译文按（类型, 原文）缓存，避免同一段文本反复查库
		_translation_cache: Dict[Tuple[str, str], Dict[str, str]] = {}

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
				apps, extras = cls._build_apps(info.get("pkgs") or [], zh_log, en_log)

				# APK 信息（版本号 / 文件名 / 体积 / 校验值）来自 getXmsVer，缺失时用 changeLog 的 versionCode
				apks = cls._fetch_apks(form, xms_version, [app["pkg"] for app in apps])
				for app in apps:
						meta = apks.get(app["pkg"]) or {}
						if not app["pkg_ver"]:
								app["pkg_ver"] = meta.get("version", "")
						app["apk_name"] = meta.get("apk_name", "")
						app["file_name"] = meta.get("file_name", "")
						app["size"] = meta.get("size", 0)
						app["md5"] = meta.get("md5", "")
						app["sha256"] = meta.get("sha256", "")

				# 只有名称、没有安装包 / 日志的条目不落库（避免空壳行）
				apps = [app for app in apps
								if app.get("file_name") or app.get("md5") or app.get("logs")]

				# 本次推送的应用包发布日期（HTTP Last-Modified）：多数包同一天上传的那天 = 真实推送日
				release_dates = [app.get("release_date") for app in apps if app.get("release_date")]
				bundle_date = None
				if release_dates:
						counter = Counter(release_dates)
						max_count = max(counter.values())
						# 并列时取较早的一天
						bundle_date = min(date for date, count in counter.items() if count == max_count)

				# 用 logs 表的官方译文补齐中英以外的语种
				for app in apps:
						cls._enrich_logs(app["logs"])
				for extra in extras:
						cls._enrich_logs(extra["logs"])

				# 应用名在 logs 的 module 里还没有时，先写一条 zh / en 占位，
				# 之后可以继续补全其它语种（不影响本次入库的名称）
				for app in apps:
						try:
								cls._ensure_module_log(app.get("name", ""), app.get("name_en", ""))
						except Exception as exc:  # 单个名称失败不影响整次入库
								logging.getLogger(__name__).warning(
										"写入 logs module 失败 %s: %s", app.get("name"), exc)

				notice = cls._notice_text(info.get("gentleNotice"))

				xms_id = cls._store_bundle(
						device=device, code=code, region=region, zone=zone, android=android,
						xms_version=xms_version, rom_version=rom_version, rom_id=rom_id,
						pkg_cnt=cls._int(info.get("pkgCnt")), prio=cls._int(info.get("prio")),
						notice=notice, changelog=extras, is_latest=is_latest,
						push_date=bundle_date
				)
				if not xms_id:
						return None
				cls._store_apps(xms_id, apps, device=device)
				# 推送日期按该 XMS 版本涉及的 ROM 最早发布日期统一
				cls.normalize_push_dates(apply=True)

				# 同一包名在所有推送里统一名称（新写入的应用名可能来自不同版本 / 语种）
				for pkg in sorted({app["pkg"] for app in apps}):
						cls.canonicalize(pkg)

				print(f"XMS 已入库: {device} {rom_version} → {xms_version}，"
							f"{len(apps)} 个应用{'（最新）' if is_latest else ''}")
				return {"id": xms_id, "version": xms_version, "rom_version": rom_version,
								"apps": len(apps), "extras": len(extras), "is_latest": is_latest}

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
						info = {
								"version": str(apk.get("lastVerCode") or "").strip(),
								"apk_name": str(apk.get("name") or "").strip(),
								"file_name": str(apk.get("fileName") or "").strip(),
								"size": cls._int(apk.get("size")),
								"md5": str(apk.get("md5") or "").strip(),
								"sha256": str(apk.get("sha256") or "").strip(),
								"download_urls": [str(url) for url in (apk.get("downloadUrls") or []) if url],
						}
						# 安装包的真实发布日期：HTTP Last-Modified（签名链接只有本次可用，立即取）
						info["release_date"] = cls._apk_release_date(info["md5"], info["file_name"],
																															 info["download_urls"])
						apks[pkg] = info
				cls._version_cache[cache_key] = apks
				return apks

		@classmethod
		def _apk_release_date(cls, md5: str, file_name: str, urls: List[str]) -> str:
				"""用 APK 的 HTTP Last-Modified 取真实发布 / 上传日期（YYYY-MM-DD，北京时间）

				优先用内存 / 数据库里同 md5 的已有值；拿不到时返回空串（不写库）。
				"""
				key = md5 or file_name
				if key and key in cls._release_cache:
						return cls._release_cache[key]
				if md5:
						row = DatabaseManager.query_one(
								"SELECT release_date FROM xms_app WHERE md5 = %s "
								"AND release_date IS NOT NULL ORDER BY id DESC LIMIT 1",
								params=(md5,)
						)
						if row and row[0]:
								value = str(row[0])
								cls._release_cache[key] = value
								return value
				for url in urls or []:
						try:
								response = requests.head(url, allow_redirects=True, timeout=10)
								last_modified = response.headers.get("Last-Modified")
								if not last_modified:
										continue
								dt = datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S %Z") + timedelta(hours=8)
								value = dt.strftime("%Y-%m-%d")
								if key:
										cls._release_cache[key] = value
								return value
						except (requests.RequestException, ValueError):
								continue
				return ""

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
		def _build_apps(cls, pkgs: List[str], zh_log: Dict,
										en_log: Dict) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
				"""合并包名列表与中英文日志，得到 xms_app 行 + 无包名模块

				返回 (apps, extras)：
				  apps   真正的应用（有 pkg），按包名去重；
				  extras 没有 package 的日志模块（如「小米超级岛」），存 xms.changelog。
				"""
				zh_groups = cls._group(cls._flatten(zh_log))
				en_groups = cls._group(cls._flatten(en_log))
				apps: List[Dict[str, Any]] = []
				extras: List[Dict[str, Any]] = []
				seen, extra_seen = set(), set()

				def add(pkg: str, zh_items: List[Dict[str, str]], en_items: List[Dict[str, str]]):
						pkg = str(pkg or "").strip()
						if not pkg or pkg in seen:
								return
						seen.add(pkg)
						apps.append(cls._make_app(pkg, zh_items, en_items))

				def add_extra(zh_items: List[Dict[str, str]], en_items: List[Dict[str, str]]):
						extra = cls._make_extra(zh_items, en_items)
						key = extra["name"].get("zh") or extra["name"].get("en") or ""
						if not key or key in extra_seen:
								return
						extra_seen.add(key)
						extras.append(extra)

				# 1) 接口给的包名列表（即使没有日志也保留，说明本次覆盖范围）
				for pkg in pkgs:
						key = str(pkg or "").strip()
						add(key, zh_groups.get(("pkg", key), []), en_groups.get(("pkg", key), []))

				# 2) 日志里有、但包名列表没提到的包；没有包名的模块单独收集
				for (kind, key), items in zh_groups.items():
						if kind == "pkg":
								add(key, items, en_groups.get(("pkg", key), []))
						else:
								add_extra(items, [])
				if not zh_groups:
						for (kind, key), items in en_groups.items():
								if kind == "pkg":
										add(key, [], items)
								else:
										add_extra([], items)

				return apps, extras

		@classmethod
		def _make_app(cls, pkg: str, zh_items: List[Dict[str, str]],
									en_items: List[Dict[str, str]]) -> Dict[str, Any]:
				name = zh_items[0]["module"] if zh_items else (
						en_items[0]["module"] if en_items else "")
				name_en = en_items[0]["module"] if en_items else ""
				pkg_ver = next((i["ver"] for i in zh_items if i["ver"]), "")
				if not pkg_ver:
						pkg_ver = next((i["ver"] for i in en_items if i["ver"]), "")
				names = cls._resolve_name(name, name_en)
				return {
						"pkg": pkg,
						"name": names.get("zh", ""),
						"name_en": names.get("en", ""),
						"names": names,
						"pkg_ver": pkg_ver,
						"apk_name": "",
						"file_name": "",
						"size": 0,
						"md5": "",
						"sha256": "",
						"logs": cls._pair_logs(zh_items, en_items),
				}

		@classmethod
		def _make_extra(cls, zh_items: List[Dict[str, str]],
										en_items: List[Dict[str, str]]) -> Dict[str, Any]:
				"""没有包名的日志模块（存 xms.changelog，不进 xms_app）"""
				name = zh_items[0]["module"] if zh_items else (
						en_items[0]["module"] if en_items else "")
				name_en = en_items[0]["module"] if en_items else ""
				return {
						"name": cls._resolve_name(name, name_en),
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

		@classmethod
		def _notice_text(cls, gentle: Optional[Dict[str, Any]]) -> str:
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

		# ==================== 多语言 / 名称统一 ====================

		@staticmethod
		def _names_from(value: Any) -> Dict[str, str]:
				"""names 列（JSON）或 {zh, en} 字典 -> 全语言名称字典"""
				if isinstance(value, str):
						try:
								value = json.loads(value)
						except (json.JSONDecodeError, TypeError):
								return {}
				if not isinstance(value, dict):
						return {}
				return {str(key): str(text).strip() for key, text in value.items()
								if str(text or "").strip()}

		@classmethod
		def _ensure_module_log(cls, zh: str, en: str) -> bool:
				"""logs 里没有该模块名时先建占位行（zh / en 两列），方便后续补全翻译

				返回是否新建了记录。
				"""
				zh = str(zh or "").strip()
				en = str(en or "").strip()
				if en and en == zh:
						en = ""
				if not zh:
						return False
				row = DatabaseManager.query_one(
						"SELECT id, logs_en FROM logs WHERE type = 'module' "
						"AND (content = %s OR logs_zh = %s OR (logs_en <> '' AND logs_en = %s)) "
						"ORDER BY id LIMIT 1",
						params=(zh, zh, en or zh),
				)
				if row:
						# 已有模块名：英文列空着时顺手补上
						if en and not str(row[1] or "").strip():
								DatabaseManager.execute(
										"UPDATE logs SET logs_en = %s WHERE id = %s",
										params=(en, row[0]), raise_on_error=True
								)
						return False
				# MySQL 9 起已移除 MD5()，在 Python 侧算好再写入
				content_hash = hashlib.md5(zh.encode("utf-8")).hexdigest()
				DatabaseManager.execute(
						"INSERT INTO logs (type, content, content_hash, logs_zh, logs_en) "
						"VALUES ('module', %s, %s, %s, %s)",
						params=(zh, content_hash, zh, en or None), raise_on_error=True
				)
				return True

		@classmethod
		def ensure_module_logs(cls) -> int:
				"""为所有 XMS 应用名补齐 logs 的 module 占位行，返回新建条数"""
				created = 0
				seen = set()
				for name, name_en in DatabaseManager.query_all(
								"SELECT DISTINCT name, name_en FROM xms_app WHERE name <> ''"):
						key = str(name or "").strip()
						if not key or key in seen:
								continue
						seen.add(key)
						if cls._ensure_module_log(name, name_en):
								created += 1
				return created

		@classmethod
		def _translations(cls, kind: str, zh: str, en: str) -> Dict[str, str]:
				"""在 logs 表按中文（或英文）原文查官方多语言译文

				kind 为 logs.type：module（模块 / 应用名）或 log（日志条目）。
				词条可能不存在，返回空字典；结果按（类型, 原文）在进程内缓存。
				"""
				zh = str(zh or "").strip()
				en = str(en or "").strip()
				if not zh and not en:
						return {}
				cache_key = (kind, zh or en)
				cached = cls._translation_cache.get(cache_key)
				if cached is not None:
						return cached

				columns = ", ".join(f"`{column}`" for column in CHANGELOG_COLUMNS)
				row = None
				if zh:
						row = DatabaseManager.query_one(
								f"SELECT {columns} FROM logs WHERE type = %s AND content = %s LIMIT 1",
								params=(kind, zh)
						)
				if not row and en:
						row = DatabaseManager.query_one(
								f"SELECT {columns} FROM logs WHERE type = %s AND logs_en = %s LIMIT 1",
								params=(kind, en)
						)

				result: Dict[str, str] = {}
				if row:
						for column, text in zip(CHANGELOG_COLUMNS, row):
								value = str(text or "").strip()
								if value:
										result[column[len("logs_"):]] = value
				cls._translation_cache[cache_key] = result
				return result

		@classmethod
		def _resolve_name(cls, name: str, name_en: str,
											fallback: str = "") -> Dict[str, str]:
				"""应用 / 模块名的多语言版本：优先 logs 表 module 行的官方译文"""
				zh = str(name or "").strip()
				en = str(name_en or "").strip()
				translations = cls._translations("module", zh, en)
				if translations:
						zh = translations.get("zh") or zh
						en = translations.get("en") or en
				zh = zh or en or str(fallback or "").strip()
				en = en or zh
				names: Dict[str, str] = {"zh": zh, "en": en}
				for key, value in translations.items():
						names.setdefault(key, value)
				return {key: value for key, value in names.items() if value}

		@classmethod
		def _enrich_logs(cls, logs: List[Dict[str, str]]) -> int:
				"""用 logs 表官方译文补全日志条目的其它语种，返回新增语言数"""
				added = 0
				for entry in logs or []:
						translations = cls._translations("log", entry.get("zh", ""), entry.get("en", ""))
						for key, value in translations.items():
								if not entry.get(key):
										entry[key] = value
										added += 1
				return added

		@classmethod
		def canonicalize(cls, pkg: str, apply: bool = True) -> int:
				"""把同一个包名在所有推送里的应用名统一成一份

				候选名来自各推送 changeLog 的模块名；能命中 logs 表 module 行的优先，
				其次取语种最全、出现次数最多的那个。返回被更新的行数。
				"""
				pkg = str(pkg or "").strip()
				if not pkg:
						return 0
				rows = DatabaseManager.query_all(
						"SELECT id, name, name_en, names FROM xms_app WHERE pkg = %s",
						params=(pkg,)
				)
				if not rows:
						return 0

				candidates: List[Tuple[Dict[str, str], bool]] = []
				for _row_id, name, name_en, names in rows:
						i18n = cls._names_from(names)
						if not i18n:
								i18n = {key: value for key, value in
												(("zh", name), ("en", name_en)) if value}
						if not i18n:
								continue
						translations = cls._translations("module", i18n.get("zh", ""), i18n.get("en", ""))
						for key, value in translations.items():
								i18n.setdefault(key, value)
						i18n = {key: value for key, value in i18n.items() if value}
						if i18n:
								candidates.append((i18n, bool(translations)))
				if not candidates:
						return 0

				counts: Dict[str, int] = {}
				for i18n, _official in candidates:
						key = i18n.get("zh") or i18n.get("en") or ""
						counts[key] = counts.get(key, 0) + 1

				best: Dict[str, str] = {}
				best_score: Tuple[int, int, int] = (-1, -1, -1)
				for i18n, official in candidates:
						key = i18n.get("zh") or i18n.get("en") or ""
						score = (1 if official else 0, len(i18n), counts.get(key, 0))
						if score > best_score:
								best, best_score = i18n, score

				zh = best.get("zh") or best.get("en") or ""
				en = best.get("en") or zh
				payload = json.dumps(best, ensure_ascii=False)
				updated = 0
				for row_id, name, name_en, names in rows:
						if (name or "") == zh and (name_en or "") == en and (names or "") == payload:
								continue
						if apply:
								DatabaseManager.execute(
										"UPDATE xms_app SET name = %s, name_en = %s, names = %s WHERE id = %s",
										params=(zh, en, payload, row_id),
										raise_on_error=True
								)
						updated += 1
				return updated

		# ==================== 落库 ====================

		@classmethod
		def normalize_push_dates(cls, apply: bool = True) -> int:
				"""同一 XMS 版本的所有行日期统一为该版本涉及的 ROM 里最早的发布日期

				优先取 roms.release_date，缺失时依次回退 public_date / beta_date；
				完全没有 ROM 日期时回退到已有 push_date。返回被改动的行数。
				"""
				rows = DatabaseManager.query_all(
						"SELECT id, version, push_date FROM xms WHERE version IS NOT NULL")
				# 每个版本取应用包发布日期的众数（多数包同一天上传的那天 = 推送日）
				mode_rows = DatabaseManager.query_all(
						"SELECT x.version, a.release_date, COUNT(*) AS cnt "
						"FROM xms_app a JOIN xms x ON x.id = a.xms_id "
						"WHERE a.release_date IS NOT NULL AND x.version IS NOT NULL "
						"GROUP BY x.version, a.release_date")
				mode: Dict[str, Any] = {}
				mode_count: Dict[str, int] = {}
				for version, release_date, cnt in mode_rows:
						count = int(cnt)
						if (count > mode_count.get(version, -1)
								or (count == mode_count.get(version, -1)
										and release_date < mode.get(version, release_date))):
								mode[version] = release_date
								mode_count[version] = count
				earliest: Dict[str, Any] = dict(mode)
				# 没有任何应用包日期的版本，回退到已有 push_date 的最早值
				for _row_id, version, push_date in rows:
						if version in earliest:
								continue
						if push_date and (version not in earliest or push_date < earliest[version]):
								earliest[version] = push_date
				updated = 0
				for row_id, version, push_date in rows:
						target = earliest.get(version)
						if not target or push_date == target:
								continue
						if apply:
								DatabaseManager.execute(
										"UPDATE xms SET push_date = %s WHERE id = %s",
										params=(target, row_id), raise_on_error=True
								)
						updated += 1
				return updated

		@classmethod
		def _store_bundle(cls, device: str, code: str, region: str, zone: int, android: str,
											xms_version: str, rom_version: str, rom_id: int,
											pkg_cnt: int, prio: int, notice: str,
											changelog: List[Dict[str, Any]],
											is_latest: int, push_date: Optional[str] = None) -> int:
				"""写入 / 更新一条 XMS 推送，返回 xms.id"""
				now = beijing_now()
				timestamp = int(now.timestamp())
				changelog_json = json.dumps(changelog, ensure_ascii=False) if changelog else None
				existing = DatabaseManager.query_one(
						"SELECT id FROM xms WHERE code = %s AND version = %s AND rom_version = %s",
						params=(code, xms_version, rom_version)
				)

				if existing:
						xms_id = int(existing[0])
						DatabaseManager.execute(
								"UPDATE xms SET device = %s, region = %s, zone = %s, android = %s, "
								"rom_id = %s, pkg_cnt = %s, prio = %s, notice = %s, changelog = %s, "
								"is_latest = %s, push_date = COALESCE(%s, push_date), update_date = %s "
								"WHERE id = %s",
								params=(device, region, zone, android, rom_id, pkg_cnt, prio, notice,
												changelog_json, is_latest, push_date, timestamp, xms_id),
								raise_on_error=True
						)
				else:
						# 推送日期取本次应用包 HTTP Last-Modified 的最早一天（下方 normalize 统一）
						push_date = push_date or now.date().isoformat()
						xms_id = DatabaseManager.insert(
								"INSERT INTO xms(device, code, region, zone, android, version, rom_version, "
								"rom_id, pkg_cnt, prio, notice, changelog, is_latest, push_date, update_date) "
								"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
								params=(device, code, region, zone, android, xms_version, rom_version, rom_id,
												pkg_cnt, prio, notice, changelog_json, is_latest, push_date,
												timestamp),
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
		def _existing_app_info(cls, pkg: str, device: str = "") -> Optional[Tuple[str, str, str, Dict[str, str]]]:
				"""取该包名在库中「最完整」的一份名称信息（用于新推送继承）

				返回 (name, name_en, apk_name, names_dict)；没有记录时返回 None。
				同机型的历史行优先（apk_name 会随机型变体变化），其次语种最全的行。
				"""
				rows = DatabaseManager.query_all(
						"SELECT a.name, a.name_en, a.names, a.apk_name, x.device "
						"FROM xms_app a LEFT JOIN xms x ON x.id = a.xms_id WHERE a.pkg = %s",
						params=(pkg,)
				)
				best: Optional[Tuple[str, str, str, Dict[str, str]]] = None
				best_score: Tuple[int, int, int] = (-1, -1, -1)
				best_apk = ""
				best_apk_score: Tuple[int, int] = (-1, -1)
				for name, name_en, names_json, apk_name, row_device in rows:
						same_device = 1 if device and row_device == device else 0
						if apk_name:
								apk_score = (same_device, 1)
								if apk_score > best_apk_score:
										best_apk, best_apk_score = apk_name, apk_score
						i18n = cls._names_from(names_json)
						if not i18n:
								i18n = {key: value for key, value in
												(("zh", name), ("en", name_en)) if value}
						score = (same_device, 1 if i18n else 0, len(i18n))
						if score > best_score:
								best = (name or "", name_en or "", best_apk, i18n)
								best_score = score
				if best and not best[2]:
						best = (best[0], best[1], best_apk, best[3])
				return best

		@classmethod
		def _store_apps(cls, xms_id: int, apps: List[Dict[str, Any]], device: str = "") -> None:
				"""按（xms_id, pkg）幂等写入应用行，并清掉本次已不存在的行

				以 pkg 作为唯一键（应用名会随版本 / 语种变化，不能进键），
				这样同一个包名在多次抓取之间不会因为名字变化重复录入。

				名称字段参考库中同一 pkg 已录入 / 手工修改过的信息：
				已有非空的 name / name_en 优先，names 只补缺失语种；
				apk_name 为空时才回落到旧值（安装包名会随机型变体变化，不能一律沿用）。
				"""
				rows = DatabaseManager.query_all(
						"SELECT id, pkg FROM xms_app WHERE xms_id = %s",
						params=(xms_id,)
				)
				existing = {row[1] or "": int(row[0]) for row in rows}
				keep = set()
				info_cache: Dict[str, Optional[Tuple[str, str, str, Dict[str, str]]]] = {}

				for app in apps:
						keep.add(app["pkg"])
						if app["pkg"] not in info_cache:
								info_cache[app["pkg"]] = cls._existing_app_info(app["pkg"], device)
						info = info_cache[app["pkg"]]

						names_dict: Dict[str, str] = dict(info[3]) if info else {}
						for key, value in (app["names"] or {}).items():
								if value and not names_dict.get(key):
										names_dict[key] = value
						name = (info[0] if info else "") or app["name"] or names_dict.get("zh", "")
						name_en = (info[1] if info else "") or app["name_en"] or names_dict.get("en", "")
						if name and not names_dict.get("zh"):
								names_dict["zh"] = name
						if name_en and not names_dict.get("en"):
								names_dict["en"] = name_en
						# apk_name 由接口生成，往往杂乱、需要人工修复；已有值优先沿用
						apk_name = (info[2] if info else "") or app["apk_name"] or ""
						app = {**app, "name": name, "name_en": name_en, "apk_name": apk_name}

						logs = json.dumps(app["logs"], ensure_ascii=False) if app["logs"] else None
						names = json.dumps(names_dict, ensure_ascii=False) if names_dict else None
						if app["pkg"] in existing:
								DatabaseManager.execute(
										"UPDATE xms_app SET name = %s, name_en = %s, names = %s, "
										"pkg_ver = %s, apk_name = %s, file_name = %s, size = %s, "
										"md5 = %s, sha256 = %s, logs = %s, "
										"release_date = COALESCE(%s, release_date) WHERE id = %s",
										params=(app["name"], app["name_en"], names, app["pkg_ver"],
														app["apk_name"], app["file_name"], app["size"] or None,
														app["md5"], app["sha256"], logs,
														app.get("release_date") or None, existing[app["pkg"]]),
										raise_on_error=True
								)
						else:
								DatabaseManager.insert(
										"INSERT INTO xms_app(xms_id, pkg, name, name_en, names, pkg_ver, "
										"apk_name, file_name, size, md5, sha256, logs, release_date) "
										"VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
										params=(xms_id, app["pkg"], app["name"], app["name_en"], names,
														app["pkg_ver"], app["apk_name"], app["file_name"],
														app["size"] or None, app["md5"], app["sha256"], logs,
														app.get("release_date") or None),
										raise_on_error=True
								)

				stale = [row_id for pkg, row_id in existing.items() if pkg not in keep]
				if stale:
						placeholders = ",".join(["%s"] * len(stale))
						DatabaseManager.execute(
								f"DELETE FROM xms_app WHERE xms_id = %s AND id IN ({placeholders})",
								params=(xms_id, *stale),
								raise_on_error=True
						)

		# ==================== 维护 ====================


		@classmethod
		def clean_empty_apps(cls, apply: bool = True) -> int:
				"""删除「只有名称、没有安装包 / 日志」的 xms_app 空条目

				这类行来自 changeLog 里只出现模块名、getXmsVer 又没返回包的推送，
				没有安装包、校验值或更新日志，前端只会显示一个空壳。
				返回匹配 / 删除的行数。
				"""
				rows = DatabaseManager.query_all(
						"SELECT id FROM xms_app WHERE (file_name IS NULL OR file_name = '') "
						"AND (md5 IS NULL OR md5 = '') "
						"AND (logs IS NULL OR logs = '' OR logs = '[]')"
				)
				ids = [int(row[0]) for row in rows]
				if apply and ids:
						placeholders = ",".join(["%s"] * len(ids))
						DatabaseManager.execute(
								f"DELETE FROM xms_app WHERE id IN ({placeholders})",
								params=tuple(ids), raise_on_error=True
						)
				return len(ids)

		@classmethod
		def migrate_legacy_extras(cls, apply: bool = True) -> int:
				'''把旧版按模块名存进 xms_app 的无包名行搬到 xms.changelog 并删除

				旧逻辑用模块名当键，模块名随请求语种变化会重复录入；新逻辑不再写这类行。
				返回待迁移 / 已迁移的行数。
				'''
				rows = DatabaseManager.query_all(
						"SELECT `id`, `xms_id`, `name`, `name_en`, `logs` FROM `xms_app` "
						"WHERE `pkg` = '' ORDER BY `id`"
				)
				if not rows:
						return 0

				grouped: Dict[int, List[Dict[str, Any]]] = {}
				for _row_id, xms_id, name, name_en, logs in rows:
						item = {
								"name": cls._resolve_name(name, name_en),
								"logs": cls._names_entries(logs),
						}
						grouped.setdefault(int(xms_id), []).append(item)
				if not apply:
						return len(rows)

				for xms_id, items in grouped.items():
						existing = DatabaseManager.query_one(
								"SELECT `changelog` FROM `xms` WHERE `id` = %s", params=(xms_id,))
						merged: List[Dict[str, Any]] = []
						seen = set()
						if existing and existing[0]:
								try:
										for old in json.loads(existing[0]):
												if not isinstance(old, dict):
														continue
												names = cls._names_from(old.get("name"))
												key = names.get("zh") or names.get("en") or ""
												if key and key not in seen:
														seen.add(key)
														merged.append(old)
								except (json.JSONDecodeError, TypeError):
										pass
						for item in items:
								key = item["name"].get("zh") or item["name"].get("en") or ""
								if key and key not in seen:
										seen.add(key)
										merged.append(item)
						if merged:
								DatabaseManager.execute(
										"UPDATE `xms` SET `changelog` = %s WHERE `id` = %s",
										params=(json.dumps(merged, ensure_ascii=False), xms_id),
										raise_on_error=True
								)
				row_ids = [int(row[0]) for row in rows]
				placeholders = ",".join(["%s"] * len(row_ids))
				DatabaseManager.execute(
						f"DELETE FROM `xms_app` WHERE `id` IN ({placeholders})",
						params=tuple(row_ids),
						raise_on_error=True
				)
				return len(row_ids)

		@classmethod
		def enrich_all(cls, apply: bool = True) -> Dict[str, int]:
				"""用 logs 表补全已有 XMS 数据的多语言译文，并按包名统一应用名

				供 scripts/enrich_xms.py 调用：默认只统计，apply=True 才写库。
				"""
				stats = {"legacy": 0, "packages": 0, "names": 0, "logs": 0, "extras": 0,
								 "modules": 0, "dates": 0, "empty": 0}
				stats["legacy"] = cls.migrate_legacy_extras(apply=apply)
				stats["empty"] = cls.clean_empty_apps(apply=apply)
				stats["dates"] = cls.normalize_push_dates(apply=apply)
				if apply:
						# 应用名在 logs 的 module 里缺失时补占位行，方便后续统一补翻译
						stats["modules"] = cls.ensure_module_logs()

				pkgs = [row[0] for row in DatabaseManager.query_all(
						"SELECT DISTINCT pkg FROM xms_app WHERE pkg <> '' ORDER BY pkg")]
				stats["packages"] = len(pkgs)
				for pkg in pkgs:
						stats["names"] += cls.canonicalize(pkg, apply=apply)

				for row_id, value in DatabaseManager.query_all(
								"SELECT id, logs FROM xms_app WHERE logs IS NOT NULL"):
						entries = cls._names_entries(value)
						added = cls._enrich_logs(entries)
						if added:
								stats["logs"] += 1
								if apply:
										DatabaseManager.execute(
												"UPDATE xms_app SET logs = %s WHERE id = %s",
												params=(json.dumps(entries, ensure_ascii=False), row_id),
												raise_on_error=True
										)

				for row_id, value in DatabaseManager.query_all(
								"SELECT id, changelog FROM xms WHERE changelog IS NOT NULL"):
						try:
								extras = json.loads(value)
						except (json.JSONDecodeError, TypeError):
								continue
						changed = 0
						for extra in extras:
								if not isinstance(extra, dict):
										continue
								# 模块名同样用 logs 表 module 行补全多语言
								names = cls._names_from(extra.get("name"))
								resolved = cls._resolve_name(names.get("zh", ""), names.get("en", ""))
								if resolved and resolved != names:
										extra["name"] = resolved
										changed += 1
								entries = extra.get("logs")
								if isinstance(entries, list):
										changed += cls._enrich_logs(entries)
						if changed:
								stats["extras"] += 1
								if apply:
										DatabaseManager.execute(
												"UPDATE xms SET changelog = %s WHERE id = %s",
												params=(json.dumps(extras, ensure_ascii=False), row_id),
												raise_on_error=True
										)
				return stats

		@staticmethod
		def _names_entries(value: Any) -> List[Dict[str, str]]:
				"""logs 列（JSON 数组）-> 可修改的条目列表"""
				if isinstance(value, str):
						try:
								value = json.loads(value)
						except (json.JSONDecodeError, TypeError):
								return []
				if not isinstance(value, list):
						return []
				return [entry for entry in value if isinstance(entry, dict)]

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
