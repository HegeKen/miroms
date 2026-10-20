"""
push.py - 数据导出、提交推送并部署站点

流程:
1. 运行 sync_devices.py 同步机型数据
2. 运行 exporter.py 导出 API 数据
3. 提交并推送 data submodule（commit message 为当前日期时间，如 2026-08-24 16:21:16）
4. 按变更的 API 目录触发对应站点部署：
   api/v1 → MIUIer、api/v2 → HyperOS.fans、api/v3 → HUB，
   只有对应目录有变更的站点才会更新；站点之间默认停留 10 秒再触发下一个

部署目标与 hook id 全部维护在 scripts/config.py（``api`` + ``ids``），
本脚本不再关心具体地址；任一站点部署失败则以非 0 退出码结束。
"""
import subprocess
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent
SYNC = SCRIPT_DIR / 'sync_devices.py'
EXPORTER = SCRIPT_DIR / 'exporter.py'

# 把 scripts/ 放进 sys.path，保证任意工作目录下都能 import deploy（进而读到 config.py）
if str(SCRIPT_DIR) not in sys.path:
	sys.path.insert(0, str(SCRIPT_DIR))

import deploy  # noqa: E402  (依赖上面的 sys.path 注入)

# API 目录 → 站点名（站点名需与 deploy.SITE_NAMES 一致）
SITE_BY_API_DIR = {
	'v1': 'MIUIer',
	'v2': 'HyperOS.fans',
	'v3': 'HUB',
}


def now() -> str:
	return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def run(cmd, cwd=None, check=False):
	"""运行命令，输出实时日志；check 为 True 时失败即退出"""
	print(f"\n$ {' '.join(cmd)}", flush=True)
	result = subprocess.run(cmd, cwd=cwd, text=True)
	if result.returncode != 0 and check:
		print(f"✗ 命令执行失败: {' '.join(cmd)}", file=sys.stderr)
		sys.exit(1)
	return result.returncode == 0


def parse_status_paths(porcelain: str) -> list[str]:
	"""从 git status --porcelain 输出中提取变更文件路径（相对 DATA_DIR）"""
	paths = []
	for line in porcelain.splitlines():
		if len(line) < 4:
			continue
		path = line[3:].strip()
		if ' -> ' in path:  # 重命名：取新路径
			path = path.split(' -> ', 1)[1]
		path = path.strip('"')
		if path:
			paths.append(path)
	return paths


def changed_sites(porcelain: str) -> list[str]:
	"""按变更的 api/vN 目录返回需要更新的站点列表（保持 v1/v2/v3 顺序）"""
	changed_dirs = set()
	for path in parse_status_paths(porcelain):
		parts = path.split('/')
		if len(parts) >= 2 and parts[0] == 'api' and parts[1] in SITE_BY_API_DIR:
			changed_dirs.add(parts[1])
	return [SITE_BY_API_DIR[api_dir] for api_dir in SITE_BY_API_DIR if api_dir in changed_dirs]


def deploy_sites(sites) -> None:
	"""触发指定站点部署，任一失败即中止流程"""
	if not sites:
		print("api/v1、api/v2、api/v3 均无变更，跳过站点更新")
		return
	print(f"检测到变更的 API 目录，待更新站点: {', '.join(sites)}")
	if not deploy.deploy_all(sites):
		print("✗ 站点部署失败", file=sys.stderr)
		sys.exit(1)


def main() -> None:
	# 1. 同步机型数据
	print(f"\n[{now()}] 开始同步机型数据...")
	run([sys.executable, str(SYNC)], check=True)

	# 2. 导出数据
	print(f"\n[{now()}] 开始导出数据...")
	run([sys.executable, str(EXPORTER)], check=True)

	# 3. 检查 data submodule 是否有变更，无变更则结束（不提交、不部署）
	status = subprocess.run(
		['git', 'status', '--porcelain'],
		cwd=DATA_DIR, capture_output=True, text=True
	).stdout.strip()
	if not status:
		print("data submodule 无文件变更，跳过提交、推送与站点更新")
		return

	# 4. 提交并推送 data submodule
	msg = now()
	print(f"\n[{msg}] 提交 data submodule...")
	run(['git', 'add', '-A'], cwd=DATA_DIR, check=True)
	run(['git', 'commit', '-m', msg], cwd=DATA_DIR, check=True)
	run(['git', 'push'], cwd=DATA_DIR, check=True)

	# 5. 依次部署有变更的站点（按 api/vN 目录决定）
	print(f"\n[{now()}] 开始部署站点...")
	deploy_sites(changed_sites(status))

	print(f"\n[{now()}] 全部完成")


if __name__ == '__main__':
	main()
