"""
resequence_ids.py - 把指定表的 id 重排成连续自增（消除 AUTO_INCREMENT 空档）

空档来源：InnoDB 的 AUTO_INCREMENT 在**插入失败 / 事务回滚**时不会回收，
抓取脚本偶发失败就会烧掉一个 id，日积月累形成空档（`MAX(id)` 比行数大）。
本脚本把 id 按现有顺序重排成 1..N，并把 AUTO_INCREMENT 重置为 N+1。

安全性：
* 只允许 **id 不被其它表引用** 的表（见 SAFE_TABLES）：
  - `roms.id`：没有任何表 / 导出 JSON / API 引用（导出用 device + version 标识，
    后台表格用 id 只是页面临时行号）；
  - `dev.id`：主键，无人引用（`roms.dev_week` 存的是周数，不是 dev.id）。
  **`logs.id` 不可重排** —— `roms.logs` / `dev.logs` 按 id 引用它。
* 重排前会把「旧 id → 新 id」映射写到 `.backup/<表名>_id_map_<时间>.csv`，可据此回滚；
* 重排前会先采样 `AUTO_INCREMENT` / `MAX(id)`，确认没有并发写入（三个项目的抓取脚本
  共用同一个 miroms 库），并列出仍在运行的抓取进程；
* 采用「先整体 +1000000，再赋 ROW_NUMBER()」两段式更新，避免主键中途撞号。

用法：
    python3 data/scripts/resequence_ids.py                    # 只看 roms 空档
    python3 data/scripts/resequence_ids.py --table dev        # 只看 dev 空档
    python3 data/scripts/resequence_ids.py --apply            # 实际重排 roms
    python3 data/scripts/resequence_ids.py --table dev --apply
    python3 data/scripts/resequence_ids.py --verify           # 只校验是否连续
"""
import argparse
import csv
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.database import DatabaseManager

# 重排期间必须没有其它写入者。注意：HyperOS.fans / NuxtMR / hub.miuier.com
# 三个项目的抓取脚本共用同一个 miroms 库（各自的 scripts/config.py 都指向它），
# 所以这里按脚本名匹配**全部三个项目**的进程，不只本项目。
BUSY_PATTERNS = (
	'fetch_changelog.py', 'get_new_branch.py', 'ota_former.py', 'ota_full.py',
	'xfu_full.py', 'mgc_fastboot.py', 'get_current_fastboot.py', 'aspatch.py',
	'run_all_jobs.py', 'import_dev_week.py', 'migrate_logs_multilang.py',
	'dedup_logs.py', 'rebuild_roms_logs.py',
)
OFFSET = 1_000_000
PROBE_SECONDS = 20      # 采样窗口：这段时间内 AUTO_INCREMENT / MAX(id) 不变才认为没人在写

# 允许重排的表（id 不被任何表引用的才能进来；logs.id 被 roms.logs / dev.logs 引用，禁止）
SAFE_TABLES = ('roms', 'dev')
TABLE = 'roms'


def ts() -> str:
	return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def running_jobs() -> list:
	found = []
	for pattern in BUSY_PATTERNS:
		result = subprocess.run(['pgrep', '-fl', pattern], capture_output=True, text=True)
		for line in (result.stdout or '').splitlines():
			if 'resequence_roms_ids' in line or pattern == 'run_all_jobs.py' and 'resequence' in line:
				continue
			found.append(line.strip())
	return found


def auto_increment() -> int:
	"""读自增计数器

	注意：information_schema 的这类动态统计默认缓存 24 小时（information_schema_stats_expiry），
	不关掉缓存会读到过期值，所以这里先把会话的缓存过期时间设为 0。
	"""
	DatabaseManager.execute("SET SESSION information_schema_stats_expiry = 0")
	row = DatabaseManager.query_one(
		"SELECT AUTO_INCREMENT FROM information_schema.TABLES "
		"WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s", params=(TABLE,))
	return int(row[0] or 0)


def write_activity(seconds: int = PROBE_SECONDS) -> bool:
	"""采样一段时间：AUTO_INCREMENT 或 MAX(id) 变化即说明有人在写 roms

	（抓取脚本插入失败也会推进 AUTO_INCREMENT —— 这正是空档的来源，
	所以它比只看行数更灵敏。）
	"""
	before = (auto_increment(), stats()['max'])
	time.sleep(seconds)
	after = (auto_increment(), stats()['max'])
	if before != after:
		print(f"   采样期间发生变化：AUTO_INCREMENT {before[0]} -> {after[0]}，"
			  f"MAX(id) {before[1]} -> {after[1]}")
		return True
	return False


def gaps() -> list:
	"""返回 [(前一个 id, 当前 id, 空档数), ...]"""
	return [(int(row[0]), int(row[1]), int(row[2])) for row in DatabaseManager.query_all(
		"SELECT prev_id, id, id - prev_id - 1 AS gap FROM ("
		f"  SELECT `id`, LAG(`id`) OVER (ORDER BY `id`) AS prev_id FROM `{TABLE}`"
		") t WHERE id - prev_id > 1 ORDER BY id"
	) or []]


def stats() -> dict:
	row = DatabaseManager.query_one(
		f"SELECT COUNT(*), MIN(`id`), MAX(`id`) FROM `{TABLE}`")
	return {'rows': int(row[0]), 'min': int(row[1] or 0), 'max': int(row[2] or 0)}


def dump_map(path: Path) -> int:
	"""导出旧 id → 新 id 映射（按现有顺序），可用于回滚或外部引用修正"""
	count = 0
	with open(path, 'w', encoding='utf-8', newline='') as handle:
		writer = csv.writer(handle)
		writer.writerow(['old_id', 'new_id'])
		rows = DatabaseManager.query_all(
			f"SELECT `id`, ROW_NUMBER() OVER (ORDER BY `id`) FROM `{TABLE}` ORDER BY `id`") or []
		for old_id, new_id in rows:
			writer.writerow([int(old_id), int(new_id)])
			count += 1
	return count


def resequence() -> None:
	backup_dir = Path(__file__).resolve().parents[2] / '.backup'
	backup_dir.mkdir(parents=True, exist_ok=True)
	stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
	map_path = backup_dir / f'{TABLE}_id_map_{stamp}.csv'
	count = dump_map(map_path)
	print(f"[{ts()}] 旧→新 id 映射已写入 {map_path}（{count} 行）")

	print(f"[{ts()}] 第一段：整体 +{OFFSET} ...")
	DatabaseManager.execute(f"UPDATE `{TABLE}` SET `id` = `id` + {OFFSET}", raise_on_error=True)

	print(f"[{ts()}] 第二段：按顺序赋连续编号 ...")
	DatabaseManager.execute(
		f"UPDATE `{TABLE}` r JOIN ("
		f"  SELECT `id`, ROW_NUMBER() OVER (ORDER BY `id`) AS rn FROM `{TABLE}`"
		") m ON m.`id` = r.`id` SET r.`id` = m.rn", raise_on_error=True)

	current = stats()
	print(f"[{ts()}] 重置 AUTO_INCREMENT = {current['max'] + 1} ...")
	DatabaseManager.execute(f"ALTER TABLE `{TABLE}` AUTO_INCREMENT = {current['max'] + 1}", raise_on_error=True)


def main() -> None:
	parser = argparse.ArgumentParser(description='重排表 id 为连续自增（默认 roms）')
	parser.add_argument('--table', default='roms', choices=SAFE_TABLES,
						help='要重排的表（仅限 id 未被引用的表）')
	parser.add_argument('--apply', action='store_true', help='实际执行重排（默认只看空档）')
	parser.add_argument('--verify', action='store_true', help='只校验 id 是否连续')
	parser.add_argument('--force', action='store_true', help='即使检测到抓取 / 导入脚本在跑也继续')
	args = parser.parse_args()
	global TABLE
	TABLE = args.table

	before = stats()
	found = gaps()
	print(f"[{ts()}] {TABLE}：{before['rows']} 行，id {before['min']} ~ {before['max']}，"
		  f"空档 {len(found)} 处 / 共 {sum(item[2] for item in found)} 个")

	if args.verify:
		if found:
			print('✖ id 不连续：', found[:10])
			sys.exit(1)
		print('✓ id 连续')
		return

	if not found:
		# id 已经连续，但自增计数器可能被 INSERT ... ON DUPLICATE KEY UPDATE /
		# 失败回滚推高（下一个 id 会跳号），顺手归位
		counter = auto_increment()
		if args.apply and counter > before['max'] + 1:
			DatabaseManager.execute(
				f"ALTER TABLE `{TABLE}` AUTO_INCREMENT = {before['max'] + 1}", raise_on_error=True)
			print(f"[{ts()}] id 已连续；自增计数器 {counter} → {before['max'] + 1} 已归位")
		elif counter > before['max'] + 1:
			print(f"[{ts()}] id 已连续；自增计数器为 {counter}（下一个 id 会跳到 {counter}，"
				  f"加 --apply 归位到 {before['max'] + 1}）")
		else:
			print(f"[{ts()}] id 连续、计数器正常（{counter}），无需处理")
		return

	if not args.apply:
		print('空档位置（前 10）：', found[:10])
		print('加 --apply 执行重排')
		return

	print(f"[{ts()}] 采样 {PROBE_SECONDS} 秒确认没有并发写入 ...")
	if write_activity():
		print(f'✖ 有人在写 {TABLE}（可能是三个项目之一的定时任务），等它结束再重排')
		sys.exit(1)
	print('   ✓ 采样期间无写入')

	busy = running_jobs()
	if busy:
		print(f"[{ts()}] 提示：检测到 {len(busy)} 个抓取进程（三个项目共用 miroms 库）：")
		for line in busy[:5]:
			print('   ', line.rsplit('/data/scripts/', 1)[-1] if '/data/scripts/' in line else line)
		if not args.force:
			print('   ✖ 它们随时可能写入，确认无进展后加 --force 继续')
			sys.exit(1)
		print('   ⚠ --force：已确认采样期内无写入，继续重排')

	resequence()

	after = stats()
	left = gaps()
	print(f"[{ts()}] 重排完成：{after['rows']} 行，id {after['min']} ~ {after['max']}，剩余空档 {len(left)} 处")
	if left:
		print('✖ 仍有空档：', left[:10])
		sys.exit(1)
	print('✓ id 已连续')


if __name__ == '__main__':
	main()
