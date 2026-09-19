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
 * 简历。表 bb_resume。
 *
 * <p>刻意与学习知识库隔离：简历不进 Milvus 分块集合、不建知识点树、不参与 RAG 检索。
 * 只有「面试报告里的薄弱点 → 出题」这一步才通过 kbId 主动跨到学习模块。
 *
 * <p>rawText 保留解析全文（用于重新抽取档案、人工核对）；
 * profileJson 是 AI 抽出的结构化档案（技能/项目/工作经历/待核实点）。
 */
@Data
@TableName("bb_resume")
public class Resume implements Serializable {

    /** 待解析 */
    public static final int STATUS_PENDING = 0;
    /** 解析中 */
    public static final int STATUS_PARSING = 1;
    /** 就绪 */
    public static final int STATUS_READY = 2;
    /** 解析失败 */
    public static final int STATUS_FAILED = 3;

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long userId;

    private String fileName;

    /** 相对 upload.dir 的路径 */
    private String filePath;

    private Long fileSize;

    private String fileType;

    /** 解析出的简历全文 */
    private String rawText;

    private Integer charCount;

    /** AI 抽取的结构化档案（MySQL JSON 列） */
    private String profileJson;

    private String targetPosition;

    private Integer status;

    private String errorMsg;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
