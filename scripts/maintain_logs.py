"""
maintain_logs.py - logs 表日常维护的统一入口（体检 / 内容 / 掩码 / id / 孤儿行 / 计数器 / 对比）

所有动作都只调用 miroms.logs_maintenance.LogMaintenance，命令本身只做参数解析与打印：
  * audit            一次性体检（重复、悬空引用、坏 JSON、孤儿行、content 不一致、
                     哈希过期、掩码可补位 / 无效位、id 空档与自增计数器），只读；
  * content          以 logs_zh 为准重建 content / content_hash，并回填「只有 content 有中文」的行；
  * masks            补齐引用掩码里「模块与条目都已有」的语言位（只增不减）；
                     加 --clean-invalid 则删除「模块行已没有该语言文本」的无效位；
  * ids              把 logs.id 压成连续 1..N，并同步重写 roms.logs / dev.logs 引用；
  * unused           删除没有被任何 ROM / 开发版周报引用的日志行；
  * dangling         删除引用里指向已不存在 logs 行的模块 / 条目（悬空引用）；
  * auto-increment   把 logs.AUTO_INCREMENT 归位到 MAX(id)+1；
  * merge            按显式分组把若干 id 合并成一行（真实译文优先，引用自动重写）；
  * snapshot         把当前所有 roms/dev 的多语言日志拍成 JSON 快照；
  * compare          对比快照与当前库，确认维护前后导出没有内容丢失。

默认全部 dry-run，只有加 --apply 才写库；破坏性动作（ids）写库前自动备份
（`--no-backup` 可跳过，`--backup PATH` 指定路径）。

去重仍由 dedup_logs.py 负责（它需要打印分组样本，参数也不同）：
    python3 scripts/dedup_logs.py --apply

用法：
    python3 scripts/maintain_logs.py                        # 体检（默认动作）
    python3 scripts/maintain_logs.py --report /tmp/logs_audit.json
    python3 scripts/maintain_logs.py content                # 看 content 不一致明细
    python3 scripts/maintain_logs.py content --apply
    python3 scripts/maintain_logs.py masks --apply
    python3 scripts/maintain_logs.py ids                    # 只看会压缩多少个 id
    python3 scripts/maintain_logs.py ids --apply
    python3 scripts/maintain_logs.py unused --apply
    python3 scripts/maintain_logs.py dangling --apply
    python3 scripts/maintain_logs.py auto-increment --apply
    python3 scripts/maintain_logs.py merge --groups "11040:1" --apply
    python3 scripts/maintain_logs.py snapshot --out /tmp/logs_before.json
    python3 scripts/maintain_logs.py compare --before /tmp/logs_before.json
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.logs_clean import LogPrefixCleaner
from miroms.logs_maintenance import LogMaintenance
from miroms.logs_store import LogStore

ACTIONS = ('audit', 'complete', 'content', 'prefix', 'masks', 'ids', 'unused',
		   'dangling', 'auto-increment', 'merge', 'snapshot', 'compare')


def ts() -> str:
	return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def print_audit(report: dict) -> None:
	print(f"[{ts()}] logs 体检")
	print(f"  行数：{report['rows']}（AI 已校对 proofed：{report['proofed']}，"
		  f"complete：{report['complete']}，语言不符标注：{report['lang_issues']}）"
		  f"　id：{report['ids']['min']} ~ {report['ids']['max']}"
		  f"（空档 {report['ids']['gaps']} 处 / {report['ids']['missing']} 个，"
		  f"AUTO_INCREMENT {report['ids']['auto_increment']}"
		  f"{'，已归位' if report['ids']['counter_ok'] else '，需归位'}）")
	print(f"  重复分组：{report['duplicates']['groups']} 组 / {report['duplicates']['rows']} 行"
		  f"（LogStore.duplicate_report：{report['duplicates']['store_groups']} 组）")
	print(f"  引用：{report['refs']['owners']} 条 roms/dev；"
		  f"悬空 {report['refs']['dangling_items']} 处；坏 JSON {report['refs']['bad']} 条")
	print(f"  孤儿行（未被引用）：{report['unused']['rows']}")
	print(f"  content：{report['content']['issues']} 行不一致 {report['content']['by_reason']}")
	print(f"  content_hash 过期：{report['hash']['stale']} 行")
	print(f"  语言掩码：可补位 {report['masks']['extendable']} 处，"
		  f"无效位 {report['masks']['invalid']} 处")
	if report['mergeable']['ids']:
		print(f"  可合并样例：{report['mergeable']['ids']}")
	if report['content']['ids']:
		print(f"  content 不一致样例：{report['content']['ids']}")


def run_audit(args) -> int:
	report = LogMaintenance.audit(samples=args.samples)
	print_audit(report)
	if args.report:
		path = Path(args.report)
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
		print(f"报告已写入 {path}")
	# no_zh 是「本来就没有中文」的已知缺口（品牌名 / 占位符，交给 fix_non_zh_logs.py），
	# 不算结构性错误；其余问题（重复 / 悬空 / 坏 JSON / content 与 logs_zh 冲突 / 哈希过期）才报错
	content_problems = sum(count for reason, count in report['content']['by_reason'].items()
						   if reason != 'no_zh')
	problems = (report['duplicates']['groups'] + report['refs']['dangling_items']
				+ report['refs']['bad'] + content_problems + report['hash']['stale'])
	if problems:
		print(f"✖ 发现 {problems} 处需要处理的问题")
		return 1
	print('✓ 没有需要处理的结构性问题')
	return 0


def run_prefix(args) -> int:
	types = tuple(item.strip() for item in args.types.split(',') if item.strip())
	rows = LogMaintenance.load_rows()
	plan = LogPrefixCleaner.plan(rows, types=types, limit=args.limit)
	print(f"[{ts()}] 开头空白/标点整理：{plan['stats']['rows']} 行，"
		  f"{plan['stats']['columns']} 列（content {plan['stats']['content']} / "
		  f"语言列 {plan['stats']['lang_columns']}），跳过 {plan['stats']['skipped']}")
	for action in plan['actions'][:args.samples]:
		print(f"  #{action['row_id']} [{action['type']}] {action['content_before']!r}")
		if 'content' in action['changes']:
			print(f"    content: {action['content_before']!r} -> {action['changes']['content']!r}")
		for column, value in action['changes'].items():
			if column == 'content':
				continue
			print(f"    {column}: {action['before'].get(column, '')!r} -> {value!r}")
	if len(plan['actions']) > args.samples:
		print(f"  ... 其余 {len(plan['actions']) - args.samples} 行")
	if plan['skipped']:
		reasons = {}
		for item in plan['skipped']:
			reasons[item['reason']] = reasons.get(item['reason'], 0) + 1
		print(f"  跳过：{reasons}")
	if not args.apply:
		print('dry-run：加 --apply 写库（写前备份）')
		return 0
	result = LogPrefixCleaner.apply(plan, apply=True, backup=not args.no_backup,
									backup_path=args.backup)
	if result.get('backup'):
		print(f"备份已写入 {result['backup']}")
	print(f"[{ts()}] 已整理：{plan['stats']['rows']} 行 / {plan['stats']['columns']} 列")
	return 0


def run_complete(args) -> int:
	result = LogMaintenance.refresh_complete(apply=False)
	print(f"[{ts()}] 全部语言齐全且 proofed=1：{result['should']} 行，"
		  f"需更新 complete：{result['changed']} 行")
	if result['ids']:
		print(f"  样例：{result['ids']}")
	if not args.apply:
		print('加 --apply 重算 complete（只改标记，不改内容）')
		return 0
	result = LogMaintenance.refresh_complete(apply=True)
	print(f"[{ts()}] 已重算 complete：{result['should']} 行为 1，"
		  f"其余 proofed 行 complete=0")
	return 0


def run_content(args) -> int:
	issues = LogMaintenance.content_issues()
	print(f"[{ts()}] content 不一致 / 非简体中文：{len(issues)} 行")
	for issue in issues[:args.samples]:
		print(f"  #{issue['id']} [{issue['reason']}] content={issue['content'][:40]!r} "
			  f"logs_zh={issue['logs_zh'][:40]!r}")
	if not args.apply:
		if issues:
			print('加 --apply 以 logs_zh 为准重建 content（no_zh / empty 交 fix_non_zh_logs.py 处理）')
		return 0
	result = LogMaintenance.repair_content(apply=True, batch=args.batch)
	print(f"[{ts()}] 已写库：content 更新 {result['content_updates']} 行，"
		  f"logs_zh 回填 {result['zh_updates']} 行；未解决 {result['unresolved']} 行"
		  f"（{result['by_reason']}）")
	return 0


def run_masks(args) -> int:
	if args.clean_invalid:
		result = LogMaintenance.clean_invalid_masks(apply=False)
		print(f"[{ts()}] 无效掩码位：{result['owners']} 条引用 / {result['items']} 个位置 / "
			  f"{result['bits']} 个语言位（{result['by_table']}）")
		if not args.apply:
			print('加 --apply 清理（只删除「模块行已没有该语言」的无效位）')
			return 0
		result = LogMaintenance.clean_invalid_masks(apply=True, batch=args.batch)
		print(f"[{ts()}] 已清理：{result['owners']} 条引用，{result['items']} 个位置，"
			  f"{result['bits']} 个语言位")
		return 0
	issues = LogMaintenance.mask_issues()
	print(f"[{ts()}] 掩码检查：可补位 {len(issues['extendable'])} 处，"
		  f"无效位 {len(issues['invalid'])} 处，悬空引用 {len(issues['dangling'])} 处")
	for detail in issues['extendable'][:args.samples]:
		print(f"  {detail['table']}#{detail['id']} 位置 {detail['position']}："
			  f"mask {detail['old_mask']} → {detail['new_mask']}，补 {detail['added']}")
	if not args.apply:
		if issues['extendable']:
			print('加 --apply 补齐语言位（只增不减，不会让导出结果回退）')
		if issues['dangling']:
			print('⚠ 存在悬空引用，先跑 dedup_logs.py / resequence_ids.py --table logs 修复引用')
		return 0
	result = LogMaintenance.fill_masks(apply=True, batch=args.batch)
	print(f"[{ts()}] 已写库：更新 {result['owners']} 条 roms/dev 引用，"
		  f"补齐 {result['items']} 个位置（{result['bits']} 个语言位）"
		  f"（{result['by_table']}）")
	return 0


def run_ids(args) -> int:
	preview = LogMaintenance.compact_ids(apply=False)
	before = preview['before']
	print(f"[{ts()}] logs：{before['rows']} 行，id {before['min']} ~ {before['max']}，"
		  f"空档 {before['gaps']} 处 / {before['missing']} 个，"
		  f"AUTO_INCREMENT {preview['auto_increment']}")
	if not preview['changed']:
		print('id 已连续，无需压缩（计数器可用 auto-increment 动作归位）')
		return 0
	print(f"  将重排 {preview['changed']} 个 id，样例 {preview['mapping_sample']}")
	if not args.apply:
		print('加 --apply 执行（同一事务内改 id + 重写 roms/dev 引用，写库前自动备份）')
		return 0
	result = LogMaintenance.compact_ids(
		apply=True, backup=not args.no_backup,
		backup_path=args.backup, batch=args.batch)
	if result.get('backup'):
		print(f"[{ts()}] 备份已写入 {result['backup']}")
	after = result['after']
	print(f"[{ts()}] 完成：{after['rows']} 行，id {after['min']} ~ {after['max']}，"
		  f"剩余空档 {after['gaps']} 处；重写 roms {result['refs'].get('roms', 0)} 行 / "
		  f"dev {result['refs'].get('dev', 0)} 行；AUTO_INCREMENT "
		  f"{result['auto_increment_after']}")
	return 0


def run_unused(args) -> int:
	result = LogMaintenance.prune_unused(apply=False)
	print(f"[{ts()}] 未被引用的日志行：{result['candidates']} 行")
	for sample in result['samples']:
		print(f"  #{sample['id']} [{sample['type']}] {sample['content']!r}")
	if not args.apply or not result['candidates']:
		if result['candidates']:
			print('加 --apply 删除这些行（会刷新导出缓存）')
		return 0
	result = LogMaintenance.prune_unused(apply=True, batch=args.batch)
	print(f"[{ts()}] 已删除 {result['candidates']} 行，logs 剩余 {result['rows_after']} 行")
	return 0


def run_dangling(args) -> int:
	result = LogMaintenance.prune_dangling(apply=False)
	print(f"[{ts()}] 悬空引用：{result['owners']} 条 roms/dev，涉及 "
		  f"{result['missing_ids']} 个已删除 id；将删除 {result['positions']} 个模块位置 / "
		  f"{result['entries']} 个条目（{result['owners_empty']} 条引用会被清空）")
	if not args.apply or not result['owners']:
		if result['owners']:
			print('加 --apply 清理（写库前自动备份）')
		return 0
	result = LogMaintenance.prune_dangling(
		apply=True, batch=args.batch, backup=not args.no_backup,
		backup_path=args.backup)
	if result.get('backup'):
		print(f"[{ts()}] 备份已写入 {result['backup']}")
	print(f"[{ts()}] 完成：重写 roms {result['refs'].get('roms', 0)} 行 / "
		  f"dev {result['refs'].get('dev', 0)} 行")
	return 0


def run_auto_increment(args) -> int:
	before = LogMaintenance.auto_increment('logs')
	stats = LogMaintenance.table_stats('logs')
	expected = stats['max'] + 1
	print(f"[{ts()}] logs.AUTO_INCREMENT = {before}，MAX(id)+1 = {expected}")
	if before == expected:
		print('计数器已归位，无需处理')
		return 0
	if not args.apply:
		print(f'加 --apply 归位（{before} → {expected}）')
		return 0
	old, new = LogMaintenance.fix_auto_increment('logs')
	print(f"[{ts()}] AUTO_INCREMENT：{old} → {new}")
	return 0


def parse_groups(spec: str) -> list:
	"""解析 "11040:1,11036:4576" → [[11040, 1], [11036, 4576]]"""
	groups = []
	for chunk in (spec or '').split(','):
		ids = []
		for piece in chunk.strip().replace(':', ' ').split():
			try:
				ids.append(int(piece))
			except ValueError:
				continue
		if len(ids) >= 2:
			groups.append(ids)
	return groups


def run_merge(args) -> int:
	groups = parse_groups(args.groups)
	if not groups:
		print('✖ merge 需要 --groups，例如 "11040:1"（多个分组用逗号分隔）')
		return 2
	rows = LogMaintenance.load_rows()
	preview = LogMaintenance.merge_groups(groups, rows=rows, apply=False)
	if not preview['groups']:
		print('✖ 分组里的 id 不存在或不足两个')
		return 2
	for group in preview['groups']:
		print(f"  合并 {group['ids']} → #{group['representative']} "
			  f"content={group['content']!r}（{len(group['texts'])} 种语言）")
		for column in LogStore.LANG_COLUMNS:
			value = group['texts'].get(column)
			if value:
				print(f"    {column}={value!r}")
	if not args.apply:
		print('dry-run：确认无误后加 --apply 执行（写库前自动备份）')
		return 0
	result = LogMaintenance.merge_groups(groups, rows=rows, apply=True,
										 backup=not args.no_backup, backup_path=args.backup)
	if result.get('backup'):
		print(f"[{ts()}] 备份已写入 {result['backup']}")
	stats = result['stats']
	print(f"[{ts()}] 完成：刷新代表行 {stats['updated_groups']} 行，删除 {stats['deleted_groups']} 行，"
		  f"重写 roms {stats['updated_roms']} 行 / dev {stats['updated_dev']} 行")
	print('提示：合并后 logs 可能出现 id 空档，可用 ids --apply 压缩（会同步重写引用）')
	return 0


def run_snapshot(args) -> int:
	print(f"[{ts()}] 正在导出全部 roms / dev 的多语言日志快照 ...")
	snapshot = LogMaintenance.export_snapshot()
	path = LogMaintenance.save_snapshot(snapshot, args.out)
	size = Path(path).stat().st_size / 1024 / 1024
	print(f"[{ts()}] 已写入 {path}（{len(snapshot)} 条 roms/dev，{size:.1f} MB）")
	return 0


def run_compare(args) -> int:
	if not args.before:
		print('✖ compare 需要 --before <快照.json>（先用 snapshot 拍一份）')
		return 2
	before = LogMaintenance.load_snapshot(args.before)
	print(f"[{ts()}] 载入快照 {args.before}（{len(before)} 条），正在对比当前导出 ...")
	after = LogMaintenance.export_snapshot()
	result = LogMaintenance.compare_snapshots(before, after, samples=args.samples)
	print(f"  条目：{result['before_keys']} -> {result['after_keys']}，变化 {result['changed']} 条")
	print(f"  新增文本 {result['added_lines']} 行，消失文本 {result['removed_lines']} 行；"
		  f"模块名 +{result['modules_added']} / -{result['modules_removed']}")
	if result['added_keys'] or result['removed_keys']:
		print(f"  新增键 {result['added_keys'][:5]}，移除键 {result['removed_keys'][:5]}")
	for sample in result['samples'][:args.samples]:
		print(f"  {sample['key']}：+{sample['added_lines']} / -{sample['removed_lines']}"
			  f"，语言 +{sample['added_languages']} -{sample['removed_languages']}")
		for detail in sample['samples'][:2]:
			print(f"    {detail['change']} [{detail['column']}] {detail['text']!r}")
	if args.report:
		path = Path(args.report)
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
		print(f"报告已写入 {path}")
	if result['lost_content']:
		print('✖ 检测到内容丢失（条目文本减少 / 语言减少 / 键消失），请人工核对后再继续')
		return 1
	print('✓ 导出对比通过：没有内容丢失')
	return 0


def main() -> int:
	parser = argparse.ArgumentParser(
		description='logs 表维护统一入口（默认体检，只读；写库需 --apply）')
	parser.add_argument('action', nargs='?', default='audit', choices=ACTIONS)
	parser.add_argument('--apply', action='store_true', help='实际写库（默认 dry-run）')
	parser.add_argument('--batch', type=int, default=500, help='分页批大小（默认 500）')
	parser.add_argument('--samples', type=int, default=5, help='打印多少条样本')
	parser.add_argument('--types', default='module,log', help='prefix 动作：module,log')
	parser.add_argument('--limit', type=int, default=0, help='prefix 动作：最多处理多少行')
	parser.add_argument('--report', help='audit / compare：把结果写入该 JSON 文件')
	parser.add_argument('--backup', help='ids 动作：备份路径（默认系统临时目录）')
	parser.add_argument('--no-backup', action='store_true', help='ids 动作：不备份')
	parser.add_argument('--clean-invalid', action='store_true',
						help='masks 动作：删除掩码里「模块行已无该语言文本」的无效位')
	parser.add_argument('--out', help='snapshot 动作：快照输出路径（默认系统临时目录）')
	parser.add_argument('--before', help='compare 动作：对比基准快照路径')
	parser.add_argument('--groups', help='merge 动作：分组，如 "11040:1"（多个分组用逗号分隔）')
	args = parser.parse_args()

	if args.action == 'audit':
		return run_audit(args)
	if args.action == 'complete':
		return run_complete(args)
	if args.action == 'prefix':
		return run_prefix(args)
	if args.action == 'content':
		return run_content(args)
	if args.action == 'masks':
		return run_masks(args)
	if args.action == 'ids':
		return run_ids(args)
	if args.action == 'unused':
		return run_unused(args)
	if args.action == 'dangling':
		return run_dangling(args)
	if args.action == 'merge':
		return run_merge(args)
	if args.action == 'snapshot':
		return run_snapshot(args)
	if args.action == 'compare':
		return run_compare(args)
	return run_auto_increment(args)


if __name__ == '__main__':
	sys.exit(main())
