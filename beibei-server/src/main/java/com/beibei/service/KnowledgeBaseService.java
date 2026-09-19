package com.beibei.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.beibei.common.BusinessException;
import com.beibei.config.EmbeddingProperties;
import com.beibei.dto.KbDto;
import com.beibei.entity.Document;
import com.beibei.entity.KnowledgeBase;
import com.beibei.entity.Tag;
import com.beibei.mapper.DocChunkMapper;
import com.beibei.mapper.DocumentMapper;
import com.beibei.mapper.KnowledgeBaseMapper;
import com.beibei.mapper.TagMapper;
import com.beibei.entity.DocChunk;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 知识库业务。
 *
 * <p>硬约束：{@code embeddingModel} 创建后不可修改。换向量模型会让已入库向量不可比，
 * 只能新建知识库重新入库。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class KnowledgeBaseService {

    private final KnowledgeBaseMapper kbMapper;
    private final DocumentMapper documentMapper;
    private final DocChunkMapper chunkMapper;
    private final TagMapper tagMapper;
    private final EmbeddingProperties embedding;
    private final AgentClient agentClient;
    // 级联删除需要用到这些（删知识库要连答卷、错题、题目一起清）
    private final com.beibei.mapper.ExamRecordMapper examMapper;
    private final com.beibei.mapper.AnswerItemMapper answerItemMapper;
    private final com.beibei.mapper.MistakeMapper mistakeMapper;
    private final com.beibei.mapper.ReviewLogMapper reviewLogMapper;
    private final com.beibei.mapper.QuestionMapper questionMapper;
    private final com.beibei.mapper.QuestionOptionMapper questionOptionMapper;
    private final com.beibei.mapper.QuestionTagMapper questionTagMapper;
    private final com.beibei.mapper.PaperMapper paperMapper;
    private final com.beibei.mapper.PaperItemMapper paperItemMapper;
    private final com.beibei.mapper.ChunkTagMapper chunkTagMapper;

    public List<KbDto.VO> list(String keyword) {
        var query = Wrappers.<KnowledgeBase>lambdaQuery()
                .eq(KnowledgeBase::getUserId, 1L)
                .orderByDesc(KnowledgeBase::getCreatedAt);
        if (keyword != null && !keyword.isBlank()) {
            query.like(KnowledgeBase::getName, keyword.trim());
        }
        return kbMapper.selectList(query).stream().map(this::toVO).toList();
    }

    public KnowledgeBase require(Long id) {
        KnowledgeBase kb = kbMapper.selectById(id);
        if (kb == null) {
            throw BusinessException.notFound("知识库", id);
        }
        return kb;
    }

    /** 取名称，查不到不报错（导出文件名用） */
    public String nameOf(Long id) {
        KnowledgeBase kb = kbMapper.selectById(id);
        return kb == null ? "知识库" + id : kb.getName();
    }

    public KnowledgeBase create(KbDto.CreateReq req) {
        String model = embedding.defaultModel();
        KnowledgeBase kb = new KnowledgeBase();
        kb.setUserId(1L);
        kb.setName(req.name().trim());
        kb.setDescription(req.description() == null ? "" : req.description());
        kb.setCoverColor(req.coverColor() == null || req.coverColor().isBlank()
                ? randomColor() : req.coverColor());
        kb.setEmbeddingModel(model);
        kb.setMilvusCollection(embedding.collectionOf(model));
        kb.setChunkSize(700);
        kb.setChunkOverlap(105);
        kb.setDocCount(0);
        kb.setChunkCount(0);
        kb.setQuestionCount(0);
        kb.setStatus(1);
        kbMapper.insert(kb);

        // 让 Python 提前把 Milvus 分区建出来；失败不阻塞创建（首次入库时还会再试）
        try {
            agentClient.ensurePartition(embedding.collectionOf(model), embedding.partitionOf(kb.getId()));
        } catch (Exception e) {
            log.warn("预创建 Milvus 分区失败（不影响知识库创建）: {}", e.getMessage());
        }

        log.info("创建知识库 #{} {}", kb.getId(), kb.getName());
        return kb;
    }

    public KbDto.VO update(Long id, KbDto.UpdateReq req) {
        KnowledgeBase kb = require(id);
        if (req.name() != null && !req.name().isBlank()) {
            kb.setName(req.name().trim());
        }
        if (req.description() != null) {
            kb.setDescription(req.description());
        }
        if (req.coverColor() != null && !req.coverColor().isBlank()) {
            kb.setCoverColor(req.coverColor());
        }
        if (req.status() != null) {
            kb.setStatus(req.status());
        }
        // embeddingModel / milvusCollection 刻意不允许修改
        kbMapper.updateById(kb);
        return toVO(kb);
    }

    /**
     * 删除知识库：连文档、分块、知识点、题目、答卷、错题本、Milvus 分区一起清掉。
     */
    @Transactional(rollbackFor = Exception.class)
    public void delete(Long id) {
        KnowledgeBase kb = require(id);

        // 答卷与错题本也要清 —— 否则删了知识库，历史答卷会变成查不到题目的孤儿数据
        List<Long> examIds = examMapper.selectList(
                        Wrappers.<com.beibei.entity.ExamRecord>lambdaQuery()
                                .eq(com.beibei.entity.ExamRecord::getKbId, id))
                .stream().map(com.beibei.entity.ExamRecord::getId).toList();
        if (!examIds.isEmpty()) {
            answerItemMapper.delete(Wrappers.<com.beibei.entity.AnswerItem>lambdaQuery()
                    .in(com.beibei.entity.AnswerItem::getExamId, examIds));
            examMapper.deleteByIds(examIds);
        }

        List<Long> mistakeIds = mistakeMapper.selectList(
                        Wrappers.<com.beibei.entity.Mistake>lambdaQuery()
                                .eq(com.beibei.entity.Mistake::getKbId, id))
                .stream().map(com.beibei.entity.Mistake::getId).toList();
        if (!mistakeIds.isEmpty()) {
            reviewLogMapper.delete(Wrappers.<com.beibei.entity.ReviewLog>lambdaQuery()
                    .in(com.beibei.entity.ReviewLog::getMistakeId, mistakeIds));
            mistakeMapper.deleteByIds(mistakeIds);
        }

        // 题目（含选项与知识点关联）
        List<Long> questionIds = questionMapper.selectList(
                        Wrappers.<com.beibei.entity.Question>lambdaQuery()
                                .eq(com.beibei.entity.Question::getKbId, id))
                .stream().map(com.beibei.entity.Question::getId).toList();
        if (!questionIds.isEmpty()) {
            questionOptionMapper.delete(Wrappers.<com.beibei.entity.QuestionOption>lambdaQuery()
                    .in(com.beibei.entity.QuestionOption::getQuestionId, questionIds));
            questionTagMapper.delete(Wrappers.<com.beibei.entity.QuestionTag>lambdaQuery()
                    .in(com.beibei.entity.QuestionTag::getQuestionId, questionIds));
            questionMapper.deleteByIds(questionIds);
        }

        paperItemMapper.delete(Wrappers.<com.beibei.entity.PaperItem>lambdaQuery()
                .inSql(com.beibei.entity.PaperItem::getPaperId,
                        "SELECT id FROM bb_paper WHERE kb_id = " + id));
        paperMapper.delete(Wrappers.<com.beibei.entity.Paper>lambdaQuery()
                .eq(com.beibei.entity.Paper::getKbId, id));

        int docs = documentMapper.delete(Wrappers.<Document>lambdaQuery().eq(Document::getKbId, id));
        int chunks = chunkMapper.delete(Wrappers.<DocChunk>lambdaQuery().eq(DocChunk::getKbId, id));
        chunkTagMapper.delete(Wrappers.<com.beibei.entity.ChunkTag>lambdaQuery()
                .eq(com.beibei.entity.ChunkTag::getKbId, id));
        tagMapper.delete(Wrappers.<Tag>lambdaQuery().eq(Tag::getKbId, id));
        kbMapper.deleteById(id);

        // 向量库的清理放在数据库事务之外，失败只记日志（有 consistency-check 兜底）
        try {
            agentClient.dropPartition(kb.getMilvusCollection(), embedding.partitionOf(id));
        } catch (Exception e) {
            log.warn("删除 Milvus 分区失败（知识库 #{}）: {}", id, e.getMessage());
        }

        log.info("删除知识库 #{}：文档 {} / 分块 {} / 题目 {} / 答卷 {} / 错题 {}",
                id, docs, chunks, questionIds.size(), examIds.size(), mistakeIds.size());
    }

    /** 重算冗余计数（文档数 / 分块数 / 知识点数），在入库完成后调用 */
    public void refreshCounters(Long kbId) {
        Long docCount = documentMapper.selectCount(
                Wrappers.<Document>lambdaQuery()
                        .eq(Document::getKbId, kbId)
                        .eq(Document::getStatus, Document.STATUS_READY));
        Long chunkCount = chunkMapper.selectCount(
                Wrappers.<DocChunk>lambdaQuery().eq(DocChunk::getKbId, kbId));
        Long tagCount = tagMapper.selectCount(
                Wrappers.<Tag>lambdaQuery().eq(Tag::getKbId, kbId));

        KnowledgeBase patch = new KnowledgeBase();
        patch.setId(kbId);
        patch.setDocCount(docCount.intValue());
        patch.setChunkCount(chunkCount.intValue());
        kbMapper.updateById(patch);

        log.debug("知识库 #{} 计数已刷新: 文档={} 分块={} 知识点={}", kbId, docCount, chunkCount, tagCount);
    }

    public KbDto.StatVO stat(Long kbId) {
        require(kbId);
        int docCount = documentMapper.selectCount(
                Wrappers.<Document>lambdaQuery()
                        .eq(Document::getKbId, kbId)
                        .eq(Document::getStatus, Document.STATUS_READY)).intValue();
        int chunkCount = chunkMapper.selectCount(
                Wrappers.<DocChunk>lambdaQuery().eq(DocChunk::getKbId, kbId)).intValue();
        int tagCount = tagMapper.selectCount(
                Wrappers.<Tag>lambdaQuery().eq(Tag::getKbId, kbId)).intValue();

        List<Map<String, Object>> mastery = new ArrayList<>();
        for (Tag t : tagMapper.selectList(Wrappers.<Tag>lambdaQuery()
                .eq(Tag::getKbId, kbId).orderByDesc(Tag::getChunkCount).last("limit 20"))) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("tagId", t.getId());
            m.put("name", t.getName());
            m.put("chunkCount", t.getChunkCount());
            m.put("questionCount", t.getQuestionCount());
            m.put("scoreRate", 0.0);   // M4 接上答题数据后填充
            mastery.add(m);
        }

        return new KbDto.StatVO(kbId, docCount, chunkCount, 0, tagCount, 0, 0.0, mastery);
    }

    public KbDto.VO toVO(KnowledgeBase kb) {
        return new KbDto.VO(
                kb.getId(), kb.getName(), kb.getDescription(), kb.getCoverColor(),
                kb.getEmbeddingModel(), kb.getMilvusCollection(),
                kb.getChunkSize(), kb.getChunkOverlap(),
                kb.getDocCount(), kb.getChunkCount(), kb.getQuestionCount(),
                kb.getStatus(), kb.getCreatedAt(), kb.getUpdatedAt()
        );
    }

    private static final String[] COLORS = {
            "#4C7CF3", "#10B981", "#F59E0B", "#EF4444", "#8B5CF6", "#06B6D4", "#EC4899"
    };

    private String randomColor() {
        return COLORS[(int) (Math.random() * COLORS.length)];
    }
}
