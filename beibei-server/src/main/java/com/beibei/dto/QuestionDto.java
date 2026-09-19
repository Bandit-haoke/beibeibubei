package com.beibei.dto;

import jakarta.validation.constraints.NotBlank;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 题目相关的请求/响应对象。
 */
public final class QuestionDto {

    private QuestionDto() {
    }

    /** 题型名称 */
    public static String typeName(Integer qType) {
        if (qType == null) {
            return "未知";
        }
        return switch (qType) {
            case 1 -> "单选题";
            case 2 -> "多选题";
            case 3 -> "判断题";
            case 4 -> "填空题";
            case 5 -> "名词解释";
            case 6 -> "简答题";
            case 7 -> "论述题";
            case 8 -> "代码题";
            case 9 -> "对比辨析";
            default -> "类型" + qType;
        };
    }

    public static String difficultyName(Integer difficulty) {
        if (difficulty == null) {
            return "中";
        }
        return switch (difficulty) {
            case 1 -> "易";
            case 3 -> "难";
            default -> "中";
        };
    }

    public record OptionVO(Long id, String key, String content, Boolean correct) {
    }

    public record VO(
            Long id,
            Long kbId,
            Integer qType,
            String qTypeName,
            Integer difficulty,
            String difficultyName,
            String stem,
            String answer,
            String analysis,
            Object rubric,
            String codeSnippet,
            List<OptionVO> options,
            List<DocDto.TagBrief> tags,
            List<Long> sourceChunkIds,
            Integer status,
            Integer origin,
            String genBatchId,
            BigDecimal qualityScore,
            String selfCheckMsg,
            Integer useCount,
            Integer correctCount,
            BigDecimal avgScoreRate,
            LocalDateTime createdAt
    ) {
    }

    /** 编辑题目 */
    public record UpdateReq(
            String stem,
            String answer,
            String analysis,
            Integer difficulty,
            String codeSnippet,
            List<OptionReq> options,
            List<Long> tagIds
    ) {
    }

    /** 手动新增题目 */
    public record ManualReq(
            Long kbId,
            Integer qType,
            Integer difficulty,
            @NotBlank(message = "题干不能为空") String stem,
            @NotBlank(message = "答案不能为空") String answer,
            String analysis,
            String codeSnippet,
            List<OptionReq> options,
            List<Long> tagIds
    ) {
    }

    public record OptionReq(String key, String content, Boolean correct) {
    }

    /** 审核通过请求 */
    public record ApproveReq(List<Long> questionIds) {
    }
}
