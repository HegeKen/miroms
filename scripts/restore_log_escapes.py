"""
restore_log_escapes.py - 还原 logs 里旧 JSON 转义（^ / $$）

背景：旧代码写库前把 ``"`` 和 ``'`` 都替换成 ``^``，把 ``%`` 替换成 ``$$``。
现在按语言列存储，不再需要；本脚本做一次性还原：

    `$$` -> `%`
    `won^t` -> `won't`；`l^écran` -> `l'écran`
    `^Service & feedback^` -> `"Service & feedback"`
    `^^文本^^` -> `"文本"`

默认保留 proofed / complete / lang_issues（机械还原，不改语义）；需要重新校对加 --reset-flags。

用法：
    python3 scripts/restore_log_escapes.py                 # 预览
    python3 scripts/restore_log_escapes.py --limit 5       # 预览前 5 行
    python3 scripts/restore_log_escapes.py --apply         # 写库（写前备份）
    python3 scripts/restore_log_escapes.py --apply --reset-flags
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.logs_maintenance import LogMaintenance
from miroms.logs_restore import LogEscapeRestorer


def ts() -> str:
	return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def main() -> int:
	parser = argparse.ArgumentParser(description='还原 logs 里的旧转义字符（^ / $$）')
	parser.add_argument('--apply', action='store_true', help='实际写库（默认预览）')
	parser.add_argument('--reset-flags', action='store_true',
						help='还原后重置 proofed=0 / complete=0 / lang_issues=NULL')
	parser.add_argument('--limit', type=int, default=0, help='最多处理多少行')
	parser.add_argument('--samples', type=int, default=10, help='预览显示多少行')
	parser.add_argument('--backup', help='备份路径')
	parser.add_argument('--no-backup', action='store_true')
	parser.add_argument('--json', help='把计划写入 JSON')
	args = parser.parse_args()

	rows = LogMaintenance.load_rows()
	plan = LogEscapeRestorer.plan(rows, limit=args.limit, reset_flags=args.reset_flags)
	print(f"[{ts()}] 需要还原：{plan['stats']['rows']} 行 / {plan['stats']['columns']} 列"
		  f"（content {plan['stats']['content']} / 语言列 {plan['stats']['lang_columns']}）")
	for action in plan['actions'][:args.samples]:
		print(f"  #{action['row_id']} [{action['type']}]")
		if 'content' in action['changes']:
			print(f"    content: {action['content_before'][:120]!r}")
			print(f"          -> {action['changes']['content'][:120]!r}")
		for column, value in list(action['changes'].items())[:3]:
			if column == 'content':
				continue
			print(f"    {column}: {action['before'].get(column, '')[:120]!r}")
			print(f"          -> {value[:120]!r}")
	if len(plan['actions']) > args.samples:
		print(f"  ... 其余 {len(plan['actions']) - args.samples} 行")
	if args.json:
		Path(args.json).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
		print(f"计划已写入 {args.json}")
	if not args.apply:
		print('dry-run：加 --apply 写库（写前备份）')
		return 0
	result = LogEscapeRestorer.apply(plan, apply=True,
									 backup=not args.no_backup,
									 backup_path=args.backup)
	if result.get('backup'):
		print(f"备份已写入 {result['backup']}")
	print(f"[{ts()}] 已还原：{plan['stats']['rows']} 行 / {plan['stats']['columns']} 列"
		  f"{'；proofed/complete/lang_issues 已重置' if args.reset_flags else '；proofed/complete 保留'}")
	print('建议复检：python3 scripts/maintain_logs.py audit')
	return 0


if __name__ == '__main__':
	sys.exit(main())
