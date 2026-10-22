"""
local_lang_check.py - 用本地模型 (LM Studio / Hunyuan-MT-7B) 校验译文语言

用途：
  1) check  逐条判断「译文是否真的用该列语言书写」，不符的写入 logs.lang_issues；
  2) fix    对已标注的行，用本地模型把中文重新翻译成目标语言并替换；
  3) calibrate  在 proofed 行上采样，输出各语言的回译相似度分布，用于调阈值。

判定方式（本地、不联网）：
  - 规则层：文字体系不符 / 与 logs_en 完全相同 / 简繁转换改写 / 俄乌字母特征；
  - 模型层：把文本翻译成它「本应使用的语言」，再与原文比相似度（回译不变性）。
    本来是德语 -> 译回德语仍然几乎一样；是英语回落 -> 会变成明显不同的德语。

常用命令：

    # 预览（会调用模型，但不写库）
    python3 scripts/local_lang_check.py check --ids 696,5135,4201,56 --run

    # 写库标注（写前自动备份）
    python3 scripts/local_lang_check.py check --ids 696,5135 --apply

    # 全量校对（4k+ 行 / 6.5w 单元格；建议后台跑，带缓存可断点续跑）
    python3 scripts/local_lang_check.py check --all --apply --workers 2 \
        --cache /tmp/langcheck_cache.json --report /tmp/langcheck_report.json

    # 对标注过的行替换译文（默认预览，--apply 写库）
    python3 scripts/local_lang_check.py fix --all --run
    python3 scripts/local_lang_check.py fix --all --apply

    # 阈值校准
    python3 scripts/local_lang_check.py calibrate --sample 60
"""
import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent))

from miroms.local_langcheck import (
	DEFAULT_LONG_RATIO,
	DEFAULT_SHORT_RATIO,
	SHORT_CHARS,
	LangChecker,
	detector_issue,
	is_trivial,
	lang_label,
	rule_issue,
)
from miroms.local_mt import (
	LANG_TARGETS,
	LocalMTClient,
	LocalMTError,
	has_han,
	similarity,
	validate_translation,
)
from miroms.logs_fill import LogFiller
from miroms.logs_maintenance import LogMaintenance
from miroms.logs_store import LogStore

CHECK_COLUMNS = [column for column in LogStore.LANG_COLUMNS if column != 'logs_zh']


def ts() -> str:
	return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def parse_ids(spec: str) -> List[int]:
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


def parse_langs(spec: Optional[str]) -> List[str]:
	if not spec:
		return list(CHECK_COLUMNS)
	columns = [item.strip() for item in str(spec).split(',') if item.strip()]
	unknown = [column for column in columns if column not in LogStore.LANG_COLUMNS]
	if unknown:
		raise SystemExit(f'✖ 未知语言列：{", ".join(unknown)}')
	return columns


def write_json(path: Optional[str], payload: Dict[str, Any]) -> None:
	if not path:
		return
	target = Path(path)
	target.parent.mkdir(parents=True, exist_ok=True)
	target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
	print(f'已写入 {target}')


def load_cache(path: Optional[str]) -> Dict[str, str]:
	if not path:
		return {}
	file = Path(path)
	if not file.exists():
		return {}
	try:
		data = json.loads(file.read_text(encoding='utf-8'))
	except (json.JSONDecodeError, OSError):
		return {}
	return data if isinstance(data, dict) else {}


def save_cache(path: Optional[str], cache: Dict[str, str]) -> None:
	if not path:
		return
	Path(path).write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')


def select_rows(rows: Dict[int, Dict[str, Any]], args) -> List[Dict[str, Any]]:
	types = {item.strip() for item in str(args.types).split(',') if item.strip()}
	ids = set(parse_ids(args.ids)) if args.ids else None
	selected = []
	for row_id in sorted(rows):
		row = rows[row_id]
		if ids is not None and row_id not in ids:
			continue
		if row['type'] not in types:
			continue
		if args.skip_proofed and row.get('proofed'):
			continue
		selected.append(row)
	if args.offset:
		selected = selected[args.offset:]
	if args.limit:
		selected = selected[:args.limit]
	return selected


def build_cells(rows: List[Dict[str, Any]], langs: List[str]) -> List[Dict[str, Any]]:
	cells = []
	for row in rows:
		en_text = LogStore.normalize(row['texts'].get('logs_en'))
		for column in langs:
			if column == 'logs_zh':
				continue
			text = LogStore.normalize(row['texts'].get(column))
			if not text or is_trivial(text):
				continue
			cells.append({'row_id': row['id'], 'column': column, 'text': text,
						  'en': en_text, 'issue': None, 'ratio': None})
	return cells


# ==================== check ====================

def run_check(rows, args, client) -> Dict[str, Any]:
	langs = parse_langs(args.langs)
	selected = select_rows(rows, args)
	cells = build_cells(selected, langs)
	print(f'[{ts()}] 载入 {len(rows)} 行，选中 {len(selected)} 行，待校验 {len(cells)} 个单元格')

	# 1) 规则层 + 本地语种识别
	pending = []
	rule_hits = 0
	detector_hits = 0
	for cell in cells:
		issue = rule_issue(cell['column'], cell['text'], cell['en'])
		if issue:
			cell['issue'] = issue
			rule_hits += 1
			continue
		if args.detector == 'hybrid':
			issue = detector_issue(cell['column'], cell['text'])
			if issue:
				cell['issue'] = issue
				detector_hits += 1
				continue
		if args.detector == 'lm' and not args.rules_only:
			pending.append(cell)
	print(f'  规则命中 {rule_hits}，语种识别命中 {detector_hits}，交给翻译模型 {len(pending)}')

	# 2) 模型层：同语言分组合批
	groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
	for cell in pending:
		if args.rules_only:
			continue
		groups[cell['column']].append(cell)

	checker = LangChecker(
		client, long_ratio=args.long_ratio, short_ratio=args.short_ratio,
		short_chars=args.short_chars, batch_size=args.batch_size,
		workers=1, cache=load_cache(args.cache))
	chunks = []
	for column, items in groups.items():
		for start in range(0, len(items), args.batch_size):
			chunks.append((column, items[start:start + args.batch_size]))

	done = 0
	started = time.time()

	def handle(column, chunk):
		texts = [item['text'] for item in chunk]
		try:
			outputs = checker.check_batch(column, texts)
		except LocalMTError as exc:
			return [(None, 0.0, str(exc)[:200])] * len(chunk)
		return [(output, ratio, None) for output, ratio in outputs]

	if chunks:
		with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
			futures = {pool.submit(handle, column, chunk): chunk for column, chunk in chunks}
			for future in as_completed(futures):
				chunk = futures[future]
				try:
					results = future.result()
				except Exception as exc:  # noqa: BLE001 - 单批失败不影响整体
					results = [(None, 0.0, f'{type(exc).__name__}: {exc}')] * len(chunk)
				for cell, (output, ratio, error) in zip(chunk, results):
					cell['ratio'] = round(ratio, 3)
					if error:
						cell['error'] = error
						continue
					cell['issue'] = checker.classify(cell['column'], cell['text'], output, ratio)
				done += len(chunk)
				if done % 200 == 0 or done == len(pending):
					save_cache(args.cache, checker.cache)
					elapsed = time.time() - started
					print(f'[{ts()}] 模型进度 {done}/{len(pending)} 单元格'
						  f'（{elapsed:.0f}s，调用 {client.calls} 次）', flush=True)
	save_cache(args.cache, checker.cache)

	# 3) 汇总
	issues_by_row: Dict[int, Dict[str, Any]] = defaultdict(dict)
	for cell in cells:
		if cell['issue']:
			issues_by_row[cell['row_id']][cell['column']] = cell['issue']

	coverage: Dict[int, int] = defaultdict(int)
	expected: Dict[int, int] = defaultdict(int)
	for row in selected:
		for column in langs:
			if column == 'logs_zh':
				continue
			text = LogStore.normalize(row['texts'].get(column))
			if text and not is_trivial(text):
				expected[row['id']] += 1
	for cell in cells:
		coverage[cell['row_id']] += 1

	by_column = Counter()
	by_source = Counter()
	for row_issues in issues_by_row.values():
		for column, detail in row_issues.items():
			by_column[column] += 1
			by_source[str(detail.get('source', '?'))] += 1

	stats = {
		'rows': len(selected), 'cells': len(cells), 'flagged_cells': sum(by_column.values()),
		'flagged_rows': len(issues_by_row), 'by_column': dict(by_column),
		'by_source': dict(by_source), 'calls': client.calls,
		'elapsed_seconds': round(time.time() - started, 1),
	}
	print(f'[{ts()}] 完成：{stats["flagged_cells"]} 个单元格 / {stats["flagged_rows"]} 行可疑'
		  f'（{stats["elapsed_seconds"]}s，模型调用 {client.calls} 次）')
	for column, count in by_column.most_common(8):
		print(f'    {column:12s} {count}')
	print('  示例：')
	shown = 0
	for row_id, row_issues in sorted(issues_by_row.items()):
		for column, detail in row_issues.items():
			print(f'    #{row_id} {column}: {detail.get("detected")} — {detail.get("reason")}')
			shown += 1
			if shown >= args.show:
				break
		if shown >= args.show:
			break

	# 4) 写库
	apply_count = 0
	if args.apply and cells:
		merged: Dict[int, Dict[str, Any]] = {}
		full_scan = not args.langs
		for row_id, row_issues in issues_by_row.items():
			row = rows[row_id]
			existing = row.get('lang_issues') or {}
			merged[row_id] = dict(row_issues) if (full_scan and args.clear_stale) else {**existing, **row_issues}
		clear_ids = []
		if args.clear_stale:
			for row in selected:
				row_id = row['id']
				if expected[row_id] == coverage[row_id] and row_id not in issues_by_row:
					clear_ids.append(row_id)
		apply_count = LogMaintenance.record_lang_issues(merged, clear_ids, apply=True)
		print(f'[{ts()}] 已写入 lang_issues：{len(merged)} 行有标注，{len(clear_ids)} 行清除旧标注')
	else:
		print('  dry-run：未写库（加 --apply 写 lang_issues）')

	return {'stats': stats, 'issues': issues_by_row, 'applied': apply_count,
			'examples': cells[:0], 'cache': args.cache}


# ==================== fix ====================

def run_fix(rows, args, client) -> Dict[str, Any]:
	langs = set(parse_langs(args.langs))
	selected = select_rows(rows, args)
	payload = []
	skipped = []
	for row in selected:
		issues = row.get('lang_issues') or {}
		targets = {column: detail for column, detail in issues.items()
				   if column in langs and column in LogStore.LANG_COLUMNS and column != 'logs_zh'}
		if not targets:
			continue
		zh = LogStore.normalize(row['texts'].get('logs_zh') or row.get('content'))
		en = LogStore.normalize(row['texts'].get('logs_en'))
		source = zh if zh else en
		if not source:
			skipped.append({'row_id': row['id'], 'reason': 'no_source'})
			continue
		translations = {}
		for column in targets:
			try:
				output = client.translate(source, LANG_TARGETS[column],
										  source_is_chinese=has_han(source))
			except LocalMTError as exc:
				skipped.append({'row_id': row['id'], 'column': column, 'reason': str(exc)[:200]})
				continue
			ok, reason = validate_translation(source, output, column)
			if not ok:
				skipped.append({'row_id': row['id'], 'column': column, 'reason': reason})
				continue
			translations[column] = {'text': output, 'confidence': 1.0}
			print(f'  #{row["id"]} {column}: {row["texts"].get(column)!r} -> {output!r}')
		if translations:
			payload.append({'row_id': row['id'], 'translations': translations})

	result = {'rows': len(payload),
			  'columns': sum(len(item['translations']) for item in payload),
			  'skipped': skipped, 'applied': False, 'backup': None}
	if args.apply and payload:
		output = LogFiller.apply(payload, rows, apply=True,
								 backup=not args.no_backup, backup_path=args.backup)
		result.update(output)
		print(f'[{ts()}] 已替换 {result["columns"]} 个单元格，涉及 {result["rows"]} 行；'
			  f'备份：{result.get("backup")}')
	else:
		print(f'[{ts()}] 预览：{result["columns"]} 个单元格 / {result["rows"]} 行'
			  f'（加 --apply 写库）')
	return result


# ==================== calibrate ====================

def run_calibrate(rows, args, client) -> Dict[str, Any]:
	langs = parse_langs(args.langs)
	candidates = [row for row in rows.values() if row.get('proofed')]
	candidates.sort(key=lambda row: row['id'])
	candidates = candidates[:args.sample]
	checker = LangChecker(client, batch_size=args.batch_size, workers=1,
						  cache=load_cache(args.cache))
	ratios: Dict[str, List[float]] = defaultdict(list)
	for row in candidates:
		for column in langs:
			text = LogStore.normalize(row['texts'].get(column))
			if not text or is_trivial(text):
				continue
			if args.per_lang and len(ratios[column]) >= args.per_lang:
				continue
			try:
				_output, ratio = checker.check_text(column, text)
			except LocalMTError:
				continue
			ratios[column].append(ratio)
	save_cache(args.cache, checker.cache)

	def percentile(values: List[float], pct: float) -> float:
		if not values:
			return 0.0
		ordered = sorted(values)
		index = min(len(ordered) - 1, int(round((len(ordered) - 1) * pct)))
		return ordered[index]

	report = {}
	print(f'[{ts()}] 校准样本：{len(candidates)} 行'
		  f'（proofed=1），各列回译相似度分位：')
	print(f'  {"列":12s} {"n":>4s} {"p1":>5s} {"p5":>5s} {"p25":>5s} {"p50":>5s}')
	for column, values in sorted(ratios.items()):
		if not values:
			continue
		report[column] = {'n': len(values), 'p1': percentile(values, 0.01),
						  'p5': percentile(values, 0.05), 'p25': percentile(values, 0.25),
						  'p50': percentile(values, 0.5)}
		print(f'  {column:12s} {len(values):4d} {report[column]["p1"]:5.2f}'
			  f' {report[column]["p5"]:5.2f} {report[column]["p25"]:5.2f}'
			  f' {report[column]["p50"]:5.2f}')
	print('  建议：long-ratio 取 p5 向下取整（不低于 0.55），short-ratio 取 p1 向下取整')
	return {'report': report, 'samples': len(candidates), 'calls': client.calls}


# ==================== main ====================

def make_client(args) -> LocalMTClient:
	client = LocalMTClient.from_config(
		model=args.model, base_url=args.base_url, api=args.api,
		timeout=args.timeout, max_retries=args.retries,
		temperature=args.temperature)
	client.model = client.resolve_model()
	print(f'[{ts()}] 本地模型：{client.model} @ {client.base_url}（{client.api}）')
	return client


def main() -> int:
	parser = argparse.ArgumentParser(description='用本地模型校验 / 修复译文语言（默认 dry-run）')
	sub = parser.add_subparsers(dest='command', required=True)

	def common(p):
		p.add_argument('--ids', help='只处理指定 logs.id，如 696,5135 或 100-200')
		p.add_argument('--all', action='store_true', help='处理全部行')
		p.add_argument('--limit', type=int, default=0, help='最多处理多少行')
		p.add_argument('--offset', type=int, default=0)
		p.add_argument('--types', default='module,log')
		p.add_argument('--langs', help='只看这些语言列（默认除 logs_zh 外全部）')
		p.add_argument('--skip-proofed', action='store_true', help='跳过 proofed=1 的行')
		p.add_argument('--model', help='LM Studio 模型 id（默认自动选 hunyuan）')
		p.add_argument('--base-url', help='LM Studio 地址，默认 http://127.0.0.1:1234')
		p.add_argument('--api', choices=('native', 'openai'), help='接口模式')
		p.add_argument('--timeout', type=float, default=180)
		p.add_argument('--retries', type=int, default=2)
		p.add_argument('--temperature', type=float, default=0.0)
		p.add_argument('--workers', type=int, default=2)
		p.add_argument('--batch-size', type=int, default=16)
		p.add_argument('--cache', default='/tmp/langcheck_cache.json')
		p.add_argument('--report')
		p.add_argument('--show', type=int, default=12)
		p.add_argument('--apply', action='store_true', help='写库（写前自动备份）')

	check = sub.add_parser('check', help='校验语言并写 lang_issues')
	common(check)
	check.add_argument('--rules-only', action='store_true', help='只跑规则，不调用模型')
	check.add_argument('--detector', choices=('hybrid', 'lm', 'rules'), default='hybrid',
						help='hybrid=规则+本地语种模型（默认，快）；lm=翻译模型回译（慢、误报多）；rules=只跑规则')
	check.add_argument('--long-ratio', type=float, default=DEFAULT_LONG_RATIO)
	check.add_argument('--short-ratio', type=float, default=DEFAULT_SHORT_RATIO)
	check.add_argument('--short-chars', type=int, default=SHORT_CHARS)
	check.add_argument('--clear-stale', action='store_true',
					   help='全量扫描时，用本次结果整体替换旧标注（默认合并，保留旧标注）')

	fix = sub.add_parser('fix', help='用本地模型替换可疑译文')
	common(fix)
	fix.add_argument('--backup')
	fix.add_argument('--no-backup', action='store_true')

	cal = sub.add_parser('calibrate', help='在 proofed 行上采样相似度分布')
	common(cal)
	cal.add_argument('--sample', type=int, default=50)
	cal.add_argument('--per-lang', type=int, default=40, help='每列最多采样多少条')

	args = parser.parse_args()
	if not (args.ids or args.all or args.limit):
		parser.error('需要 --ids / --all / --limit 之一')

	rows = LogMaintenance.load_rows()
	client = make_client(args)
	started = time.time()
	if args.command == 'check':
		result = run_check(rows, args, client)
	elif args.command == 'fix':
		result = run_fix(rows, args, client)
	else:
		result = run_calibrate(rows, args, client)
	result['command'] = args.command
	result['generated_at'] = ts()
	result['model'] = client.model
	result['elapsed_seconds'] = round(time.time() - started, 1)
	write_json(args.report, result)
	return 0


if __name__ == '__main__':
	sys.exit(main())
