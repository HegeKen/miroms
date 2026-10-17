"""
miroms.logs_restore - 还原旧 JSON 存储时代的转义

旧代码在写库前执行：
    d.replace('%','$$').replace('"','^').replace("'", "^")

新版日志按语言列存储，不再需要这些转义。本模块负责：

- ``$$`` -> ``%``
- ``\\^`` -> ``'``（历史上反斜杠 + 上撇被转义成 \\^）
- 词中间的 ``^`` -> ``'``（won^t / l^écran / 2025^te）
- 成对引号 ``^...^`` -> ``"..."``；``^^...^^`` 合并为一对双引号
- ``^’`` -> ``’``
- 剩余的字母相邻 ``^`` -> ``'``
- 更新 content / content_hash；默认保留 proofed / complete / lang_issues（机械转义还原，不改语义）
"""
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from miroms.database import DatabaseManager
from miroms.logs_maintenance import LogMaintenance
from miroms.logs_store import LogStore

BETWEEN = re.compile(r'(?<=[^\W_])\^(?=[^\W_])')
DOUBLE = re.compile(r'\^\^([^\^\n]{1,80}?)\^\^')
PAIR = re.compile(r'(?<![^\W_])\^([^\^\n]{1,80}?)\^(?![^\W_])')
RESIDUAL = re.compile(r'(?<=[^\W_])\^|\^(?=[^\W_])')


def restore_text(value: Any) -> str:
	"""还原一段旧转义文本"""
	text = str(value or '')
	text = text.replace('\\^', "'").replace('$$', '%')
	text = BETWEEN.sub("'", text)
	text = DOUBLE.sub(lambda match: '"' + match.group(1).strip('"') + '"', text)

	def pair_replacement(match):
		inner = match.group(1)
		if len(inner) >= 2 and inner.startswith('"') and inner.endswith('"'):
			return inner
		return '"' + inner + '"'

	text = PAIR.sub(pair_replacement, text)
	text = text.replace("^’", "’").replace("^'", "'")
	text = RESIDUAL.sub("'", text)
	return text


class LogEscapeRestorer:
	"""还原 logs 里的旧转义字符"""

	@classmethod
	def plan(cls, rows: Dict[int, Dict[str, Any]], limit: int = 0,
			 reset_flags: bool = False) -> Dict[str, Any]:
		actions: List[Dict[str, Any]] = []
		for row_id in sorted(rows):
			row = rows[row_id]
			old_content = row.get('content') or ''
			new_content = restore_text(old_content)
			changes: Dict[str, str] = {}
			for column in LogStore.LANG_COLUMNS:
				value = row['texts'].get(column)
				if not value:
					continue
				restored = restore_text(value)
				if restored != value:
					changes[column] = restored
			if new_content != old_content:
				changes['content'] = new_content
			if 'logs_zh' in changes:
				changes['content'] = changes['logs_zh']
			if not changes:
				continue
			actions.append({
				'row_id': row_id,
				'type': row['type'],
				'changes': changes,
				'content_before': old_content,
				'before': {column: row['texts'].get(column) or '' for column in changes
						   if column != 'content'},
				'reset_flags': reset_flags,
			})
			if limit and len(actions) >= limit:
				break
		return {
			'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
			'actions': actions,
			'stats': {
				'rows': len(actions),
				'columns': sum(len(action['changes']) for action in actions),
				'content': sum(1 for action in actions if 'content' in action['changes']),
				'lang_columns': sum(1 for action in actions for column in action['changes']
									if column != 'content'),
			},
			'applied': False,
			'backup': None,
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
					parts.extend(['`content` = %s', '`content_hash` = %s'])
					params.extend([content, LogStore.hash_text(content)])
					if action.get('reset_flags'):
						parts.extend(['`proofed` = 0', '`complete` = 0',
									  '`lang_issues` = NULL'])
					params.append(action['row_id'])
					DatabaseManager.execute(
						f"UPDATE `logs` SET {', '.join(parts)} WHERE `id` = %s",
						params=tuple(params), raise_on_error=True)
		LogStore.refresh_cache()
		result['applied'] = True
		return result
