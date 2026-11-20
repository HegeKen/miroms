DROP TABLE IF EXISTS `xms_app`;
CREATE TABLE `xms_app` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `xms_id` bigint NOT NULL COMMENT '所属 XMS 推送（xms.id）',
  `release_id` bigint NOT NULL COMMENT '所属 APK 发布物（xms_app_release.id）',
  `pkg` varchar(128) COLLATE utf8mb4_bin NOT NULL DEFAULT '' COMMENT '应用包名（冗余，恒等于 xms_app_release.pkg）：便于按推送查询与维持唯一约束',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_xms_app_xms_pkg` (`xms_id`,`pkg`),
  UNIQUE KEY `uq_xms_app_xms_release` (`xms_id`,`release_id`),
  KEY `idx_xms_app_release` (`release_id`),
  KEY `idx_xms_app_pkg` (`pkg`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

-- 说明：
-- 「推送 ↔ APK 发布物」关联表 —— 一次 XMS 推送覆盖的每个应用一行。
-- APK 的全部元数据（name / apk_name / md5 / logs / release_date 等）已抽到
-- xms_app_release，本表只保留归属关系，避免同一应用版本被多次推送时重复存储。
--
-- 保留 pkg 列（冗余）的原因：
--   1. 数据库级唯一约束 uq_xms_app_xms_pkg 保证「同一推送内一个包名只出现一次」；
--   2. 按推送列出应用时可直接 SELECT * FROM xms_app WHERE xms_id=?，无需每次 JOIN；
--   3. 与 xms_app_release.pkg 由写入端保证一致，管理后台自查规则会校验二者漂移。
--
-- 宽列（name / names / apk_name / file_name / size / md5 / sha256 / logs / release_date /
-- pkg_ver）请查 xms_app_release（JOIN xms_app.release_id = xms_app_release.id）。
--
-- 数据示例：
--   1867, 62, 1, 'com.android.deskclock'   -- 推送 62 包含 deskclock 1306003100（release.id=1）
--   1997, 66, 1, 'com.android.deskclock'   -- 推送 66 同样包含该 APK，指向同一 release
