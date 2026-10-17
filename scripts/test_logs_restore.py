"""test_logs_restore.py - 旧转义还原测试（不连数据库）"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.changelog import ChangelogManager
from miroms.logs_restore import LogEscapeRestorer, restore_text


class RestoreTextTest(unittest.TestCase):
	def test_apostrophe(self):
		self.assertEqual("won't", restore_text('won^t'))
		self.assertEqual("l'écran", restore_text('l^écran'))
		self.assertEqual("2025'te", restore_text('2025^te'))

	def test_paired_quotes(self):
		self.assertEqual('"Service & feedback"', restore_text('^Service & feedback^'))
		self.assertEqual('"Recently deleted"', restore_text('^^Recently deleted^^'))

	def test_percent_and_backslash(self):
		self.assertEqual('5%', restore_text('5$$'))
		self.assertEqual("d'écran", restore_text('d\\^écran'))

	def test_no_caret(self):
		self.assertNotIn('^', restore_text('Fix: ^"Lever pour activer"^ ne marche pas'))
		self.assertNotIn('^', restore_text('Patch^i Kasım 2025^te'))


class ChangelogCleanTest(unittest.TestCase):
	def test_quotes_and_percent_are_preserved(self):
		raw = 'won\'t 5% "quoted"\tend'
		cleaned = ChangelogManager._clean_log(raw)
		self.assertIn("won't", cleaned)
		self.assertIn('5%', cleaned)
		self.assertIn('"quoted"', cleaned)
		self.assertNotIn('\t', cleaned)
		self.assertNotIn('^', cleaned)
		self.assertNotIn('$$', cleaned)


class PlanTest(unittest.TestCase):
	def test_plan(self):
		rows = {
			1: {'id': 1, 'type': 'log', 'content': 'won^t',
				'texts': {'logs_zh': 'won^t', 'logs_en': 'won^t'}, 'proofed': True},
		}
		plan = LogEscapeRestorer.plan(rows)
		self.assertEqual(1, plan['stats']['rows'])
		self.assertEqual("won't", plan['actions'][0]['changes']['logs_en'])

	def test_apply_dry(self):
		rows = {1: {'id': 1, 'type': 'log', 'content': 'won^t',
					'texts': {'logs_zh': 'won^t'}}}
		plan = LogEscapeRestorer.plan(rows)
		result = LogEscapeRestorer.apply(plan, apply=False)
		self.assertFalse(result['applied'])


if __name__ == '__main__':
	unittest.main(verbosity=2)
