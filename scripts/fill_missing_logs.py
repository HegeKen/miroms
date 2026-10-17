"""
fill_missing_logs.py - 为 proofed 行排查缺失语言并 AI 翻译回填（默认只盘点）

用法：
    python3 scripts/fill_missing_logs.py                    # 列出 proofed 行缺失语言 + token 估算
    python3 scripts/fill_missing_logs.py --ids 23           # 只看指定行
    python3 scripts/fill_missing_logs.py --expected owners  # 只补引用里实际出现的语言
    python3 scripts/fill_missing_logs.py --langs logs_de,logs_fr
    python3 scripts/fill_missing_logs.py --run              # 调 AI 预览，不写库
    python3 scripts/fill_missing_logs.py --apply            # 调 AI 并写库（每行即时写，写前备份）
    python3 scripts/fill_missing_logs.py --apply --atomic   # 全部跑完再统一写
    python3 scripts/fill_missing_logs.py --apply --keep-proofed

回填后默认 proofed=0（新增译文需要重新校对）；--keep-proofed 且没有剩余
lang_issues 时保留 proofed=1。
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.deepseek import DeepSeekClient, DeepSeekError
from miroms.logs_fill import LogFiller
from miroms.logs_maintenance import LogMaintenance
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
	parser = argparse.ArgumentParser(description='proofed 行缺失语言 AI 翻译回填（默认只盘点）')
	parser.add_argument('--ids', help='只处理指定 logs.id，如 23,253 或 100-200')
	parser.add_argument('--types', default='module,log', help='类型，默认 module,log')
	parser.add_argument('--expected', choices=('all', 'owners'), default='all',
						help='期望语言：all=全部语言列（默认）；owners=该行引用里出现过的语言')
	parser.add_argument('--langs', help='只补这些语言列，逗号分隔，如 logs_de,logs_fr')
	parser.add_argument('--include-unproofed', action='store_true',
						help='连未 proofed 的行一起处理（默认只处理 proofed=1）')
	parser.add_argument('--offset', type=int, default=0,
						help='跳过前 N 行（分批运行用，默认 0）')
	parser.add_argument('--limit', type=int, default=0, help='最多处理多少行')
	parser.add_argument('--min-confidence', type=float, default=0.8,
						help='写入所需的最低置信度（默认 0.8）')
	parser.add_argument('--max-calls', type=int, default=None,
						help='本次最多调用多少次 API（默认取 config.deepseek_max_calls）')
	parser.add_argument('--run', action='store_true', help='调用 AI 预览，不写库')
	parser.add_argument('--apply', action='store_true', help='调用 AI 并写库（默认 dry-run）')
	parser.add_argument('--atomic', action='store_true',
						help='全部跑完再统一写库（旧行为）；默认每行拿到译文就立即写入')
	parser.add_argument('--keep-proofed', action='store_true',
						help='回填后保留 proofed=1（仅当没有剩余 lang_issues）')
	parser.add_argument('--cache', help='AI 结果缓存 JSON（可按行增量保存）')
	parser.add_argument('--decisions', help='把结果写入 JSON')
	parser.add_argument('--json', help='把估算 / 结果写入 JSON')
	parser.add_argument('--backup', help='写库前备份路径')
	parser.add_argument('--no-backup', action='store_true')
	parser.add_argument('--show', type=int, default=20, help='预览显示多少行（默认 20）')
	args = parser.parse_args()

	types = tuple(item.strip() for item in args.types.split(',') if item.strip())
	langs = [item.strip() for item in args.langs.split(',') if item.strip()] if args.langs else None
	ids = parse_ids(args.ids) if args.ids else None
	if langs:
		unknown = [item for item in langs if item not in LogStore.LANG_COLUMNS]
		if unknown:
			print(f'✖ 未知语言列：{unknown}')
			return 2

	rows = LogMaintenance.load_rows()
	owners = LogMaintenance.load_owners() if args.expected == 'owners' else None
	items = LogFiller.missing_rows(rows, owners, ids=ids, expected=args.expected,
								   langs=langs, types=types,
								   include_unproofed=args.include_unproofed,
								   offset=args.offset, limit=args.limit)
	estimate = LogFiller.estimate(items)
	scope = '全部行' if args.include_unproofed else 'proofed 行'
	print(f"[{ts()}] {scope}缺失语言：{estimate['rows']} 行 / {estimate['columns']} 列，"
		  f"预计 {estimate['calls']} 次调用，约 {estimate['total_tokens'] / 10000:.1f} 万 tokens")
	for item in items[:args.show]:
		print(f"  #{item['row_id']} [{item['type']}] {item['content']!r} "
			  f"缺 {len(item['missing'])}：{','.join(item['missing'])}")
	if len(items) > args.show:
		print(f"  ... 其余 {len(items) - args.show} 行")
	if args.json:
		Path(args.json).write_text(json.dumps(
			{'estimate': estimate, 'items': items}, ensure_ascii=False, indent=2),
			encoding='utf-8')
		print(f'估算已写入 {args.json}')
	if not items:
		print('没有需要回填的行')
		return 0
	if not (args.run or args.apply):
		print('\n只盘点，未调用 AI。确认后加 --run 预览，或 --apply 写库。')
		return 0

	try:
		client = DeepSeekClient.from_config(max_calls=args.max_calls)
	except DeepSeekError as exc:
		print(f'✖ 无法启用 AI：{exc}')
		return 1

	backup_file = None
	incremental = args.apply and not args.atomic
	if incremental and not args.no_backup:
		backup_file = LogMaintenance.backup(args.backup)
		print(f"备份已写入 {backup_file}（增量写库前一次性备份）")
	applied = {'rows': 0, 'columns': 0, 'complete': 0}

	def show(index, total, result):
		print(f"[{ts()}] {index}/{total} #{result['row_id']} "
			  f"{'缓存' if result.get('cached') else 'AI'}"
			  f"{' 失败: ' + result['error'] if result.get('error') else ''}")
		for column, detail in result.get('translations', {}).items():
			print(f"    {column} = {detail['text']!r} ({detail['confidence']:.2f})")
		if incremental:
			written = LogFiller.apply([result], rows, apply=True,
									  keep_proofed=args.keep_proofed,
									  backup=False)
			applied['rows'] += written['rows']
			applied['columns'] += written['columns']
			applied['complete'] += written.get('complete', 0)

	results = LogFiller.run(items, client, min_confidence=args.min_confidence,
							cache_path=args.cache, on_row=show)
	translated = sum(len(result['translations']) for result in results)
	errors = [result for result in results if result.get('error')]
	print(f"[{ts()}] 完成：{len(results)} 行，得到 {translated} 条译文，"
		  f"{len(errors)} 行调用失败")
	if args.decisions:
		Path(args.decisions).write_text(
			json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
		print(f'结果已写入 {args.decisions}')
	if not args.apply:
		print('\n预览完成，未写库。确认后加 --apply。')
		return 1 if errors else 0
	if args.atomic:
		applied = LogFiller.apply(results, rows, apply=True,
								  keep_proofed=args.keep_proofed,
								  backup=not args.no_backup, backup_path=args.backup)
		if applied.get('backup'):
			print(f"备份已写入 {applied['backup']}")
	elif backup_file:
		print(f"增量写库使用备份 {backup_file}")
	print(f"[{ts()}] 已回填：{applied['rows']} 行 / {applied['columns']} 列；"
		  f"complete={applied.get('complete', 0)} 行，"
		  f"proofed {'保留=1' if args.keep_proofed else '重置=0'}"
		  f"{'（每行即时写库）' if incremental else '（全部完成后统一写库）'}")
	if not args.keep_proofed:
		print('建议复检：python3 scripts/proofread_logs.py check --ids '
			  + ','.join(str(result['row_id']) for result in results[:20]))
	return 1 if errors else 0


if __name__ == '__main__':
	sys.exit(main())
