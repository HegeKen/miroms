"""
fix_mixed_translations.py - mixed_translations 两步修复规划器

默认只读：扫描当前行（或指定 id / decisions）重新判定 mixed_translations，然后：

第一步：把中文翻译成英文，按英文/中文相似度找候选行，AI 判断是否同一内容；
        一致 -> 生成 merge 计划（删除 mixed 行，引用改到候选行）。
第二步：不一致 -> AI 把语言按语义聚簇，生成 split 计划，并按引用掩码与各簇语言集的
        交集选择簇；冲突位置标记待人工，不自动拆分。

用法：
    python3 scripts/fix_mixed_translations.py --ids 760,1483,1611        # 只扫描这些行
    python3 scripts/fix_mixed_translations.py --scan --limit 500          # 扫描当前多语言行
    python3 scripts/fix_mixed_translations.py --scan --include-proofed
    python3 scripts/fix_mixed_translations.py --decisions /tmp/d.json     # 复用已校验 decisions
    python3 scripts/fix_mixed_translations.py --ids 760 --apply-merges    # 执行 merge 计划

注意：旧 decisions 的 row_id 可能已过期；本脚本会按 current_zh + type 校验，过期的跳过。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.deepseek import DeepSeekClient, DeepSeekError
from miroms.logs_maintenance import LogMaintenance
from miroms.logs_mixed import MixedTranslationFixer
from miroms.logs_proofread import LogProofreader
from miroms.logs_store import LogStore


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
	parser = argparse.ArgumentParser(description='mixed_translations 两步修复规划器（默认只读）')
	parser.add_argument('--ids', help='只扫描这些 logs.id，如 760,1483 或 100-200')
	parser.add_argument('--scan', action='store_true', help='扫描当前所有多语言行（耗时/耗 token）')
	parser.add_argument('--decisions', help='已有 decisions JSON（会校验是否与当前行一致）')
	parser.add_argument('--types', default='module,log', help='module,log')
	parser.add_argument('--min-langs', type=int, default=2, help='扫描时最少语言数，默认 2')
	parser.add_argument('--limit', type=int, default=0, help='最多扫描多少行')
	parser.add_argument('--include-proofed', action='store_true', help='连 proofed 行一起扫描')
	parser.add_argument('--batch-size', type=int, default=10, help='扫描批次大小')
	parser.add_argument('--min-confidence', type=float, default=0.8, help='AI 判定 same 的最低置信度')
	parser.add_argument('--max-candidates', type=int, default=5, help='每行最多比较多少个候选')
	parser.add_argument('--cache', help='扫描缓存 JSON')
	parser.add_argument('--decisions-out', help='把扫描得到的 decisions 写入 JSON')
	parser.add_argument('--prune-stale', action='store_true',
						help='过滤掉与当前行不匹配的过期 decisions（可用 --decisions-out 另存）')
	parser.add_argument('--prune-only', action='store_true',
						help='只校验并删除过期 decisions，不扫描、不调 AI')
	parser.add_argument('--json', help='把修复计划写入 JSON')
	parser.add_argument('--apply-merges', action='store_true', help='执行第一步 merge 计划')
	parser.add_argument('--apply-splits', action='store_true',
						help='执行第二步 split 计划（有歧义引用的行会跳过）')
	parser.add_argument('--backup', help='merge 前备份路径')
	parser.add_argument('--no-backup', action='store_true')
	parser.add_argument('--samples', type=int, default=10)
	args = parser.parse_args()

	ids = parse_ids(args.ids) if args.ids else None
	if not (ids or args.scan or args.decisions):
		print('✖ 需要 --ids / --scan / --decisions 之一')
		return 2
	types = tuple(item.strip() for item in args.types.split(',') if item.strip())
	rows = LogMaintenance.load_rows()
	owners = LogMaintenance.load_owners()
	client = None
	if not args.prune_only:
		try:
			client = DeepSeekClient.from_config()
		except DeepSeekError as exc:
			print(f'✖ 无法启用 AI：{exc}')
			return 1
	decisions = []
	if args.decisions:
		payload = json.loads(Path(args.decisions).read_text(encoding='utf-8'))
		decisions = payload.get('decisions', payload) if isinstance(payload, dict) else payload
		decisions = [item for item in decisions if item.get('verdict') == 'mixed_translations']
		print(f"[{ts()}] 载入 decisions：{len(decisions)} 条 mixed")
	elif ids:
		result = LogProofreader.inspect(ids, rows, owners, client=client, force=True)
		decisions = [item['decision'] for item in result['rows']
					 if item.get('decision') and item['decision'].get('verdict') == 'mixed_translations']
		print(f"[{ts()}] 扫描 {len(ids)} 行，mixed {len(decisions)} 条")
	else:
		selected, _known, batches = LogProofreader.prepare_batches(
			rows, owners, batch_size=args.batch_size, min_langs=args.min_langs,
			types=types, limit=args.limit, include_proofed=args.include_proofed)
		print(f"[{ts()}] 扫描 {len(selected)} 行 / {len(batches)} 批 ...")

		def progress(index, total, batch, cached):
			if index == 1 or index % 20 == 0 or index == total:
				print(f"  批次 {index}/{total}（{batch['type']}）{'缓存' if cached else ''}")

		result = LogProofreader.batch_review(
			rows, owners, client, batch_size=args.batch_size,
			include_single=False, min_langs=args.min_langs, types=types,
			limit=args.limit, cache_path=args.cache, on_progress=progress,
			include_proofed=args.include_proofed)
		decisions = [item for item in result['decisions']
					 if item.get('verdict') == 'mixed_translations']
		print(f"[{ts()}] 扫描完成：mixed {len(decisions)} 条")

	if args.prune_stale or args.prune_only:
		if not args.decisions:
			print('✖ --prune-stale/--prune-only 需要 --decisions')
			return 2
		decisions, stale = MixedTranslationFixer.validate_decisions(decisions, rows)
		print(f"[{ts()}] 过期 decisions 已过滤：保留 {len(decisions)}，删除 {len(stale)}")
		target = args.decisions_out or args.decisions
		if target:
			Path(target).write_text(
				json.dumps(decisions, ensure_ascii=False, indent=2), encoding='utf-8')
			print(f'干净 decisions 已写入 {target}')
		if args.prune_only:
			return 0

	if args.decisions_out:
		Path(args.decisions_out).write_text(
			json.dumps(decisions, ensure_ascii=False, indent=2), encoding='utf-8')
		print(f'decisions 已写入 {args.decisions_out}')

	if not decisions:
		print('没有 mixed_translations 行')
		return 0
	plan = MixedTranslationFixer.plan(decisions, rows, owners, client,
									  min_confidence=args.min_confidence,
									  max_candidates=args.max_candidates)
	print(f"[{ts()}] 计划：merge {plan['stats']['merge']}，split {plan['stats']['split']}，"
		  f"manual {plan['stats']['manual']}，歧义引用 {plan['stats']['ambiguous']}；"
		  f"过期 decisions 跳过 {plan['stale']}")
	for action in plan['actions'][:args.samples]:
		print(f"\n#{action['row_id']} [{action['type']}] {action['action']}  en={action.get('en')!r}")
		if action['action'] == 'merge':
			print(f"  -> 合并到 #{action['target_id']} ({action['confidence']}) {action.get('reason', '')}")
		elif action['action'] == 'split':
			for cluster in action['clusters']:
				print(f"  簇 {cluster['langs']} zh={cluster['zh']!r} en={cluster['en']!r}")
			for item in action['routing']:
				print(f"  路由 {item['table']}#{item['owner_id']} pos={item['position']} "
					  f"-> 簇 {item['cluster']}")
			for item in action['ambiguous']:
				print(f"  ⚠ 歧义 {item['table']}#{item['owner_id']} pos={item['position']} mask={item['mask']}")
		else:
			print(f"  {action.get('reason')}")
	if args.json:
		Path(args.json).write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding='utf-8')
		print(f'计划已写入 {args.json}')

	if args.apply_merges:
		applied = MixedTranslationFixer.apply_merges(
			plan, rows, apply=True, backup=not args.no_backup, backup_path=args.backup)
		if applied.get('backup'):
			print(f"备份已写入 {applied['backup']}")
		print(f"[{ts()}] merge 执行：{applied['rows']} 行")
	if args.apply_splits:
		applied = MixedTranslationFixer.apply_splits(
			plan, rows, owners, client, apply=True,
			backup=not args.no_backup, backup_path=args.backup,
			min_confidence=args.min_confidence)
		if applied.get('backup'):
			print(f"备份已写入 {applied['backup']}")
		print(f"[{ts()}] split 执行：{applied['rows']} 行，新建 {applied['new_rows']} 行；"
			  f"跳过歧义 {applied['skipped_ambiguous']} 行")
	if not (args.apply_merges or args.apply_splits):
		print('\n只读规划完成；merge 加 --apply-merges，split 加 --apply-splits。')
	return 0


if __name__ == '__main__':
	sys.exit(main())
