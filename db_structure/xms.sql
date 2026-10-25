DROP TABLE IF EXISTS `xms`;
CREATE TABLE `xms` (
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
  `changelog` longtext COLLATE utf8mb4_bin COMMENT '没有包名的日志模块 JSON 数组：[{"name":{"zh","en",...},"logs":[{"zh","en",...}]}, ...]',
  `is_latest` tinyint(1) NOT NULL DEFAULT '0' COMMENT '是否为该分支当前最新系统版本上的最新 XMS：1=是、0=否',
  `push_date` date DEFAULT NULL COMMENT '推送日期：该版本应用包 HTTP Last-Modified 的众数（多数包上传的那天）',
  `update_date` bigint DEFAULT NULL COMMENT '最近一次更新时间戳（秒）',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_xms_code_ver_rom` (`code`,`version`,`rom_version`),
  KEY `idx_xms_device` (`device`),
  KEY `idx_xms_code_latest` (`code`,`is_latest`),
  KEY `idx_xms_version` (`version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin ROW_FORMAT=DYNAMIC;

-- 说明：
-- 小米 OTA 接口（https://update.miui.com/updates/miotaV3.php）除了 LatestRom /
-- CurrentRom，还会返回 xmsUpdateInfo —— 系统应用级的增量更新（SOTA，接口内部叫 XMS）：
--   hasXmsUpdate=1 表示「当前系统版本上还有一批系统应用可以更新」，
--   lstVer 是这批应用的版本号（如 C11），pkgs 是本次覆盖的包名列表。
-- 同一份 XMS 会挂在不同系统版本上（如 C11 对 302/303/304 都能推），
-- 因此本表按「分支代码 + XMS 版本 + 系统版本」唯一，一次推送一行。
--
-- is_latest：只有「查询时当前系统版本 == 接口返回的 LatestRom」才标记为 1，
-- 表示这是最新系统版本上的最新 XMS；接口没返回 LatestRom 时退化为
-- 「与该分支 roms 表里最新的版本一致」。同一分支同时只有一行为 1。
--
-- push_date：XMS 接口本身不提供发布时间，取该版本应用包下载链接 Last-Modified 的众数（多数包上传的那天，回退最早抓取日期）；
-- 同一（分支代码, XMS 版本）的后续系统版本行会沿用最早那一行的日期。
--
-- 应用明细（包名 / 版本号 / 更新日志）见 xms_app.sql；
-- 接口 changeLog 里没有 package 的模块（如「小米超级岛」）不是应用，存在本表 changelog 里。
--
-- 数据示例：
--   1,'violin','violin','cn',1,'16.0','C11','OS3.0.304.0.WOTCNXM',52106,27,1,
--     '若部分应用已通过其他渠道提前更新至最新版本……',1,'2026-05-21',1761300000
