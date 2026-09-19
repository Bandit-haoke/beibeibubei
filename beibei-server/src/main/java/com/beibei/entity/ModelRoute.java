package com.beibei.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * 任务 → 模型路由。表 bb_model_route。
 *
 * <p>「出题用强模型、分类用便宜模型」的落地点。
 */
@Data
@TableName("bb_model_route")
public class ModelRoute implements Serializable {

    public static final String TASK_QUESTION_GEN = "QUESTION_GEN";
    public static final String TASK_GRADING = "GRADING";
    public static final String TASK_CLASSIFY = "CLASSIFY";
    public static final String TASK_CHUNK_TAG = "CHUNK_TAG";
    public static final String TASK_SELF_CHECK = "SELF_CHECK";
    public static final String TASK_RECITE_CHECK = "RECITE_CHECK";
    public static final String TASK_ASR = "ASR";

    @TableId(type = IdType.AUTO)
    private Long id;

    private String taskType;

    private Long providerId;

    /** 主模型失败时的降级目标 */
    private Long fallbackProviderId;

    private String remark;

    private LocalDateTime updatedAt;
}