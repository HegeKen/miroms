"""deploy.py - 触发 Cloudflare Pages 站点部署
"""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.error
import urllib.request

try:
	import config
except ModuleNotFoundError:
	sys.exit("✗ 找不到 scripts/config.py，请复制 scripts/config.py.back 并填写数据库与部署配置")

# 站点名称，顺序与 config.ids 一一对应（见 config.py 中的注释：HUB / HyperOS.fans / MIUIer）
SITE_NAMES = ("HUB", "HyperOS.fans", "MIUIer")
DEFAULT_TIMEOUT = 30
# 每个站点 hook 触发后停留的秒数，避免连续触发多个站点的部署
DEFAULT_INTERVAL = 10


def site_name(index: int) -> str:
	"""按序号取站点名；config.ids 比预设名称多时用「站点 N」兜底"""
	if index < len(SITE_NAMES):
		return SITE_NAMES[index]
	return f"站点{index + 1}"


def deploy_targets(selected=None) -> list[tuple[str, str]]:
	"""解析 config 中的部署目标，返回 [(站点名, deploy hook URL), ...]

	优先 ``api`` + ``ids``；两者缺失时回退旧配置 ``deploy_url`` / ``deploy_urls``。
	``selected`` 为站点名或 hook id 前缀列表（忽略大小写），为空表示全部。
	"""
	hook_ids = [
		str(hook_id).strip()
		for hook_id in (getattr(config, "ids", None) or [])
		if hook_id and str(hook_id).strip()
	]
	base_api = getattr(config, "api", None)

	targets: list[tuple[str, str]] = []
	if base_api and hook_ids:
		base = str(base_api).strip().rstrip("/")
		for index, hook_id in enumerate(hook_ids):
			targets.append((site_name(index), f"{base}/{hook_id}"))
	else:
		urls = getattr(config, "deploy_urls", None)
		if not urls:
			single = getattr(config, "deploy_url", None)
			urls = [single] if single else []
		for index, url in enumerate(urls):
			if url and str(url).strip():
				targets.append((site_name(index), str(url).strip()))

	if not selected:
		return targets

	wanted = [str(item).strip().lower() for item in selected if str(item).strip()]
	matched: list[tuple[str, str]] = []
	for name, url in targets:
		hook_id = url.rstrip("/").rsplit("/", 1)[-1].lower()
		if name.lower() in wanted or any(hook_id.startswith(item) for item in wanted):
			matched.append((name, url))
	return matched


def ssl_context() -> ssl.SSLContext:
	"""构造 TLS 上下文：优先用 certifi 的 CA（框架版 Python 常缺系统根证书）

	可通过 config.ca_bundle 指定自定义 CA bundle；未安装 certifi 时回退系统默认。
	"""
	ca_bundle = getattr(config, "ca_bundle", None)
	if ca_bundle and str(ca_bundle).strip():
		return ssl.create_default_context(cafile=str(ca_bundle).strip())
	try:
		import certifi
	except ImportError:
		return ssl.create_default_context()
	return ssl.create_default_context(cafile=certifi.where())


def post_hook(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict:
	"""POST 一个 Cloudflare deploy hook，返回解析后的 JSON"""
	request = urllib.request.Request(url, data=b"", method="POST")
	with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
		body = response.read().decode("utf-8", "replace")
	return json.loads(body)


def deploy_one(name: str, url: str, timeout: int = DEFAULT_TIMEOUT) -> bool:
	"""触发单个站点部署并打印结果，返回是否成功"""
	print(f"→ {name}: POST {url}", flush=True)
	try:
		response = post_hook(url, timeout)
	except urllib.error.HTTPError as error:
		detail = error.read().decode("utf-8", "replace").strip()
		print(f"✗ {name} 部署失败: HTTP {error.code} {detail}", flush=True)
		return False
	except urllib.error.URLError as error:
		print(f"✗ {name} 部署失败: {error.reason}", flush=True)
		return False
	except TimeoutError:
		print(f"✗ {name} 部署请求超时（{timeout}s）", flush=True)
		return False
	except json.JSONDecodeError:
		print(f"✗ {name} 部署失败: 无法解析返回的 JSON", flush=True)
		return False
	except Exception as error:  # noqa: BLE001 - 单个站点异常不应中断其余站点
		print(f"✗ {name} 部署失败: {error}", flush=True)
		return False

	if not response.get("success"):
		print(f"✗ {name} 部署失败: {response.get('errors') or '未知错误'}", flush=True)
		return False

	result = response.get("result") or {}
	details = f"ID: {result.get('id', '未知')}"
	if result.get("short_id"):
		details += f", short_id: {result['short_id']}"
	if result.get("url"):
		details += f", URL: {result['url']}"
	print(f"✓ {name} 部署已触发，{details}", flush=True)
	return True


def deploy_all(selected=None, timeout: int = DEFAULT_TIMEOUT, interval: int = DEFAULT_INTERVAL) -> bool:
	"""依次触发所有目标站点部署，返回是否全部成功

	每个 hook 触发后停留 ``interval`` 秒（默认 10s）再触发下一个站点；
	``interval=0`` 表示不等待。失败不会中断后续站点，只影响最终返回值。
	"""
	targets = deploy_targets(selected)
	if not targets:
		print("✗ 没有可部署的站点，请检查 scripts/config.py 中的 api / ids", flush=True)
		return False

	print(f"共 {len(targets)} 个站点待部署: {', '.join(name for name, _ in targets)}", flush=True)
	ok = 0
	for index, (name, url) in enumerate(targets):
		if deploy_one(name, url, timeout):
			ok += 1
		if index < len(targets) - 1 and interval > 0:
			print(f"⏳ 停留 {interval}s 后触发下一个站点: {targets[index + 1][0]}", flush=True)
			time.sleep(interval)
	print(f"\n部署结果: {ok}/{len(targets)} 成功", flush=True)
	return ok == len(targets)


def main(argv: list[str]) -> int:
	selected: list[str] = []
	timeout = DEFAULT_TIMEOUT
	interval = DEFAULT_INTERVAL
	show_list = False

	args = list(argv)
	while args:
		arg = args.pop(0)
		if arg in ("-h", "--help"):
			print(__doc__)
			return 0
		if arg == "--list":
			show_list = True
		elif arg == "--timeout":
			if not args:
				print("✗ --timeout 需要参数（秒）", file=sys.stderr)
				return 1
			try:
				timeout = int(args.pop(0))
			except ValueError:
				print("✗ --timeout 需要整数秒", file=sys.stderr)
				return 1
		elif arg == "--interval":
			if not args:
				print("✗ --interval 需要参数（秒，0 表示不等待）", file=sys.stderr)
				return 1
			try:
				interval = max(0, int(args.pop(0)))
			except ValueError:
				print("✗ --interval 需要整数秒", file=sys.stderr)
				return 1
		elif arg.startswith("-"):
			print(f"✗ 未知参数: {arg}（用 --help 查看用法）", file=sys.stderr)
			return 1
		else:
			selected.append(arg)

	if show_list:
		targets = deploy_targets(selected)
		if not targets:
			print("✗ 没有匹配的部署目标", file=sys.stderr)
			return 1
		for name, url in targets:
			print(f"{name}\t{url}")
		return 0

	return 0 if deploy_all(selected, timeout, interval) else 1


if __name__ == "__main__":
	sys.exit(main(sys.argv[1:]))
