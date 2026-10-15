-- 20261016_logs_multilang.sql
-- ---------------------------------------------------------------------------
-- logs 表改为「同一日志的多语言版本共用一行」，roms 表 21 个 logs_xx 列
-- （logs_zh / logs_zh_tw / logs_en / logs_ja / ... / logs_bo）合并为单一
-- 语言中性的 logs 列；同时新增 dev_week 列标注开发版周数。
--
-- 本文件只包含 roms 表的 DDL 改动。logs 表的重建与存量数据迁移由
-- data/scripts/migrate_logs_multilang.py 完成（需要先把 roms 各语言日志解码后
-- 按位置重新分组写入新 logs 表，再执行下面的 DROP COLUMN）。
--
-- 完整的迁移顺序（脚本会自动按此顺序执行）：
--   1. 把旧 logs 表改名为 logs_legacy（保留旧数据，便于核对 / 回滚）
--   2. python3 data/scripts/migrate_logs_multilang.py
--        ├─ 建新 logs 表（含 21 个语言列，列集合见 scripts/miroms/constants.py）
--        ├─ 重新分组写入 logs
--        ├─ ALTER roms ADD COLUMN logs / dev_week
--        ├─ 逐行回写 roms.logs
--        └─ 执行本文件余下的 DROP CHECK / DROP COLUMN / ADD CONSTRAINT
--   3. 核对无误后：DROP TABLE logs_legacy;
--
-- 手工执行时请先确认 migrate_logs_multilang.py 已完成回写。
-- ---------------------------------------------------------------------------

-- 1) 删除旧的「一门语言一个 json_valid 检查」
ALTER TABLE `roms`
  DROP CHECK `roms_chk_1`,
  DROP CHECK `roms_chk_2`,
  DROP CHECK `roms_chk_3`,
  DROP CHECK `roms_chk_4`,
  DROP CHECK `roms_chk_5`,
  DROP CHECK `roms_chk_6`,
  DROP CHECK `roms_chk_7`,
  DROP CHECK `roms_chk_8`,
  DROP CHECK `roms_chk_9`,
  DROP CHECK `roms_chk_10`,
  DROP CHECK `roms_chk_11`,
  DROP CHECK `roms_chk_12`,
  DROP CHECK `roms_chk_13`,
  DROP CHECK `roms_chk_14`,
  DROP CHECK `roms_chk_15`,
  DROP CHECK `roms_chk_16`,
  DROP CHECK `roms_chk_17`,
  DROP CHECK `roms_chk_18`,
  DROP CHECK `roms_chk_19`,
  DROP CHECK `roms_chk_20`,
  DROP CHECK `roms_chk_21`;

-- 2) 新增单一日志列与开发版周数列（脚本中带 IF NOT EXISTS 判断）
ALTER TABLE `roms`
  ADD COLUMN `logs` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin
    COMMENT '更新日志（语言中性）的 logs 表 ID 引用结构（见 logs.sql）：[[模块ID,[条目ID,...]],...]；具体语言在 logs 表按列存放' AFTER `update_date`,
  ADD COLUMN `dev_week` int DEFAULT NULL
    COMMENT '开发版周数：该 ROM 属于哪一周的开发版（仅 branch=X 有意义，见 dev 表）' AFTER `logs`;

-- 3) 删除 21 个按语言的日志列
ALTER TABLE `roms`
  DROP COLUMN `logs_zh`,
  DROP COLUMN `logs_en`,
  DROP COLUMN `logs_zh_tw`,
  DROP COLUMN `logs_ug`,
  DROP COLUMN `logs_bo`,
  DROP COLUMN `logs_ja`,
  DROP COLUMN `logs_ko`,
  DROP COLUMN `logs_ru`,
  DROP COLUMN `logs_uk`,
  DROP COLUMN `logs_pl`,
  DROP COLUMN `logs_de`,
  DROP COLUMN `logs_fr`,
  DROP COLUMN `logs_it`,
  DROP COLUMN `logs_es`,
  DROP COLUMN `logs_pt`,
  DROP COLUMN `logs_tr`,
  DROP COLUMN `logs_in`,
  DROP COLUMN `logs_id`,
  DROP COLUMN `logs_vi`,
  DROP COLUMN `logs_th`,
  DROP COLUMN `logs_ar`;

-- 4) 新的 json_valid 检查 + 自增计数修正（自增取当前最大 id + 1）
ALTER TABLE `roms`
  ADD CONSTRAINT `roms_chk_1` CHECK (json_valid(`logs`));
-- ALTER TABLE `roms` AUTO_INCREMENT = <MAX(id)+1>;   -- 脚本自动计算
