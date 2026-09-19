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
 * 分块 ↔ 知识点关联。表 bb_chunk_tag。
 */
@Data
@TableName("bb_chunk_tag")
public class ChunkTag implements Serializable {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long chunkId;
    private Long tagId;
    private Long kbId;

    /** 打标置信度 0~1 */
    private BigDecimal confidence;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;
}
