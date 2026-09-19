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
 * 文档分块。表 bb_doc_chunk。
 *
 * <p>本表是主数据，Milvus 里的是索引副本：{@code milvusPk} 对应 Milvus 集合的主键，
 * partition 为 {@code kb_{kbId}}。删除文档时先删向量再删分块。
 */
@Data
@TableName("bb_doc_chunk")
public class DocChunk implements Serializable {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long docId;
    private Long kbId;

    private Integer chunkIndex;

    private String content;
    private Integer tokenCount;

    /** 起始页码（PDF 用） */
    private Integer pageNo;

    /** 标题路径，如「第3章 > 3.2 Spring Boot > 自动装配」 */
    private String sectionPath;

    /** 原文字符偏移，前端高亮定位用 */
    private Integer charStart;
    private Integer charEnd;

    /** Milvus 主键 */
    private Long milvusPk;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
}
