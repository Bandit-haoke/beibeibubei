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
 * 知识库 / 科目。表 bb_knowledge_base。
 *
 * <p>{@code embeddingModel} 创建后不可修改 —— 换向量模型会让已入库向量不可比，
 * 只能新建知识库重新入库（设计文档硬约束 1）。
 */
@Data
@TableName("bb_knowledge_base")
public class KnowledgeBase implements Serializable {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;
    private String name;
    private String description;
    private String coverColor;

    /** 向量模型，创建后锁定 */
    private String embeddingModel;

    /** 向量集合名，由 embeddingModel 推导 */
    private String milvusCollection;

    private Integer chunkSize;
    private Integer chunkOverlap;

    private Integer docCount;
    private Integer chunkCount;
    private Integer questionCount;

    /** 1 正常 0 归档 */
    private Integer status;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
