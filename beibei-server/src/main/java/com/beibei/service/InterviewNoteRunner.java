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
 * 把「Java 的面经任务」和「Python 的面经流水线」接起来。
 *
 * <p>与 IngestRunner / InterviewRunner 同一套路：Java 建任务 → 调 Python 的 SSE 接口
 * → 逐条推进度 → Java 收尾。面经的正文与逐句对话由 Python 直接写库
 * （和出题、简历解析一致），Java 这里只管任务状态。
 *
 * <p>为什么这条流水线特别慢：等讯飞语音转写本身就是分钟级，之后还有
 * 角色判定、口语清洗、面经生成三次大模型调用，所以它用了一个独立的、
 * 长达两小时的 SSE 超时（见 {@link #STREAM_TIMEOUT_SECONDS}）。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class InterviewNoteRunner {

    /**
     * 面经流水线的超时：2 小时。
     *
     * <p>全局默认是 120 秒，对单次大模型调用够用，但对「整场面试录音」远远不够 ——
     * 一段 40 分钟的录音，讯飞转写就可能要十几分钟。超时被掐断的话，
     * 用户会看到"任务失败"，而讯飞那边其实还在正常跑，非常难排查。
     */
    private static final int STREAM_TIMEOUT_SECONDS = 2 * 60 * 60;

    private final AgentStreamClient agentStream;
    private final AsyncTaskService taskService;
    private final ObjectMapper objectMapper;

    @Async("beibeiExecutor")
    public void runGenerate(long taskId, long noteId, String filePath, String fileName,
                            String company, String position) {
        log.info("开始面经任务 #{} note={} file={}", taskId, noteId, fileName);
        taskService.running(taskId, "正在准备音频文件");

        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("taskId", taskId);
        payload.put("noteId", noteId);
        payload.put("filePath", filePath == null ? "" : filePath);
        payload.put("fileName", fileName == null ? "" : fileName);
        payload.put("company", company == null ? "" : company);
        payload.put("position", position == null ? "" : position);

        try {
            agentStream.postStream("/api/v1/interview-note/generate", payload,
                    event -> handleEvent(taskId, noteId, event), STREAM_TIMEOUT_SECONDS);
            log.info("面经任务 #{} 的 SSE 流已结束", taskId);
        } catch (Exception e) {
            log.error("面经任务 #{} 失败", taskId, e);
            taskService.fail(taskId, friendly(e));
        }
    }

    private void handleEvent(long taskId, long noteId, AgentStreamClient.SseEvent event) {
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
                    summary.put("noteId", noteId);
                    for (String key : List.of("turnCount", "questionCount", "durationMs")) {
                        summary.put(key, node.path(key).asInt(0));
                    }
                    summary.put("title", node.path("title").asText(""));
                    summary.put("engine", node.path("engine").asText(""));
                    summary.put("roleSource", node.path("roleSource").asText(""));
                    summary.put("degraded", node.path("degraded").asBoolean(false));
                    summary.put("degradeReason", node.path("degradeReason").asText(""));
                    taskService.success(taskId, summary);
                    log.info("面经任务完成 note={} {}", noteId, summary);
                }
                case "error" -> taskService.fail(taskId, read(data).path("errorMsg").asText("未知错误"));
                default -> log.debug("忽略未知 SSE 事件: {} -> {}", event.event(), data);
            }
        } catch (Exception e) {
            log.warn("处理面经 SSE 事件失败 event={} data={}", event.event(), data, e);
        }
    }

    private JsonNode read(String data) throws Exception {
        return objectMapper.readTree(data);
    }

    private String friendly(Exception e) {
        String msg = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
        if (msg.contains("Connection refused") || msg.contains("ConnectException")) {
            return "智能体未启动，请先启动 beibei-agent";
        }
        if (msg.contains("HttpTimeoutException") || msg.contains("timeout")) {
            return "面经处理超时（已等待 2 小时）。音频越长耗时越久，"
                    + "可到 beibei-agent 日志里看讯飞语音转写是否还在处理。";
        }
        return msg;
    }
}
