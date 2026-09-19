package com.beibei.controller;

import com.beibei.common.Result;
import com.beibei.dto.TagDto;
import com.beibei.entity.Tag;
import com.beibei.service.AgentStreamClient;
import com.beibei.service.TagService;
import io.swagger.v3.oas.annotations.Operation;
import jakarta.validation.Valid;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.Executor;

/**
 * 知识点接口。
 */
@Slf4j
@RestController
@RequestMapping("/api/tag")
@io.swagger.v3.oas.annotations.tags.Tag(name = "知识点", description = "知识点树的查询、人工维护与 AI 重新抽取")
public class TagController {

    private final TagService tagService;
    private final AgentStreamClient agentStream;
    private final Executor executor;

    public TagController(TagService tagService,
                         AgentStreamClient agentStream,
                         @Qualifier("beibeiExecutor") Executor executor) {
        this.tagService = tagService;
        this.agentStream = agentStream;
        this.executor = executor;
    }

    @GetMapping("/tree")
    @Operation(summary = "知识点树")
    public Result<List<TagDto.NodeVO>> tree(@RequestParam Long kbId) {
        return Result.ok(tagService.tree(kbId));
    }

    @PostMapping
    @Operation(summary = "新增知识点")
    public Result<Long> create(@Valid @RequestBody TagDto.SaveReq req) {
        Tag tag = tagService.create(req);
        return Result.ok(tag.getId());
    }

    @PutMapping("/{id}")
    @Operation(summary = "修改知识点")
    public Result<Void> update(@PathVariable Long id, @RequestBody TagDto.SaveReq req) {
        tagService.update(id, req);
        return Result.ok();
    }

    @DeleteMapping("/{id}")
    @Operation(summary = "删除知识点（连带子孙与关联关系）")
    public Result<Void> delete(@PathVariable Long id) {
        tagService.delete(id);
        return Result.ok();
    }

    @PostMapping("/refresh")
    @Operation(summary = "重算每个知识点关联的分块数")
    public Result<Void> refresh(@RequestParam Long kbId) {
        tagService.refreshChunkCounts(kbId);
        return Result.ok();
    }

    /**
     * 让 AI 重新抽取知识点树，SSE 推进度。
     *
     * <p>用 GET + EventSource 而不是 POST：浏览器原生的 EventSource 不支持请求体，
     * 这种「只传几个查询参数」的场景用 GET 最省事。
     *
     * <p>Java 在这里只是转发层 —— 真正的 SSE 流来自 Python 的
     * {@code POST /api/v1/tags/extract}。
     */
    @GetMapping(value = "/ai-extract/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    @Operation(summary = "AI 重新抽取知识点树（SSE）")
    public SseEmitter aiExtractStream(@RequestParam Long kbId,
                                      @RequestParam(defaultValue = "false") boolean force) {
        SseEmitter emitter = new SseEmitter(30 * 60 * 1000L);

        emitter.onTimeout(emitter::complete);
        emitter.onError(e -> log.debug("知识点抽取 SSE 连接异常: {}", e.getMessage()));

        executor.execute(() -> {
            Map<String, Object> payload = new LinkedHashMap<>();
            payload.put("taskId", 0);
            payload.put("kbId", kbId);
            payload.put("force", force);

            try {
                agentStream.postStream("/api/v1/tags/extract", payload, event -> {
                    try {
                        emitter.send(SseEmitter.event().name(event.event()).data(event.data()));
                    } catch (IOException e) {
                        // 浏览器已断开，用运行时异常中断流读取
                        throw new UncheckedIOException(e);
                    }
                });
                emitter.complete();
            } catch (Exception e) {
                log.warn("AI 抽取知识点失败: {}", e.getMessage());
                try {
                    Map<String, Object> err = new LinkedHashMap<>();
                    err.put("kbId", kbId);
                    err.put("errorMsg", friendly(e));
                    emitter.send(SseEmitter.event().name("error").data(err));
                } catch (Exception ignored) {
                    // 连接已断
                }
                emitter.complete();
            }
        });

        return emitter;
    }

    private String friendly(Exception e) {
        String msg = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
        if (msg.contains("Connection refused") || msg.contains("ConnectException")) {
            return "智能体未启动，请先在 PyCharm 中运行 beibei-agent";
        }
        return msg;
    }
}
