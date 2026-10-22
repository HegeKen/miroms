"""
miroms.logs_proofread - 日志多语言校对（规则扫描 + DeepSeek 复核 + 安全写回）

背景：logs 表按「语言结构指纹」聚类，同一 ROM 的结构不一致时，其他语言会被并入
附加模块。早期用「模块名 / 条目数」猜测补译的脚本，可能把中文模块名填错：
例如 id=11036 的德文是 Interkonnektivität，中文却被填成「其他」，与 id=11038
（Datenschutz und Sicherheit → 安全隐私）一起制造出多个同名中文模块。

本模块把这类问题做成可重复的流程：

1. ``scan``（纯规则，不调用 AI）
   - ``zh_conflict``：同一个 ROM 内多个 module 行的中文名相同，但**真实外文**
     （排除等于本行 logs_en 的英文回落）互不相同 —— 至少有一行的中文名填错了；
   - ``translation_mismatch``：某行某门外语在全库共现统计里几乎只与**另一个中文**
     一起出现（例如 ja 译文属于「安全隐私」却被挂在「设备互联」行上），
     多为译文错列 / 互换（只报告，不自动改）。
2. ``review``：把 zh_conflict 候选按 family 批量交给 DeepSeek，要求它从该 ROM 的
   中文模块名列表里选择每一行真正对应的名字（或 null = 额外模块），并给出置信度。
3. ``plan``：把 AI 结论转成动作
   - ``rename``：完整行（语言多、带 logs_en）直接改正 logs_zh / content；
   - ``clear``：附加语言簇的窄行（语言少、无 logs_en）只清掉中文，并把引用掩码里的
     中文位去掉（中文由该 ROM 自己的中文簇提供，避免导出重复）；
   - 低置信度 / 证据不足 → 只报告。
4. ``apply``：写库（默认 dry-run），写前备份，写后刷新导出缓存。

典型用法见 scripts/proofread_logs.py。
"""
import copy
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from miroms.constants import CHANGELOG_LOCALES
from miroms.database import DatabaseManager
from miroms.logs_maintenance import LogMaintenance
from miroms.logs_store import LogStore
from miroms.logs_text import LogText

ZH_BIT = 1 << LogStore.LANG_INDEX[LogStore.ZH_COLUMN]
# 「完整行」判定：带英文且有足够语言覆盖；否则视为附加语言簇的窄行
FULL_ROW_LANGS = 8
# 只有语言数很少、且没有英文的窄行才允许 clear（避免误清合法语言簇的中文）
NARROW_ROW_LANGS = 6


class LogProofreader:
	"""日志多语言校对（类方法，无需实例化）"""

	# 语言列 -> 中文名（用于让模型判断「该列文本是否真是这门语言」）
	LANG_NAMES: Dict[str, str] = {item['column']: item['zh'] for item in CHANGELOG_LOCALES}
	# 低于该置信度的语言不符标注不写库
	LANG_ISSUE_MIN_CONFIDENCE = 0.6
	LANG_RULES = (
		'\n另外，对每个非空语言列判断文本是否真的属于该语言。列对照：'
		+ json.dumps(LANG_NAMES, ensure_ascii=False)
		+ '。明显不是该语言时，在结果的 lang_issues 中标注：'
		'{"logs_de":{"detected":"英文","confidence":0.98,"correct":"Sonstiges",'
		'"reason":"实际是英文 Other；德语应为 Sonstiges"}}。'
		'`correct` 是该语言下的正确译文：只有 confidence ≥ 0.8 且你能确定时才给，'
		'给不出就省略，不要编造；品牌名 / 产品名 / 型号 / URL / 纯数字或符号不算语言不符。'
		'lang_issues 只写确实有问题的列，没有就返回空对象 {}。'
		'每条结果都必须带 lang_issues 字段，不能省略。'
		'例如 logs_de 的值是英文 Other，应标注 '
		'{"logs_de":{"detected":"英文","confidence":0.95,"correct":"Sonstiges",'
		'"reason":"Other 是英文，不是德文"}}。'
	)

	# ==================== 规则扫描 ====================

	@staticmethod
	def authoritative_texts(row: Dict[str, Any]) -> Dict[str, str]:
		"""真实译文：排除 logs_zh 与「等于本行 logs_en」的英文回落"""
		texts = row['texts']
		en = LogStore.normalize(texts.get(LogStore.EN_COLUMN))
		result: Dict[str, str] = {}
		for column, value in texts.items():
			if column == LogStore.ZH_COLUMN:
				continue
			if en and column != LogStore.EN_COLUMN and LogStore.normalize(value) == en:
				continue
			result[column] = value
		return result

	@classmethod
	def _signature(cls, row: Dict[str, Any]) -> Tuple[Tuple[str, str], ...]:
		return tuple(sorted(cls.authoritative_texts(row).items()))

	@classmethod
	def scan(cls, rows: Optional[Dict[int, Dict[str, Any]]] = None,
			 owners: Optional[Dict[Tuple[str, int], List[Any]]] = None,
			 include_logs: bool = False, min_support: int = 3,
			 mismatch_limit: int = 200) -> Dict[str, Any]:
		"""规则扫描，返回 {families, mismatches, stats}

		families 里的每个元素可以原样写进报告、交给 ``review``；
		mismatches 只是「疑似译文错列」的清单，供人工 / 后续版本处理。
		"""
		rows = rows if rows is not None else LogMaintenance.load_rows()
		owners = owners if owners is not None else LogMaintenance.load_owners()
		families: Dict[str, Dict[str, Any]] = {}

		for (table, owner_id), refs in owners.items():
			positions: List[Tuple[int, str, Dict[str, Any]]] = []
			for module_id, _entries, _mask in LogMaintenance.iter_refs(refs):
				row = rows.get(module_id)
				if not row or row.get('proofed'):
					continue
				if row['type'] != 'module' and not include_logs:
					continue
				zh = LogStore.normalize(row['texts'].get(LogStore.ZH_COLUMN) or row['content'])
				if zh and LogText.is_chinese(zh):
					positions.append((module_id, zh, row))
			if len(positions) < 2:
				continue
			known_zh = sorted({zh for _, zh, _ in positions})
			groups: Dict[Tuple[str, str], set] = defaultdict(set)
			for module_id, zh, row in positions:
				groups[(row['type'], zh)].add(module_id)
			for (log_type, zh), ids in groups.items():
				if len(ids) < 2:
					continue
				if len({cls._signature(rows[i]) for i in ids}) < 2:
					continue  # 外文完全一致 → 只是重复位置，不是填错
				key = f'{log_type}|{zh}|' + ','.join(str(i) for i in sorted(ids))
				family = families.get(key)
				if family is None:
					family = {
						'key': key,
						'type': log_type,
						'zh': zh,
						'row_ids': sorted(ids),
						'known_zh': set(),
						'owners_count': 0,
						'owners_sample': [],
						'priority': False,
						'rows': [],
					}
					for row_id in sorted(ids):
						row = rows[row_id]
						texts = {column: str(value)[:160] for column, value in row['texts'].items()
								 if column != LogStore.ZH_COLUMN}
						has_en = LogStore.EN_COLUMN in row['texts']
						family['rows'].append({
							'row_id': row_id,
							'current_zh': LogStore.normalize(
								row['texts'].get(LogStore.ZH_COLUMN) or row['content']),
							'langs': len(row['texts']),
							'has_en': has_en,
							'texts': texts,
						})
						if not has_en or len(row['texts']) < FULL_ROW_LANGS:
							family['priority'] = True
					families[key] = family
				family['known_zh'].update(known_zh)
				family['owners_count'] += 1
				if len(family['owners_sample']) < 5:
					family['owners_sample'].append([table, owner_id])

		for family in families.values():
			family['known_zh'] = sorted(family['known_zh'])
		ordered = sorted(families.values(),
						 key=lambda item: (not item['priority'], -item['owners_count']))

		mismatches = cls.scan_translation_mismatches(
			rows, min_support=min_support, limit=mismatch_limit, include_logs=include_logs)
		return {
			'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
			'families': ordered,
			'mismatches': mismatches,
			'stats': {
				'rows': len(rows),
				'owners': len(owners),
				'families': len(ordered),
				'priority_families': sum(1 for item in ordered if item['priority']),
				'families_rows': sum(len(item['row_ids']) for item in ordered),
				'mismatches': len(mismatches),
			},
		}

	@classmethod
	def scan_translation_mismatches(cls, rows: Dict[int, Dict[str, Any]],
									min_support: int = 3, limit: int = 200,
									include_logs: bool = False) -> List[Dict[str, Any]]:
		"""用「译文 → 中文」的共现统计找疑似错列的译文

		同一门外语文本在库里几乎只和某个中文一起出现，若某行把它挂在另一个中文下，
		说明这一列很可能错位 / 与其他行互换（如 4576 的 ja 属于 4577 的「安全隐私」）。
		比较前会把中文转成简体，避免「系統 vs 系统」这类繁简差异被误报。
		"""
		types = {'module', 'log'} if include_logs else {'module'}
		cooccurrence: Dict[Tuple[str, str], Dict[str, Counter]] = defaultdict(
			lambda: defaultdict(Counter))
		for row in rows.values():
			if row['type'] not in types or row.get('proofed'):
				continue
			zh = LogStore.normalize(row['texts'].get(LogStore.ZH_COLUMN) or row['content'])
			if not zh or not LogText.is_chinese(zh):
				continue
			for column, value in row['texts'].items():
				if column in (LogStore.ZH_COLUMN, LogStore.EN_COLUMN) or not value:
					continue
				cooccurrence[(row['type'], column)][LogStore.normalize(value)][zh] += 1

		def simplified(text: str) -> str:
			return LogText.to_simplified(text) or text

		mismatches: List[Dict[str, Any]] = []
		for row_id, row in rows.items():
			if row['type'] not in types or row.get('proofed'):
				continue
			zh = LogStore.normalize(row['texts'].get(LogStore.ZH_COLUMN) or row['content'])
			if not zh or not LogText.is_chinese(zh):
				continue
			en = LogStore.normalize(row['texts'].get(LogStore.EN_COLUMN))
			for column, value in row['texts'].items():
				if column in (LogStore.ZH_COLUMN, LogStore.EN_COLUMN) or not value:
					continue
				text = LogStore.normalize(value)
				if en and text == en:
					continue  # 英文回落，不是真实译文
				counter = cooccurrence[(row['type'], column)].get(text)
				if not counter:
					continue
				best_zh, support = counter.most_common(1)[0]
				if support < min_support or simplified(best_zh) == simplified(zh):
					continue
				mismatches.append({
					'row_id': row_id,
					'type': row['type'],
					'column': column,
					'current_zh': zh[:80],
					'text': text[:120],
					'likely_zh': best_zh[:80],
					'support': support,
				})
		mismatches.sort(key=lambda item: -item['support'])
		return mismatches[:limit]

	# ==================== AI 复核 ====================

	SYSTEM_PROMPT = (
		'你是小米 MIUI / HyperOS 更新日志的多语言校对员。只输出 JSON，不要输出 JSON 之外的文字。\n'
		'任务：对每个模块行先判定 verdict，再给出中文模块名：\n'
		'- "ok"：当前中文名与译文语义一致（措辞差异不算错）；\n'
		'- "wrong_zh"：当前中文名明显错误，且全部真实译文一致指向另一个中文模块名；\n'
		'- "mixed_translations"：同一行内不同语言的译文指向不同模块（部分支持当前中文、部分属于另一个模块），'
		'这是译文错列 / 互换，不要改中文；\n'
		'- "extra_module"：该行是中文结构里没有的额外模块（没有合适的中文名）。\n'
		'规则：\n'
		'1. wrong_zh 时 zh 只能从 known_zh 列表里选；extra_module 时 zh 为 null；'
		'ok / mixed_translations 时 zh 返回当前中文名。\n'
		'2. 以 en / de / ja / ko / ru 等真实译文含义为依据；等于该行 logs_en 的外语只是英文回落，不能作为依据。\n'
		'3. 如果 logs_en 与当前中文名一致，通常说明中文是对的，应优先判为 mixed_translations（问题在译文），'
		'而不是改中文。\n'
		'4. 同一个 ROM 的中文模块名不会重复指代不同模块；当前中文名已被另一个含义不同的行占用时，'
		'结合规则 2-3 判断。\n'
		'5. 当前中文名与候选名可能只是措辞差异（例如「系统动画」与「系统动画设计」），语义一致时返回 ok。\n'
		'6. confidence 取 0~1；证据不足就给低分，不要猜。\n'
		'输出格式：{"results":[{"row_id":11036,"verdict":"wrong_zh","zh":"设备互联",'
		'"confidence":0.95,"reason":"德文 Interkonnektivität = 设备互联","lang_issues":{}}]}'
	)

	LOG_SYSTEM_PROMPT = (
		'你是小米 MIUI / HyperOS 更新日志的校对员。只输出 JSON，不要输出 JSON 之外的文字。\n'
		'任务：判断这条日志条目的简体中文（current_zh）是否与各语言真实译文语义一致，并给出 verdict：\n'
		'- "ok"：中文与译文语义一致（措辞差异不算错）；\n'
		'- "mixed_translations"：同一行不同语言的译文指向不同含义 / 模块，属于译文错列；\n'
		'- "wrong_zh"：中文明显是错误翻译，且你能给出正确的简体中文；\n'
		'- "extra_module"：没有可用的中文（极少用）。\n'
		'规则：wrong_zh 时给出 zh（简体中文译法）；ok / mixed_translations 时 zh 返回当前中文；'
		'confidence 取 0~1，证据不足给低分。\n'
		'输出格式：{"results":[{"row_id":123,"verdict":"ok","zh":"...","confidence":0.9,"reason":"...","lang_issues":{}}]}'
	)

	@classmethod
	def _row_payload(cls, row: Dict[str, Any]) -> Dict[str, Any]:
		return {
			'row_id': row['id'],
			'current_zh': LogStore.normalize(
				row['texts'].get(LogStore.ZH_COLUMN) or row['content']),
			'langs': len(row['texts']),
			'has_en': LogStore.EN_COLUMN in row['texts'],
			'has_zh': bool(row['texts'].get(LogStore.ZH_COLUMN)),
			'texts': {column: str(value)[:160] for column, value in row['texts'].items()
					  if column != LogStore.ZH_COLUMN},
		}

	@classmethod
	def build_log_prompt(cls, row: Dict[str, Any]) -> List[Dict[str, str]]:
		payload = {'type': 'log', 'rows': [cls._row_payload(row)]}
		return [
			{'role': 'system', 'content': cls.LOG_SYSTEM_PROMPT + cls.LANG_RULES},
			{'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
		]

	@classmethod
	def build_prompt(cls, family: Dict[str, Any]) -> List[Dict[str, str]]:
		"""把一个 family 转成 DeepSeek 的 messages"""
		payload = {
			'type': family['type'],
			'shared_zh': family['zh'],
			'known_zh': family['known_zh'],
			'rows': family['rows'],
		}
		return [
			{'role': 'system', 'content': cls.SYSTEM_PROMPT + cls.LANG_RULES},
			{'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
		]

	VERDICTS = ('ok', 'wrong_zh', 'mixed_translations', 'extra_module')

	@classmethod
	def _merge_lang_issues(cls, ai_issues: Dict[str, Dict[str, Any]],
						   texts: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
		"""合并 AI 标注与「值等于 logs_en」的确定性回落标注

		某个非英文列与 logs_en 完全相同，通常说明它是英文副本而不是该语言译文；
		置信度取 0.75，低于 AI 的明确判定（AI 的条目优先）。
		"""
		issues = dict(ai_issues)
		en = LogStore.normalize((texts or {}).get(LogStore.EN_COLUMN))
		if not en:
			return issues
		for column, value in (texts or {}).items():
			if column in (LogStore.EN_COLUMN, LogStore.ZH_COLUMN) or column in issues:
				continue
			if LogStore.normalize(value) == en:
				issues[column] = {
					'detected': '与 logs_en 相同（英文回落）',
					'confidence': 0.75,
					'reason': '该列文本与 logs_en 完全相同',
				}
		return issues

	@classmethod
	def _parse_issue_map(cls, item: Dict[str, Any], available: set) -> Dict[str, Dict[str, Any]]:
		"""解析模型的 lang_issues：只保留存在的语言列、置信度足够、且检测语言不是本列语言"""
		raw = item.get('lang_issues')
		if not isinstance(raw, dict):
			return {}
		issues: Dict[str, Dict[str, Any]] = {}
		for column, detail in raw.items():
			if column not in LogStore.LANG_COLUMNS or column not in available:
				continue
			if not isinstance(detail, dict):
				detail = {'detected': str(detail)}
			detected = str(detail.get('detected') or '').strip()[:40]
			if not detected or detected == cls.LANG_NAMES.get(column):
				continue
			try:
				confidence = float(detail.get('confidence') or 0)
			except (TypeError, ValueError):
				confidence = 0.0
			if confidence < cls.LANG_ISSUE_MIN_CONFIDENCE:
				continue
			issue = {
				'detected': detected,
				'confidence': round(min(1.0, max(0.0, confidence)), 3),
				'reason': str(detail.get('reason') or '')[:160],
			}
			correct = detail.get('correct')
			if correct is not None:
				correct = str(correct).strip()
				if correct:
					issue['correct'] = correct[:4000]
			issues[column] = issue
		return issues

	@classmethod
	def parse_decisions(cls, payload: Dict[str, Any], family: Dict[str, Any]) -> List[Dict[str, Any]]:
		"""校验模型返回：row_id 必须在 family 内；wrong_zh 的 zh 必须在 known_zh 内

		兼容没有 verdict 的旧格式：zh 等于当前中文名 → ok；zh 为 null → extra_module；
		其余 → wrong_zh。
		"""
		results = payload.get('results')
		if not isinstance(results, list):
			raise ValueError('模型返回缺少 results 数组')
		current = {item['row_id']: item['current_zh'] for item in family['rows']}
		payloads = {item['row_id']: item for item in family['rows']}
		known = set(family['known_zh'])
		decisions: List[Dict[str, Any]] = []
		for item in results:
			if not isinstance(item, dict):
				continue
			try:
				row_id = int(item.get('row_id'))
			except (TypeError, ValueError):
				continue
			if row_id not in current:
				continue
			raw_zh = item.get('zh')
			zh = str(raw_zh).strip() if raw_zh is not None else None
			if not zh:
				zh = None
			verdict = str(item.get('verdict') or '').strip()
			if verdict not in cls.VERDICTS:
				if zh is None:
					verdict = 'extra_module'
				elif zh == current[row_id]:
					verdict = 'ok'
				else:
					verdict = 'wrong_zh'
			if verdict == 'wrong_zh' and (zh is None or zh not in known):
				continue  # 只能从该 ROM 已有的中文模块名里选
			if verdict in ('ok', 'mixed_translations'):
				zh = current[row_id]
			if verdict == 'extra_module':
				zh = None
			try:
				confidence = float(item.get('confidence') or 0)
			except (TypeError, ValueError):
				confidence = 0.0
			confidence = max(0.0, min(1.0, confidence))
			payload_row = payloads.get(row_id) or {}
			available = set(payload_row.get('texts') or {})
			if current[row_id]:
				available.add(LogStore.ZH_COLUMN)
			issues = cls._merge_lang_issues(
				cls._parse_issue_map(item, available), payload_row.get('texts') or {})
			decisions.append({
				'row_id': row_id,
				'verdict': verdict,
				'family': family['key'],
				'family_type': family['type'],
				'family_zh': family['zh'],
				'current_zh': current[row_id],
				'suggested_zh': zh,
				'confidence': confidence,
				'reason': str(item.get('reason') or '')[:200],
				'known_zh': family['known_zh'],
				'lang_issues': issues,
			})
		return decisions

	@classmethod
	def parse_log_decisions(cls, payload: Dict[str, Any], row: Dict[str, Any]) -> List[Dict[str, Any]]:
		"""校验「单条日志」的 AI 返回（wrong_zh 允许自由中文，不限制候选列表）"""
		results = payload.get('results')
		if not isinstance(results, list):
			raise ValueError('模型返回缺少 results 数组')
		current = LogStore.normalize(
			row['texts'].get(LogStore.ZH_COLUMN) or row['content'])
		decisions: List[Dict[str, Any]] = []
		for item in results:
			if not isinstance(item, dict):
				continue
			try:
				row_id = int(item.get('row_id'))
			except (TypeError, ValueError):
				continue
			if row_id != int(row['id']):
				continue
			raw_zh = item.get('zh')
			zh = str(raw_zh).strip() if raw_zh is not None else None
			verdict = str(item.get('verdict') or '').strip()
			if verdict not in cls.VERDICTS:
				verdict = 'wrong_zh' if zh and zh != current else 'ok'
			if verdict == 'wrong_zh':
				if not zh or not LogText.is_chinese(zh):
					continue
			elif verdict in ('ok', 'mixed_translations'):
				zh = current
			else:
				zh = None
			try:
				confidence = float(item.get('confidence') or 0)
			except (TypeError, ValueError):
				confidence = 0.0
			decisions.append({
				'row_id': row_id,
				'verdict': verdict,
				'current_zh': current,
				'suggested_zh': zh,
				'confidence': max(0.0, min(1.0, confidence)),
				'reason': str(item.get('reason') or '')[:200],
				'free_zh': True,
				'type': row['type'],
				'lang_issues': cls._merge_lang_issues(
					cls._parse_issue_map(item, set(row['texts'])), row['texts']),
			})
		return decisions

	@classmethod
	def inspect(cls, ids: Sequence[int],
				rows: Optional[Dict[int, Dict[str, Any]]] = None,
				owners: Optional[Dict[Tuple[str, int], List[Any]]] = None,
				client=None, min_support: int = 3, force: bool = False) -> Dict[str, Any]:
		"""校对指定的若干 logs.id（单条检查，不写库）

		返回每条的目的前状态、英文回落列、疑似译文错列、同 ROM 中文模块名，
		以及（传了 client 时的）AI verdict / 建议。
		"""
		rows = rows if rows is not None else LogMaintenance.load_rows()
		owners = owners if owners is not None else LogMaintenance.load_owners()
		targets = {int(item) for item in ids}
		mismatches = cls.scan_translation_mismatches(
			rows, min_support=min_support, limit=1_000_000)

		common_names: Dict[int, set] = {}
		all_names: Dict[int, set] = defaultdict(set)
		owners_count: Dict[int, int] = defaultdict(int)
		for (table, owner_id), refs in owners.items():
			hit = set()
			names = set()
			for module_id, _entries, _mask in LogMaintenance.iter_refs(refs):
				row = rows.get(module_id)
				if not row:
					continue
				name = LogStore.normalize(
					row['texts'].get(LogStore.ZH_COLUMN) or row['content'])
				if name and LogText.is_chinese(name):
					names.add(name)
				if module_id in targets:
					hit.add(module_id)
			if hit:
				for row_id in hit:
					owners_count[row_id] += 1
					all_names[row_id].update(names)
					if row_id not in common_names:
						common_names[row_id] = set(names)
					else:
						common_names[row_id] &= names
		known_by_row: Dict[int, List[str]] = {}
		for row_id in targets:
			common = common_names.get(row_id) or set()
			known = common if common else all_names.get(row_id, set())
			known_by_row[row_id] = sorted(known)[:120]

		results = []
		for row_id in sorted(targets):
			row = rows.get(row_id)
			if not row:
				results.append({'row_id': row_id, 'error': 'not_found'})
				continue
			current = LogStore.normalize(
				row['texts'].get(LogStore.ZH_COLUMN) or row['content'])
			payload = cls._row_payload(row)
			item: Dict[str, Any] = {
				'row_id': row_id,
				'type': row['type'],
				'content': row['content'],
				'current_zh': current,
				'langs': len(row['texts']),
				'has_en': LogStore.EN_COLUMN in row['texts'],
				'has_zh': bool(row['texts'].get(LogStore.ZH_COLUMN)),
				'proofed': bool(row.get('proofed')),
				'texts': dict(row['texts']),
				'fallbacks': sorted(cls._fallback_columns(row)),
				'mismatches': [m for m in mismatches if m['row_id'] == row_id],
				'known_zh': known_by_row.get(row_id, []),
				'owners': owners_count.get(row_id, 0),
				'decision': None,
				'error': None,
				'skipped': None,
			}
			if item['proofed'] and not force:
				item['skipped'] = 'proofed'
				results.append(item)
				continue
			if client:
				try:
					if row['type'] == 'log':
						response = client.json_chat(cls.build_log_prompt(row))
						decisions = cls.parse_log_decisions(response, row)
					else:
						family = {
							'key': f'row|{row_id}',
							'type': row['type'],
							'zh': current,
							'row_ids': [row_id],
							'known_zh': item['known_zh'],
							'rows': [payload],
						}
						response = client.json_chat(cls.build_prompt(family))
						decisions = cls.parse_decisions(response, family)
					item['decision'] = decisions[0] if decisions else None
				except Exception as exc:
					item['error'] = f'{type(exc).__name__}: {exc}'
			results.append(item)
		return {
			'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
			'rows': results,
		}

	@classmethod
	def _fallback_columns(cls, row: Dict[str, Any]) -> set:
		en = LogStore.normalize(row['texts'].get(LogStore.EN_COLUMN))
		if not en:
			return set()
		return {column for column, value in row['texts'].items()
				if column != LogStore.EN_COLUMN and LogStore.normalize(value) == en}

	BATCH_MODULE_PROMPT = (
		'你是小米 MIUI / HyperOS 更新日志的多语言校对员。只输出 JSON，不要输出 JSON 之外的文字。\n'
		'逐条判断 module 行的中文名是否正确：\n'
		'- "ok"：当前中文与译文语义一致（措辞差异不算错）；\n'
		'- "wrong_zh"：中文明显错误，且全部真实译文一致指向该行 known_zh 里的另一个名字；\n'
		'- "mixed_translations"：同一行不同语言译文指向不同模块（译文错列 / 互换），不要改中文；\n'
		'- "extra_module"：该行是中文结构里没有的额外模块。\n'
		'规则：wrong_zh 时 zh 只能从该行 known_zh 里选；extra_module 时 zh 为 null；'
		'ok / mixed_translations 时 zh 返回当前中文。等于 logs_en 的外语只是英文回落，不能作为依据。'
		'若 logs_en 与当前中文一致，优先判 mixed_translations。confidence 0~1，证据不足给低分。\n'
		'输出格式：{"results":[{"row_id":11036,"verdict":"wrong_zh","zh":"设备互联",'
		'"confidence":0.95,"reason":"...","lang_issues":{}}]}'
	)

	BATCH_LOG_PROMPT = (
		'你是小米 MIUI / HyperOS 更新日志的校对员。只输出 JSON，不要输出 JSON 之外的文字。\n'
		'逐条判断日志条目的简体中文（current_zh）与各语言真实译文是否语义一致：\n'
		'- "ok"：一致（措辞差异不算错）；\n'
		'- "mixed_translations"：同一行不同语言译文指向不同含义 / 模块（译文错列）；\n'
		'- "wrong_zh"：中文明显是错误翻译，且能给出正确的简体中文；\n'
		'- "extra_module"：没有可用中文。\n'
		'规则：wrong_zh 时给出 zh（简体中文译法）；ok / mixed_translations 时 zh 返回当前中文。'
		'confidence 0~1，证据不足给低分。\n'
		'输出格式：{"results":[{"row_id":123,"verdict":"ok","zh":"...","confidence":0.9,"reason":"...","lang_issues":{}}]}'
	)

	@classmethod
	def select_batch_rows(cls, rows: Dict[int, Dict[str, Any]], include_single: bool = False,
						  min_langs: int = 2, types: Sequence[str] = ('module', 'log'),
						  limit: int = 0, include_proofed: bool = False) -> List[Dict[str, Any]]:
		"""挑选要批量校对的行（默认只挑 ≥min_langs 种语言的行）"""
		allowed = set(types)
		selected = [row for row in rows.values()
					if row['type'] in allowed
					and (include_proofed or not row.get('proofed'))
					and (include_single or len(row['texts']) >= min_langs)]
		selected.sort(key=lambda row: (row['type'], row['id']))
		if limit:
			selected = selected[:limit]
		return selected

	@classmethod
	def _module_known_context(cls, rows: Dict[int, Dict[str, Any]],
							  owners: Dict[Tuple[str, int], List[Any]],
							  ids: Sequence[int]) -> Dict[int, List[str]]:
		"""module id -> 同一 ROM 的中文模块名（跨 owner 取交集，避免列表过长）"""
		targets = {int(item) for item in ids}
		if not targets:
			return {}
		common: Dict[int, set] = {}
		all_names: Dict[int, set] = defaultdict(set)
		for (_table, _owner_id), refs in owners.items():
			hit = set()
			names = set()
			for module_id, _entries, _mask in LogMaintenance.iter_refs(refs):
				row = rows.get(module_id)
				if not row:
					continue
				name = LogStore.normalize(
					row['texts'].get(LogStore.ZH_COLUMN) or row['content'])
				if name and LogText.is_chinese(name):
					names.add(name)
				if module_id in targets:
					hit.add(module_id)
			if not hit:
				continue
			for row_id in hit:
				all_names[row_id].update(names)
				if row_id not in common:
					common[row_id] = set(names)
				else:
					common[row_id] &= names
		return {row_id: sorted(common.get(row_id) or all_names.get(row_id, set()))[:120]
				for row_id in targets}

	@classmethod
	def build_batch_prompt(cls, rows_subset: Sequence[Dict[str, Any]],
						   known: Dict[int, List[str]], log_type: str) -> List[Dict[str, str]]:
		"""构造一批（默认 10 条）的 prompt：module / log 分开，避免混淆判定规则"""
		if log_type == 'module':
			payload = {'rows': [dict(cls._row_payload(row),
									 known_zh=known.get(row['id'], []))
								for row in rows_subset]}
			system = cls.BATCH_MODULE_PROMPT
		else:
			payload = {'rows': [cls._row_payload(row) for row in rows_subset]}
			system = cls.BATCH_LOG_PROMPT
		return [
			{'role': 'system', 'content': system + cls.LANG_RULES},
			{'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
		]

	@classmethod
	def prepare_batches(cls, rows: Dict[int, Dict[str, Any]],
						owners: Dict[Tuple[str, int], List[Any]],
						batch_size: int = 10, include_single: bool = False,
						min_langs: int = 2, types: Sequence[str] = ('module', 'log'),
						limit: int = 0, include_proofed: bool = False
						) -> Tuple[List[Dict[str, Any]], Dict[int, List[str]], List[Dict[str, Any]]]:
		"""返回 (选中的行, module 的 known_zh, batches)

		batches 里每条含 type / rows / messages，供估算或实际调用复用。
		"""
		selected = cls.select_batch_rows(rows, include_single=include_single,
										 min_langs=min_langs, types=types, limit=limit,
										 include_proofed=include_proofed)
		module_ids = [row['id'] for row in selected if row['type'] == 'module']
		known = cls._module_known_context(rows, owners, module_ids)
		batches: List[Dict[str, Any]] = []
		for log_type in ('module', 'log'):
			subset = [row for row in selected if row['type'] == log_type]
			for index in range(0, len(subset), batch_size):
				chunk = subset[index:index + batch_size]
				batches.append({
					'type': log_type,
					'rows': chunk,
					'messages': cls.build_batch_prompt(chunk, known, log_type),
				})
		return selected, known, batches

	@classmethod
	def estimate_batches(cls, batches: Sequence[Dict[str, Any]], batch_size: int,
						 selected: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
		"""离线估算 tokens（不调用 API）

		prompt 按 0.35~0.42 token/字符；completion 按「每批约 1000 + 150×批大小」，
		系数来自 deepseek-flash + reasoning_effort=low 的实测样本。
		"""
		prompt_chars = sum(len(message['content'])
						   for batch in batches for message in batch['messages'])
		calls = len(batches)
		per_batch = 1000 + 150 * batch_size
		return {
			'rows': len(selected),
			'rows_by_type': {t: sum(1 for row in selected if row['type'] == t)
							 for t in ('module', 'log')},
			'batches': calls,
			'batch_size': batch_size,
			'prompt_chars': prompt_chars,
			'prompt_tokens': [int(prompt_chars * 0.35), int(prompt_chars * 0.42)],
			'completion_tokens': [int(calls * per_batch * 0.7), int(calls * per_batch * 1.3)],
			'total_tokens': [int(prompt_chars * 0.35 + calls * per_batch * 0.7),
							 int(prompt_chars * 0.42 + calls * per_batch * 1.3)],
			'estimated_hours': [round(calls * 4 / 3600, 2), round(calls * 10 / 3600, 2)],
		}

	@classmethod
	def parse_batch_decisions(cls, payload: Dict[str, Any],
							  rows_subset: Sequence[Dict[str, Any]],
							  known: Dict[int, List[str]], log_type: str) -> List[Dict[str, Any]]:
		"""校验一批 AI 返回；module 的 wrong_zh 只能选该行的 known_zh"""
		results = payload.get('results')
		if not isinstance(results, list):
			raise ValueError('模型返回缺少 results 数组')
		items = {}
		for item in results:
			if not isinstance(item, dict):
				continue
			try:
				items[int(item.get('row_id'))] = item
			except (TypeError, ValueError):
				continue
		decisions: List[Dict[str, Any]] = []
		for row in rows_subset:
			item = items.get(int(row['id']))
			if not item:
				continue
			current = LogStore.normalize(
				row['texts'].get(LogStore.ZH_COLUMN) or row['content'])
			raw_zh = item.get('zh')
			zh = str(raw_zh).strip() if raw_zh is not None else None
			zh = zh or None
			verdict = str(item.get('verdict') or '').strip()
			if verdict not in cls.VERDICTS:
				verdict = 'wrong_zh' if zh and zh != current else 'ok'
			if log_type == 'module':
				candidates = set(known.get(row['id'], []))
				if verdict == 'wrong_zh' and (zh is None or zh not in candidates):
					continue
				if verdict in ('ok', 'mixed_translations'):
					zh = current
				if verdict == 'extra_module':
					zh = None
			else:
				if verdict == 'wrong_zh':
					if not zh or not LogText.is_chinese(zh):
						continue
				elif verdict in ('ok', 'mixed_translations'):
					zh = current
				else:
					zh = None
			try:
				confidence = float(item.get('confidence') or 0)
			except (TypeError, ValueError):
				confidence = 0.0
			decisions.append({
				'row_id': int(row['id']),
				'type': log_type,
				'verdict': verdict,
				'current_zh': current,
				'suggested_zh': zh,
				'confidence': max(0.0, min(1.0, confidence)),
				'reason': str(item.get('reason') or '')[:200],
				'known_zh': known.get(row['id'], []) if log_type == 'module' else [],
				'free_zh': log_type == 'log',
				'lang_issues': cls._merge_lang_issues(
					cls._parse_issue_map(item, set(row['texts'])), row['texts']),
			})
		return decisions

	@classmethod
	def batch_review(cls, rows: Dict[int, Dict[str, Any]],
					 owners: Dict[Tuple[str, int], List[Any]], client,
					 batch_size: int = 10, include_single: bool = False,
					 min_langs: int = 2, types: Sequence[str] = ('module', 'log'),
					 limit: int = 0, cache_path: Optional[str] = None,
					 on_progress=None, on_decisions=None,
					 include_proofed: bool = False) -> Dict[str, Any]:
		"""批量校对：每批（默认 10 条）一次调用，返回 decisions / errors"""
		selected, known, batches = cls.prepare_batches(
			rows, owners, batch_size=batch_size, include_single=include_single,
			min_langs=min_langs, types=types, limit=limit,
			include_proofed=include_proofed)
		cache: Dict[str, Any] = {}
		cache_file = Path(cache_path) if cache_path else None
		if cache_file and cache_file.exists():
			try:
				cache = json.loads(cache_file.read_text(encoding='utf-8'))
			except json.JSONDecodeError:
				cache = {}
		decisions: Dict[int, Dict[str, Any]] = {}
		errors: List[Dict[str, Any]] = []
		calls = 0
		aborted = None
		max_calls = getattr(client, 'max_calls', None)
		for index, batch in enumerate(batches, 1):
			messages = batch['messages']
			cache_key = hashlib.sha256(
				json.dumps(messages, ensure_ascii=False, sort_keys=True).encode('utf-8')
			).hexdigest()
			payload = cache.get(cache_key)
			cached = payload is not None
			if payload is None:
				if max_calls is not None and getattr(client, 'calls', 0) >= max_calls:
					aborted = 'max_calls'
					errors.append({'batch': index, 'type': batch['type'],
								   'row_ids': [row['id'] for row in batch['rows']],
								   'error': f'max_calls_reached: {max_calls}'})
					break
				try:
					payload = client.json_chat(messages)
				except Exception as exc:
					errors.append({'batch': index, 'type': batch['type'],
								   'row_ids': [row['id'] for row in batch['rows']],
								   'error': f'{type(exc).__name__}: {exc}'})
					if on_progress:
						on_progress(index, len(batches), batch, False)
					continue
				cache[cache_key] = payload
				calls += 1
				if cache_file:
					cache_file.parent.mkdir(parents=True, exist_ok=True)
					cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
										  encoding='utf-8')
			try:
				parsed = cls.parse_batch_decisions(payload, batch['rows'], known, batch['type'])
			except Exception as exc:
				errors.append({'batch': index, 'type': batch['type'],
							   'row_ids': [row['id'] for row in batch['rows']],
							   'error': f'{type(exc).__name__}: {exc}'})
				parsed = []
			for decision in parsed:
				decisions[decision['row_id']] = decision
			if on_decisions and parsed:
				on_decisions(parsed)
			if on_progress:
				on_progress(index, len(batches), batch, cached)
		by_verdict: Dict[str, int] = defaultdict(int)
		by_type_verdict: Dict[str, int] = defaultdict(int)
		for decision in decisions.values():
			by_verdict[decision['verdict']] += 1
			by_type_verdict[f"{decision['type']}:{decision['verdict']}"] += 1
		return {
			'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
			'rows': len(selected),
			'batches': len(batches),
			'calls': calls,
			'aborted': aborted,
			'cache': str(cache_file) if cache_file else None,
			'errors': errors,
			'by_verdict': dict(by_verdict),
			'by_type_verdict': dict(by_type_verdict),
			'lang_issues': sum(1 for item in decisions.values() if item.get('lang_issues')),
			'decisions': sorted(decisions.values(), key=lambda item: -item['confidence']),
		}

	@classmethod
	def review(cls, families: Sequence[Dict[str, Any]], client,
			   only_priority: bool = True, limit: int = 0,
			   cache_path: Optional[str] = None,
			   min_confidence: float = 0.0,
			   on_progress=None, on_decisions=None) -> Dict[str, Any]:
		"""逐 family 调 DeepSeek，返回去重后的 decisions

		cache_path 为 JSON 缓存：同一 prompt 不重复计费，可中断后续跑。
		on_decisions 在每个 family 解析完成后收到本批被采纳的 decisions，
		供调用方立即落库（proofed / lang_issues），避免长跑中断丢标注。
		"""
		cache: Dict[str, Any] = {}
		cache_file = Path(cache_path) if cache_path else None
		if cache_file and cache_file.exists():
			try:
				cache = json.loads(cache_file.read_text(encoding='utf-8'))
			except json.JSONDecodeError:
				cache = {}
		selected = [family for family in families if family['priority'] or not only_priority]
		if limit:
			selected = selected[:limit]

		decisions: Dict[int, Dict[str, Any]] = {}
		errors: List[Dict[str, Any]] = []
		calls = 0
		aborted = None
		for index, family in enumerate(selected, 1):
			messages = cls.build_prompt(family)
			cache_key = hashlib.sha256(
				json.dumps(messages, ensure_ascii=False, sort_keys=True).encode('utf-8')
			).hexdigest()
			payload = cache.get(cache_key)
			cached = payload is not None
			if payload is None:
				try:
					payload = client.json_chat(messages)
				except Exception as exc:   # 单个 family 失败不影响其余候选
					errors.append({'family': family['key'], 'error': f'{type(exc).__name__}: {exc}'})
					if on_progress:
						on_progress(index, len(selected), family, False)
					continue
				cache[cache_key] = payload
				calls += 1
				if cache_file:
					cache_file.parent.mkdir(parents=True, exist_ok=True)
					cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2),
										  encoding='utf-8')
			if on_progress:
				on_progress(index, len(selected), family, cached)
			accepted: List[Dict[str, Any]] = []
			for decision in cls.parse_decisions(payload, family):
				if decision['confidence'] < min_confidence:
					continue
				previous = decisions.get(decision['row_id'])
				if previous is None or decision['confidence'] > previous['confidence']:
					decisions[decision['row_id']] = decision
					accepted.append(decision)
				elif (decision['confidence'] == previous['confidence']
					  and decision['suggested_zh'] != previous['suggested_zh']):
					previous['conflict'] = True
			if on_decisions and accepted:
				on_decisions(accepted)
		return {
			'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
			'families': len(selected),
			'calls': calls,
			'aborted': aborted,
			'cache': str(cache_file) if cache_file else None,
			'errors': errors,
			'decisions': sorted(decisions.values(), key=lambda item: -item['confidence']),
		}

	# ==================== 计划 / 写回 ====================

	@classmethod
	def _module_ref_index(cls, owners: Dict[Tuple[str, int], List[Any]]
						  ) -> Dict[int, List[Tuple[str, int, int, int]]]:
		"""module id -> [(表, owner, 位置, 掩码), ...]（只收录带中文位的引用）"""
		index: Dict[int, List[Tuple[str, int, int, int]]] = defaultdict(list)
		for (table, owner_id), refs in owners.items():
			for position, item in enumerate(refs):
				if not (isinstance(item, list) and len(item) >= 3):
					continue
				try:
					module_id = int(item[0])
					mask = int(item[2])
				except (TypeError, ValueError):
					continue
				if mask & ZH_BIT:
					index[module_id].append((table, owner_id, position, mask))
		return index

	@classmethod
	def plan(cls, decisions: Sequence[Dict[str, Any]],
			 rows: Optional[Dict[int, Dict[str, Any]]] = None,
			 owners: Optional[Dict[Tuple[str, int], List[Any]]] = None,
			 min_confidence: float = 0.8, allow_clear: bool = False) -> Dict[str, Any]:
		"""把 AI 结论转成可执行动作（不改库）

		rename：完整行改正中文；clear：附加语言簇窄行清空中文并去掉掩码中文位；
		其余（低置信度 / 额外模块但未允许 clear）进入 skipped。
		"""
		rows = rows if rows is not None else LogMaintenance.load_rows()
		owners = owners if owners is not None else LogMaintenance.load_owners()
		ref_index = cls._module_ref_index(owners)
		mask_updates: Dict[Tuple[str, int], List[Any]] = {}
		actions: List[Dict[str, Any]] = []
		skipped: List[Dict[str, Any]] = []
		mixed: List[Dict[str, Any]] = []

		for decision in decisions:
			row_id = int(decision['row_id'])
			row = rows.get(row_id)
			if not row:
				skipped.append({'row_id': row_id, 'reason': 'missing_row'})
				continue
			if row['type'] != 'module':
				# log 条目的中文改法不自动写库（AI 翻译需人工确认）
				skipped.append({'row_id': row_id, 'reason': 'log_entry_needs_manual'})
				continue
			if decision.get('conflict'):
				skipped.append({'row_id': row_id, 'reason': 'ai_conflict'})
				continue
			verdict = decision.get('verdict') or 'unknown'
			if verdict == 'mixed_translations':
				# 中文可能是对的，问题在译文错列 / 互换：只记录，等后续专门的换列修复
				mixed.append({'row_id': row_id, 'current_zh': decision.get('current_zh'),
							  'confidence': decision.get('confidence'),
							  'reason': decision.get('reason')})
				continue
			if verdict == 'ok':
				skipped.append({'row_id': row_id, 'reason': 'no_change'})
				continue
			if decision['confidence'] < min_confidence:
				skipped.append({'row_id': row_id, 'reason': 'low_confidence',
								'confidence': decision['confidence']})
				continue
			current_zh = LogStore.normalize(
				row['texts'].get(LogStore.ZH_COLUMN) or row['content'])
			target_zh = decision.get('suggested_zh')
			has_zh = bool(LogStore.normalize(row['texts'].get(LogStore.ZH_COLUMN)))
			has_en = LogStore.EN_COLUMN in row['texts']
			full_row = has_en and len(row['texts']) >= FULL_ROW_LANGS
			narrow_row = (not has_en) and len(row['texts']) <= NARROW_ROW_LANGS
			if not has_zh and (target_zh is None or not full_row):
				# 已经是「无中文」状态（额外语言簇 / 之前已清空），不需要再写
				skipped.append({'row_id': row_id, 'reason': 'already_cleared'})
				continue
			if target_zh is not None and target_zh == current_zh:
				skipped.append({'row_id': row_id, 'reason': 'no_change'})
				continue
			if target_zh is None:
				# AI 认为它是中文结构里没有的额外模块：只有窄行才敢直接清空中文
				if not narrow_row:
					skipped.append({'row_id': row_id, 'reason': 'ambiguous_row_needs_manual',
									'suggested_zh': None})
					continue
				if not allow_clear:
					skipped.append({'row_id': row_id, 'reason': 'extra_module_needs_clear',
									'suggested_zh': None})
					continue
				action = 'clear'
			elif full_row:
				action = 'rename'
			elif narrow_row and allow_clear:
				action = 'clear'
			elif narrow_row:
				skipped.append({'row_id': row_id, 'reason': 'extra_module_needs_clear',
								'suggested_zh': target_zh})
				continue
			else:
				# 语言数不少但没有英文：改中文 / 清中文都可能误伤独有译文，只报告，交给人工
				skipped.append({'row_id': row_id, 'reason': 'ambiguous_row_needs_manual',
								'suggested_zh': target_zh})
				continue

			if action == 'clear' and not LogStore.normalize(row['texts'].get(LogStore.ZH_COLUMN)):
				skipped.append({'row_id': row_id, 'reason': 'no_change'})
				continue
			action_item: Dict[str, Any] = {
				'row_id': row_id,
				'action': action,
				'current_zh': current_zh,
				'suggested_zh': target_zh,
				'confidence': decision['confidence'],
				'reason': decision.get('reason', ''),
				'mask_updates': 0,
			}
			if action == 'rename':
				action_item['content'] = target_zh
			else:
				foreign = {column: value for column, value in row['texts'].items()
						   if column != LogStore.ZH_COLUMN}
				content = LogStore.primary_text(foreign) or row['content'] or current_zh
				action_item['content'] = content
				for table, owner_id, position, mask in ref_index.get(row_id, []):
					refs = mask_updates.get((table, owner_id))
					if refs is None:
						refs = copy.deepcopy(owners[(table, owner_id)])
						mask_updates[(table, owner_id)] = refs
					refs[position][2] = mask & ~ZH_BIT
					action_item['mask_updates'] += 1
			actions.append(action_item)

		updates: List[Tuple[str, int, str]] = []
		for (table, owner_id), refs in mask_updates.items():
			updates.append((table, owner_id, json.dumps(refs, ensure_ascii=False)))
		return {
			'actions': actions,
			'skipped': skipped,
			'mixed': mixed,
			'mask_updates': updates,
			'stats': {
				'rename': sum(1 for item in actions if item['action'] == 'rename'),
				'clear': sum(1 for item in actions if item['action'] == 'clear'),
				'skipped': len(skipped),
				'mixed_translations': len(mixed),
				'mask_updates': len(updates),
			},
			'applied': False,
		}

	@classmethod
	def apply(cls, plan: Dict[str, Any], apply: bool = False, backup: bool = True,
			  backup_path: Optional[str] = None, batch: int = 500) -> Dict[str, Any]:
		"""执行 plan（默认 dry-run）；写库前可选备份，写后刷新导出缓存"""
		result = dict(plan)
		result['applied'] = False
		result['backup'] = None
		if not plan['actions'] and not plan['mask_updates']:
			return result
		if not apply:
			return result
		if backup:
			result['backup'] = LogMaintenance.backup(backup_path)
		with LogStore.write_lock():
			for action in plan['actions']:
				if action['action'] == 'rename':
					DatabaseManager.execute(
						"UPDATE `logs` SET `logs_zh` = %s, `content` = %s, `content_hash` = %s, "
						"`proofed` = 0, `complete` = 0, `lang_issues` = NULL WHERE `id` = %s",
						params=(action['suggested_zh'], action['content'],
								LogStore.hash_text(action['content']), action['row_id']),
						raise_on_error=True)
				else:
					DatabaseManager.execute(
						"UPDATE `logs` SET `logs_zh` = NULL, `content` = %s, `content_hash` = %s, "
						"`proofed` = 0, `complete` = 0, `lang_issues` = NULL WHERE `id` = %s",
						params=(action['content'], LogStore.hash_text(action['content']),
								action['row_id']),
						raise_on_error=True)
			for table, owner_id, value in plan['mask_updates']:
				DatabaseManager.execute(
					f"UPDATE `{table}` SET `logs` = %s WHERE `id` = %s",
					params=(value, owner_id), raise_on_error=True)
			changed_ids = [action['row_id'] for action in plan['actions']]
			if changed_ids:
				LogMaintenance.mark_proofed(changed_ids, value=False)
		LogStore.refresh_cache()
		result['applied'] = True
		return result
