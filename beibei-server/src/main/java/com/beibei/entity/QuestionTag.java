package com.beibei.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;

/**
 * 题目 ↔ 知识点关联。表 bb_question_tag。
 */
@Data
@TableName("bb_question_tag")
public class QuestionTag implements Serializable {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long questionId;
    private Long tagId;
    private Long kbId;
}
