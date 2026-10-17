"""
修复 logs 表中「content 不是简体中文」的记录：尽量补齐 logs_zh，并同步 content。

判定目标：
    logs_zh 为空、或不含汉字、或含日文假名 —— 都视为「没有简体中文」。
    （content 的语义是「优先简体中文，无中文时取英文/原文」，所以补到 logs_zh 后
      还要把仍是外文的 content / content_hash 一并改成中文。）

补全顺序（越靠前越可信，最终按票数加权决定，冲突则不写）：
    0. content 本身是简体中文（无假名、无繁体特征、且不等于其它语言列）→ 直接采用；
    1. 精确匹配：同一 type 下，另一行的任意外文文本与本行完全相同且该行有中文 → 采用；
    2. 同 ROM 模块对齐：roms/dev.logs 里同一模块会被多门语言各引用一次（掩码不同），
       按「中文模块名 + 条目数」把缺中文的位置对齐到已有完整中文的同类位置；
    3. 抓取中文日志：对仍有缺口的 ROM 调小米接口取 zh_CN 日志，按「模块名 + 条目数」
       对齐后填充；
    4. 可选 --from-tw：用 opencc / zhconv 把繁体转简体（未安装则跳过并提示）。

写入只补不覆盖：
    - logs_zh 没有简体中文时才写；
    - content 没有简体中文时才改成中文，并同步 content_hash；
    - 补完后顺手把 roms.logs / dev.logs 中对应簇的掩码补上中文位（第 0 位），
      否则导出侧按掩码过滤时仍看不到中文。

文本判定（中文 / 繁体 / 日文假名 / 繁转简）统一走 miroms.logs_text.LogText，
载入与引用结构统一走 miroms.logs_maintenance.LogMaintenance。

默认 dry-run，只输出统计与样本；加 --apply 才落库。

用法：
    python3 data/scripts/fix_non_zh_logs.py                        # dry-run 报告
    python3 data/scripts/fix_non_zh_logs.py --apply                # 落库（含抓取）
    python3 data/scripts/fix_non_zh_logs.py --apply --no-fetch     # 只用本地策略
    python3 data/scripts/fix_non_zh_logs.py --apply --max-fetch 200 --sleep 0.3
    python3 data/scripts/fix_non_zh_logs.py --apply --from-tw
    python3 data/scripts/fix_non_zh_logs.py --no-fetch --zh-map /tmp/zh_map.json
    python3 data/scripts/fix_non_zh_logs.py --report /tmp/fix_non_zh.json
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import common
from miroms.logs_maintenance import LogMaintenance
from miroms.logs_store import LogStore
from miroms.logs_text import LogText

# 文本判定全部委托给 LogText（保留原有函数名，减少调用处改动）
has_cjk = LogText.has_cjk
is_zh_ok = LogText.is_chinese
looks_simplified = LogText.looks_simplified

# 票数权重：精确匹配 / 繁体转换最可信，位置对齐需要交叉校验加持
WEIGHT_CONTENT = 100
WEIGHT_EXACT = 50
WEIGHT_ALIGN_VALIDATED = 12
WEIGHT_ALIGN_WEAK = 4
WEIGHT_FETCH_VALIDATED = 15
WEIGHT_FETCH_ALIGN = 10
WEIGHT_FETCH_GUESS = 5
WEIGHT_TW = 30
WEIGHT_MANUAL = 1000

# 低于该票数且没有任何交叉校验证据的候选不写（避免单次位置猜测写坏数据）
ACCEPT_MIN_SCORE = 8


# ==================== 数据载入 ====================

def load_rows() -> dict:
	"""载入 logs 全表：{id: {'id','type','content','texts'}}（不做 content→zh 回填）"""
	return LogMaintenance.load_rows()


def load_owners() -> dict:
	"""{('roms'|'dev', id): refs}，只保留合法的 ID 引用结构"""
	return LogMaintenance.load_owners()


# ==================== 决策（投票） ====================

class Decisions:
	"""每行收集多个来源的中文候选，按权重投票，冲突不写"""

	def __init__(self):
		self.votes = defaultdict(lambda: defaultdict(int))
		self.strong = defaultdict(bool)
		self.reasons = defaultdict(set)

	def add(self, row_id: int, zh: str, weight: int, reason: str, checked: int = 0):
		zh = LogStore.normalize(zh)
		if not zh or not is_zh_ok(zh):
			return
		self.votes[row_id][zh] += weight
		self.reasons[row_id].add(reason)
		if checked:
			self.strong[row_id] = True

	def has(self, row_id: int) -> bool:
		return bool(self.votes.get(row_id))

	def max_score(self, row_id: int) -> int:
		return max(self.votes[row_id].values()) if self.votes.get(row_id) else 0

	def result(self, row_id: int):
		"""返回 (zh|None, reason)；冲突/证据不足时 zh 为 None"""
		votes = self.votes.get(row_id)
		if not votes:
			return None, 'no_candidate'
		ranked = sorted(votes.items(), key=lambda item: -item[1])
		best_zh, best_score = ranked[0]
		if len(ranked) > 1 and ranked[1][1] == best_score:
			return None, 'conflict'
		if best_score < ACCEPT_MIN_SCORE and not self.strong.get(row_id):
			return None, 'weak_evidence'
		return best_zh, 'filled'


def validate(row: dict, zh: str, mapping: dict):
	"""用精确翻译表交叉校验：候选中文必须与该行已知外文的既有译法一致

	返回 (ok, checked)：checked 表示命中了多少条已知映射。
	"""
	ok, checked = True, 0
	for column, text in row['texts'].items():
		if column == LogStore.ZH_COLUMN or not text:
			continue
		allowed = mapping.get((row['type'], column, text))
		if not allowed:
			continue
		checked += 1
		if zh not in allowed:
			ok = False
	return ok, checked


# ==================== 阶段 0 / 1：内容与精确匹配 ====================

def build_translation_map(rows: dict) -> dict:
	"""{(type, 语言列, 文本): {中文...}}，只收录已有可用中文的行"""
	mapping = defaultdict(set)
	for row in rows.values():
		zh = row['texts'].get(LogStore.ZH_COLUMN)
		if not is_zh_ok(zh):
			continue
		for column, text in row['texts'].items():
			if column == LogStore.ZH_COLUMN or not text:
				continue
			mapping[(row['type'], column, LogStore.normalize(text))].add(LogStore.normalize(zh))
	return mapping


def apply_content(rows: dict, targets: set, decisions: Decisions, stats: dict):
	"""阶段 0：content 本身就是简体中文的，直接作为 logs_zh"""
	for row_id in targets:
		row = rows[row_id]
		if looks_simplified(row['content'], row['texts']):
			decisions.add(row_id, row['content'], WEIGHT_CONTENT, 'content')
			stats['content'] += 1


def apply_exact(rows: dict, targets: set, mapping: dict, decisions: Decisions, stats: dict):
	"""阶段 1：同一 type 下任意外文文本完全相同的行，复用其中文"""
	for row_id in targets:
		row = rows[row_id]
		for column, text in row['texts'].items():
			if column == LogStore.ZH_COLUMN or not text:
				continue
			allowed = mapping.get((row['type'], column, LogStore.normalize(text)))
			if not allowed:
				continue
			for zh in allowed:
				decisions.add(row_id, zh, WEIGHT_EXACT, f'exact:{column}')
				stats['exact'] += 1


# ==================== 阶段 2：同 ROM 模块名对齐 ====================

def iter_ref_items(refs: list):
	"""遍历引用结构里的 (模块ID, [条目ID...])（掩码由 LogMaintenance.iter_refs 统一解析）"""
	for module_id, entries, _ in LogMaintenance.iter_refs(refs):
		yield module_id, entries


def owner_row_ids(refs: list):
	"""引用结构涉及的全部 logs 行 id（模块 + 条目）"""
	for module_id, entries in iter_ref_items(refs):
		yield module_id
		yield from entries


def module_candidates(rows: dict, module_id: int, mapping: dict) -> set:
	"""推断一个模块行的中文名候选（直接中文 / 由外文反查 / content）"""
	row = rows.get(module_id)
	if not row:
		return set()
	name = row['texts'].get(LogStore.ZH_COLUMN)
	if is_zh_ok(name):
		return {LogStore.normalize(name)}
	candidates = set()
	for column, text in row['texts'].items():
		if column == LogStore.ZH_COLUMN or not text:
			continue
		for zh in mapping.get((row['type'], column, LogStore.normalize(text)), ()):
			candidates.add(zh)
	if looks_simplified(row['content'], row['texts']):
		candidates.add(LogStore.normalize(row['content']))
	candidates.discard('')
	return candidates


def module_template(rows: dict, module_id: int, entries: list):
	"""模块位置的中文是否完整（模块名 + 全部条目）；完整则返回中文模块名"""
	row = rows.get(module_id)
	if not row:
		return None
	name = row['texts'].get(LogStore.ZH_COLUMN)
	if not is_zh_ok(name):
		return None
	for entry_id in entries:
		entry = rows.get(entry_id)
		if not entry or not is_zh_ok(entry['texts'].get(LogStore.ZH_COLUMN)):
			return None
	return LogStore.normalize(name)


def propose(rows: dict, targets: set, mapping: dict, decisions: Decisions, stats: dict,
			row_id: int, zh: str, weight_checked: int, weight_weak: int,
			reason: str, stat_prefix: str) -> bool:
	"""候选先过交叉校验再投票；返回是否被采纳"""
	if row_id not in targets or not is_zh_ok(zh):
		return False
	ok, checked = validate(rows[row_id], zh, mapping)
	if not ok:
		stats[f'{stat_prefix}_rejected'] += 1
		return False
	decisions.add(row_id, zh, weight_checked if checked else weight_weak, reason, checked)
	stats[f'{stat_prefix}_validated' if checked else f'{stat_prefix}_weak'] += 1
	return True


def apply_module_alignment(rows: dict, targets: set, owners: dict, mapping: dict,
						   decisions: Decisions, stats: dict):
	"""阶段 2：同一 ROM 内按「中文模块名 + 条目数」对齐同一模块的其它语言位置"""
	for (table, owner_id), refs in owners.items():
		items = list(iter_ref_items(refs))
		templates = defaultdict(list)
		for module_id, entries in items:
			name = module_template(rows, module_id, entries)
			if name:
				templates[name].append(entries)
		if not templates:
			continue

		for module_id, entries in items:
			if not any(row_id in targets for row_id in [module_id] + entries):
				continue

			# 候选模块名 -> 该名下的条目中文序列集合
			sequences = defaultdict(set)
			for name in module_candidates(rows, module_id, mapping):
				for template_entries in templates.get(name, ()):
					if len(template_entries) != len(entries):
						continue
					sequences[name].add(tuple(
						LogStore.normalize(rows[entry_id]['texts'].get(LogStore.ZH_COLUMN))
						for entry_id in template_entries
					))
			# 同名模板给出不同译文时不猜
			usable = {name: next(iter(seqs)) for name, seqs in sequences.items() if len(seqs) == 1}
			if not usable:
				if sequences:
					stats['align_template_conflict'] += 1
				continue
			unique = set(usable.values())
			if len(unique) > 1:
				stats['align_template_conflict'] += 1
				continue
			sequence = unique.pop()

			reason = f'rom-align:{table}:{owner_id}'
			if len(usable) == 1:
				name = next(iter(usable))
				propose(rows, targets, mapping, decisions, stats, module_id, name,
						WEIGHT_ALIGN_VALIDATED, WEIGHT_ALIGN_WEAK, reason, 'align')
			for index, entry_id in enumerate(entries):
				propose(rows, targets, mapping, decisions, stats, entry_id, sequence[index],
						WEIGHT_ALIGN_VALIDATED, WEIGHT_ALIGN_WEAK, reason, 'align')


# ==================== 阶段 3：抓取中文日志 ====================

def apply_fetched_structure(rows: dict, targets: set, pending: set, refs: list, obj: dict,
							mapping: dict, decisions: Decisions, stats: dict,
							rom_id: int) -> bool:
	"""把接口返回的中文结构按「模块名 + 条目数」对齐到该 ROM 的引用位置

	返回是否至少有一个位置在结构上匹配（用于区分「接口没给中文」和「结构对不上」）。
	"""
	fetched = {}
	for name, lines in LogStore.items_of(obj):
		name = LogStore.normalize(name)
		if name and name not in fetched:
			fetched[name] = [LogStore.normalize(line) for line in lines]
	if not fetched:
		return False

	aligned = False
	for module_id, entries in iter_ref_items(refs):
		row_ids = [module_id] + entries
		if not any(row_id in pending for row_id in row_ids):
			continue

		matching = []
		for name in module_candidates(rows, module_id, mapping):
			lines = fetched.get(name)
			if lines is not None and len(lines) == len(entries):
				matching.append((name, lines))
		via_name = bool(matching)
		if not matching:
			# 模块名无法解析时，只有「条目数唯一」才敢按序号对齐（弱证据）
			same_count = [(name, lines) for name, lines in fetched.items()
						  if len(lines) == len(entries)]
			if len(same_count) != 1:
				continue
			matching = same_count

		sequences = {tuple(lines) for _, lines in matching}
		if len(sequences) > 1:
			stats['fetch_conflict'] += 1
			continue
		sequence = sequences.pop()
		names = {name for name, _ in matching}
		aligned = True
		weight_weak = WEIGHT_FETCH_ALIGN if via_name else WEIGHT_FETCH_GUESS

		reason = f'api:{rom_id}'
		if len(names) == 1:
			propose(rows, targets, mapping, decisions, stats, module_id, next(iter(names)),
					WEIGHT_FETCH_VALIDATED, weight_weak, reason, 'fetch')
		for index, entry_id in enumerate(entries):
			propose(rows, targets, mapping, decisions, stats, entry_id, sequence[index],
					WEIGHT_FETCH_VALIDATED, weight_weak, reason, 'fetch')

	return aligned


def fetch_pending_roms(rows: dict, targets: set, owners: dict, mapping: dict,
					   decisions: Decisions, stats: dict, args) -> None:
	"""阶段 3：对仍有缺口的 ROM 抓 zh_CN 日志，按模块名 + 条目数对齐后填充"""
	pending = {row_id for row_id in targets if decisions.result(row_id)[0] is None}
	if not pending:
		print('阶段 3：没有需要抓取的记录')
		return

	rom_ids = set()
	for (table, owner_id), refs in owners.items():
		if table != 'roms':
			continue
		if any(row_id in pending for row_id in owner_row_ids(refs)):
			rom_ids.add(owner_id)

	rom_ids = sorted(rom_ids, reverse=True)
	if args.max_fetch:
		rom_ids = rom_ids[:args.max_fetch]
	print(f"\n阶段 3：{len(rom_ids)} 个 ROM 需要抓取中文日志"
		  f"{'（--max-fetch 截断）' if args.max_fetch else ''}")

	if not rom_ids:
		return

	import fetch_changelog as fc

	info_map = {}
	for i in range(0, len(rom_ids), 500):
		chunk = rom_ids[i:i + 500]
		sql = ("SELECT id, device, code, region, branch, android, version, zone "
			   f"FROM roms WHERE id IN ({','.join(['%s'] * len(chunk))})")
		for row in common.DatabaseManager.query_all(sql, params=tuple(chunk)) or []:
			info_map[int(row[0])] = {
				'device': row[1], 'code': row[2], 'region': row[3], 'branch': row[4],
				'android': row[5], 'version': row[6], 'zone': row[7],
			}

	total = len(rom_ids)
	for index, rom_id in enumerate(rom_ids, 1):
		info = info_map.get(rom_id)
		if not info:
			stats['fetch_missing_info'] += 1
			continue

		# 该 ROM 下仍有缺口的行（其它 ROM 可能已经补过）
		owner_key = ('roms', rom_id)
		refs = owners.get(owner_key, [])
		pending_rows = {row_id for row_id in owner_row_ids(refs) if row_id in pending}
		if not pending_rows:
			continue

		if index % 100 == 0 or index == 1:
			print(f"\r  抓取 {index}/{total}：rom {rom_id} {info['device']} {info['version']}", end='', flush=True)

		try:
			form = fc.build_changelog_form(info)
			result = fc.get_changelog_for_device(info, 'zh_CN', form=form)
		except Exception as exc:
			stats['fetch_failed'] += 1
			if stats['fetch_failed'] == 1:
				print(f"\n  ✖ 首个请求失败（rom {rom_id}）：{type(exc).__name__}: {exc}")
			if args.sleep:
				time.sleep(args.sleep)
			continue

		if args.sleep:
			time.sleep(args.sleep)

		stats['fetched'] += 1
		if not result:
			stats['fetch_failed'] += 1
			continue

		log = result.get('changelog')
		if not log:
			stats['api_empty'] += 1
			continue

		try:
			obj = json.loads(log)
		except (json.JSONDecodeError, TypeError):
			stats['api_bad_json'] += 1
			continue

		if not has_cjk(json.dumps(obj, ensure_ascii=False)):
			# 接口回落英文/原文，没有中文可用
			stats['api_non_zh'] += 1
			continue

		if not apply_fetched_structure(rows, targets, pending, refs, obj, mapping,
									   decisions, stats, rom_id):
			stats['fetch_shape_mismatch'] += 1
			continue
		for row_id in pending_rows:
			if decisions.result(row_id)[0] is not None:
				pending.discard(row_id)
		if not any(decisions.result(row_id)[0] is not None for row_id in pending_rows):
			stats['fetch_no_progress'] += 1

	print()


# ==================== 阶段 4：繁体转简体（可选） ====================

def load_tw_converter():
	"""返回 (库名, 繁转简函数) 或 (None, None)；两个库都没装时跳过"""
	return LogText.converter() or (None, None)


def apply_from_tw(rows: dict, targets: set, decisions: Decisions, stats: dict):
	"""阶段 4：只用繁体行时，退而求其次做繁→简转换（需显式 --from-tw）"""
	name, _ = load_tw_converter()
	if not name:
		print('⚠ 未安装 opencc / zhconv，--from-tw 已跳过'
			  '（pip install opencc 或 pip install zhconv）')
		stats['tw_skipped'] += 1
		return
	print(f'阶段 4：使用 {name} 做繁体转简体')
	for row_id in targets:
		if decisions.result(row_id)[0]:
			continue
		zh = LogText.to_simplified(rows[row_id]['texts'].get('logs_zh_tw'))
		if zh:
			decisions.add(row_id, zh, WEIGHT_TW, f'tw:{name}')
			stats['tw'] += 1


# ==================== 写入 ====================

def update_ref_mask(refs: list, rows: dict, filled: set, zh_ok_ids: set) -> bool:
	"""给引用了新增中文的簇补语言掩码第 0 位（简体中文），返回是否有改动"""
	changed = False
	for item in refs:
		if not (isinstance(item, list) and len(item) >= 2):
			continue
		try:
			module_id = int(item[0])
			entries = [int(x) for x in item[1]]
		except (TypeError, ValueError):
			continue
		mask = int(item[2]) if len(item) > 2 and isinstance(item[2], int) else 0
		if mask & 1:
			continue
		module_ok = module_id in filled or module_id in zh_ok_ids
		entry_ok = any(entry_id in filled or entry_id in zh_ok_ids for entry_id in entries)
		if module_ok and (entry_ok or not entries):
			if len(item) == 2:
				item.append(mask | 1)
			else:
				item[2] = mask | 1
			changed = True
	return changed


def write_plans(rows: dict, plans: dict, owners: dict, stats: dict, dry_run: bool) -> None:
	"""落库：补 logs_zh / content / content_hash，并修正 roms/dev 的语言掩码"""
	filled = set(plans)
	updates = []
	for row_id, zh in plans.items():
		row = rows[row_id]
		current_zh = row['texts'].get(LogStore.ZH_COLUMN)
		content = row['content'] or ''
		sets, params = [], []
		if not is_zh_ok(current_zh):
			sets.append('`logs_zh` = %s')
			params.append(zh)
		if not is_zh_ok(content):
			sets.append('`content` = %s')
			params.append(zh)
			sets.append('`content_hash` = %s')
			params.append(LogStore.hash_text(zh))
		if sets:
			sets.append('`proofed` = 0')
			sets.append('`complete` = 0')
			sets.append('`lang_issues` = NULL')
			updates.append((row_id, sets, params))
			if not is_zh_ok(content):
				stats['content_rewritten'] += 1

	if dry_run:
		print(f'\n[dry-run] 将更新 {len(updates)} 行 logs')
		return

	if not updates and not filled:
		return

	zh_ok_ids = {
		row_id for row_id, row in rows.items()
		if is_zh_ok(row['texts'].get(LogStore.ZH_COLUMN))
	}
	mask_updates = []
	for (table, owner_id), refs in owners.items():
		if update_ref_mask(refs, rows, filled, zh_ok_ids):
			mask_updates.append((table, owner_id, json.dumps(refs, ensure_ascii=False)))

	with LogStore.write_lock():
		for row_id, sets, params in updates:
			common.DatabaseManager.execute(
				f"UPDATE `logs` SET {', '.join(sets)} WHERE `id` = %s",
				params=tuple(params + [row_id]), raise_on_error=True,
			)
			stats['rows_updated'] += 1
		for table, owner_id, value in mask_updates:
			common.DatabaseManager.execute(
				f"UPDATE `{table}` SET `logs` = %s WHERE `id` = %s",
				params=(value, owner_id), raise_on_error=True,
			)
		stats['masks_updated'] = len(mask_updates)

	LogStore.refresh_cache()


# ==================== 报告 ====================

def build_report(rows: dict, targets: set, decisions: Decisions, notes: dict,
				 stats: dict) -> dict:
	unresolved = []
	conflicts = []
	by_reason = defaultdict(int)

	for row_id in sorted(targets):
		zh, reason = decisions.result(row_id)
		if zh:
			continue
		languages = [column for column in LogStore.LANG_COLUMNS
					 if column != LogStore.ZH_COLUMN and rows[row_id]['texts'].get(column)]
		item = {
			'id': row_id,
			'type': rows[row_id]['type'],
			'content': (rows[row_id]['content'] or '')[:160],
			'languages': languages,
			'reason': reason,
			'reasons': sorted(decisions.reasons.get(row_id, set())) + sorted(notes.get(row_id, set())),
			'votes': dict(decisions.votes.get(row_id, {})),
		}
		if reason == 'conflict':
			conflicts.append(item)
		else:
			unresolved.append(item)
		by_reason[reason] += 1

	return {
		'unresolved_count': len(unresolved),
		'conflict_count': len(conflicts),
		'by_reason': dict(by_reason),
		'unresolved': unresolved,
		'conflicts': conflicts,
	}


def print_summary(stats: dict, report: dict, dry_run: bool) -> None:
	print('\n' + '=' * 60)
	print(f"目标记录：{stats['targets']} 行"
		  f"（logs_zh 缺失/非中文 {stats['targets_no_zh']}，zh 非中文 {stats['targets_bad_zh']}）")
	print(f"可补全：{stats['plans']} 行"
		  f"（手工 {stats['manual']} / content {stats['content']} / 精确匹配 {stats['exact']} / "
		  f"位置对齐 {stats['align_validated'] + stats['align_weak']}"
		  f"（拒绝 {stats['align_rejected']}） / "
		  f"抓取 {stats['fetch_validated'] + stats['fetch_weak']} / 繁体转换 {stats['tw']}）")
	print(f"未解决：{report['unresolved_count']} 行，冲突：{report['conflict_count']} 行"
		  f"（{report['by_reason']}）")
	if not dry_run:
		print(f"已写库：logs {stats['rows_updated']} 行，content 改写 {stats['content_rewritten']} 行，"
			  f"掩码更新 {stats['masks_updated']} 条 roms/dev")
	else:
		print('（dry-run：未写库，加 --apply 执行）')
	print('=' * 60)


# ==================== 主流程 ====================

def main() -> None:
	parser = argparse.ArgumentParser(description='补齐 logs 表中缺失的简体中文日志')
	parser.add_argument('--apply', action='store_true', help='实际写库（默认 dry-run）')
	parser.add_argument('--no-fetch', action='store_true', help='不调用小米接口，只用本地策略')
	parser.add_argument('--max-fetch', type=int, default=0, help='最多抓取多少个 ROM，0 表示不限')
	parser.add_argument('--sleep', type=float, default=0.3, help='每次接口请求后的间隔秒数，默认 0.3')
	parser.add_argument('--min-id', type=int, default=0, help='只处理 id 大于该值的 logs 行')
	parser.add_argument('--limit', type=int, default=0, help='最多处理多少条待补记录，0 表示不限')
	parser.add_argument('--from-tw', action='store_true', help='最后尝试用 opencc/zhconv 把繁体转简体')
	parser.add_argument('--zh-map', help='手工补译 JSON：{"logs.id": "简体中文"}，优先级最高')
	parser.add_argument('--report', help='把未解决/冲突明细写入该 JSON 文件')
	args = parser.parse_args()

	print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始修复非简体中文日志"
		  f"{'（dry-run）' if not args.apply else ''}")

	rows = load_rows()
	targets = {
		row_id for row_id, row in rows.items()
		if not is_zh_ok(row['texts'].get(LogStore.ZH_COLUMN))
	}
	if args.min_id:
		targets = {row_id for row_id in targets if row_id > args.min_id}
	if args.limit:
		targets = set(sorted(targets)[:args.limit])

	no_zh = sum(1 for row_id in targets if not rows[row_id]['texts'].get(LogStore.ZH_COLUMN))
	stats = defaultdict(int)
	stats.update({
		'targets': len(targets),
		'targets_no_zh': no_zh,
		'targets_bad_zh': len(targets) - no_zh,
	})
	print(f"logs 共 {len(rows)} 行，待补简体中文 {len(targets)} 行"
		  f"（无 zh 列 {no_zh}，zh 列非中文 {len(targets) - no_zh}）")

	if not targets:
		print('没有需要处理的记录')
		return

	owners = load_owners()
	print(f"已载入 {len(owners)} 条 roms/dev 引用记录")

	mapping = build_translation_map(rows)
	decisions = Decisions()
	notes = defaultdict(set)

	apply_content(rows, targets, decisions, stats)
	print(f"阶段 0（content 即中文）：{stats['content']} 行")

	apply_exact(rows, targets, mapping, decisions, stats)
	print(f"阶段 1（精确匹配）：{stats['exact']} 条候选")

	if args.zh_map:
		payload = json.loads(Path(args.zh_map).read_text(encoding='utf-8'))
		applied = skipped = 0
		for key, value in payload.items():
			try:
				row_id = int(key)
			except (TypeError, ValueError):
				skipped += 1
				continue
			zh = LogStore.normalize(value)
			if row_id not in targets or not is_zh_ok(zh):
				skipped += 1
				continue
			decisions.add(row_id, zh, WEIGHT_MANUAL, 'manual')
			applied += 1
		stats['manual'] = applied
		print(f"手工补译：{applied} 行（跳过 {skipped} 条，不在目标集或译文无效）")
	else:
		stats['manual'] = 0

	apply_module_alignment(rows, targets, owners, mapping, decisions, stats)
	print(f"阶段 2（同 ROM 模块对齐）：有效 {stats['align_validated']} 条，弱证据 {stats['align_weak']} 条，"
		  f"校验拒绝 {stats['align_rejected']} 条，模板冲突 {stats['align_template_conflict']} 条")

	if not args.no_fetch:
		fetch_pending_roms(rows, targets, owners, mapping, decisions, stats, args)
	else:
		print('阶段 3：已跳过（--no-fetch）')

	if args.from_tw:
		apply_from_tw(rows, targets, decisions, stats)

	plans = {}
	for row_id in targets:
		zh, reason = decisions.result(row_id)
		if zh:
			plans[row_id] = zh
		else:
			notes[row_id].add(reason)

	stats['plans'] = len(plans)
	report = build_report(rows, targets, decisions, notes, stats)
	write_plans(rows, plans, owners, stats, dry_run=not args.apply)
	print_summary(stats, report, dry_run=not args.apply)

	if args.report:
		path = Path(args.report)
		path.parent.mkdir(parents=True, exist_ok=True)
		payload = {
			'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
			'dry_run': not args.apply,
			'stats': dict(stats),
			**report,
		}
		path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
		print(f'报告已写入 {path}')

	if plans and not args.apply:
		sample_ids = sorted(plans)[:10]
		print('\n补全样本：')
		for row_id in sample_ids:
			print(f"  #{row_id} [{rows[row_id]['type']}] "
				  f"{(rows[row_id]['content'] or '')[:50]!r} -> {plans[row_id][:50]!r}")


if __name__ == '__main__':
	main()
