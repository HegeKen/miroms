#!/usr/bin/env python3
"""由 launchd 定时调用，顺序执行 .vscode/tasks.json 中 run-all-jobs 包含的全部脚本。

工作目录设为项目根目录，与 VS Code 中执行 task 的行为保持一致。
"""

import os
import subprocess
import sys
from datetime import datetime

PROJECT_ROOT = "/Users/hegeken/Desktop/Codes/hub.miuier.com"
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "data", "scripts")

# 与 tasks.json run-all-jobs 的 dependsOn 列表一致
SCRIPTS = [
	"get_new_branch.py",
	"ota_former.py",
	"ota_full.py",
	"xfu_full.py",
	"mgc_fastboot.py",
	"get_current_fastboot.py",
	"aspatch.py",
	"fetch_changelog.py",
]


def now():
	return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main():
	os.chdir(PROJECT_ROOT)
	print(f"===== {now()} run-all-jobs 开始 =====", flush=True)
	for script in SCRIPTS:
		path = os.path.join(SCRIPTS_DIR, script)
		print(f"----- {now()} 开始执行 {script} -----", flush=True)
		result = subprocess.run([sys.executable, path], cwd=PROJECT_ROOT)
		print(f"----- {now()} {script} 结束，退出码: {result.returncode} -----", flush=True)
	print(f"===== {now()} run-all-jobs 全部结束 =====", flush=True)


if __name__ == "__main__":
	main()
