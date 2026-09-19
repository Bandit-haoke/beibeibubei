package com.beibei.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 知识库相关的请求/响应对象。
 */
public final class KbDto {

    private KbDto() {
    }

    /** 新建知识库 */
    public record CreateReq(
            @NotBlank(message = "知识库名称不能为空")
            @Size(max = 100, message = "知识库名称不能超过 100 字")
            String name,

            @Size(max = 500, message = "描述不能超过 500 字")
            String description,

            String coverColor
    ) {
    }

    /** 修改知识库（不允许改 embeddingModel） */
    public record UpdateReq(
            @Size(max = 100, message = "知识库名称不能超过 100 字")
            String name,

            @Size(max = 500, message = "描述不能超过 500 字")
            String description,

            String coverColor,

            Integer status
    ) {
    }

    /** 知识库列表/详情 */
    public record VO(
            Long id,
            String name,
            String description,
            String coverColor,
            String embeddingModel,
            String milvusCollection,
            Integer chunkSize,
            Integer chunkOverlap,
            Integer docCount,
            Integer chunkCount,
            Integer questionCount,
            Integer status,
            LocalDateTime createdAt,
            LocalDateTime updatedAt
    ) {
    }

    /** 知识库掌握度统计（雷达图数据源，M4 会用上） */
    public record StatVO(
            Long kbId,
            int docCount,
            int chunkCount,
            int questionCount,
            int tagCount,
            int examCount,
            double avgScoreRate,
            List<Map<String, Object>> tagMastery
    ) {
    }
}
