package com.beibei.dto;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 文档相关的请求/响应对象。
 */
public final class DocDto {

    private DocDto() {
    }

    /** 文档列表项 */
    public record VO(
            Long id,
            Long kbId,
            String fileName,
            String fileType,
            Long fileSize,
            Integer sourceType,
            Integer status,
            Integer chunkCount,
            Integer pageCount,
            Integer charCount,
            String errorMsg,
            LocalDateTime createdAt
    ) {
    }

    /** 文档详情（含分块预览） */
    public record DetailVO(
            VO doc,
            List<ChunkVO> chunks,
            List<TagBrief> tags
    ) {
    }

    /** 分块 */
    public record ChunkVO(
            Long id,
            Integer chunkIndex,
            String content,
            Integer tokenCount,
            Integer pageNo,
            String sectionPath,
            Long milvusPk,
            List<TagBrief> tags
    ) {
    }

    /** 知识点简要信息 */
    public record TagBrief(
            Long id,
            String name,
            Integer level
    ) {
    }

    /** 手动粘贴文本入库 */
    public record PasteReq(
            Long kbId,
            String title,
            String content
    ) {
    }
}
