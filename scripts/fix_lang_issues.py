"""
fix_lang_issues.py - 按 logs.lang_issues 修正语言列（默认 dry-run）

`lang_issues` 是 AI 校对时写入的语言标注，例如：

    {"logs_de": {"detected": "英文", "confidence": 0.98, "reason": "Other 是英文"}}

本脚本按标注修正：

- 默认 correct：AI 给了 correct 且 confidence ≥ 阈值时，直接替换成正确译文；
- --mode translate：对没有可用 correct 的标注调用 AI 翻译回填，成功即清除该条 lang_issues；
- --mode hybrid：有正确译文则替换，否则清空；
- --mode clear：把不是该语言的列置 NULL；
- --mode move：如果 detected 能映射到另一个语言列且该列为空，则移动过去，否则清空；
- --clean-masks：对 module 行，同步把被清空语言在 roms/dev 掩码里的位去掉；
- logs_zh / logs_en 是核心列，默认不动，需要 --allow-core 才允许清空；
- 修正后同步清理 lang_issues，并把 proofed 重置为 0（需要重新校对）。

用法：
    python3 scripts/fix_lang_issues.py                     # 预览全部
    python3 scripts/fix_lang_issues.py --ids 1,165        # 只处理指定 logs.id
    python3 scripts/fix_lang_issues.py --apply            # 写库（先备份）
    python3 scripts/fix_lang_issues.py --mode move --apply
    python3 scripts/fix_lang_issues.py --clean-masks --apply
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.deepseek import DeepSeekClient, DeepSeekError
from miroms.logs_lang_fix import LogLangFixer
from miroms.logs_maintenance import LogMaintenance


def ts() -> str:
	return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def parse_ids(spec: str) -> list:
	ids = set()
	for chunk in (spec or '').split(','):
		chunk = chunk.strip()
		if not chunk:
			continue
		if '-' in chunk:
			start, end = chunk.split('-', 1)
			ids.update(range(int(start), int(end) + 1))
		else:
			ids.add(int(chunk))
	return sorted(ids)


def main() -> int:
	parser = argparse.ArgumentParser(description='按 logs.lang_issues 修正语言列（默认 dry-run）')
	parser.add_argument('--ids', help='只处理指定 logs.id，如 1,165 或 100-200')
	parser.add_argument('--mode', choices=('correct', 'translate', 'hybrid', 'clear', 'move'),
						default='correct',
						help='correct=用已有 correct 替换（默认）；translate=没有 correct 时调用 AI 翻译回填；'
							 'hybrid=无正确译文则清空；clear=清空；move=能映射到空语言列时移动')
	parser.add_argument('--max-calls', type=int, default=None,
						help='translate 模式最多调用多少次 AI（默认取 config.deepseek_max_calls）')
	parser.add_argument('--min-confidence', type=float, default=0.8,
						help='correct 替换所需的最低置信度（默认 0.8）')
	parser.add_argument('--allow-core', action='store_true',
						help='允许清空 logs_zh / logs_en（默认只报告不动）')
	parser.add_argument('--clean-masks', action='store_true',
						help='module 行被清空的语言同时从 roms/dev 引用掩码里去掉')
	parser.add_argument('--limit', type=int, default=0, help='最多处理多少行')
	parser.add_argument('--progress-every', type=int, default=1,
						help='每多少行打印一次进度（默认 1，translate 模式可看当前 id）')
	parser.add_argument('--apply', action='store_true', help='实际写库（默认预览）')
	parser.add_argument('--backup', help='备份路径（默认系统临时目录）')
	parser.add_argument('--no-backup', action='store_true')
	parser.add_argument('--json', help='把计划 / 结果写入 JSON')
	parser.add_argument('--restore-backup',
						help='从 fix_lang_issues 写库前的备份恢复被清空的列（只恢复当时标注过的列）')
	args = parser.parse_args()

	ids = parse_ids(args.ids) if args.ids else None
	rows = LogMaintenance.load_rows()

	if args.restore_backup:
		payload = json.loads(Path(args.restore_backup).read_text(encoding='utf-8'))
		restore = LogLangFixer.plan_restore(payload.get('rows', {}), rows, ids=ids)
		print(f"[{ts()}] 恢复计划：{restore['stats']['rows']} 行 / "
			  f"{restore['stats']['columns']} 列，跳过 {restore['stats']['skipped']}")
		for action in restore['actions'][:20]:
			print(f"  #{action['row_id']} 恢复 {sorted(action['set_columns'])}")
		for item in restore['skipped'][:10]:
			print(f"  跳过 #{item['row_id']}：{item['reason']}")
		if not args.apply:
			print('\n dry-run：加 --apply 执行恢复')
			return 0
		result = LogLangFixer.apply_restore(restore, apply=True,
											backup=not args.no_backup,
											backup_path=args.backup)
		if result.get('backup'):
			print(f"恢复前备份已写入 {result['backup']}")
		print(f"[{ts()}] 已恢复 {restore['stats']['rows']} 行 / {restore['stats']['columns']} 列；"
			  f"proofed / lang_issues 已重置，请重新跑 AI 校对生成 correct")
		print('下一步：python3 scripts/proofread_logs.py check --ids '
			  + ','.join(str(action['row_id']) for action in restore['actions']))
		return 0

	owners = LogMaintenance.load_owners() if args.clean_masks else None
	client = None
	if args.mode == 'translate':
		try:
			client = DeepSeekClient.from_config(max_calls=args.max_calls)
		except DeepSeekError as exc:
			print(f'✖ translate 模式无法启用 AI：{exc}')
			return 1
	incremental = bool(args.apply and args.mode == 'translate' and not args.clean_masks)
	backup_file = None
	applied = {'rows': 0, 'columns': 0}
	if incremental and not args.no_backup:
		backup_file = LogMaintenance.backup(args.backup)
		print(f"备份已写入 {backup_file}（增量写库前一次性备份）", flush=True)

	def progress(index, total, row_id):
		every = max(1, args.progress_every)
		if index == 1 or index % every == 0 or index == total:
			print(f"[{ts()}] 进度 {index}/{total} #{row_id} ...", flush=True)

	def apply_one(action):
		written = LogLangFixer.apply({'actions': [action], 'mask_updates': []},
									 apply=True, backup=False)
		applied['rows'] += written['rows']
		applied['columns'] += written['columns']
		print(f"  ✓ 写库 #{action['row_id']} {written['columns']} 列，"
			  f"剩余标注 {len(action['remaining_issues'])}", flush=True)

	plan = LogLangFixer.plan(rows, owners, ids=ids, mode=args.mode,
							 allow_core=args.allow_core,
							 clean_masks=args.clean_masks,
							 min_confidence=args.min_confidence, limit=args.limit,
							 client=client, on_progress=progress,
							 on_action=apply_one if incremental else None)
	print(f"[{ts()}] 计划：{plan['stats']['rows']} 行，"
		  f"correct {plan['stats'].get('corrected', 0)} 列，"
		  f"translate {plan['stats'].get('translated', 0)} 列，"
		  f"clear {plan['stats']['cleared']} 列，move {plan['stats']['moved']} 列，"
		  f"跳过 {plan['stats']['skipped']}，掩码更新 {plan['stats']['mask_updates']} 条")
	for action in plan['actions'][:20]:
		print(f"\n--- #{action['row_id']} [{action['type']}]")
		for detail in action['details']:
			target = f" → {detail['target']}" if detail['action'] == 'move' else ''
			correct = ''
			if detail['action'] in ('correct', 'translate'):
				correct = f" -> {detail.get('correct')!r}"
			print(f"    {detail['action']}: {detail['column']} "
				  f"(detected={detail['detected']!r}, {detail['confidence']}){target}{correct}")
		if action['remaining_issues']:
			print(f"    保留未处理标注：{sorted(action['remaining_issues'])}")
	if plan['skipped']:
		reasons = {}
		for item in plan['skipped']:
			reasons[item['reason']] = reasons.get(item['reason'], 0) + 1
		print(f"\n跳过：{reasons}")
	if args.json:
		Path(args.json).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
		print(f"计划已写入 {args.json}")
	if not args.apply:
		print('\n dry-run：确认无误后加 --apply 写库（写前自动备份）')
		return 0
	if incremental:
		print(f"[{ts()}] 已增量写库：{applied['rows']} 行 / {applied['columns']} 列；"
			  f"中断前的行已保存")
		return 0
	if not plan['actions'] and not plan['mask_updates']:
		print('没有需要修正的行')
		return 0
	result = LogLangFixer.apply(plan, apply=True, backup=not args.no_backup,
								backup_path=args.backup)
	if result.get('backup'):
		print(f"备份已写入 {result['backup']}")
	print(f"[{ts()}] 已写库：{plan['stats']['rows']} 行，"
		  f"替换 {plan['stats'].get('corrected', 0)} 列，"
		  f"清空 {plan['stats']['cleared']} 列，移动 {plan['stats']['moved']} 列，"
		  f"掩码更新 {plan['stats']['mask_updates']} 条")
	print('建议随后运行：python3 scripts/maintain_logs.py audit')
	print('如需确认导出影响：maintain_logs.py snapshot / compare')
	return 0


if __name__ == '__main__':
	sys.exit(main())
