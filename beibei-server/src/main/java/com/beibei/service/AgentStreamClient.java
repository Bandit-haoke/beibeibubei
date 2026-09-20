package com.beibei.service;

import com.beibei.config.AgentProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.function.Consumer;
import java.util.stream.Stream;

/**
 * 消费 beibei-agent 的 SSE 流。
 *
 * <p>刻意用 JDK 自带的 {@link java.net.http.HttpClient} + {@code BodyHandlers.ofLines()}，
 * 而不是引入 WebClient（spring-webflux）：少一套响应式依赖，代码也更好懂。
 *
 * <p>SSE 报文格式（与 Python 侧约定一致）：
 * <pre>
 * event: progress
 * data: {"taskId":1,"progress":45,"stage":"正在生成第 9/20 道题","status":1}
 * &lt;空行&gt;
 * </pre>
 */
@Slf4j
@Component
public class AgentStreamClient {

    /** 一个解析出来的 SSE 事件 */
    public record SseEvent(String event, String data) {
    }

    private final AgentProperties props;
    private final ObjectMapper objectMapper;
    private final HttpClient httpClient;

    public AgentStreamClient(AgentProperties props, ObjectMapper objectMapper) {
        this.props = props;
        this.objectMapper = objectMapper;
        this.httpClient = HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(10))
                .version(HttpClient.Version.HTTP_1_1)
                .build();
    }

    /**
     * POST 一个 JSON 到 Python 并逐行消费 SSE 响应。
     *
     * @param path    形如 {@code /api/v1/ingest}
     * @param body    请求体，会被序列化成 JSON
     * @param handler 每收到一个完整事件回调一次
     * @throws IOException 网络异常或 Python 返回非 200
     */
    public void postStream(String path, Object body, Consumer<SseEvent> handler) throws IOException {
        postStream(path, body, handler, props.timeoutSeconds());
    }

    /**
     * 同上，但单独指定超时。
     *
     * <p>为什么需要这个重载：全局默认是 120 秒，对一次 LLM 调用足够，
     * 但面经流水线是「整场面试录音」，光是等待讯飞语音转写出结果就可能十几分钟，
     * 用 120 秒必然被掐断。这里让长任务自己声明一个够用的超时。
     */
    public void postStream(String path, Object body, Consumer<SseEvent> handler,
                           int timeoutSeconds) throws IOException {
        String json;
        try {
            json = objectMapper.writeValueAsString(body);
        } catch (Exception e) {
            throw new IOException("请求体序列化失败: " + e.getMessage(), e);
        }

        HttpRequest request = HttpRequest.newBuilder()
                .uri(URI.create(props.baseUrl() + path))
                .timeout(Duration.ofSeconds(timeoutSeconds))
                .header("Content-Type", "application/json; charset=utf-8")
                .header("Accept", "text/event-stream")
                .header("X-Internal-Token", props.internalToken() == null ? "" : props.internalToken())
                .POST(HttpRequest.BodyPublishers.ofString(json, StandardCharsets.UTF_8))
                .build();

        HttpResponse<Stream<String>> response;
        try {
            response = httpClient.send(request, HttpResponse.BodyHandlers.ofLines());
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new IOException("调用智能体被中断", e);
        }

        if (response.statusCode() != 200) {
            String detail;
            try (Stream<String> lines = response.body()) {
                detail = String.join("\n", lines.limit(20).toList());
            }
            throw new IOException("智能体返回 HTTP " + response.statusCode() + "：" + detail);
        }

        String eventName = null;
        StringBuilder dataBuf = new StringBuilder();

        try (Stream<String> lines = response.body()) {
            for (String line : (Iterable<String>) lines::iterator) {
                if (line == null) {
                    continue;
                }
                // 空行 = 一个事件的结束
                if (line.isEmpty()) {
                    if (dataBuf.length() > 0 || eventName != null) {
                        handler.accept(new SseEvent(
                                eventName == null ? "message" : eventName,
                                dataBuf.toString()));
                    }
                    eventName = null;
                    dataBuf.setLength(0);
                    continue;
                }
                // 以 ':' 开头的是注释/心跳
                if (line.charAt(0) == ':') {
                    continue;
                }
                if (line.startsWith("event:")) {
                    eventName = line.substring(6).trim();
                } else if (line.startsWith("data:")) {
                    if (dataBuf.length() > 0) {
                        dataBuf.append('\n');
                    }
                    dataBuf.append(line.substring(5).trim());
                }
            }
        }

        // 流结束时补发最后一个未闭合的事件
        if (dataBuf.length() > 0 || eventName != null) {
            handler.accept(new SseEvent(eventName == null ? "message" : eventName, dataBuf.toString()));
        }
    }
}
