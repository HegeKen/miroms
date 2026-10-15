DROP TABLE IF EXISTS `dev`;
CREATE TABLE `dev` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `week` int NOT NULL COMMENT '开发版周数（如 652）',
  `region` varchar(16) COLLATE utf8mb4_bin NOT NULL DEFAULT 'cn' COMMENT '开发版区域：cn=大陆版 / global=国际版（同一周数可同时存在两条）',
  `zone` tinyint DEFAULT NULL COMMENT '区域分区：1=中国、2=国际',
  `bigver` varchar(64) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '大版本，如 HyperOS 1、MIUI 13',
  `versions` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '该周开发版版本号，如 OS1.0.24.7.28.DEV、21.6.16（同时是绑定 roms.dev_week 的依据）',
  `title_zh` varchar(512) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '公告标题（简体中文）',
  `title_en` varchar(512) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '公告标题（英文）',
  `post_id` varchar(64) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '小米社区公告 ID',
  `update_time` datetime DEFAULT NULL COMMENT '公告更新时间',
  `release_date` date DEFAULT NULL COMMENT '发布日期',
  `description` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin COMMENT '公告正文（JSON 数组 [{zh,en},...]）',
  `attention` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin COMMENT '升级说明 / 注意事项（JSON 数组 [{zh,en},...]）',
  `suspended` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin COMMENT '停版 / 推迟发布机型（JSON 数组，源数据自带，无法从其他表推导）',
  `logs` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin COMMENT '更新日志的 logs 表 ID 引用结构（语言中性，同 roms.logs，见 logs.sql）',
  `source` varchar(32) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '数据来源：hyperos.fans / nuxtmr / miuiroms',
  `show` tinyint NOT NULL DEFAULT '1' COMMENT '是否展示：1=展示、0=隐藏',
  `insdate` date DEFAULT NULL COMMENT '记录录入日期',
  `update_date` bigint DEFAULT NULL COMMENT '记录更新时间戳',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_dev_week_region` (`week`,`region`),
  KEY `idx_dev_week` (`week`),
  KEY `idx_dev_region` (`region`),
  KEY `idx_dev_versions` (`versions`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- 说明：
-- 开发版分大陆版（region=cn，zone=1）与国际版（region=global，zone=2），
-- 同一周数会是两条记录（各自有独立的公告、日志与机型列表）。
--
-- 机型 / ROM 清单**不再单独存 JSON**：roms 表已有 `dev_week` 字段，
-- 「某一周有哪些机型」= `SELECT * FROM roms WHERE dev_week = <week> AND zone = <zone>`，
-- 机型名走 devices 表（full_names / names），版本号 / Android / 发布日期 / 卡刷线刷包
-- 全部读 roms 本身，因此 dev 表只保留公告与日志这类真正独有的数据。
-- 导出（export_dev）与后台（/dev-bind 绑定页）都按这个关系现算。
--
-- 数据示例：
--   652,'cn',1,'HyperOS 1','OS1.0.24.7.28.DEV','开发版第652周发布公告（小米澎湃OS开发版多机型推送）',
--   'DEV for week 652 (HyperOS DEV released for various devices)','47119859','2024-08-02 20:15:52','2024-08-02',
--   '[{"zh":"...","en":"..."}]','[{"zh":"升级前请您务必备份好重要数据","en":"..."}]','[]',
--   '[[1,[2,3],3],[4,[5],3]]','hyperos.fans',1,'2026-10-16',NULL
