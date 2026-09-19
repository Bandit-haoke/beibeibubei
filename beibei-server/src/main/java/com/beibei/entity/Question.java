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
 * 题目。表 bb_question。
 *
 * <p>核心约束：AI 生成的题一律先落成 {@code status=DRAFT}，必须人工审核通过
 * 才转 {@code PUBLISHED}，组卷只捞已发布的。没有这道闸门，题库会迅速变成垃圾场。
 */
@Data
@TableName("bb_question")
public class Question implements Serializable {

    /** 待审草稿 */
    public static final int STATUS_DRAFT = 0;
    /** 已发布，可组卷 */
    public static final int STATUS_PUBLISHED = 1;
    /** 停用 */
    public static final int STATUS_DISABLED = 2;

    /** 来源：AI 生成 */
    public static final int ORIGIN_AI = 1;
    /** 来源：手动录入 */
    public static final int ORIGIN_MANUAL = 2;

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long kbId;

    /** 1单选 2多选 3判断 4填空 5名词解释 6简答 7论述 8代码题 9对比辨析 */
    private Integer qType;

    /** 1易 2中 3难 */
    private Integer difficulty;

    private String stem;
    private String answer;
    private String analysis;

    /** 判分要点 JSON：[{"point":"...","score":3}] */
    private String rubric;

    private String codeSnippet;

    /** 依据的分块 ID JSON 数组，溯源用 */
    private String sourceChunkIds;

    private Long sourceDocId;

    private Integer status;
    private Integer origin;

    /** 同批生成 UUID，便于整批回滚 */
    private String genBatchId;

    /** 自检质量分 0~1 */
    private BigDecimal qualityScore;

    private String selfCheckMsg;

    private Integer useCount;
    private Integer correctCount;
    private BigDecimal avgScoreRate;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
