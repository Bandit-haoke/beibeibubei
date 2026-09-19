package com.beibei.controller;

import com.beibei.common.Result;
import com.beibei.config.EmbeddingProperties;
import com.beibei.entity.KnowledgeBase;
import com.beibei.service.AgentClient;
import com.beibei.service.KnowledgeBaseService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 检索接口：Java 转发到 Python 的混合检索。
 *
 * <p>Java 这一层负责把 kbId 翻译成 Milvus 的 collection / partition，
 * 前端不需要知道向量库的内部结构。
 */
@Slf4j
@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
@Tag(name = "检索", description = "混合检索（稠密向量 + BM25 + RRF）")
public class SearchController {

    private final AgentClient agentClient;
    private final KnowledgeBaseService kbService;
    private final EmbeddingProperties embedding;

    public record SearchRequest(
            Long kbId,
            String query,
            Integer topK,
            List<Long> tagIds,
            List<Long> docIds,
            Boolean enrich
    ) {
    }

    @PostMapping("/search")
    @Operation(summary = "混合检索")
    public Result<Map<String, Object>> search(@RequestBody SearchRequest req) {
        if (req.kbId() == null) {
            return Result.fail(Result.BAD_REQUEST, "缺少 kbId");
        }
        if (req.query() == null || req.query().isBlank()) {
            return Result.fail(Result.BAD_REQUEST, "查询内容不能为空");
        }

        KnowledgeBase kb = kbService.require(req.kbId());

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("kbId", req.kbId());
        payload.put("query", req.query().trim());
        payload.put("topK", req.topK() == null ? 8 : req.topK());
        payload.put("tagIds", req.tagIds());
        payload.put("docIds", req.docIds());
        payload.put("enrich", req.enrich() == null || req.enrich());
        payload.put("collection", kb.getMilvusCollection());
        payload.put("partition", embedding.partitionOf(req.kbId()));

        return Result.ok(agentClient.search(payload));
    }
}
