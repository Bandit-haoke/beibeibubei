-- ============================================================================
--  背备不悲 (BeiBeiBuBei) · 面经功能建表 + 提示词
--  MySQL 8.0+ / utf8mb4
--
--  功能：上传面试录音 → 长音频转写 → 区分「面试官 / 我」→ 去口语化与重复
--        → AI 生成面经 → 保存并展示
--
--  与 bb_interview 的区别（重要）：
--    bb_interview      = 本工具"扮演"面试官，与用户进行模拟面试（AI 生成内容）
--    bb_interview_note = 用户上传"真实发生过的面试录音"，由 AI 整理成面经（AI 整理内容）
--  两者互不依赖，可以同时存在。
--
--  执行：python scripts/apply_sql.py docs/sql/interview_note.sql
-- ============================================================================

SET NAMES utf8mb4;
USE `beibei`;

-- ----------------------------------------------------------------------------
-- 1. bb_interview_note 面经主表
--    一场真实面试 = 一份录音 = 一条记录
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_interview_note_turn`;
DROP TABLE IF EXISTS `bb_interview_note`;
CREATE TABLE `bb_interview_note` (
  `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`        BIGINT UNSIGNED NOT NULL DEFAULT 1,

  `title`          VARCHAR(200)    NOT NULL DEFAULT '' COMMENT '面经标题（AI 生成，可人工改）',
  `company`        VARCHAR(100)    NOT NULL DEFAULT '' COMMENT '公司名（用户填，可空）',
  `position`       VARCHAR(100)    NOT NULL DEFAULT '' COMMENT '面试岗位（用户填，可空）',

  -- 录音文件
  `file_name`      VARCHAR(255)    NOT NULL DEFAULT '' COMMENT '原始音频文件名',
  `file_path`      VARCHAR(500)    NOT NULL DEFAULT '' COMMENT '落盘相对路径',
  `file_size`      BIGINT          NOT NULL DEFAULT 0  COMMENT '字节',
  `file_type`      VARCHAR(20)     NOT NULL DEFAULT '' COMMENT 'mp3/wav/m4a/flac/opus',
  `duration_ms`    INT             NOT NULL DEFAULT 0  COMMENT '音频时长（毫秒）',

  -- 转写引擎与角色来源（排查问题时要能一眼看出走的哪条路）
  `engine`         VARCHAR(20)     NOT NULL DEFAULT '' COMMENT 'LFASR=讯飞语音转写 / IAT=语音听写兜底',
  `role_source`    VARCHAR(20)     NOT NULL DEFAULT '' COMMENT 'LFASR=引擎原生角色分离 / LLM=大模型推断',

  -- 状态机：0 待处理 1 转写中 2 转写完成 3 生成面经中 4 完成 9 失败
  `status`         TINYINT         NOT NULL DEFAULT 0,
  `progress`       INT             NOT NULL DEFAULT 0  COMMENT '0~100，前端进度条',
  `stage`          VARCHAR(120)    NOT NULL DEFAULT '' COMMENT '当前阶段文案',

  -- 结果
  `turn_count`     INT             NOT NULL DEFAULT 0  COMMENT '清洗后的句子数',
  `question_count` INT             NOT NULL DEFAULT 0  COMMENT '面试官提问数',
  `speaker_count`  INT             NOT NULL DEFAULT 0  COMMENT '识别出的说话人个数',
  `summary`        VARCHAR(600)    NOT NULL DEFAULT '' COMMENT '60 字总览',
  `content`        MEDIUMTEXT               DEFAULT NULL COMMENT '面经正文（Markdown）',
  `questions_json` JSON                     DEFAULT NULL COMMENT '结构化问题清单',
  `highlights_json` JSON                    DEFAULT NULL COMMENT '经验点数组',
  `raw_json`       JSON                     DEFAULT NULL COMMENT '转写原文（含 speaker/时间戳），供溯源核对',

  `error_msg`      VARCHAR(1000)   NOT NULL DEFAULT '',
  `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  PRIMARY KEY (`id`),
  KEY `idx_status`  (`status`),
  KEY `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='面经（真实面试录音整理）';


-- ----------------------------------------------------------------------------
-- 2. bb_interview_note_turn 面经对话轮次
--    一句话一行，role 只有两种：面试官 / 我
-- ----------------------------------------------------------------------------
CREATE TABLE `bb_interview_note_turn` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `note_id`       BIGINT UNSIGNED NOT NULL,
  `seq`           INT             NOT NULL COMMENT '从 1 开始的顺序号',
  `role`          TINYINT         NOT NULL COMMENT '1 面试官 2 我（候选人）',
  `start_ms`      INT             NOT NULL DEFAULT 0 COMMENT '起始时间（毫秒）',
  `end_ms`        INT             NOT NULL DEFAULT 0 COMMENT '结束时间（毫秒）',
  `raw_text`      TEXT            NOT NULL COMMENT '转写原文（未清洗）',
  `clean_text`    TEXT            NOT NULL COMMENT '清洗后文本（去语气词/重复）',
  `removed_words` VARCHAR(300)    NOT NULL DEFAULT '' COMMENT '被去掉的口语词，便于人工核对',
  `question_type` VARCHAR(20)     NOT NULL DEFAULT '' COMMENT '仅面试官：INTRO/PROJECT/TECH/SCENARIO/ALGO/REVERSE/OTHER',
  `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_note` (`note_id`, `seq`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='面经对话轮次';


-- ============================================================================
--  提示词模板
-- ============================================================================

DELETE FROM `bb_prompt_template` WHERE `code` IN
  ('INTERVIEW_NOTE_SEGMENT', 'INTERVIEW_NOTE_SPEAKER_MAP', 'INTERVIEW_NOTE_POLISH',
   'INTERVIEW_NOTE_SUMMARY', 'INTERVIEW_NOTE_ROLE');

INSERT INTO `bb_prompt_template`
  (`code`, `name`, `content`, `variables`, `version`, `is_active`, `builtin`, `remark`)
VALUES
(
  'INTERVIEW_NOTE_SPEAKER_MAP',
  '面经·说话人编号映射',
  '下面是一场面试的转写片段。转写引擎已经自动区分了说话人，并给出编号（编号只是引擎内部标识，没有任何语义）。\n请判断每个编号对应的是「面试官」还是「候选人（我）」。\n【判断线索】\n- 面试官：提问、追问、要求展开、介绍公司或岗位、宣布流程、给出评价\n- 候选人：自我介绍、回答问题、讲项目经历、讲技术细节、表达不确定\n- 一场面试里面试官只有一个，候选人只有一个\n【带编号的发言片段】\n{speaker_samples}\n【出现过的编号】{speaker_ids}\n严格只输出 JSON：{"mapping":{"1":1,"2":2},"reason":"判断理由"}。mapping 的键是引擎编号，值是 1=面试官 或 2=候选人。',
  JSON_ARRAY(
    JSON_OBJECT('name','speaker_samples','desc','每个说话人的代表性发言，形如 [说话人1] xxx'),
    JSON_OBJECT('name','speaker_ids','desc','出现过的说话人编号，逗号分隔')
  ),
  1, 1, 1, '面经功能：把引擎的说话人编号映射到面试官/候选人'
),
(
  'INTERVIEW_NOTE_SEGMENT',
  '面经·切句与角色判定',
  '下面是一段面试录音的转写文本。转写没有说话人标记，而且标点并不可靠 —— 两个人的话经常被连成一串。\n请把它按「谁在说话」切分成若干句，并标注每句的角色。\n【背景】这是一场技术面试，全程只有两个人：面试官 和 候选人（也就是"我"）。\n【典型情况】原文「你好，请先做一个自我介绍面试官好，我叫张三，有三年 Java 经验」其实是两句：\n  「你好，请先做一个自我介绍」→ 面试官（提问）\n  「面试官好，我叫张三，有三年 Java 经验」→ 候选人（回答）\n【切分规则】\n1. 同一个人连续说的一段话算一句，一旦换人就切开\n2. 面试官：提问、追问、要求展开、宣布流程、给出评价，通常较短且是问句\n3. 候选人：自我介绍、回答问题、讲项目、讲技术细节、表达不确定，通常较长且含技术细节\n4. 只做切分和标注：不要改写、不要润色、不要增删任何字词\n5. 把切分结果按顺序拼起来，必须和原文完全一致（这是校验依据）\n6. 一句话里如果确实同时包含提问和回答，在换人的位置切开\n【转写文本】\n{text}\n严格只输出 JSON：{"items":[{"text":"","role":1}]}。role 取 1=面试官，2=候选人。',
  JSON_ARRAY(
    JSON_OBJECT('name','text','desc','一段连续、未区分说话人的转写文本')
  ),
  1, 1, 1, '面经功能：没有说话人分离时，让大模型边切句边判角色'
),
(
  'INTERVIEW_NOTE_POLISH',
  '面经·口语清洗',
  '下面是一段面试录音的转写文本，口语痕迹很重，请逐句清洗成通顺的书面表达。\n【需要处理的问题】\n1. 语气词与口头禅：啊、额、嗯、呃、那个、就是说、然后呢、对吧\n2. 重复：我我我、就是就是、这个这个\n3. 口误与自我纠正：说了半句改口（只保留最终意思）\n4. 无意义的填充和寒暄碎片\n【硬性要求】\n- 不改变原意，不增加原文没有的事实，不替说话人补充内容\n- 不合并也不拆分句子，输入一句就输出一句，seq 必须一一对应\n- 某句清洗后确实没有任何有效内容时，cleanText 填空字符串\n- 保留专业术语和数据，不要"顺"掉技术细节\n【待清洗文本】每行格式 `序号|角色|内容`\n{lines}\n严格只输出 JSON：{"items":[{"seq":1,"cleanText":""}]}',
  JSON_ARRAY(JSON_OBJECT('name','lines','desc','每行格式 序号|角色|内容 的待清洗文本')),
  1, 1, 1, '面经功能：去语气词、去重复、修口误'
),
(
  'INTERVIEW_NOTE_SUMMARY',
  '面经·生成面经',
  '你是一位求职辅导专家。下面是一场真实面试的完整记录（已区分面试官和候选人，已完成口语清洗）。\n请把它整理成一篇对后来者有参考价值的「面经」。\n【公司】{company}\n【岗位】{position}\n【面试记录】\n{transcript}\n【输出要求】\n- questions：面试官问过的每一个问题，question 用清洗后的问题原文；answer 是候选人回答的要点摘要（2~3 句，忠实于原意）；category 从 自我介绍/项目经历/技术原理/场景设计/算法/反问环节/其他 中选一个\n- highlights：值得记录的经验点 3~6 条，要具体（例如"面试官连追三层缓存一致性"），不要说空话\n- content：面经正文，Markdown 格式，分三节：## 面试流程、## 问题与回答要点、## 复盘与建议\n- 如果候选人某题答得明显不好，要在建议里点出来\n严格只输出 JSON：{"title":"","summary":"","questions":[{"question":"","answer":"","category":""}],"highlights":[],"content":""}',
  JSON_ARRAY(
    JSON_OBJECT('name','company','desc','公司名，可空'),
    JSON_OBJECT('name','position','desc','面试岗位，可空'),
    JSON_OBJECT('name','transcript','desc','带角色标记的面试记录全文')
  ),
  1, 1, 1, '面经功能：生成面经正文、问题清单与经验点'
);

-- ============================================================================
--  验证
-- ============================================================================
SELECT 'tables' AS kind, COUNT(*) AS n FROM information_schema.tables
  WHERE table_schema = 'beibei' AND table_name LIKE 'bb_interview_note%'
UNION ALL
SELECT 'prompts', COUNT(*) FROM bb_prompt_template
  WHERE code LIKE 'INTERVIEW_NOTE%';
