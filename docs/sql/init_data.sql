-- ============================================================================
--  背备不悲 (BeiBeiBuBei) · 初始数据
--  先执行 schema.sql，再执行本脚本
-- ============================================================================

USE `beibei`;

-- ----------------------------------------------------------------------------
-- 1. 默认用户（单人本机自用，跳过注册流程）
--    密码：beibei123 的 BCrypt 哈希（首次登录后请修改）
-- ----------------------------------------------------------------------------
INSERT INTO `bb_user` (`id`, `username`, `password_hash`, `nickname`, `daily_goal`)
VALUES (1, 'beibei', '$2a$10$N.zmdr9k7uOCQb376NoUnuTJ8iAt6Z5EHsM8lE9lBOsl7iKTVKIUi', '我', 20)
ON DUPLICATE KEY UPDATE `nickname` = VALUES(`nickname`);

-- ----------------------------------------------------------------------------
-- 2. AI 厂商
--    ⚠ api_key_enc 留空，请在前端「设置 → AI 配置」里填写并点击「测试连通」
--    加密由 Java 层 AES 完成，数据库里永远不出现明文 Key
-- ----------------------------------------------------------------------------
INSERT INTO `bb_ai_provider`
  (`id`, `name`, `vendor`, `protocol`, `base_url`, `model`, `capability`, `extra_params`, `enabled`, `priority`, `is_active`, `locked`, `remark`)
VALUES
  (1, 'DeepSeek Chat', 'deepseek', 'openai-compatible', 'https://api.deepseek.com', 'deepseek-chat', 'CHAT',
      JSON_OBJECT('temperature', 0.7, 'max_tokens', 8192, 'top_p', 0.95), 1, 10, 1, 0,
      '默认主力模型，便宜、中文强、支持 JSON 输出。出题与判分都用它'),
  (2, 'DeepSeek Reasoner', 'deepseek', 'openai-compatible', 'https://api.deepseek.com', 'deepseek-reasoner', 'CHAT',
      JSON_OBJECT('temperature', 0.6, 'max_tokens', 16384), 1, 20, 0, 0,
      '推理模型，出题质量更好但更慢更贵。可在「任务路由」里把 QUESTION_GEN 切到它'),
  (3, '通义千问（备用）', 'qwen', 'openai-compatible', 'https://dashscope.aliyuncs.com/compatible-mode/v1', 'qwen-plus', 'CHAT',
      JSON_OBJECT('temperature', 0.7, 'max_tokens', 8192), 0, 30, 0, 0, '备用厂商，填 Key 后启用'),
  (11, '本地 BGE-M3（向量）', 'local', 'custom', 'http://127.0.0.1:8001', 'BAAI/bge-m3', 'EMBED',
      JSON_OBJECT('dim', 1024, 'batch_size', 16, 'normalize', TRUE, 'device', 'cuda'), 1, 1, 1, 1,
      '🔒 锁定不可切换。换向量模型会导致已入库向量不可比，只能新建知识库重跑'),
  (21, '讯飞语音听写', 'xfyun', 'custom', 'https://iat-api.xfyun.cn/v2/iat', 'iat', 'ASR',
      JSON_OBJECT('language', 'zh_cn', 'domain', 'iat', 'ptt', 1, 'format', 'audio/L16;rate=16000'), 0, 10, 0, 0,
      '需填 AppId / ApiKey / ApiSecret，前端「测试连通」通过后启用'),
  (22, '阿里云智能语音', 'aliyun', 'custom', 'https://nls-gateway-cn-shanghai.aliyuncs.com', 'nls', 'ASR',
      JSON_OBJECT('format', 'pcm', 'sample_rate', 16000, 'enable_punctuation', TRUE), 0, 20, 0, 0,
      '需填 AppKey / AccessKeyId / AccessKeySecret'),
  (31, '本地 PaddleOCR', 'local', 'custom', 'http://127.0.0.1:8001', 'PP-OCRv5', 'OCR',
      JSON_OBJECT('lang', 'ch', 'use_gpu', TRUE, 'det_db_thresh', 0.3), 1, 1, 1, 1,
      '🔒 本地 OCR，照片识别走它，不消耗云端额度')
ON DUPLICATE KEY UPDATE `name` = VALUES(`name`);

-- ----------------------------------------------------------------------------
-- 3. 任务 → 模型路由（出题用强模型、分类用便宜模型的落地点）
-- ----------------------------------------------------------------------------
INSERT INTO `bb_model_route` (`task_type`, `provider_id`, `fallback_provider_id`, `remark`) VALUES
  ('QUESTION_GEN',  1, 2, '出题：主力 DeepSeek Chat，失败降级到 Reasoner'),
  ('GRADING',       1, 2, '判分：需要理解语义与要点对齐'),
  ('CLASSIFY',      1, 0, '知识点树抽取'),
  ('CHUNK_TAG',     1, 0, '分块打标，调用量大，可用便宜模型'),
  ('SELF_CHECK',    1, 0, '题目自检，防幻觉'),
  ('RECITE_CHECK',  1, 0, '口述复述覆盖度核对'),
  ('ASR',          21, 22, '语音转文字：讯飞优先，失败降级阿里云')
ON DUPLICATE KEY UPDATE `provider_id` = VALUES(`provider_id`);

-- ----------------------------------------------------------------------------
-- 4. Prompt 模板（⭐ 出题与判分质量的天花板，可在前端随时改并自动生成新版本）
--    {xxx} 为占位变量，由 Python 侧注入
-- ----------------------------------------------------------------------------
INSERT INTO `bb_prompt_template` (`code`, `name`, `content`, `variables`, `version`, `is_active`, `builtin`, `remark`) VALUES

-- 4.1 知识点树抽取 -----------------------------------------------------------
('CLASSIFY_TAG', '知识点树抽取', '你是资深课程知识体系设计专家。下面是《{kb_name}》学习资料的内容。

【任务】抽取一份层级化知识点树，最多 3 层，用于给题目分类。

【要求】
1. 顶层是该课程的主要模块（如 Spring Boot、Redis、Spring Cloud、MyBatis），数量控制在 5~12 个
2. 第二层是该模块下的核心考点，每个模块 3~8 个
3. 第三层只在确有必要时出现，不要为了凑层级而拆分
4. 命名必须用课程/技术栈的标准术语，2~10 个字，不要写成句子
5. 粒度要能承载题目：太粗（如 Java 基础）无法定位薄弱点，太细（如 String 的 substring 第二个参数含义）出不了几道题
6. 严禁编造资料中不存在的内容；资料没覆盖的模块不要出现
7. description 用一句话说明这个知识点包含什么，20 字以内

【资料内容】
---
{content}
---

严格只输出 JSON，不要任何解释、不要 markdown 代码块：
{"tags":[{"name":"Spring Boot","description":"Spring 的快速开发框架","children":[{"name":"自动装配原理","description":"@EnableAutoConfiguration 与 SPI 机制","children":[]}]}]}',
 JSON_ARRAY(JSON_OBJECT('name','kb_name','desc','知识库名称'), JSON_OBJECT('name','content','desc','文档全文或大纲')),
 1, 1, 1, '文档入库时调用，生成 bb_tag 树'),

-- 4.2 分块打标 ---------------------------------------------------------------
('CHUNK_TAG', '分块知识点打标', '你是学习资料的标注员。下面给出候选知识点列表和一段资料原文。

【任务】判断这段原文主要讲解哪些知识点，返回命中的知识点 ID。

【规则】
1. 只选真正在讲的知识点，最多选 3 个，宁少勿滥
2. 如果原文是过渡段落、目录、习题答案、无关内容，返回空数组
3. 优先选最具体的知识点，不要同时选上位的模块名。例如原文在讲 @Conditional 条件装配，就选「自动装配原理」，不要再选「Spring Boot」
4. 只允许从候选列表里选，禁止自己造 ID

【候选知识点】（格式 id: 名称 - 说明）
{candidate_tags}

【原文】
---
{chunk_content}
---

严格只输出 JSON：{"tagIds":[12,15],"reason":"该段主要讲解自动装配的条件注解机制"}',
 JSON_ARRAY(JSON_OBJECT('name','candidate_tags','desc','候选知识点列表'), JSON_OBJECT('name','chunk_content','desc','分块原文')),
 1, 1, 1, '文档入库时逐块调用，建立 bb_chunk_tag'),

-- 4.3 出题 -------------------------------------------------------------------
('QUESTION_GEN', 'AI 出题（核心）', '你是一位资深《{kb_name}》课程命题老师，正在为一名学生准备自测题。

【命题材料】以下是从教材中检索出的原文片段，你的题目必须严格基于这些材料，不得使用材料之外的知识：
{context}

【命题要求】
- 本次生成 {count} 道题
- 覆盖知识点：{tags}
- 题型配比：{q_type_ratio}
- 难度配比：{difficulty_ratio}

【硬性规则】
1. 每道题的答案必须能在【命题材料】中找到明确依据，禁止出材料里没有的内容。宁可少出，不可超纲
2. 每道题的 sourceChunkIds 必须填写你实际依据的分片 ID，且这些 ID 必须来自【命题材料】
3. 单选题恰好 4 个选项；多选题 4~5 个选项、正确答案 2~3 个；判断题的 answer 只能是「正确」或「错误」
4. 干扰项必须有迷惑性，要基于学生常见误解来设计，不能出现一眼就看出的荒谬选项
5. 主观题（名词解释/简答/论述/对比辨析）必须给 rubric，每条要点带分值，分值之和必须等于该题总分
6. 代码题必须给出完整可读的代码片段（放在 codeSnippet），答案里写清关键 API、执行结果和原理
7. 难度：1 易（原文直接能查到）2 中（需要理解或跨段落综合）3 难（需要推理、对比或易混淆点辨析）
8. 题干要具体、可回答，禁止「请论述一下 XX」这类过大的题
9. 题目之间不要重复考察同一个细节，注意知识点覆盖面
10. analysis 要写清这个考点为什么重要、易错在哪，不要复述答案

【题型代码】SINGLE 单选 | MULTI 多选 | JUDGE 判断 | BLANK 填空 | TERM 名词解释 | SHORT 简答 | ESSAY 论述 | CODE 代码题 | COMPARE 对比辨析

严格只输出 JSON，不要任何解释、不要 markdown 代码块：
{"questions":[{"qType":"SINGLE","difficulty":2,"stem":"下列关于 Redis 缓存穿透的说法，正确的是？","options":[{"key":"A","content":"..."},{"key":"B","content":"..."},{"key":"C","content":"..."},{"key":"D","content":"..."}],"answer":"B","analysis":"...","codeSnippet":null,"rubric":null,"fullScore":5,"tagIds":[12],"sourceChunkIds":[5521]},{"qType":"SHORT","difficulty":3,"stem":"简述 Redis 缓存击穿的成因与解决方案。","options":null,"answer":"成因：热点 key 在失效瞬间大量并发请求穿透到数据库。方案：①互斥锁 ②逻辑过期 ③热点数据不设过期时间并提前预热。","analysis":"高频面试点，学生最容易把击穿和雪崩混为一谈。","codeSnippet":null,"rubric":[{"point":"说出成因是单个热点 key 失效","score":3},{"point":"答出互斥锁方案","score":3},{"point":"答出逻辑过期方案","score":2},{"point":"提到提前预热或不设过期时间","score":2}],"fullScore":10,"tagIds":[12],"sourceChunkIds":[5521]}]}',
 JSON_ARRAY(
   JSON_OBJECT('name','kb_name','desc','知识库名称'),
   JSON_OBJECT('name','context','desc','检索出的原文片段，含 chunkId'),
   JSON_OBJECT('name','count','desc','本次题量'),
   JSON_OBJECT('name','tags','desc','覆盖的知识点名称列表'),
   JSON_OBJECT('name','q_type_ratio','desc','题型配比'),
   JSON_OBJECT('name','difficulty_ratio','desc','难度配比')),
 1, 1, 1, '⭐ 核心模板。改这里的效果远大于改代码'),

-- 4.4 主观题判分 -------------------------------------------------------------
('GRADING_SUBJECTIVE', '主观题判分', '你是一位严谨的阅卷老师，需要按评分要点给学生答案打分。

【题目】
{stem}

【参考答案】
{reference_answer}

【评分要点 rubric】
{rubric}

【教材原文依据】
{context}

【学生答案】
{user_answer}

【评分规则】
1. 逐条对照 rubric 判断是否命中。语义等价即算命中，不要求字面一致；学生用自己的话说对就算对
2. 每条要点按 0 / 满分 计分。仅当该要点分值 ≥3 且学生答出了核心的一半时，可给一半分并四舍五入到 0.5
3. 总分 = 命中要点得分之和，不得超过本题满分 {full_score}
4. 学生答案中明显错误的表述要单独列入 wrongPoints 并给出 correction，即使总分不为 0 也要列
5. 参考答案里有、但学生没答的关键点，列入 missPoints 并给出 hint，告诉学生「差在哪、怎么补」
6. citations 只能引用【教材原文依据】中真实存在的 chunkId，严禁编造。没有依据就返回空数组
7. 学生完全没作答时，score 为 0，missPoints 列出全部要点，feedback 写「未作答」
8. feedback 要具体，指出具体缺了什么、和标准答案差在哪。禁止写「回答基本正确」「还需加强」这类空话

严格只输出 JSON，不要任何解释、不要 markdown 代码块：
{"score":7,"hitPoints":[{"point":"答出成因是单个热点 key 失效","score":3}],"missPoints":[{"point":"互斥锁方案","hint":"你描述了现象，但没答出解决办法"}],"wrongPoints":[{"point":"把击穿说成多个 key 同时失效","correction":"那是雪崩；击穿强调单个热点 key 失效瞬间的并发穿透"}],"citations":[{"chunkId":5521,"quote":"缓存击穿是指某个热点 key 在失效的瞬间……"}],"feedback":"三个概念的区分讲清楚了，扣分主要在解决方案部分：击穿和雪崩的应对手段都缺失，而这是本考点的后半段。"}',
 JSON_ARRAY(
   JSON_OBJECT('name','stem','desc','题干'),
   JSON_OBJECT('name','reference_answer','desc','参考答案'),
   JSON_OBJECT('name','rubric','desc','评分要点'),
   JSON_OBJECT('name','context','desc','检索出的原文依据'),
   JSON_OBJECT('name','user_answer','desc','学生答案'),
   JSON_OBJECT('name','full_score','desc','本题满分')),
 1, 1, 1, '判分必须给依据，否则用户不会信'),

-- 4.5 题目自检（防幻觉） -----------------------------------------------------
('SELF_CHECK', '题目自检（防幻觉）', '你是题库质检员。下面是一道 AI 生成的题目，以及它声称依据的原文片段。

【任务】判断这道题是否合格。只要命中下列任一情况，就判 pass=false。

【不合格的情况】
1. 题目的答案无法从原文片段中推出（超纲 / 幻觉）
2. 题目表述有歧义，存在多个同样合理的答案
3. 选择题有多个选项都正确，或一个正确选项都没有
4. 填空题答案不唯一，且题干没有做限定
5. 题干与自身给出的答案相矛盾
6. 题干出现「根据材料」之类措辞，但材料里根本没有对应内容
7. 代码题存在明显的技术性错误（API 用错、输出结果写错）
8. rubric 各要点分值之和与 fullScore 不一致

【题目】
{question_json}

【原文片段】
{context}

严格只输出 JSON，不要任何解释：
{"pass":true,"score":0.95,"reason":"答案可在第 2 个片段中找到明确依据，选项设置无歧义"}',
 JSON_ARRAY(JSON_OBJECT('name','question_json','desc','待检题目 JSON'), JSON_OBJECT('name','context','desc','声称依据的原文片段')),
 1, 1, 1, '出题后逐题调用，不通过的题直接丢弃并补生成'),

-- 4.6 口述复述核对（费曼模式） ----------------------------------------------
('RECITE_CHECK', '口述复述核对（费曼模式）', '你正在帮学生做「口述复述」检测。学生刚刚用自己的话复述了一段学习材料。

【原文】
{content}

【学生复述】（来自语音转写，可能含同音错别字和口语化表达，请宽容处理）
{user_recite}

【任务】
1. 把原文拆成若干个关键信息点（5~12 个，视原文长度而定）
2. 判断学生的复述覆盖了哪些、漏了哪些、哪些说错了
3. 给出覆盖度得分 0~100

【判分注意】
- 语音转写会有同音错字，例如「缓存击穿」被转成「缓存基础」，要结合上下文理解为正确答案，不要判错
- 学生用自己的话表达即视为命中，不要求与原文措辞一致
- 复述顺序与原文不同不扣分
- 表达啰嗦但内容正确不扣分
- 只遗漏细枝末节不重扣，只遗漏核心结论重扣

严格只输出 JSON，不要任何解释、不要 markdown 代码块：
{"coverageScore":75,"hitPoints":["缓存穿透的定义","布隆过滤器的解决方案"],"missPoints":["缓存雪崩与击穿的区别"],"wrongPoints":[{"point":"把击穿说成大量 key 同时过期","correction":"那是雪崩，击穿强调单个热点 key"}],"feedback":"主体概念复述准确，但三个缓存问题的对比关系没讲清楚，建议重点回看 5.3 节的对照表。"}',
 JSON_ARRAY(JSON_OBJECT('name','content','desc','原文'), JSON_OBJECT('name','user_recite','desc','学生复述文本')),
 1, 1, 1, '费曼模式：给一段原文让学生口述，AI 核对覆盖度')
ON DUPLICATE KEY UPDATE `content` = VALUES(`content`);

-- ----------------------------------------------------------------------------
-- 5. 系统设置
-- ----------------------------------------------------------------------------
INSERT INTO `bb_setting` (`skey`, `svalue`, `remark`) VALUES
  ('sys.app_name',              '背备不悲', '页面标题'),
  ('sys.default_kb_id',         '0',        '默认知识库 ID'),
  ('ai.default_embedding_model','bge-m3',   '默认向量模型，创建知识库时使用'),
  ('milvus.collection_prefix',  'bb_chunk', 'Milvus collection 前缀，最终为 bb_chunk_{embedding_model}'),
  ('milvus.partition_prefix',   'kb_',      'Milvus partition 前缀，最终为 kb_{kbId}'),
  ('milvus.host',               '192.168.1.100', 'Milvus 所在主机的 IP（占位符，改成你自己的）'),
  ('milvus.port',               '19530',    'Milvus gRPC 端口'),
  ('rag.top_k',                 '8',        '每组出题检索的分块数'),
  ('rag.hybrid_enabled',        'true',     '启用稠密向量 + BM25 混合检索'),
  ('rag.rrf_k',                 '60',       'RRF 重排参数'),
  ('chunk.size',                '700',      '分块目标 token 数'),
  ('chunk.overlap',             '105',      '分块重叠 token 数'),
  ('gen.default_count',         '20',       '出题页默认题量'),
  ('gen.max_retry',             '3',        'LLM 返回非法 JSON 时的重试次数'),
  ('gen.self_check_threshold',  '0.75',     '自检质量分低于此值则丢弃该题'),
  ('gen.dedup_similarity',      '0.92',     '与已有题目向量相似度高于此值则判为重复'),
  ('gen.batch_size',            '5',        '每次请求 LLM 生成几道题，太大容易 JSON 截断'),
  ('grade.objective_local',     'true',     '客观题走本地程序判定，不消耗 Token'),
  ('asr.domain',               'exam_answer', 'ASR 领域，启用专有名词热词表'),
  ('asr.max_seconds',           '60',       '单次录音最长秒数'),
  ('asr.hotword_enabled',       'true',     '把知识库专有名词作为 ASR 热词'),
  ('upload.max_size_mb',        '100',      '单文件最大体积'),
  ('upload.allowed_ext',        'pdf,doc,docx,ppt,pptx,txt,md,xlsx,jpg,jpeg,png,bmp,webp', '允许的扩展名'),
  ('upload.ocr_auto',           'true',     '扫描版 PDF 和图片自动走 OCR'),
  ('ffmpeg.path',               'ffmpeg',   'ffmpeg 可执行文件路径，语音转码用'),
  ('review.mastered_streak',    '4',        '连续答对几次视为已掌握'),
  ('review.mastered_interval',  '30',       '间隔达到多少天视为已掌握')
ON DUPLICATE KEY UPDATE `remark` = VALUES(`remark`);

-- ============================================================================
--  初始数据完成
--  下一步：
--   1. 到「设置 → AI 配置」填写 DeepSeek API Key 并测试连通
--   2. 把 sys.milvus.host 改成 Linux 虚拟机的真实 IP
--   3. 启动 beibei-agent，它会自动创建 Milvus collection
-- ============================================================================
