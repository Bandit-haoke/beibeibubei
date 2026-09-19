package com.beibei.mapper;

import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.List;
import java.util.Map;

/**
 * 统计类查询。
 *
 * <p>这些都是聚合 SQL，用 MyBatis-Plus 的 Wrapper 写会很别扭，所以直接注解写 SQL。
 * 全部只读，不涉及事务。
 */
@Mapper
public interface StatMapper {

    /** 今日待复习题数（next_review_at 已到期且未掌握） */
    @Select("SELECT COUNT(*) FROM bb_mistake "
            + "WHERE user_id = 1 AND mastered = 0 AND next_review_at <= NOW()")
    int countTodayDue();

    /** 今日已复习题数 */
    @Select("SELECT COUNT(*) FROM bb_review_log WHERE reviewed_at >= CURDATE()")
    int countTodayReviewed();

    /** 连续打卡天数（从今天往前数，有复习记录或答卷就算打卡） */
    @Select("SELECT DISTINCT DATE(day) AS d FROM ("
            + "  SELECT reviewed_at AS day FROM bb_review_log "
            + "  UNION ALL SELECT submitted_at FROM bb_exam_record WHERE submitted_at IS NOT NULL"
            + ") t ORDER BY d DESC LIMIT 400")
    List<String> recentActiveDays();

    /** 知识点掌握度：每个知识点下已答题数与得分率 */
    @Select("SELECT t.id AS tagId, t.name AS name, t.level AS level, "
            + "       COUNT(ai.id) AS answered, "
            + "       SUM(CASE WHEN ai.score >= ai.full_score * 0.999 THEN 1 ELSE 0 END) AS correct, "
            + "       COALESCE(AVG(ai.score / NULLIF(ai.full_score, 0)), 0) AS scoreRate "
            + "FROM bb_tag t "
            + "JOIN bb_question_tag qt ON qt.tag_id = t.id "
            + "JOIN bb_answer_item ai ON ai.question_id = qt.question_id "
            + "JOIN bb_exam_record e ON e.id = ai.exam_id AND e.status = 3 "
            + "WHERE t.kb_id = #{kbId} "
            + "GROUP BY t.id, t.name, t.level "
            + "HAVING answered > 0 "
            + "ORDER BY scoreRate ASC")
    List<Map<String, Object>> tagMastery(@Param("kbId") Long kbId);

    /** 正确率趋势：按天汇总 */
    @Select("SELECT DATE(e.graded_at) AS date, "
            + "       COUNT(DISTINCT e.id) AS examCount, "
            + "       COUNT(ai.id) AS answered, "
            + "       COALESCE(AVG(ai.score / NULLIF(ai.full_score, 0)), 0) AS avgScoreRate "
            + "FROM bb_exam_record e "
            + "JOIN bb_answer_item ai ON ai.exam_id = e.id "
            + "WHERE e.status = 3 AND e.graded_at >= DATE_SUB(CURDATE(), INTERVAL #{days} DAY) "
            + "GROUP BY DATE(e.graded_at) "
            + "ORDER BY date")
    List<Map<String, Object>> scoreTrend(@Param("days") int days);

    /** Token 用量与成本：按天 × 厂商 × 模型汇总 */
    @Select("SELECT DATE(created_at) AS date, vendor, model, "
            + "       COUNT(*) AS calls, "
            + "       SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) AS failedCalls, "
            + "       COALESCE(SUM(prompt_tokens), 0) AS promptTokens, "
            + "       COALESCE(SUM(completion_tokens), 0) AS completionTokens, "
            + "       COALESCE(SUM(cost), 0) AS cost, "
            + "       COALESCE(AVG(latency_ms), 0) AS avgLatencyMs "
            + "FROM bb_ai_call_log "
            + "WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL #{days} DAY) "
            + "GROUP BY DATE(created_at), vendor, model "
            + "ORDER BY date DESC, calls DESC")
    List<Map<String, Object>> aiCosts(@Param("days") int days);

    /** 成本总计 */
    @Select("SELECT COUNT(*) AS totalCalls, "
            + "       COALESCE(SUM(total_tokens), 0) AS totalTokens, "
            + "       COALESCE(SUM(cost), 0) AS totalCost, "
            + "       COALESCE(AVG(latency_ms), 0) AS avgLatencyMs "
            + "FROM bb_ai_call_log "
            + "WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL #{days} DAY)")
    Map<String, Object> aiCostSummary(@Param("days") int days);

    /** 每个知识库的掌握情况 */
    @Select("SELECT k.id AS kbId, k.name AS name, "
            + "       (SELECT COUNT(*) FROM bb_question q WHERE q.kb_id = k.id AND q.status = 1) AS questionCount, "
            + "       (SELECT COUNT(*) FROM bb_answer_item ai "
            + "        JOIN bb_question q2 ON q2.id = ai.question_id "
            + "        WHERE q2.kb_id = k.id) AS answeredCount, "
            + "       COALESCE((SELECT AVG(ai.score / NULLIF(ai.full_score, 0)) FROM bb_answer_item ai "
            + "        JOIN bb_question q3 ON q3.id = ai.question_id "
            + "        WHERE q3.kb_id = k.id), 0) AS scoreRate "
            + "FROM bb_knowledge_base k ORDER BY k.created_at DESC")
    List<Map<String, Object>> kbMastery();

    /** 复习日历：未来 N 天内每天到期的题数 */
    @Select("SELECT DATE(next_review_at) AS date, COUNT(*) AS dueCount "
            + "FROM bb_mistake "
            + "WHERE user_id = 1 AND mastered = 0 "
            + "  AND next_review_at >= DATE_SUB(CURDATE(), INTERVAL #{pastDays} DAY) "
            + "  AND next_review_at < DATE_ADD(CURDATE(), INTERVAL #{futureDays} DAY) "
            + "GROUP BY DATE(next_review_at)")
    List<Map<String, Object>> reviewCalendar(@Param("pastDays") int pastDays,
                                             @Param("futureDays") int futureDays);

    /** 复习日历：过去 N 天每天的复习量 */
    @Select("SELECT DATE(reviewed_at) AS date, COUNT(*) AS reviewedCount "
            + "FROM bb_review_log "
            + "WHERE reviewed_at >= DATE_SUB(CURDATE(), INTERVAL #{pastDays} DAY) "
            + "GROUP BY DATE(reviewed_at)")
    List<Map<String, Object>> reviewedCalendar(@Param("pastDays") int pastDays);
}
