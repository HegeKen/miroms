"""
miroms.logs_fill - 为 proofed 行排查缺失语言并 AI 翻译回填

只处理 ``logs.proofed = 1`` 的行（可用 --include-unproofed 放开）：

- 期望语言默认是全部语言列（``--expected all``）；也可用 ``--expected owners``
  只补该行在 roms/dev 引用里实际出现过的语言；
- 以 ``logs_zh`` / ``content`` / ``logs_en`` 为源，把缺失语言交给 AI 翻译；
- 翻译结果带 confidence，低于 ``--min-confidence``（默认 0.8）不写；
- 与源语言完全相同的结果视为无效（避免又写回英文回落）；
- 回填后默认把 proofed 重置为 0（新增译文需要重新校对）；``--keep-proofed``
  且没有剩余 lang_issues 时保留 proofed=1；
- 回填列会从 lang_issues 中移除；全部移除后置 NULL；
- 回填后若全部语言齐全且 proofed=1，则 complete=1，否则 complete=0。

默认只列出缺口，不调用 API；``--run`` 调 AI 预览；``--apply`` 调 AI 并写库。
"""
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from miroms.constants import CHANGELOG_LOCALES
from miroms.database import DatabaseManager
from miroms.deepseek import DeepSeekClient, DeepSeekError
from miroms.logs_maintenance import LogMaintenance
from miroms.logs_store import LogStore

LANG_NAMES = {item['column']: item['zh'] for item in CHANGELOG_LOCALES}
ZH_COLUMN = LogStore.ZH_COLUMN
EN_COLUMN = LogStore.EN_COLUMN


class LogFiller:
	"""proofed 行缺失语言翻译回填"""

	SYSTEM_PROMPT = (
		'你是 MIUI / HyperOS 更新日志的本地化译者。把给定文本翻译成目标语言，只输出 JSON，'
		'不要输出 JSON 之外的文字。\n'
		'输出格式：{"translations":{"logs_de":{"text":"...","confidence":0.95},'
		'"logs_fr":{"text":"...","confidence":0.95}}}\n'
		'规则：\n'
		'1. 保留 %s、{0}、%1$s 等占位符，URL、数字、版本号、型号原样；\n'
		'2. 品牌名 / 产品名（MIUI、HyperOS、Xiaomi、Redmi、POCO 等）不翻译；\n'
		'3. 模块名用该系统语言里常见的设置项译法；日志句子保持简洁；\n'
		'4. 只翻译 targets 里列出的语言；不确定就省略该语言或给低 confidence，不要编造；\n'
		'5. 不要解释，不要输出 Markdown。'
	)

	@classmethod
	def _owner_language_bits(cls, owners: Dict[Tuple[str, int], List[Any]]
							 ) -> Tuple[Dict[int, int], Dict[int, int]]:
		module_bits: Dict[int, int] = defaultdict(int)
		entry_bits: Dict[int, int] = defaultdict(int)
		for refs in owners.values():
			for item in refs:
				if not (isinstance(item, list) and len(item) >= 3):
					continue
				try:
					module_id = int(item[0])
					mask = int(item[2])
				except (TypeError, ValueError):
					continue
				if not mask:
					continue
				module_bits[module_id] |= mask
				for entry_id in item[1] or []:
					try:
						entry_bits[int(entry_id)] |= mask
					except (TypeError, ValueError):
						continue
		return module_bits, entry_bits

	@classmethod
	def missing_rows(cls, rows: Dict[int, Dict[str, Any]],
					 owners: Optional[Dict[Tuple[str, int], List[Any]]] = None,
					 ids: Optional[Sequence[int]] = None,
					 expected: str = 'all', langs: Optional[Sequence[str]] = None,
					 types: Sequence[str] = ('module', 'log'),
					 include_unproofed: bool = False,
					 offset: int = 0, limit: int = 0) -> List[Dict[str, Any]]:
		"""列出 proofed 行缺失的语言（不调用 AI）"""
		if expected not in ('all', 'owners'):
			raise ValueError('expected 只能是 all / owners')
		allowed = set(langs or LogStore.LANG_COLUMNS)
		if owners is None and expected == 'owners':
			owners = LogMaintenance.load_owners()
		module_bits, entry_bits = (cls._owner_language_bits(owners or {})
								   if expected == 'owners' else ({}, {}))
		target_ids = sorted(int(item) for item in ids) if ids else [
			row_id for row_id, row in rows.items()
			if (include_unproofed or row.get('proofed')) and row['type'] in types]
		result: List[Dict[str, Any]] = []
		for row_id in target_ids:
			row = rows.get(row_id)
			if not row or row['type'] not in types:
				continue
			if not (include_unproofed or row.get('proofed')):
				continue
			texts = row['texts']
			zh = texts.get(ZH_COLUMN) or row.get('content') or ''
			en = texts.get(EN_COLUMN) or ''
			if not zh and not en:
				continue
			if expected == 'all':
				expected_columns = set(LogStore.LANG_COLUMNS)
			else:
				bits = (module_bits.get(row_id, 0) if row['type'] == 'module'
						else entry_bits.get(row_id, 0))
				expected_columns = set(LogStore.columns_of(bits))
				if not expected_columns:
					continue
			missing = [column for column in LogStore.LANG_COLUMNS
					   if column in expected_columns and column in allowed
					   and not texts.get(column)]
			if not missing:
				continue
			result.append({
				'row_id': row_id,
				'type': row['type'],
				'content': row.get('content') or '',
				'zh': zh,
				'en': en,
				'missing': missing,
			})
		if offset:
			result = result[offset:]
		if limit:
			result = result[:limit]
		return result

	@classmethod
	def build_prompt(cls, item: Dict[str, Any]) -> List[Dict[str, str]]:
		payload = {
			'type': item['type'],
			'zh': item['zh'],
			'en': item['en'],
			'targets': {column: LANG_NAMES.get(column, column) for column in item['missing']},
		}
		return [
			{'role': 'system', 'content': cls.SYSTEM_PROMPT},
			{'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
		]

	@classmethod
	def parse_translations(cls, payload: Dict[str, Any], item: Dict[str, Any],
						   min_confidence: float = 0.8) -> Dict[str, Dict[str, Any]]:
		raw = payload.get('translations')
		if not isinstance(raw, dict):
			return {}
		zh = LogStore.normalize(item.get('zh'))
		en = LogStore.normalize(item.get('en'))
		result: Dict[str, Dict[str, Any]] = {}
		for column in item['missing']:
			detail = raw.get(column)
			if detail is None:
				continue
			if not isinstance(detail, dict):
				detail = {'text': str(detail)}
			text = str(detail.get('text') or '').strip()
			if not text:
				continue
			try:
				confidence = float(detail.get('confidence') or 0)
			except (TypeError, ValueError):
				confidence = 0.0
			if confidence < min_confidence:
				continue
			normalized = LogStore.normalize(text)
			if not normalized:
				continue
			if column != EN_COLUMN and en and normalized == en:
				continue
			if column != ZH_COLUMN and zh and normalized == zh and column != 'logs_zh_tw':
				continue
			result[column] = {'text': text[:4000], 'confidence': round(confidence, 3)}
		return result

	@classmethod
	def estimate(cls, items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
		rows = len(items)
		columns = sum(len(item['missing']) for item in items)
		# 粗略：每次 system+source 约 700 tokens，每个目标语言输出约 60 tokens
		prompt_tokens = rows * 700 + sum(len(item['zh']) + len(item['en']) for item in items) // 2
		completion_tokens = columns * 60
		return {'rows': rows, 'columns': columns, 'calls': rows,
				'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens,
				'total_tokens': prompt_tokens + completion_tokens}

	@classmethod
	def run(cls, items: Sequence[Dict[str, Any]], client: DeepSeekClient,
			min_confidence: float = 0.8, cache_path: Optional[str] = None,
			on_row=None) -> List[Dict[str, Any]]:
		cache: Dict[str, Any] = {}
		if cache_path:
			path = Path(cache_path)
			if path.exists():
				try:
					cache = json.loads(path.read_text(encoding='utf-8'))
				except json.JSONDecodeError:
					cache = {}
		results: List[Dict[str, Any]] = []
		for index, item in enumerate(items, 1):
			key = f"{item['row_id']}:{','.join(item['missing'])}"
			translations = cache.get(key)
			cached = translations is not None
			error = None
			if translations is None:
				try:
					payload = client.json_chat(cls.build_prompt(item))
					translations = cls.parse_translations(payload, item, min_confidence)
				except DeepSeekError as exc:
					translations = {}
					error = str(exc)[:200]
				if translations:
					cache[key] = translations
					if cache_path:
						Path(cache_path).write_text(
							json.dumps(cache, ensure_ascii=False), encoding='utf-8')
			result = {**item, 'translations': translations or {},
					  'cached': cached, 'error': error}
			results.append(result)
			if on_row:
				on_row(index, len(items), result)
		return results

	@classmethod
	def apply(cls, results: Sequence[Dict[str, Any]], rows: Dict[int, Dict[str, Any]],
			  apply: bool = False, keep_proofed: bool = False,
			  backup: bool = True, backup_path: Optional[str] = None) -> Dict[str, Any]:
		"""把翻译写回；默认 proofed=0（新增译文需要重新校对）"""
		actions = []
		for result in results:
			translations = result.get('translations') or {}
			row = rows.get(result['row_id'])
			if not translations or not row:
				continue
			texts = dict(row['texts'])
			texts.update({column: detail['text'] for column, detail in translations.items()})
			content = LogStore.primary_text(texts)
			issues = dict(row.get('lang_issues') or {})
			for column in translations:
				issues.pop(column, None)
			proofed = 1 if keep_proofed and not issues else 0
			complete = 1 if proofed and all(texts.get(column) for column in LogStore.LANG_COLUMNS) else 0
			actions.append({
				'row_id': row['id'],
				'columns': {column: detail['text'] for column, detail in translations.items()},
				'content': content,
				'content_hash': LogStore.hash_text(content),
				'lang_issues': issues,
				'proofed': proofed,
				'complete': complete,
			})
		stats = {'rows': len(actions),
				 'columns': sum(len(action['columns']) for action in actions),
				 'complete': sum(1 for action in actions if action['complete'])}
		output = {**stats, 'actions': actions, 'applied': False, 'backup': None}
		if not apply or not actions:
			return output
		if backup:
			output['backup'] = LogMaintenance.backup(backup_path)
		with LogStore.write_lock():
			for action in actions:
				parts = [f'`{column}` = %s' for column in action['columns']]
				params: List[Any] = list(action['columns'].values())
				parts.extend(['`content` = %s', '`content_hash` = %s',
							  '`proofed` = %s', '`complete` = %s'])
				params.extend([action['content'], action['content_hash'],
							   action['proofed'], action['complete']])
				if action['lang_issues']:
					parts.append('`lang_issues` = %s')
					params.append(json.dumps(action['lang_issues'], ensure_ascii=False))
				else:
					parts.append('`lang_issues` = NULL')
				params.append(action['row_id'])
				DatabaseManager.execute(
					f"UPDATE `logs` SET {', '.join(parts)} WHERE `id` = %s",
					params=tuple(params), raise_on_error=True)
		LogStore.refresh_cache()
		output['applied'] = True
		return output
