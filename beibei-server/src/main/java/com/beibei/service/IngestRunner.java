package com.beibei.service;

import com.beibei.entity.AsyncTask;
import com.beibei.entity.Document;
import com.beibei.mapper.DocumentMapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 把「Java 的异步任务」和「Python 的解析流水线」接起来。
 *
 * <p>Java 落盘 + 建任务 → 调 Python 的 SSE 接口 → 逐条把进度写回
 * {@code bb_async_task} 并推给浏览器 → Python 直接写业务表（分块/标签/向量），
 * Java 再把文档状态改成 READY 并刷新知识库计数。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class IngestRunner {

    private final AgentStreamClient agentStream;
    private final AsyncTaskService taskService;
    private final DocumentMapper documentMapper;
    private final KnowledgeBaseService kbService;
    private final ObjectMapper objectMapper;

    // ------------------------------------------------------------------
    //  对外入口
    // ------------------------------------------------------------------

    /** 按文件路径入库（上传 / 重新解析走这里） */
    @Async("beibeiExecutor")
    public void runIngest(long taskId, long kbId, long docId, String absolutePath,
                          String fileName, String fileType, int sourceType,
                          String collection, String partition,
                          int chunkSize, int chunkOverlap) {

        Map<String, Object> payload = basePayload(taskId, kbId, docId, fileName,
                collection, partition, chunkSize, chunkOverlap);
        payload.put("filePath", absolutePath);
        payload.put("fileType", fileType);
        payload.put("sourceType", sourceType);

        execute(taskId, docId, kbId, fileName, payload);
    }

    /** 按文本内容入库（手动粘贴走这里，没有落盘文件） */
    @Async("beibeiExecutor")
    public void runIngestText(long taskId, long kbId, long docId, String fileName, String textContent,
                              String collection, String partition,
                              int chunkSize, int chunkOverlap) {

        Map<String, Object> payload = basePayload(taskId, kbId, docId, fileName,
                collection, partition, chunkSize, chunkOverlap);
        payload.put("textContent", textContent);
        payload.put("fileType", "txt");
        payload.put("sourceType", Document.SOURCE_PASTE);

        execute(taskId, docId, kbId, fileName, payload);
    }

    // ------------------------------------------------------------------
    //  内部实现
    // ------------------------------------------------------------------

    private Map<String, Object> basePayload(long taskId, long kbId, long docId, String fileName,
                                            String collection, String partition,
                                            int chunkSize, int chunkOverlap) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("taskId", taskId);
        payload.put("kbId", kbId);
        payload.put("docId", docId);
        payload.put("fileName", fileName);
        payload.put("collection", collection);
        payload.put("partition", partition);
        payload.put("chunkSize", chunkSize);
        payload.put("chunkOverlap", chunkOverlap);
        return payload;
    }

    private void execute(long taskId, long docId, long kbId, String fileName, Map<String, Object> payload) {
        log.info("开始入库任务 #{} docId={} file={}", taskId, docId, fileName);
        taskService.running(taskId, "正在解析文档 " + fileName);
        markDocument(docId, Document.STATUS_PARSING, null);

        try {
            agentStream.postStream("/api/v1/ingest", payload,
                    event -> handleEvent(taskId, docId, kbId, event));
            log.info("入库任务 #{} 的 SSE 流已结束", taskId);

        } catch (Exception e) {
            log.error("入库任务 #{} 失败", taskId, e);
            String msg = friendly(e);
            taskService.fail(taskId, msg);
            markDocument(docId, Document.STATUS_FAILED, msg);
        }
    }

    private void handleEvent(long taskId, long docId, long kbId, AgentStreamClient.SseEvent event) {
        String data = event.data();
        try {
            switch (event.event()) {
                case "progress" -> {
                    JsonNode node = read(data);
                    taskService.progress(taskId, node.path("progress").asInt(0),
                            node.path("stage").asText(""));
                }
                case "done" -> {
                    JsonNode node = read(data);
                    int chunkCount = node.path("chunkCount").asInt(0);
                    int charCount = node.path("charCount").asInt(0);
                    int pageCount = node.path("pageCount").asInt(0);
                    int tagCount = node.path("tagCount").asInt(0);

                    Document patch = new Document();
                    patch.setId(docId);
                    patch.setStatus(Document.STATUS_READY);
                    patch.setChunkCount(chunkCount);
                    patch.setCharCount(charCount);
                    patch.setPageCount(pageCount);
                    patch.setErrorMsg("");
                    documentMapper.updateById(patch);

                    Map<String, Object> result = new LinkedHashMap<>();
                    result.put("docId", docId);
                    result.put("kbId", kbId);
                    result.put("chunkCount", chunkCount);
                    result.put("charCount", charCount);
                    result.put("pageCount", pageCount);
                    result.put("tagCount", tagCount);
                    result.put("degraded", node.path("degraded").asBoolean(false));
                    taskService.success(taskId, result);

                    // ⚠️ 这一行以前是漏的（类注释里写了「并刷新知识库计数」，代码却没做）。
                    // 后果：文档解析成功、分块也写进去了，但 bb_knowledge_base.chunk_count
                    // 一直是 0；而「AI 出题」页正好用这个字段做前置校验，
                    // 于是报「这个知识库还没有解析好的资料，先去上传文档」——
                    // 明明有 33 个分块却说出不了题。
                    refreshKbCounters(kbId);

                    log.info("入库完成 docId={} 分块={} 知识点={}", docId, chunkCount, tagCount);
                }
                case "error" -> {
                    JsonNode node = read(data);
                    String msg = node.path("errorMsg").asText(node.path("error").asText("未知错误"));
                    taskService.fail(taskId, msg);
                    markDocument(docId, Document.STATUS_FAILED, msg);
                    // 失败也要刷新：这次可能已经写入了一部分分块，计数不能停在旧值上
                    refreshKbCounters(kbId);
                }
                default -> log.debug("忽略未知 SSE 事件: {} -> {}", event.event(), data);
            }
        } catch (Exception e) {
            log.warn("处理 SSE 事件失败 event={} data={}", event.event(), data, e);
        }
    }

    private JsonNode read(String data) throws Exception {
        return objectMapper.readTree(data);
    }

    /**
     * 重算知识库的冗余计数（文档数 / 分块数）。
     *
     * <p>这些计数是**冗余字段**，只为了让列表页和出题页少查几次库。
     * 冗余就有漂移风险，所以每次入库结束（无论成功失败）都要重算。
     * 这里刻意吞掉异常：计数不准只是显示问题，不该把入库任务判成失败。
     */
    private void refreshKbCounters(long kbId) {
        try {
            kbService.refreshCounters(kbId);
        } catch (Exception e) {
            log.warn("刷新知识库 #{} 计数失败（不影响入库结果）：{}", kbId, e.getMessage());
        }
    }

    private void markDocument(long docId, int status, String errorMsg) {
        Document patch = new Document();
        patch.setId(docId);
        patch.setStatus(status);
        if (errorMsg != null) {
            patch.setErrorMsg(errorMsg.length() > 990 ? errorMsg.substring(0, 990) : errorMsg);
        }
        documentMapper.updateById(patch);
    }

    private String friendly(Exception e) {
        String msg = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
        if (msg.contains("Connection refused") || msg.contains("ConnectException")
                || msg.contains("Connection reset")) {
            return "智能体未启动，请先在 PyCharm 中运行 beibei-agent";
        }
        return msg;
    }
}
