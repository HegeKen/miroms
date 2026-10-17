"""
push.py - 数据导出、提交推送并部署站点

流程:
1. 运行 sync_devices.py 同步机型数据
2. 运行 exporter.py 导出 API 数据
3. 提交并推送 data submodule（commit message 为当前日期时间，如 2026-08-24 16:21:16）
4. 调用 deploy.py 按 config.ids 依次触发站点部署（HUB / HyperOS.fans / MIUIer），
   站点之间默认停留 10 秒再触发下一个

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


def deploy_sites() -> None:
	"""触发 config.ids 中的全部站点部署，任一失败即中止流程"""
	if not deploy.deploy_all():
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

	# 5. 依次部署各站点（config.ids）
	print(f"\n[{now()}] 开始部署站点...")
	deploy_sites()

	print(f"\n[{now()}] 全部完成")


if __name__ == '__main__':
	main()
