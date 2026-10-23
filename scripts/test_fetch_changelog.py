"""test_fetch_changelog.py - 日志校验辅助函数的单元测试（不连数据库、不请求接口）"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import fetch_changelog as fc


class IsSameLogTest(unittest.TestCase):
	def test_exact_match(self):
		self.assertTrue(fc.is_same_log('{"System": ["x"]}', {'System': ['x']}))

	def test_whitespace_is_ignored(self):
		self.assertTrue(fc.is_same_log('{" System ": [" x "]}', {'System': ['x']}))

	def test_duplicate_entries_are_ignored(self):
		self.assertTrue(fc.is_same_log('{"System": ["x", "x"]}', {'System': ['x']}))

	def test_module_order_is_ignored(self):
		self.assertTrue(fc.is_same_log('{"A": ["1"], "B": ["2"]}',
									   {'B': ['2'], 'A': ['1']}))

	def test_different_text_is_not_same(self):
		self.assertFalse(fc.is_same_log('{"System": ["x"]}', {'System': ['y']}))

	def test_entry_order_is_ignored(self):
		self.assertTrue(fc.is_same_log('{"System": ["x", "y"]}', {'System': ['y', 'x']}))

	def test_json_like_text_is_not_decoded(self):
		self.assertFalse(fc.is_same_log('{"A": ["{\\"b\\": 1}"]}', {'A': [{'b': 1}]}))

	def test_empty_is_not_same(self):
		self.assertFalse(fc.is_same_log('', {'System': ['x']}))
		self.assertFalse(fc.is_same_log('{"System": ["x"]}', None))


class ParseOfficialLogTest(unittest.TestCase):
	def test_parse(self):
		self.assertEqual({'A': ['1']}, fc.parse_official_log('{"A": ["1"]}'))

	def test_empty_inputs(self):
		self.assertIsNone(fc.parse_official_log(None))
		self.assertIsNone(fc.parse_official_log(''))
		self.assertIsNone(fc.parse_official_log('{}'))
		self.assertIsNone(fc.parse_official_log('not json'))
		self.assertIsNone(fc.parse_official_log('["A"]'))


class FilterIdsTest(unittest.TestCase):
	def test_order_and_bounds(self):
		ids = [30, 20, 10]
		self.assertEqual([30, 20], fc._filter_ids(ids, min_id=15))
		self.assertEqual([20, 10], fc._filter_ids(ids, max_id=25))
		self.assertEqual([30, 20], fc._filter_ids(ids, limit=2))
		self.assertEqual([30], fc._filter_ids(ids, min_id=15, limit=1))

	def test_filter_note_only_when_filtered(self):
		self.assertEqual('', fc._filter_note(5, 5, 0, 0, 0))
		self.assertIn('--min-id 10', fc._filter_note(5, 2, 10, 0, 0))
		self.assertIn('--verify-limit 3',
					  fc._filter_note(5, 3, 0, 0, 3, limit_label='--verify-limit'))


if __name__ == '__main__':
	unittest.main(verbosity=2)
