"""test_logs_clean.py - 开头空白/标点整理测试（不连数据库）"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.logs_clean import LogPrefixCleaner, clean_prefix, is_bad_start


def row(row_id, content, texts, log_type='log'):
	return {'id': row_id, 'type': log_type, 'content': content,
			'texts': dict(texts), 'proofed': False, 'complete': False,
			'lang_issues': {}}


class CleanTextTest(unittest.TestCase):
	def test_bullet_and_space(self):
		self.assertEqual(('全新', True), clean_prefix('· 全新'))

	def test_star_is_excluded(self):
		self.assertEqual(('* note', False), clean_prefix('* note'))
		self.assertEqual(('* note', True), clean_prefix('  * note'))

	def test_bracket_prefix(self):
		self.assertEqual(('焦点】', True), clean_prefix('【焦点】'))

	def test_empty(self):
		self.assertEqual(('', True), clean_prefix('  '))

	def test_bad_start(self):
		self.assertTrue(is_bad_start('· x'))
		self.assertTrue(is_bad_start(' x'))
		self.assertFalse(is_bad_start('* x'))
		self.assertFalse(is_bad_start('正常'))


class PlanTest(unittest.TestCase):
	def setUp(self):
		self.rows = {
			1: row(1, '· 全新', {'logs_zh': '· 全新', 'logs_zh_tw': '· 全新', 'logs_en': '· New'}),
			2: row(2, '* 备注', {'logs_zh': '* 备注', 'logs_en': '* Note'}),
			3: row(3, '【】', {'logs_zh': '【】'}),
		}

	def test_plan_skips_star_and_empty(self):
		plan = LogPrefixCleaner.plan(self.rows)
		self.assertEqual([1], [action['row_id'] for action in plan['actions']])
		self.assertEqual('全新', plan['actions'][0]['changes']['logs_zh'])
		self.assertEqual('New', plan['actions'][0]['changes']['logs_en'])
		self.assertEqual(1, plan['stats']['skipped'])

	def test_apply_dry(self):
		plan = LogPrefixCleaner.plan(self.rows)
		result = LogPrefixCleaner.apply(plan, apply=False)
		self.assertFalse(result['applied'])


if __name__ == '__main__':
	unittest.main(verbosity=2)
