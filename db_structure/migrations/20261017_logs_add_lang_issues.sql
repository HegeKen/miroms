-- AI 语言标注：记录「语言列文本与列语言不符」的明细；有标注的行不置 proofed
ALTER TABLE `logs`
  ADD COLUMN `lang_issues` json DEFAULT NULL
  COMMENT 'AI 标注：语言列文本与列语言不符的明细（JSON）'
  AFTER `proofed`;
