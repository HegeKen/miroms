-- 设备系列表：按品牌内产品系列归组，用于理清机型（设备代号）在同一品牌内的展示/排序顺序。
-- 解决「同一台机器在同一个品牌下有多个马甲名称（如 Redmi Note 9S / Redmi Note 10 Lite）导致排序混乱」的问题。
-- 每个 series 属于一个品牌（xiaomi/redmi/poco），device_ids 存该系列内设备的基准行 id（devices.id）有序数组，
-- 数组顺序即该系列内机型的展示顺序；series 之间按 sort_order 排序。

DROP TABLE IF EXISTS `series`;
CREATE TABLE `series` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `brand` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '系列所属品牌：xiaomi/redmi/poco',
  `name_zh` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '系列中文名，如 红米 K 系列、POCO F 系列',
  `name_en` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '系列英文名，如 Redmi K Series、POCO F Series',
  `device_ids` longtext COLLATE utf8mb4_bin COMMENT '设备 id 有序数组（devices.id），数组顺序即该系列内机型展示顺序，如 [3, 8, 12]',
  `sort_order` int DEFAULT 0 COMMENT '系列排序权重，越小优先级越高（同品牌内）',
  PRIMARY KEY (`id`),
  KEY `idx_series_brand` (`brand`),
  CONSTRAINT `series_chk_1` CHECK (json_valid(`device_ids`))
) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

-- 数据示例：
-- 1,'xiaomi','小米数字系列','Xiaomi Digital Series','[3, 8, 12]',0
-- 2,'redmi','红米 K 系列','Redmi K Series','[5, 15]',0
-- 3,'poco','POCO F 系列','POCO F Series','[20]',0
