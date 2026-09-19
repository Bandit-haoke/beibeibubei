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
 * 题卷。表 bb_paper。
 */
@Data
@TableName("bb_paper")
public class Paper implements Serializable {

    /** 生成中 */
    public static final int STATUS_GENERATING = 0;
    /** 待审 */
    public static final int STATUS_PENDING_REVIEW = 1;
    /** 可用 */
    public static final int STATUS_READY = 2;
    /** 生成失败 */
    public static final int STATUS_FAILED = 3;

    /** 来源：AI 生成 */
    public static final int SOURCE_AI = 1;
    /** 来源：手动组卷 */
    public static final int SOURCE_MANUAL = 2;
    /** 来源：错题重考 */
    public static final int SOURCE_MISTAKE = 3;
    /** 来源：随机练习 */
    public static final int SOURCE_RANDOM = 4;

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long kbId;
    private Long userId;

    private String title;

    private Integer source;

    private Integer totalCount;
    private BigDecimal totalScore;

    /** 题型配比 JSON */
    private String qTypeRatio;

    /** 难度配比 JSON */
    private String difficultyRatio;

    /** 覆盖的知识点 ID JSON 数组 */
    private String tagIds;

    /** 限时秒数，0 不限时 */
    private Integer durationLimit;

    private Integer status;

    private Long genTaskId;
    private Long providerId;

    /** 生成统计 JSON {requested,generated,saved,...} */
    private String genSummary;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
