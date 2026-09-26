DROP TABLE IF EXISTS `logs`;
CREATE TABLE `logs` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `type` varchar(8) COLLATE utf8mb4_bin NOT NULL COMMENT '日志类型：module=模块名 / log=日志条目',
  `content` text COLLATE utf8mb4_bin NOT NULL COMMENT '原文内容',
  `content_hash` char(32) COLLATE utf8mb4_bin NOT NULL COMMENT 'content 的 MD5（hex），用于去重查找',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_type_hash` (`type`, `content_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- 说明：roms 表的 logs_* 列不再存原文 JSON 对象，改存 ID 引用结构：
--   [[模块ID,[条目ID,...]],...]  如 [[3,[6,8]],[32,[45,48]]]
-- 模块顺序即数组顺序；条目顺序保持原日志内顺序。
-- 数据示例：1,'module','系统','65f8...' / 6,'log','新增 手电筒光亮调节页','9b1e...'
