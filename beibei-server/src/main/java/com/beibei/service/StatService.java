package com.beibei.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.beibei.dto.StatDto;
import com.beibei.entity.ExamRecord;
import com.beibei.entity.Mistake;
import com.beibei.entity.Question;
import com.beibei.mapper.AnswerItemMapper;
import com.beibei.mapper.DocChunkMapper;
import com.beibei.mapper.DocumentMapper;
import com.beibei.mapper.ExamRecordMapper;
import com.beibei.mapper.KnowledgeBaseMapper;
import com.beibei.mapper.MistakeMapper;
import com.beibei.mapper.QuestionMapper;
import com.beibei.mapper.StatMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 统计看板。
 *
 * <p>所有数字都是**现算**的，不做缓存 —— 单用户本地库数据量小，
 * 缓存带来的不一致比省下的几毫秒更麻烦。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class StatService {

    private final StatMapper statMapper;
    private final KnowledgeBaseMapper kbMapper;
    private final DocumentMapper documentMapper;
    private final DocChunkMapper chunkMapper;
    private final QuestionMapper questionMapper;
    private final MistakeMapper mistakeMapper;
    private final ExamRecordMapper examMapper;
    private final AnswerItemMapper answerItemMapper;

    // ------------------------------------------------------------------
    //  概览
    // ------------------------------------------------------------------

    public StatDto.OverviewVO overview() {
        int kbCount = count(kbMapper.selectCount(null));
        int docCount = count(documentMapper.selectCount(
                Wrappers.<com.beibei.entity.Document>lambdaQuery()
                        .eq(com.beibei.entity.Document::getStatus, 2)));
        int chunkCount = count(chunkMapper.selectCount(null));

        int questionCount = count(questionMapper.selectCount(null));
        int publishedCount = count(questionMapper.selectCount(
                Wrappers.<Question>lambdaQuery().eq(Question::getStatus, Question.STATUS_PUBLISHED)));
        int draftCount = count(questionMapper.selectCount(
                Wrappers.<Question>lambdaQuery().eq(Question::getStatus, Question.STATUS_DRAFT)));

        int mistakeCount = count(mistakeMapper.selectCount(
                Wrappers.<Mistake>lambdaQuery().eq(Mistake::getMastered, 0)));
        int masteredCount = count(mistakeMapper.selectCount(
                Wrappers.<Mistake>lambdaQuery().eq(Mistake::getMastered, 1)));

        int totalExams = count(examMapper.selectCount(null));
        int gradedExams = count(examMapper.selectCount(
                Wrappers.<ExamRecord>lambdaQuery().eq(ExamRecord::getStatus, ExamRecord.STATUS_GRADED)));

        // 平均得分率 = 所有已判分答卷的得分之和 / 满分之和
        double avgRate = 0.0;
        List<ExamRecord> graded = examMapper.selectList(
                Wrappers.<ExamRecord>lambdaQuery().eq(ExamRecord::getStatus, ExamRecord.STATUS_GRADED));
        double got = 0;
        double total = 0;
        for (ExamRecord e : graded) {
            got += e.getGotScore() == null ? 0 : e.getGotScore().doubleValue();
            total += e.getTotalScore() == null ? 0 : e.getTotalScore().doubleValue();
        }
        if (total > 0) {
            avgRate = Math.round(got / total * 1000) / 10.0;
        }

        int totalAnswered = count(answerItemMapper.selectCount(null));

        return new StatDto.OverviewVO(
                kbCount, docCount, chunkCount, questionCount, publishedCount, draftCount,
                mistakeCount, masteredCount,
                statMapper.countTodayDue(), statMapper.countTodayReviewed(),
                totalExams, gradedExams, avgRate, streakDays(), totalAnswered
        );
    }

    /**
     * 连续打卡天数：从今天（或昨天）往前数，连续有「复习或交卷」记录的天数。
     * 今天还没学不算断 —— 否则每天早上打开都显示 0，体验很差。
     */
    private int streakDays() {
        List<String> days = statMapper.recentActiveDays();
        if (days == null || days.isEmpty()) {
            return 0;
        }
        java.util.Set<LocalDate> active = new java.util.HashSet<>();
        for (String d : days) {
            try {
                active.add(LocalDate.parse(String.valueOf(d).substring(0, 10)));
            } catch (Exception ignored) {
                // 忽略异常格式
            }
        }
        if (active.isEmpty()) {
            return 0;
        }

        LocalDate cursor = LocalDate.now();
        if (!active.contains(cursor)) {
            cursor = cursor.minusDays(1);
            if (!active.contains(cursor)) {
                return 0;
            }
        }
        int streak = 0;
        while (active.contains(cursor)) {
            streak++;
            cursor = cursor.minusDays(1);
        }
        return streak;
    }

    // ------------------------------------------------------------------
    //  知识点掌握度（雷达图）
    // ------------------------------------------------------------------

    public List<StatDto.RadarItemVO> radar(Long kbId) {
        List<Map<String, Object>> rows = statMapper.tagMastery(kbId);
        List<StatDto.RadarItemVO> out = new ArrayList<>();
        for (Map<String, Object> row : rows) {
            out.add(new StatDto.RadarItemVO(
                    toLong(row.get("tagId")),
                    String.valueOf(row.getOrDefault("name", "")),
                    toInt(row.get("level")),
                    toInt(row.get("answered")),
                    toInt(row.get("correct")),
                    round2(toDouble(row.get("scoreRate")) * 100)
            ));
        }
        return out;
    }

    // ------------------------------------------------------------------
    //  正确率趋势
    // ------------------------------------------------------------------

    public List<StatDto.TrendPointVO> trend(int days) {
        int span = Math.max(1, Math.min(days, 365));
        Map<String, StatDto.TrendPointVO> byDate = new LinkedHashMap<>();
        for (Map<String, Object> row : statMapper.scoreTrend(span)) {
            String date = String.valueOf(row.get("date"));
            byDate.put(date, new StatDto.TrendPointVO(
                    date,
                    toInt(row.get("examCount")),
                    toInt(row.get("answered")),
                    round2(toDouble(row.get("avgScoreRate")) * 100)
            ));
        }

        // 补齐没有数据的天，否则折线图会断
        List<StatDto.TrendPointVO> out = new ArrayList<>();
        LocalDate from = LocalDate.now().minusDays(span);
        for (LocalDate d = from; !d.isAfter(LocalDate.now()); d = d.plusDays(1)) {
            String key = d.toString();
            out.add(byDate.getOrDefault(key, new StatDto.TrendPointVO(key, 0, 0, 0.0)));
        }
        return out;
    }

    // ------------------------------------------------------------------
    //  Token 用量与成本
    // ------------------------------------------------------------------

    public StatDto.CostSummaryVO cost(int days) {
        int span = Math.max(1, Math.min(days, 365));
        Map<String, Object> summary = statMapper.aiCostSummary(span);

        List<StatDto.CostItemVO> items = new ArrayList<>();
        for (Map<String, Object> row : statMapper.aiCosts(span)) {
            items.add(new StatDto.CostItemVO(
                    String.valueOf(row.get("date")),
                    String.valueOf(row.getOrDefault("vendor", "")),
                    String.valueOf(row.getOrDefault("model", "")),
                    toInt(row.get("calls")),
                    toInt(row.get("failedCalls")),
                    toLong(row.get("promptTokens")),
                    toLong(row.get("completionTokens")),
                    round4(toDouble(row.get("cost"))),
                    toInt(row.get("avgLatencyMs"))
            ));
        }

        return new StatDto.CostSummaryVO(
                summary == null ? 0 : toLong(summary.get("totalCalls")),
                summary == null ? 0 : toLong(summary.get("totalTokens")),
                summary == null ? 0.0 : round4(toDouble(summary.get("totalCost"))),
                summary == null ? 0 : toInt(summary.get("avgLatencyMs")),
                items
        );
    }

    // ------------------------------------------------------------------
    //  每个知识库的掌握情况
    // ------------------------------------------------------------------

    public List<StatDto.KbMasteryVO> kbMastery() {
        List<StatDto.KbMasteryVO> out = new ArrayList<>();
        for (Map<String, Object> row : statMapper.kbMastery()) {
            out.add(new StatDto.KbMasteryVO(
                    toLong(row.get("kbId")),
                    String.valueOf(row.getOrDefault("name", "")),
                    toInt(row.get("questionCount")),
                    toInt(row.get("answeredCount")),
                    round2(toDouble(row.get("scoreRate")) * 100)
            ));
        }
        return out;
    }

    // ------------------------------------------------------------------

    private static int count(Long value) {
        return value == null ? 0 : value.intValue();
    }

    private static int toInt(Object v) {
        return v instanceof Number n ? n.intValue() : 0;
    }

    private static long toLong(Object v) {
        return v instanceof Number n ? n.longValue() : 0L;
    }

    private static double toDouble(Object v) {
        return v instanceof Number n ? n.doubleValue() : 0.0;
    }

    private static double round2(double v) {
        return Math.round(v * 100) / 100.0;
    }

    private static double round4(double v) {
        return Math.round(v * 10000) / 10000.0;
    }
}
