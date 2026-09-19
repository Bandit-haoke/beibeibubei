package com.beibei.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;

/**
 * 选择题选项。表 bb_question_option。
 */
@Data
@TableName("bb_question_option")
public class QuestionOption implements Serializable {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long questionId;

    /** A / B / C / D / E */
    private String optionKey;

    private String content;

    private Integer isCorrect;

    private Integer sortOrder;
}
