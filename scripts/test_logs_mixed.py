"""test_logs_mixed.py - mixed_translations 规划器测试（不连数据库）"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.logs_mixed import MixedTranslationFixer
from miroms.logs_store import LogStore


def row(row_id, content, texts, log_type='module'):
	return {'id': row_id, 'type': log_type, 'content': content,
			'texts': dict(texts), 'proofed': False, 'complete': False, 'lang_issues': {}}


class ValidateTest(unittest.TestCase):
	def setUp(self):
		self.rows = {1: row(1, '设置', {'logs_zh': '设置', 'logs_en': 'Settings'})}

	def test_valid(self):
		decision = {'row_id': 1, 'type': 'module', 'current_zh': '设置',
					'verdict': 'mixed_translations'}
		valid, stale = MixedTranslationFixer.validate_decisions([decision], self.rows)
		self.assertEqual(1, len(valid))
		self.assertEqual([], stale)

	def test_stale_row_id(self):
		decision = {'row_id': 1, 'type': 'log', 'current_zh': '别的',
					'verdict': 'mixed_translations'}
		valid, stale = MixedTranslationFixer.validate_decisions([decision], self.rows)
		self.assertEqual([], valid)
		self.assertEqual(1, len(stale))


class CandidateTest(unittest.TestCase):
	def test_candidates(self):
		rows = {
			1: row(1, '设置', {'logs_zh': '设置', 'logs_en': 'Settings'}),
			2: row(2, '设置', {'logs_zh': '设置', 'logs_en': 'Settings'}),
			3: row(3, '相机', {'logs_zh': '相机', 'logs_en': 'Camera'}),
		}
		result = MixedTranslationFixer.candidates(rows[1], rows, 'Settings', limit=3)
		self.assertEqual(2, result[0][0])
		self.assertGreaterEqual(result[0][1], 0.9)


class RoutingTest(unittest.TestCase):
	def test_max_intersection(self):
		clusters = [{'langs': ['logs_ja', 'logs_ko']}, {'langs': ['logs_en', 'logs_de']}]
		mask = (1 << LogStore.LANG_INDEX['logs_en']) | (1 << LogStore.LANG_INDEX['logs_de'])
		self.assertEqual(1, MixedTranslationFixer._route_cluster(clusters, mask))

	def test_tie_is_ambiguous(self):
		clusters = [{'langs': ['logs_ja']}, {'langs': ['logs_en']}]
		mask = (1 << LogStore.LANG_INDEX['logs_ja']) | (1 << LogStore.LANG_INDEX['logs_en'])
		self.assertIsNone(MixedTranslationFixer._route_cluster(clusters, mask))


class ApplyDryTest(unittest.TestCase):
	def test_apply_merges_dry(self):
		plan = {'actions': [{'action': 'merge', 'row_id': 1, 'target_id': 2}]}
		self.assertFalse(MixedTranslationFixer.apply_merges(plan, {}, apply=False)['applied'])

	def test_apply_splits_dry(self):
		plan = {'actions': [{'action': 'split', 'row_id': 1, 'ambiguous': []}]}
		self.assertFalse(MixedTranslationFixer.apply_splits(plan, {}, {}, None, apply=False)['applied'])


if __name__ == '__main__':
	unittest.main(verbosity=2)
