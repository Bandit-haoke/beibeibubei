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
 * 上传的文档。表 bb_document。
 */
@Data
@TableName("bb_document")
public class Document implements Serializable {

    /** 状态：待处理 */
    public static final int STATUS_PENDING = 0;
    /** 状态：解析中 */
    public static final int STATUS_PARSING = 1;
    /** 状态：就绪 */
    public static final int STATUS_READY = 2;
    /** 状态：失败 */
    public static final int STATUS_FAILED = 3;

    /** 来源：文件上传 */
    public static final int SOURCE_FILE = 1;
    /** 来源：图片 OCR */
    public static final int SOURCE_IMAGE = 2;
    /** 来源：手动粘贴 */
    public static final int SOURCE_PASTE = 3;

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long kbId;
    private Long userId;

    private String fileName;
    private String filePath;
    private String fileType;
    private Long fileSize;

    /** SHA-256，同一知识库内去重 */
    private String fileHash;

    private Integer sourceType;
    private Integer status;

    private Integer chunkCount;
    private Integer pageCount;
    private Integer charCount;

    private String errorMsg;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}
