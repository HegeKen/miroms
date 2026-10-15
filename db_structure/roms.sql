DROP TABLE IF EXISTS `roms`;
CREATE TABLE `roms` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `device` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '设备代号，如 taiko、leedsa',
  `code` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '设备代码，如 taiko_global',
  `type` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '系统类型：MIUI / HyperOS',
  `bigver` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '大版本号，如 HyperOS 3、MIUI 14',
  `region` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '区域代号：cn/global/in/eea 等',
  `tag` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'ROM 标签，如 CnOO、MIXM',
  `branch` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '分支类型：F=正式版、X=开发版',
  `zone` int DEFAULT NULL COMMENT '区域分区：1=中国、2=国际',
  `version` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '完整版本号，如 OS3.0.303.0.WOVCNXM',
  `android` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'Android 版本号，如 16.0、14.0',
  `beta_date` date DEFAULT NULL COMMENT 'Beta/内测发布日期',
  `release_date` date DEFAULT NULL COMMENT '正式发布日期',
  `public_date` date DEFAULT NULL COMMENT '公开发布日期',
  `recovery` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'Recovery 包文件名',
  `fastboot` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'Fastboot 包文件名',
  `ctelecom` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '中国电信定制包文件名',
  `cmobile` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '中国移动定制包文件名',
  `cunicom` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '中国联通定制包文件名',
  `others` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '其他渠道包文件名',
  `insdate` date DEFAULT NULL COMMENT '记录录入日期',
  `update_date` bigint DEFAULT NULL COMMENT '记录更新时间戳',
  `logs` longtext CHARACTER SET utf8mb4 COLLATE utf8mb4_bin COMMENT '更新日志（语言中性）的 logs 表 ID 引用结构（见 logs.sql）：[[模块ID,[条目ID,...]],...]；具体语言在 logs 表按列存放',
  `dev_week` int DEFAULT NULL COMMENT '开发版周数：该 ROM 属于哪一周的开发版（仅 branch=X 有意义，见 dev 表）',
  `aspatch` date DEFAULT NULL COMMENT '安卓安全补丁日期',
  PRIMARY KEY (`id`) USING BTREE,
  KEY `idx_roms_device` (`device`),
  KEY `idx_roms_code` (`code`),
  KEY `idx_roms_device_type` (`device`,`type`),
  KEY `idx_roms_beta_date` (`beta_date`),
  KEY `idx_roms_release_date` (`release_date`),
  CONSTRAINT `roms_chk_1` CHECK (json_valid(`logs`))
) ENGINE=InnoDB AUTO_INCREMENT=1 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

-- 数据示例（logs 已改为单一的语言中性 ID 引用结构，各语言原文在 logs 表按列存放）：
-- 52119,'taiko','taiko','HyperOS','HyperOS 3','cn','CnOO','F',1,'OS3.0.303.0.WOVCNXM','16.0',
--   '2026-04-22','2026-04-22','2026-04-27','taiko-ota_full-....zip','taiko_images_....tgz',
--   'taiko_images_..._chinatelecom_....tgz',NULL,NULL,NULL,'2026-04-22',NULL,
--   '[[1,[2,3]],[32,[45,48]]]',652,'2026-03-01'
-- 其中 logs.dev_week=652 表示该开发版属于第 652 周（dev 表 week=652 + region 定位公告）。
