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
 * 知识点树节点。表 bb_tag。最多 3 层，每个知识库独立一套。
 */
@Data
@TableName("bb_tag")
public class Tag implements Serializable {

    /** 来源：AI 抽取 */
    public static final int ORIGIN_AI = 1;
    /** 来源：手动创建 */
    public static final int ORIGIN_MANUAL = 2;

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long kbId;

    /** 0 表示根节点 */
    private Long parentId;

    private String name;

    /** 1 / 2 / 3 */
    private Integer level;

    private Integer sortOrder;

    private String description;

    private Integer origin;

    private Integer chunkCount;
    private Integer questionCount;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
