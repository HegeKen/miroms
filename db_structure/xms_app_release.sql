DROP TABLE IF EXISTS `xms_app_release`;
CREATE TABLE `xms_app_release` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `pkg` varchar(128) COLLATE utf8mb4_bin NOT NULL DEFAULT '' COMMENT '应用包名，如 com.miui.securitycenter；空串表示该日志模块接口没给包名',
  `pkg_ver` varchar(64) COLLATE utf8mb4_bin NOT NULL DEFAULT '' COMMENT '应用版本号（接口 versionCode，如 40011275）',
  `name` varchar(128) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '应用 / 日志模块名（简体中文），如 手机管家',
  `name_en` varchar(128) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '应用 / 日志模块名（英文），如 Security',
  `names` longtext COLLATE utf8mb4_bin COMMENT '应用 / 模块名的多语言 JSON：{"zh":"手机管家","en":"Security","ja":"セキュリティ",...}（同一包名统一取一份）',
  `apk_name` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '安装包名称（接口 name，如「平板管家-CN-OS3」）',
  `file_name` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'APK 文件名（接口 fileName）',
  `size` bigint DEFAULT NULL COMMENT 'APK 体积（字节，接口 size）',
  `md5` char(32) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'APK MD5（接口 md5）',
  `sha256` char(64) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'APK SHA-256（接口 sha256）',
  `logs` longtext COLLATE utf8mb4_bin COMMENT '该应用的更新日志条目 JSON 数组：[{"zh":"...","en":"..."}, ...]（缺失语种省略对应键）',
  `release_date` date DEFAULT NULL COMMENT '安装包真实发布 / 上传日期：下载链接 HTTP 响应头 Last-Modified（北京时间）',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_release_pkg_ver` (`pkg`,`pkg_ver`),
  KEY `idx_release_pkg` (`pkg`),
  KEY `idx_release_md5` (`md5`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

-- 说明：
-- 「APK 发布物」表 —— 同一个应用版本（pkg + pkg_ver）只存一行元数据。
-- 一次 XMS 推送覆盖哪些应用，由 xms_app（推送 ↔ 发布物关联表）记录，
-- 因此同一个 APK 被多次推送引用时，name / apk_name / md5 / logs 等只存一份，
-- 不再在 xms_app 里逐行重复（旧结构下同一 pkg_ver 最多重复 36 次以上）。
--
-- 与 xms_app 的关系：xms_app.release_id → xms_app_release.id，多对一。
-- pkg_ver 由接口 versionCode 决定；实测同一 (pkg, pkg_ver) 恒对应同一 md5 / file_name /
-- apk_name / logs / release_date，且只属于一个 XMS 版本，故 (pkg, pkg_ver) 可作为本表唯一键。
--
-- 写入与消费：
--   - 写入：scripts/miroms/xms.py（upsert 发布物 + 写关联）
--   - 导出：scripts/miroms/exporters.py export_xms()（xms_app JOIN xms_app_release）
--   - 管理后台：app/admin（xms_app_release 纳入通用表 CRUD 白名单）
--
-- 数据示例：
--   1,'com.android.deskclock','1306003100','时钟','Clock',
--     '{"zh":"时钟",...}','deskclock-...apk',18292955,'ab227ddee8...','...sha256...',
--     '[{"zh":"..."}]','2026-11-04'
