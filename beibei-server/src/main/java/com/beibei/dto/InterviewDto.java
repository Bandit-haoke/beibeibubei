package com.beibei.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * AI 模拟面试相关的请求/响应对象。
 */
public final class InterviewDto {

    private InterviewDto() {
    }

    // ------------------------------------------------------------------
    //  简历库
    // ------------------------------------------------------------------

    /** 上传简历的返回 */
    public record ResumeUploadResult(
            Long resumeId,
            Long taskId,
            String fileName,
            boolean duplicated,
            String message
    ) {
    }

    /** 手动粘贴简历文字 */
    public record ResumePasteReq(
            String fileName,
            String content,
            String targetPosition
    ) {
    }

    public record ResumeVO(
            Long id,
            String fileName,
            String fileType,
            Long fileSize,
            Integer charCount,
            String targetPosition,
            Integer status,
            String errorMsg,
            Integer skillCount,
            Integer projectCount,
            Integer riskCount,
            LocalDateTime createdAt,
            LocalDateTime updatedAt
    ) {
    }

    /** 简历详情：结构化档案 + 原文（供人工核对 AI 抽得对不对） */
    public record ResumeDetailVO(
            ResumeVO resume,
            Map<String, Object> profile,
            String rawText
    ) {
    }

    // ------------------------------------------------------------------
    //  面试
    // ------------------------------------------------------------------

    /** 新建一场面试 */
    public record StartReq(
            @NotNull(message = "请先选择一份简历") Long resumeId,
            String jobTitle,
            /** 可选：关联的学习知识库，用于「薄弱点 → 出题」 */
            Long kbId,
            @Min(value = 1, message = "难度取 1~3") @Max(value = 3, message = "难度取 1~3")
            Integer difficulty,
            @Min(value = 5, message = "至少 5 轮") @Max(value = 20, message = "最多 20 轮")
            Integer maxTurns
    ) {
    }

    /** 一个面试问题 */
    public record QuestionVO(
            String question,
            String type,
            String basedOn,
            List<String> expects,
            Integer turnNo
    ) {
    }

    public record StartVO(
            Long interviewId,
            String jobTitle,
            Integer difficulty,
            Integer maxTurns,
            Integer turnCount,
            QuestionVO question
    ) {
    }

    /** 提交一轮回答 */
    public record AnswerReq(String answer) {
    }

    public record AnswerVO(
            Long interviewId,
            Integer turnCount,
            Integer maxTurns,
            Boolean finished,
            Map<String, Object> evaluation,
            QuestionVO nextQuestion
    ) {
    }

    public record TurnVO(
            Long id,
            Integer seq,
            Integer role,
            String content,
            String questionType,
            String basedOn,
            List<String> expects,
            BigDecimal score,
            Map<String, Object> feedback,
            LocalDateTime createdAt
    ) {
    }

    public record InterviewVO(
            Long id,
            Long resumeId,
            String resumeName,
            Long kbId,
            String kbName,
            String jobTitle,
            Integer difficulty,
            Integer maxTurns,
            Integer turnCount,
            Integer status,
            BigDecimal totalScore,
            String summary,
            LocalDateTime createdAt,
            LocalDateTime startedAt,
            LocalDateTime finishedAt
    ) {
    }

    /** 面试详情：元信息 + 完整对话 + 报告 */
    public record DetailVO(
            InterviewVO interview,
            List<TurnVO> turns,
            Map<String, Object> report
    ) {
    }

    // ------------------------------------------------------------------
    //  与学习模块的联动
    // ------------------------------------------------------------------

    /**
     * 「针对薄弱点出题」。
     *
     * <p>不传 tagIds 时，Java 会拿报告里的 knowledgePoints 去关联知识库里按名字匹配知识点，
     * 匹配不到的会把名字回传，让前端提示用户。
     */
    public record LinkageReq(
            Long kbId,
            List<Long> tagIds,
            @Min(value = 1, message = "至少 1 道题") @Max(value = 60, message = "一次最多 60 道题")
            Integer count,
            Boolean selfCheck,
            Long providerId
    ) {
    }

    public record LinkageVO(
            Long paperId,
            Long taskId,
            Long kbId,
            String kbName,
            List<String> matchedTags,
            List<String> unmatchedPoints,
            /** 知识点 → 命中标签 的对应关系，排查「为什么匹配到这个标签」全靠它 */
            List<MatchVO> matches,
            Integer count,
            String message
    ) {
    }

    /** 一条「知识点 → 知识库标签」的匹配结果 */
    public record MatchVO(String point, String tagName, Long tagId, Integer chunkCount) {
    }
}
