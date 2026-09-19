package com.beibei.dto;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 错题本与复习相关的请求/响应对象。
 */
public final class ReviewDto {

    private ReviewDto() {
    }

    /** 今日待复习条目 */
    public record DueItemVO(
            Long mistakeId,
            Long questionId,
            Long kbId,
            String kbName,
            Integer qType,
            String qTypeName,
            Integer difficulty,
            String stem,
            List<DocDto.TagBrief> tags,
            Integer wrongCount,
            Integer rightStreak,
            BigDecimal easeFactor,
            Integer intervalDays,
            Integer repetitions,
            LocalDateTime nextReviewAt,
            /** 逾期天数，0 表示今天到期 */
            Integer overdueDays
    ) {
    }

    /** 错题本条目 */
    public record MistakeVO(
            Long id,
            Long questionId,
            Long kbId,
            String kbName,
            Integer qType,
            String qTypeName,
            String stem,
            List<DocDto.TagBrief> tags,
            Integer wrongCount,
            Integer rightStreak,
            BigDecimal easeFactor,
            Integer intervalDays,
            Integer repetitions,
            LocalDateTime nextReviewAt,
            LocalDateTime lastWrongAt,
            Integer mastered,
            /** 掌握度描述，直接给前端展示 */
            String stage
    ) {
    }

    /** 发起复习后返回题卷 ID，前端再调 /api/exam/start */
    public record StartReviewVO(
            Long paperId,
            String title,
            int count,
            int totalScore,
            List<Long> questionIds
    ) {
    }

    /** 复习日历的一天 */
    public record CalendarDayVO(
            String date,
            int dueCount,
            int reviewedCount
    ) {
    }
}
