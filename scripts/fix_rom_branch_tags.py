#!/usr/bin/env python3
"""修复 roms.tag 误填 branches.vercode 导致的 v2/v3 设备导出遗漏。

安全判定：ROM 的 device + code 必须能对应 devices 记录，且当前 roms.tag
等于 branches.vercode、devices.tag 等于同一 branches.tag。目标不唯一时跳过。

默认仅预览，不写数据库：
  python3 data/scripts/fix_rom_branch_tags.py
  python3 data/scripts/fix_rom_branch_tags.py --device madrid

实际修复（自动备份旧值）：
  python3 data/scripts/fix_rom_branch_tags.py --apply

修复并重新生成受影响机型的 v2/v3 设备 JSON：
  python3 data/scripts/fix_rom_branch_tags.py --apply --export
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from miroms.database import DatabaseManager


def load_plan(device=None):
    """返回 (可唯一修复的记录, 目标分支有歧义的记录)。"""
    sql = """
        SELECT r.id, r.device, r.code, r.tag, r.version, d.tag AS expected_tag
        FROM roms r
        JOIN devices d ON d.device = r.device AND d.code = r.code
        JOIN branches b ON b.vercode = r.tag AND b.tag = d.tag
        WHERE r.type IN ('MIUI', 'HyperOS') AND r.tag <> d.tag
    """
    params = []
    if device:
        sql += " AND r.device = %s"
        params.append(device)
    sql += " ORDER BY r.id"

    grouped = {}
    for row in DatabaseManager.query_all(sql, params=params) or []:
        rom_id, rom_device, code, current_tag, version, expected_tag = row
        item = grouped.setdefault(int(rom_id), {
            'id': int(rom_id),
            'device': rom_device,
            'code': code,
            'version': version,
            'current_tag': current_tag,
            'expected_tags': set(),
        })
        item['expected_tags'].add(expected_tag)

    candidates = []
    ambiguous = []
    for item in grouped.values():
        expected_tags = sorted(item.pop('expected_tags'))
        if len(expected_tags) == 1:
            item['new_tag'] = expected_tags[0]
            candidates.append(item)
        else:
            item['expected_tags'] = expected_tags
            ambiguous.append(item)

    candidates.sort(key=lambda item: item['id'])
    ambiguous.sort(key=lambda item: item['id'])
    return candidates, ambiguous


def print_plan(candidates, ambiguous):
    for item in candidates:
        print(
            f"#{item['id']} {item['device']} {item['version']} | "
            f"{item['code']} | {item['current_tag']} -> {item['new_tag']}"
        )

    for item in ambiguous:
        targets = ', '.join(item['expected_tags'])
        print(
            f"跳过 #{item['id']} {item['device']} {item['version']}："
            f"目标分支不唯一 ({targets})",
            file=sys.stderr,
        )

    devices = sorted({item['device'] for item in candidates})
    print(f"\n可修复 {len(candidates)} 条 ROM，涉及 {len(devices)} 台机型")
    if devices:
        print('机型：' + ', '.join(devices))
    if ambiguous:
        print(f"另有 {len(ambiguous)} 条目标不唯一，未纳入自动修复", file=sys.stderr)


def backup_plan(candidates):
    backup_dir = Path(__file__).resolve().parents[2] / '.backup'
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = backup_dir / f'rom_branch_tags_{stamp}.json'
    payload = {
        'created_at': datetime.now().isoformat(timespec='seconds'),
        'table': 'roms',
        'field': 'tag',
        'rows': candidates,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def apply_plan(candidates):
    """在一个事务内更新，并通过 id + 旧 tag 防止覆盖并发修改。"""
    with DatabaseManager.transaction() as connection:
        with connection.cursor() as cursor:
            for item in candidates:
                affected = cursor.execute(
                    'UPDATE roms SET tag = %s WHERE id = %s AND tag = %s',
                    (item['new_tag'], item['id'], item['current_tag']),
                )
                if affected != 1:
                    raise RuntimeError(
                        f"ROM #{item['id']} 更新失败：记录不存在或 tag 已被其他进程修改"
                    )


def export_devices(devices):
    from miroms.exporters import exportV2, exportV3

    for device in devices:
        v2_result = exportV2(device)
        v3_result = exportV3(device)
        if v2_result is None and v3_result is None:
            print(f'- 跳过 {device}：导出器标记为未发布或不适用')
        else:
            print(f'✓ 已重新导出 {device} 的 v2/v3 设备 JSON')


def main():
    parser = argparse.ArgumentParser(
        description='修复 roms.tag / branches.vercode 混用（默认 dry-run）'
    )
    parser.add_argument('--device', help='只处理指定机型代号，例如 madrid')
    parser.add_argument('--apply', action='store_true', help='实际写库；默认仅预览')
    parser.add_argument('--export', action='store_true', help='写库后重新导出受影响机型的 v2/v3 JSON')
    args = parser.parse_args()

    if args.export and not args.apply:
        parser.error('--export 必须与 --apply 一起使用')

    candidates, ambiguous = load_plan(args.device)
    print_plan(candidates, ambiguous)
    if not candidates:
        print('没有可自动修复的记录。')
        return 0

    if not args.apply:
        scope = f' --device {args.device}' if args.device else ''
        print(f"\ndry-run 结束，未写库。确认后执行：")
        print(f'python3 data/scripts/fix_rom_branch_tags.py{scope} --apply --export')
        return 0

    backup = backup_plan(candidates)
    print(f'\n旧值备份：{backup}')
    try:
        apply_plan(candidates)
    except Exception as exc:
        print(f'✖ 写库失败，事务已回滚：{exc}', file=sys.stderr)
        return 1

    remaining, _ = load_plan(args.device)
    planned_ids = {item['id'] for item in candidates}
    not_fixed = sorted(planned_ids & {item['id'] for item in remaining})
    if not_fixed:
        print(f'✖ 复检仍有未修复记录：{not_fixed}', file=sys.stderr)
        return 1
    print(f'✓ 已修复并复检 {len(candidates)} 条 ROM 的 tag')

    if args.export:
        try:
            export_devices(sorted({item['device'] for item in candidates}))
        except Exception as exc:
            print(f'✖ 数据库已修复，但导出未完整完成：{exc}', file=sys.stderr)
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
