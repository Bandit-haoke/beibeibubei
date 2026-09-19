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
 * Prompt 模板（带版本）。表 bb_prompt_template。
 *
 * <p>编辑等于插入新版本并把旧版本置为非激活，所以随时可以回滚。
 */
@Data
@TableName("bb_prompt_template")
public class PromptTemplate implements Serializable {

    @TableId(type = IdType.AUTO)
    private Long id;

    /** QUESTION_GEN / GRADING_SUBJECTIVE / CLASSIFY_TAG / CHUNK_TAG / SELF_CHECK / RECITE_CHECK */
    private String code;

    private String name;

    /** 模板正文，{var} 为占位变量 */
    private String content;

    private String variables;

    private Integer version;

    private Integer isActive;

    /** 1 内置 0 用户新增 */
    private Integer builtin;

    private String remark;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
}