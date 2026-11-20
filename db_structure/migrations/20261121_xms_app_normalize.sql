-- 20261121_xms_app_normalize.sql
-- ---------------------------------------------------------------------------
-- 把 xms_app 里「同一 APK 被多次推送重复存储」的元数据抽到新表 xms_app_release，
-- xms_app 瘦身为「推送 ↔ 发布物」关联表。
--
-- 背景：旧 xms_app 每个推送里每个应用一行，同一个 (pkg, pkg_ver) 会被数十次
--       推送重复录入（实测 pkg_ver=1306003100 有 36 行，全表 2983 行仅 83 个真实 APK）。
--       同一 (pkg, pkg_ver) 的 md5 / file_name / apk_name / logs / release_date 恒等，
--       故以 (pkg, pkg_ver) 为唯一键抽离到 xms_app_release。
--
-- 执行方式（数据回填用 Python，SQL 只做结构切换，见 scripts/migrate_xms_app_normalize.py）：
--   1. python3 scripts/migrate_xms_app_normalize.py          # 建 release 表 + 回填 + 切换
--   2. 校验：行数无损、导出 JSON 与迁移前一致、后台可编辑
--   3. 确认无误后删除归档：DROP TABLE xms_app_archive;
--      （或脚本加 --drop-archive）
--
-- 回滚（迁移后随时可执行，恢复旧结构）：
--   DROP TABLE IF EXISTS xms_app;
--   RENAME TABLE xms_app_archive TO xms_app;
--   DROP TABLE IF EXISTS xms_app_release;
-- ---------------------------------------------------------------------------

-- 1) 新增 APK 发布物表（一个 (pkg, pkg_ver) 一行）
CREATE TABLE IF NOT EXISTS `xms_app_release` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `pkg` varchar(128) COLLATE utf8mb4_bin NOT NULL DEFAULT '',
  `pkg_ver` varchar(64) COLLATE utf8mb4_bin NOT NULL DEFAULT '',
  `name` varchar(128) COLLATE utf8mb4_bin DEFAULT NULL,
  `name_en` varchar(128) COLLATE utf8mb4_bin DEFAULT NULL,
  `names` longtext COLLATE utf8mb4_bin,
  `apk_name` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL,
  `file_name` varchar(255) COLLATE utf8mb4_bin DEFAULT NULL,
  `size` bigint DEFAULT NULL,
  `md5` char(32) COLLATE utf8mb4_bin DEFAULT NULL,
  `sha256` char(64) COLLATE utf8mb4_bin DEFAULT NULL,
  `logs` longtext COLLATE utf8mb4_bin,
  `release_date` date DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_release_pkg_ver` (`pkg`,`pkg_ver`),
  KEY `idx_release_pkg` (`pkg`),
  KEY `idx_release_md5` (`md5`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

-- 2) 数据回填（由 scripts/migrate_xms_app_normalize.py 完成）：
--    - 从旧 xms_app 按 (pkg, pkg_ver) 选「最完整」一行写入 xms_app_release
--    - 建立 release_id 映射后，生成新的 xms_app 关联行（保留原 id、xms_id、pkg）

-- 3) 切换（RENAME 原子操作，需先完成上面的数据回填）：
--    RENAME TABLE `xms_app` TO `xms_app_archive`;
--    CREATE TABLE `xms_app` ( ... 关联表结构，见 db_structure/xms_app.sql ... );
--    INSERT INTO `xms_app` (id, xms_id, release_id, pkg)
--      SELECT a.id, a.xms_id, r.id, a.pkg
--      FROM `xms_app_archive` a JOIN `xms_app_release` r
--        ON r.pkg = a.pkg AND r.pkg_ver <=> a.pkg_ver;

-- 4) 校验通过后清理归档：
--    DROP TABLE `xms_app_archive`;

-- ---------------------------------------------------------------------------
-- 全新数据库初始化请直接执行：
--   db_structure/xms_app_release.sql  +  db_structure/xms_app.sql  +  db_structure/xms.sql
-- 本迁移文件仅用于把「已存在旧结构」的库升级到新结构。
-- ---------------------------------------------------------------------------
