DROP TABLE IF EXISTS `devices`;
CREATE TABLE `devices` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `device` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '设备代号，如 marble、leedsa',
  `devtag` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '设备内部标识，如 MA、Mioneplus',
  `code` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '设备代码，如 marble_global、leedsa_in_global',
  `tag` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'ROM 标签，如 CnOO、MIXM、INXM',
  `region` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '区域代号：cn/global/in/eea 等',
  `devcode` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '设备版本号后6位',
  `carrier` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '运营商列表，JSON 数组',
  `branchcode` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '分支代码，原始文件名中的分支标识',
  `full_brands` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '品牌全称，JSON 数组，如 ["Xiaomi","Redmi"]',
  `brands` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '品牌简称，逗号分隔，如 "Xiaomi, Redmi"',
  `full_names` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '设备全名，JSON 对象，如 {"zh":"小米14","en":"Xiaomi 14"}',
  `names` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '设备简称，JSON 对象',
  `xiaomi` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '小米品牌下的设备名，JSON 对象',
  `redmi` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'Redmi品牌下的设备名，JSON 对象',
  `poco` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'POCO品牌下的设备名，JSON 对象',
  `image` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '设备图片路径',
  `launch_date` date DEFAULT NULL COMMENT '设备发布日期',
  PRIMARY KEY (`id`),
  KEY `idx_devices_device` (`device`),
  KEY `idx_devices_code` (`code`),
  KEY `idx_devices_devtag` (`devtag`),
  KEY `idx_devices_branchcode` (`branchcode`)
) ENGINE=InnoDB AUTO_INCREMENT=1997 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

--数据 示例：1,'mione_plus','MA','mione_plus','CnOO','cn',NULL,'[\'\',\'chinatelecom\',\'chinamobile\',\'chinaunicom\']','Mioneplus','[\"Xiaomi\"]','[\"Xiaomi\"]','{\"zh\": \"小米手机1/1S\",\"en\":\"MI 1/1S\"}','{\"zh\": \"小米手机1/1S\",\"en\":\"MI 1/1S\"}','{\"zh\": \"小米手机1/1S\",\"en\":\"MI 1/1S\"}',NULL,NULL,NULL,'2011-08-16'
