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
 * 一次作答记录（答卷）。表 bb_exam_record。
 */
@Data
@TableName("bb_exam_record")
public class ExamRecord implements Serializable {

    /** 进行中，可续答 */
    public static final int STATUS_ONGOING = 0;
    /** 已交卷，待判分 */
    public static final int STATUS_SUBMITTED = 1;
    /** 判分中 */
    public static final int STATUS_GRADING = 2;
    /** 已判完 */
    public static final int STATUS_GRADED = 3;
    /** 判分失败 */
    public static final int STATUS_FAILED = 4;

    /** 练习：答完一题立刻看解析 */
    public static final int MODE_PRACTICE = 1;
    /** 考试：交卷后统一看结果 */
    public static final int MODE_EXAM = 2;
    /** 复习：来自错题本 */
    public static final int MODE_REVIEW = 3;

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long paperId;
    private Long kbId;
    private Long userId;

    private String title;

    private Integer status;
    private Integer examMode;

    private BigDecimal totalScore;
    private BigDecimal gotScore;

    private Integer correctCount;
    private Integer wrongCount;

    private Integer durationSec;

    private Long gradeTaskId;

    private LocalDateTime startedAt;
    private LocalDateTime submittedAt;
    private LocalDateTime gradedAt;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
}
