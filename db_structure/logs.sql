DROP TABLE IF EXISTS `logs`;
CREATE TABLE `logs` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT '自增主键（同一日志的各语言版本共用一行）',
  `type` varchar(8) COLLATE utf8mb4_bin NOT NULL COMMENT '日志类型：module=模块名 / log=日志条目',
  `content` text COLLATE utf8mb4_bin NOT NULL COMMENT '主内容（简体中文；无中文时取英文，再取最早出现的原文），去重依据',
  `content_hash` char(32) COLLATE utf8mb4_bin NOT NULL COMMENT 'content 的 MD5（hex），查专用索引（同内容可因译文冲突存在多行）',
  `proofed` tinyint(1) NOT NULL DEFAULT 0 COMMENT 'AI 校对通过（内容一致）；后续校对跳过',
  `complete` tinyint(1) NOT NULL DEFAULT 0 COMMENT '所有语言齐全且 proofed=1',
  `lang_issues` json DEFAULT NULL COMMENT 'AI 标注：语言列文本与列语言不符的明细（JSON）',
  `logs_zh` longtext COLLATE utf8mb4_bin COMMENT '简体中文（zh_CN，与 content 同值）',
  `logs_zh_tw` longtext COLLATE utf8mb4_bin COMMENT '繁体中文（zh_TW）',
  `logs_en` longtext COLLATE utf8mb4_bin COMMENT '英文（en_US）',
  `logs_ja` longtext COLLATE utf8mb4_bin COMMENT '日文（ja_JP）',
  `logs_ko` longtext COLLATE utf8mb4_bin COMMENT '韩文（ko_KR）',
  `logs_ru` longtext COLLATE utf8mb4_bin COMMENT '俄文（ru_RU）',
  `logs_uk` longtext COLLATE utf8mb4_bin COMMENT '乌克兰文（uk_UA）',
  `logs_pl` longtext COLLATE utf8mb4_bin COMMENT '波兰文（pl_PL）',
  `logs_de` longtext COLLATE utf8mb4_bin COMMENT '德文（de_DE）',
  `logs_fr` longtext COLLATE utf8mb4_bin COMMENT '法文（fr_FR）',
  `logs_it` longtext COLLATE utf8mb4_bin COMMENT '意大利文（it_IT）',
  `logs_es` longtext COLLATE utf8mb4_bin COMMENT '西班牙文（es_ES）',
  `logs_pt` longtext COLLATE utf8mb4_bin COMMENT '葡萄牙文（pt_BR）',
  `logs_tr` longtext COLLATE utf8mb4_bin COMMENT '土耳其文（tr_TR）',
  `logs_id` longtext COLLATE utf8mb4_bin COMMENT '印尼文（id_ID）',
  `logs_vi` longtext COLLATE utf8mb4_bin COMMENT '越南文（vi_VN）',
  `logs_th` longtext COLLATE utf8mb4_bin COMMENT '泰文（th_TH）',
  `logs_ar` longtext COLLATE utf8mb4_bin COMMENT '阿拉伯文（ar_EG）',
  `logs_in` longtext COLLATE utf8mb4_bin COMMENT '印地文（hi_IN）',
  `logs_ug` longtext COLLATE utf8mb4_bin COMMENT '维吾尔文（ug_CN）',
  `logs_bo` longtext COLLATE utf8mb4_bin COMMENT '藏文（bo_CN）',
  PRIMARY KEY (`id`),
  KEY `idx_type_hash` (`type`, `content_hash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;

-- 说明：同一句日志的不同语言版本存放在同一行。
--   content 为简体中文主内容（也是 content_hash 的去重依据），logs_zh 与 content 同值；
--   其余语言按各自的列存储（一门语言一列，列集合由 scripts/miroms/constants.py 的
--   CHANGELOG_LOCALES 统一维护，新增语种只需加列，无需再动 roms 表）。
-- roms.logs 存 ID 引用结构：[[模块ID,[条目ID,...]],...] 如 [[3,[6,8]],[32,[45,48]]]。
-- 数据示例：
--   1,'module','系统','65f8...','系统','系統','System','システム',...
--   6,'log','新增 手电筒光亮调节页','9b1e...','新增 手电筒光亮调节页',NULL,'New: Adjust flashlight brightness',...
