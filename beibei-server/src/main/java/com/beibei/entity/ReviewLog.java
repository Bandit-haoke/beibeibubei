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
 * 复习历史。表 bb_review_log。
 */
@Data
@TableName("bb_review_log")
public class ReviewLog implements Serializable {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long mistakeId;
    private Long userId;
    private Long examId;

    /** SM-2 质量分 0~5 */
    private Integer grade;

    /** 本次得分率 */
    private BigDecimal scoreRate;

    private Integer intervalBefore;
    private Integer intervalAfter;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime reviewedAt;
}
