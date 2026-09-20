-- ============================================================================
--  背备不悲 (BeiBeiBuBei) · AI 模拟面试模块增量脚本
--  依赖：先执行 schema.sql（21 张表）+ init_data.sql
--  本脚本新增：3 张表 + 4 个 Prompt 模板 + 4 条模型路由
--  幂等：表用 CREATE TABLE IF NOT EXISTS，Prompt 用 code 去重后升级版本号
-- ============================================================================

SET NAMES utf8mb4;
USE `beibei`;

-- ----------------------------------------------------------------------------
-- 22. bb_resume 简历库
--     与学习知识库**完全隔离**：简历不进 Milvus 分块集合、不参与知识点树。
--     raw_text 保留解析出的全文，profile_json 存 AI 抽取的结构化档案。
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `bb_resume` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`         BIGINT UNSIGNED NOT NULL DEFAULT 1,
  `file_name`       VARCHAR(255)    NOT NULL COMMENT '原始文件名',
  `file_path`       VARCHAR(500)    NOT NULL COMMENT '上传落盘路径',
  `file_size`       BIGINT          NOT NULL DEFAULT 0 COMMENT '字节',
  `file_type`       VARCHAR(20)     NOT NULL DEFAULT '' COMMENT 'pdf/docx/doc/txt/md',
  `raw_text`        LONGTEXT        DEFAULT NULL COMMENT '解析出的简历全文',
  `char_count`      INT             NOT NULL DEFAULT 0,
  `profile_json`    JSON            DEFAULT NULL COMMENT 'AI 抽取的结构化档案',
  `target_position` VARCHAR(100)    NOT NULL DEFAULT '' COMMENT '意向岗位',
  `status`          TINYINT         NOT NULL DEFAULT 0 COMMENT '0 待解析 1 解析中 2 就绪 3 失败',
  `error_msg`       VARCHAR(1000)   NOT NULL DEFAULT '',
  `created_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_status` (`status`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='简历库';

-- ----------------------------------------------------------------------------
-- 23. bb_interview 模拟面试场次
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `bb_interview` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`       BIGINT UNSIGNED NOT NULL DEFAULT 1,
  `resume_id`     BIGINT UNSIGNED NOT NULL COMMENT '用哪份简历面试',
  `kb_id`         BIGINT UNSIGNED DEFAULT NULL COMMENT '可选：关联的学习知识库，用于薄弱点出题',
  `job_title`     VARCHAR(100)    NOT NULL DEFAULT '' COMMENT '目标岗位',
  `difficulty`    TINYINT         NOT NULL DEFAULT 2 COMMENT '1 初级 2 中级 3 高级',
  `max_turns`     INT             NOT NULL DEFAULT 10 COMMENT '计划轮数（8~12）',
  `turn_count`    INT             NOT NULL DEFAULT 0 COMMENT '已完成的问答轮数',
  `status`        TINYINT         NOT NULL DEFAULT 0 COMMENT '0 待开始 1 进行中 2 已结束 3 失败',
  `total_score`   DECIMAL(5,2)    DEFAULT NULL COMMENT '整场综合得分',
  `summary`       VARCHAR(600)    NOT NULL DEFAULT '' COMMENT '总评摘要',
  `report_json`   JSON            DEFAULT NULL COMMENT '完整评估报告',
  `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `started_at`    DATETIME        DEFAULT NULL,
  `finished_at`   DATETIME        DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_resume` (`resume_id`),
  KEY `idx_status` (`status`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='模拟面试场次';

-- ----------------------------------------------------------------------------
-- 24. bb_interview_turn 面试对话轮次
--     role=1 面试官提问 / role=2 候选人回答。
--     面试官那一条带 based_on（可追溯到简历哪一段）与 expects（期望要点）；
--     候选人那一条带 score 与 feedback_json（评分明细）。
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS `bb_interview_turn` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `interview_id`  BIGINT UNSIGNED NOT NULL,
  `seq`           INT             NOT NULL COMMENT '从 1 开始的顺序号',
  `role`          TINYINT         NOT NULL COMMENT '1 面试官 2 候选人',
  `content`       TEXT            NOT NULL,
  `question_type` VARCHAR(20)     NOT NULL DEFAULT '' COMMENT 'INTRO/PROJECT/TECH/FOLLOWUP/SCENARIO/BEHAVIOR',
  `based_on`      VARCHAR(300)    NOT NULL DEFAULT '' COMMENT '本题基于简历的哪一段（可追溯）',
  `expects`       JSON            DEFAULT NULL COMMENT '期望回答覆盖的要点',
  `score`         DECIMAL(5,2)    DEFAULT NULL,
  `feedback_json` JSON            DEFAULT NULL COMMENT '评分明细与点评',
  `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_interview` (`interview_id`, `seq`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='面试对话轮次';

-- ============================================================================
--  Prompt 模板（code 已存在则不重复插入，由应用层版本化）
-- ============================================================================
INSERT INTO `bb_prompt_template`
  (`code`, `name`, `content`, `variables`, `version`, `is_active`, `builtin`, `remark`)
SELECT * FROM (
  SELECT 'RESUME_PARSE' AS code, '简历结构化抽取' AS name,
'你是资深 HR 兼技术面试官。下面是一份候选人简历的原文，请抽取结构化档案。
【简历原文】
{resume_text}

要求：
1. 只抽取原文里真实出现的信息，不要脑补、不要替候选人美化；
2. 原文没有的字段留空字符串或空数组，不要编造；
3. skills 拆到具体技术名词（如 Redis、Spring Boot、MySQL 索引优化）；
4. projects 每条都要带 evidence，填简历原文里的原话片段，后面面试官要靠它追问核实；
5. risks 填简历里可疑或模糊的点（时间线断档、技术栈与岗位不符、只有名词没有成果），供面试官重点追问。

严格只输出 JSON：
{"name":"","years":0,"education":"","school":"","major":"","currentCompany":"","currentTitle":"","targetPosition":"","skills":[],"projects":[{"name":"","role":"","period":"","techStack":[],"highlights":[],"evidence":""}],"workExperience":[{"company":"","title":"","period":"","duty":""}],"selfEvaluation":"","highlights":[],"risks":[]}' AS content,
'["resume_text"]' AS variables, 1 AS version, 1 AS is_active, 1 AS builtin,
'模拟面试：把简历全文变成结构化档案' AS remark
) AS t
WHERE NOT EXISTS (SELECT 1 FROM `bb_prompt_template` WHERE `code` = 'RESUME_PARSE');

INSERT INTO `bb_prompt_template`
  (`code`, `name`, `content`, `variables`, `version`, `is_active`, `builtin`, `remark`)
SELECT * FROM (
  SELECT 'INTERVIEW_ASK' AS code, '模拟面试官提问' AS name,
'你是一场模拟技术面试的面试官。请根据候选人简历、目标岗位和已进行的对话，提出下一个问题。

【目标岗位】{job_title}
【难度要求】{difficulty}
【候选人简历档案】
{resume_profile}
【已问过的问题】
{asked_questions}
【最近一轮问答】
{recent_qa}
【进度】本场共 {max_turns} 轮，这是第 {turn_no} 轮

出题策略：
1. 第 1 轮固定让候选人做自我介绍；
2. 之后顺着简历里的项目做深度追问：为什么这么设计、遇到什么问题、怎么解决、有没有量化结果；
3. 每 3 轮穿插一道原理/八股题，验证基础知识是否扎实；
4. 如果候选人上一轮回答含糊（只给结论不给过程），优先针对那个点追问，type 用 FOLLOWUP；
5. 不要重复已问过的问题，一次只问一个问题，不要一次抛多个问题。

basedOn 填本题对应简历里的哪一段原话或哪个项目，没有就填空字符串。

严格只输出 JSON：
{"question":"","type":"INTRO","basedOn":"","expects":[""]}' AS content,
'["job_title","difficulty","resume_profile","asked_questions","recent_qa","turn_no","max_turns"]' AS variables,
1 AS version, 1 AS is_active, 1 AS builtin,
'模拟面试：逐轮提问与追问' AS remark
) AS t
WHERE NOT EXISTS (SELECT 1 FROM `bb_prompt_template` WHERE `code` = 'INTERVIEW_ASK');

INSERT INTO `bb_prompt_template`
  (`code`, `name`, `content`, `variables`, `version`, `is_active`, `builtin`, `remark`)
SELECT * FROM (
  SELECT 'INTERVIEW_EVAL' AS code, '面试回答评分' AS name,
'你是模拟面试的面试官，请对候选人这一轮的回答打分并给出反馈。

【目标岗位】{job_title}
【面试问题】{question}
【本题类型】{question_type}
【期望覆盖的要点】{expects}
【简历相关原文】{resume_evidence}
【候选人回答】
{answer}

评分维度（每项 0~100）：
- techAccuracy 技术准确性：技术表述是否正确，有没有概念性错误；
- specificity 项目具体性：有没有讲清自己做了什么、用了什么数据、做了什么取舍；
- structure 表达结构：有没有条理（背景 → 方案 → 结果）；
- consistency 与简历一致性：回答是否与简历原文矛盾，矛盾必须扣分并指出；
- relevance 岗位匹配度：是否切题、是否命中岗位核心要求。

score 是综合得分（0~100，整数）。contradiction 只在确实与简历矛盾时填写，并引用简历原话；没有矛盾填空字符串。

严格只输出 JSON：
{"scores":{"techAccuracy":0,"specificity":0,"structure":0,"consistency":0,"relevance":0},"score":0,"goodPoints":[],"problems":[],"suggestion":"","contradiction":"","followUpNeeded":true}' AS content,
'["job_title","question","question_type","expects","resume_evidence","answer"]' AS variables,
1 AS version, 1 AS is_active, 1 AS builtin,
'模拟面试：单轮回答五维评分' AS remark
) AS t
WHERE NOT EXISTS (SELECT 1 FROM `bb_prompt_template` WHERE `code` = 'INTERVIEW_EVAL');

INSERT INTO `bb_prompt_template`
  (`code`, `name`, `content`, `variables`, `version`, `is_active`, `builtin`, `remark`)
SELECT * FROM (
  SELECT 'INTERVIEW_REPORT' AS code, '面试评估报告' AS name,
'你是模拟面试的主考官，一场面试已经结束，请出具书面评估报告。

【目标岗位】{job_title}
【难度要求】{difficulty}
【候选人简历档案】
{resume_profile}
【完整面试记录】
{transcript}

要求：
1. overallScore 是整场综合得分（0~100，整数），要和各轮得分基本吻合，不要虚高；
2. dimensions 给 4~6 个维度的得分与短评；
3. weakPoints 只列得分低或答不上来的技能项，每项都要写 evidence（面试中的具体表现）和 suggestion（怎么补）；
4. knowledgePoints 给 3~6 条最该优先补的知识点，用标准技术术语、每个不超过 20 字，后续要直接拿去出题，不要写句子；
5. summary 是 150 字以内的总评，直说问题和差距。

严格只输出 JSON：
{"overallScore":0,"summary":"","dimensions":[{"name":"","score":0,"comment":""}],"strengths":[],"weakPoints":[{"skill":"","level":"","evidence":"","suggestion":""}],"knowledgePoints":[],"nextSteps":[]}' AS content,
'["job_title","difficulty","resume_profile","transcript"]' AS variables,
1 AS version, 1 AS is_active, 1 AS builtin,
'模拟面试：整场评估报告（含薄弱知识点）' AS remark
) AS t
WHERE NOT EXISTS (SELECT 1 FROM `bb_prompt_template` WHERE `code` = 'INTERVIEW_REPORT');

-- ============================================================================
--  模型路由：provider_id = 0 表示「跟随当前启用的对话模型」，
--  与 QUESTION_GEN 的既有约定一致（换厂商时不用逐个改路由）
-- ============================================================================
INSERT INTO `bb_model_route` (`task_type`, `provider_id`, `remark`)
SELECT * FROM (
  SELECT 'RESUME_PARSE' AS task_type, 0 AS provider_id, '简历结构化抽取' AS remark
) AS t WHERE NOT EXISTS (SELECT 1 FROM `bb_model_route` WHERE `task_type` = 'RESUME_PARSE');

INSERT INTO `bb_model_route` (`task_type`, `provider_id`, `remark`)
SELECT * FROM (
  SELECT 'INTERVIEW_ASK' AS task_type, 0 AS provider_id, '模拟面试官提问' AS remark
) AS t WHERE NOT EXISTS (SELECT 1 FROM `bb_model_route` WHERE `task_type` = 'INTERVIEW_ASK');

INSERT INTO `bb_model_route` (`task_type`, `provider_id`, `remark`)
SELECT * FROM (
  SELECT 'INTERVIEW_EVAL' AS task_type, 0 AS provider_id, '面试回答评分' AS remark
) AS t WHERE NOT EXISTS (SELECT 1 FROM `bb_model_route` WHERE `task_type` = 'INTERVIEW_EVAL');

INSERT INTO `bb_model_route` (`task_type`, `provider_id`, `remark`)
SELECT * FROM (
  SELECT 'INTERVIEW_REPORT' AS task_type, 0 AS provider_id, '面试评估报告' AS remark
) AS t WHERE NOT EXISTS (SELECT 1 FROM `bb_model_route` WHERE `task_type` = 'INTERVIEW_REPORT');

-- ============================================================================
--  完成。本脚本新增 3 张表（M6 完成时库内共 24 张表）。
--  后续 M7 面经模块的 docs/sql/interview_note.sql 会再加 2 张，最终 26 张。
--
--  ⚠️ Prompt 模板内容以 interview_prompt_v2.sql 为准 —— 真实跑过大模型之后，
--     这三个模板（RESUME_PARSE / INTERVIEW_ASK / INTERVIEW_REPORT）做了修正，
--     修的是「技能重复抽取」「揪着一个点问到底」「薄弱知识点太啰嗦匹配不上标签」
--     这三个只有用真实模型才会暴露的问题。
--
--  新库执行顺序：
--     schema.sql → init_data.sql → interview.sql → interview_prompt_v2.sql
-- ============================================================================
