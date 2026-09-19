-- ============================================================================
--  背备不悲 · 模拟面试 Prompt 模板 v2
--
--  为什么出 v2（都是真实跑 DeepSeek 之后暴露的问题）：
--    1. RESUME_PARSE：模型一次抽出 57 个「技能」，SpringBoot / MySQL / Redis / 锁机制
--       各重复两遍；而且把在校生推测成了「两年工作经验」。
--       → 加去重、限 20 个原子名词、明确在校生 years 必须为 0。
--    2. INTERVIEW_ASK：模型在「实习经历」这一个点上连问了 4 轮，
--       整场面试实际只覆盖了一个话题。
--       → 加「同一主题最多连续追问 2 轮」。
--    3. INTERVIEW_REPORT：模型给出的 knowledgePoints 是
--       「布隆过滤器原理与误判率」这类 15 字短语，拿去和知识库标签名匹配一个都命中不了，
--       闭环直接退化成整库出题。
--       → 明确要求最小粒度、不超过 10 字、一条只讲一个点。
--
--  执行方式：python scripts/apply_sql.py docs/sql/interview_prompt_v2.sql
--  幂等：重复执行不会生成 v3（WHERE 里卡了 version = 1）
-- ============================================================================

SET NAMES utf8mb4;
USE `beibei`;

-- ----------------------------------------------------------------------------
-- 1. RESUME_PARSE v2
-- ----------------------------------------------------------------------------
INSERT INTO `bb_prompt_template`
  (`code`, `name`, `content`, `variables`, `version`, `is_active`, `builtin`, `remark`)
SELECT 'RESUME_PARSE', '简历结构化抽取',
'你是资深 HR 兼技术面试官。下面是一份候选人简历的原文，请抽取结构化档案。
【简历原文】
{resume_text}

要求：
1. 只抽取原文里真实出现的信息，不要脑补、不要替候选人美化；
2. 原文没有的字段留空字符串或空数组，不要编造；
3. 如果候选人是在校生 / 应届生、简历里没有正式工作经历，years 必须填 0，
   currentCompany 与 currentTitle 都留空，**不要**从「项目经历」推测出工作年限；
4. skills 只放**原子技术名词**（如 Redis、Spring Boot、MySQL 索引），
   同一门技术只出现一次（大小写统一，统一写 Spring Boot 而不是 SpringBoot），
   最多 20 个，按在简历里出现的先后顺序排列；
5. projects 每条都要带 evidence，填简历原文里的原话片段，后面面试官要靠它追问核实；
6. risks 填简历里可疑或模糊的点（时间线断档、技术栈与岗位不符、只有名词没有成果），供面试官重点追问。

严格只输出 JSON：
{"name":"","years":0,"education":"","school":"","major":"","currentCompany":"","currentTitle":"","targetPosition":"","skills":[],"projects":[{"name":"","role":"","period":"","techStack":[],"highlights":[],"evidence":""}],"workExperience":[{"company":"","title":"","period":"","duty":""}],"selfEvaluation":"","highlights":[],"risks":[]}',
'["resume_text"]', 2, 1, 1,
'v2：技能去重并限 20 个；在校生 years 必须为 0，不许推测工作年限'
FROM DUAL
WHERE EXISTS (SELECT 1 FROM `bb_prompt_template` WHERE `code` = 'RESUME_PARSE' AND `version` = 1);

UPDATE `bb_prompt_template` SET `is_active` = 0
WHERE `code` = 'RESUME_PARSE' AND `version` = 1
  AND EXISTS (SELECT 1 FROM (SELECT 1 FROM `bb_prompt_template` WHERE `code` = 'RESUME_PARSE' AND `version` = 2) AS t);

-- ----------------------------------------------------------------------------
-- 2. INTERVIEW_ASK v2
-- ----------------------------------------------------------------------------
INSERT INTO `bb_prompt_template`
  (`code`, `name`, `content`, `variables`, `version`, `is_active`, `builtin`, `remark`)
SELECT 'INTERVIEW_ASK', '模拟面试官提问',
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
5. 不要重复已问过的问题，一次只问一个问题，不要一次抛多个问题；
6. **同一个主题最多连续追问 2 轮**。第 3 轮必须换到简历里的另一个项目或另一门技能，
   不要揪着一个点问到底 —— 那样整场面试只覆盖了一个技术点，评估报告会失真；
7. 如果候选人的回答与简历明显对不上（比如自称有工作经验但简历是在校生），
   可以追问一次澄清，但**最多一次**，澄清完就继续正常往下问，不要反复纠缠。

basedOn 填本题对应简历里的哪一段原话或哪个项目，没有就填空字符串。

严格只输出 JSON：
{"question":"","type":"INTRO","basedOn":"","expects":[""]}',
'["job_title","difficulty","resume_profile","asked_questions","recent_qa","turn_no","max_turns"]',
2, 1, 1,
'v2：同一主题最多连追 2 轮；简历矛盾最多追问一次，不反复纠缠'
FROM DUAL
WHERE EXISTS (SELECT 1 FROM `bb_prompt_template` WHERE `code` = 'INTERVIEW_ASK' AND `version` = 1);

UPDATE `bb_prompt_template` SET `is_active` = 0
WHERE `code` = 'INTERVIEW_ASK' AND `version` = 1
  AND EXISTS (SELECT 1 FROM (SELECT 1 FROM `bb_prompt_template` WHERE `code` = 'INTERVIEW_ASK' AND `version` = 2) AS t);

-- ----------------------------------------------------------------------------
-- 3. INTERVIEW_REPORT v2
-- ----------------------------------------------------------------------------
INSERT INTO `bb_prompt_template`
  (`code`, `name`, `content`, `variables`, `version`, `is_active`, `builtin`, `remark`)
SELECT 'INTERVIEW_REPORT', '面试评估报告',
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
3. weakPoints 只列得分低或答不上来的技能项，每项都要写 evidence（面试中的具体表现）
   和 suggestion（怎么补）；
4. knowledgePoints 给 3~6 条最该优先补的知识点。这一项**会被程序直接拿去和知识库的
   标签名做匹配**，请严格遵守：
   - 每条只讲**一个**最小粒度的知识点，不要用顿号把多个点连起来；
   - 用标准技术术语，**不超过 10 个字**，不要加「原理与误判率」「方案对比」「与……的区别」
     这类修饰。例子：写「布隆过滤器」而不是「布隆过滤器原理与误判率」；
     写「最左前缀原则」而不是「MySQL联合索引与最左前缀」；写「Redis 分布式锁」而不是
     「Redis分布式锁与Lua原子性」；
   - 不要写成句子。
5. summary 是 150 字以内的总评，直说问题和差距。

严格只输出 JSON：
{"overallScore":0,"summary":"","dimensions":[{"name":"","score":0,"comment":""}],"strengths":[],"weakPoints":[{"skill":"","level":"","evidence":"","suggestion":""}],"knowledgePoints":[],"nextSteps":[]}',
'["job_title","difficulty","resume_profile","transcript"]',
2, 1, 1,
'v2：knowledgePoints 必须最小粒度、≤10 字、一条只讲一个点（下游要按名字匹配知识库标签）'
FROM DUAL
WHERE EXISTS (SELECT 1 FROM `bb_prompt_template` WHERE `code` = 'INTERVIEW_REPORT' AND `version` = 1);

UPDATE `bb_prompt_template` SET `is_active` = 0
WHERE `code` = 'INTERVIEW_REPORT' AND `version` = 1
  AND EXISTS (SELECT 1 FROM (SELECT 1 FROM `bb_prompt_template` WHERE `code` = 'INTERVIEW_REPORT' AND `version` = 2) AS t);

-- ============================================================================
--  完成。当前每个面试模板都应有一条 version=2 且 is_active=1。
-- ============================================================================
