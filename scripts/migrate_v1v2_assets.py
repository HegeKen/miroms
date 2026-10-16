#!/usr/bin/env python3
"""把两个参考站点的「静态 / 目录 / 遗留机型」文件补齐到 api/v1、api/v2。

``miroms/legacy_exporters.py`` 负责从库里**重生成**站点接口文件；本脚本负责迁移那些
库里没有来源、只能随仓库维护的部分：

* **静态接口文件**（手写内容或生成脚本早已废弃的归档结构）：
  v1 的 ``tools.json`` / ``thanks.json`` / ``devices.json`` / ``log.json`` / ``stable.json``
  / ``update.json`` / ``update_full.json`` / ``newrom.json``；
  v2 的 ``updates.json`` / ``new-rom.json``。
* **机型目录**（人工维护的品牌 / 系列 / 排序）：v1 ``devlist.json``、v2 ``devices.json``；
  只在目标缺失时播种，之后由 ``exporter.py`` 回填 android / miui / supports。
* **仅存于参考仓库的遗留机型**：``devices/<codename>.json`` 在目标里不存在时按原样补齐
  （这些机型在 miroms 库中没有记录，例如 mione、HM2013023、pond、chicago 等）。

**机型图片不搬运**：参考站点把机型图放在各自的 ``assets/images/**``，但仓库里已经有一份
**规范位置** ``data/images/``（站点根 ``https://api.miuier.com/images/<file>``，前端
``useApi().buildDeviceImageUrl`` 就走这里）。两个站点的图片与它逐文件一致（382/382，
且 v2 ``devices.json`` 引用的 247 张全覆盖），因此再往 ``api/v2/assets/images/`` 复制一份
纯属重复（约 25 MB）。确需还原旧结构时加 ``--with-images``。

默认**只补缺失**（不覆盖）：设备文件与静态文件一旦落库 / 落仓，后续就以仓库版本为准，
避免重跑脚本把手改内容或库里导出的设备文件冲掉。需要强制覆盖静态文件时加 ``--force``。

用法::

    python3 scripts/migrate_v1v2_assets.py --dry-run      # 只看会补哪些文件
    python3 scripts/migrate_v1v2_assets.py                # 只补缺失
    python3 scripts/migrate_v1v2_assets.py --force        # 静态文件强制覆盖
    python3 scripts/migrate_v1v2_assets.py --with-images  # 额外把图片复制到 api/v2/assets/images
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).parent))

from miroms.utils import FileUtils  # noqa: E402

# 参考仓库的数据目录（与 import_dev_week.py / import_sitelog.py 同风格）
SOURCE_ROOTS: Dict[str, Path] = {
	'nuxtmr': Path('/Users/hegeken/Desktop/Codes/NuxtMR/public/MRData/data'),
	'hyperos': Path('/Users/hegeken/Desktop/Codes/HyperOS.fans/public/data'),
}

# 目标目录：api/<版本>/<目录名>
TARGETS: Dict[str, str] = {
	'nuxtmr': 'v1',
	'hyperos': 'v2',
}

_EXPORT_BASE = Path(FileUtils.get_base_path()) / "data" / "api"

# 手写内容 / 废弃脚本的归档产物：本脚本播种，之后随仓库维护，不再自动生成
STATIC_FILES: Dict[str, List[str]] = {
	'nuxtmr': [
		'tools.json', 'thanks.json', 'devices.json', 'log.json',
		'stable.json', 'update.json', 'update_full.json', 'newrom.json',
	],
	'hyperos': [
		'updates.json', 'new-rom.json',
	],
}

# 机型目录：只在目标缺失时播种（exporter.py 会回填派生字段）
CATALOG_FILES: Dict[str, List[str]] = {
	'nuxtmr': ['devlist.json'],
	'hyperos': ['devices.json'],
}

# 需要整目录搬运的资源：(源相对路径, 目标相对路径)
# 默认不搬（规范位置是 data/images/，见模块 docstring），仅 --with-images 时启用
ASSET_TREES: Dict[str, List[Tuple[str, str]]] = {
	'hyperos': [('assets/images', 'assets/images')],
}


def copy_file(src: Path, dst: Path, force: bool, dry_run: bool) -> str:
	"""复制单个文件，返回动作名（copied / forced / skipped / missing）。"""
	if not src.exists():
		return 'missing'
	existed = dst.exists()
	if existed and not force:
		return 'skipped'
	if dry_run:
		return 'forced' if existed else 'copied'
	dst.parent.mkdir(parents=True, exist_ok=True)
	shutil.copy2(src, dst)
	return 'forced' if existed else 'copied'


def migrate(source: str, args: argparse.Namespace) -> None:
	version = TARGETS[source]
	src_root = SOURCE_ROOTS[source]
	dst_root = _EXPORT_BASE / version
	print(f'--- {source} -> api/{version} ---')

	stats: Dict[str, int] = {}

	def bump(action: str) -> None:
		stats[action] = stats.get(action, 0) + 1

	# 1) 静态接口文件
	for name in STATIC_FILES[source]:
		action = copy_file(src_root / name, dst_root / name, args.force, args.dry_run)
		bump(action)
		if action in ('copied', 'forced'):
			print(f'  {action:7} {name}')

	# 2) 机型目录（只在缺失时播种，--force 可强制回退到参考仓库版本）
	for name in CATALOG_FILES[source]:
		action = copy_file(src_root / name, dst_root / name, args.force, args.dry_run)
		bump(action)
		print(f'  {action:7} {name}（目录，随后由 exporter.py 回填派生字段）')

	# 3) 图片等资源目录（默认跳过：规范位置是 data/images/，仅 --with-images 时搬运）
	if args.with_images:
		for src_rel, dst_rel in ASSET_TREES.get(source, []):
			src_dir, dst_dir = src_root / src_rel, dst_root / dst_rel
			if not src_dir.is_dir():
				bump('missing')
				continue
			for item in sorted(src_dir.rglob('*')):
				if not item.is_file() or item.name == '.DS_Store':
					continue
				action = copy_file(item, dst_dir / item.relative_to(src_dir), False, args.dry_run)
				bump(action)
			print(f'  {dst_rel}: {sum(1 for _ in src_dir.rglob("*") if _.is_file())} 个文件（只补缺失）')

	# 4) 仅存于参考仓库的遗留机型（绝不覆盖库里导出的设备文件）
	dev_src = src_root / 'devices'
	dev_dst = dst_root / 'devices'
	legacy: List[str] = []
	if dev_src.is_dir():
		for item in sorted(dev_src.glob('*.json')):
			if (dev_dst / item.name).exists():
				continue
			if not args.dry_run:
				dev_dst.mkdir(parents=True, exist_ok=True)
				shutil.copy2(item, dev_dst / item.name)
			legacy.append(item.stem)
		if legacy:
			bump('copied')
	print(f'  遗留机型: 补 {len(legacy)} 个' + (f' -> {", ".join(legacy)}' if legacy else ''))

	print(f'  统计: ' + ', '.join(f'{k}={v}' for k, v in sorted(stats.items())) + '\n')


def main() -> None:
	parser = argparse.ArgumentParser(description='补齐 v1/v2 的静态文件、机型目录、图片与遗留机型')
	parser.add_argument('--source', choices=sorted(SOURCE_ROOTS), help='只处理某个站点（默认两个都处理）')
	parser.add_argument('--force', action='store_true', help='静态文件 / 目录强制覆盖（设备文件始终不覆盖）')
	parser.add_argument('--dry-run', action='store_true', help='只列出将补哪些文件，不写入')
	parser.add_argument('--with-images', action='store_true',
						help='额外把参考站点的图片复制到 api/v2/assets/images（默认跳过，规范位置是 data/images/）')
	args = parser.parse_args()

	sources = [args.source] if args.source else sorted(SOURCE_ROOTS)
	for source in sources:
		migrate(source, args)

	print('完成（--dry-run，未写入）' if args.dry_run else '完成')


if __name__ == '__main__':
	main()
