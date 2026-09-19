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
 * 把「Java 的判分任务」和「Python 的判分流水线」接起来。
 *
 * <p>与 IngestRunner / GenerationRunner 同一套路：
 * Java 建任务 → 调 Python 的 SSE 接口 → 逐条推进度 → Python 直接写判分明细
 * → Java 收尾刷新答卷状态。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class GradingRunner {

    private final AgentStreamClient agentStream;
    private final AsyncTaskService taskService;
    private final ObjectMapper objectMapper;

    /** 交卷判分（整卷） */
    @Async("beibeiExecutor")
    public void runGrade(long taskId, long examId) {
        log.info("开始判分任务 #{} exam={}", taskId, examId);
        taskService.running(taskId, "正在读取答卷");

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("taskId", taskId);
        payload.put("examId", examId);

        try {
            agentStream.postStream("/api/v1/grade", payload,
                    event -> handleEvent(taskId, examId, event, false, 0L));
            log.info("判分任务 #{} 的 SSE 流已结束", taskId);
        } catch (Exception e) {
            log.error("判分任务 #{} 失败", taskId, e);
            taskService.fail(taskId, friendly(e));
        }
    }

    /** 申诉重判（单题） */
    @Async("beibeiExecutor")
    public void runAppeal(long taskId, long examId, long answerItemId, String reason) {
        log.info("开始申诉重判任务 #{} answerItem={}", taskId, answerItemId);
        taskService.running(taskId, "正在重新批阅");

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("taskId", taskId);
        payload.put("examId", examId);
        payload.put("answerItemId", answerItemId);
        payload.put("appealReason", reason);

        try {
            agentStream.postStream("/api/v1/appeal-regrade", payload,
                    event -> handleEvent(taskId, examId, event, true, answerItemId));
            log.info("申诉重判任务 #{} 的 SSE 流已结束", taskId);
        } catch (Exception e) {
            log.error("申诉重判任务 #{} 失败", taskId, e);
            taskService.fail(taskId, friendly(e));
        }
    }

    private void handleEvent(long taskId, long examId, AgentStreamClient.SseEvent event,
                             boolean appeal, long answerItemId) {
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
                    summary.put("examId", examId);
                    if (appeal) {
                        summary.put("appealAnswerItemId", answerItemId);
                        summary.put("score", node.path("score").asDouble(0));
                        summary.put("fullScore", node.path("fullScore").asDouble(0));
                    } else {
                        for (String key : List.of("totalScore", "gotScore", "correctCount",
                                "wrongCount", "mistakeCount")) {
                            summary.put(key, node.path(key).asInt(0));
                        }
                        summary.put("gotScore", node.path("gotScore").asDouble(0));
                        summary.put("scoreRate", node.path("scoreRate").asDouble(0));
                    }
                    taskService.success(taskId, summary);
                    log.info("判分完成 exam={} {}", examId,
                            appeal ? "（申诉单题）" : summary.toString());
                }
                case "error" -> {
                    JsonNode node = read(data);
                    String msg = node.path("errorMsg").asText("未知错误");
                    taskService.fail(taskId, msg);
                }
                default -> log.debug("忽略未知 SSE 事件: {} -> {}", event.event(), data);
            }
        } catch (Exception e) {
            log.warn("处理判分 SSE 事件失败 event={} data={}", event.event(), data, e);
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
