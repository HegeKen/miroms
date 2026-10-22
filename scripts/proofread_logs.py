"""
proofread_logs.py - 日志多语言校对（规则扫描 → DeepSeek 复核 → 安全写回）

背景：同一 ROM 的不同语言结构，会被拆成「中文簇 + 附加语言簇」。早期补译脚本
按模块名 / 条目数猜测，可能把中文模块名填错，例如：

    id=11036  de='Interkonnektivität'   中文却被填成「其他」
    id=11038  de='Datenschutz und Sicherheit'  中文也被填成「其他」
    id=11040  de='Sonstiges'            这个才是真正的「其他」

本脚本把「发现 → AI 复核 → 计划 → 写库」拆成三步，默认全程 dry-run：

    # 只校对某几个 logs.id（不改日志内容；verdict=ok 时写 proofed 标记；退出码 0=正常，1=有疑点，2=参数错误）
    python3 scripts/proofread_logs.py check --ids 11036
    python3 scripts/proofread_logs.py check --ids 11036,11038
    python3 scripts/proofread_logs.py check --ids 3788 --no-ai          # 只做规则检查
    python3 scripts/proofread_logs.py check --ids 2998 --json /tmp/check.json

    python3 scripts/proofread_logs.py scan                 # 全库规则扫描（不调用 AI）
    python3 scripts/proofread_logs.py scan --report /tmp/proofread_scan.json

批量校对（默认只估算，加 --run 执行）：
    python3 scripts/proofread_logs.py batch-review --batch-size 10       # 全部多语言行，约 250–300 万 tokens
    python3 scripts/proofread_logs.py batch-review --batch-size 10 --run
    python3 scripts/proofread_logs.py batch-review --batch-size 1 --all  # 逐条全量（不推荐）
    python3 scripts/proofread_logs.py batch-review --batch-size 1 --all --run --allow-expensive

    # 需要先配置 DeepSeek API key（环境变量 DEEPSEEK_API_KEY 或 config.py 的 deepseek_api_key）
    python3 scripts/proofread_logs.py review               # 调 AI 复核 priority 候选
    python3 scripts/proofread_logs.py review --all         # 连同非优先候选一起复核
    python3 scripts/proofread_logs.py review --limit 20 --cache /tmp/proofread_cache.json

    python3 scripts/proofread_logs.py apply --decisions /tmp/proofread_decisions.json
    python3 scripts/proofread_logs.py apply --decisions ... --allow-clear --apply

动作说明：
  * rename：完整行（语言多、带 logs_en）直接改正 logs_zh / content；
  * clear ：附加语言簇的窄行（语言少、无 logs_en）只清中文，并去掉引用掩码的中文位；
            中文由该 ROM 自己的中文簇提供，因此不会造成导出重复；
  * 低置信度 / AI 意见冲突 / 未允许 clear 的，只报告不写库。

写库前自动备份，写后建议再跑一次：
    python3 scripts/maintain_logs.py audit
    python3 scripts/maintain_logs.py snapshot --out /tmp/before.json.gz
    python3 scripts/maintain_logs.py compare --before /tmp/before.json.gz
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.deepseek import DeepSeekClient, DeepSeekError
from miroms.logs_maintenance import LogMaintenance
from miroms.logs_proofread import LogProofreader
from miroms.logs_store import LogStore


def ts() -> str:
	return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def write_json(path: str, payload) -> None:
	target = Path(path)
	target.parent.mkdir(parents=True, exist_ok=True)
	target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
	print(f"已写入 {target}")


def print_families(report: dict, samples: int) -> None:
	stats = report['stats']
	print(f"[{ts()}] 扫描完成：{stats['families']} 个中文名冲突 family"
		  f"（priority {stats['priority_families']} 个，涉及 {stats['families_rows']} 行），"
		  f"疑似译文错列 {stats['mismatches']} 条")
	shown = 0
	for family in report['families']:
		if not family['priority']:
			continue
		shown += 1
		if shown > samples:
			break
		print(f"\n--- 「{family['zh']}」× {len(family['row_ids'])} 行，"
			  f"出现在 {family['owners_count']} 个 ROM（示例 {family['owners_sample'][:3]}）")
		for item in family['rows']:
			texts = ', '.join(f"{column[5:]}={value[:26]!r}"
							  for column, value in list(item['texts'].items())[:4])
			flag = '' if item['has_en'] and item['langs'] >= 8 else ' ⚠窄行'
			print(f"    #{item['row_id']} zh={item['current_zh']!r} langs={item['langs']}{flag}")
			print(f"        {texts}")
	if report['mismatches']:
		print('\n--- 疑似译文错列（只报告）：')
		for item in report['mismatches'][:samples]:
			print(f"    #{item['row_id']} {item['column'][5:]}={item['text']!r} "
				  f"现挂中文={item['current_zh']!r}，共现中文={item['likely_zh']!r} "
				  f"(support={item['support']})")


def parse_ids(spec: str) -> list:
	"""解析 "11036,11038,11040-11042" → 去重排序的 id 列表"""
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


def fmt_tokens(value) -> str:
	if isinstance(value, (list, tuple)):
		low, high = value
		return f'{low/10000:.1f}–{high/10000:.1f} 万'
	return f'{value/10000:.1f} 万'


def record_ai_marks(decisions) -> tuple:
	"""把 AI 结论落成标注：语言不符写入 lang_issues；ok 且无语言问题才置 proofed

	返回 (有语言标注的行数, 置 proofed=1 的行数, 置 proofed=0 的行数)。
	"""
	issues_by_id = {item['row_id']: item.get('lang_issues') or {}
					for item in decisions if item.get('lang_issues')}
	clear_ids = [item['row_id'] for item in decisions
				 if item['verdict'] == 'ok' and not item.get('lang_issues')]
	annotated, ok_count = 0, 0
	if issues_by_id or clear_ids:
		LogMaintenance.record_lang_issues(issues_by_id, clear_ids)
		annotated = len(issues_by_id)
	ok_ids = [item['row_id'] for item in decisions
			  if item['verdict'] == 'ok' and not item.get('lang_issues')]
	if ok_ids:
		LogMaintenance.mark_proofed(ok_ids, value=True)
		ok_count = len(ok_ids)
	bad_ids = [item['row_id'] for item in decisions if item['verdict'] != 'ok']
	if bad_ids:
		LogMaintenance.mark_proofed(bad_ids, value=False)
	return annotated, ok_count, len(bad_ids)


def print_lang_issues(issues: dict) -> None:
	if not issues:
		return
	print('  语言不符标注：')
	for column, detail in issues.items():
		correct = f" → {detail['correct']!r}" if detail.get('correct') else ''
		print(f"    {column} 实际={detail.get('detected')!r} "
			  f"({detail.get('confidence', 0):.2f}){correct} {detail.get('reason', '')[:80]}")


def run_batch_review(args) -> int:
	types = tuple(item.strip() for item in args.types.split(',') if item.strip())
	if not set(types) <= {'module', 'log'} or not types:
		print('✖ --types 只能是 module,log 的组合')
		return 2
	if args.batch_size < 1:
		print('✖ --batch-size 必须 ≥1')
		return 2
	rows = LogMaintenance.load_rows()
	owners = LogMaintenance.load_owners()
	selected, _known, batches = LogProofreader.prepare_batches(
		rows, owners, batch_size=args.batch_size, include_single=args.all,
		min_langs=args.min_langs, types=types, limit=args.limit_rows,
		include_proofed=args.include_proofed)
	estimate = LogProofreader.estimate_batches(batches, args.batch_size, selected)
	print(f"[{ts()}] 批量校对估算（未调用 API）")
	print(f"  行数：{estimate['rows']}（module {estimate['rows_by_type']['module']} / "
		  f"log {estimate['rows_by_type']['log']}）")
	print(f"  批次：{estimate['batches']}（每批 {estimate['batch_size']} 条）")
	print(f"  Prompt：约 {fmt_tokens(estimate['prompt_tokens'])} tokens")
	print(f"  Completion（含 reasoning）：约 {fmt_tokens(estimate['completion_tokens'])} tokens")
	print(f"  合计：约 {fmt_tokens(estimate['total_tokens'])} tokens；"
		  f"预计 {estimate['estimated_hours'][0]}–{estimate['estimated_hours'][1]} 小时")
	print(f"  缓存：{args.cache}；decisions：{args.decisions}")
	if args.batch_size == 1:
		print('  ⚠ 逐条模式调用次数很多，仅建议小样本 / 指定 --limit-rows 使用')
	if args.batch_size == 1 and args.all:
		print('  ⚠ 逐条 + 全部行包含 7,156 条单语言行，token 花费高且没有跨语言校对价值')

	expensive = estimate['total_tokens'][1] > 8_000_000 or estimate['batches'] > 5000
	if expensive and not args.run:
		print('  ⚠ 该方案超过 800 万 tokens 或 5,000 次调用；确认要跑请加 '
			  '--run --allow-expensive')
	if args.json:
		write_json(args.json, {'estimate': estimate, 'batch_size': args.batch_size,
							   'types': list(types), 'include_single': args.all,
							   'min_langs': args.min_langs})
	if not args.run:
		print('\n仅估算，未调用 API。确认后加 --run 执行。')
		return 0
	if expensive and not args.allow_expensive:
		print('✖ 超过安全阈值：需要 --allow-expensive 显式确认')
		return 2
	try:
		client = DeepSeekClient.from_config(max_calls=args.max_calls)
	except DeepSeekError as exc:
		print(f'✖ {exc}')
		return 2

	def progress(index: int, total: int, batch: dict, cached: bool) -> None:
		every = max(1, args.progress_every)
		if index == 1 or index % every == 0 or index == total:
			ids = ', '.join(str(row['id']) for row in batch['rows'])
			print(f"[{ts()}] 批次 {index}/{total}（{batch['type']}，"
				  f"{len(batch['rows'])} 条）id={ids}"
				  f"{'（缓存）' if cached else ''}")

	mark_stats = {'annotated': 0, 'proofed': 0, 'unproofed': 0}

	def flush_marks(parsed) -> None:
		# 每批立即落库：11k 行逐条跑要很久，不能等全部结束才写 lang_issues
		if args.no_mark:
			return
		annotated, ok_count, bad_count = record_ai_marks(parsed)
		mark_stats['annotated'] += annotated
		mark_stats['proofed'] += ok_count
		mark_stats['unproofed'] += bad_count

	try:
		result = LogProofreader.batch_review(
			rows, owners, client, batch_size=args.batch_size,
			include_single=args.all, min_langs=args.min_langs, types=types,
			limit=args.limit_rows, cache_path=args.cache, on_progress=progress,
			on_decisions=flush_marks)
	except DeepSeekError as exc:
		print(f'✖ DeepSeek 调用失败：{exc}')
		return 1
	print(f"[{ts()}] 完成：{result['rows']} 行 / {result['batches']} 批，"
		  f"实际调用 {result['calls']} 次")
	print(f"  verdict：{result['by_verdict']}")
	print(f"  按类型：{result['by_type_verdict']}")
	print(f"  语言不符标注：{result.get('lang_issues', 0)} 行")
	if result.get('aborted') == 'max_calls':
		print(f"  ⚠ 已达到 max_calls 上限，已提前停止；本次只处理了前 "
			  f"{result['calls']} 次调用。加 --max-calls <更大值> 继续（缓存会复用已完成的批次）。")
	if result['errors']:
		print(f"  ⚠ {len(result['errors'])} 个批次失败：")
		for item in result['errors'][:5]:
			print(f"    {item['type']} {item['row_ids']}: {item['error']}")
	if not args.no_mark:
		print(f"[{ts()}] 语言不符标注 {mark_stats['annotated']} 行，"
			  f"proofed=TRUE {mark_stats['proofed']} 行（每批已立即落库）")
	if args.decisions:
		write_json(args.decisions, result)
	print('下一步：python3 scripts/proofread_logs.py apply '
		  f'--decisions {args.decisions} --allow-clear --apply')
	return 0


def run_check(args) -> int:
	ids = parse_ids(args.ids)
	if not ids:
		print('✖ 需要 --ids，例如 --ids 11036 或 --ids 11036,11038')
		return 2
	rows = LogMaintenance.load_rows()
	owners = LogMaintenance.load_owners()
	client = None
	if not args.no_ai:
		try:
			client = DeepSeekClient.from_config()
		except DeepSeekError as exc:
			print(f'⚠ 未启用 AI（{exc}），只做规则检查')
	result = LogProofreader.inspect(ids, rows, owners, client=client,
									min_support=args.min_support, force=args.force)
	suspicious = 0
	for item in result['rows']:
		print('=' * 20, f"#{item['row_id']}")
		if item.get('error') == 'not_found':
			print('  ✖ logs 表中没有这个 id')
			suspicious += 1
			continue
		print(f"  type={item['type']}  langs={item['langs']}  owners={item['owners']}  "
			  f"proofed={item.get('proofed')}")
		if item.get('skipped') == 'proofed':
			print('  ⏭ 已标记 proofed（AI 曾判定一致），跳过；加 --force 可强制重新校对')
			continue
		print(f"  content={item['content']!r}")
		print(f"  zh={item['current_zh']!r}  en={item['texts'].get('logs_en')!r}  "
			  f"has_zh={item.get('has_zh')}")
		for column in ('logs_zh_tw', 'logs_de', 'logs_ja', 'logs_ko', 'logs_ru',
					   'logs_ug', 'logs_bo'):
			if item['texts'].get(column):
				print(f"  {column}={item['texts'][column]!r}")
		if not item.get('has_zh'):
			print('  注意：logs_zh 为空（可能是附加语言簇或已清空）')
		if item['fallbacks']:
			print(f"  英文回落列（值等于 logs_en）：{item['fallbacks']}")
			suspicious += 1
		if item['known_zh'] and item['type'] == 'module':
			print(f"  同 ROM 中文模块名：{item['known_zh']}")
		if item['mismatches']:
			print('  疑似译文错列：')
			for detail in item['mismatches'][:5]:
				print(f"    {detail['column']}={detail['text']!r} "
					  f"现挂中文={detail['current_zh']!r} 共现中文={detail['likely_zh']!r} "
					  f"(support={detail['support']})")
			suspicious += 1
		if item['error']:
			print(f"  ✖ AI 调用失败：{item['error']}")
			suspicious += 1
		decision = item['decision']
		if decision:
			mark = {'ok': '✓', 'wrong_zh': '→', 'mixed_translations': '⚠',
					'extra_module': '✖'}.get(decision['verdict'], '?')
			print(f"  {mark} AI verdict={decision['verdict']} "
				  f"建议={decision['suggested_zh']!r} ({decision['confidence']:.2f})")
			print(f"    理由：{decision['reason']}")
			print_lang_issues(decision.get('lang_issues') or {})
			if decision['verdict'] != 'ok':
				suspicious += 1
		# 结论
		if decision:
			if decision['verdict'] == 'ok':
				print('  结论：✓ 中文与译文一致')
			elif decision['verdict'] == 'mixed_translations':
				print('  结论：⚠ 译文混装 / 错列，中文可能正确；不要直接改中文')
			elif decision['verdict'] == 'wrong_zh':
				if item.get('has_zh'):
					print(f"  结论：→ 中文可能填错，建议改为 {decision['suggested_zh']!r}")
				else:
					print(f"  结论：本行当前无中文；AI 认为它对应 "
						  f"{decision['suggested_zh']!r}（附加语言簇，中文通常由中文簇提供，不需要写回）")
			elif decision['verdict'] == 'extra_module':
				print('  结论：✖ 可能是额外模块，没有对应中文')
		elif not item.get('has_zh'):
			print('  结论：无中文，规则无法判定；可启用 AI 查它对应哪个中文模块')
		elif item['fallbacks'] or item['mismatches']:
			print('  结论：⚠ 规则检查发现异常（未启用 AI，无法判断中文是否正确）')
		else:
			print('  结论：规则检查未发现异常')
		if decision and not args.no_mark:
			annotated, ok_count, _bad = record_ai_marks([decision])
			if annotated:
				print('  ✓ 已写入语言不符标注（该行不会标记 proofed）')
			elif ok_count:
				print('  ✓ 已标记 proofed=TRUE（后续校对跳过）')
		if args.decisions and decision and decision['verdict'] in ('wrong_zh', 'extra_module'):
			if item['type'] == 'log':
				print('  提示：log 条目的中文改法不进入 apply（需要人工确认翻译）')
	if args.json:
		write_json(args.json, result)
	if args.decisions:
		decisions = [dict(item['decision'], family=f"row|{item['row_id']}")
					 for item in result['rows']
					 if item.get('decision')
					 and item['decision']['verdict'] in ('wrong_zh', 'extra_module')
					 and item['type'] == 'module']
		write_json(args.decisions, {
			'generated_at': result['generated_at'],
			'families': len({item['row_id'] for item in result['rows']}),
			'calls': 0,
			'errors': [],
			'decisions': decisions,
		})
	print(f"\n检查完成：{len(result['rows'])} 条，疑似 {suspicious} 处")
	return 1 if suspicious else 0


def run_scan(args) -> int:
	report = LogProofreader.scan(include_logs=args.include_logs,
								 min_support=args.min_support,
								 mismatch_limit=args.mismatch_limit)
	print_families(report, args.samples)
	if args.report:
		write_json(args.report, report)
	return 0


def run_review(args) -> int:
	if args.scan:
		report = json.loads(Path(args.scan).read_text(encoding='utf-8'))
		# 旧报告里可能有已 proofed 的行：过滤掉，避免重复审核
		rows = LogMaintenance.load_rows()
		families = []
		for family in report['families']:
			alive = [item for item in family['rows']
					 if not rows.get(item['row_id'], {}).get('proofed')]
			if len(alive) < 2:
				continue
			family = dict(family)
			family['rows'] = alive
			family['row_ids'] = [item['row_id'] for item in alive]
			families.append(family)
		report['families'] = families
		print(f"[{ts()}] 从 {args.scan} 载入候选（跳过 proofed 后 {len(families)} 个 family）")
	else:
		report = LogProofreader.scan(include_logs=args.include_logs,
									 min_support=args.min_support,
									 mismatch_limit=args.mismatch_limit)
		count = report['stats']['priority_families'] if not args.all else report['stats']['families']
		print(f"[{ts()}] 扫描得到 {count} 个 family 待复核")
	try:
		client = DeepSeekClient.from_config(model=args.model, max_calls=args.max_calls)
	except DeepSeekError as exc:
		print(f'✖ {exc}')
		return 2
	mark_stats = {'annotated': 0, 'proofed': 0, 'unproofed': 0}

	def flush_marks(parsed) -> None:
		# 每个 family 立即落库：长跑中断也不丢已完成的标注
		if args.no_mark:
			return
		annotated, ok_count, bad_count = record_ai_marks(parsed)
		mark_stats['annotated'] += annotated
		mark_stats['proofed'] += ok_count
		mark_stats['unproofed'] += bad_count

	try:
		def progress(index: int, total: int, family: dict, cached: bool) -> None:
			if index == 1 or index % 10 == 0 or index == total:
				print(f"[{ts()}] 复核 {index}/{total}：{family['zh']} × {len(family['row_ids'])} 行"
					  f"{'（缓存）' if cached else ''}")

		result = LogProofreader.review(
			report['families'], client, only_priority=not args.all,
			limit=args.limit, cache_path=args.cache,
			min_confidence=args.min_confidence, on_progress=progress,
			on_decisions=flush_marks)
	except DeepSeekError as exc:
		print(f'✖ DeepSeek 调用失败：{exc}')
		return 1
	print(f"[{ts()}] 复核 {result['families']} 个 family，实际调用 {result['calls']} 次"
		  f"（缓存 {result['cache'] or '未启用'}）")
	if client.last_usage:
		print(f"    最近一次 usage: {client.last_usage}")
	by_confidence = Counter()
	by_verdict = Counter()
	marks = {'ok': '✓', 'wrong_zh': '→', 'extra_module': '✖',
			 'mixed_translations': '⚠', 'unknown': '?'}
	for decision in result['decisions']:
		if decision['confidence'] >= 0.8:
			level = 'high(>=0.8)'
		elif decision['confidence'] >= 0.5:
			level = 'medium(>=0.5)'
		else:
			level = 'low(<0.5)'
		by_confidence[level] += 1
		verdict = decision.get('verdict', 'unknown')
		by_verdict[verdict] += 1
		mark = marks.get(verdict, '?')
		print(f"  {mark} #{decision['row_id']} {decision['current_zh']!r} → "
			  f"{decision['suggested_zh']!r} ({decision['confidence']:.2f}) "
			  f"[{verdict}] {decision['reason'][:60]}")
	print(f"    confidence: {dict(by_confidence)}　verdict: {dict(by_verdict)}")
	if result['errors']:
		print(f"    ⚠ {len(result['errors'])} 个 family 调用失败，已跳过：")
		for item in result['errors'][:5]:
			print(f"      {item['family']}: {item['error']}")
	decisions = {
		'generated_at': result['generated_at'],
		'families': result['families'],
		'calls': result['calls'],
		'errors': result['errors'],
		'decisions': result['decisions'],
	}
	if not args.no_mark:
		print(f"[{ts()}] 语言不符标注 {mark_stats['annotated']} 行，"
			  f"proofed=TRUE {mark_stats['proofed']} 行（每批已立即落库）")
	if args.decisions:
		write_json(args.decisions, decisions)
	else:
		default = str(Path(args.cache).with_name('proofread_decisions.json')
					  if args.cache else Path('/tmp/proofread_decisions.json'))
		write_json(default, decisions)
	return 0


def run_apply(args) -> int:
	payload = json.loads(Path(args.decisions).read_text(encoding='utf-8'))
	decisions = payload.get('decisions', payload) if isinstance(payload, dict) else payload
	plan = LogProofreader.plan(decisions, min_confidence=args.min_confidence,
							   allow_clear=args.allow_clear)
	print(f"[{ts()}] 计划：rename {plan['stats']['rename']}，clear {plan['stats']['clear']}，"
		  f"译文混装 {plan['stats']['mixed_translations']}，跳过 {plan['stats']['skipped']}，"
		  f"掩码更新 {plan['stats']['mask_updates']} 条记录")
	for action in plan['actions']:
		target = action['suggested_zh'] or '（清空中文）'
		print(f"  {action['action']}: #{action['row_id']} {action['current_zh']!r} → {target!r} "
			  f"({action['confidence']:.2f}) 掩码 {action['mask_updates']} 处；"
			  f"{action['reason'][:50]}")
	if plan['mixed']:
		print(f"  ⚠ 以下 {len(plan['mixed'])} 行属于译文混装（中文可能正确，问题在译文错列），"
			  f"未自动改动：")
		for item in plan['mixed'][:8]:
			print(f"    #{item['row_id']} zh={item['current_zh']!r} "
				  f"({item['confidence']:.2f}) {item['reason'][:60]}")
	skipped = Counter(item['reason'] for item in plan['skipped'])
	if skipped:
		print(f"  跳过原因：{dict(skipped)}")
	if not args.apply:
		print('\n dry-run：确认无误后加 --apply 写库（写前自动备份）')
		return 0
	if not plan['actions'] and not plan['mask_updates']:
		print('没有需要写库的动作')
		return 0
	result = LogProofreader.apply(plan, apply=True, backup=not args.no_backup,
								  backup_path=args.backup)
	if result.get('backup'):
		print(f"备份已写入 {result['backup']}")
	print(f"[{ts()}] 已写库：{result['stats']['rename']} 行改名，"
		  f"{result['stats']['clear']} 行清空中文，{result['stats']['mask_updates']} 条引用掩码更新")
	print('建议随后运行：python3 scripts/maintain_logs.py audit')
	return 0


def main() -> int:
	parser = argparse.ArgumentParser(
		description='日志多语言校对（规则扫描 + DeepSeek 复核 + 安全写回）')
	sub = parser.add_subparsers(dest='action', required=True)

	batch = sub.add_parser(
		'batch-review',
		help='批量校对（默认只估算；--run 执行）：--batch-size 10 全量多语言行 / --batch-size 1 --all 逐条')
	batch.add_argument('--batch-size', type=int, default=10, help='每批行数（默认 10；1 = 逐条）')
	batch.add_argument('--all', action='store_true', help='包含单语言行（不推荐，仅逐条/验证时用）')
	batch.add_argument('--min-langs', type=int, default=2, help='默认只处理 ≥ 该语言数的行（默认 2）')
	batch.add_argument('--types', default='module,log', help='module,log 的组合（默认两者）')
	batch.add_argument('--limit-rows', type=int, default=0, help='只处理前 N 行（调试/抽样）')
	batch.add_argument('--run', action='store_true', help='实际调用 API（默认只估算）')
	batch.add_argument('--allow-expensive', action='store_true',
					   help='允许超过 800 万 tokens / 5,000 次调用（逐条全量必须显式开启）')
	batch.add_argument('--cache', default='/tmp/proofread_batch_cache.json')
	batch.add_argument('--decisions', default='/tmp/proofread_batch_decisions.json')
	batch.add_argument('--max-calls', type=int, default=None, help='本次最多调用多少次 API')
	batch.add_argument('--progress-every', type=int, default=10,
					   help='每多少个批次打印一次进度（默认 10；设 1 则每批都打印 id）')
	batch.add_argument('--include-proofed', action='store_true',
					   help='连已 proofed 的行一起复核（默认跳过）')
	batch.add_argument('--json', help='把估算 / 结果写入 JSON')
	batch.add_argument('--no-mark', action='store_true',
					   help='不写 proofed / lang_issues（完全只读）')

	check = sub.add_parser('check', help='校对指定 logs.id（不改内容；ok 时写 proofed）')
	check.add_argument('--ids', required=True, help='逗号分隔的 logs.id，如 11036,11038 或 11040-11042')
	check.add_argument('--no-ai', action='store_true', help='只做规则检查，不调用 AI')
	check.add_argument('--json', help='把完整结果写入 JSON')
	check.add_argument('--decisions', help='把 AI 的 wrong_zh / extra_module 结论写成 decisions JSON')
	check.add_argument('--min-support', type=int, default=10,
					   help='译文错列共现统计的最小支持数（默认 10，避免常见短译文误报）')
	check.add_argument('--force', action='store_true',
					   help='即使该行已标记 proofed 也重新校对')
	check.add_argument('--no-mark', action='store_true',
					   help='不写 proofed / lang_issues')

	scan = sub.add_parser('scan', help='规则扫描（不调用 AI）')
	scan.add_argument('--report', help='把扫描结果写入 JSON')
	scan.add_argument('--samples', type=int, default=8, help='打印多少个候选')
	scan.add_argument('--include-logs', action='store_true',
					  help='同时扫描 log 条目（默认只扫描 module 模块名）')
	scan.add_argument('--min-support', type=int, default=3,
					  help='译文错列共现统计的最小支持数（默认 3）')
	scan.add_argument('--mismatch-limit', type=int, default=200,
					  help='报告多少条疑似译文错列（默认 200）')

	review = sub.add_parser('review', help='调用 DeepSeek 复核候选')
	review.add_argument('--scan', help='使用 scan 写出的 JSON（默认重新扫描）')
	review.add_argument('--all', action='store_true', help='复核全部候选（默认只复核 priority）')
	review.add_argument('--limit', type=int, default=0, help='最多复核多少个 family')
	review.add_argument('--cache', default='/tmp/proofread_cache.json',
						help='prompt 缓存文件（默认 /tmp/proofread_cache.json）')
	review.add_argument('--decisions', help='decisions 输出路径')
	review.add_argument('--model', help='覆盖 config 的 deepseek_model')
	review.add_argument('--max-calls', type=int, default=None, help='本次最多调用多少次 API')
	review.add_argument('--min-confidence', type=float, default=0.0,
						help='低于该置信度的结果不写入 decisions（默认 0，全部保留；apply 时再按 0.8 过滤）')
	review.add_argument('--no-mark', action='store_true',
						help='不写 proofed / lang_issues（完全只读）')
	review.add_argument('--include-logs', action='store_true')
	review.add_argument('--min-support', type=int, default=3)
	review.add_argument('--mismatch-limit', type=int, default=200)

	apply_cmd = sub.add_parser('apply', help='执行 decisions（默认 dry-run）')
	apply_cmd.add_argument('--decisions', required=True)
	apply_cmd.add_argument('--apply', action='store_true', help='实际写库')
	apply_cmd.add_argument('--allow-clear', action='store_true',
						   help='允许清空附加语言簇窄行的中文（并去掉掩码中文位）')
	apply_cmd.add_argument('--min-confidence', type=float, default=0.8)
	apply_cmd.add_argument('--backup', help='备份路径（默认系统临时目录）')
	apply_cmd.add_argument('--no-backup', action='store_true')

	args = parser.parse_args()
	if args.action == 'batch-review':
		return run_batch_review(args)
	if args.action == 'check':
		return run_check(args)
	if args.action == 'scan':
		return run_scan(args)
	if args.action == 'review':
		return run_review(args)
	return run_apply(args)


if __name__ == '__main__':
	sys.exit(main())
