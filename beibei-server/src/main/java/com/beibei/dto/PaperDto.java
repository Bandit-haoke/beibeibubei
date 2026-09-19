package com.beibei.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * 题卷相关的请求/响应对象。
 */
public final class PaperDto {

    private PaperDto() {
    }

    /** 出题请求 */
    public record GenerateReq(
            @NotNull(message = "知识库 ID 不能为空") Long kbId,
            String title,

            @NotNull(message = "题量不能为空")
            @Min(value = 1, message = "至少 1 道题")
            @Max(value = 60, message = "一次最多 60 道题")
            Integer count,

            List<Long> tagIds,
            Boolean includeChildTags,
            Map<String, Double> qTypeRatio,
            Map<String, Double> difficultyRatio,
            Boolean selfCheck,
            Long providerId
    ) {
    }

    /** 出题提交结果 */
    public record GenerateResult(Long paperId, Long taskId) {
    }

    public record VO(
            Long id,
            Long kbId,
            String title,
            Integer source,
            Integer totalCount,
            BigDecimal totalScore,
            Integer durationLimit,
            Integer status,
            Map<String, Object> genSummary,
            Integer draftCount,
            Integer publishedCount,
            LocalDateTime createdAt
    ) {
    }

    /** 题卷详情（含全部题目） */
    public record DetailVO(
            VO paper,
            List<QuestionDto.VO> questions
    ) {
    }
}
