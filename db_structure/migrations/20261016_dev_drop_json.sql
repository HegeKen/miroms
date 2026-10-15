-- 20261016_dev_drop_json.sql
-- ---------------------------------------------------------------------------
-- dev 表瘦身：机型 / ROM 清单不再各存一份 JSON，改为复用 roms 表。
--
-- dev.devices（约 297 KB JSON）与 dev.roms（约 878 KB JSON）里的内容
-- （机型名、版本号、Android、发布日期、卡刷 / 线刷包文件名）在 devices / roms
-- 表中都已存在，其中「某一周有哪些 ROM」由 roms.dev_week 表达：
--
--     SELECT * FROM roms WHERE dev_week = <week> AND zone = <zone>
--
-- 因此直接删掉这两列；导出与后台绑定页都按上面的关系现算。
--
-- 执行顺序：
--   1. python3 data/scripts/import_dev_week.py --all       # 先把 roms.dev_week 绑全（按周版本号）
--   2. 执行本文件（或 import_dev_week.py 会自动检查列是否存在）
--   3. python3 data/scripts/export_dev…（exporter.py）     # 重新导出 v3/dev/**
--
-- 回滚：本迁移只删列，重新导入即可恢复（数据源仍在参考仓库）。
-- ---------------------------------------------------------------------------

ALTER TABLE `dev`
  DROP COLUMN `devices`,
  DROP COLUMN `roms`;

-- 依据 roms.dev_week + zone 反查某一周的机型与 ROM（导出 / 后台同款查询）
-- SELECT r.device, r.version, r.android, r.release_date, r.recovery, r.fastboot
--   FROM roms r
--   JOIN dev d ON d.week = r.dev_week AND d.zone = r.zone
--  WHERE d.week = 652 AND d.region = 'cn';
