"""
miroms.logs_clean - 清理 logs 行开头的空格 / 标点符号

规则：
- 只看 ``content`` 是否以空格或标点符号开头；
- ``*`` 例外：以 ``*`` 开头的行不处理，保留星号；
- 处理时去掉开头连续的空白和标点，直到遇到第一个非空白/非标点字符，或遇到 ``*``；
- ``content`` 和所有非空语言列都清理；清理后为空则跳过该列/该行；
- 修改后重置 proofed / complete，清空 lang_issues，并重建 content / content_hash。
"""
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from miroms.constants import CHANGELOG_LOCALES
from miroms.database import DatabaseManager
from miroms.logs_maintenance import LogMaintenance
from miroms.logs_store import LogStore

LANG_COLUMNS = LogStore.LANG_COLUMNS


def is_bad_start(text: Any) -> bool:
	value = str(text or '')
	if not value:
		return False
	ch = value[0]
	if ch == '*':
		return False
	return ch.isspace() or unicodedata.category(ch).startswith('P')


def clean_prefix(text: Any) -> Tuple[str, bool]:
	"""去掉开头空白/标点（遇到 * 立即停止），返回 (新文本, 是否变化)"""
	value = str(text or '')
	original = value
	value = value.lstrip()
	while value:
		ch = value[0]
		if ch == '*':
			break
		if ch.isspace() or unicodedata.category(ch).startswith('P'):
			value = value[1:]
			continue
		break
	return value, value != original


class LogPrefixCleaner:
	"""清理 content / 语言列开头的空白和标点"""

	@classmethod
	def plan(cls, rows: Dict[int, Dict[str, Any]],
			 types: Sequence[str] = ('module', 'log'),
			 limit: int = 0) -> Dict[str, Any]:
		actions: List[Dict[str, Any]] = []
		skipped: List[Dict[str, Any]] = []
		for row_id in sorted(rows):
			row = rows[row_id]
			if row['type'] not in types or not is_bad_start(row.get('content')):
				continue
			content, content_changed = clean_prefix(row.get('content'))
			if not content:
				skipped.append({'row_id': row_id, 'reason': 'empty_after_clean'})
				continue
			changes: Dict[str, str] = {}
			if content_changed:
				changes['content'] = content
			for column in LANG_COLUMNS:
				value = row['texts'].get(column)
				if not value:
					continue
				cleaned, changed = clean_prefix(value)
				if not changed:
					continue
				if not cleaned:
					skipped.append({'row_id': row_id, 'column': column,
									'reason': 'column_empty_after_clean'})
					continue
				changes[column] = cleaned
			if 'logs_zh' in changes:
				changes['content'] = changes['logs_zh']
			if not changes:
				continue
			actions.append({
				'row_id': row_id,
				'type': row['type'],
				'changes': changes,
				'before': {column: row['texts'].get(column, '') for column in changes
						   if column != 'content'},
				'content_before': row.get('content') or '',
			})
			if limit and len(actions) >= limit:
				break
		return {
			'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
			'actions': actions,
			'skipped': skipped,
			'stats': {
				'rows': len(actions),
				'columns': sum(len(action['changes']) for action in actions),
				'content': sum(1 for action in actions if 'content' in action['changes']),
				'lang_columns': sum(1 for action in actions for column in action['changes']
									if column != 'content'),
				'skipped': len(skipped),
			},
		}

	@classmethod
	def apply(cls, plan: Dict[str, Any], apply: bool = False,
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
			with DatabaseManager.transaction():
				for action in plan['actions']:
					changes = action['changes']
					content = changes.get('content', action['content_before'])
					parts: List[str] = []
					params: List[Any] = []
					for column, value in changes.items():
						parts.append(f'`{column}` = %s')
						params.append(value)
					parts.extend(['`content` = %s', '`content_hash` = %s',
								  '`proofed` = 0', '`complete` = 0',
								  '`lang_issues` = NULL'])
					params.extend([content, LogStore.hash_text(content), action['row_id']])
					DatabaseManager.execute(
						f"UPDATE `logs` SET {', '.join(parts)} WHERE `id` = %s",
						params=tuple(params), raise_on_error=True)
		LogStore.refresh_cache()
		result['applied'] = True
		return result
