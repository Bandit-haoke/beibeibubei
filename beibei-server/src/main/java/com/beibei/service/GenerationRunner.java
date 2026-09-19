package com.beibei.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Async;
import org.springframework.stereotype.Service;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 把「Java 的出题任务」和「Python 的出题流水线」接起来。
 *
 * <p>与 {@link IngestRunner} 同一个套路：Java 建任务 → 调 Python 的 SSE 接口
 * → 逐条把进度写回 bb_async_task 并推给浏览器 → Python 直接写题目表 →
 * Java 收尾更新题卷状态。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class GenerationRunner {

    private final AgentStreamClient agentStream;
    private final AsyncTaskService taskService;
    private final PaperStatusService paperStatusService;
    private final ObjectMapper objectMapper;

    @Async("beibeiExecutor")
    public void runGenerate(long taskId, long paperId, long kbId,
                            int count, List<Long> tagIds, boolean includeChildTags,
                            Map<String, Double> qTypeRatio, Map<String, Double> difficultyRatio,
                            boolean selfCheck, String collection, String partition) {

        log.info("开始出题任务 #{} paper={} 题量={}", taskId, paperId, count);
        taskService.running(taskId, "正在准备命题材料");

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("taskId", taskId);
        payload.put("paperId", paperId);
        payload.put("kbId", kbId);
        payload.put("count", count);
        payload.put("tagIds", tagIds == null ? List.of() : tagIds);
        payload.put("includeChildTags", includeChildTags);
        payload.put("qTypeRatio", qTypeRatio);
        payload.put("difficultyRatio", difficultyRatio);
        payload.put("selfCheck", selfCheck);
        payload.put("collection", collection);
        payload.put("partition", partition);

        try {
            agentStream.postStream("/api/v1/generate-questions", payload,
                    event -> handleEvent(taskId, paperId, event));
            log.info("出题任务 #{} 的 SSE 流已结束", taskId);

        } catch (Exception e) {
            log.error("出题任务 #{} 失败", taskId, e);
            String msg = friendly(e);
            taskService.fail(taskId, msg);
            paperStatusService.markFailed(paperId, msg);
        }
    }

    private void handleEvent(long taskId, long paperId, AgentStreamClient.SseEvent event) {
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
                    Map<String, Object> summary = new LinkedHashMap<>();
                    summary.put("paperId", paperId);
                    for (String key : List.of("requested", "generated", "droppedByValidate",
                            "droppedBySelfCheck", "droppedByDedup", "saved")) {
                        summary.put(key, node.path(key).asInt(0));
                    }
                    summary.put("batchId", node.path("batchId").asText(""));

                    paperStatusService.markGenerated(paperId, summary);
                    taskService.success(taskId, summary);

                    log.info("出题完成 paper={} 生成={} 保存={} 丢弃(校验/自检/查重)={}/{}/{}",
                            paperId, summary.get("generated"), summary.get("saved"),
                            summary.get("droppedByValidate"), summary.get("droppedBySelfCheck"),
                            summary.get("droppedByDedup"));
                }
                case "error" -> {
                    JsonNode node = read(data);
                    String msg = node.path("errorMsg").asText(node.path("error").asText("未知错误"));
                    String hint = node.path("hint").asText("");
                    taskService.fail(taskId, msg);
                    paperStatusService.markFailed(paperId, msg);
                    if (!hint.isBlank()) {
                        log.warn("出题失败提示：{}", hint);
                    }
                }
                default -> log.debug("忽略未知 SSE 事件: {} -> {}", event.event(), data);
            }
        } catch (Exception e) {
            log.warn("处理出题 SSE 事件失败 event={} data={}", event.event(), data, e);
        }
    }

    private JsonNode read(String data) throws Exception {
        return objectMapper.readTree(data);
    }

    private String friendly(Exception e) {
        String msg = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
        if (msg.contains("Connection refused") || msg.contains("ConnectException")) {
            return "智能体未启动，请先在 PyCharm 中运行 beibei-agent";
        }
        return msg;
    }
}
