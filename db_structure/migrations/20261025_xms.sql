-- 20261025_xms.sql
-- ---------------------------------------------------------------------------
-- 新增 xms / xms_app 表：把小米 OTA 接口返回的 XMS（SOTA 系统应用更新）
-- 收进数据库 —— 每次推送一行 xms，推送里每个应用一行 xms_app。
--
-- 本文件供「已有数据库」增量建表；全新初始化请直接执行
-- db_structure/xms.sql 与 db_structure/xms_app.sql（结构与本文件一致，
-- 本文件只多了 IF NOT EXISTS）。
--
-- 执行顺序：
--   1. 执行本文件建表（或在全新库执行 db_structure/xms.sql、xms_app.sql）
--   2. python3 data/scripts/ota_former.py（或 ota_full.py / get_new_branch.py）
--      —— 抓取 OTA 时会顺带解析并写入 XMS
-- 回滚：DROP TABLE xms_app; DROP TABLE xms;（数据随时可由 OTA 脚本重新抓取）
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS `xms` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `device` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '设备代号，如 violin',
  `code` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '分支代码（OTA 请求表单的 d 字段），如 violin、miro_id_global',
  `region` varchar(32) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '区域代号：cn/global/in/eea 等',
  `zone` int DEFAULT NULL COMMENT '区域分区：1=中国、2=国际',
  `android` varchar(8) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'Android 版本，如 16.0（XMS 请求的 c 字段）',
  `version` varchar(32) COLLATE utf8mb4_bin NOT NULL COMMENT 'XMS（SOTA 应用更新）版本号，如 C11',
  `rom_version` varchar(64) COLLATE utf8mb4_bin NOT NULL COMMENT '该 XMS 推送所基于的系统版本号，如 OS3.0.305.0.WOTCNXM',
  `rom_id` bigint DEFAULT NULL COMMENT '对应 roms.id（该 rom_version 已入库时）',
  `pkg_cnt` int DEFAULT NULL COMMENT '本次 XMS 覆盖的包数量（接口 xmsUpdateInfo.pkgCnt）',
  `prio` int DEFAULT NULL COMMENT '推送优先级（接口 xmsUpdateInfo.prio）',
  `notice` longtext COLLATE utf8mb4_bin COMMENT '注意事项（接口 xmsUpdateInfo.gentleNotice，已去 HTML 标签）',
  `changelog` longtext COLLATE utf8mb4_bin COMMENT '没有包名的日志模块 JSON 数组',
  `is_latest` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否为该分支当前最新系统版本上的最新 XMS：1=是、0=否',
  `push_date` date DEFAULT NULL COMMENT '首次抓取到该 XMS 版本的日期（近似推送日期）',
  `update_date` bigint DEFAULT NULL COMMENT '最近一次更新时间戳（秒）',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_xms_code_ver_rom` (`code`,`version`,`rom_version`),
  KEY `idx_xms_device` (`device`),
  KEY `idx_xms_code_latest` (`code`,`is_latest`),
  KEY `idx_xms_version` (`version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

CREATE TABLE IF NOT EXISTS `xms_app` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `xms_id` bigint NOT NULL COMMENT '所属 XMS 推送（xms.id）',
  `pkg` varchar(128) COLLATE utf8mb4_bin NOT NULL DEFAULT '' COMMENT '应用包名，如 com.miui.securitycenter；空串表示该日志模块接口没给包名',
  `name` varchar(128) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '应用 / 日志模块名（简体中文），如 手机管家',
  `name_en` varchar(128) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '应用 / 日志模块名（英文），如 Security',
  `names` longtext COLLATE utf8mb4_bin COMMENT '应用 / 模块名的多语言 JSON',
  `pkg_ver` varchar(64) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '应用版本号（接口 versionCode，如 40011275）',
  `apk_name` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT '安装包名称（接口 name，如「平板管家-CN-OS3」）',
  `file_name` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'APK 文件名（接口 fileName）',
  `size` bigint DEFAULT NULL COMMENT 'APK 体积（字节，接口 size）',
  `md5` char(32) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'APK MD5（接口 md5）',
  `sha256` char(64) COLLATE utf8mb4_bin DEFAULT NULL COMMENT 'APK SHA-256（接口 sha256）',
  `logs` longtext COLLATE utf8mb4_bin COMMENT '该应用的更新日志条目 JSON 数组：[{"zh":"...","en":"..."}, ...]（缺失语种省略对应键）',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_xms_app` (`xms_id`,`pkg`),
  KEY `idx_xms_app_pkg` (`pkg`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

-- ---------------------------------------------------------------------------
-- 从旧版结构升级（若已按旧版建过 xms / xms_app：无 names / changelog，
-- 且 uq_xms_app 含 name）。全新库执行上面的 CREATE 即可，不需要这些语句。
--
--   ALTER TABLE `xms`
--     ADD COLUMN `changelog` longtext COLLATE utf8mb4_bin
--       COMMENT '没有包名的日志模块 JSON 数组' AFTER `notice`;
--   ALTER TABLE `xms_app`
--     ADD COLUMN `names` longtext COLLATE utf8mb4_bin
--       COMMENT '应用 / 模块名的多语言 JSON' AFTER `name_en`;
--
--   -- 无包名模块搬到 xms.changelog，再删掉旧行（模块名不入键，避免重复录入）
--   UPDATE `xms` x JOIN (
--     SELECT `xms_id`, JSON_ARRAYAGG(JSON_OBJECT(
--              'name', JSON_OBJECT('zh', `name`, 'en', IFNULL(NULLIF(`name_en`, ''), `name`)),
--              'logs', CAST(`logs` AS JSON))) AS `items`
--       FROM `xms_app` WHERE `pkg` = '' GROUP BY `xms_id`
--   ) t ON t.`xms_id` = x.`id`
--   SET x.`changelog` = t.`items`;
--   DELETE FROM `xms_app` WHERE `pkg` = '';
--
--   -- 同一推送内一个包名只留一行
--   ALTER TABLE `xms_app` DROP INDEX `uq_xms_app`;
--   ALTER TABLE `xms_app` ADD UNIQUE KEY `uq_xms_app` (`xms_id`, `pkg`);
--
--   -- 回填多语言名称 / 日志
--   python3 scripts/enrich_xms.py --apply
-- ---------------------------------------------------------------------------
