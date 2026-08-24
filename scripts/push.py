"""
push.py - 数据导出、提交推送并部署站点

流程:
1. 运行 exporter.py 导出 API 数据
2. 提交并推送 data submodule（commit message 为当前日期时间，如 2026-08-24 16:21:16）
3. 运行 deploy.py 触发站点部署
"""
import subprocess
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent
EXPORTER = SCRIPT_DIR / 'exporter.py'
DEPLOY = SCRIPT_DIR / 'deploy.py'


def run(cmd, cwd=None, check=False):
	"""运行命令，输出实时日志；check 为 True 时失败即退出"""
	print(f"\n$ {' '.join(cmd)}", flush=True)
	result = subprocess.run(cmd, cwd=cwd, text=True)
	if result.returncode != 0 and check:
		print(f"✗ 命令执行失败: {' '.join(cmd)}", file=sys.stderr)
		sys.exit(1)
	return result.returncode == 0


def main() -> None:
	# 1. 导出数据
	print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始导出数据...")
	run([sys.executable, str(EXPORTER)], check=True)

	# 2. 检查 data submodule 是否有变更，无变更则结束（不提交、不部署）
	status = subprocess.run(
		['git', 'status', '--porcelain'],
		cwd=DATA_DIR, capture_output=True, text=True
	).stdout.strip()
	if not status:
		print("data submodule 无文件变更，跳过提交、推送与站点更新")
		return

	# 3. 提交并推送 data submodule
	msg = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
	print(f"\n[{msg}] 提交 data submodule...")
	run(['git', 'add', '-A'], cwd=DATA_DIR, check=True)
	run(['git', 'commit', '-m', msg], cwd=DATA_DIR, check=True)
	run(['git', 'push'], cwd=DATA_DIR, check=True)

	# 4. 部署站点
	print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始部署站点...")
	run([sys.executable, str(DEPLOY)], check=True)

	print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 全部完成")


if __name__ == '__main__':
	main()
