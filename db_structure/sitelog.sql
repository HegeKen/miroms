DROP TABLE IF EXISTS `sitelog`;
CREATE TABLE `sitelog` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `site` varchar(32) COLLATE utf8mb4_bin NOT NULL COMMENT '站点标识：nuxtmr（MIUI 站，导出到 api/v1）/ hyperos.fans（HyperOS 站，导出到 api/v2）/ hub.web、hub.admin（hub 官网前端与管理后台，导出到 api/v3）',
  `kind` varchar(16) COLLATE utf8mb4_bin NOT NULL DEFAULT 'entry' COMMENT '行类型：entry=一条站点日志 / meta=站点级元信息（图标调色板等）',
  `ver` varchar(64) COLLATE utf8mb4_bin NOT NULL DEFAULT '' COMMENT '站点版本号：如 V1.5.0 / V0.9.6（meta 行为空串）',
  `icon` varchar(64) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '时间线图标（mdi-*），仅 hyperos.fans 使用',
  `log_date` date DEFAULT NULL COMMENT '该条日志的日期',
  `devices_zh` varchar(512) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '本次新增机型摘要（中文），对应 nuxtmr sitelog 条目的顶层 zh-cn',
  `devices_en` varchar(512) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '本次新增机型摘要（英文），对应 nuxtmr sitelog 条目的顶层 en-us',
  `logs` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin COMMENT '日志正文条目 JSON 数组：[{"zh":"...","en":"..."}, ...]（导出时按站点映射为 zh-cn/en-us 或 zh/en）',
  `icons` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin COMMENT '站点图标调色板 JSON 数组，如 ["mdi-web", ...]（仅 meta 行，hyperos.fans 前端当前未使用，保留源站数据）',
  `sort_order` int NOT NULL DEFAULT 0 COMMENT '同站点内排序权重，越小越靠前（与源文件顺序一致，导出按此升序）',
  `insdate` date DEFAULT NULL COMMENT '记录录入日期',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_sitelog_site_kind_ver_date` (`site`,`kind`,`ver`,`log_date`),
  KEY `idx_sitelog_site_kind_order` (`site`,`kind`,`sort_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

-- 说明：
-- 站点日志原先分散在两个参考仓库的手写 JSON 里，且两边结构不同：
--   NuxtMR/public/MRData/data/sitelog.json       -> {"log":[{sudate,ver,zh-cn,en-us,log:[{zh-cn,en-us}]}]}
--   HyperOS.fans/public/data/sitelog.json        -> {"icons":[mdi-*...],"logs":[{siteVer,icon,date,log:[{zh,en}]}]}
-- 现统一存本表，用 `site` 区分站点，导出时各自还原为原来的结构（见 scripts/miroms/exporters.py 的 export_sitelog）：
--   site='nuxtmr'       -> api/v1/sitelog.json
--   site='hyperos.fans' -> api/v2/sitelog.json（meta 行提供顶层 icons 调色板）
--
-- 站内版本号允许重复（nuxtmr 有两条 V0.5.5-SNAPSHOT、两条 V0.3.8-SNAPSHOT），
-- 因此唯一键带上 log_date。
--
-- 数据示例：
--   1,'nuxtmr','entry','V1.5.0',NULL,'2024-02-18','','',
--     '[{"zh":"升级Nuxt底层至Nuxt3","en":"Updating Nuxt to Nuxt3"}]',NULL,0,'2026-10-16'
--   2,'hyperos.fans','meta','',NULL,NULL,NULL,NULL,NULL,
--     '["mdi-bug-check","mdi-web","mdi-plus-box","mdi-checkbox-marked-circle-outline"]',0,'2026-10-16'
--   3,'hyperos.fans','entry','V0.9.6','mdi-plus-box','2026-09-23',NULL,NULL,
--     '[{"zh":"新增机型：小米 18 Pro 系列 、 小米平板 9 系列","en":"New Devices: Xiaomi 18 Pro Series, Xiaomi Pad 9 Series"}]',
--     NULL,0,'2026-10-16'
