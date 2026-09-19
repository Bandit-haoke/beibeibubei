package com.beibei.service;

import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.beibei.common.BusinessException;
import com.beibei.common.PageResult;
import com.beibei.config.EmbeddingProperties;
import com.beibei.dto.DocDto;
import com.beibei.entity.AsyncTask;
import com.beibei.entity.DocChunk;
import com.beibei.entity.Document;
import com.beibei.entity.KnowledgeBase;
import com.beibei.mapper.DocChunkMapper;
import com.beibei.mapper.DocumentMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 文档业务：上传落盘 → 建异步任务 → 交给 {@link IngestRunner} 调 Python 解析入库。
 *
 * <p>注意：上传流程刻意**不加 {@code @Transactional}**。
 * 因为 {@code runIngest} 是异步的，如果包在事务里，Python 可能在事务提交前
 * 就按 docId 去查文档，查不到。让每次 insert 各自提交，顺序就确定了。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DocumentService {

    /** 手动粘贴的文档用这个当扩展名之外的类型标记 */
    private static final String TYPE_TEXT = "txt";

    private final DocumentMapper documentMapper;
    private final DocChunkMapper chunkMapper;
    private final KnowledgeBaseService kbService;
    private final TagService tagService;
    private final FileStorageService storage;
    private final AsyncTaskService taskService;
    private final IngestRunner ingestRunner;
    private final EmbeddingProperties embedding;
    private final AgentClient agentClient;

    /** 单个文件的上传结果 */
    public record UploadResult(Long docId, Long taskId, String fileName, boolean duplicated, String message) {
    }

    // ------------------------------------------------------------------
    //  上传
    // ------------------------------------------------------------------

    /**
     * 批量上传并触发解析。
     *
     * @param sourceType {@link Document#SOURCE_FILE} 或 {@link Document#SOURCE_IMAGE}
     */
    public List<UploadResult> upload(Long kbId, MultipartFile[] files, int sourceType) {
        KnowledgeBase kb = kbService.require(kbId);
        if (files == null || files.length == 0) {
            throw BusinessException.invalid("没有选择文件");
        }

        List<UploadResult> results = new ArrayList<>(files.length);
        for (MultipartFile file : files) {
            String originalName = file.getOriginalFilename() == null ? "unnamed" : file.getOriginalFilename();
            try {
                FileStorageService.StoredFile stored = storage.store(kbId, file);

                // 同一知识库内按 SHA-256 去重
                Document existing = documentMapper.selectOne(
                        Wrappers.<Document>lambdaQuery()
                                .eq(Document::getKbId, kbId)
                                .eq(Document::getFileHash, stored.sha256())
                                .last("limit 1"));
                if (existing != null) {
                    storage.delete(stored.relativePath());   // 刚落的盘没必要留
                    log.info("文档已存在，跳过：{}（命中 #{}）", originalName, existing.getId());
                    results.add(new UploadResult(existing.getId(), null, originalName, true,
                            "内容与已有文档「" + existing.getFileName() + "」完全相同，已跳过"));
                    continue;
                }

                Document doc = new Document();
                doc.setKbId(kbId);
                doc.setUserId(1L);
                doc.setFileName(originalName);
                doc.setFilePath(stored.relativePath());
                doc.setFileType(stored.ext());
                doc.setFileSize(stored.size());
                doc.setFileHash(stored.sha256());
                doc.setSourceType(sourceType);
                doc.setStatus(Document.STATUS_PENDING);
                doc.setChunkCount(0);
                doc.setPageCount(0);
                doc.setCharCount(0);
                doc.setErrorMsg("");
                documentMapper.insert(doc);

                Long taskId = startIngest(kb, doc, stored.absolutePath());
                results.add(new UploadResult(doc.getId(), taskId, originalName, false, "已加入解析队列"));

            } catch (BusinessException e) {
                log.warn("上传 {} 被拒绝: {}", originalName, e.getMessage());
                results.add(new UploadResult(null, null, originalName, false, e.getMessage()));
            } catch (Exception e) {
                log.error("上传 {} 失败", originalName, e);
                results.add(new UploadResult(null, null, originalName, false, "上传失败：" + e.getMessage()));
            }
        }

        return results;
    }

    /** 手动粘贴文本入库 */
    public UploadResult paste(DocDto.PasteReq req) {
        if (req.content() == null || req.content().isBlank()) {
            throw BusinessException.invalid("粘贴内容不能为空");
        }
        KnowledgeBase kb = kbService.require(req.kbId());

        String title = (req.title() == null || req.title().isBlank())
                ? "手动录入 " + java.time.LocalDateTime.now().toLocalDate()
                : req.title().trim();

        Document doc = new Document();
        doc.setKbId(req.kbId());
        doc.setUserId(1L);
        doc.setFileName(title + ".txt");
        doc.setFilePath("");                            // 粘贴内容没有落盘文件
        doc.setFileType(TYPE_TEXT);
        doc.setFileSize((long) req.content().getBytes(java.nio.charset.StandardCharsets.UTF_8).length);
        doc.setFileHash(sha256(req.content()));
        doc.setSourceType(Document.SOURCE_PASTE);
        doc.setStatus(Document.STATUS_PENDING);
        doc.setChunkCount(0);
        doc.setPageCount(0);
        doc.setCharCount(0);
        doc.setErrorMsg("");
        documentMapper.insert(doc);

        Long taskId = startIngest(kb, doc, req.content());
        return new UploadResult(doc.getId(), taskId, doc.getFileName(), false, "已加入解析队列");
    }

    /** 建任务 + 起异步解析。textContent 非空表示直接给文本（粘贴场景）。 */
    private Long startIngest(KnowledgeBase kb, Document doc, String pathOrContent) {
        AsyncTask task = taskService.create(AsyncTask.TYPE_INGEST, doc.getId(), 1L);

        if (doc.getSourceType() != null && doc.getSourceType() == Document.SOURCE_PASTE) {
            ingestRunner.runIngestText(task.getId(), kb.getId(), doc.getId(),
                    doc.getFileName(), pathOrContent,
                    kb.getMilvusCollection(), embedding.partitionOf(kb.getId()),
                    kb.getChunkSize(), kb.getChunkOverlap());
        } else {
            ingestRunner.runIngest(task.getId(), kb.getId(), doc.getId(),
                    pathOrContent, doc.getFileName(), doc.getFileType(),
                    doc.getSourceType() == null ? Document.SOURCE_FILE : doc.getSourceType(),
                    kb.getMilvusCollection(), embedding.partitionOf(kb.getId()),
                    kb.getChunkSize(), kb.getChunkOverlap());
        }
        return task.getId();
    }

    // ------------------------------------------------------------------
    //  查询
    // ------------------------------------------------------------------

    public PageResult<DocDto.VO> list(Long kbId, Integer status, String keyword, long pageNum, long pageSize) {
        var query = Wrappers.<Document>lambdaQuery()
                .eq(kbId != null, Document::getKbId, kbId)
                .eq(status != null, Document::getStatus, status)
                .orderByDesc(Document::getCreatedAt);
        if (keyword != null && !keyword.isBlank()) {
            query.like(Document::getFileName, keyword.trim());
        }
        IPage<Document> page = documentMapper.selectPage(new Page<>(pageNum, pageSize), query);
        return PageResult.of(page, this::toVO);
    }

    public Document require(Long id) {
        Document doc = documentMapper.selectById(id);
        if (doc == null) {
            throw BusinessException.notFound("文档", id);
        }
        return doc;
    }

    public DocDto.DetailVO detail(Long id, int chunkLimit) {
        Document doc = require(id);
        List<DocDto.ChunkVO> chunks = chunkList(id, 1, chunkLimit);

        List<DocDto.TagBrief> tags = new ArrayList<>();
        for (com.beibei.dto.TagDto.NodeVO node : tagService.tree(doc.getKbId())) {
            collectTags(node, tags);
        }
        return new DocDto.DetailVO(toVO(doc), chunks, tags);
    }

    /** 把知识点树拍平成列表（文档详情页要展示该知识库的全部知识点） */
    private void collectTags(com.beibei.dto.TagDto.NodeVO node, List<DocDto.TagBrief> out) {
        out.add(new DocDto.TagBrief(node.id(), node.name(), node.level()));
        if (node.children() != null) {
            for (com.beibei.dto.TagDto.NodeVO child : node.children()) {
                collectTags(child, out);
            }
        }
    }

    public List<DocDto.ChunkVO> chunkList(Long docId, long pageNum, long pageSize) {
        IPage<DocChunk> page = chunkMapper.selectPage(
                new Page<>(pageNum, pageSize),
                Wrappers.<DocChunk>lambdaQuery()
                        .eq(DocChunk::getDocId, docId)
                        .orderByAsc(DocChunk::getChunkIndex));

        List<Long> chunkIds = page.getRecords().stream().map(DocChunk::getId).toList();
        Map<Long, List<DocDto.TagBrief>> tagMap = tagService.tagBriefsByChunk(chunkIds);

        return page.getRecords().stream()
                .map(c -> new DocDto.ChunkVO(
                        c.getId(), c.getChunkIndex(), c.getContent(), c.getTokenCount(),
                        c.getPageNo(), c.getSectionPath(), c.getMilvusPk(),
                        tagMap.getOrDefault(c.getId(), List.of())))
                .toList();
    }

    public PageResult<DocDto.ChunkVO> chunkPage(Long docId, long pageNum, long pageSize) {
        IPage<DocChunk> page = chunkMapper.selectPage(
                new Page<>(pageNum, pageSize),
                Wrappers.<DocChunk>lambdaQuery()
                        .eq(DocChunk::getDocId, docId)
                        .orderByAsc(DocChunk::getChunkIndex));

        List<Long> chunkIds = page.getRecords().stream().map(DocChunk::getId).toList();
        Map<Long, List<DocDto.TagBrief>> tagMap = tagService.tagBriefsByChunk(chunkIds);

        return PageResult.of(page, c -> new DocDto.ChunkVO(
                c.getId(), c.getChunkIndex(), c.getContent(), c.getTokenCount(),
                c.getPageNo(), c.getSectionPath(), c.getMilvusPk(),
                tagMap.getOrDefault(c.getId(), List.of())));
    }

    // ------------------------------------------------------------------
    //  删除 / 重建
    // ------------------------------------------------------------------

    /**
     * 删除文档及其分块与向量。
     *
     * <p>顺序：先删 MySQL 分块 → 再删文档行 → 最后删 Milvus 向量。
     * 向量删除失败只记日志，靠 {@code /api/sys/consistency-check} 兜底清理，
     * 不会因为向量库抽风导致业务数据删不掉。
     */
    public void delete(Long id) {
        Document doc = require(id);
        KnowledgeBase kb = kbService.require(doc.getKbId());

        int chunks = chunkMapper.delete(Wrappers.<DocChunk>lambdaQuery().eq(DocChunk::getDocId, id));
        if (doc.getFilePath() != null && !doc.getFilePath().isBlank()) {
            storage.delete(doc.getFilePath());
        }
        documentMapper.deleteById(id);

        try {
            Map<String, Object> resp = agentClient.deleteVectors(
                    kb.getMilvusCollection(), embedding.partitionOf(kb.getId()), id);
            if (Boolean.FALSE.equals(resp.get("ok"))) {
                log.warn("删除向量返回异常: {}", resp.get("error"));
            }
        } catch (Exception e) {
            log.warn("删除 Milvus 向量失败（文档 #{}）: {}", id, e.getMessage());
        }

        kbService.refreshCounters(doc.getKbId());
        log.info("删除文档 #{}，清理 {} 个分块", id, chunks);
    }

    /** 重新解析入库：先清掉旧分块与向量，再跑一遍完整流程 */
    public Long reindex(Long id) {
        Document doc = require(id);
        KnowledgeBase kb = kbService.require(doc.getKbId());

        if (doc.getSourceType() != null && doc.getSourceType() == Document.SOURCE_PASTE) {
            throw BusinessException.invalid("手动粘贴的文档不支持重新解析，请删除后重新粘贴");
        }
        if (doc.getFilePath() == null || doc.getFilePath().isBlank()) {
            throw BusinessException.invalid("找不到原始文件，无法重新解析");
        }

        chunkMapper.delete(Wrappers.<DocChunk>lambdaQuery().eq(DocChunk::getDocId, id));
        try {
            agentClient.deleteVectors(kb.getMilvusCollection(), embedding.partitionOf(kb.getId()), id);
        } catch (Exception e) {
            log.warn("重建前清理向量失败: {}", e.getMessage());
        }

        Document patch = new Document();
        patch.setId(id);
        patch.setStatus(Document.STATUS_PENDING);
        patch.setChunkCount(0);
        patch.setErrorMsg("");
        documentMapper.updateById(patch);

        return startIngest(kb, doc, storage.resolve(doc.getFilePath()).toString());
    }

    // ------------------------------------------------------------------

    public DocDto.VO toVO(Document d) {
        return new DocDto.VO(
                d.getId(), d.getKbId(), d.getFileName(), d.getFileType(), d.getFileSize(),
                d.getSourceType(), d.getStatus(), d.getChunkCount(), d.getPageCount(),
                d.getCharCount(), d.getErrorMsg(), d.getCreatedAt()
        );
    }

    private static String sha256(String text) {
        try {
            java.security.MessageDigest md = java.security.MessageDigest.getInstance("SHA-256");
            return java.util.HexFormat.of().formatHex(
                    md.digest(text.getBytes(java.nio.charset.StandardCharsets.UTF_8)));
        } catch (Exception e) {
            return java.util.UUID.randomUUID().toString();
        }
    }
}
