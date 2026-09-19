package com.beibei.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.math.BigDecimal;

/**
 * 题卷题目明细。表 bb_paper_item。
 */
@Data
@TableName("bb_paper_item")
public class PaperItem implements Serializable {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long paperId;
    private Long questionId;

    private Integer sortOrder;

    /** 本题分值 */
    private BigDecimal score;
}
