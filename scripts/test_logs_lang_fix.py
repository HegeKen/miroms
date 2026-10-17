"""
test_logs_lang_fix.py - 按 lang_issues 修正语言列的单元测试

不连数据库。
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.logs_lang_fix import LogLangFixer
from miroms.logs_store import LogStore


def row(row_id, texts, issues, log_type='module'):
	return {'id': row_id, 'type': log_type, 'content': texts.get('logs_zh') or '',
			'proofed': False, 'lang_issues': dict(issues), 'texts': dict(texts)}


def bit(column):
	return 1 << LogStore.LANG_INDEX[column]


class DetectTest(unittest.TestCase):
	def test_detected_mapping(self):
		self.assertEqual('logs_de', LogLangFixer.detect_column('德文'))
		self.assertEqual('logs_de', LogLangFixer.detect_column('German'))
		self.assertEqual('logs_en', LogLangFixer.detect_column('与 logs_en 相同（英文回落）'))
		self.assertIsNone(LogLangFixer.detect_column(''))


class PlanTest(unittest.TestCase):
	def setUp(self):
		self.rows = {
			1: row(1, {'logs_zh': '其他', 'logs_en': 'Other', 'logs_de': 'Other',
					   'logs_ja': 'Bonjour'},
				   {'logs_de': {'detected': '英文', 'confidence': 0.9},
					'logs_zh': {'detected': '英文', 'confidence': 0.9}}),
			2: row(2, {'logs_zh': '其他', 'logs_en': 'Other'},
				   {'logs_ko': {'detected': '英文', 'confidence': 0.9}}),
		}
		self.owners = {('roms', 1): [[1, [], bit('logs_zh') | bit('logs_en') | bit('logs_de')]]}

	def test_clear_skips_core_by_default(self):
		plan = LogLangFixer.plan(self.rows, self.owners, ids=[1], mode='clear')
		action = plan['actions'][0]
		self.assertEqual({'logs_de': None}, action['set_columns'])
		self.assertIn('logs_zh', action['remaining_issues'])
		self.assertEqual(1, plan['stats']['cleared'])
		self.assertIn('core_column_needs_manual',
					  [item['reason'] for item in plan['skipped']])

	def test_allow_core(self):
		plan = LogLangFixer.plan(self.rows, self.owners, ids=[1], mode='clear', allow_core=True)
		self.assertIn('logs_zh', plan['actions'][0]['set_columns'])

	def test_stale_issue_cleanup(self):
		plan = LogLangFixer.plan(self.rows, self.owners, ids=[2], mode='clear')
		action = plan['actions'][0]
		self.assertEqual({}, action['set_columns'])
		self.assertEqual({}, action['remaining_issues'])

	def test_move_to_empty_language(self):
		rows = dict(self.rows)
		rows[3] = row(3, {'logs_zh': '设置', 'logs_en': 'Settings', 'logs_de': 'Bonjour'},
					  {'logs_de': {'detected': '法文', 'confidence': 0.9}})
		plan = LogLangFixer.plan(rows, self.owners, ids=[3], mode='move')
		action = plan['actions'][0]
		self.assertIsNone(action['set_columns']['logs_de'])
		self.assertEqual('Bonjour', action['set_columns']['logs_fr'])
		self.assertEqual('move', action['details'][0]['action'])

	def test_clean_masks(self):
		plan = LogLangFixer.plan(self.rows, self.owners, ids=[1], mode='clear',
								 clean_masks=True)
		self.assertEqual(1, len(plan['mask_updates']))
		self.assertEqual(1, plan['stats']['mask_updates'])

	def test_apply_dry_run(self):
		plan = LogLangFixer.plan(self.rows, self.owners, ids=[1], mode='clear')
		result = LogLangFixer.apply(plan, apply=False)
		self.assertFalse(result['applied'])

	def test_correct_replaces_with_translation(self):
		rows = dict(self.rows)
		rows[4] = row(4, {'logs_zh': '收音机', 'logs_en': 'Radio', 'logs_de': 'Radio'},
					  {'logs_de': {'detected': '英文', 'confidence': 0.95,
								   'correct': 'Radio-App'}})
		plan = LogLangFixer.plan(rows, self.owners, ids=[4])
		action = plan['actions'][0]
		self.assertEqual('Radio-App', action['set_columns']['logs_de'])
		self.assertEqual('correct', action['details'][0]['action'])
		self.assertEqual(1, plan['stats']['corrected'])

	def test_low_confidence_skips_without_clearing(self):
		rows = dict(self.rows)
		rows[4] = row(4, {'logs_zh': '收音机', 'logs_en': 'Radio', 'logs_de': 'Radio'},
					  {'logs_de': {'detected': '英文', 'confidence': 0.5,
								   'correct': 'Radio-App'}})
		plan = LogLangFixer.plan(rows, self.owners, ids=[4])
		self.assertEqual([], plan['actions'])
		self.assertEqual('low_confidence', plan['skipped'][0]['reason'])


class TranslateModeTest(unittest.TestCase):
	def make_row(self):
		return {4: row(4, {'logs_zh': '其他', 'logs_en': 'Other', 'logs_de': 'Other'},
					   {'logs_de': {'detected': '英文', 'confidence': 0.9}})}

	class Client:
		def json_chat(self, messages):
			return {'translations': {'logs_de': {'text': 'Sonstiges', 'confidence': 0.95}}}

	def test_translate_fills_and_clears_issue(self):
		plan = LogLangFixer.plan(self.make_row(), ids=[4], mode='translate', client=self.Client())
		action = plan['actions'][0]
		self.assertEqual('Sonstiges', action['set_columns']['logs_de'])
		self.assertEqual({}, action['remaining_issues'])
		self.assertEqual('translate', action['details'][0]['action'])
		self.assertEqual(1, plan['stats']['translated'])

	def test_on_action_called(self):
		seen = []
		LogLangFixer.plan(self.make_row(), ids=[4], mode='translate',
						  client=self.Client(), on_action=seen.append)
		self.assertEqual(1, len(seen))
		self.assertEqual('Sonstiges', seen[0]['set_columns']['logs_de'])

	def test_no_client_keeps_issue(self):
		plan = LogLangFixer.plan(self.make_row(), ids=[4], mode='translate')
		self.assertEqual([], plan['actions'])
		self.assertIn('ai_required', [item['reason'] for item in plan['skipped']])

	def test_low_confidence_keeps_issue(self):
		class LowClient:
			def json_chat(self, messages):
				return {'translations': {'logs_de': {'text': 'Sonstiges', 'confidence': 0.3}}}
		plan = LogLangFixer.plan(self.make_row(), ids=[4], mode='translate', client=LowClient())
		self.assertEqual([], plan['actions'])
		self.assertIn('translation_failed', [item['reason'] for item in plan['skipped']])


if __name__ == '__main__':
	unittest.main(verbosity=2)
