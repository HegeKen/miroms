"""
enrich_xms.py - 用 logs 表补全 XMS 数据，并按包名统一应用名

抓取时（miroms/xms.py 的 record()）已经会查 logs 表补多语言译文，
本脚本用于：

* 回填历史数据（早期只存了 zh / en 的应用名与日志）；
* logs 表后续补齐译文后，重新刷新 XMS 的名称 / 日志；
* 把同一个包名在各个推送里的应用名统一成一份（有官方译文的优先）。

没有包名的日志模块（如「小米超级岛」）存在 xms.changelog 里，不参与包名统一。

用法：
    python3 scripts/enrich_xms.py            # 只统计，不写库
    python3 scripts/enrich_xms.py --apply    # 写库
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import common


def main() -> None:
	apply = '--apply' in sys.argv
	stats = common.XmsStore.enrich_all(apply=apply)
	action = '已写入' if apply else '预览（加 --apply 才写库）'
	print(f"XMS 多语言补全 {action}：")
	print(f"  旧版无包名行迁移 {stats['legacy']} 行（搬到 xms.changelog）")
	print(f"  空条目清理 {stats.get('empty', 0)} 行（只有名称、无安装包 / 日志）")
	print(f"  推送日期归一 {stats.get('dates', 0)} 行（取应用包 Last-Modified 众数）")
	print(f"  logs module 占位新增 {stats.get('modules', 0)} 条（缺失的应用名）")
	print(f"  包名 {stats['packages']} 个，应用名需更新 {stats['names']} 行")
	print(f"  应用日志需补全 {stats['logs']} 行，无包名模块需补全 {stats['extras']} 条")


if __name__ == '__main__':
	main()
