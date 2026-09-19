package com.beibei.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.beibei.common.BusinessException;
import com.beibei.dto.ExamDto;
import com.beibei.dto.QuestionDto;
import com.beibei.entity.AnswerItem;
import com.beibei.entity.AsyncTask;
import com.beibei.entity.ExamRecord;
import com.beibei.entity.Paper;
import com.beibei.entity.PaperItem;
import com.beibei.entity.Question;
import com.beibei.mapper.AnswerItemMapper;
import com.beibei.mapper.ExamRecordMapper;
import com.beibei.mapper.PaperItemMapper;
import com.beibei.mapper.QuestionMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.stream.Collectors;

/**
 * 答题与判分业务。
 *
 * <p>流程：开始作答（为每道题建空的 {@code bb_answer_item}）→ 边答边存草稿
 * → 交卷（置 SUBMITTED 并起判分任务）→ Python 判分写回明细 → 查结果 → 申诉重判。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class ExamService {

    private final ExamRecordMapper examMapper;
    private final AnswerItemMapper answerMapper;
    private final PaperItemMapper paperItemMapper;
    private final QuestionMapper questionMapper;
    private final PaperService paperService;
    private final QuestionService questionService;
    private final AsyncTaskService taskService;
    private final GradingRunner gradingRunner;
    private final ObjectMapper objectMapper;

    // ------------------------------------------------------------------
    //  开始作答
    // ------------------------------------------------------------------

    @Transactional(rollbackFor = Exception.class)
    public ExamDto.StartVO start(ExamDto.StartReq req) {
        Paper paper = paperService.require(req.paperId());
        int mode = req.examMode() == null ? ExamRecord.MODE_EXAM : req.examMode();
        boolean onlyPublished = req.onlyPublished() == null || req.onlyPublished();

        List<PaperItem> items = paperItemMapper.selectList(
                Wrappers.<PaperItem>lambdaQuery()
                        .eq(PaperItem::getPaperId, paper.getId())
                        .orderByAsc(PaperItem::getSortOrder));
        if (items.isEmpty()) {
            throw BusinessException.invalid("这份题卷里还没有题目");
        }

        List<Question> questions = loadOrdered(items);
        if (onlyPublished) {
            questions = questions.stream()
                    .filter(q -> q.getStatus() == Question.STATUS_PUBLISHED)
                    .toList();
        }
        if (questions.isEmpty()) {
            throw BusinessException.invalid("题卷里没有已发布的题目，请先在审核页通过审核");
        }

        BigDecimal totalScore = questions.stream()
                .map(this::scoreOf)
                .reduce(BigDecimal.ZERO, BigDecimal::add);

        ExamRecord exam = new ExamRecord();
        exam.setPaperId(paper.getId());
        exam.setKbId(paper.getKbId());
        exam.setUserId(1L);
        exam.setTitle(paper.getTitle());
        exam.setStatus(ExamRecord.STATUS_ONGOING);
        exam.setExamMode(mode);
        exam.setTotalScore(totalScore);
        exam.setGotScore(BigDecimal.ZERO);
        exam.setCorrectCount(0);
        exam.setWrongCount(0);
        exam.setDurationSec(0);
        exam.setGradeTaskId(0L);
        exam.setStartedAt(LocalDateTime.now());
        examMapper.insert(exam);

        // 为每道题预建作答行，这样「存草稿」就只是 UPDATE
        int order = 0;
        Map<Long, BigDecimal> scoreMap = new LinkedHashMap<>();
        for (Question q : questions) {
            scoreMap.put(q.getId(), scoreOf(q));
        }
        for (Question q : questions) {
            AnswerItem item = new AnswerItem();
            item.setExamId(exam.getId());
            item.setQuestionId(q.getId());
            item.setUserAnswer("");
            item.setAsrText("");
            item.setInputMode(AnswerItem.INPUT_TYPING);
            item.setScore(BigDecimal.ZERO);
            item.setFullScore(scoreMap.get(q.getId()));
            item.setGradeMethod(AnswerItem.METHOD_NONE);
            item.setAppealStatus(AnswerItem.APPEAL_NONE);
            item.setAppealReason("");
            answerMapper.insert(item);
            order++;
        }

        log.info("开始作答：exam=#{} paper=#{} {} 道题 / {} 分", exam.getId(), paper.getId(), order, totalScore);
        return buildStartVO(exam, questions, scoreMap);
    }

    private List<Question> loadOrdered(List<PaperItem> items) {
        List<Long> ids = items.stream().map(PaperItem::getQuestionId).toList();
        Map<Long, Question> index = questionMapper.selectByIds(ids).stream()
                .collect(Collectors.toMap(Question::getId, q -> q));
        return ids.stream().map(index::get).filter(Objects::nonNull).toList();
    }

    private ExamDto.StartVO buildStartVO(ExamRecord exam, List<Question> questions,
                                         Map<Long, BigDecimal> scoreMap) {
        Map<Long, AnswerItem> saved = answerMapper.selectList(
                        Wrappers.<AnswerItem>lambdaQuery().eq(AnswerItem::getExamId, exam.getId()))
                .stream().collect(Collectors.toMap(AnswerItem::getQuestionId, a -> a));

        List<Long> ids = questions.stream().map(Question::getId).toList();
        Map<Long, List<QuestionDto.OptionVO>> optionMap = questionService.optionsOf(ids);

        List<ExamDto.ExamQuestionVO> vos = new ArrayList<>();
        int order = 0;
        for (Question q : questions) {
            AnswerItem item = saved.get(q.getId());
            vos.add(new ExamDto.ExamQuestionVO(
                    q.getId(), q.getQType(), QuestionDto.typeName(q.getQType()),
                    q.getDifficulty(), QuestionDto.difficultyName(q.getDifficulty()),
                    q.getStem(), q.getCodeSnippet(),
                    optionMap.getOrDefault(q.getId(), List.of()),
                    scoreMap.getOrDefault(q.getId(), BigDecimal.ZERO),
                    order++,
                    item == null ? "" : item.getUserAnswer(),
                    item == null ? AnswerItem.INPUT_TYPING : item.getInputMode()
            ));
        }

        return new ExamDto.StartVO(
                exam.getId(), exam.getPaperId(), exam.getKbId(), exam.getTitle(),
                exam.getExamMode(), exam.getStatus(), 0,
                exam.getTotalScore(), vos.size(), exam.getStartedAt(), vos
        );
    }

    private BigDecimal scoreOf(Question q) {
        // 分值目前按题型给：客观题 5 分，主观题 10 分
        return q.getQType() != null && q.getQType() <= 4
                ? new BigDecimal("5.0") : new BigDecimal("10.0");
    }

    // ------------------------------------------------------------------
    //  作答
    // ------------------------------------------------------------------

    public ExamRecord require(Long examId) {
        ExamRecord exam = examMapper.selectById(examId);
        if (exam == null) {
            throw BusinessException.notFound("答卷", examId);
        }
        return exam;
    }

    /** 自动存草稿：只更新用户答案，不触发判分 */
    @Transactional(rollbackFor = Exception.class)
    public void saveDraft(Long examId, ExamDto.SaveDraftReq req) {
        ExamRecord exam = require(examId);
        if (exam.getStatus() != ExamRecord.STATUS_ONGOING) {
            throw BusinessException.invalid("这份答卷已经提交，不能再修改");
        }
        applyAnswers(examId, req.answers());

        if (req.durationSec() != null) {
            ExamRecord patch = new ExamRecord();
            patch.setId(examId);
            patch.setDurationSec(req.durationSec());
            examMapper.updateById(patch);
        }
    }

    /** 交卷并触发判分 */
    public Long submit(Long examId, ExamDto.SubmitReq req) {
        ExamRecord exam = require(examId);
        if (exam.getStatus() != ExamRecord.STATUS_ONGOING
                && exam.getStatus() != ExamRecord.STATUS_FAILED) {
            throw BusinessException.invalid("这份答卷已经提交过了");
        }

        applyAnswers(examId, req.answers());

        int duration = req.durationSec() != null && req.durationSec() > 0
                ? req.durationSec()
                : (int) Duration.between(exam.getStartedAt(), LocalDateTime.now()).getSeconds();

        ExamRecord patch = new ExamRecord();
        patch.setId(examId);
        patch.setStatus(ExamRecord.STATUS_SUBMITTED);
        patch.setSubmittedAt(LocalDateTime.now());
        patch.setDurationSec(duration);
        examMapper.updateById(patch);

        AsyncTask task = taskService.create(AsyncTask.TYPE_GRADING, examId, 1L);
        ExamRecord patch2 = new ExamRecord();
        patch2.setId(examId);
        patch2.setGradeTaskId(task.getId());
        examMapper.updateById(patch2);

        gradingRunner.runGrade(task.getId(), examId);

        log.info("交卷：exam=#{} 用时 {} 秒，判分任务 #{}", examId, duration, task.getId());
        return task.getId();
    }

    private void applyAnswers(Long examId, List<ExamDto.AnswerReq> answers) {
        if (answers == null || answers.isEmpty()) {
            return;
        }
        Map<Long, AnswerItem> existing = answerMapper.selectList(
                        Wrappers.<AnswerItem>lambdaQuery().eq(AnswerItem::getExamId, examId))
                .stream().collect(Collectors.toMap(AnswerItem::getQuestionId, a -> a));

        for (ExamDto.AnswerReq answer : answers) {
            if (answer.questionId() == null) {
                continue;
            }
            AnswerItem item = existing.get(answer.questionId());
            if (item == null) {
                continue;
            }
            AnswerItem patch = new AnswerItem();
            patch.setId(item.getId());
            patch.setUserAnswer(answer.userAnswer() == null ? "" : answer.userAnswer());
            if (answer.asrText() != null && !answer.asrText().isBlank()) {
                patch.setAsrText(answer.asrText());
            }
            if (answer.inputMode() != null) {
                patch.setInputMode(answer.inputMode());
            }
            answerMapper.updateById(patch);
        }
    }

    // ------------------------------------------------------------------
    //  结果
    // ------------------------------------------------------------------

    public ExamDto.ResultVO result(Long examId) {
        ExamRecord exam = require(examId);

        List<AnswerItem> items = answerMapper.selectList(
                Wrappers.<AnswerItem>lambdaQuery().eq(AnswerItem::getExamId, examId));
        Map<Long, AnswerItem> byQuestion = items.stream()
                .collect(Collectors.toMap(AnswerItem::getQuestionId, a -> a, (a, b) -> a));

        List<PaperItem> paperItems = paperItemMapper.selectList(
                Wrappers.<PaperItem>lambdaQuery()
                        .eq(PaperItem::getPaperId, exam.getPaperId())
                        .orderByAsc(PaperItem::getSortOrder));
        List<Question> questions = loadOrdered(paperItems);
        List<Long> qIds = questions.stream().map(Question::getId).toList();

        Map<Long, List<QuestionDto.OptionVO>> optionMap = questionService.optionsOf(qIds);
        Map<Long, List<com.beibei.dto.DocDto.TagBrief>> tagMap = questionService.tagBriefsOf(qIds);

        List<ExamDto.ItemResultVO> vos = new ArrayList<>();
        boolean graded = exam.getStatus() == ExamRecord.STATUS_GRADED;

        for (Question q : questions) {
            AnswerItem item = byQuestion.get(q.getId());
            if (item == null) {
                continue;
            }
            vos.add(new ExamDto.ItemResultVO(
                    item.getId(), q.getId(), q.getQType(), QuestionDto.typeName(q.getQType()),
                    q.getStem(), q.getCodeSnippet(),
                    optionMap.getOrDefault(q.getId(), List.of()),
                    item.getUserAnswer(), item.getAsrText(), item.getInputMode(),
                    item.getScore(), item.getFullScore(),
                    parseList(item.getHitPoints()),
                    parseList(item.getMissPoints()),
                    parseList(item.getWrongPoints()),
                    parseList(item.getCitations()),
                    item.getAiFeedback(),
                    item.getGradeMethod(), ExamDto.gradeMethodName(item.getGradeMethod()),
                    // 练习模式答完就能看答案；考试模式必须等判分完成
                    graded ? q.getAnswer() : null,
                    graded ? q.getAnalysis() : null,
                    tagMap.getOrDefault(q.getId(), List.of()),
                    item.getAppealStatus(), item.getAppealReason(),
                    item.getAppealScore(), parseList(item.getAppealResult())
            ));
        }

        BigDecimal total = exam.getTotalScore() == null ? BigDecimal.ZERO : exam.getTotalScore();
        BigDecimal got = exam.getGotScore() == null ? BigDecimal.ZERO : exam.getGotScore();
        double rate = total.compareTo(BigDecimal.ZERO) == 0 ? 0.0
                : got.multiply(new BigDecimal("100"))
                  .divide(total, 1, RoundingMode.HALF_UP).doubleValue();

        return new ExamDto.ResultVO(
                exam.getId(), exam.getPaperId(), exam.getKbId(), exam.getTitle(),
                exam.getStatus(), exam.getExamMode(), total, got, rate,
                exam.getCorrectCount(), exam.getWrongCount(), exam.getDurationSec(),
                exam.getStartedAt(), exam.getSubmittedAt(), exam.getGradedAt(), vos
        );
    }

    public List<ExamDto.ExamVO> list(Long kbId) {
        var query = Wrappers.<ExamRecord>lambdaQuery().orderByDesc(ExamRecord::getStartedAt);
        if (kbId != null) {
            query.eq(ExamRecord::getKbId, kbId);
        }
        return examMapper.selectList(query).stream().map(e -> {
            BigDecimal total = e.getTotalScore() == null ? BigDecimal.ZERO : e.getTotalScore();
            BigDecimal got = e.getGotScore() == null ? BigDecimal.ZERO : e.getGotScore();
            double rate = total.compareTo(BigDecimal.ZERO) == 0 ? 0.0
                    : got.multiply(new BigDecimal("100"))
                      .divide(total, 1, RoundingMode.HALF_UP).doubleValue();
            return new ExamDto.ExamVO(
                    e.getId(), e.getPaperId(), e.getKbId(), e.getTitle(),
                    e.getStatus(), ExamDto.statusName(e.getStatus()), e.getExamMode(),
                    total, got, rate, e.getCorrectCount(), e.getWrongCount(),
                    e.getDurationSec(), e.getStartedAt(), e.getSubmittedAt());
        }).toList();
    }

    // ------------------------------------------------------------------
    //  申诉
    // ------------------------------------------------------------------

    public Long appeal(Long answerItemId, String reason) {
        AnswerItem item = answerMapper.selectById(answerItemId);
        if (item == null) {
            throw BusinessException.notFound("作答记录", answerItemId);
        }
        ExamRecord exam = require(item.getExamId());
        if (exam.getStatus() != ExamRecord.STATUS_GRADED) {
            throw BusinessException.invalid("这份答卷还没有判分完成，暂时不能申诉");
        }

        AnswerItem patch = new AnswerItem();
        patch.setId(answerItemId);
        patch.setAppealStatus(AnswerItem.APPEAL_PENDING);
        patch.setAppealReason(reason == null ? "" : reason.trim());
        answerMapper.updateById(patch);

        AsyncTask task = taskService.create(AsyncTask.TYPE_APPEAL, answerItemId, 1L);
        gradingRunner.runAppeal(task.getId(), exam.getId(), answerItemId,
                reason == null ? "" : reason.trim());

        log.info("申诉重判：answerItem=#{} exam=#{} 理由={}", answerItemId, exam.getId(), reason);
        return task.getId();
    }

    // ------------------------------------------------------------------

    private List<Object> parseList(String json) {
        if (json == null || json.isBlank()) {
            return List.of();
        }
        try {
            return objectMapper.readValue(json, List.class);
        } catch (Exception e) {
            return List.of();
        }
    }
}
