package com.beibei.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 知识点相关的请求/响应对象。
 */
public final class TagDto {

    private TagDto() {
    }

    /** 树节点 */
    public record NodeVO(
            Long id,
            Long parentId,
            String name,
            Integer level,
            Integer sortOrder,
            String description,
            Integer origin,
            Integer chunkCount,
            Integer questionCount,
            List<NodeVO> children
    ) {
    }

    /** 新增/修改知识点 */
    public record SaveReq(
            @NotNull(message = "知识库 ID 不能为空")
            Long kbId,
            Long parentId,
            @NotBlank(message = "知识点名称不能为空")
            String name,
            Integer sortOrder,
            String description
    ) {
    }
}
