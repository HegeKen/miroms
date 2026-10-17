-- complete：全部语言列都有内容且 proofed=1
ALTER TABLE `logs`
  ADD COLUMN `complete` tinyint(1) NOT NULL DEFAULT 0
  COMMENT '所有语言齐全且 proofed=1'
  AFTER `proofed`;
