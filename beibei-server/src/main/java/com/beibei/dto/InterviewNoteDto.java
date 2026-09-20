package com.beibei.dto;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 面经相关的请求/响应对象。
 *
 * <p>列表用 {@link NoteVO}，详情用 {@link DetailVO}（含逐句对话与结构化问题）。
 */
public final class InterviewNoteDto {

    private InterviewNoteDto() {
    }

    /** 上传录音后的返回：先给 recordId，前端拿 taskId 订阅进度 */
    public record UploadResult(
            Long noteId,
            Long taskId,
            String fileName,
            String message
    ) {
    }

    /** 列表项 / 详情头部 */
    public record NoteVO(
            Long id,
            String title,
            String company,
            String position,
            String fileName,
            String fileType,
            Long fileSize,
            Integer durationMs,
            String engine,
            String roleSource,
            Integer status,
            Integer progress,
            String stage,
            Integer turnCount,
            Integer questionCount,
            Integer speakerCount,
            String summary,
            String errorMsg,
            LocalDateTime createdAt
    ) {
    }

    /** 一句话 */
    public record TurnVO(
            Integer seq,
            Integer role,
            Integer startMs,
            Integer endMs,
            String text,
            String rawText,
            String removedWords,
            String questionType
    ) {
    }

    /** 结构化问题（由 AI 从对话里抽出来） */
    public record QuestionVO(
            String question,
            String answer,
            String category
    ) {
    }

    /** 详情：头部信息 + 逐句对话 + 问题清单 + 经验点 + 正文 */
    public record DetailVO(
            NoteVO note,
            List<TurnVO> turns,
            List<QuestionVO> questions,
            List<String> highlights,
            String content
    ) {
    }

    /** 人工修正标题/公司/岗位 */
    public record UpdateReq(
            String title,
            String company,
            String position
    ) {
    }
}
