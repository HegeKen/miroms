DROP TABLE IF EXISTS `xms_app`;
CREATE TABLE `xms_app` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `xms_id` bigint NOT NULL COMMENT '所属 XMS 推送（xms.id）',
  `pkg` varchar(128) COLLATE utf8mb4_bin NOT NULL DEFAULT '' COMMENT '应用包名，如 com.miui.securitycenter；空串表示该日志模块接口没给包名',
  `name` varchar(128) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '应用 / 日志模块名（简体中文），如 手机管家',
  `name_en` varchar(128) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '应用 / 日志模块名（英文），如 Security',
  `names` longtext COLLATE utf8mb4_bin COMMENT '应用 / 模块名的多语言 JSON：{"zh":"手机管家","en":"Security","ja":"セキュリティ",...}（同一包名统一取一份）',
  `pkg_ver` varchar(64) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '应用版本号（接口 versionCode，如 40011275）',
  `apk_name` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '安装包名称（接口 name，如「平板管家-CN-OS3」）',
  `file_name` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'APK 文件名（接口 fileName）',
  `size` bigint DEFAULT NULL COMMENT 'APK 体积（字节，接口 size）',
  `md5` char(32) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'APK MD5（接口 md5）',
  `sha256` char(64) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'APK SHA-256（接口 sha256）',
  `logs` longtext COLLATE utf8mb4_bin COMMENT '该应用的更新日志条目 JSON 数组：[{"zh":"...","en":"..."}, ...]（缺失语种省略对应键）',
  `release_date` date DEFAULT NULL COMMENT '安装包真实发布 / 上传日期：下载链接 HTTP 响应头 Last-Modified（北京时间）',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_xms_app` (`xms_id`,`pkg`),
  KEY `idx_xms_app_pkg` (`pkg`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

-- 说明：
-- 一次 XMS 推送覆盖的每个应用一行（接口 xmsUpdateInfo.pkgs），
-- 更新日志来自 xmsUpdateInfo.changeLog（请求带 xv=<lstVer> 时返回）：
--   changeLog 以「模块名」为键，条目里可能带 package / versionCode / txt。
-- 中文与英文日志由两次请求（l=zh_CN / l=en_US）分别取回，按包名 + 条目序号对齐，
-- 数量不一致时只保留中文（避免错配）。
--
-- 没有包名的日志模块（如「小米超级岛」这类说明性条目）不进本表，统一存到 xms.changelog，
-- 避免用模块名当键、每次抓取重复录入。
--
-- 应用名按包名统一：同一个 pkg 在所有推送里共用一份 name / name_en / names，
-- 译文优先取 logs 表 type='module' 的同名模块（官方多语言）。
--
-- 数据示例：
--   1,1,'com.miui.securitycenter','手机管家','Security','40011275',
--     '[{"zh":"优化 “游戏工具箱”界面焕新，动画效果升级，实时帧率更直观","en":"Optimization: ..."}]'
