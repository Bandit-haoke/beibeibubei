package com.beibei.service;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.beibei.common.BusinessException;
import com.beibei.common.PageResult;
import com.beibei.dto.DocDto;
import com.beibei.dto.QuestionDto;
import com.beibei.entity.Question;
import com.beibei.entity.QuestionOption;
import com.beibei.entity.QuestionTag;
import com.beibei.mapper.QuestionMapper;
import com.beibei.mapper.QuestionOptionMapper;
import com.beibei.mapper.QuestionTagMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 题库业务。
 *
 * <p>审核心跳：AI 生成的题一律 {@code DRAFT}，只有 {@code approve} 之后才是
 * {@code PUBLISHED}。组卷/答题只捞已发布的。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class QuestionService {

    private final QuestionMapper questionMapper;
    private final QuestionOptionMapper optionMapper;
    private final QuestionTagMapper questionTagMapper;
    private final com.beibei.mapper.PaperItemMapper paperItemMapper;
    private final TagService tagService;
    private final ObjectMapper objectMapper;

    // ------------------------------------------------------------------
    //  查询
    // ------------------------------------------------------------------

    public PageResult<QuestionDto.VO> list(Long kbId, Integer status, Integer qType, Integer difficulty,
                                           Long tagId, String keyword, long pageNum, long pageSize) {
        var query = Wrappers.<Question>lambdaQuery()
                .eq(kbId != null, Question::getKbId, kbId)
                .eq(status != null, Question::getStatus, status)
                .eq(qType != null, Question::getQType, qType)
                .eq(difficulty != null, Question::getDifficulty, difficulty)
                .orderByDesc(Question::getCreatedAt);
        if (keyword != null && !keyword.isBlank()) {
            query.like(Question::getStem, keyword.trim());
        }

        // 按知识点过滤：先查出该知识点下的题目 ID
        if (tagId != null) {
            List<Long> ids = questionTagMapper.selectList(
                            Wrappers.<QuestionTag>lambdaQuery().eq(QuestionTag::getTagId, tagId))
                    .stream().map(QuestionTag::getQuestionId).toList();
            if (ids.isEmpty()) {
                return PageResult.empty(pageNum, pageSize);
            }
            query.in(Question::getId, ids);
        }

        IPage<Question> page = questionMapper.selectPage(new Page<>(pageNum, pageSize), query);
        return PageResult.of(page, q -> toVO(q, null, null));
    }

    /** 批量装配选项与知识点，避免 N+1 */
    public List<QuestionDto.VO> enrich(List<Question> questions) {
        if (questions == null || questions.isEmpty()) {
            return List.of();
        }
        List<Long> ids = questions.stream().map(Question::getId).toList();

        Map<Long, List<QuestionOption>> optionMap = optionMapper.selectList(
                        Wrappers.<QuestionOption>lambdaQuery()
                                .in(QuestionOption::getQuestionId, ids)
                                .orderByAsc(QuestionOption::getSortOrder))
                .stream().collect(Collectors.groupingBy(QuestionOption::getQuestionId));

        List<QuestionTag> relations = questionTagMapper.selectList(
                Wrappers.<QuestionTag>lambdaQuery().in(QuestionTag::getQuestionId, ids));

        Map<Long, List<DocDto.TagBrief>> tagMap = new LinkedHashMap<>();
        if (!relations.isEmpty()) {
            List<Long> tagIds = relations.stream().map(QuestionTag::getTagId).distinct().toList();
            Map<Long, com.beibei.entity.Tag> tagIndex = tagService.requireAll(tagIds).stream()
                    .collect(Collectors.toMap(com.beibei.entity.Tag::getId, t -> t));
            for (QuestionTag relation : relations) {
                com.beibei.entity.Tag tag = tagIndex.get(relation.getTagId());
                if (tag != null) {
                    tagMap.computeIfAbsent(relation.getQuestionId(), k -> new ArrayList<>())
                            .add(new DocDto.TagBrief(tag.getId(), tag.getName(), tag.getLevel()));
                }
            }
        }

        return questions.stream()
                .map(q -> toVO(q, optionMap.get(q.getId()), tagMap.get(q.getId())))
                .toList();
    }

    public Question require(Long id) {
        Question question = questionMapper.selectById(id);
        if (question == null) {
            throw BusinessException.notFound("题目", id);
        }
        return question;
    }

    public QuestionDto.VO detail(Long id) {
        Question question = require(id);
        List<QuestionDto.VO> enriched = enrich(List.of(question));
        return enriched.get(0);
    }

    public List<QuestionDto.VO> byPaper(Long paperId) {
        return List.of();
    }

    // ------------------------------------------------------------------
    //  审核
    // ------------------------------------------------------------------

    @Transactional(rollbackFor = Exception.class)
    public int approve(List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return 0;
        }
        int updated = 0;
        for (Long id : ids) {
            Question question = questionMapper.selectById(id);
            if (question == null || question.getStatus() != Question.STATUS_DRAFT) {
                continue;
            }
            Question patch = new Question();
            patch.setId(id);
            patch.setStatus(Question.STATUS_PUBLISHED);
            questionMapper.updateById(patch);
            updated++;
        }
        log.info("审核通过 {} 道题", updated);
        return updated;
    }

    @Transactional(rollbackFor = Exception.class)
    public int approveByBatch(String genBatchId) {
        List<Question> drafts = questionMapper.selectList(
                Wrappers.<Question>lambdaQuery()
                        .eq(Question::getGenBatchId, genBatchId)
                        .eq(Question::getStatus, Question.STATUS_DRAFT));
        return approve(drafts.stream().map(Question::getId).toList());
    }

    public void disable(Long id) {
        require(id);
        Question patch = new Question();
        patch.setId(id);
        patch.setStatus(Question.STATUS_DISABLED);
        questionMapper.updateById(patch);
    }

    @Transactional(rollbackFor = Exception.class)
    public void delete(Long id) {
        require(id);
        optionMapper.delete(Wrappers.<QuestionOption>lambdaQuery().eq(QuestionOption::getQuestionId, id));
        questionTagMapper.delete(Wrappers.<QuestionTag>lambdaQuery().eq(QuestionTag::getQuestionId, id));
        questionMapper.deleteById(id);
    }

    /** 删除整批 AI 生成的草稿题（重新生成前清理） */
    @Transactional(rollbackFor = Exception.class)
    public int deleteDraftsOfPaper(Long paperId) {
        List<Long> ids = paperItemQuestionIds(paperId);
        if (ids.isEmpty()) {
            return 0;
        }
        List<Question> drafts = questionMapper.selectList(
                Wrappers.<Question>lambdaQuery()
                        .in(Question::getId, ids)
                        .eq(Question::getStatus, Question.STATUS_DRAFT));
        for (Question question : drafts) {
            delete(question.getId());
        }
        return drafts.size();
    }

    private List<Long> paperItemQuestionIds(Long paperId) {
        return paperItemMapper.selectList(
                        Wrappers.<com.beibei.entity.PaperItem>lambdaQuery()
                                .eq(com.beibei.entity.PaperItem::getPaperId, paperId))
                .stream().map(com.beibei.entity.PaperItem::getQuestionId).toList();
    }

    // ------------------------------------------------------------------
    //  给答题页/结果页用的批量查询（避免 N+1）
    // ------------------------------------------------------------------

    /** 批量取选项：questionId -> 选项列表（不含 isCorrect 的语义由 correct 字段承载） */
    public Map<Long, List<QuestionDto.OptionVO>> optionsOf(List<Long> questionIds) {
        if (questionIds == null || questionIds.isEmpty()) {
            return Map.of();
        }
        List<QuestionOption> options = optionMapper.selectList(
                Wrappers.<QuestionOption>lambdaQuery()
                        .in(QuestionOption::getQuestionId, questionIds)
                        .orderByAsc(QuestionOption::getSortOrder));
        Map<Long, List<QuestionDto.OptionVO>> out = new LinkedHashMap<>();
        for (QuestionOption o : options) {
            out.computeIfAbsent(o.getQuestionId(), k -> new ArrayList<>())
                    .add(new QuestionDto.OptionVO(o.getId(), o.getOptionKey(), o.getContent(),
                            o.getIsCorrect() != null && o.getIsCorrect() == 1));
        }
        return out;
    }

    /** 批量取题目挂的知识点 */
    public Map<Long, List<DocDto.TagBrief>> tagBriefsOf(List<Long> questionIds) {
        if (questionIds == null || questionIds.isEmpty()) {
            return Map.of();
        }
        List<QuestionTag> relations = questionTagMapper.selectList(
                Wrappers.<QuestionTag>lambdaQuery().in(QuestionTag::getQuestionId, questionIds));
        if (relations.isEmpty()) {
            return Map.of();
        }
        List<Long> tagIds = relations.stream().map(QuestionTag::getTagId).distinct().toList();
        Map<Long, com.beibei.entity.Tag> index = tagService.requireAll(tagIds).stream()
                .collect(Collectors.toMap(com.beibei.entity.Tag::getId, t -> t));

        Map<Long, List<DocDto.TagBrief>> out = new LinkedHashMap<>();
        for (QuestionTag relation : relations) {
            com.beibei.entity.Tag tag = index.get(relation.getTagId());
            if (tag != null) {
                out.computeIfAbsent(relation.getQuestionId(), k -> new ArrayList<>())
                        .add(new DocDto.TagBrief(tag.getId(), tag.getName(), tag.getLevel()));
            }
        }
        return out;
    }

    // ------------------------------------------------------------------
    //  编辑 / 新增
    // ------------------------------------------------------------------

    @Transactional(rollbackFor = Exception.class)
    public void update(Long id, QuestionDto.UpdateReq req) {
        Question question = require(id);

        Question patch = new Question();
        patch.setId(id);
        if (req.stem() != null && !req.stem().isBlank()) {
            patch.setStem(req.stem().trim());
        }
        if (req.answer() != null && !req.answer().isBlank()) {
            patch.setAnswer(req.answer().trim());
        }
        if (req.analysis() != null) {
            patch.setAnalysis(req.analysis());
        }
        if (req.difficulty() != null) {
            patch.setDifficulty(req.difficulty());
        }
        if (req.codeSnippet() != null) {
            patch.setCodeSnippet(req.codeSnippet());
        }
        questionMapper.updateById(patch);

        if (req.options() != null && !req.options().isEmpty()) {
            optionMapper.delete(Wrappers.<QuestionOption>lambdaQuery()
                    .eq(QuestionOption::getQuestionId, id));
            insertOptions(id, req.options());
        }

        if (req.tagIds() != null) {
            questionTagMapper.delete(Wrappers.<QuestionTag>lambdaQuery()
                    .eq(QuestionTag::getQuestionId, id));
            for (Long tagId : req.tagIds()) {
                QuestionTag relation = new QuestionTag();
                relation.setQuestionId(id);
                relation.setTagId(tagId);
                relation.setKbId(question.getKbId());
                questionTagMapper.insert(relation);
            }
        }
        log.info("编辑题目 #{}", id);
    }

    @Transactional(rollbackFor = Exception.class)
    public Long create(QuestionDto.ManualReq req) {
        if (req.qType() == null || req.qType() < 1 || req.qType() > 9) {
            throw BusinessException.invalid("题型不合法");
        }
        Question question = new Question();
        question.setKbId(req.kbId());
        question.setQType(req.qType());
        question.setDifficulty(req.difficulty() == null ? 2 : req.difficulty());
        question.setStem(req.stem().trim());
        question.setAnswer(req.answer().trim());
        question.setAnalysis(req.analysis() == null ? "" : req.analysis());
        question.setCodeSnippet(req.codeSnippet());
        question.setSourceChunkIds("[]");
        question.setSourceDocId(0L);
        // 手动录入的题直接发布，不需要审核
        question.setStatus(Question.STATUS_PUBLISHED);
        question.setOrigin(Question.ORIGIN_MANUAL);
        question.setGenBatchId("");
        question.setQualityScore(BigDecimal.ONE);
        question.setSelfCheckMsg("手动录入");
        question.setUseCount(0);
        question.setCorrectCount(0);
        question.setAvgScoreRate(BigDecimal.ZERO);
        questionMapper.insert(question);

        if (req.options() != null) {
            insertOptions(question.getId(), req.options());
        }
        if (req.tagIds() != null) {
            for (Long tagId : req.tagIds()) {
                QuestionTag relation = new QuestionTag();
                relation.setQuestionId(question.getId());
                relation.setTagId(tagId);
                relation.setKbId(req.kbId());
                questionTagMapper.insert(relation);
            }
        }
        log.info("手动新增题目 #{}", question.getId());
        return question.getId();
    }

    private void insertOptions(Long questionId, List<QuestionDto.OptionReq> options) {
        int order = 0;
        for (QuestionDto.OptionReq option : options) {
            if (option.content() == null || option.content().isBlank()) {
                continue;
            }
            QuestionOption entity = new QuestionOption();
            entity.setQuestionId(questionId);
            entity.setOptionKey(option.key() == null ? String.valueOf((char) ('A' + order))
                    : option.key().trim().toUpperCase());
            entity.setContent(option.content().trim());
            entity.setIsCorrect(Boolean.TRUE.equals(option.correct()) ? 1 : 0);
            entity.setSortOrder(order++);
            optionMapper.insert(entity);
        }
    }

    // ------------------------------------------------------------------
    //  转换
    // ------------------------------------------------------------------

    public QuestionDto.VO toVO(Question q, List<QuestionOption> options, List<DocDto.TagBrief> tags) {
        List<QuestionDto.OptionVO> optionVOs = options == null ? List.of()
                : options.stream()
                .map(o -> new QuestionDto.OptionVO(o.getId(), o.getOptionKey(), o.getContent(),
                        o.getIsCorrect() != null && o.getIsCorrect() == 1))
                .toList();

        return new QuestionDto.VO(
                q.getId(), q.getKbId(), q.getQType(), QuestionDto.typeName(q.getQType()),
                q.getDifficulty(), QuestionDto.difficultyName(q.getDifficulty()),
                q.getStem(), q.getAnswer(), q.getAnalysis(),
                parseJson(q.getRubric()), q.getCodeSnippet(),
                optionVOs,
                tags == null ? List.of() : tags,
                parseLongList(q.getSourceChunkIds()),
                q.getStatus(), q.getOrigin(), q.getGenBatchId(),
                q.getQualityScore(), q.getSelfCheckMsg(),
                q.getUseCount(), q.getCorrectCount(), q.getAvgScoreRate(),
                q.getCreatedAt()
        );
    }

    private Object parseJson(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readValue(json, Object.class);
        } catch (Exception e) {
            return null;
        }
    }

    private List<Long> parseLongList(String json) {
        if (json == null || json.isBlank()) {
            return List.of();
        }
        try {
            return objectMapper.readValue(json,
                    objectMapper.getTypeFactory().constructCollectionType(List.class, Long.class));
        } catch (Exception e) {
            return List.of();
        }
    }
}
