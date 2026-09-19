package com.beibei.dto;

import java.util.List;

/**
 * 统计看板相关的响应对象。
 */
public final class StatDto {

    private StatDto() {
    }

    /** 首页概览 */
    public record OverviewVO(
            int kbCount,
            int docCount,
            int chunkCount,
            int questionCount,
            int publishedCount,
            int draftCount,
            int mistakeCount,
            int masteredCount,
            /** 今日待复习题数 */
            int todayDueCount,
            /** 今日已复习题数 */
            int todayReviewedCount,
            int totalExams,
            int gradedExams,
            double avgScoreRate,
            /** 连续打卡天数 */
            int streakDays,
            /** 累计答题数 */
            int totalAnswered
    ) {
    }

    /** 知识点掌握度（雷达图） */
    public record RadarItemVO(
            Long tagId,
            String name,
            Integer level,
            int answered,
            int correct,
            double scoreRate
    ) {
    }

    /** 正确率趋势的一天 */
    public record TrendPointVO(
            String date,
            int examCount,
            int answered,
            double avgScoreRate
    ) {
    }

    /** Token 用量与成本 */
    public record CostItemVO(
            String date,
            String vendor,
            String model,
            int calls,
            int failedCalls,
            long promptTokens,
            long completionTokens,
            double cost,
            int avgLatencyMs
    ) {
    }

    /** 成本总览 */
    public record CostSummaryVO(
            long totalCalls,
            long totalTokens,
            double totalCost,
            int avgLatencyMs,
            List<CostItemVO> items
    ) {
    }

    /** 每个知识库的掌握情况 */
    public record KbMasteryVO(
            Long kbId,
            String name,
            int questionCount,
            int answeredCount,
            double scoreRate
    ) {
    }
}
