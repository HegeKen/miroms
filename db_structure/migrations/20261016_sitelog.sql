-- 20261016_sitelog.sql
-- ---------------------------------------------------------------------------
-- 新增 sitelog 表：把 NuxtMR 与 HyperOS.fans 两个参考站点的手写站点日志
-- （sitelog.json）收进数据库，用 site 列区分站点，导出为 api/v1|v2/sitelog.json。
--
-- 本文件供「已有数据库」增量建表；全新初始化请直接执行 db_structure/sitelog.sql
-- （两者结构一致，本文件只多了 IF NOT EXISTS）。
--
-- 执行顺序：
--   1. 执行本文件建表（或在全新库执行 db_structure/sitelog.sql）
--   2. python3 data/scripts/import_sitelog.py --all           # 从两个参考仓库导入
--   3. python3 data/scripts/exporter.py                       # 重新导出 api/v1|v2/sitelog.json
--
-- 回滚：DROP TABLE sitelog;（数据源仍在两个参考仓库，可随时重新导入）
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `sitelog` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `site` varchar(32) COLLATE utf8mb4_bin NOT NULL COMMENT '站点标识：nuxtmr / hyperos.fans',
  `kind` varchar(16) COLLATE utf8mb4_bin NOT NULL DEFAULT 'entry' COMMENT '行类型：entry=日志条目 / meta=站点级元信息',
  `ver` varchar(64) COLLATE utf8mb4_bin NOT NULL DEFAULT '' COMMENT '站点版本号（meta 行为空串）',
  `icon` varchar(64) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '时间线图标（mdi-*），仅 hyperos.fans 使用',
  `log_date` date DEFAULT NULL COMMENT '该条日志的日期',
  `devices_zh` varchar(512) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '新增机型摘要（中文）',
  `devices_en` varchar(512) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '新增机型摘要（英文）',
  `logs` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin COMMENT '日志正文条目 JSON 数组 [{zh,en},...]',
  `icons` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin COMMENT '站点图标调色板 JSON 数组（仅 meta 行）',
  `sort_order` int NOT NULL DEFAULT 0 COMMENT '同站点内排序权重，越小越靠前',
  `insdate` date DEFAULT NULL COMMENT '记录录入日期',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sitelog_site_kind_ver_date` (`site`,`kind`,`ver`,`log_date`),
  KEY `idx_sitelog_site_kind_order` (`site`,`kind`,`sort_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;
