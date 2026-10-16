#!/usr/bin/env python3
"""把 hub 自身（web / admin）的更新日志按 git 记录导入 sitelog 表。

两个项目在 sitelog 表里各有独立的一条线：

* ``hub.web``   —— ``app/web``   的提交（导出为 ``api/v3/sitelog.json`` 的 ``sites['hub.web']``）
* ``hub.admin`` —— ``app/admin`` 的提交（admin 直连数据库读取）

仓库目前没有任何 git tag，因此版本号按**提交日期**分版：把每个项目在该路径下的提交
按作者日期（``--date=short``）分组，日期升序依次编号 ``V0.1.0``、``V0.2.0``…；
最新的一版即当前版本号。git 历史只会在末尾追加，所以既有版本号是稳定的。

提交标题会去掉对本项目冗余的前缀：``[web]`` / ``[admin]`` / ``[root]`` / ``[data]``
以及 ``feat(web):`` / ``fix(admin):`` 这类作用域，其余原样保留。
英文列只在标题本身不含中日韩字符时填同一份文本，否则留空——前端在译文缺失时回退中文。

用法::

    python3 scripts/import_hub_sitelog.py --dry-run   # 只看会写入什么
    python3 scripts/import_hub_sitelog.py             # 写入两个项目
    python3 scripts/import_hub_sitelog.py --site hub.web
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from miroms.sitelog_store import make_row, upsert_site  # noqa: E402
from miroms.utils import FileUtils  # noqa: E402

# 站点标识 -> 该站点在仓库中的代码路径
SITES: Dict[str, str] = {
	'hub.web': 'app/web',
	'hub.admin': 'app/admin',
}

# 提交标题里对本项目冗余的前缀：[web] / [admin][data] / [root] ...
_BRACKET_PREFIX = re.compile(r'^(\[[^\]]+\]\s*)+')
# 冗余作用域：feat(web): / fix(admin): / chore(root): / feat(data): / feat(android):
_REDUNDANT_SCOPE = re.compile(r'^(\w+)\((web|admin|root|data|android)\):\s*')
# 中日韩字符（含假名、韩文音节）——用于判断标题是否已经是英文
_CJK = re.compile(r'[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]')


def clean_subject(subject: str) -> str:
	"""去掉冗余的提交前缀，返回面向站点的标题。"""
	text = _BRACKET_PREFIX.sub('', subject or '').strip()
	text = _REDUNDANT_SCOPE.sub(r'\1: ', text)
	return text.strip()


def git_commits(repo_root: Path, rel_path: str) -> List[Tuple[str, str]]:
	"""读取某个路径下的提交，返回按日期升序的 [(YYYY-MM-DD, 标题), ...]。"""
	result = subprocess.run(
		['git', '-C', str(repo_root), 'log', '--date=short',
		 '--pretty=format:%ad\x1f%s', '--reverse', '--', rel_path],
		capture_output=True, text=True,
	)
	if result.returncode != 0:
		raise RuntimeError(f'git log 失败（{rel_path}）：{result.stderr.strip()}')
	commits: List[Tuple[str, str]] = []
	for line in result.stdout.splitlines():
		if '\x1f' not in line:
			continue
		day, subject = line.split('\x1f', 1)
		subject = clean_subject(subject)
		if day and subject:
			commits.append((day.strip(), subject))
	return commits


def build_rows(commits: List[Tuple[str, str]], drop_types: Tuple[str, ...] = ()) -> List[Dict]:
	"""按日期分组并顺序编号，返回 sitelog 行（sort_order 0 = 最新一版）。

	``drop_types`` 里的提交类型（``chore`` / ``build`` / ``docs`` 等）会被剔除，
	适合只把面向用户的功能与修复放进站点日志；某天的提交被剔除干净时该日期不留版本。
	"""
	grouped: Dict[str, List[str]] = {}
	for day, subject in commits:
		if drop_types and re.match(rf'^({"|".join(map(re.escape, drop_types))}):', subject):
			continue
		grouped.setdefault(day, []).append(subject)

	days = sorted(grouped)
	total = len(days)
	rows: List[Dict] = []
	for index, day in enumerate(days):
		logs = [
			{'zh': subject, 'en': '' if _CJK.search(subject) else subject}
			for subject in grouped[day]
		]
		rows.append(make_row(
			kind='entry',
			ver=f'V0.{index + 1}.0',
			log_date=date.fromisoformat(day),
			logs=logs,
			# 源站点日志的约定：sort_order 越小越靠前，0 = 最新
			sort_order=total - 1 - index,
		))
	return rows


def main() -> None:
	parser = argparse.ArgumentParser(description='按 git 记录导入 hub 自身（web / admin）的更新日志')
	parser.add_argument('--site', choices=sorted(SITES), help='只导入某个项目（默认两个都导入）')
	parser.add_argument('--drop-types', default='',
						help='剔除的提交类型，逗号分隔（如 chore,build,docs）；默认全部保留')
	parser.add_argument('--dry-run', action='store_true', help='只预览，不写库')
	args = parser.parse_args()

	drop_types = tuple(t.strip() for t in args.drop_types.split(',') if t.strip())

	repo_root = Path(FileUtils.get_base_path())
	if not (repo_root / '.git').exists():
		print(f'✗ 不是 git 仓库：{repo_root}', file=sys.stderr)
		sys.exit(1)

	sites = [args.site] if args.site else sorted(SITES)
	for site in sites:
		rel_path = SITES[site]
		commits = git_commits(repo_root, rel_path)
		rows = build_rows(commits, drop_types)
		print(f'--- {site} ({rel_path})：{len(commits)} 个提交 -> {len(rows)} 个版本 ---')
		if not rows:
			print('  ⚠ 没有提交记录，跳过')
			continue

		for row in rows:
			mark = '★' if row['sort_order'] == 0 else ' '
			print(f"  {mark} {row['ver']}  {row['log_date']}  {len(row['logs'])} 条")
			if args.dry_run:
				for item in row['logs']:
					print(f'      · {item["zh"]}')

		if args.dry_run:
			print('  （--dry-run，未写库）')
			continue
		stats = upsert_site(site, rows)
		print(f"    写入：新增 {stats['inserted']} 行、更新 {stats['updated']} 行、删除 {stats['removed']} 行")

	print('\n完成（--dry-run，未写库）' if args.dry_run else '\n完成')


if __name__ == '__main__':
	main()
