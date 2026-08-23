DROP TABLE IF EXISTS `branches`;
CREATE TABLE `branches` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `branch` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '分支类型：F=正式版、X=开发版',
  `name_zh` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '分支中文名称，如 中国大陆正式版',
  `name_en` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '分支英文名称，如 China Mainland Stable',
  `tag` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '分支标签，如 CnOO、MIXM',
  `code` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '分支代码后缀，如 _global、_in_global',
  `vercode` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '版本代码，用于匹配新设备分支',
  `carrier` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '运营商列表，JSON 数组',
  `region` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '区域代号：cn/global/in/eea 等',
  `zone` int DEFAULT NULL COMMENT '区域分区：1=中国、2=国际',
  `visibility` int DEFAULT NULL COMMENT '是否可见：1=可见、0=隐藏',
  `ep` int DEFAULT NULL COMMENT '是否政企版：1=是、0=否',
  PRIMARY KEY (`id`),
  KEY `idx_branches_vercode` (`vercode`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

--数据 示例：1,'F','中国大陆正式版','China Mainland Stable','CnOO',NULL,'CNXM','[\'\',\'chinatelecom\',\'chinamobile\',\'chinaunicom\']','cn',1,1,0
