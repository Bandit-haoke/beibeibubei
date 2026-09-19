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
 * 面试对话轮次。表 bb_interview_turn。
 *
 * <p>一次「问答」= 两行：面试官提问（role=1）+ 候选人回答（role=2）。
 * 面试官那行带 basedOn 与 expects，回答那行带 score 与 feedbackJson。
 *
 * <p>可追溯性就落在这张表上：每个问题都能回答「为什么问这个」
 * （basedOn 指向简历里的具体一段），每个分数都能回答「凭什么给这个分」
 * （feedbackJson 里是五维明细与点评）。
 */
@Data
@TableName("bb_interview_turn")
public class InterviewTurn implements Serializable {

    /** 面试官 */
    public static final int ROLE_INTERVIEWER = 1;
    /** 候选人 */
    public static final int ROLE_CANDIDATE = 2;

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long interviewId;

    /** 从 1 开始的顺序号 */
    private Integer seq;

    private Integer role;

    private String content;

    /** INTRO / PROJECT / TECH / FOLLOWUP / SCENARIO / BEHAVIOR */
    private String questionType;

    /** 本题基于简历里的哪一段（可追溯） */
    private String basedOn;

    /** 期望回答覆盖的要点（JSON 数组） */
    private String expects;

    private BigDecimal score;

    /** 五维评分与点评（JSON） */
    private String feedbackJson;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
}
