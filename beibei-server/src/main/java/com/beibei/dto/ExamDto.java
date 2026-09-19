package com.beibei.dto;

import jakarta.validation.constraints.NotNull;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 答题与判分相关的请求/响应对象。
 */
public final class ExamDto {

    private ExamDto() {
    }

    // ------------------------------------------------------------------
    //  请求
    // ------------------------------------------------------------------

    /** 开始作答 */
    public record StartReq(
            @NotNull(message = "题卷 ID 不能为空") Long paperId,
            Integer examMode,
            Boolean onlyPublished
    ) {
    }

    /** 单题作答 */
    public record AnswerReq(
            Long questionId,
            String userAnswer,
            String asrText,
            Integer inputMode
    ) {
    }

    /** 自动存草稿 */
    public record SaveDraftReq(
            List<AnswerReq> answers,
            Integer durationSec
    ) {
    }

    /** 交卷 */
    public record SubmitReq(
            List<AnswerReq> answers,
            Integer durationSec
    ) {
    }

    /** 申诉 */
    public record AppealReq(String reason) {
    }

    // ------------------------------------------------------------------
    //  响应
    // ------------------------------------------------------------------

    /** 答题页需要的题目信息（比审核页少一些字段，不含答案与解析） */
    public record ExamQuestionVO(
            Long questionId,
            Integer qType,
            String qTypeName,
            Integer difficulty,
            String difficultyName,
            String stem,
            String codeSnippet,
            List<QuestionDto.OptionVO> options,
            BigDecimal fullScore,
            Integer sortOrder,
            /** 已保存的作答，用于断点续答 */
            String savedAnswer,
            Integer savedInputMode
    ) {
    }

    /** 开始作答的返回 */
    public record StartVO(
            Long examId,
            Long paperId,
            Long kbId,
            String title,
            Integer examMode,
            Integer status,
            Integer durationLimit,
            BigDecimal totalScore,
            Integer questionCount,
            LocalDateTime startedAt,
            List<ExamQuestionVO> questions
    ) {
    }

    /** 判分结果里的单题明细 */
    public record ItemResultVO(
            Long answerItemId,
            Long questionId,
            Integer qType,
            String qTypeName,
            String stem,
            String codeSnippet,
            List<QuestionDto.OptionVO> options,
            String userAnswer,
            String asrText,
            Integer inputMode,
            BigDecimal score,
            BigDecimal fullScore,
            List<Object> hitPoints,
            List<Object> missPoints,
            List<Object> wrongPoints,
            List<Object> citations,
            String aiFeedback,
            Integer gradeMethod,
            String gradeMethodName,
            String referenceAnswer,
            String analysis,
            List<DocDto.TagBrief> tags,
            Integer appealStatus,
            String appealReason,
            BigDecimal appealScore,
            List<Object> appealResult
    ) {
    }

    /** 判分结果总览 */
    public record ResultVO(
            Long examId,
            Long paperId,
            Long kbId,
            String title,
            Integer status,
            Integer examMode,
            BigDecimal totalScore,
            BigDecimal gotScore,
            Double scoreRate,
            Integer correctCount,
            Integer wrongCount,
            Integer durationSec,
            LocalDateTime startedAt,
            LocalDateTime submittedAt,
            LocalDateTime gradedAt,
            List<ItemResultVO> items
    ) {
    }

    /** 答卷列表项 */
    public record ExamVO(
            Long id,
            Long paperId,
            Long kbId,
            String title,
            Integer status,
            String statusName,
            Integer examMode,
            BigDecimal totalScore,
            BigDecimal gotScore,
            Double scoreRate,
            Integer correctCount,
            Integer wrongCount,
            Integer durationSec,
            LocalDateTime startedAt,
            LocalDateTime submittedAt
    ) {
    }

    public static String statusName(Integer status) {
        if (status == null) {
            return "未知";
        }
        return switch (status) {
            case 0 -> "进行中";
            case 1 -> "已交卷";
            case 2 -> "判分中";
            case 3 -> "已判完";
            case 4 -> "判分失败";
            default -> "状态" + status;
        };
    }

    public static String gradeMethodName(Integer method) {
        if (method == null) {
            return "未判";
        }
        return switch (method) {
            case 1 -> "程序判定";
            case 2 -> "AI 要点判分";
            case 3 -> "AI 代码审阅";
            case 4 -> "人工";
            default -> "未判";
        };
    }
}
