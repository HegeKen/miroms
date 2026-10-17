-- AI 校对标记：proofed=1 表示该行内容已被 AI 校对为一致，后续校对跳过
ALTER TABLE `logs`
  ADD COLUMN `proofed` tinyint(1) NOT NULL DEFAULT 0
  COMMENT 'AI 校对通过（内容一致）；后续校对跳过'
  AFTER `content_hash`;
