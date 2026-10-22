"""
test_logs_maintenance.py - 日志维护纯逻辑的单元测试（不连数据库、不写库）

覆盖：LogText 文本判定、LogMaintenance 的去重计划 / 引用重排 / content 体检 /
语言掩码体检与补齐 / 孤儿行识别。这些函数都接受传入的 rows / owners，
因此可以直接用构造数据验证；涉及数据库的部分由 scripts/maintain_logs.py 的 dry-run 验证。

运行：
    python3 data/scripts/test_logs_maintenance.py
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.logs_maintenance import LogMaintenance
from miroms.logs_store import LogStore
from miroms.logs_text import LogText


def row(row_id, log_type='log', content='', texts=None):
	return {'id': row_id, 'type': log_type, 'content': content, 'texts': dict(texts or {})}


def bit(column):
	return 1 << LogStore.LANG_INDEX[column]


class LogTextTest(unittest.TestCase):
	def test_chinese_and_kana(self):
		self.assertTrue(LogText.is_chinese('修复 部分场景下的问题'))
		self.assertTrue(LogText.is_chinese('設定'))          # 繁体也算「中文」，只是不是简体
		self.assertFalse(LogText.is_chinese('設定する'))     # 含假名 → 日文
		self.assertFalse(LogText.is_chinese('Settings'))
		self.assertFalse(LogText.is_chinese(''))
		self.assertTrue(LogText.has_kana('その他'))
		self.assertFalse(LogText.has_kana('其他'))

	def test_looks_simplified(self):
		self.assertTrue(LogText.looks_simplified('优化系统'))
		self.assertFalse(LogText.looks_simplified('優化系統'))
		self.assertTrue(LogText.looks_simplified('设置'))     # 无繁体特征字，按可用中文处理
		# 与其它语言列完全相同 → 就是那门语言，不能当简体中文
		self.assertFalse(LogText.looks_simplified('设定', {'logs_ja': '设定'}))
		self.assertFalse(LogText.looks_simplified('Fix bug', {'logs_en': 'Fix bug'}))

	def test_to_simplified(self):
		converter = LogText.converter()
		if converter is None:
			self.skipTest('未安装 zhconv / opencc')
		self.assertEqual(LogText.to_simplified('設定'), '设定')
		self.assertIsNone(LogText.to_simplified('設定する'))


class DuplicatePlanTest(unittest.TestCase):
	def test_merges_compatible_rows(self):
		rows = {
			1: row(1, content='修复问题', texts={'logs_zh': '修复问题', 'logs_en': 'Fix issue'}),
			2: row(2, content='修复问题', texts={'logs_zh': '修复问题', 'logs_ja': '修正'}),
		}
		mapping, merged = LogMaintenance.duplicate_plan(rows)
		self.assertEqual({1: 1, 2: 1}, mapping)
		self.assertEqual({1}, set(merged))
		self.assertEqual({'logs_zh': '修复问题', 'logs_en': 'Fix issue', 'logs_ja': '修正'},
						 merged[1]['texts'])
		self.assertEqual('修复问题', merged[1]['content'])

	def test_conflicting_translation_stays_separate(self):
		rows = {
			1: row(1, content='修复问题', texts={'logs_zh': '修复问题', 'logs_en': 'Fix issue'}),
			2: row(2, content='修复问题', texts={'logs_zh': '修复问题', 'logs_ja': '修正'}),
			3: row(3, content='修复问题', texts={'logs_zh': '修复问题', 'logs_en': 'Fix problem'}),
		}
		mapping, merged = LogMaintenance.duplicate_plan(rows)
		# 3 与代表行 1 的英文冲突；但 2 没有英文，可以与 1 合并后再与 3 对比留下 3
		self.assertEqual(1, mapping[1])
		self.assertEqual(1, mapping[2])
		self.assertEqual(3, mapping[3])
		self.assertEqual({1}, set(merged))

	def test_representative_prefers_more_languages(self):
		rows = {
			1: row(1, content='设置', texts={'logs_zh': '设置'}),
			2: row(2, content='设置', texts={'logs_zh': '设置', 'logs_en': 'Settings'}),
		}
		mapping, merged = LogMaintenance.duplicate_plan(rows)
		self.assertEqual(2, mapping[1])
		self.assertEqual(2, mapping[2])
		self.assertIn('logs_en', merged[2]['texts'])

	def test_no_duplicates(self):
		rows = {
			1: row(1, content='设置', texts={'logs_zh': '设置'}),
			2: row(2, content='音量', texts={'logs_zh': '音量'}),
		}
		mapping, merged = LogMaintenance.duplicate_plan(rows)
		self.assertEqual({1: 1, 2: 2}, mapping)
		self.assertEqual({}, merged)


class RemapTest(unittest.TestCase):
	def test_remap_structure(self):
		value = '[[5, [6, 7], 3], [9, [], 2]]'
		self.assertEqual(
			'[[2, [4, 7], 3], [9, [], 2]]',
			LogMaintenance.remap_structure(value, {5: 2, 6: 4}))
		self.assertIsNone(LogMaintenance.remap_structure(value, {1: 2}))
		self.assertIsNone(LogMaintenance.remap_structure(None, {1: 2}))
		self.assertIsNone(LogMaintenance.remap_structure('not json', {1: 2}))

	def test_keep_extra_elements(self):
		# 多于 3 个元素的旧数据不丢字段
		self.assertEqual('[[2, [6], 1, "x"]]',
						 LogMaintenance.remap_structure('[[1, [6], 1, "x"]]', {1: 2}))

	def test_iter_refs_skips_bad_items(self):
		refs = [[1, [2, 3], 5], ['x'], [None, [1]], [4, [5]]]
		self.assertEqual([(1, [2, 3], 5), (4, [5], 0)],
						 list(LogMaintenance.iter_refs(refs)))


class ContentAuditTest(unittest.TestCase):
	def setUp(self):
		self.rows = {
			1: row(1, content='修复问题', texts={'logs_zh': '修复问题'}),
			2: row(2, content='優化系統', texts={'logs_zh': '优化系统'}),
			3: row(3, content='关闭广告', texts={'logs_en': 'Disable ads'}),
			4: row(4, content='Fix bug', texts={'logs_en': 'Fix bug'}),
			5: row(5, content=''),
		}

	def test_reasons(self):
		issues = {issue['id']: issue['reason'] for issue in LogMaintenance.content_issues(self.rows)}
		self.assertEqual({2: 'content_not_zh', 3: 'zh_missing',
						  4: 'no_zh', 5: 'empty'}, issues)

	def test_repair_plan(self):
		result = LogMaintenance.repair_content(self.rows, apply=False)
		self.assertEqual(1, result['content_updates'])
		self.assertEqual(1, result['zh_updates'])
		self.assertEqual(2, result['unresolved'])
		self.assertEqual(4, result['candidates'])
		self.assertFalse(result['applied'])


class MaskTest(unittest.TestCase):
	def setUp(self):
		zh, en, tw = bit('logs_zh'), bit('logs_en'), bit('logs_zh_tw')
		self.zh, self.en, self.tw = zh, en, tw
		self.rows = {
			1: row(1, 'module', '设置', {'logs_zh': '设置', 'logs_en': 'Settings'}),
			2: row(2, 'log', '关闭广告', {'logs_zh': '关闭广告', 'logs_en': 'Disable ads'}),
			3: row(3, 'module', '音量', {'logs_zh': '音量', 'logs_en': 'Volume'}),
			4: row(4, 'log', '修复问题', {'logs_zh': '修复问题', 'logs_en': 'Fix issue'}),
		}

	def test_extendable_mask(self):
		# 本 ROM 在别处声明过 en，才允许补到只声明了 zh 的位置上
		owners = {('roms', 10): [[1, [2], self.zh], [3, [4], self.zh | self.en]]}
		issues = LogMaintenance.mask_issues(self.rows, owners)
		self.assertEqual(1, len(issues['extendable']))
		detail = issues['extendable'][0]
		self.assertEqual(0, detail['position'])
		self.assertEqual(self.zh, detail['old_mask'])
		self.assertEqual(self.zh | self.en, detail['new_mask'])
		self.assertEqual(['logs_en'], detail['added'])

	def test_extendable_mask_stays_within_owner_languages(self):
		# 共享行的 en 可能来自别的 ROM：本 ROM 从未声明 en 时不得补位
		owners = {('roms', 10): [[1, [2], self.zh]]}
		issues = LogMaintenance.mask_issues(self.rows, owners)
		self.assertEqual([], issues['extendable'])

	def test_invalid_bit(self):
		owners = {('roms', 10): [[1, [2], self.zh | self.en | self.tw]]}
		issues = LogMaintenance.mask_issues(self.rows, owners)
		self.assertEqual([], issues['extendable'])
		self.assertEqual(['logs_zh_tw'], issues['invalid'][0]['bits'])

	def test_dangling(self):
		owners = {('roms', 10): [[1, [999], self.zh]]}
		issues = LogMaintenance.mask_issues(self.rows, owners)
		self.assertEqual([999], issues['dangling'][0]['missing'])

	def test_fill_masks_is_pure_on_dry_run(self):
		owners = {('roms', 10): [[1, [2], self.zh], [3, [4], self.zh | self.en]]}
		snapshot = copy.deepcopy(owners)
		result = LogMaintenance.fill_masks(self.rows, owners, apply=False)
		self.assertEqual(1, result['items'])
		self.assertEqual(1, result['owners'])
		self.assertEqual(snapshot, owners)   # dry-run 不得改调用方数据

	def test_fill_masks_skips_maskless_refs(self):
		owners = {('roms', 10): [[1, [2]]]}
		result = LogMaintenance.fill_masks(self.rows, owners, apply=False)
		self.assertEqual(0, result['items'])
		self.assertEqual({'roms': 0, 'dev': 0}, result['by_table'])

	def test_fill_masks_by_table(self):
		owners = {('dev', 3): [[1, [2], self.zh], [3, [4], self.zh | self.en]]}
		result = LogMaintenance.fill_masks(self.rows, owners, apply=False)
		self.assertEqual({'roms': 0, 'dev': 1}, result['by_table'])

	def test_fill_masks_stays_within_owner_languages(self):
		# 共享行被别的 ROM 补齐了 en，但本 ROM 只声明过 zh → 不补，避免把别人的译文写进掩码
		owners = {('roms', 10): [[1, [2], self.zh]]}
		snapshot = copy.deepcopy(owners)
		result = LogMaintenance.fill_masks(self.rows, owners, apply=False)
		self.assertEqual(0, result['items'])
		self.assertEqual(0, result['owners'])
		self.assertEqual({'roms': 0, 'dev': 0}, result['by_table'])
		self.assertEqual(snapshot, owners)

	def test_clean_invalid_masks_dry_run(self):
		owners = {('roms', 10): [[1, [2], self.zh | self.en | self.tw]]}
		snapshot = copy.deepcopy(owners)
		result = LogMaintenance.clean_invalid_masks(self.rows, owners, apply=False)
		self.assertEqual(1, result['items'])
		self.assertEqual(1, result['bits'])
		self.assertEqual(snapshot, owners)   # dry-run 无副作用


class PruneTest(unittest.TestCase):
	def test_unused_candidates(self):
		rows = {
			1: row(1, content='设置', texts={'logs_zh': '设置'}),
			2: row(2, content='孤儿', texts={'logs_zh': '孤儿'}),
		}
		owners = {('roms', 10): [[1, [], 1]]}
		result = LogMaintenance.prune_unused(rows, owners, apply=False)
		self.assertEqual(1, result['candidates'])
		self.assertEqual(2, result['samples'][0]['id'])
		self.assertEqual(2, result['rows_before'])
		self.assertEqual(2, result['rows_after'])


class MergeGroupsTest(unittest.TestCase):
	def test_prefers_real_translation_over_english_fallback(self):
		rows = {
			1: row(1, 'module', '其他', {
				'logs_zh': '其他', 'logs_en': 'Other', 'logs_ja': 'その他',
				'logs_fr': 'Autre', 'logs_de': 'Other', 'logs_ug': 'Other'}),
			11040: row(11040, 'module', '其他', {
				'logs_zh': '其他', 'logs_de': 'Sonstiges', 'logs_ug': 'باشقىلىرى'}),
		}
		result = LogMaintenance.merge_groups([[11040, 1]], rows=rows, apply=False)
		self.assertFalse(result['applied'])
		self.assertEqual({1: 1, 11040: 1}, result['mapping'])
		group = result['groups'][0]
		self.assertEqual(1, group['representative'])
		self.assertEqual('Sonstiges', group['texts']['logs_de'])
		self.assertEqual('باشقىلىرى', group['texts']['logs_ug'])
		self.assertEqual('Other', group['texts']['logs_en'])   # 回落值作为空缺保留
		self.assertEqual('其他', group['texts']['logs_zh'])

	def test_ignores_unknown_ids(self):
		rows = {1: row(1, 'module', '其他', {'logs_zh': '其他'})}
		result = LogMaintenance.merge_groups([[1, 999]], rows=rows)
		self.assertEqual({}, result['mapping'])
		self.assertEqual([], result['groups'])


class CompareTest(unittest.TestCase):
	def test_detects_added_and_removed(self):
		before = {'roms:1': {'logs_zh': {'设置': ['修复A']},
							 'logs_en': {'Settings': ['Fix A']}}}
		after = {'roms:1': {'logs_zh': {'设置': ['修复A', '新增B']}}}
		result = LogMaintenance.compare_snapshots(before, after, samples=2)
		self.assertEqual(1, result['changed'])
		self.assertEqual(1, result['added_lines'])
		self.assertEqual(1, result['removed_lines'])
		self.assertEqual(['logs_en'], result['lost_languages'])
		self.assertTrue(result['lost_content'])
		self.assertEqual('roms:1', result['samples'][0]['key'])

	def test_identical_snapshots(self):
		snapshot = {'roms:1': {'logs_zh': {'设置': ['修复A']}}}
		result = LogMaintenance.compare_snapshots(snapshot, copy.deepcopy(snapshot))
		self.assertEqual(0, result['changed'])
		self.assertFalse(result['lost_content'])

	def test_added_key_is_not_content_loss(self):
		before = {}
		after = {'roms:2': {'logs_zh': {'设置': ['新增']}}}
		result = LogMaintenance.compare_snapshots(before, after)
		self.assertEqual(['roms:2'], result['added_keys'])
		self.assertFalse(result['lost_content'])

	def test_module_label_change_is_reported_but_not_loss(self):
		before = {'roms:1': {'logs_de': {'Other': ['Fix']}}}
		after = {'roms:1': {'logs_de': {'Sonstiges': ['Fix']}}}
		result = LogMaintenance.compare_snapshots(before, after)
		self.assertEqual(1, result['changed'])
		self.assertEqual(1, result['modules_added'])
		self.assertEqual(1, result['modules_removed'])
		self.assertEqual(0, result['removed_lines'])
		self.assertEqual(0, result['added_lines'])
		self.assertFalse(result['lost_content'])


if __name__ == '__main__':
	unittest.main(verbosity=2)
