import common
import subprocess
import sys
from pathlib import Path

for device in common.fullDevices:
  common.exportV1(device)
  common.exportV2(device)
  common.exportV3(device)

# 导出设备系列排序索引（供前端 / generate-index 消费）
print("\n--- 导出设备系列排序 (series.json) ---")
try:
  common.export_series_index()
  print("系列排序索引已生成")
except Exception as e:
  print(f"系列排序索引生成失败: {e}", file=sys.stderr)

# 导出数据库真实统计（供官网首页统计卡片，口径与后台一致）
print("\n--- 导出统计 (statistics.json) ---")
try:
  common.export_statistics()
  print("统计已生成")
except Exception as e:
  print(f"统计生成失败: {e}", file=sys.stderr)

# 导出完成后自动同步 index.json
print("\n--- 同步 index.json ---")
index_script = Path(__file__).resolve().parent.parent.parent / 'app' / 'web' / 'scripts' / 'generate-index.mjs'
if index_script.exists():
  result = subprocess.run(
    ['node', str(index_script)],
    capture_output=True, text=True
  )
  print(result.stdout)
  if result.returncode != 0:
    print(f"index 生成失败: {result.stderr}", file=sys.stderr)
else:
  print(f"index 脚本不存在: {index_script}", file=sys.stderr)