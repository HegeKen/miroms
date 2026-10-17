"""
test_logs_fill.py - proofed 行缺失语言回填的单元测试（不连数据库）
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.logs_fill import LogFiller
from miroms.logs_store import LogStore


def row(row_id, content, texts, log_type='module', proofed=True, issues=None):
	return {'id': row_id, 'type': log_type, 'content': content, 'proofed': proofed,
			'lang_issues': issues or {}, 'texts': dict(texts)}


def bit(column):
	return 1 << LogStore.LANG_INDEX[column]


class MissingTest(unittest.TestCase):
	def setUp(self):
		self.rows = {
			1: row(1, '相册', {'logs_zh': '相册', 'logs_en': 'Gallery'}),
			2: row(2, '修复若干问题', {'logs_zh': '修复若干问题', 'logs_en': 'Fixed issues',
									 'logs_fr': 'Problèmes corrigés'}, log_type='log'),
			3: row(3, '未校对', {'logs_zh': '未校对'}, proofed=False),
		}
		self.owners = {('roms', 10): [[1, [99], bit('logs_zh') | bit('logs_en') | bit('logs_de')]]}

	def test_all_languages(self):
		items = LogFiller.missing_rows(self.rows, types=('module', 'log'))
		self.assertEqual([1, 2], [item['row_id'] for item in items])
		self.assertIn('logs_de', items[0]['missing'])
		self.assertNotIn('logs_zh', items[0]['missing'])

	def test_expected_owners(self):
		items = LogFiller.missing_rows(self.rows, self.owners, expected='owners',
									   types=('module', 'log'))
		self.assertEqual([1], [item['row_id'] for item in items])
		self.assertEqual(['logs_de'], items[0]['missing'])

	def test_include_unproofed_and_limit(self):
		items = LogFiller.missing_rows(self.rows, types=('module', 'log'),
									   include_unproofed=True, limit=2)
		self.assertEqual(2, len(items))

	def test_offset_and_limit(self):
		items = LogFiller.missing_rows(self.rows, types=('module', 'log'),
									   offset=1, limit=1)
		self.assertEqual([2], [item['row_id'] for item in items])

	def test_estimate(self):
		items = LogFiller.missing_rows(self.rows, types=('module', 'log'))
		estimate = LogFiller.estimate(items)
		self.assertEqual(2, estimate['calls'])
		self.assertGreaterEqual(estimate['columns'], 2)


class ParseTest(unittest.TestCase):
	def setUp(self):
		self.item = {'row_id': 1, 'type': 'module', 'zh': '相册', 'en': 'Gallery',
					 'missing': ['logs_de', 'logs_fr', 'logs_ug']}

	def test_parse_valid_and_skip_bad(self):
		payload = {'translations': {
			'logs_de': {'text': 'Galerie', 'confidence': 0.95},
			'logs_fr': {'text': 'Gallery', 'confidence': 0.95},        # 等同英文，跳过
			'logs_ug': {'text': 'Galerie', 'confidence': 0.4},          # 置信度不足
		}}
		result = LogFiller.parse_translations(payload, self.item)
		self.assertEqual({'logs_de'}, set(result))
		self.assertEqual('Galerie', result['logs_de']['text'])

	def test_prompt_targets(self):
		messages = LogFiller.build_prompt(self.item)
		self.assertIn('logs_de', messages[-1]['content'])
		self.assertIn('相册', messages[-1]['content'])

	def test_apply_dry_run(self):
		results = [{'row_id': 1, 'translations': {'logs_de': {'text': 'Galerie', 'confidence': 0.95}}}]
		output = LogFiller.apply(results, {1: self.rows_row()}, apply=False)
		self.assertFalse(output['applied'])
		self.assertEqual(1, output['columns'])

	def test_complete_when_all_languages_and_kept_proofed(self):
		texts = {column: f'x-{column}' for column in LogStore.LANG_COLUMNS}
		texts['logs_zh'] = '相册'
		texts.pop('logs_de')
		row = {'id': 1, 'type': 'module', 'content': '相册', 'proofed': True,
			   'complete': False, 'lang_issues': {}, 'texts': texts}
		results = [{'row_id': 1, 'translations': {'logs_de': {'text': 'Galerie', 'confidence': 0.95}}}]
		output = LogFiller.apply(results, {1: row}, apply=False, keep_proofed=True)
		self.assertEqual(1, output['actions'][0]['complete'])
		self.assertEqual(1, output['actions'][0]['proofed'])

	def rows_row(self):
		return row(1, '相册', {'logs_zh': '相册', 'logs_en': 'Gallery'})


if __name__ == '__main__':
	unittest.main(verbosity=2)
