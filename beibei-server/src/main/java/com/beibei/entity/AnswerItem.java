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
 * 逐题作答与判分明细。表 bb_answer_item —— 判分结果的核心载体。
 *
 * <p>「判分必须可解释」这条硬约束就落在 hitPoints / missPoints / wrongPoints / citations
 * 这四个字段上：缺了引用链的判分不允许落库。
 */
@Data
@TableName("bb_answer_item")
public class AnswerItem implements Serializable {

    /** 未判 */
    public static final int METHOD_NONE = 0;
    /** 程序判定（客观题） */
    public static final int METHOD_PROGRAM = 1;
    /** AI 要点判分 */
    public static final int METHOD_AI = 2;
    /** AI 代码审阅 */
    public static final int METHOD_AI_CODE = 3;
    /** 人工 */
    public static final int METHOD_MANUAL = 4;

    /** 无申诉 */
    public static final int APPEAL_NONE = 0;
    /** 已申诉待重判 */
    public static final int APPEAL_PENDING = 1;
    /** 已重判 */
    public static final int APPEAL_DONE = 2;

    public static final int INPUT_TYPING = 1;
    public static final int INPUT_VOICE = 2;

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long examId;
    private Long questionId;

    private String userAnswer;

    /** 语音转写原文，便于回溯（用户在转写后可以再编辑） */
    private String asrText;

    private Integer inputMode;

    private BigDecimal score;
    private BigDecimal fullScore;

    /** 命中要点 JSON */
    private String hitPoints;
    /** 漏掉要点 JSON */
    private String missPoints;
    /** 答错内容 JSON */
    private String wrongPoints;
    /** 引用出处 JSON */
    private String citations;

    private String aiFeedback;

    private Integer gradeMethod;
    private Long aiCallId;

    private Integer appealStatus;
    private String appealReason;
    private BigDecimal appealScore;
    private String appealResult;
    private LocalDateTime appealAt;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
