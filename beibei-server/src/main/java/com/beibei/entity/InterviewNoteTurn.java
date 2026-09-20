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
 * 面经的一句话。表 bb_interview_note_turn。
 *
 * <p>一句话一行，role 只有两种：面试官 / 我。
 * 同时保留 {@code rawText}（转写原文）与 {@code cleanText}（去口语后），
 * 这样用户能看出 AI 到底"洗"掉了什么，而不是只能选择相信。
 */
@Data
@TableName("bb_interview_note_turn")
public class InterviewNoteTurn implements Serializable {

    /** 面试官 */
    public static final int ROLE_INTERVIEWER = 1;
    /** 我（候选人） */
    public static final int ROLE_ME = 2;

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long noteId;

    private Integer seq;

    /** 1 面试官 2 我 */
    private Integer role;

    private Integer startMs;

    private Integer endMs;

    /** 转写原文 */
    private String rawText;

    /** 清洗后文本（去语气词、去重复、修口误） */
    private String cleanText;

    /** 被去掉的口语词，便于人工核对 */
    private String removedWords;

    private String questionType;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
}
