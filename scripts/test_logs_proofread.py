"""
test_logs_proofread.py - 日志校对（规则扫描 / AI 返回校验 / 计划）的单元测试

不连数据库、不调用真实 API：DeepSeek 客户端用 FakeClient 替代。
运行：
    python3 data/scripts/test_logs_proofread.py
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.deepseek import DeepSeekClient, DeepSeekError, extract_json
from miroms.logs_maintenance import LogMaintenance
from miroms.logs_proofread import LogProofreader
from miroms.logs_store import LogStore


def row(row_id, content, texts, log_type='module', proofed=False):
	return {'id': row_id, 'type': log_type, 'content': content,
			'proofed': proofed, 'texts': dict(texts)}


ZH = 1
EN = 1 << LogStore.LANG_INDEX['logs_en']


class FakeClient:
	def __init__(self, answers):
		self.answers = answers
		self.calls = 0
		self.last_usage = {}

	def json_chat(self, messages, **kwargs):
		self.calls += 1
		payload = json.loads(messages[-1]['content'])
		results = []
		for item in payload['rows']:
			row_id = item['row_id']
			if row_id in self.answers:
				results.append({'row_id': row_id, **self.answers[row_id]})
		return {'results': results}


class ExtractJsonTest(unittest.TestCase):
	def test_plain_and_fenced(self):
		self.assertEqual({'a': 1}, extract_json('{"a": 1}'))
		self.assertEqual({'a': 2}, extract_json('```json\n{"a": 2}\n```'))
		self.assertEqual({'a': 3}, extract_json('说明文字 {"a": 3} 结束'))

	def test_invalid(self):
		with self.assertRaises(DeepSeekError):
			extract_json('没有 JSON')
		with self.assertRaises(DeepSeekError):
			extract_json('[1, 2]')

	def test_client_requires_key(self):
		with self.assertRaises(DeepSeekError):
			DeepSeekClient(api_key='')


class ScanTest(unittest.TestCase):
	def setUp(self):
		# 同一 ROM：设备互联（正常）+ 两个被填成「其他」的窄行（德文含义不同）
		self.rows = {
			10: row(10, '设备互联', {'logs_zh': '设备互联', 'logs_en': 'Interconnectivity'}),
			20: row(20, '其他', {'logs_zh': '其他', 'logs_de': 'Interkonnektivität',
								'logs_ug': 'ئۈسكۈنە ئالاقىسى', 'logs_bo': 'སྒྲིག་ཆས་མཉམ་སྦྲེལ།'}),
			21: row(21, '其他', {'logs_zh': '其他', 'logs_de': 'Datenschutz und Sicherheit',
								'logs_ug': 'بىخەتەرلىك شەخسىيىتى', 'logs_bo': 'བདེ་འཇགས་གསང་དོན།'}),
		}
		self.owners = {('roms', 1): [[10, [], 7], [20, [], ZH], [21, [], ZH]]}

	def test_finds_conflict_family(self):
		report = LogProofreader.scan(self.rows, self.owners)
		self.assertEqual(1, len(report['families']))
		family = report['families'][0]
		self.assertEqual([20, 21], family['row_ids'])
		self.assertIn('设备互联', family['known_zh'])
		self.assertTrue(family['priority'])
		self.assertEqual(1, report['stats']['priority_families'])

	def test_skips_proofed_rows(self):
		self.rows[20]['proofed'] = True
		report = LogProofreader.scan(self.rows, self.owners)
		self.assertEqual([], report['families'])

	def test_mark_proofed_dry_run(self):
		self.assertEqual(2, LogMaintenance.mark_proofed([20, 21, 20], apply=False))

	def test_skips_consistent_duplicates(self):
		# 同一个 module 在同一 ROM 出现两次（重复位置）不算「中文名冲突」
		owners = {('roms', 1): [[10, [], 7], [10, [], 7]]}
		report = LogProofreader.scan({10: self.rows[10]}, owners)
		self.assertEqual([], report['families'])


class DecisionTest(unittest.TestCase):
	def setUp(self):
		self.family = {
			'key': 'module|其他|20,21',
			'type': 'module',
			'zh': '其他',
			'row_ids': [20, 21],
			'known_zh': ['其他', '设备互联', '安全隐私'],
			'rows': [
				{'row_id': 20, 'current_zh': '其他',
				 'texts': {'logs_de': 'Interkonnektivität', 'logs_ug': 'x', 'logs_bo': 'y'}},
				{'row_id': 21, 'current_zh': '其他', 'texts': {'logs_de': 'Datenschutz'}},
			],
		}

	def test_parse_valid_and_filter_invalid(self):
		payload = {'results': [
			{'row_id': 20, 'zh': '设备互联', 'confidence': 1.2, 'reason': 'x'},
			{'row_id': 21, 'zh': '不存在的中文', 'confidence': 0.9},
			{'row_id': 999, 'zh': '其他', 'confidence': 0.9},
			{'row_id': 21, 'zh': None, 'confidence': 0.4},
		]}
		decisions = LogProofreader.parse_decisions(payload, self.family)
		self.assertEqual(2, len(decisions))
		self.assertEqual(1.0, decisions[0]['confidence'])
		self.assertIsNone(decisions[1]['suggested_zh'])

	def test_verdicts(self):
		payload = {'results': [
			{'row_id': 20, 'verdict': 'mixed_translations', 'zh': '其他', 'confidence': 0.9},
			{'row_id': 21, 'verdict': 'extra_module', 'zh': None, 'confidence': 0.7},
		]}
		decisions = {d['row_id']: d for d in LogProofreader.parse_decisions(payload, self.family)}
		self.assertEqual('mixed_translations', decisions[20]['verdict'])
		self.assertEqual('其他', decisions[20]['suggested_zh'])
		self.assertEqual('extra_module', decisions[21]['verdict'])
		self.assertIsNone(decisions[21]['suggested_zh'])

	def test_lang_issues_parsed(self):
		payload = {'results': [{
			'row_id': 20, 'verdict': 'mixed_translations', 'zh': '其他',
			'confidence': 0.9,
			'lang_issues': {
				'logs_de': {'detected': '英文', 'confidence': 0.9, 'correct': 'Sonstiges', 'reason': 'English'},
				'logs_ug': {'detected': '英文', 'confidence': 0.3},
				'logs_bo': {'detected': '英文', 'confidence': 0.8},
				'logs_not_a_column': {'detected': '英文', 'confidence': 0.9},
			},
		}]}
		decisions = LogProofreader.parse_decisions(payload, self.family)
		issues = decisions[0]['lang_issues']
		self.assertEqual({'logs_de', 'logs_bo'}, set(issues))
		self.assertEqual('英文', issues['logs_de']['detected'])
		self.assertEqual('Sonstiges', issues['logs_de']['correct'])

	def test_prompt_contains_language_rules(self):
		messages = LogProofreader.build_prompt(self.family)
		self.assertIn('lang_issues', messages[0]['content'])
		self.assertIn('logs_de', messages[0]['content'])

	def test_deterministic_english_fallback_issue(self):
		issues = LogProofreader._merge_lang_issues({}, {
			'logs_en': 'Other', 'logs_de': 'Other', 'logs_id': 'Other',
			'logs_ja': 'その他', 'logs_zh': '其他'})
		self.assertEqual({'logs_de', 'logs_id'}, set(issues))
		self.assertIn('logs_en', issues['logs_de']['reason'])

	def test_record_issues_dry_run(self):
		self.assertEqual(2, LogMaintenance.record_lang_issues(
			{1: {'logs_de': {'detected': '英文'}}}, clear_ids=[2], apply=False))

	def test_prompt_contains_context(self):
		messages = LogProofreader.build_prompt(self.family)
		payload = json.loads(messages[-1]['content'])
		self.assertEqual('其他', payload['shared_zh'])
		self.assertIn('设备互联', payload['known_zh'])
		self.assertEqual([20, 21], [item['row_id'] for item in payload['rows']])


class ReviewTest(unittest.TestCase):
	def setUp(self):
		self.family = {
			'key': 'module|其他|20,21',
			'type': 'module',
			'zh': '其他',
			'row_ids': [20, 21],
			'known_zh': ['其他', '设备互联', '安全隐私'],
			'priority': True,
			'owners_count': 1,
			'owners_sample': [['roms', 1]],
			'rows': [
				{'row_id': 20, 'current_zh': '其他', 'langs': 4, 'has_en': False,
				 'texts': {'logs_de': 'Interkonnektivität'}},
				{'row_id': 21, 'current_zh': '其他', 'langs': 4, 'has_en': False,
				 'texts': {'logs_de': 'Datenschutz'}},
			],
		}

	def test_review_and_cache(self):
		fake = FakeClient({
			20: {'zh': '设备互联', 'confidence': 0.9, 'reason': 'de'},
			21: {'zh': '安全隐私', 'confidence': 0.8, 'reason': 'de'},
		})
		with tempfile.TemporaryDirectory() as tmp:
			cache = str(Path(tmp) / 'cache.json')
			first = LogProofreader.review([self.family], fake, cache_path=cache)
			self.assertEqual(1, first['calls'])
			self.assertEqual(2, len(first['decisions']))
			self.assertTrue(Path(cache).exists())
			second = LogProofreader.review([self.family], fake, cache_path=cache)
			self.assertEqual(0, second['calls'])
			self.assertEqual(2, len(second['decisions']))

	def test_review_flushes_decisions_per_family(self):
		fake = FakeClient({
			20: {'zh': '设备互联', 'confidence': 0.9, 'reason': 'de'},
			21: {'zh': '安全隐私', 'confidence': 0.8, 'reason': 'de'},
		})
		flushed = []
		result = LogProofreader.review([self.family], fake,
									   on_decisions=flushed.append)
		self.assertEqual(1, len(flushed))
		self.assertEqual([20, 21], [item['row_id'] for item in flushed[0]])
		self.assertEqual([20, 21], [item['row_id'] for item in result['decisions']])

	def test_review_does_not_flush_filtered_decisions(self):
		fake = FakeClient({
			20: {'zh': '设备互联', 'confidence': 0.9, 'reason': 'de'},
			21: {'zh': '安全隐私', 'confidence': 0.6, 'reason': 'de'},
		})
		flushed = []
		result = LogProofreader.review([self.family], fake, min_confidence=0.8,
									   on_decisions=flushed.append)
		self.assertEqual([20], [item['row_id'] for item in flushed[0]])
		self.assertEqual([20], [item['row_id'] for item in result['decisions']])


class BatchTest(unittest.TestCase):
	def setUp(self):
		self.rows = {
			1: row(1, '其他', {'logs_zh': '其他', 'logs_de': 'Interkonnektivität'}),
			2: row(2, '更多内容', {'logs_zh': '更多内容', 'logs_en': 'More',
								'logs_de': 'Gehe zu Einstellungen'}, log_type='log'),
			3: row(3, '只有中文', {'logs_zh': '只有中文'}, log_type='log'),
			4: row(4, '设备互联', {'logs_zh': '设备互联', 'logs_en': 'Interconnectivity'}),
		}
		self.owners = {('roms', 1): [[4, [], 7], [1, [], ZH]]}

	def test_select_rows(self):
		selected = LogProofreader.select_batch_rows(self.rows, min_langs=2)
		self.assertEqual([2, 1, 4], [r['id'] for r in selected])
		logs = LogProofreader.select_batch_rows(
			self.rows, min_langs=2, types=('log',), include_single=True)
		self.assertEqual([2, 3], [r['id'] for r in logs])

	def test_select_skips_proofed(self):
		self.rows[1]['proofed'] = True
		selected = LogProofreader.select_batch_rows(self.rows, min_langs=2)
		self.assertNotIn(1, [r['id'] for r in selected])

	def test_estimate(self):
		selected, known, batches = LogProofreader.prepare_batches(
			self.rows, self.owners, batch_size=2, min_langs=2)
		self.assertEqual(3, len(selected))
		self.assertEqual(2, len(batches))
		estimate = LogProofreader.estimate_batches(batches, 2, selected)
		self.assertEqual(2, estimate['batches'])
		self.assertLess(estimate['prompt_tokens'][0], estimate['prompt_tokens'][1])
		self.assertIn('设备互联', known[1])

	def test_module_batch_prompt_and_parse(self):
		selected, known, batches = LogProofreader.prepare_batches(
			self.rows, self.owners, batch_size=1, min_langs=2, types=('module',))
		payload = json.loads(batches[0]['messages'][-1]['content'])
		self.assertIn('known_zh', payload['rows'][0])
		response = {'results': [{'row_id': 1, 'verdict': 'wrong_zh', 'zh': '设备互联',
								 'confidence': 0.9, 'reason': 'de'}]}
		decisions = LogProofreader.parse_batch_decisions(response, batches[0]['rows'], known, 'module')
		self.assertEqual('wrong_zh', decisions[0]['verdict'])
		self.assertEqual('设备互联', decisions[0]['suggested_zh'])
		# 不在 known_zh 里的建议被丢弃
		bad = {'results': [{'row_id': 1, 'verdict': 'wrong_zh', 'zh': '不存在', 'confidence': 0.9}]}
		self.assertEqual([], LogProofreader.parse_batch_decisions(bad, batches[0]['rows'], known, 'module'))

	def test_log_batch_free_zh(self):
		selected, known, batches = LogProofreader.prepare_batches(
			self.rows, self.owners, batch_size=1, min_langs=2, types=('log',))
		payload = json.loads(batches[0]['messages'][-1]['content'])
		self.assertNotIn('known_zh', payload['rows'][0])
		response = {'results': [{'row_id': 2, 'verdict': 'wrong_zh', 'zh': '更多内容官网',
								 'confidence': 0.8, 'reason': 'de 是设置指引'}]}
		decisions = LogProofreader.parse_batch_decisions(response, batches[0]['rows'], known, 'log')
		self.assertEqual('更多内容官网', decisions[0]['suggested_zh'])
		self.assertTrue(decisions[0]['free_zh'])

	def test_batch_review_calls_on_decisions_per_batch(self):
		seen = []

		class Client:
			def json_chat(self, messages, **kwargs):
				payload = json.loads(messages[-1]['content'])
				return {'results': [{'row_id': item['row_id'], 'verdict': 'ok',
									 'zh': item['current_zh'], 'confidence': 0.9,
									 'reason': ''} for item in payload['rows']]}

		result = LogProofreader.batch_review(
			self.rows, self.owners, Client(), batch_size=2, min_langs=2,
			on_decisions=lambda parsed: seen.extend(parsed))
		self.assertEqual(len(result['decisions']), len(seen))
		self.assertEqual(result['decisions'][0]['row_id'], seen[0]['row_id'])

	def test_batch_review_with_fake_client(self):
		class Client:
			def __init__(self):
				self.calls = 0
			def json_chat(self, messages, **kwargs):
				self.calls += 1
				payload = json.loads(messages[-1]['content'])
				results = []
				for item in payload['rows']:
					if item['row_id'] == 1:
						results.append({'row_id': 1, 'verdict': 'wrong_zh', 'zh': '设备互联',
										'confidence': 0.9, 'reason': 'de'})
					else:
						results.append({'row_id': item['row_id'], 'verdict': 'ok',
										'zh': item['current_zh'], 'confidence': 0.9, 'reason': ''})
				return {'results': results}

		client = Client()
		with tempfile.TemporaryDirectory() as tmp:
			cache = str(Path(tmp) / 'batch_cache.json')
			result = LogProofreader.batch_review(self.rows, self.owners, client,
												 batch_size=2, min_langs=2, cache_path=cache)
			self.assertEqual(2, result['calls'])
			self.assertEqual(1, result['by_verdict'].get('wrong_zh'))
			self.assertEqual(3, len(result['decisions']))
			again = LogProofreader.batch_review(self.rows, self.owners, client,
												batch_size=2, min_langs=2, cache_path=cache)
			self.assertEqual(0, again['calls'])


class InspectTest(unittest.TestCase):
	def setUp(self):
		self.rows = {
			20: row(20, '其他', {'logs_zh': '其他', 'logs_de': 'Interkonnektivität',
								'logs_ug': 'ئۈسكۈنە ئالاقىسى', 'logs_bo': 'x'}),
			21: row(21, '更多内容', {'logs_zh': '更多内容', 'logs_en': 'More',
								 'logs_de': 'Gehe zu Einstellungen'}, log_type='log'),
			30: row(30, '设备互联', {'logs_zh': '设备互联', 'logs_en': 'Interconnectivity'}),
		}
		self.owners = {('roms', 1): [[30, [], 7], [20, [], ZH]]}

	def test_module_inspect_with_ai(self):
		class Client:
			def json_chat(self, messages, **kwargs):
				payload = json.loads(messages[-1]['content'])
				return {'results': [{
					'row_id': payload['rows'][0]['row_id'],
					'verdict': 'wrong_zh', 'zh': '设备互联',
					'confidence': 0.95, 'reason': 'de'}]}

		result = LogProofreader.inspect([20], self.rows, self.owners, client=Client())
		item = result['rows'][0]
		self.assertEqual('wrong_zh', item['decision']['verdict'])
		self.assertEqual('设备互联', item['decision']['suggested_zh'])
		self.assertIn('设备互联', item['known_zh'])

	def test_log_inspect_mixed(self):
		class Client:
			def json_chat(self, messages, **kwargs):
				return {'results': [{
					'row_id': 21, 'verdict': 'mixed_translations', 'zh': '更多内容',
					'confidence': 0.9, 'reason': 'de 指向别的模块'}]}

		result = LogProofreader.inspect([21], self.rows, self.owners, client=Client())
		item = result['rows'][0]
		self.assertEqual('mixed_translations', item['decision']['verdict'])
		self.assertEqual('更多内容', item['decision']['suggested_zh'])

	def test_inspect_skips_proofed_unless_force(self):
		self.rows[20]['proofed'] = True
		result = LogProofreader.inspect([20], self.rows, self.owners)
		item = result['rows'][0]
		self.assertEqual('proofed', item['skipped'])
		self.assertIsNone(item['decision'])

		class Client:
			def json_chat(self, messages, **kwargs):
				return {'results': [{'row_id': 20, 'verdict': 'wrong_zh',
									 'zh': '设备互联', 'confidence': 0.9, 'reason': ''}]}

		forced = LogProofreader.inspect([20], self.rows, self.owners,
										client=Client(), force=True)
		self.assertEqual('wrong_zh', forced['rows'][0]['decision']['verdict'])

	def test_inspect_without_ai(self):
		result = LogProofreader.inspect([20, 999], self.rows, self.owners)
		self.assertIsNone(result['rows'][0]['decision'])
		self.assertEqual('not_found', result['rows'][1]['error'])


class PlanTest(unittest.TestCase):
	def setUp(self):
		full_texts = {column: 'text' for column in LogStore.LANG_COLUMNS}
		full_texts['logs_zh'] = '其他'
		full_texts['logs_en'] = 'Other'
		self.rows = {
			20: row(20, '其他', {'logs_zh': '其他', 'logs_de': 'Interkonnektivität',
								'logs_ug': 'ئۈسكۈنە ئالاقىسى', 'logs_bo': 'x'}),
			30: row(30, '其他', full_texts),
			40: row(40, '系统', {'logs_zh': '系统', 'logs_en': 'System'}),
		}
		self.owners = {('roms', 1): [[20, [], ZH], [20, [], ZH | EN], [30, [], ZH]]}
		self.low = {'row_id': 20, 'current_zh': '其他', 'suggested_zh': '设备互联',
					'confidence': 0.5, 'reason': ''}
		self.clear = {'row_id': 20, 'current_zh': '其他', 'suggested_zh': '设备互联',
					  'confidence': 0.9, 'reason': ''}
		self.rename = {'row_id': 30, 'current_zh': '其他', 'suggested_zh': '设备互联',
					   'confidence': 0.9, 'reason': ''}

	def test_low_confidence_skipped(self):
		plan = LogProofreader.plan([self.low], self.rows, self.owners, allow_clear=True)
		self.assertEqual([], plan['actions'])
		self.assertEqual('low_confidence', plan['skipped'][0]['reason'])

	def test_extra_row_needs_allow_clear(self):
		plan = LogProofreader.plan([self.clear], self.rows, self.owners, allow_clear=False)
		self.assertEqual([], plan['actions'])
		self.assertEqual('extra_module_needs_clear', plan['skipped'][0]['reason'])
		plan = LogProofreader.plan([self.clear], self.rows, self.owners, allow_clear=True)
		self.assertEqual('clear', plan['actions'][0]['action'])
		self.assertEqual('Interkonnektivität', plan['actions'][0]['content'])
		self.assertEqual(2, plan['actions'][0]['mask_updates'])
		# 两个位置的掩码都去掉中文位；带英文的位置保留英文
		values = {value for _, _, value in plan['mask_updates']}
		masks = set()
		for value in values:
			for item in json.loads(value):
				masks.add(item[2])
		self.assertIn(0, masks)
		self.assertIn(EN, masks)

	def test_full_row_renamed(self):
		plan = LogProofreader.plan([self.rename], self.rows, self.owners)
		self.assertEqual('rename', plan['actions'][0]['action'])
		self.assertEqual('设备互联', plan['actions'][0]['content'])
		self.assertEqual([], plan['mask_updates'])

	def test_ambiguous_row_needs_manual(self):
		wide_texts = {column: 'text' for column in LogStore.LANG_COLUMNS}
		wide_texts.pop('logs_en')
		wide_texts['logs_zh'] = '其他'
		rows = dict(self.rows)
		rows[31] = row(31, '其他', wide_texts)   # 16 种语言但没有英文
		decision = {'row_id': 31, 'current_zh': '其他', 'suggested_zh': '设备互联',
					'confidence': 0.9, 'reason': ''}
		plan = LogProofreader.plan([decision], rows, self.owners, allow_clear=True)
		self.assertEqual([], plan['actions'])
		self.assertEqual('ambiguous_row_needs_manual', plan['skipped'][0]['reason'])

	def test_log_decisions_not_applied(self):
		log_row = row(70, '更多内容', {'logs_zh': '更多内容', 'logs_en': 'More'}, log_type='log')
		rows = dict(self.rows)
		rows[70] = log_row
		decision = {'row_id': 70, 'verdict': 'wrong_zh', 'current_zh': '更多内容',
					'suggested_zh': '更多内容官网', 'confidence': 0.9, 'reason': ''}
		plan = LogProofreader.plan([decision], rows, self.owners)
		self.assertEqual([], plan['actions'])
		self.assertEqual('log_entry_needs_manual', plan['skipped'][0]['reason'])

	def test_mixed_translations_not_changed(self):
		decision = {'row_id': 30, 'verdict': 'mixed_translations', 'current_zh': '其他',
					'suggested_zh': '其他', 'confidence': 0.9, 'reason': 'mixed'}
		plan = LogProofreader.plan([decision], self.rows, self.owners, allow_clear=True)
		self.assertEqual([], plan['actions'])
		self.assertEqual(1, plan['stats']['mixed_translations'])

	def test_null_suggestion_clears_narrow_row(self):
		decision = {'row_id': 20, 'current_zh': '其他', 'suggested_zh': None,
					'confidence': 0.9, 'reason': 'extra module'}
		plan = LogProofreader.plan([decision], self.rows, self.owners, allow_clear=True)
		self.assertEqual('clear', plan['actions'][0]['action'])

	def test_no_change_skipped(self):
		decision = dict(self.rename, suggested_zh='其他')
		plan = LogProofreader.plan([decision], self.rows, self.owners)
		self.assertEqual([], plan['actions'])
		self.assertEqual('no_change', plan['skipped'][0]['reason'])

	def test_apply_dry_run(self):
		plan = LogProofreader.plan([self.rename], self.rows, self.owners)
		result = LogProofreader.apply(plan, apply=False)
		self.assertFalse(result['applied'])


if __name__ == '__main__':
	unittest.main(verbosity=2)
