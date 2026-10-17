"""
miroms.logs_mixed - 处理 mixed_translations 的两步修复框架

第一步：把 mixed 行的中文翻成英文，按英文/中文相似度找候选行，再让 AI 对比是否同一内容；
        一致则把 mixed 行合并到候选行（删除 mixed 行并重写 roms/dev 引用）。
第二步：找不到一致的候选时，让 AI 把各语言按语义聚类；每个簇成为新行，AI 补齐缺失语言；
        按引用掩码与各簇原始语言集合的交集路由引用；歧义位置保留原行并标记待人工。

本模块只负责计划和执行；输入 decisions 必须与当前 rows 校验，过期（row_id 指向别的行）直接跳过。
"""
import copy
import difflib
import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from miroms.database import DatabaseManager
from miroms.logs_fill import LogFiller
from miroms.logs_maintenance import LogMaintenance
from miroms.logs_store import LogStore


class MixedTranslationFixer:
	"""mixed_translations 的两步修复"""

	@staticmethod
	def _norm(value: Any) -> str:
		return LogStore.normalize(value)

	@classmethod
	def validate_decisions(cls, decisions: Sequence[Dict[str, Any]],
							rows: Dict[int, Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
		valid, stale = [], []
		for decision in decisions:
			row = rows.get(int(decision.get('row_id') or 0))
			current = cls._norm((row or {}).get('texts', {}).get(LogStore.ZH_COLUMN)
								or (row or {}).get('content'))
			if (row and row['type'] == decision.get('type')
					and current == cls._norm(decision.get('current_zh'))):
				valid.append(decision)
			else:
				stale.append(decision)
		return valid, stale

	@classmethod
	def translate_english(cls, row: Dict[str, Any], client) -> str:
		en = cls._norm(row['texts'].get(LogStore.EN_COLUMN))
		if en:
			return en
		payload = {
			'type': row['type'],
			'zh': cls._norm(row['texts'].get(LogStore.ZH_COLUMN) or row['content']),
		}
		messages = [
			{'role': 'system', 'content': '只输出 JSON：{"en":"..."}，把中文翻译成简洁英文，不要解释。'},
			{'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
		]
		try:
			return cls._norm(client.json_chat(messages).get('en'))
		except Exception:
			return ''

	@classmethod
	def candidates(cls, row: Dict[str, Any], rows: Dict[int, Dict[str, Any]],
				   en: str, limit: int = 5) -> List[Tuple[int, float]]:
		zh = cls._norm(row['texts'].get(LogStore.ZH_COLUMN) or row['content'])
		scored = []
		for other_id, other in rows.items():
			if other_id == row['id'] or other['type'] != row['type']:
				continue
			values = [
				cls._norm(other['texts'].get(LogStore.EN_COLUMN)),
				cls._norm(other['content']),
				cls._norm(other['texts'].get(LogStore.ZH_COLUMN)),
			]
			score = max((difflib.SequenceMatcher(None, en, value).ratio()
						 for value in values if value), default=0.0)
			zh_score = max((difflib.SequenceMatcher(None, zh, value).ratio()
							for value in values if value), default=0.0)
			score = max(score, zh_score)
			if score >= 0.55:
				scored.append((other_id, round(score, 3)))
		return sorted(scored, key=lambda item: -item[1])[:limit]

	@classmethod
	def same_content(cls, row: Dict[str, Any], other: Dict[str, Any],
					 en: str, client, min_confidence: float = 0.8) -> Optional[Dict[str, Any]]:
		payload = {
			'a': {'zh': cls._norm(row['texts'].get(LogStore.ZH_COLUMN) or row['content']),
				  'en': en},
			'b': {'zh': cls._norm(other['texts'].get(LogStore.ZH_COLUMN) or other['content']),
				  'en': cls._norm(other['texts'].get(LogStore.EN_COLUMN))},
		}
		messages = [
			{'role': 'system', 'content':
				'判断 a 和 b 是否描述同一件日志/同一模块。只输出 JSON：'
				'{"same":true/false,"confidence":0.0,"reason":"..."}。'},
			{'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
		]
		try:
			data = client.json_chat(messages)
		except Exception:
			return None
		try:
			confidence = float(data.get('confidence') or 0)
		except (TypeError, ValueError):
			confidence = 0
		if not data.get('same') or confidence < min_confidence:
			return None
		return {'confidence': round(confidence, 3), 'reason': str(data.get('reason') or '')[:160]}

	@classmethod
	def cluster(cls, row: Dict[str, Any], en: str, client) -> Optional[Dict[str, Any]]:
		texts = {column: value for column, value in row['texts'].items()
				 if column != LogStore.ZH_COLUMN and value}
		payload = {
			'type': row['type'],
			'zh': cls._norm(row['texts'].get(LogStore.ZH_COLUMN) or row['content']),
			'en': en,
			'texts': texts,
		}
		messages = [
			{'role': 'system', 'content':
				'把同一行里语义不同的语言译文按含义分组。只输出 JSON：'
				'{"clusters":[{"langs":["logs_ja","logs_ko"],"zh":"...","en":"..."}]}。'
				'每个非中文语言列必须且只能出现在一个簇里；簇内 zh 是该含义的简体中文，en 是英文。'
				'至少返回两个簇。'},
			{'role': 'user', 'content': json.dumps(payload, ensure_ascii=False)},
		]
		try:
			data = client.json_chat(messages)
		except Exception:
			return None
		clusters = data.get('clusters')
		if not isinstance(clusters, list) or len(clusters) < 2:
			return None
		available = set(texts)
		seen = set()
		result = []
		for item in clusters:
			if not isinstance(item, dict):
				return None
			langs = [column for column in item.get('langs') or []
					 if column in available and column not in seen]
			if not langs:
				return None
			seen.update(langs)
			result.append({'langs': langs,
						   'zh': cls._norm(item.get('zh')),
						   'en': cls._norm(item.get('en'))})
		if seen != available:
			return None
		return {'clusters': result}

	@classmethod
	def _positions(cls, owners: Dict[Tuple[str, int], List[Any]],
				   row_id: int) -> List[Tuple[str, int, int, int, List[int]]]:
		result = []
		for (table, owner_id), refs in owners.items():
			for position, item in enumerate(refs):
				if not (isinstance(item, list) and len(item) >= 3):
					continue
				try:
					module_id = int(item[0])
					entries = [int(x) for x in (item[1] or [])]
					mask = int(item[2])
				except (TypeError, ValueError):
					continue
				result.append((table, owner_id, position, mask, entries))
		return result

	@classmethod
	def _route_cluster(cls, clusters: Sequence[Dict[str, Any]], mask: int) -> Optional[int]:
		mask_columns = set(LogStore.columns_of(mask))
		scores = [len(set(cluster['langs']) & mask_columns) for cluster in clusters]
		best = max(scores)
		if best <= 0 or scores.count(best) != 1:
			return None
		return scores.index(best)

	@classmethod
	def plan(cls, decisions: Sequence[Dict[str, Any]], rows: Dict[int, Dict[str, Any]],
			 owners: Dict[Tuple[str, int], List[Any]], client,
			 min_confidence: float = 0.8, max_candidates: int = 5) -> Dict[str, Any]:
		valid, stale = cls.validate_decisions(decisions, rows)
		actions: List[Dict[str, Any]] = []
		for decision in valid:
			row = rows[decision['row_id']]
			en = cls.translate_english(row, client)
			merge = None
			for other_id, score in cls.candidates(row, rows, en, limit=max_candidates):
				other = rows[other_id]
				compared = cls.same_content(row, other, en, client, min_confidence)
				if compared:
					merge = {'target_id': other_id, 'score': score, **compared}
					break
			if merge:
				actions.append({'action': 'merge', 'row_id': row['id'],
								'type': row['type'], 'en': en, **merge})
				continue
			grouped = cls.cluster(row, en, client)
			if not grouped:
				actions.append({'action': 'manual', 'row_id': row['id'],
								'type': row['type'], 'en': en,
								'reason': 'cluster_failed'})
				continue
			clusters = grouped['clusters']
			# 路由检查：只检查引用该行的位置
			positions = [item for item in cls._positions(owners, row['id'])
						 if (item[0] == 'roms' or item[0] == 'dev')]
			routing = []
			ambiguous = []
			for table, owner_id, position, mask, entries in positions:
				refs = owners[(table, owner_id)][position]
				is_module = int(refs[0]) == row['id']
				is_entry = row['id'] in entries
				if not (is_module or is_entry):
					continue
				index = cls._route_cluster(clusters, mask)
				if index is None:
					ambiguous.append({'table': table, 'owner_id': owner_id,
									  'position': position, 'mask': mask})
				else:
					routing.append({'table': table, 'owner_id': owner_id,
									'position': position, 'module': is_module,
									'cluster': index})
			actions.append({'action': 'split', 'row_id': row['id'],
							'type': row['type'], 'en': en, 'clusters': clusters,
							'routing': routing, 'ambiguous': ambiguous})
		return {'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
				'valid': len(valid), 'stale': len(stale),
				'stale_ids': [item.get('row_id') for item in stale[:20]],
				'actions': actions,
				'stats': {'merge': sum(1 for a in actions if a['action'] == 'merge'),
						  'split': sum(1 for a in actions if a['action'] == 'split'),
						  'manual': sum(1 for a in actions if a['action'] == 'manual'),
						  'ambiguous': sum(len(a.get('ambiguous') or []) for a in actions)}}

	@classmethod
	def _fill_cluster(cls, row: Dict[str, Any], cluster: Dict[str, Any],
					  client, min_confidence: float) -> Dict[str, str]:
		texts = {column: row['texts'][column] for column in cluster['langs']
				 if row['texts'].get(column)}
		zh = cluster.get('zh') or LogStore.normalize(
			row['texts'].get(LogStore.ZH_COLUMN) or row['content'])
		en = cluster.get('en') or LogStore.normalize(row['texts'].get(LogStore.EN_COLUMN))
		missing = [column for column in LogStore.LANG_COLUMNS
				   if column not in texts and column not in (LogStore.ZH_COLUMN, LogStore.EN_COLUMN)]
		if missing:
			item = {'row_id': 0, 'type': row['type'], 'zh': zh, 'en': en,
					'missing': missing}
			try:
				payload = client.json_chat(LogFiller.build_prompt(item))
				for column, detail in LogFiller.parse_translations(
						payload, item, min_confidence).items():
					texts[column] = detail['text']
			except Exception:
				pass
		texts[LogStore.ZH_COLUMN] = zh
		if en:
			texts[LogStore.EN_COLUMN] = en
		return texts

	@classmethod
	def apply_splits(cls, plan: Dict[str, Any], rows: Dict[int, Dict[str, Any]],
					 owners: Dict[Tuple[str, int], List[Any]], client,
					 apply: bool = False, backup: bool = True,
					 backup_path: Optional[str] = None,
					 min_confidence: float = 0.8) -> Dict[str, Any]:
		splits = [action for action in plan['actions']
				  if action['action'] == 'split' and not action.get('ambiguous')]
		result = {'rows': len(splits), 'new_rows': 0, 'applied': False,
				  'backup': None, 'skipped_ambiguous': sum(
					  1 for action in plan['actions']
					  if action['action'] == 'split' and action.get('ambiguous'))}
		if not apply or not splits:
			return result
		if backup:
			result['backup'] = LogMaintenance.backup(backup_path)
		with LogStore.write_lock():
			with DatabaseManager.transaction():
				for action in splits:
					row = rows.get(action['row_id'])
					if not row:
						continue
					new_ids = []
					for cluster in action['clusters']:
						texts = cls._fill_cluster(row, cluster, client, min_confidence)
						content = LogStore.primary_text(texts)
						new_id = LogStore._insert_row(
							{'type': row['type'], 'content': content, 'texts': texts})
						new_ids.append(new_id)
						result['new_rows'] += 1
					ref_updates: Dict[Tuple[str, int], List[Any]] = {}
					for item in action['routing']:
						key = (item['table'], item['owner_id'])
						refs = ref_updates.get(key)
						if refs is None:
							refs = copy.deepcopy(owners[key])
							ref_updates[key] = refs
						position = item['position']
						cluster_id = new_ids[item['cluster']]
						if item['module']:
							refs[position][0] = cluster_id
						else:
							entries = list(refs[position][1] or [])
							refs[position][1] = [cluster_id if int(x) == row['id'] else x
												 for x in entries]
					for (table, owner_id), refs in ref_updates.items():
						DatabaseManager.execute(
							f"UPDATE `{table}` SET `logs` = %s WHERE `id` = %s",
							params=(json.dumps(refs, ensure_ascii=False), owner_id),
							raise_on_error=True)
					DatabaseManager.execute("DELETE FROM `logs` WHERE `id` = %s",
											params=(row['id'],), raise_on_error=True)
		LogStore.refresh_cache()
		result['applied'] = True
		return result

	@classmethod
	def apply_merges(cls, plan: Dict[str, Any], rows: Dict[int, Dict[str, Any]],
					 apply: bool = False, backup: bool = True,
					 backup_path: Optional[str] = None) -> Dict[str, Any]:
		merges = [action for action in plan['actions'] if action['action'] == 'merge']
		result = {'rows': len(merges), 'applied': False, 'backup': None}
		if not apply or not merges:
			return result
		if backup:
			result['backup'] = LogMaintenance.backup(backup_path)
		mapping = {action['row_id']: action['target_id'] for action in merges}
		merged_rows = {action['target_id']: rows[action['target_id']] for action in merges}
		LogMaintenance.apply_duplicates(mapping, merged_rows)
		result['applied'] = True
		return result
