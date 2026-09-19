-- ============================================================================
--  背备不悲 (BeiBeiBuBei) · 数据库建表脚本
--  MySQL 8.0+ / utf8mb4 / 表前缀 bb_
--  说明：不使用物理外键（逻辑外键，由应用层保证），便于数据修复与批量导入
--        向量数据不在 MySQL，见 Milvus 集合设计（docs/02-数据库设计.md）
-- ============================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

CREATE DATABASE IF NOT EXISTS `beibei`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE `beibei`;

-- ----------------------------------------------------------------------------
-- 1. bb_user 用户（单人自用阶段只有一个 id=1 的账号，保留表结构便于扩展）
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_user`;
CREATE TABLE `bb_user` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `username`      VARCHAR(64)     NOT NULL COMMENT '登录名',
  `password_hash` VARCHAR(128)    NOT NULL DEFAULT '' COMMENT 'BCrypt 哈希',
  `nickname`      VARCHAR(64)     NOT NULL DEFAULT '' COMMENT '昵称',
  `avatar`        VARCHAR(300)    NOT NULL DEFAULT '' COMMENT '头像路径',
  `daily_goal`    INT             NOT NULL DEFAULT 20 COMMENT '每日目标题量，用于打卡',
  `streak_days`   INT             NOT NULL DEFAULT 0  COMMENT '连续打卡天数',
  `last_active_date` DATE         DEFAULT NULL COMMENT '最后活跃日期',
  `status`        TINYINT         NOT NULL DEFAULT 1 COMMENT '1 正常 0 禁用',
  `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户';

-- ----------------------------------------------------------------------------
-- 2. bb_knowledge_base 知识库 / 科目
--    embedding_model 创建后不可修改 —— 向量空间不可混用的硬约束（约束 1）
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_knowledge_base`;
CREATE TABLE `bb_knowledge_base` (
  `id`               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`          BIGINT UNSIGNED NOT NULL DEFAULT 1,
  `name`             VARCHAR(100)    NOT NULL COMMENT '如 JavaWeb 开发',
  `description`      VARCHAR(500)    NOT NULL DEFAULT '',
  `cover_color`      VARCHAR(20)     NOT NULL DEFAULT '#4C7CF3' COMMENT '卡片主题色',
  `embedding_model`  VARCHAR(64)     NOT NULL DEFAULT 'bge-m3' COMMENT '向量模型，创建后锁定不可改',
  `milvus_collection` VARCHAR(128)   NOT NULL DEFAULT '' COMMENT '由 embedding_model 推导，如 bb_chunk_bge_m3',
  `chunk_size`       INT             NOT NULL DEFAULT 700 COMMENT '分块目标 token 数',
  `chunk_overlap`    INT             NOT NULL DEFAULT 105 COMMENT '分块重叠 token 数(15%)',
  `doc_count`        INT             NOT NULL DEFAULT 0,
  `chunk_count`      INT             NOT NULL DEFAULT 0,
  `question_count`   INT             NOT NULL DEFAULT 0,
  `status`           TINYINT         NOT NULL DEFAULT 1 COMMENT '1 正常 0 归档',
  `created_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user_status` (`user_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库/科目';

-- ----------------------------------------------------------------------------
-- 3. bb_document 文档
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_document`;
CREATE TABLE `bb_document` (
  `id`           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `kb_id`        BIGINT UNSIGNED NOT NULL,
  `user_id`      BIGINT UNSIGNED NOT NULL DEFAULT 1,
  `file_name`    VARCHAR(255)    NOT NULL COMMENT '原始文件名',
  `file_path`    VARCHAR(500)    NOT NULL DEFAULT '' COMMENT '存储路径 data/upload/{kbId}/{uuid}.{ext}',
  `file_type`    VARCHAR(20)     NOT NULL DEFAULT '' COMMENT 'pdf/docx/doc/pptx/txt/md/image/xlsx',
  `file_size`    BIGINT          NOT NULL DEFAULT 0 COMMENT '字节',
  `file_hash`    CHAR(64)        NOT NULL DEFAULT '' COMMENT 'SHA-256，上传去重用',
  `source_type`  TINYINT         NOT NULL DEFAULT 1 COMMENT '1 文件 2 图片OCR 3 手动粘贴',
  `status`       TINYINT         NOT NULL DEFAULT 0 COMMENT '0 待处理 1 解析中 2 就绪 3 失败',
  `chunk_count`  INT             NOT NULL DEFAULT 0,
  `page_count`   INT             NOT NULL DEFAULT 0,
  `char_count`   INT             NOT NULL DEFAULT 0,
  `error_msg`    VARCHAR(1000)   NOT NULL DEFAULT '',
  `created_at`   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_kb_hash` (`kb_id`, `file_hash`),
  KEY `idx_kb_status` (`kb_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='上传的文档';

-- ----------------------------------------------------------------------------
-- 4. bb_doc_chunk 文档分块（主数据，Milvus 是索引副本）
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_doc_chunk`;
CREATE TABLE `bb_doc_chunk` (
  `id`           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `doc_id`       BIGINT UNSIGNED NOT NULL,
  `kb_id`        BIGINT UNSIGNED NOT NULL,
  `chunk_index`  INT             NOT NULL DEFAULT 0 COMMENT '文档内序号',
  `content`      MEDIUMTEXT      NOT NULL COMMENT '分块原文',
  `token_count`  INT             NOT NULL DEFAULT 0,
  `page_no`      INT             NOT NULL DEFAULT 0 COMMENT '起始页码',
  `section_path` VARCHAR(500)    NOT NULL DEFAULT '' COMMENT '标题路径 第3章 > 3.2 Spring Boot > 自动装配',
  `char_start`   INT             NOT NULL DEFAULT 0 COMMENT '原文偏移，前端高亮用',
  `char_end`     INT             NOT NULL DEFAULT 0,
  `milvus_pk`    BIGINT          NOT NULL DEFAULT 0 COMMENT 'Milvus 主键，partition=kb_{kbId}',
  `created_at`   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_doc_index` (`doc_id`, `chunk_index`),
  KEY `idx_kb` (`kb_id`),
  KEY `idx_milvus_pk` (`milvus_pk`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档分块';

-- 可选：中文关键词兜底检索（Milvus 2.5 自带 BM25，正常不需要，留作降级方案）
-- ALTER TABLE `bb_doc_chunk` ADD FULLTEXT KEY `ft_content` (`content`) WITH PARSER ngram;

-- ----------------------------------------------------------------------------
-- 5. bb_tag 知识点树（最多 3 层）
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_tag`;
CREATE TABLE `bb_tag` (
  `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `kb_id`          BIGINT UNSIGNED NOT NULL,
  `parent_id`      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '0 为根节点',
  `name`           VARCHAR(100)    NOT NULL COMMENT '如 Redis / Spring Cloud',
  `level`          TINYINT         NOT NULL DEFAULT 1 COMMENT '1/2/3',
  `sort_order`     INT             NOT NULL DEFAULT 0,
  `description`    VARCHAR(500)    NOT NULL DEFAULT '' COMMENT 'AI 生成的考点简介',
  `origin`         TINYINT         NOT NULL DEFAULT 1 COMMENT '1 AI 抽取 2 手动创建',
  `chunk_count`    INT             NOT NULL DEFAULT 0,
  `question_count` INT             NOT NULL DEFAULT 0,
  `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_kb_parent` (`kb_id`, `parent_id`),
  KEY `idx_kb_level` (`kb_id`, `level`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识点树';

-- ----------------------------------------------------------------------------
-- 6. bb_chunk_tag 分块 ↔ 知识点
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_chunk_tag`;
CREATE TABLE `bb_chunk_tag` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `chunk_id`   BIGINT UNSIGNED NOT NULL,
  `tag_id`     BIGINT UNSIGNED NOT NULL,
  `kb_id`      BIGINT UNSIGNED NOT NULL,
  `confidence` DECIMAL(4,3)    NOT NULL DEFAULT 1.000 COMMENT '打标置信度',
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_chunk_tag` (`chunk_id`, `tag_id`),
  KEY `idx_tag` (`tag_id`),
  KEY `idx_kb` (`kb_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='分块知识点关联';

-- ----------------------------------------------------------------------------
-- 7. bb_question 题目主表
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_question`;
CREATE TABLE `bb_question` (
  `id`               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `kb_id`            BIGINT UNSIGNED NOT NULL,
  `q_type`           TINYINT         NOT NULL COMMENT '1单选 2多选 3判断 4填空 5名词解释 6简答 7论述 8代码题 9对比辨析',
  `difficulty`       TINYINT         NOT NULL DEFAULT 2 COMMENT '1易 2中 3难',
  `stem`             TEXT            NOT NULL COMMENT '题干',
  `answer`           TEXT            NOT NULL COMMENT '参考答案',
  `analysis`         TEXT            NOT NULL COMMENT '解析',
  `rubric`           JSON            DEFAULT NULL COMMENT '判分要点 [{"point":"...","score":3}] 主观题必填',
  `code_snippet`     TEXT            DEFAULT NULL COMMENT '代码题代码片段',
  `source_chunk_ids` JSON            DEFAULT NULL COMMENT '依据的分块 ID 数组，溯源用',
  `source_doc_id`    BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `status`           TINYINT         NOT NULL DEFAULT 0 COMMENT '0 DRAFT待审 1 PUBLISHED已发布 2 DISABLED停用',
  `origin`           TINYINT         NOT NULL DEFAULT 1 COMMENT '1 AI生成 2 手动录入',
  `gen_batch_id`     VARCHAR(36)     NOT NULL DEFAULT '' COMMENT '同批生成 UUID，便于整批回滚',
  `quality_score`    DECIMAL(4,3)    NOT NULL DEFAULT 0 COMMENT '自检质量分 0~1',
  `self_check_msg`   VARCHAR(500)    NOT NULL DEFAULT '' COMMENT '自检结论',
  `use_count`        INT             NOT NULL DEFAULT 0,
  `correct_count`    INT             NOT NULL DEFAULT 0,
  `avg_score_rate`   DECIMAL(5,4)    NOT NULL DEFAULT 0 COMMENT '平均得分率，用于难度校准',
  `created_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_kb_status_type` (`kb_id`, `status`, `q_type`),
  KEY `idx_batch` (`gen_batch_id`),
  KEY `idx_doc` (`source_doc_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='题目';

-- ----------------------------------------------------------------------------
-- 8. bb_question_option 选择题选项
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_question_option`;
CREATE TABLE `bb_question_option` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `question_id` BIGINT UNSIGNED NOT NULL,
  `option_key`  CHAR(2)         NOT NULL COMMENT 'A/B/C/D/E',
  `content`     VARCHAR(1000)   NOT NULL,
  `is_correct`  TINYINT         NOT NULL DEFAULT 0,
  `sort_order`  INT             NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_q_key` (`question_id`, `option_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='选择题选项';

-- ----------------------------------------------------------------------------
-- 9. bb_question_tag 题目 ↔ 知识点
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_question_tag`;
CREATE TABLE `bb_question_tag` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `question_id` BIGINT UNSIGNED NOT NULL,
  `tag_id`      BIGINT UNSIGNED NOT NULL,
  `kb_id`       BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_q_tag` (`question_id`, `tag_id`),
  KEY `idx_tag` (`tag_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='题目知识点关联';

-- ----------------------------------------------------------------------------
-- 10. bb_paper 题卷
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_paper`;
CREATE TABLE `bb_paper` (
  `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `kb_id`          BIGINT UNSIGNED NOT NULL,
  `user_id`        BIGINT UNSIGNED NOT NULL DEFAULT 1,
  `title`          VARCHAR(200)    NOT NULL,
  `source`         TINYINT         NOT NULL DEFAULT 1 COMMENT '1 AI生成 2 手动组卷 3 错题重考 4 随机练习',
  `total_count`    INT             NOT NULL DEFAULT 0,
  `total_score`    DECIMAL(6,1)    NOT NULL DEFAULT 0,
  `q_type_ratio`   JSON            DEFAULT NULL COMMENT '题型配比',
  `difficulty_ratio` JSON          DEFAULT NULL COMMENT '难度配比',
  `tag_ids`        JSON            DEFAULT NULL COMMENT '覆盖的知识点',
  `duration_limit` INT             NOT NULL DEFAULT 0 COMMENT '限时秒数，0 不限时',
  `status`         TINYINT         NOT NULL DEFAULT 0 COMMENT '0 生成中 1 待审 2 可用 3 失败',
  `gen_task_id`    BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `provider_id`    BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '生成时使用的厂商，便于复现',
  `gen_summary`    JSON            DEFAULT NULL COMMENT '生成统计 {requested,generated,droppedBySelfCheck,droppedByDedup}',
  `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_kb_status` (`kb_id`, `status`),
  KEY `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='题卷';

-- ----------------------------------------------------------------------------
-- 11. bb_paper_item 题卷题目明细
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_paper_item`;
CREATE TABLE `bb_paper_item` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `paper_id`    BIGINT UNSIGNED NOT NULL,
  `question_id` BIGINT UNSIGNED NOT NULL,
  `sort_order`  INT             NOT NULL DEFAULT 0,
  `score`       DECIMAL(5,1)    NOT NULL DEFAULT 0 COMMENT '本题分值',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_paper_question` (`paper_id`, `question_id`),
  KEY `idx_paper_sort` (`paper_id`, `sort_order`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='题卷题目明细';

-- ----------------------------------------------------------------------------
-- 12. bb_exam_record 答卷
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_exam_record`;
CREATE TABLE `bb_exam_record` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `paper_id`      BIGINT UNSIGNED NOT NULL,
  `kb_id`         BIGINT UNSIGNED NOT NULL,
  `user_id`       BIGINT UNSIGNED NOT NULL DEFAULT 1,
  `title`         VARCHAR(200)    NOT NULL DEFAULT '' COMMENT '快照标题',
  `status`        TINYINT         NOT NULL DEFAULT 0 COMMENT '0 进行中 1 已交卷 2 判分中 3 已判完 4 判分失败',
  `exam_mode`     TINYINT         NOT NULL DEFAULT 1 COMMENT '1 练习(即时解析) 2 考试(交卷后看) 3 复习',
  `total_score`   DECIMAL(6,1)    NOT NULL DEFAULT 0,
  `got_score`     DECIMAL(6,1)    NOT NULL DEFAULT 0,
  `correct_count` INT             NOT NULL DEFAULT 0,
  `wrong_count`   INT             NOT NULL DEFAULT 0,
  `duration_sec`  INT             NOT NULL DEFAULT 0,
  `grade_task_id` BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `started_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `submitted_at`  DATETIME        DEFAULT NULL,
  `graded_at`     DATETIME        DEFAULT NULL,
  `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_paper` (`paper_id`),
  KEY `idx_user_status` (`user_id`, `status`),
  KEY `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='答卷';

-- ----------------------------------------------------------------------------
-- 13. bb_answer_item 逐题作答 + 判分明细（判分核心表）
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_answer_item`;
CREATE TABLE `bb_answer_item` (
  `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `exam_id`        BIGINT UNSIGNED NOT NULL,
  `question_id`    BIGINT UNSIGNED NOT NULL,
  `user_answer`    TEXT            DEFAULT NULL COMMENT '用户答案',
  `asr_text`       TEXT            DEFAULT NULL COMMENT '语音转写原文，便于回溯',
  `input_mode`     TINYINT         NOT NULL DEFAULT 1 COMMENT '1 打字 2 语音',
  `score`          DECIMAL(5,1)    NOT NULL DEFAULT 0,
  `full_score`     DECIMAL(5,1)    NOT NULL DEFAULT 0,
  `hit_points`     JSON            DEFAULT NULL COMMENT '命中要点 [{"point":"...","score":2}]',
  `miss_points`    JSON            DEFAULT NULL COMMENT '漏掉要点 [{"point":"...","hint":"..."}]',
  `wrong_points`   JSON            DEFAULT NULL COMMENT '错误表述 [{"point":"...","correction":"..."}]',
  `citations`      JSON            DEFAULT NULL COMMENT '引用出处 [{"chunkId":5521,"docId":12,"pageNo":88,"sectionPath":"...","snippet":"..."}]',
  `ai_feedback`    TEXT            DEFAULT NULL COMMENT 'AI 评语',
  `grade_method`   TINYINT         NOT NULL DEFAULT 0 COMMENT '0 未判 1 程序判定 2 AI要点判分 3 AI代码审阅 4 人工',
  `ai_call_id`     BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `appeal_status`  TINYINT         NOT NULL DEFAULT 0 COMMENT '0 无 1 已申诉待重判 2 已重判',
  `appeal_reason`  VARCHAR(1000)   NOT NULL DEFAULT '',
  `appeal_score`   DECIMAL(5,1)    DEFAULT NULL,
  `appeal_result`  JSON            DEFAULT NULL,
  `appeal_at`      DATETIME        DEFAULT NULL,
  `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_exam_question` (`exam_id`, `question_id`),
  KEY `idx_question` (`question_id`),
  KEY `idx_appeal` (`appeal_status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='逐题作答与判分明细';

-- ----------------------------------------------------------------------------
-- 14. bb_mistake 错题本（SM-2 间隔重复参数）
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_mistake`;
CREATE TABLE `bb_mistake` (
  `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`        BIGINT UNSIGNED NOT NULL DEFAULT 1,
  `kb_id`          BIGINT UNSIGNED NOT NULL,
  `question_id`    BIGINT UNSIGNED NOT NULL,
  `wrong_count`    INT             NOT NULL DEFAULT 1 COMMENT '累计答错次数',
  `right_streak`   INT             NOT NULL DEFAULT 0 COMMENT '连续答对次数',
  `last_wrong_at`  DATETIME        DEFAULT NULL,
  `ease_factor`    DECIMAL(4,2)    NOT NULL DEFAULT 2.50 COMMENT '难度系数，下限 1.30',
  `interval_days`  INT             NOT NULL DEFAULT 1 COMMENT '当前复习间隔天数',
  `repetitions`    INT             NOT NULL DEFAULT 0 COMMENT '连续答对轮次',
  `next_review_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '下次复习时间',
  `mastered`       TINYINT         NOT NULL DEFAULT 0 COMMENT '1 已掌握，移出错题本',
  `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_question` (`user_id`, `question_id`),
  KEY `idx_review` (`user_id`, `mastered`, `next_review_at`),
  KEY `idx_kb` (`kb_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='错题本';

-- ----------------------------------------------------------------------------
-- 15. bb_review_log 复习历史
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_review_log`;
CREATE TABLE `bb_review_log` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `mistake_id`      BIGINT UNSIGNED NOT NULL,
  `user_id`         BIGINT UNSIGNED NOT NULL DEFAULT 1,
  `exam_id`         BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `grade`           TINYINT         NOT NULL DEFAULT 0 COMMENT 'SM-2 质量分 0~5',
  `score_rate`      DECIMAL(5,4)    NOT NULL DEFAULT 0 COMMENT '本次得分率',
  `interval_before` INT             NOT NULL DEFAULT 0,
  `interval_after`  INT             NOT NULL DEFAULT 0,
  `reviewed_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_mistake` (`mistake_id`),
  KEY `idx_reviewed` (`reviewed_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='复习历史';

-- ----------------------------------------------------------------------------
-- 16. bb_ai_provider AI 厂商配置
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_ai_provider`;
CREATE TABLE `bb_ai_provider` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name`            VARCHAR(60)     NOT NULL COMMENT '展示名 DeepSeek 官方',
  `vendor`          VARCHAR(30)     NOT NULL COMMENT 'deepseek/qwen/zhipu/moonshot/openai/claude/ollama/xfyun/aliyun/local',
  `protocol`        VARCHAR(20)     NOT NULL DEFAULT 'openai-compatible' COMMENT 'openai-compatible/anthropic/gemini/ollama/custom',
  `base_url`        VARCHAR(300)    NOT NULL DEFAULT '',
  `model`           VARCHAR(80)     NOT NULL DEFAULT '',
  `api_key_enc`     VARCHAR(500)    NOT NULL DEFAULT '' COMMENT 'AES 加密存储，接口返回时脱敏',
  `api_secret_enc`  VARCHAR(500)    NOT NULL DEFAULT '' COMMENT 'ASR 厂商的 Secret',
  `app_id`          VARCHAR(80)     NOT NULL DEFAULT '' COMMENT '讯飞/阿里 ASR 的 AppId',
  `capability`      VARCHAR(50)     NOT NULL DEFAULT 'CHAT' COMMENT 'CHAT/EMBED/ASR/OCR，多能力用逗号分隔',
  `extra_params`    JSON            DEFAULT NULL COMMENT 'temperature、max_tokens、top_p',
  `enabled`         TINYINT         NOT NULL DEFAULT 1,
  `priority`        INT             NOT NULL DEFAULT 100 COMMENT '越小越优先，用于降级',
  `is_active`       TINYINT         NOT NULL DEFAULT 0 COMMENT '同能力下当前选中',
  `locked`          TINYINT         NOT NULL DEFAULT 0 COMMENT '1 锁定不可切换（本地 embedding 用）',
  `last_test_at`    DATETIME        DEFAULT NULL,
  `last_test_ok`    TINYINT         NOT NULL DEFAULT 0,
  `last_test_msg`   VARCHAR(500)    NOT NULL DEFAULT '',
  `remark`          VARCHAR(300)    NOT NULL DEFAULT '',
  `created_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_capability` (`capability`, `enabled`, `priority`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 厂商配置';

-- ----------------------------------------------------------------------------
-- 17. bb_model_route 任务 → 模型路由
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_model_route`;
CREATE TABLE `bb_model_route` (
  `id`                   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `task_type`            VARCHAR(40)     NOT NULL COMMENT 'QUESTION_GEN/GRADING/CLASSIFY/CHUNK_TAG/SELF_CHECK/RECITE_CHECK/ASR',
  `provider_id`          BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `fallback_provider_id` BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '主模型失败时的降级目标',
  `remark`               VARCHAR(200)    NOT NULL DEFAULT '',
  `updated_at`           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_task_type` (`task_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='任务模型路由';

-- ----------------------------------------------------------------------------
-- 18. bb_prompt_template Prompt 模板（带版本）
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_prompt_template`;
CREATE TABLE `bb_prompt_template` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `code`       VARCHAR(60)     NOT NULL COMMENT 'QUESTION_GEN/GRADING_SUBJECTIVE/CLASSIFY_TAG/...',
  `name`       VARCHAR(120)    NOT NULL,
  `content`    MEDIUMTEXT      NOT NULL COMMENT '模板正文，{var} 为占位变量',
  `variables`  JSON            DEFAULT NULL COMMENT '可用变量说明 [{"name":"kb_name","desc":"知识库名"}]',
  `version`    INT             NOT NULL DEFAULT 1,
  `is_active`  TINYINT         NOT NULL DEFAULT 1,
  `builtin`    TINYINT         NOT NULL DEFAULT 1 COMMENT '1 内置 0 用户新增',
  `remark`     VARCHAR(300)    NOT NULL DEFAULT '',
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_code_version` (`code`, `version`),
  KEY `idx_code_active` (`code`, `is_active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Prompt 模板';

-- ----------------------------------------------------------------------------
-- 19. bb_ai_call_log AI 调用日志（Token 与成本）
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_ai_call_log`;
CREATE TABLE `bb_ai_call_log` (
  `id`                BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `task_type`         VARCHAR(40)     NOT NULL DEFAULT '' COMMENT 'QUESTION_GEN/GRADING/...',
  `provider_id`       BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `vendor`            VARCHAR(30)     NOT NULL DEFAULT '',
  `model`             VARCHAR(80)     NOT NULL DEFAULT '',
  `biz_type`          VARCHAR(40)     NOT NULL DEFAULT '' COMMENT 'PAPER/EXAM/INVEST/DOC',
  `biz_id`            BIGINT UNSIGNED NOT NULL DEFAULT 0,
  `prompt_tokens`     INT             NOT NULL DEFAULT 0,
  `completion_tokens` INT             NOT NULL DEFAULT 0,
  `total_tokens`      INT             NOT NULL DEFAULT 0,
  `cost`              DECIMAL(12,6)   NOT NULL DEFAULT 0 COMMENT '估算费用(元)',
  `latency_ms`        INT             NOT NULL DEFAULT 0,
  `success`           TINYINT         NOT NULL DEFAULT 1,
  `retry_times`       INT             NOT NULL DEFAULT 0,
  `error_msg`         VARCHAR(1000)   NOT NULL DEFAULT '',
  `request_preview`   VARCHAR(2000)   NOT NULL DEFAULT '',
  `response_preview`  VARCHAR(2000)   NOT NULL DEFAULT '',
  `created_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_created` (`created_at`),
  KEY `idx_task_created` (`task_type`, `created_at`),
  KEY `idx_biz` (`biz_type`, `biz_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 调用日志';

-- ----------------------------------------------------------------------------
-- 20. bb_async_task 异步任务
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_async_task`;
CREATE TABLE `bb_async_task` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `task_type`   VARCHAR(40)     NOT NULL COMMENT 'INGEST/OCR/TAG_EXTRACT/GEN_QUESTION/GRADING/APPEAL/EXPORT/BACKUP/RESTORE',
  `biz_id`      BIGINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '关联业务 ID（docId/paperId/examId）',
  `user_id`     BIGINT UNSIGNED NOT NULL DEFAULT 1,
  `status`      TINYINT         NOT NULL DEFAULT 0 COMMENT '0 排队 1 运行 2 成功 3 失败 4 取消',
  `progress`    INT             NOT NULL DEFAULT 0 COMMENT '0~100',
  `stage`       VARCHAR(120)    NOT NULL DEFAULT '' COMMENT '当前阶段文案，SSE 直接展示',
  `message`     VARCHAR(1000)   NOT NULL DEFAULT '',
  `result_json` JSON            DEFAULT NULL,
  `error_msg`   VARCHAR(2000)   NOT NULL DEFAULT '',
  `started_at`  DATETIME        DEFAULT NULL,
  `finished_at` DATETIME        DEFAULT NULL,
  `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_status` (`status`, `created_at`),
  KEY `idx_biz` (`task_type`, `biz_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='异步任务';

-- ----------------------------------------------------------------------------
-- 21. bb_setting 系统设置
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_setting`;
CREATE TABLE `bb_setting` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `skey`       VARCHAR(80)     NOT NULL,
  `svalue`     TEXT            NOT NULL,
  `remark`     VARCHAR(300)    NOT NULL DEFAULT '',
  `updated_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_skey` (`skey`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统设置';

-- ----------------------------------------------------------------------------
-- 22. bb_resume 简历库
--     与学习知识库**完全隔离**：简历不进 Milvus 分块集合、不参与知识点树。
--     raw_text 保留解析出的全文，profile_json 存 AI 抽取的结构化档案。
-- ----------------------------------------------------------------------------
DROP TABLE IF EXISTS `bb_resume`;
CREATE TABLE `bb_resume` (
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
DROP TABLE IF EXISTS `bb_interview`;
CREATE TABLE `bb_interview` (
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
DROP TABLE IF EXISTS `bb_interview_turn`;
CREATE TABLE `bb_interview_turn` (
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

SET FOREIGN_KEY_CHECKS = 1;

-- ============================================================================
--  建表完成，共 24 张表
--  下一步：依次执行 init_data.sql（初始配置）、interview.sql（面试 Prompt 模板）
--  注意：Milvus collection 由 beibei-agent 启动时自动创建，不在 SQL 里
-- ============================================================================
