"""
miroms.logs_lang_fix - 按 logs.lang_issues 修正语言列

lang_issues 由 LogProofreader 在 AI 校对时写入，格式：

    {"logs_de": {"detected": "英文", "confidence": 0.98, "reason": "..."}}

本模块按标注修复 logs 行：

- ``correct``（默认）：AI 给了 ``correct`` 且 confidence ≥ 阈值时，直接用正确译文替换；
  没有 correct 或置信度不足时**保留原值并继续标注，不删除**；
- ``translate``：对没有可用 correct 的 lang_issues，调用 AI 翻译并回填；翻译成功即清除该条
  lang_issues，低置信度/失败则保留标注（不删除原值）；
- ``hybrid``：有正确译文则替换，否则清空；
- ``clear``：把不是该语言的列置为 NULL（显式选择才删除）；
- ``move``：如果检测到的语言能映射到另一个语言列、且该列当前为空，则把文本移动过去，
  否则仍然清空；目标列不会映射到 logs_zh / logs_en（避免改主内容）；
- ``--clean-masks``：对 module 行，把被清空语言在 roms/dev 引用掩码里的位去掉；
- 修正后同步更新 lang_issues（去掉已修正的项），全部修正完时置 NULL，并把 proofed 重置为 0。

默认 dry-run，写库前备份。

用法：
    python3 scripts/fix_lang_issues.py                     # 预览全部
    python3 scripts/fix_lang_issues.py --ids 1,165        # 只处理指定行
    python3 scripts/fix_lang_issues.py --apply
    python3 scripts/fix_lang_issues.py --mode move --apply
    python3 scripts/fix_lang_issues.py --clean-masks --apply
"""
import copy
import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from miroms.constants import CHANGELOG_LOCALES
from miroms.database import DatabaseManager
from miroms.logs_fill import LogFiller
from miroms.logs_maintenance import LogMaintenance
from miroms.logs_store import LogStore

# 语言列 -> 中文名（与 LogProofreader.LANG_NAMES 一致）
LANG_NAMES = {item['column']: item['zh'] for item in CHANGELOG_LOCALES}
# 反向：AI / 人可能的写法 -> 语言列
DETECTED_ALIASES = {
	'英文': 'logs_en', '英语': 'logs_en', 'English': 'logs_en', 'en': 'logs_en',
	'简体中文': 'logs_zh', '中文': 'logs_zh', 'Chinese': 'logs_zh', 'zh': 'logs_zh',
	'繁体中文': 'logs_zh_tw', '繁體中文': 'logs_zh_tw', 'zh_tw': 'logs_zh_tw',
	'日文': 'logs_ja', '日语': 'logs_ja', 'Japanese': 'logs_ja', 'ja': 'logs_ja',
	'韩文': 'logs_ko', '韩语': 'logs_ko', 'Korean': 'logs_ko', 'ko': 'logs_ko',
	'俄文': 'logs_ru', '俄语': 'logs_ru', 'Russian': 'logs_ru', 'ru': 'logs_ru',
	'乌克兰文': 'logs_uk', 'Ukrainian': 'logs_uk', 'uk': 'logs_uk',
	'波兰文': 'logs_pl', 'Polish': 'logs_pl', 'pl': 'logs_pl',
	'德文': 'logs_de', '德语': 'logs_de', 'German': 'logs_de', 'de': 'logs_de',
	'法文': 'logs_fr', '法语': 'logs_fr', 'French': 'logs_fr', 'fr': 'logs_fr',
	'意大利文': 'logs_it', 'Italian': 'logs_it', 'it': 'logs_it',
	'西班牙文': 'logs_es', 'Spanish': 'logs_es', 'es': 'logs_es',
	'葡萄牙文': 'logs_pt', 'Portuguese': 'logs_pt', 'pt': 'logs_pt',
	'土耳其文': 'logs_tr', 'Turkish': 'logs_tr', 'tr': 'logs_tr',
	'印尼文': 'logs_id', 'Indonesian': 'logs_id', 'id': 'logs_id',
	'越南文': 'logs_vi', 'Vietnamese': 'logs_vi', 'vi': 'logs_vi',
	'泰文': 'logs_th', 'Thai': 'logs_th', 'th': 'logs_th',
	'阿拉伯文': 'logs_ar', 'Arabic': 'logs_ar', 'ar': 'logs_ar',
	'印地文': 'logs_in', 'Hindi': 'logs_in', 'in': 'logs_in',
	'维吾尔文': 'logs_ug', 'Uyghur': 'logs_ug', 'ug': 'logs_ug',
	'藏文': 'logs_bo', 'Tibetan': 'logs_bo', 'bo': 'logs_bo',
}
for _column, _name in LANG_NAMES.items():
	DETECTED_ALIASES.setdefault(_name, _column)

CORE_COLUMNS = (LogStore.ZH_COLUMN, LogStore.EN_COLUMN)


class LogLangFixer:
	"""按 lang_issues 修正语言列（类方法，无需实例化）"""

	@staticmethod
	def detect_column(detected: Any) -> Optional[str]:
		"""把 AI 的 detected 文本映射到语言列（尽可能保守）"""
		value = str(detected or '').strip()
		if not value:
			return None
		if value.startswith('与 logs_en'):
			return LogStore.EN_COLUMN
		if value in DETECTED_ALIASES:
			return DETECTED_ALIASES[value]
		for name, column in DETECTED_ALIASES.items():
			if len(name) > 1 and (name in value or value in name):
				return column
		return None

	@classmethod
	def plan(cls, rows: Dict[int, Dict[str, Any]],
			 owners: Optional[Dict[Tuple[str, int], List[Any]]] = None,
			 ids: Optional[Sequence[int]] = None,
			 mode: str = 'correct', allow_core: bool = False,
			 clean_masks: bool = False, min_confidence: float = 0.8,
			 limit: int = 0, client=None, on_progress=None,
			 on_action=None) -> Dict[str, Any]:
		"""生成修正计划（不改库）

		- mode='clear'：清空被标注的列；
		- mode='move'：能映射到另一个空语言列时移动，否则清空；
		- clean_masks：module 行被清空的语言从引用掩码里去掉。
		"""
		if mode not in ('correct', 'translate', 'hybrid', 'clear', 'move'):
			raise ValueError('mode 只能是 correct / translate / hybrid / clear / move')
		target_ids = [int(item) for item in ids] if ids else [
			row_id for row_id, row in rows.items() if row.get('lang_issues')]
		target_ids = sorted(set(target_ids))
		if limit:
			target_ids = target_ids[:limit]

		actions: List[Dict[str, Any]] = []
		skipped: List[Dict[str, Any]] = []
		cleared_languages: Dict[int, List[str]] = defaultdict(list)
		for index, row_id in enumerate(target_ids, 1):
			if on_progress:
				on_progress(index, len(target_ids), row_id)
			row = rows.get(row_id)
			if not row:
				skipped.append({'row_id': row_id, 'reason': 'missing_row'})
				continue
			issues = dict(row.get('lang_issues') or {})
			if not issues:
				continue
			set_columns: Dict[str, Optional[str]] = {}
			remaining: Dict[str, Any] = {}
			detail_items: List[Dict[str, Any]] = []
			needs_translation: List[Tuple[str, Dict[str, Any]]] = []
			for column, detail in issues.items():
				if column not in LogStore.LANG_COLUMNS:
					skipped.append({'row_id': row_id, 'column': column,
									'reason': 'unknown_column'})
					continue
				if not row['texts'].get(column):
					skipped.append({'row_id': row_id, 'column': column,
									'reason': 'stale_issue'})
					continue
				if column in CORE_COLUMNS and not allow_core:
					remaining[column] = detail
					skipped.append({'row_id': row_id, 'column': column,
									'reason': 'core_column_needs_manual'})
					continue
				detected = (detail or {}).get('detected')
				confidence = float((detail or {}).get('confidence') or 0)
				correct = (detail or {}).get('correct')
				target = cls.detect_column(detected)
				action = None
				if mode in ('correct', 'translate', 'hybrid') and correct and confidence >= min_confidence:
					if LogStore.normalize(correct) != LogStore.normalize(row['texts'][column]):
						set_columns[column] = str(correct)
						action = 'correct'
					else:
						action = 'no_change'
				elif mode == 'correct':
					remaining[column] = detail
					skipped.append({'row_id': row_id, 'column': column,
									'reason': 'no_correct_translation' if not correct
											  else 'low_confidence'})
					continue
				elif mode == 'translate':
					needs_translation.append((column, detail))
					continue
				elif (mode == 'move' and target and target != column
					  and target not in CORE_COLUMNS
					  and target in LogStore.LANG_COLUMNS
					  and not row['texts'].get(target)):
					set_columns[column] = None
					set_columns[target] = str(row['texts'][column])
					cleared_languages[row_id].append(column)
					action = 'move'
				elif mode in ('move', 'hybrid', 'clear'):
					set_columns[column] = None
					cleared_languages[row_id].append(column)
					action = 'clear'
				if action is None:
					continue
				detail_items.append({'column': column, 'detected': detected,
									 'confidence': confidence,
									 'action': action,
									 'correct': correct,
									 'target': target if action == 'move' else None})
			if needs_translation:
				zh = LogStore.normalize(row['texts'].get(LogStore.ZH_COLUMN) or row['content'])
				en = LogStore.normalize(row['texts'].get(LogStore.EN_COLUMN))
				if not client:
					for column, detail in needs_translation:
						remaining[column] = detail
						skipped.append({'row_id': row_id, 'column': column,
										'reason': 'ai_required'})
				else:
					item = {'row_id': row_id, 'type': row['type'], 'zh': zh, 'en': en,
							'missing': [column for column, _detail in needs_translation]}
					translated: Dict[str, Dict[str, Any]] = {}
					try:
						payload = client.json_chat(LogFiller.build_prompt(item))
						translated = LogFiller.parse_translations(
							payload, item, min_confidence)
					except Exception as exc:
						for column, detail in needs_translation:
							remaining[column] = detail
							skipped.append({'row_id': row_id, 'column': column,
											'reason': f'ai_error: {type(exc).__name__}'})
					for column, detail in needs_translation:
						translation = translated.get(column)
						if not translation:
							remaining[column] = detail
							skipped.append({'row_id': row_id, 'column': column,
											'reason': 'translation_failed'})
							continue
						if LogStore.normalize(translation['text']) == LogStore.normalize(row['texts'][column]):
							detail_items.append({'column': column, 'detected': detail.get('detected'),
												 'confidence': translation['confidence'],
												 'action': 'no_change', 'correct': translation['text'],
												 'target': None})
						else:
							set_columns[column] = translation['text']
							detail_items.append({'column': column, 'detected': detail.get('detected'),
												 'confidence': translation['confidence'],
												 'action': 'translate',
												 'correct': translation['text'], 'target': None})
			if not set_columns and remaining == issues:
				continue
			# 若核心列被清空，content / content_hash 必须按剩余文本重建
			if any(column in CORE_COLUMNS for column in set_columns):
				remaining_texts = {column: value for column, value in row['texts'].items()
								   if column not in set_columns or set_columns[column] is not None}
				for column, value in set_columns.items():
					if value is not None:
						remaining_texts[column] = value
				content = LogStore.primary_text(remaining_texts)
				set_columns['content'] = content
				set_columns['content_hash'] = LogStore.hash_text(content)
			action = {
				'row_id': row_id,
				'type': row['type'],
				'set_columns': set_columns,
				'remaining_issues': remaining,
				'proofed_before': bool(row.get('proofed')),
				'details': detail_items,
			}
			actions.append(action)
			if on_action:
				on_action(action)

		mask_updates: List[Tuple[str, int, str]] = []
		if clean_masks and owners:
			mask_updates = cls._build_mask_updates(actions, cleared_languages, owners)
		return {
			'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
			'mode': mode,
			'actions': actions,
			'skipped': skipped,
			'mask_updates': mask_updates,
			'stats': {
				'rows': len(actions),
				'corrected': sum(1 for action in actions for detail in action['details']
								if detail['action'] == 'correct'),
				'translated': sum(1 for action in actions for detail in action['details']
								 if detail['action'] == 'translate'),
				'cleared': sum(1 for action in actions for detail in action['details']
							   if detail['action'] == 'clear'),
				'moved': sum(1 for action in actions for detail in action['details']
							 if detail['action'] == 'move'),
				'skipped': len(skipped),
				'mask_updates': len(mask_updates),
			},
			'applied': False,
		}

	@classmethod
	def _build_mask_updates(cls, actions: Sequence[Dict[str, Any]],
							cleared_languages: Dict[int, List[str]],
							owners: Dict[Tuple[str, int], List[Any]]
							) -> List[Tuple[str, int, str]]:
		"""module 行被清空的语言从 roms/dev 引用掩码里去掉"""
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
				if mask:
					index[module_id].append((table, owner_id, position, mask))
		copies: Dict[Tuple[str, int], List[Any]] = {}
		for action in actions:
			if action['type'] != 'module':
				continue
			row_id = action['row_id']
			for column in cleared_languages.get(row_id, []):
				bit = 1 << LogStore.LANG_INDEX[column]
				for table, owner_id, position, mask in index.get(row_id, []):
					if not (mask & bit):
						continue
					key = (table, owner_id)
					refs = copies.get(key)
					if refs is None:
						refs = copy.deepcopy(owners[key])
						copies[key] = refs
					refs[position][2] = int(refs[position][2]) & ~bit
		return [(table, owner_id, json.dumps(refs, ensure_ascii=False))
				for (table, owner_id), refs in copies.items()]

	@classmethod
	def plan_restore(cls, backup_rows: Dict[str, Dict[str, Any]],
					 rows: Dict[int, Dict[str, Any]],
					 ids: Optional[Sequence[int]] = None) -> Dict[str, Any]:
		"""从 fix_lang_issues 写库前的备份恢复被清空的列（只恢复当时被标注的列）

		backup_rows 是 LogMaintenance.backup() 的 rows（key 为字符串 id）。
		"""
		targets = {int(item) for item in ids} if ids else None
		actions = []
		skipped = []
		for key, backup in backup_rows.items():
			row_id = int(key)
			if targets is not None and row_id not in targets:
				continue
			current = rows.get(row_id)
			if not current:
				skipped.append({'row_id': row_id, 'reason': 'row_merged_or_deleted'})
				continue
			issues = backup.get('lang_issues') or {}
			if not issues:
				continue
			set_columns = {}
			for column in issues:
				if column not in LogStore.LANG_COLUMNS:
					continue
				old_value = (backup.get('texts') or {}).get(column)
				if old_value and not current['texts'].get(column):
					set_columns[column] = old_value
			if set_columns:
				actions.append({'row_id': row_id, 'set_columns': set_columns})
		return {
			'actions': actions,
			'skipped': skipped,
			'stats': {
				'rows': len(actions),
				'columns': sum(len(action['set_columns']) for action in actions),
				'skipped': len(skipped),
			},
		}

	@classmethod
	def apply_restore(cls, plan: Dict[str, Any], apply: bool = False,
					  backup: bool = True, backup_path: Optional[str] = None) -> Dict[str, Any]:
		result = dict(plan)
		result['applied'] = False
		result['backup'] = None
		if not plan['actions']:
			return result
		if not apply:
			return result
		if backup:
			result['backup'] = LogMaintenance.backup(backup_path)
		with LogStore.write_lock():
			for action in plan['actions']:
				parts = [f'`{column}` = %s' for column in action['set_columns']]
				params = list(action['set_columns'].values())
				parts.extend(['`lang_issues` = NULL', '`proofed` = 0', '`complete` = 0'])
				params.append(action['row_id'])
				DatabaseManager.execute(
					f"UPDATE `logs` SET {', '.join(parts)} WHERE `id` = %s",
					params=tuple(params), raise_on_error=True)
		LogStore.refresh_cache()
		result['applied'] = True
		return result

	@classmethod
	def apply(cls, plan: Dict[str, Any], apply: bool = False, backup: bool = True,
			  backup_path: Optional[str] = None, batch: int = 200) -> Dict[str, Any]:
		"""执行计划（默认 dry-run）"""
		result = dict(plan)
		result['applied'] = False
		result['backup'] = None
		result['rows'] = len(plan['actions'])
		result['columns'] = sum(len(action['set_columns']) for action in plan['actions'])
		if not plan['actions'] and not plan['mask_updates']:
			return result
		if not apply:
			return result
		if backup:
			result['backup'] = LogMaintenance.backup(backup_path)
		with LogStore.write_lock():
			for action in plan['actions']:
				parts: List[str] = []
				params: List[Any] = []
				for column, value in action['set_columns'].items():
					parts.append(f'`{column}` = %s')
					params.append(value)
				remaining = action['remaining_issues']
				if remaining:
					parts.append('`lang_issues` = %s')
					params.append(json.dumps(remaining, ensure_ascii=False))
				else:
					# 全部标注都已修正：显式置 NULL
					parts.append('`lang_issues` = NULL')
				parts.append('`proofed` = 0')
				parts.append('`complete` = 0')
				params.append(action['row_id'])
				DatabaseManager.execute(
					f"UPDATE `logs` SET {', '.join(parts)} WHERE `id` = %s",
					params=tuple(params), raise_on_error=True)
			for table, owner_id, value in plan['mask_updates']:
				DatabaseManager.execute(
					f"UPDATE `{table}` SET `logs` = %s WHERE `id` = %s",
					params=(value, owner_id), raise_on_error=True)
		LogStore.refresh_cache()
		result['applied'] = True
		return result
