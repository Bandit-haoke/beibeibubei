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
 * 把「Java 的简历解析任务」和「Python 的简历解析流水线」接起来。
 *
 * <p>与 IngestRunner / GradingRunner 同一套路：
 * Java 建任务 → 调 Python 的 SSE 接口 → 逐条推进度 → Java 收尾。
 *
 * <p>为什么简历解析要异步：扫描件 PDF 会走 OCR，一份简历几十秒到几分钟很正常，
 * 不能把浏览器挂在 HTTP 请求上等。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class InterviewRunner {

    private final AgentStreamClient agentStream;
    private final AsyncTaskService taskService;
    private final ObjectMapper objectMapper;

    @Async("beibeiExecutor")
    public void runParse(long taskId, long resumeId, String textContent) {
        log.info("开始简历解析任务 #{} resume={}", taskId, resumeId);
        taskService.running(taskId, "正在读取简历文件");

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("taskId", taskId);
        payload.put("resumeId", resumeId);
        if (textContent != null && !textContent.isBlank()) {
            payload.put("textContent", textContent);
        }

        try {
            agentStream.postStream("/api/v1/resume-parse", payload,
                    event -> handleEvent(taskId, resumeId, event));
            log.info("简历解析任务 #{} 的 SSE 流已结束", taskId);
        } catch (Exception e) {
            log.error("简历解析任务 #{} 失败", taskId, e);
            taskService.fail(taskId, friendly(e));
        }
    }

    private void handleEvent(long taskId, long resumeId, AgentStreamClient.SseEvent event) {
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
                    summary.put("resumeId", resumeId);
                    for (String key : List.of("charCount", "skillCount", "projectCount",
                            "riskCount", "tokens", "latencyMs")) {
                        summary.put(key, node.path(key).asInt(0));
                    }
                    summary.put("model", node.path("model").asText(""));
                    taskService.success(taskId, summary);
                    log.info("简历解析完成 resume={} {}", resumeId, summary);
                }
                case "error" -> taskService.fail(taskId, read(data).path("errorMsg").asText("未知错误"));
                default -> log.debug("忽略未知 SSE 事件: {} -> {}", event.event(), data);
            }
        } catch (Exception e) {
            log.warn("处理简历解析 SSE 事件失败 event={} data={}", event.event(), data, e);
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
