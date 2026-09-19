package com.beibei.service;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.beibei.common.BusinessException;
import com.beibei.common.PageResult;
import com.beibei.dto.DocDto;
import com.beibei.dto.QuestionDto;
import com.beibei.dto.ReviewDto;
import com.beibei.entity.KnowledgeBase;
import com.beibei.entity.Mistake;
import com.beibei.entity.Paper;
import com.beibei.entity.PaperItem;
import com.beibei.entity.Question;
import com.beibei.mapper.KnowledgeBaseMapper;
import com.beibei.mapper.MistakeMapper;
import com.beibei.mapper.PaperItemMapper;
import com.beibei.mapper.PaperMapper;
import com.beibei.mapper.QuestionMapper;
import com.beibei.mapper.StatMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;

/**
 * 错题本与复习计划。
 *
 * <p>这是「背书」和「刷题」的分界线：判错的题自动进错题本，按 SM-2 算出的
 * {@code next_review_at} 排期，首页推「今日待复习」。
 *
 * <p>复习模式**复用已有题目**，不重新生成 —— 复习的目的是记住，不是刷新题。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ReviewService {

    /** 单次复习最多带多少道题 */
    private static final int REVIEW_BATCH_MAX = 50;

    private final MistakeMapper mistakeMapper;
    private final QuestionMapper questionMapper;
    private final PaperMapper paperMapper;
    private final PaperItemMapper paperItemMapper;
    private final KnowledgeBaseMapper kbMapper;
    private final QuestionService questionService;
    private final StatMapper statMapper;

    // ------------------------------------------------------------------
    //  今日待复习
    // ------------------------------------------------------------------

    public List<ReviewDto.DueItemVO> today(Long kbId, int limit) {
        var query = Wrappers.<Mistake>lambdaQuery()
                .eq(Mistake::getUserId, 1L)
                .eq(Mistake::getMastered, 0)
                .le(Mistake::getNextReviewAt, LocalDateTime.now())
                .eq(kbId != null, Mistake::getKbId, kbId)
                // 逾期最久的排前面
                .orderByAsc(Mistake::getNextReviewAt)
                .last("LIMIT " + Math.max(1, Math.min(limit, 200)));

        List<Mistake> mistakes = mistakeMapper.selectList(query);
        if (mistakes.isEmpty()) {
            return List.of();
        }

        List<Long> questionIds = mistakes.stream().map(Mistake::getQuestionId).toList();
        Map<Long, Question> questionMap = questionMapper.selectByIds(questionIds).stream()
                .collect(Collectors.toMap(Question::getId, q -> q));
        Map<Long, List<DocDto.TagBrief>> tagMap = questionService.tagBriefsOf(questionIds);
        Map<Long, String> kbNames = kbNames(mistakes.stream().map(Mistake::getKbId).distinct().toList());

        LocalDateTime now = LocalDateTime.now();
        List<ReviewDto.DueItemVO> out = new ArrayList<>();
        for (Mistake m : mistakes) {
            Question q = questionMap.get(m.getQuestionId());
            if (q == null || q.getStatus() == Question.STATUS_DISABLED) {
                continue;   // 题目被删/停用了就跳过
            }
            out.add(new ReviewDto.DueItemVO(
                    m.getId(), m.getQuestionId(), m.getKbId(), kbNames.getOrDefault(m.getKbId(), ""),
                    q.getQType(), QuestionDto.typeName(q.getQType()), q.getDifficulty(), q.getStem(),
                    tagMap.getOrDefault(q.getId(), List.of()),
                    m.getWrongCount(), m.getRightStreak(), m.getEaseFactor(),
                    m.getIntervalDays(), m.getRepetitions(), m.getNextReviewAt(),
                    overdueDays(m.getNextReviewAt(), now)
            ));
        }
        return out;
    }

    private int overdueDays(LocalDateTime next, LocalDateTime now) {
        if (next == null) {
            return 0;
        }
        long days = ChronoUnit.DAYS.between(next.toLocalDate(), now.toLocalDate());
        return (int) Math.max(0, days);
    }

    // ------------------------------------------------------------------
    //  错题本列表
    // ------------------------------------------------------------------

    public PageResult<ReviewDto.MistakeVO> listMistakes(Long kbId, Integer mastered, Long tagId,
                                                        long pageNum, long pageSize) {
        var query = Wrappers.<Mistake>lambdaQuery()
                .eq(Mistake::getUserId, 1L)
                .eq(kbId != null, Mistake::getKbId, kbId)
                .eq(mastered != null, Mistake::getMastered, mastered)
                .orderByAsc(Mistake::getNextReviewAt);

        IPage<Mistake> page = mistakeMapper.selectPage(new Page<>(pageNum, pageSize), query);
        List<Mistake> records = page.getRecords();
        if (records.isEmpty()) {
            return PageResult.empty(pageNum, pageSize);
        }

        List<Long> questionIds = records.stream().map(Mistake::getQuestionId).toList();
        Map<Long, Question> questionMap = questionMapper.selectByIds(questionIds).stream()
                .collect(Collectors.toMap(Question::getId, q -> q));
        Map<Long, List<DocDto.TagBrief>> tagMap = questionService.tagBriefsOf(questionIds);
        Map<Long, String> kbNames = kbNames(records.stream().map(Mistake::getKbId).distinct().toList());

        List<ReviewDto.MistakeVO> list = new ArrayList<>();
        for (Mistake m : records) {
            Question q = questionMap.get(m.getQuestionId());
            if (q == null) {
                continue;
            }
            List<DocDto.TagBrief> tags = tagMap.getOrDefault(q.getId(), List.of());
            if (tagId != null && tags.stream().noneMatch(t -> Objects.equals(t.id(), tagId))) {
                continue;
            }
            list.add(new ReviewDto.MistakeVO(
                    m.getId(), m.getQuestionId(), m.getKbId(), kbNames.getOrDefault(m.getKbId(), ""),
                    q.getQType(), QuestionDto.typeName(q.getQType()), q.getStem(), tags,
                    m.getWrongCount(), m.getRightStreak(), m.getEaseFactor(),
                    m.getIntervalDays(), m.getRepetitions(), m.getNextReviewAt(),
                    m.getLastWrongAt(), m.getMastered(), stageOf(m)
            ));
        }
        return new PageResult<>(page.getTotal(), list, page.getCurrent(), page.getSize(), page.getPages());
    }

    /** 把 SM-2 的内部参数翻译成人话 */
    public static String stageOf(Mistake m) {
        if (m.getMastered() != null && m.getMastered() == 1) {
            return "已掌握";
        }
        int reps = m.getRepetitions() == null ? 0 : m.getRepetitions();
        int interval = m.getIntervalDays() == null ? 1 : m.getIntervalDays();
        if (reps == 0) {
            return m.getWrongCount() != null && m.getWrongCount() >= 3 ? "反复出错" : "新错题";
        }
        if (reps == 1) {
            return "刚开始复习";
        }
        if (interval >= 15) {
            return "接近掌握";
        }
        return "复习中";
    }

    // ------------------------------------------------------------------
    //  发起复习
    // ------------------------------------------------------------------

    /**
     * 用今日待复习的题目组一份临时题卷，前端随后调 {@code /api/exam/start} 进入答题。
     *
     * <p>刻意复用题卷+答卷这套结构：复习的判分、错题推进、统计口径与平时答题完全一致，
     * 不需要为复习单独写一套逻辑。
     */
    @Transactional(rollbackFor = Exception.class)
    public ReviewDto.StartReviewVO startReview(Long kbId, Integer limit) {
        int size = limit == null ? 20 : Math.max(1, Math.min(limit, REVIEW_BATCH_MAX));
        List<ReviewDto.DueItemVO> due = today(kbId, size);
        if (due.isEmpty()) {
            throw BusinessException.invalid("今天没有需要复习的题目。答错的题会按艾宾浩斯曲线自动排期。");
        }

        // 记录类的访问器不带 get 前缀
        List<Long> questionIds = due.stream().map(ReviewDto.DueItemVO::questionId).toList();
        Map<Long, Question> questionMap = questionMapper.selectByIds(questionIds).stream()
                .collect(Collectors.toMap(Question::getId, q -> q));

        BigDecimal total = BigDecimal.ZERO;
        for (Long qid : questionIds) {
            total = total.add(scoreOf(questionMap.get(qid)));
        }

        Paper paper = new Paper();
        paper.setKbId(due.get(0).kbId());
        paper.setUserId(1L);
        paper.setTitle("错题复习 · " + LocalDate.now() + " · " + questionIds.size() + " 道");
        paper.setSource(Paper.SOURCE_MISTAKE);
        paper.setTotalCount(questionIds.size());
        paper.setTotalScore(total);
        paper.setTagIds("[]");
        paper.setDurationLimit(0);
        paper.setStatus(Paper.STATUS_READY);   // 直接用，不需要审核
        paper.setGenTaskId(0L);
        paper.setProviderId(0L);
        paperMapper.insert(paper);

        int order = 0;
        for (Long qid : questionIds) {
            PaperItem item = new PaperItem();
            item.setPaperId(paper.getId());
            item.setQuestionId(qid);
            item.setSortOrder(order++);
            item.setScore(scoreOf(questionMap.get(qid)));
            paperItemMapper.insert(item);
        }

        log.info("发起错题复习：paper=#{} {} 道 / {} 分", paper.getId(), questionIds.size(), total);
        return new ReviewDto.StartReviewVO(paper.getId(), paper.getTitle(),
                questionIds.size(), total.intValue(), questionIds);
    }

    private BigDecimal scoreOf(Question q) {
        if (q == null || q.getQType() == null) {
            return new BigDecimal("5.0");
        }
        return q.getQType() <= 4 ? new BigDecimal("5.0") : new BigDecimal("10.0");
    }

    // ------------------------------------------------------------------
    //  手动维护
    // ------------------------------------------------------------------

    /** 手动标记已掌握 / 移出错题本 */
    public void markMastered(Long mistakeId, boolean mastered) {
        Mistake m = mistakeMapper.selectById(mistakeId);
        if (m == null) {
            throw BusinessException.notFound("错题", mistakeId);
        }
        Mistake patch = new Mistake();
        patch.setId(mistakeId);
        patch.setMastered(mastered ? 1 : 0);
        if (mastered) {
            // 标记已掌握时把间隔推到最长，避免马上又被推上来
            patch.setIntervalDays(365);
            patch.setNextReviewAt(LocalDateTime.now().plusDays(365));
        } else {
            patch.setIntervalDays(1);
            patch.setRepetitions(0);
            patch.setNextReviewAt(LocalDateTime.now());
        }
        mistakeMapper.updateById(patch);
        log.info("错题 #{} 标记为{}", mistakeId, mastered ? "已掌握" : "未掌握");
    }

    public void remove(Long mistakeId) {
        if (mistakeMapper.deleteById(mistakeId) == 0) {
            throw BusinessException.notFound("错题", mistakeId);
        }
        log.info("已从错题本移除 #{}", mistakeId);
    }

    // ------------------------------------------------------------------
    //  复习日历
    // ------------------------------------------------------------------

    public List<ReviewDto.CalendarDayVO> calendar(int pastDays, int futureDays) {
        Map<String, Integer> due = new LinkedHashMap<>();
        Map<String, Integer> reviewed = new LinkedHashMap<>();

        for (Map<String, Object> row : statMapper.reviewCalendar(pastDays, futureDays)) {
            due.put(String.valueOf(row.get("date")), toInt(row.get("dueCount")));
        }
        for (Map<String, Object> row : statMapper.reviewedCalendar(pastDays)) {
            reviewed.put(String.valueOf(row.get("date")), toInt(row.get("reviewedCount")));
        }

        LocalDate from = LocalDate.now().minusDays(pastDays);
        LocalDate to = LocalDate.now().plusDays(futureDays);
        List<ReviewDto.CalendarDayVO> out = new ArrayList<>();
        for (LocalDate d = from; !d.isAfter(to); d = d.plusDays(1)) {
            String key = d.toString();
            out.add(new ReviewDto.CalendarDayVO(key,
                    due.getOrDefault(key, 0), reviewed.getOrDefault(key, 0)));
        }
        return out;
    }

    // ------------------------------------------------------------------

    private Map<Long, String> kbNames(List<Long> kbIds) {
        if (kbIds == null || kbIds.isEmpty()) {
            return Map.of();
        }
        return kbMapper.selectByIds(kbIds).stream()
                .collect(Collectors.toMap(KnowledgeBase::getId, KnowledgeBase::getName));
    }

    private static int toInt(Object value) {
        if (value == null) {
            return 0;
        }
        if (value instanceof Number n) {
            return n.intValue();
        }
        try {
            return Integer.parseInt(String.valueOf(value));
        } catch (NumberFormatException e) {
            return 0;
        }
    }
}
