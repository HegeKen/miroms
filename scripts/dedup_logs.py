"""
dedup_logs.py - 合并 logs 表中「同一日志」的重复行（LogMaintenance 的命令行入口）

背景：logs 表按内容跨 ROM 复用分组，但历史上写入侧只按 content_hash 找候选行，
当同一条日志的两行主内容不同（例如 #25 content=相册、#27 content=Gallery，其实是
同一个「相册 / Gallery」模块）时就永远匹配不上，于是同一日志被拆成多行。

本脚本以中文日志为依据，把「类型相同、中文文本相同、各语言文本互不冲突」的行合并为一行：
  * 代表行取语言覆盖最全（其次 id 最小）的那一行；
  * 各语言文本取并集，content 按「中文 > 英文 > 任一」重建，content_hash 同步刷新；
  * 同步重写 roms.logs / dev.logs 里的 ID 引用（[[模块ID,[条目ID,...],掩码],...]）；
  * 语言掩码保持不变，已有译文不会被改写；合并只补齐原本缺失的语言。

判定 / 合并算法见 miroms.logs_maintenance.LogMaintenance（duplicate_plan / apply_duplicates），
体检与掩码维护见 maintain_logs.py。

用法：
    python3 data/scripts/dedup_logs.py              # 只统计并打印样本（默认 dry-run）
    python3 data/scripts/dedup_logs.py --apply      # 实际合并（先自动备份到 /tmp）
    python3 data/scripts/dedup_logs.py --apply --batch 500
    python3 data/scripts/dedup_logs.py --apply --prune-unused
    python3 data/scripts/dedup_logs.py --apply --fix-auto-increment
    python3 data/scripts/dedup_logs.py --apply --backup /tmp/logs_before.json --no-backup
"""
import argparse
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.logs_maintenance import LogMaintenance
from miroms.logs_store import LogStore


def ts() -> str:
	return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def print_duplicates(rows, mapping, samples: int) -> int:
	"""打印可合并分组，返回可减少的行数"""
	groups = Counter(mapping.values())
	duplicate_groups = {root: size for root, size in groups.items() if size > 1}
	removable = sum(size - 1 for size in duplicate_groups.values())
	print(f"[{ts()}] 重复分组 {len(duplicate_groups)} 组，涉及 "
		  f"{sum(duplicate_groups.values())} 行，合并后可减少 {removable} 行")
	for root, size in list(sorted(duplicate_groups.items(), key=lambda item: -item[1]))[:samples]:
		ids = [gid for gid, representative in mapping.items() if representative == root]
		print(f"\n--- 代表 #{root}（{size} 行合并）")
		for gid in sorted(ids):
			mark = '→' if gid == root else ' '
			print(f"  {mark} #{gid} content={rows[gid]['content'][:28]!r} "
				  f"语言={sorted(rows[gid]['texts'])}")
	return removable


def main() -> None:
	parser = argparse.ArgumentParser(description='合并 logs 表中同一日志的重复行')
	parser.add_argument('--apply', action='store_true', help='实际合并（默认只统计）')
	parser.add_argument('--batch', type=int, default=500, help='分页批大小（默认 500）')
	parser.add_argument('--samples', type=int, default=5, help='打印多少组样本')
	parser.add_argument('--prune-unused', action='store_true',
						help='同时删除没有被任何 ROM / 开发版周报引用的日志行')
	parser.add_argument('--fix-auto-increment', action='store_true',
						help='合并后把 logs.AUTO_INCREMENT 归位到 MAX(id)+1')
	parser.add_argument('--backup', help='--apply 前的备份路径（默认写入系统临时目录）')
	parser.add_argument('--no-backup', action='store_true', help='--apply 前不做备份')
	args = parser.parse_args()

	print(f"[{ts()}] 载入 logs 表...")
	rows = LogMaintenance.load_rows()
	print(f"[{ts()}] 共 {len(rows)} 行，正在计算可合并分组...")
	mapping, merged_rows = LogMaintenance.duplicate_plan(rows)
	removable = print_duplicates(rows, mapping, args.samples)

	if not removable:
		print(f"\n[{ts()}] 没有需要合并的重复行。")
		if args.apply and args.prune_unused:
			result = LogMaintenance.prune_unused(rows=rows, apply=True, batch=args.batch)
			print(f"[{ts()}] 清理未被引用的日志行 {result['candidates']} 行，"
				  f"剩余 {result['rows_after']} 行")
		if args.apply and args.fix_auto_increment:
			before, after = LogMaintenance.fix_auto_increment('logs')
			print(f"[{ts()}] AUTO_INCREMENT：{before} -> {after}")
		return

	if not args.apply:
		print(f"\n[{ts()}] dry-run 结束（未写库）。确认无误后加 --apply 执行合并。")
		return

	if not args.no_backup:
		path = LogMaintenance.backup(args.backup)
		print(f"[{ts()}] 合并前备份已写入 {path}")

	print(f"\n[{ts()}] 开始合并...")
	stats = LogMaintenance.apply_duplicates(mapping, merged_rows, batch=args.batch)
	print(f"[{ts()}] 完成：刷新代表行 {stats['updated_groups']} 行，"
		  f"删除重复行 {stats['deleted_groups']} 行，"
		  f"重写 roms {stats['updated_roms']} 行 / dev {stats['updated_dev']} 行")

	after = LogMaintenance.load_rows()
	print(f"[{ts()}] 合并后 logs 表 {len(after)} 行"
		  f"（合并前 {len(rows)} 行，减少 {len(rows) - len(after)} 行）")

	remaining, _ = LogMaintenance.duplicate_plan(after)
	left = Counter(remaining.values())
	print(f"[{ts()}] 复检：仍有重复分组 {sum(1 for size in left.values() if size > 1)} 组")

	if args.prune_unused:
		result = LogMaintenance.prune_unused(rows=after, apply=True, batch=args.batch)
		print(f"[{ts()}] 清理未被引用的日志行 {result['candidates']} 行，"
			  f"剩余 {result['rows_after']} 行")
		after = LogMaintenance.load_rows()
		remaining, _ = LogMaintenance.duplicate_plan(after)
		left = Counter(remaining.values())
		print(f"[{ts()}] 清理后复检：重复分组 "
			  f"{sum(1 for size in left.values() if size > 1)} 组")
	if args.fix_auto_increment:
		before, after_counter = LogMaintenance.fix_auto_increment('logs')
		print(f"[{ts()}] AUTO_INCREMENT：{before} -> {after_counter}")
	store_dupes = LogStore.duplicate_report()
	print(f"[{ts()}] LogStore.duplicate_report 复检：重复分组 {len(store_dupes)} 组")
	if store_dupes:
		sys.exit(1)
	print(f"[{ts()}] 提示：合并会并集各语言文本，可随后用 "
		  f"`maintain_logs.py masks --apply` 补齐引用掩码（只增不减）")


if __name__ == '__main__':
	main()
