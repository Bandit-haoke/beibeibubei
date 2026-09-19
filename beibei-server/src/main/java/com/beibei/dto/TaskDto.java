package com.beibei.dto;

import java.time.LocalDateTime;

/**
 * 异步任务响应对象。与 SSE 事件里的字段保持一致，前端可复用同一套渲染逻辑。
 */
public final class TaskDto {

    private TaskDto() {
    }

    public record VO(
            Long id,
            String taskType,
            Long bizId,
            Integer status,
            Integer progress,
            String stage,
            String message,
            String resultJson,
            String errorMsg,
            LocalDateTime startedAt,
            LocalDateTime finishedAt,
            LocalDateTime createdAt
    ) {
    }
}
