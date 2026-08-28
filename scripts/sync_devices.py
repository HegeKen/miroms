"""
从数据库同步设备列表到 miroms/data.py 源文件
- fullDevices: 所有在 roms 表中出现的设备
- currentStable: 最近三年内有 ROM 记录的设备（排除 unreleased）
- flags: devices 表中 code/device 和 branchcode/device 的去重合集
"""
import re
import common
from pathlib import Path

DATA_PY = str(Path(__file__).parent / 'miroms' / 'data.py')


def format_list(items, indent='\t'):
    """将列表格式化为每行约120字符的Python列表字符串"""
    lines = []
    line = ''
    for item in sorted(items):
        entry = f"'{item}', "
        if line and len(line) + len(entry) > 120:
            lines.append(indent + line.rstrip(', '))
            line = ''
        line += entry
    if line:
        lines.append(indent + line.rstrip(', '))
    return '[\n' + ',\n'.join(lines) + '\n]'


def replace_list_var(source, var_name, new_value):
    """替换源码中列表变量的值"""
    pattern = rf'({var_name}\s*=\s*)\[.*?\]'
    new_source, count = re.subn(pattern, rf'\g<1>{new_value}', source, count=1, flags=re.DOTALL)
    if count == 0:
        print(f"  ⚠ 未找到 {var_name} 定义，跳过")
        return source
    return new_source


def replace_dict_var(source, var_name, new_value):
    """替换源码中字典变量的值"""
    pattern = rf'({var_name}\s*=\s*)\{{.*?\}}'
    new_source, count = re.subn(pattern, rf'\g<1>{new_value}', source, count=1, flags=re.DOTALL)
    if count == 0:
        print(f"  ⚠ 未找到 {var_name} 定义，跳过")
        return source
    return new_source


def format_flags(flags_dict, indent='\t'):
    """将 flags 字典格式化为Python字典字符串，每行一个键值对"""
    lines = []
    for key in sorted(flags_dict.keys()):
        value = flags_dict[key]
        lines.append(f"{indent}'{key}': '{value}',")
    return '{\n' + '\n'.join(lines) + '\n}'


# ==================== 更新 fullDevices ====================
sql = "SELECT DISTINCT device FROM roms WHERE device IS NOT NULL AND device != '' ORDER BY device LIMIT 5000"
result = common.DatabaseManager.execute(sql, fetch_one=False)

if result:
    new_devices = [row[0] for row in result if row and row[0]]
    print(f"✓ 查询到 {len(new_devices)} 个设备")
else:
    new_devices = []
    print("✗ 未查询到任何设备")

# ==================== 更新 currentStable ====================
stable_sql = """
    SELECT device, MAX(COALESCE(beta_date, release_date)) as latest_date
    FROM roms
    WHERE beta_date IS NOT NULL OR release_date IS NOT NULL
    GROUP BY device
    HAVING latest_date >= DATE_SUB(CURDATE(), INTERVAL 3 YEAR)
    ORDER BY device
"""
stable_result = common.DatabaseManager.execute(stable_sql, fetch_one=False)

if stable_result:
    new_stable = [row[0] for row in stable_result if row and row[0] and row[0] not in common.unreleased]
    print(f"✓ 查询到 {len(new_stable)} 个稳定版设备")
else:
    new_stable = []
    print("✗ 未查询到任何稳定版设备")

# ==================== 更新 flags ====================
# 查询 devices 表中 code/device 和 branchcode/device 的去重合集
flags_sql = """
    SELECT code, device FROM devices WHERE code IS NOT NULL AND code != '' AND device IS NOT NULL AND device != ''
    UNION
    SELECT branchcode, device FROM devices WHERE branchcode IS NOT NULL AND branchcode != '' AND device IS NOT NULL AND device != ''
"""
flags_result = common.DatabaseManager.execute(flags_sql, fetch_one=False)

new_flags = {}
if flags_result:
    for row in flags_result:
        if row and row[0] and row[1]:
            key = row[0]
            value = row[1]
            # 添加原始键值对
            new_flags[key] = value
            # 添加大写键值对（与现有 flags 风格一致）
            upper_key = key.upper()
            if upper_key != key:
                new_flags[upper_key] = value
    print(f"✓ 查询到 {len(new_flags)} 个 flags 条目")
else:
    print("✗ 未查询到任何 flags 数据")

# ==================== 诊断：检测异常设备记录（None / NULL / 空 / 'None' 字符串） ====================
# 这些异常值会被带入 fullDevices/currentStable，进而导致 exporter 报"设备 'None' 不存在"
print("--- 诊断：检测异常设备记录 ---")
for table in ('roms', 'devices'):
    diag_sql = f"""
        SELECT id, device, code FROM {table}
        WHERE device IS NULL OR device = '' OR device = 'None'
        ORDER BY id
    """
    diag_result = common.DatabaseManager.execute(diag_sql, fetch_one=False)
    if diag_result:
        for row in diag_result:
            print(f"  ⚠ {table} 表异常设备记录 id={row[0]}, device={row[1]!r}, code={row[2]!r}")
    else:
        print(f"  ✓ {table} 表无异常设备记录")

# ==================== 写入 miroms/data.py 源文件 ====================
with open(DATA_PY, 'r', encoding='utf-8') as f:
    source = f.read()

source = replace_list_var(source, 'fullDevices', format_list(new_devices))
source = replace_list_var(source, 'currentStable', format_list(new_stable, indent='\t\t'))
source = replace_dict_var(source, 'flags', format_flags(new_flags))

with open(DATA_PY, 'w', encoding='utf-8') as f:
    f.write(source)

print(f"✓ miroms/data.py 已更新")
