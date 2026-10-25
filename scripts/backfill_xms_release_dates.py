#!/usr/bin/env python3
"""用 XMS 安装包下载链接的 HTTP Last-Modified 回填 xms_app.release_date

XMS 只给签名下载链接（有时效），链接响应头里的 Last-Modified 就是安装包真实
上传 / 发布的时间（北京时间）。逐条推送调用 getXmsVer 拿链接，HEAD 取日期，
写回 xms_app.release_date，最后把 xms.push_date 归一为该版本最早的应用包日期。

用法：
    python3 scripts/backfill_xms_release_dates.py [--limit N]
"""
import argparse
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

import common  # noqa: E402
from miroms.constants import _const  # noqa: E402
from miroms.firmware import FirmwareParser  # noqa: E402
from miroms.utils import beijing_now  # noqa: E402


def head_date(url: str) -> str:
    """HEAD 取 Last-Modified，转北京时间日期；失败返回空串"""
    try:
        response = requests.head(url, allow_redirects=True, timeout=15)
        last_modified = response.headers.get("Last-Modified")
        if not last_modified:
            return ""
        dt = datetime.strptime(last_modified, "%a, %d %b %Y %H:%M:%S %Z") + timedelta(hours=8)
        return dt.strftime("%Y-%m-%d")
    except (requests.RequestException, ValueError):
        return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 条推送（调试用）")
    args = parser.parse_args()

    rows = common.DatabaseManager.query_all(
        "SELECT x.id, x.device, x.code, x.region, x.zone, x.android, x.version, "
        "       x.rom_version, r.branch "
        "FROM xms x LEFT JOIN roms r ON r.id = x.rom_id ORDER BY x.id"
    )
    if args.limit:
        rows = rows[: args.limit]

    tasks = []  # (xms_id, pkg, md5, urls)
    for xms_id, device, code, region, zone, android, version, rom_version, branch in rows:
        pkgs = [row[0] for row in common.DatabaseManager.query_all(
            "SELECT pkg FROM xms_app WHERE xms_id = %s AND pkg <> '' ORDER BY pkg",
            params=(xms_id,)
        )]
        if not pkgs:
            continue
        form = FirmwareParser.build_ota_form(
            device, code, region, branch or "F", zone, android, rom_version)
        android_short = str(form.get("c") or "").strip()
        if android_short.endswith(".0"):
            android_short = android_short[:-2]
        payload = {
            "b": form.get("b") or "F",
            "c": android_short,
            "d": form.get("d") or "",
            "f": "1",
            "l": form.get("l") or "zh_CN",
            "lsv": version,
            "r": form.get("r") or "",
            "id": "",
            "pkgs": [{"pkg": pkg, "pkgVer": "1"} for pkg in pkgs],
            "rv": rom_version or "",
        }
        result = None
        for attempt in range(1, 4):
            try:
                result = common.NetworkClient.call_api_form(
                    payload, url=_const.XMS_VER_URL,
                    extra={"n": str(uuid.uuid4()), "ts": str(int(beijing_now().timestamp() * 1000))}
                )
            except Exception as exc:
                print(f"  #{xms_id} {device} getXmsVer 失败（第 {attempt} 次）: {exc}")
                result = None
            if isinstance(result, dict) and result.get("apkLists"):
                break
            time.sleep(1.5)
        if not isinstance(result, dict) or not result.get("apkLists"):
            print(f"  #{xms_id} {device} {version} getXmsVer 无 apkLists，跳过")
            continue
        for apk in (result or {}).get("apkLists") or []:
            pkg = str(apk.get("packName") or "").strip()
            urls = [str(url) for url in (apk.get("downloadUrls") or []) if url]
            if pkg and urls:
                tasks.append((int(xms_id), pkg, str(apk.get("md5") or "").strip(), urls))
        print(f"  #{xms_id} {device} {version}: {len(pkgs)} 个包")

    print(f"待取 Last-Modified 的安装包：{len(tasks)} 个")

    cache = {}

    def resolve(task):
        xms_id, pkg, md5, urls = task
        if md5 and md5 in cache:
            return xms_id, pkg, cache[md5]
        date_text = head_date(urls[0])
        if md5 and date_text:
            cache[md5] = date_text
        return xms_id, pkg, date_text

    results = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for index, item in enumerate(pool.map(resolve, tasks), 1):
            results.append(item)
            if index % 100 == 0:
                print(f"  已解析 {index}/{len(tasks)}")

    updated = 0
    for xms_id, pkg, date_text in results:
        if not date_text:
            continue
        common.DatabaseManager.execute(
            "UPDATE xms_app SET release_date = %s WHERE xms_id = %s AND pkg = %s",
            params=(date_text, xms_id, pkg), raise_on_error=True
        )
        updated += 1

    print(f"已写入 release_date 的应用行：{updated}")
    changed = common.XmsStore.normalize_push_dates(apply=True)
    print(f"xms.push_date 归一：{changed} 行")
    print(common.DatabaseManager.query_all(
        "SELECT version, MIN(push_date), MAX(push_date) FROM xms GROUP BY version"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
