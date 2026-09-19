package com.beibei.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 模拟面试场次。表 bb_interview。
 *
 * <p>对话内容不在这张表里 —— 在 {@link InterviewTurn}。
 * 这里只放「一场面试」的元信息与最终报告。
 */
@Data
@TableName("bb_interview")
public class Interview implements Serializable {

    /** 待开始 */
    public static final int STATUS_DRAFT = 0;
    /** 进行中 */
    public static final int STATUS_RUNNING = 1;
    /** 已结束 */
    public static final int STATUS_FINISHED = 2;
    /** 失败 */
    public static final int STATUS_FAILED = 3;

    public static final int DIFFICULTY_JUNIOR = 1;
    public static final int DIFFICULTY_MIDDLE = 2;
    public static final int DIFFICULTY_SENIOR = 3;

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;

    private Long resumeId;

    /** 可选：关联的学习知识库，用于「薄弱点 → 出题」 */
    private Long kbId;

    private String jobTitle;

    /** 1 初级 2 中级 3 高级 */
    private Integer difficulty;

    /** 计划轮数（8~12） */
    private Integer maxTurns;

    /** 已完成的问答轮数 */
    private Integer turnCount;

    private Integer status;

    private BigDecimal totalScore;

    private String summary;

    /** 完整评估报告（MySQL JSON 列） */
    private String reportJson;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    private LocalDateTime startedAt;

    private LocalDateTime finishedAt;
}
