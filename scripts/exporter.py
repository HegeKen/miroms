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

# 导出开发版（周更）公告与更新日志（供官网 /dev 页面按周展示）
print("\n--- 导出开发版周报 (v3/dev) ---")
try:
  dev_index = common.export_dev()
  print(f"开发版周报已生成：{dev_index['total']} 个周次（最近第 {dev_index['latest']} 周）")
except Exception as e:
  print(f"开发版周报生成失败: {e}", file=sys.stderr)

# 导出参考站点附属接口（api/v1 = NuxtMR、api/v2 = HyperOS.fans）
# 依赖上面的设备文件（机型目录要回填 android / miui / supports），必须放在其后。
print("\n--- 导出 v1 附属接口 (NuxtMR) ---")
try:
  v1_extras = common.export_v1_extras()
  print(f"v1 附属接口已生成：首页 {v1_extras['index'] and v1_extras['index']['week']} 周、"
        f"周更 {v1_extras['weeklyWeeks']} 个周次、站点日志 {'有' if v1_extras['sitelog'] else '无'}")
except Exception as e:
  print(f"v1 附属接口生成失败: {e}", file=sys.stderr)

print("\n--- 导出 v2 附属接口 (HyperOS.fans) ---")
try:
  v2_extras = common.export_v2_extras()
  print(f"v2 附属接口已生成：首页 {len((v2_extras['index'] or {}).get('recent', {}).get('roms', {}))} 台机型、"
        f"周更 {v2_extras['devWeeks']} 个周次、站点日志 {'有' if v2_extras['sitelog'] else '无'}")
except Exception as e:
  print(f"v2 附属接口生成失败: {e}", file=sys.stderr)

# 导出 hub 自身附属接口：站点日志（web / admin，按 git 记录导入）+ 工具下载
print("\n--- 导出 hub 附属接口 (v3: sitelog / tools) ---")
try:
  hub_extras = common.export_hub_extras()
  sites = (hub_extras['sitelog'] or {}).get('sites', {})
  tools = hub_extras['tools'] or {}
  print("hub 附属接口已生成：站点日志 "
        + '、'.join(f"{s} {v['latest']}({v['count']})" for s, v in sites.items())
        + f"；工具 {len(tools.get('tools', []))} 个")
except Exception as e:
  print(f"hub 附属接口生成失败: {e}", file=sys.stderr)

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