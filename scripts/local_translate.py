"""
local_translate.py - 用 LM Studio（Hunyuan-MT-7B）逐条校对 / 补写日志翻译

背景：``logs`` 表每行是一条日志（``module`` / ``log``）的多语言版本，语言列见
``CHANGELOG_LOCALES``。很多行缺少部分语言（``logs_de`` / ``logs_ar`` …），早期
补译走 DeepSeek 的 JSON 输出。本地部署 Hunyuan-MT-7B 后，可以用纯翻译模型逐条处理。

用法：

    # 0) 检查 LM Studio 服务与模型（需要先在 LM Studio 里加载模型并 Start Server）
    python3 scripts/local_translate.py check
    python3 scripts/local_translate.py check --probe

    # 1) 盘点缺口（不调用模型）
    python3 scripts/local_translate.py fill --limit 50
    python3 scripts/local_translate.py review --langs logs_en --limit 50

    # 2) 预览（调用模型，不写库）
    python3 scripts/local_translate.py fill --ids 146 --run
    python3 scripts/local_translate.py review --ids 146 --langs logs_en --run

    # 3) 写库（默认先备份；新增 / 替换的译文会把 proofed 重置为 0）
    python3 scripts/local_translate.py fill --ids 146 --apply
    python3 scripts/local_translate.py review --ids 146 --langs logs_en --fix

    # 4) 一条命令同时补缺 + 校对
    python3 scripts/local_translate.py all --limit 200 --run
    python3 scripts/local_translate.py all --limit 200 --apply --fix

    # 只处理引用里实际出现的语言、并发 4 路、结果缓存
    python3 scripts/local_translate.py fill --expected owners --workers 4 \\
        --cache /tmp/local_translate_cache.json --apply

校对方式：把源文本（优先 ``logs_zh``）重新翻译成目标语言，与现有译文做相似度比较；
低于阈值（长文本 ``--ratio`` 默认 0.75，短文本 ``--short-ratio`` 默认 0.45）判为可疑。
纯翻译模型不擅长「判断译文对错」，重译对比比让它打分更可靠；``--fix`` 时用重译结果替换。

写库复用 ``LogFiller.apply()``：备份、``lang_issues`` 清理、``proofed`` / ``complete``
语义均与 ``fill_missing_logs.py`` 一致。写完建议再跑一遍 ``review`` 确认。
"""
import argparse
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.local_mt import (
	LANG_TARGETS, LocalMTClient, LocalMTError, has_han,
	script_issue, similarity, validate_translation,
)
from miroms.logs_fill import LogFiller
from miroms.logs_maintenance import LogMaintenance
from miroms.logs_store import LogStore

FILL = 'fill'
REVIEW = 'review'
FLAGGED = ('fallback', 'invalid', 'mismatch')
ZH = LogStore.ZH_COLUMN
EN = LogStore.EN_COLUMN


def ts() -> str:
	return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def parse_ids(spec: str):
	ids = set()
	for chunk in (spec or '').split(','):
		chunk = chunk.strip()
		if not chunk:
			continue
		try:
			if '-' in chunk:
				start, end = chunk.split('-', 1)
				ids.update(range(int(start), int(end) + 1))
			else:
				ids.add(int(chunk))
		except ValueError as exc:
			raise SystemExit(f'✖ --ids 格式不对：{chunk!r}（示例：146,253 或 100-200）') from exc
	return sorted(ids)


def parse_langs(spec) -> list:
	if not spec:
		return list(LogStore.LANG_COLUMNS)
	columns = []
	for chunk in str(spec).split(','):
		column = chunk.strip()
		if not column:
			continue
		if column not in LogStore.LANG_COLUMNS:
			raise SystemExit(f'✖ 未知语言列 {column}；可选：{", ".join(LogStore.LANG_COLUMNS)}')
		columns.append(column)
	return columns


def write_json(path: str, payload) -> None:
	target = Path(path)
	target.parent.mkdir(parents=True, exist_ok=True)
	target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
	print(f'已写入 {target}')


# ==================== 任务构建 ====================

def pick_source(row, target_column):
	"""为某目标语言挑源文本：中文优先，其次英文；补中文时用英文反向翻译"""
	texts = row['texts']
	zh = texts.get(ZH) or (row['content'] if has_han(row['content']) else '')
	en = texts.get(EN) or ''
	if target_column == ZH:
		if en:
			return en, EN, False
		for column in LogStore.LANG_COLUMNS:
			if column != ZH and texts.get(column):
				return texts[column], column, has_han(texts[column])
		return '', '', False
	if zh:
		return zh, ZH, True
	if en:
		return en, EN, False
	for column in LogStore.LANG_COLUMNS:
		if texts.get(column):
			return texts[column], column, has_han(texts[column])
	return '', '', False


def expected_columns(row, args, module_bits, entry_bits):
	if args.expected == 'all':
		return set(LogStore.LANG_COLUMNS)
	bits = module_bits.get(row['id'], 0) if row['type'] == 'module' else entry_bits.get(row['id'], 0)
	return set(LogStore.columns_of(bits))


def build_tasks(rows, args, kinds, owners=None):
	module_bits, entry_bits = ({}, {})
	if args.expected == 'owners':
		module_bits, entry_bits = LogFiller._owner_language_bits(owners or {})
	tasks = []
	for row in rows:
		expected = expected_columns(row, args, module_bits, entry_bits)
		if not expected:
			continue
		for column in args.langs:
			if column not in expected:
				continue
			existing = LogStore.normalize(row['texts'].get(column))
			if FILL in kinds and not existing:
				kind = FILL
			elif REVIEW in kinds and existing:
				kind = REVIEW
			else:
				continue
			source, source_column, source_is_chinese = pick_source(row, column)
			if not source or source_column == column:
				continue
			tasks.append({
				'index': len(tasks),
				'kind': kind,
				'row_id': row['id'],
				'type': row['type'],
				'column': column,
				'source': source,
				'source_column': source_column,
				'source_is_chinese': source_is_chinese,
				'existing': existing,
				'key': f"{kind}:{row['id']}:{column}:{LogStore.hash_text(source)[:12]}",
				'output': None,
				'error': None,
				'cached': False,
				'ratio': None,
				'verdict': '',
			})
	return tasks


def select_rows(rows, args):
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


# ==================== 调用与判定 ====================

def classify(task, args) -> str:
	if task['error']:
		return 'error'
	issue = script_issue(task['existing'], task['column'])
	if issue:
		return 'invalid'
	if task['column'] != ZH and LogStore.normalize(task['existing']) == LogStore.normalize(task['source']):
		return 'fallback'
	threshold = args.short_ratio if len(task['existing']) <= args.short_chars else args.ratio
	if task['ratio'] is not None and task['ratio'] < threshold:
		return 'mismatch'
	return 'ok'



def to_traditional(text: str) -> str:
	"""把模型输出的简体转成繁体（台湾用字）；OpenCC 缺失时原样返回"""
	try:
		from opencc import OpenCC

		return OpenCC('s2twp').convert(text)
	except Exception:  # noqa: BLE001 - 可选依赖
		return text

def run_one(task, client, args, cache):
	key = task['key']
	cached = cache.get(key)
	if isinstance(cached, dict) and cached.get('output'):
		task['output'] = cached['output']
		task['cached'] = True
	else:
		try:
			task['output'] = client.translate(
				task['source'], LANG_TARGETS[task['column']], task['source_is_chinese'])
		except LocalMTError as exc:
			task['output'] = None
			task['error'] = str(exc)[:300]
	if task['output'] and not task['error'] and task['column'] == 'logs_zh_tw':
		task['output'] = to_traditional(task['output'])
	if task['output'] and not task['error']:
		ok, reason = validate_translation(task['source'], task['output'], task['column'])
		if not ok:
			task['error'] = f'invalid:{reason}'
			task['output'] = None
		else:
			cache[key] = {'output': task['output']}
	if task['kind'] == REVIEW:
		task['ratio'] = (similarity(task['existing'], task['output'])
						 if task['output'] else None)
		task['verdict'] = classify(task, args)
	return task


def run_tasks(tasks, client, args, cache):
	total = len(tasks)
	results = [None] * total
	done = 0

	def progress():
		nonlocal done
		done += 1
		if done == total or done % max(1, args.progress_every) == 0:
			print(f'[{ts()}] 进度 {done}/{total}（调用 {client.calls} 次）', flush=True)

	if args.workers > 1:
		with ThreadPoolExecutor(max_workers=args.workers) as pool:
			futures = {pool.submit(run_one, task, client, args, cache): task['index']
					   for task in tasks}
			for future in as_completed(futures):
				index = futures[future]
				try:
					results[index] = future.result()
				except Exception as exc:  # noqa: BLE001 - 单条失败不中断整批
					task = tasks[index]
					task['error'] = f'{type(exc).__name__}: {exc}'
					results[index] = task
				progress()
				if args.cache and done % 25 == 0:
					save_cache(args.cache, cache)
	else:
		for index, task in enumerate(tasks):
			results[index] = run_one(task, client, args, cache)
			if args.cache and index % 25 == 0:
				save_cache(args.cache, cache)
			progress()
	return results


def load_cache(path):
	if not path:
		return {}
	file = Path(path)
	if not file.exists():
		return {}
	try:
		data = json.loads(file.read_text(encoding='utf-8'))
	except json.JSONDecodeError:
		return {}
	return data if isinstance(data, dict) else {}


def save_cache(path, cache):
	if not path:
		return
	Path(path).write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')


# ==================== 写库 ====================

def apply_results(results, rows, args, want_fill: bool, want_fix: bool):
	merged = {}
	for result in results:
		if result.get('error') or not result.get('output'):
			continue
		if result['kind'] == FILL:
			if not want_fill:
				continue
		elif not (want_fix and result.get('verdict') in FLAGGED):
			continue
		merged.setdefault(result['row_id'], {})[result['column']] = result['output']
	if not merged:
		return {'rows': 0, 'columns': 0, 'applied': False, 'backup': None}
	payload = [
		{'row_id': row_id,
		 'translations': {column: {'text': text, 'confidence': 1.0}
						  for column, text in columns.items()}}
		for row_id, columns in merged.items()
	]
	return LogFiller.apply(
		payload, rows, apply=True,
		keep_proofed=getattr(args, 'keep_proofed', False),
		backup=not getattr(args, 'no_backup', False),
		backup_path=getattr(args, 'backup', None),
	)


# ==================== 输出 ====================

def print_inventory(rows, selected, tasks, kinds, args):
	fills = sum(1 for task in tasks if task['kind'] == FILL)
	reviews = len(tasks) - fills
	print(f'[{ts()}] 载入 logs {len(rows)} 行，选中 {len(selected)} 行，'
		  f'涉及 {len({t["row_id"] for t in tasks})} 行')
	if FILL in kinds:
		print(f'  待补译：{fills} 项（{len({t["row_id"] for t in tasks if t["kind"] == FILL})} 行）')
	if REVIEW in kinds:
		print(f'  待校对：{reviews} 项（{len({t["row_id"] for t in tasks if t["kind"] == REVIEW})} 行）')
	if not tasks:
		print('  没有需要处理的项目（可用 --include / --langs 放宽条件）')
		return
	print(f'  预计调用模型：{len(tasks)} 次'
		  f'（并发 {args.workers}，模型逐个处理）')
	print('  预览/写库：加 --run；补译写库加 --apply；校对写库加 --fix')


def print_results(results, args):
	errors = [item for item in results if item.get('error')]
	flagged = [item for item in results
			   if item['kind'] == REVIEW and item.get('verdict') in FLAGGED]
	filled = [item for item in results
			  if item['kind'] == FILL and item.get('output') and not item.get('error')]
	print(f'[{ts()}] 完成：补译 {len(filled)} 项，校对 {len(results) - len(filled)} 项'
		  f'（可疑 {len(flagged)}，失败 {len(errors)}）')
	if filled:
		print('  补译示例：')
		for item in filled[:args.show]:
			print(f"    + #{item['row_id']} {item['column']}: {item['output']!r}")
	if flagged:
		print('  可疑译文：')
		for item in flagged[:args.show]:
			mark = {'fallback': '↩', 'invalid': '✖', 'mismatch': '⚠'}.get(item['verdict'], '?')
			ratio = item.get('ratio')
			print(f"    {mark} #{item['row_id']} {item['column']} "
				  f"相似度 {ratio:.2f} [{item['verdict']}]" if ratio is not None else
				  f"    {mark} #{item['row_id']} {item['column']} [{item['verdict']}]")
			print(f"        现有: {item['existing']!r}")
			print(f"        重译: {item['output']!r}")
	if errors:
		print('  失败：')
		for item in errors[:args.show]:
			print(f"    ✖ #{item['row_id']} {item['column']}: {item['error']}")


def build_report(mode, rows, tasks, results, args, apply_output):
	verdicts = Counter()
	for item in results:
		if item.get('error'):
			verdicts['error'] += 1
		elif item['kind'] == FILL:
			verdicts['filled'] += 1
		else:
			verdicts[item.get('verdict') or 'unknown'] += 1
	return {
		'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
		'mode': mode,
		'model': getattr(args, 'resolved_model', ''),
		'base_url': getattr(args, 'resolved_base_url', ''),
		'rows': len(rows),
		'tasks': len(tasks),
		'stats': dict(verdicts),
		'apply': apply_output,
		'results': results,
	}


# ==================== 子命令 ====================

def make_client(args):
	client = LocalMTClient.from_config(
		model=getattr(args, 'model', None),
		base_url=getattr(args, 'base_url', None),
		api=getattr(args, 'api', None),
		timeout=getattr(args, 'timeout', None) or 120,
		max_retries=args.retries,
		temperature=args.temperature,
		top_p=args.top_p,
		max_tokens=args.max_tokens,
		top_k=args.top_k,
		repeat_penalty=args.repeat_penalty,
	)
	client.model = client.resolve_model()
	return client


def cmd_check(args):
	client = LocalMTClient.from_config(
		model=getattr(args, 'model', None),
		base_url=getattr(args, 'base_url', None),
		api=getattr(args, 'api', None),
		timeout=getattr(args, 'timeout', None) or 120,
		max_retries=args.retries,
		temperature=args.temperature,
		top_p=args.top_p,
		max_tokens=args.max_tokens,
		top_k=args.top_k,
		repeat_penalty=args.repeat_penalty,
	)
	try:
		models = client.list_models()
	except LocalMTError as exc:
		print(f'✖ {exc}')
		return 2
	print(f'✓ 服务可用：{client.base_url}（{client.api} 接口）')
	print(f'  已加载模型：{", ".join(models) if models else "（无）"}')
	try:
		client.model = client.resolve_model()
	except LocalMTError as exc:
		print(f'✖ {exc}')
		return 2
	print(f'  使用模型：{client.model}')
	if args.probe:
		try:
			output = client.translate('优化系统稳定性，修复若干问题', 'English', source_is_chinese=True)
		except LocalMTError as exc:
			print(f'✖ 试翻失败：{exc}')
			return 1
		print(f'  试翻结果：{output!r}')
		print(f'  usage：{client.last_usage}')
	return 0


def cmd_translate(mode, args):
	rows = LogMaintenance.load_rows()
	selected = select_rows(rows, args)
	owners = None
	if args.expected == 'owners':
		print(f'[{ts()}] 载入引用结构（--expected owners）...')
		owners = LogMaintenance.load_owners()
	kinds = {'fill': [FILL], 'review': [REVIEW], 'all': [FILL, REVIEW]}[mode]
	tasks = build_tasks(selected, args, kinds, owners)
	print_inventory(rows, selected, tasks, kinds, args)
	if not tasks:
		return 0
	want_run = bool(args.run or getattr(args, 'apply', False) or getattr(args, 'fix', False))
	if not want_run:
		return 0

	client = make_client(args)
	args.resolved_model = client.model
	args.resolved_base_url = client.base_url
	print(f'[{ts()}] 使用模型 {client.model}（{client.base_url}）')
	cache = load_cache(args.cache)
	results = run_tasks(tasks, client, args, cache)
	if args.cache:
		save_cache(args.cache, cache)
	print_results(results, args)

	want_fill = mode in ('fill', 'all') and bool(getattr(args, 'apply', False))
	want_fix = mode in ('review', 'all') and bool(getattr(args, 'fix', False))
	apply_output = None
	if want_fill or want_fix:
		apply_output = apply_results(results, rows, args, want_fill, want_fix)
		if apply_output.get('applied'):
			print(f"  已写库：{apply_output['rows']} 行 / {apply_output['columns']} 列"
				  f"（备份：{apply_output.get('backup') or '无'}，proofed 已重置）")
		else:
			print('  没有可写入的译文')
	report = build_report(mode, rows, tasks, results, args, apply_output)
	if args.json:
		write_json(args.json, report)
	errors = sum(1 for item in results if item.get('error'))
	return 1 if errors else 0


# ==================== 参数 ====================

def add_connection_args(parser):
	parser.add_argument('--base-url', help='LM Studio 地址，默认 http://127.0.0.1:1234（原生接口）')
	parser.add_argument('--api', choices=('native', 'openai'),
						help='接口模式：native=/api/v1/chat（默认，system_prompt+input）；'
							 'openai=/v1/chat/completions')
	parser.add_argument('--model', help='模型标识；留空自动选模型列表里的 Hunyuan 模型')
	parser.add_argument('--timeout', type=float, help='单次请求超时秒数（默认 120）')
	parser.add_argument('--retries', type=int, default=2, help='网络/HTTP 错误重试次数（默认 2）')
	parser.add_argument('--temperature', type=float, default=0.7,
						help='采样温度（模型卡推荐 0.7；追求稳定可用 0.2）')
	parser.add_argument('--top-p', type=float, default=0.6, help='top_p（模型卡推荐 0.6）')
	parser.add_argument('--max-tokens', type=int, default=0,
						help='输出上限；0=按源文本长度自动计算')
	parser.add_argument('--top-k', type=int, help='top_k（模型卡推荐 20；不传则用 LM Studio 默认）')
	parser.add_argument('--repeat-penalty', type=float,
						help='repetition_penalty（模型卡推荐 1.05；不传则用 LM Studio 默认）')


def add_selection_args(parser):
	parser.add_argument('--types', default='module,log', help='日志类型，默认 module,log')
	parser.add_argument('--ids', help='只处理指定 logs.id，如 146,253 或 100-200')
	parser.add_argument('--langs', help='只处理这些语言列，逗号分隔；默认全部')
	parser.add_argument('--expected', choices=('all', 'owners'), default='all',
						help='期望语言：all=全部语言列（默认）；owners=该行引用里出现过的语言')
	parser.add_argument('--limit', type=int, default=0, help='最多处理多少行（默认 0=全部）')
	parser.add_argument('--offset', type=int, default=0, help='跳过前 N 行')
	parser.add_argument('--skip-proofed', action='store_true', help='跳过已 proofed 的行')
	parser.add_argument('--workers', type=int, default=1,
						help='并发请求数（默认 1=逐条；本地模型建议 1-4）')
	parser.add_argument('--progress-every', type=int, default=20, help='每 N 条打印一次进度')
	parser.add_argument('--show', type=int, default=20, help='预览最多显示多少条')


def add_output_args(parser):
	parser.add_argument('--cache', help='结果缓存 JSON（可跨次运行复用）')
	parser.add_argument('--json', help='把完整报告写入 JSON')


def build_parser():
	parser = argparse.ArgumentParser(
		description='用 LM Studio（Hunyuan-MT-7B）逐条校对 / 补写日志翻译',
		formatter_class=argparse.RawDescriptionHelpFormatter)
	sub = parser.add_subparsers(dest='command', required=True)

	check = sub.add_parser('check', help='检查 LM Studio 服务与模型')
	add_connection_args(check)
	check.add_argument('--probe', action='store_true', help='试翻一句，验证模型可用')
	check.set_defaults(func=lambda args: cmd_check(args))

	fill = sub.add_parser('fill', help='补写缺失语言（默认只盘点）')
	add_connection_args(fill)
	add_selection_args(fill)
	add_output_args(fill)
	fill.add_argument('--run', action='store_true', help='调用模型预览，不写库')
	fill.add_argument('--apply', action='store_true', help='调用模型并写库')
	fill.add_argument('--keep-proofed', action='store_true',
					  help='补译后保留 proofed（默认重置为 0，需要重新校对）')
	fill.add_argument('--backup', help='写库前备份路径')
	fill.add_argument('--no-backup', action='store_true', help='不备份（不推荐）')
	fill.set_defaults(func=lambda args: cmd_translate('fill', args))

	review = sub.add_parser('review', help='校对现有译文（默认只盘点）')
	add_connection_args(review)
	add_selection_args(review)
	add_output_args(review)
	review.add_argument('--run', action='store_true', help='调用模型并报告，不写库')
	review.add_argument('--fix', action='store_true', help='把可疑译文替换为模型重译结果')
	review.add_argument('--ratio', type=float, default=0.75,
						help='长文本相似度阈值（低于即判可疑，默认 0.75）')
	review.add_argument('--short-ratio', type=float, default=0.45,
						help='短文本相似度阈值（默认 0.45）')
	review.add_argument('--short-chars', type=int, default=24,
						help='短文本长度分界（默认 24 字符）')
	review.add_argument('--keep-proofed', action='store_true',
						help='替换译文后保留 proofed（默认重置为 0）')
	review.add_argument('--backup', help='写库前备份路径')
	review.add_argument('--no-backup', action='store_true', help='不备份（不推荐）')
	review.set_defaults(func=lambda args: cmd_translate('review', args))

	all_cmd = sub.add_parser('all', help='同时补缺 + 校对')
	add_connection_args(all_cmd)
	add_selection_args(all_cmd)
	add_output_args(all_cmd)
	all_cmd.add_argument('--run', action='store_true', help='调用模型并报告，不写库')
	all_cmd.add_argument('--apply', action='store_true', help='补译结果写库')
	all_cmd.add_argument('--fix', action='store_true', help='校对可疑项替换写库')
	all_cmd.add_argument('--ratio', type=float, default=0.75,
						 help='长文本相似度阈值（默认 0.75）')
	all_cmd.add_argument('--short-ratio', type=float, default=0.45,
						 help='短文本相似度阈值（默认 0.45）')
	all_cmd.add_argument('--short-chars', type=int, default=24,
						 help='短文本长度分界（默认 24 字符）')
	all_cmd.add_argument('--keep-proofed', action='store_true',
						 help='写库后保留 proofed（默认重置为 0）')
	all_cmd.add_argument('--backup', help='写库前备份路径')
	all_cmd.add_argument('--no-backup', action='store_true', help='不备份（不推荐）')
	all_cmd.set_defaults(func=lambda args: cmd_translate('all', args))
	return parser


def main(argv=None) -> int:
	parser = build_parser()
	args = parser.parse_args(argv)
	if hasattr(args, 'workers'):
		args.workers = max(1, int(args.workers))
	if hasattr(args, 'langs'):
		try:
			args.langs = parse_langs(args.langs)
		except SystemExit as exc:
			print(exc)
			return 2
	try:
		return args.func(args)
	except KeyboardInterrupt:
		print('\n已中断（已完成的写库不受影响）')
		return 130
	except SystemExit as exc:
		if isinstance(exc.code, str):
			print(exc.code)
			return 2
		raise
	except LocalMTError as exc:
		print(f'✖ {exc}')
		return 2


if __name__ == '__main__':
	sys.exit(main())
