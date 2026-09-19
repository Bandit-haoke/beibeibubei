package com.beibei.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.beibei.common.BusinessException;
import com.beibei.config.EmbeddingProperties;
import com.beibei.dto.PaperDto;
import com.beibei.dto.QuestionDto;
import com.beibei.entity.AsyncTask;
import com.beibei.entity.KnowledgeBase;
import com.beibei.entity.Paper;
import com.beibei.entity.PaperItem;
import com.beibei.entity.Question;
import com.beibei.mapper.PaperItemMapper;
import com.beibei.mapper.PaperMapper;
import com.beibei.mapper.QuestionMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 题卷业务：发起 AI 出题、审核草稿、管理题卷。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PaperService {

    private static final DateTimeFormatter TITLE_TIME = DateTimeFormatter.ofPattern("MM-dd HH:mm");

    private final PaperMapper paperMapper;
    private final PaperItemMapper paperItemMapper;
    private final QuestionMapper questionMapper;
    private final KnowledgeBaseService kbService;
    private final QuestionService questionService;
    private final AsyncTaskService taskService;
    private final GenerationRunner generationRunner;
    private final EmbeddingProperties embedding;
    private final ObjectMapper objectMapper;

    // ------------------------------------------------------------------
    //  出题
    // ------------------------------------------------------------------

    public PaperDto.GenerateResult generate(PaperDto.GenerateReq req) {
        KnowledgeBase kb = kbService.require(req.kbId());

        String title = (req.title() == null || req.title().isBlank())
                ? "「" + kb.getName() + "」AI 出题 · " + req.count() + " 道 · "
                  + LocalDateTime.now().format(TITLE_TIME)
                : req.title().trim();

        Paper paper = new Paper();
        paper.setKbId(req.kbId());
        paper.setUserId(1L);
        paper.setTitle(title);
        paper.setSource(Paper.SOURCE_AI);
        paper.setTotalCount(0);
        paper.setTotalScore(BigDecimal.ZERO);
        paper.setQTypeRatio(toJson(req.qTypeRatio()));
        paper.setDifficultyRatio(toJson(req.difficultyRatio()));
        paper.setTagIds(toJson(req.tagIds()));
        paper.setDurationLimit(0);
        paper.setStatus(Paper.STATUS_GENERATING);
        paper.setGenTaskId(0L);
        paper.setProviderId(req.providerId() == null ? 0L : req.providerId());
        paperMapper.insert(paper);

        AsyncTask task = taskService.create(AsyncTask.TYPE_GEN_QUESTION, paper.getId(), 1L);

        Paper patch = new Paper();
        patch.setId(paper.getId());
        patch.setGenTaskId(task.getId());
        paperMapper.updateById(patch);

        generationRunner.runGenerate(
                task.getId(), paper.getId(), req.kbId(),
                req.count(),
                req.tagIds(),
                req.includeChildTags() == null || req.includeChildTags(),
                req.qTypeRatio(),
                req.difficultyRatio(),
                req.selfCheck() == null || req.selfCheck(),
                kb.getMilvusCollection(),
                embedding.partitionOf(req.kbId())
        );

        log.info("发起出题：paper=#{} kb=#{} count={}", paper.getId(), req.kbId(), req.count());
        return new PaperDto.GenerateResult(paper.getId(), task.getId());
    }

    // 出题成功/失败后的状态收尾（markGenerated / markFailed / recomputeTotals）
    // 已挪到 PaperStatusService —— 否则 PaperService ↔ GenerationRunner 会形成循环依赖，
    // Spring Boot 2.6+ 默认禁止循环引用，应用会直接启动失败。

    // ------------------------------------------------------------------
    //  查询
    // ------------------------------------------------------------------

    public List<PaperDto.VO> list(Long kbId) {
        var query = Wrappers.<Paper>lambdaQuery().orderByDesc(Paper::getCreatedAt);
        if (kbId != null) {
            query.eq(Paper::getKbId, kbId);
        }
        return paperMapper.selectList(query).stream().map(this::toVO).toList();
    }

    public Paper require(Long id) {
        Paper paper = paperMapper.selectById(id);
        if (paper == null) {
            throw BusinessException.notFound("题卷", id);
        }
        return paper;
    }

    public PaperDto.DetailVO detail(Long id, boolean onlyReviewable) {
        Paper paper = require(id);
        List<PaperItem> items = paperItemMapper.selectList(
                Wrappers.<PaperItem>lambdaQuery()
                        .eq(PaperItem::getPaperId, id)
                        .orderByAsc(PaperItem::getSortOrder));

        List<Long> questionIds = items.stream().map(PaperItem::getQuestionId).toList();
        List<Question> questions = questionIds.isEmpty() ? List.of()
                : questionMapper.selectByIds(questionIds);

        // 保持 paper_item 里的顺序
        Map<Long, Question> index = new LinkedHashMap<>();
        questions.forEach(q -> index.put(q.getId(), q));
        List<Question> ordered = questionIds.stream().map(index::get).filter(java.util.Objects::nonNull).toList();
        if (onlyReviewable) {
            ordered = ordered.stream()
                    .filter(q -> q.getStatus() == Question.STATUS_DRAFT)
                    .toList();
        }

        return new PaperDto.DetailVO(toVO(paper), questionService.enrich(ordered));
    }

    public PaperDto.VO toVO(Paper p) {
        List<PaperItem> items = paperItemMapper.selectList(
                Wrappers.<PaperItem>lambdaQuery().eq(PaperItem::getPaperId, p.getId()));
        int total = items.size();
        int published = 0;
        int draft = 0;
        if (!items.isEmpty()) {
            List<Long> ids = items.stream().map(PaperItem::getQuestionId).toList();
            List<Question> questions = questionMapper.selectByIds(ids);
            for (Question q : questions) {
                if (q.getStatus() == Question.STATUS_PUBLISHED) {
                    published++;
                } else if (q.getStatus() == Question.STATUS_DRAFT) {
                    draft++;
                }
            }
        }

        return new PaperDto.VO(
                p.getId(), p.getKbId(), p.getTitle(), p.getSource(),
                total, p.getTotalScore(), p.getDurationLimit(), p.getStatus(),
                parseMap(p.getGenSummary()), draft, published, p.getCreatedAt()
        );
    }

    // ------------------------------------------------------------------
    //  删除
    // ------------------------------------------------------------------

    @Transactional(rollbackFor = Exception.class)
    public void delete(Long id, boolean withQuestions) {
        require(id);
        List<PaperItem> items = paperItemMapper.selectList(
                Wrappers.<PaperItem>lambdaQuery().eq(PaperItem::getPaperId, id));
        paperItemMapper.delete(Wrappers.<PaperItem>lambdaQuery().eq(PaperItem::getPaperId, id));

        if (withQuestions) {
            for (PaperItem item : items) {
                try {
                    questionService.delete(item.getQuestionId());
                } catch (Exception e) {
                    log.warn("删除题目 #{} 失败：{}", item.getQuestionId(), e.getMessage());
                }
            }
        }
        paperMapper.deleteById(id);
        log.info("删除题卷 #{}（连带 {} 道题：{}）", id, items.size(), withQuestions);
    }

    // ------------------------------------------------------------------

    private String toJson(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception e) {
            return null;
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> parseMap(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readValue(json, Map.class);
        } catch (Exception e) {
            return null;
        }
    }

    public List<QuestionDto.VO> questionsOf(Long paperId) {
        return detail(paperId, false).questions();
    }

    /** 整卷通过审核：把该题卷下所有草稿题一次性发布 */
    @Transactional(rollbackFor = Exception.class)
    public int approveAll(Long paperId) {
        List<PaperItem> items = paperItemMapper.selectList(
                Wrappers.<PaperItem>lambdaQuery().eq(PaperItem::getPaperId, paperId));
        List<Long> ids = items.stream().map(PaperItem::getQuestionId).toList();

        int approved = questionService.approve(ids);

        Long remainingDrafts = questionMapper.selectCount(
                Wrappers.<Question>lambdaQuery()
                        .in(!ids.isEmpty(), Question::getId, ids)
                        .eq(Question::getStatus, Question.STATUS_DRAFT));

        Paper patch = new Paper();
        patch.setId(paperId);
        // 还有草稿就停在「待审」，全部通过了才转「可用」
        patch.setStatus(remainingDrafts != null && remainingDrafts > 0
                ? Paper.STATUS_PENDING_REVIEW : Paper.STATUS_READY);
        paperMapper.updateById(patch);

        log.info("题卷 #{} 整卷审核：通过 {} 道，剩余草稿 {}", paperId, approved, remainingDrafts);
        return approved;
    }

    /** 重新出题：清掉本卷的草稿题，再跑一次生成 */
    public PaperDto.GenerateResult regenerate(Long paperId, Integer count, Boolean selfCheck) {
        Paper paper = require(paperId);

        int removed = questionService.deleteDraftsOfPaper(paperId);
        log.info("重新出题前清理 {} 道草稿（paper=#{}）", removed, paperId);

        PaperDto.GenerateReq req = new PaperDto.GenerateReq(
                paper.getKbId(),
                paper.getTitle(),
                count != null ? count : Math.max(1, paper.getTotalCount()),
                parseLongList(paper.getTagIds()),
                true,
                parseDoubleMap(paper.getQTypeRatio()),
                parseDoubleMap(paper.getDifficultyRatio()),
                selfCheck == null || selfCheck,
                paper.getProviderId()
        );
        return generate(req);
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

    @SuppressWarnings("unchecked")
    private Map<String, Double> parseDoubleMap(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            Map<String, Object> raw = objectMapper.readValue(json, Map.class);
            Map<String, Double> out = new LinkedHashMap<>();
            raw.forEach((k, v) -> {
                if (v instanceof Number n) {
                    out.put(k, n.doubleValue());
                }
            });
            return out;
        } catch (Exception e) {
            return null;
        }
    }
}
