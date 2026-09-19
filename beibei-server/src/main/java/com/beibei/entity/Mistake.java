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
 * 错题本。表 bb_mistake —— 含 SM-2 间隔重复参数。
 *
 * <p>这是「背书」与「刷题」的分界线：判错的题自动进来，
 * 按 nextReviewAt 安排复习，首页推「今日待复习」。
 */
@Data
@TableName("bb_mistake")
public class Mistake implements Serializable {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;
    private Long kbId;
    private Long questionId;

    /** 累计答错次数 */
    private Integer wrongCount;

    /** 连续答对次数 */
    private Integer rightStreak;

    private LocalDateTime lastWrongAt;

    /** 难度系数，初始 2.50，下限 1.30 */
    private BigDecimal easeFactor;

    /** 当前复习间隔（天） */
    private Integer intervalDays;

    /** 连续答对轮次 */
    private Integer repetitions;

    /** 下次复习时间，首页「今日待复习」靠它查 */
    private LocalDateTime nextReviewAt;

    /** 1 = 已掌握，移出错题本 */
    private Integer mastered;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
