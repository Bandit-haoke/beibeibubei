package com.beibei.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * 异步任务。表 bb_async_task。
 *
 * <p>文档解析、批量出题、批量判分都可能跑几分钟，统一走这张表 + SSE 推进度。
 * 前端订阅 {@code GET /api/task/{id}/stream}。
 */
@Data
@TableName("bb_async_task")
public class AsyncTask implements Serializable {

    /** 排队中 */
    public static final int STATUS_PENDING = 0;
    /** 运行中 */
    public static final int STATUS_RUNNING = 1;
    /** 成功 */
    public static final int STATUS_SUCCESS = 2;
    /** 失败 */
    public static final int STATUS_FAILED = 3;
    /** 已取消 */
    public static final int STATUS_CANCELED = 4;

    /** 任务类型 */
    public static final String TYPE_INGEST = "INGEST";
    public static final String TYPE_OCR = "OCR";
    public static final String TYPE_TAG_EXTRACT = "TAG_EXTRACT";
    public static final String TYPE_GEN_QUESTION = "GEN_QUESTION";
    public static final String TYPE_GRADING = "GRADING";
    public static final String TYPE_APPEAL = "APPEAL";
    public static final String TYPE_EXPORT = "EXPORT";
    public static final String TYPE_BACKUP = "BACKUP";
    public static final String TYPE_RESTORE = "RESTORE";
    /** 简历解析（模拟面试模块） */
    public static final String TYPE_RESUME_PARSE = "RESUME_PARSE";
    /** 面经生成（录音转写 → 分角色 → 清洗 → 成文） */
    public static final String TYPE_INTERVIEW_NOTE = "INTERVIEW_NOTE";

    @TableId(type = IdType.AUTO)
    private Long id;

    private String taskType;

    /** 关联业务 ID（docId / paperId / examId） */
    private Long bizId;

    private Long userId;

    private Integer status;

    /** 0~100 */
    private Integer progress;

    /** 当前阶段文案，SSE 直接展示给用户 */
    private String stage;

    private String message;

    /** 结果 JSON 字符串 */
    private String resultJson;

    private String errorMsg;

    private LocalDateTime startedAt;
    private LocalDateTime finishedAt;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
}
