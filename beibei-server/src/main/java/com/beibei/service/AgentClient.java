package com.beibei.service;

import com.beibei.config.AgentProperties;
import lombok.extern.slf4j.Slf4j;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 调用 beibei-agent（Python 智能体）的客户端。
 *
 * <p>约定：只有 Java 主动调 Python，前端永远不直连 8000 端口。
 * 所有请求带 {@code X-Internal-Token}，与 Python 侧 .env 的 INTERNAL_TOKEN 一致。
 *
 * <p>统一走 {@link #getSafe} / {@link #postSafe}：智能体没启动时返回结构化的失败信息，
 * 而不是抛异常把 500 抛给前端 —— 前端要能显示「智能体未启动，请先运行 beibei-agent」。
 */
@Slf4j
@Component
public class AgentClient {

    private static final ParameterizedTypeReference<Map<String, Object>> MAP_TYPE =
            new ParameterizedTypeReference<>() {
            };

    private final AgentProperties props;
    private final RestClient restClient;
    private final AgentStreamClient agentStream;

    public AgentClient(AgentProperties props, AgentStreamClient agentStream) {
        this.props = props;
        this.agentStream = agentStream;

        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5_000);
        factory.setReadTimeout(props.timeoutSeconds() * 1000);

        this.restClient = RestClient.builder()
                .baseUrl(props.baseUrl())
                .requestFactory(factory)
                .defaultHeader("X-Internal-Token",
                        props.internalToken() == null ? "" : props.internalToken())
                .build();

        log.info("AgentClient 已初始化: baseUrl={}, timeout={}s",
                props.baseUrl(), props.timeoutSeconds());
    }

    // ------------------------------------------------------------------
    //  公开方法
    // ------------------------------------------------------------------

    /** 极简存活探测。 */
    public Map<String, Object> ping() {
        return getSafe("/api/v1/health/ping");
    }

    /** 环境自检（8 项）。 */
    public Map<String, Object> health() {
        return getSafe("/api/v1/health");
    }

    /**
     * 环境自检，可选真实探测一次大模型。
     *
     * @param probeLlm true 时会实际调用一次 DeepSeek 验证 Key 有效性
     */
    public Map<String, Object> health(boolean probeLlm) {
        return getSafe("/api/v1/health?probe_llm=" + probeLlm);
    }

    /** 确保 Milvus 分区存在（幂等）。建知识库时预创建，省得首次入库才建。 */
    public Map<String, Object> ensurePartition(String collection, String partition) {
        return postSafe("/api/v1/vectors/ensure-partition",
                Map.of("collection", collection, "partition", partition));
    }

    /** 删除 Milvus 分区（连带分区内所有向量）。删知识库时调用。 */
    public Map<String, Object> dropPartition(String collection, String partition) {
        return postSafe("/api/v1/vectors/drop-partition",
                Map.of("collection", collection, "partition", partition));
    }

    /** 按 docId 删除向量。删文档时调用。 */
    public Map<String, Object> deleteVectors(String collection, String partition, Long docId) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("collection", collection);
        body.put("partition", partition);
        body.put("docId", docId);
        return postSafe("/api/v1/vectors/delete", body);
    }

    /** 混合检索（向量 + BM25 + RRF），调试页与 RAG 共用。 */
    public Map<String, Object> search(Object request) {
        return postSafe("/api/v1/search", request);
    }

    /**
     * 语音转文字。
     *
     * <p>走 multipart 上传音频；Python 侧会用 ffmpeg 转 16k PCM 再调讯飞，
     * 最后做专有名词热词纠错。
     */
    public Map<String, Object> transcribe(byte[] audio, String filename, Long kbId, boolean applyHotwords) {
        try {
            org.springframework.util.LinkedMultiValueMap<String, Object> form =
                    new org.springframework.util.LinkedMultiValueMap<>();
            form.add("audio", new org.springframework.core.io.ByteArrayResource(audio) {
                @Override
                public String getFilename() {
                    return filename;
                }
            });
            if (kbId != null) {
                form.add("kbId", String.valueOf(kbId));
            }
            form.add("applyHotwords", String.valueOf(applyHotwords));

            Map<String, Object> body = restClient.post()
                    .uri("/api/v1/asr")
                    .contentType(org.springframework.http.MediaType.MULTIPART_FORM_DATA)
                    .body(form)
                    .retrieve()
                    .body(MAP_TYPE);
            return body == null ? asrUnavailable("智能体返回空响应") : body;
        } catch (Exception ex) {
            log.warn("语音转文字失败: {}", ex.getMessage());
            return asrUnavailable(friendlyError(ex));
        }
    }

    /** 热词纠错（调试用，不需要 ASR 凭据） */
    public Map<String, Object> correctHotwords(Object body) {
        return postSafe("/api/v1/asr/correct-hotwords", body);
    }

    /** 查看当前热词表 */
    public Map<String, Object> listHotwords(Long kbId) {
        return getSafe("/api/v1/asr/hotwords" + (kbId == null ? "" : "?kbId=" + kbId));
    }

    /**
     * 讯飞凭据探测：让 Python 用三个值做一次真实 WebSocket 握手。
     *
     * <p>签名逻辑只有 Python 那一份，Java 不重复实现 ——
     * 而且 Python 能直接读库里的加密凭据，不用把明文 Key 来回传。
     */
    public Map<String, Object> probeAsr(Long providerId) {
        return postSafe("/api/v1/asr/probe", Map.of("providerId", providerId));
    }

    /**
     * 探测讯飞【语音转写】能不能用（面经功能依赖它做角色分离）。
     *
     * <p>Python 侧只调 prepare，不上传音频、不消耗转写时长，所以点多少次都不会花钱。
     * 签名也在 Python 那份代码里，Java 不重复实现。
     */
    public Map<String, Object> probeLfasr(Long providerId) {
        return postSafe("/api/v1/interview-note/probe", Map.of("providerId", providerId));
    }

    /** MySQL 分块 ↔ Milvus 向量 一致性校验 */
    public Map<String, Object> consistencyCheck() {
        return getSafe("/api/v1/vectors/consistency");
    }

    /** 清理孤儿向量 */
    public Map<String, Object> repairConsistency() {
        return postSafe("/api/v1/vectors/consistency/repair", Map.of());
    }

    private Map<String, Object> asrUnavailable(String message) {        Map<String, Object> result = new LinkedHashMap<>();
        result.put("ok", false);
        result.put("asrUnavailable", true);
        result.put("error", message);
        result.put("hint", "语音服务不可用，请手动输入答案");
        return result;
    }

    private String friendlyError(Exception ex) {
        String msg = ex.getMessage() == null ? ex.getClass().getSimpleName() : ex.getMessage();
        if (msg.contains("Connection refused") || msg.contains("ConnectException")) {
            return "智能体未启动";
        }
        return msg;
    }

    /** 抽取知识点树（异步任务内调用，走 SSE）。 */
    public void extractTags(Object request, java.util.function.Consumer<AgentStreamClient.SseEvent> handler)
            throws java.io.IOException {
        agentStream.postStream("/api/v1/tags/extract", request, handler);
    }

    // ------------------------------------------------------------------
    //  AI 模拟面试
    // ------------------------------------------------------------------

    /** 解析简历并抽取结构化档案（异步任务内调用，走 SSE 推进度）。 */
    public void parseResume(Object request,
                            java.util.function.Consumer<AgentStreamClient.SseEvent> handler)
            throws java.io.IOException {
        agentStream.postStream("/api/v1/resume-parse", request, handler);
    }

    /**
     * 开始一场面试，拿第一题。
     *
     * <p>后面三个都走同步 JSON：一轮就是一次 LLM 调用，几秒钟的事，
     * 用 SSE 推「进度」反而让前端状态机复杂一倍。
     */
    public Map<String, Object> interviewStart(Long interviewId) {
        return postSafe("/api/v1/interview/start", Map.of("interviewId", interviewId));
    }

    /** 提交一轮回答：评分 + 追问。 */
    public Map<String, Object> interviewAnswer(Long interviewId, String answer) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("interviewId", interviewId);
        body.put("answer", answer == null ? "" : answer);
        return postSafe("/api/v1/interview/answer", body);
    }

    /** 结束面试并生成评估报告。 */
    public Map<String, Object> interviewFinish(Long interviewId) {
        return postSafe("/api/v1/interview/finish", Map.of("interviewId", interviewId));
    }

    // ------------------------------------------------------------------
    //  内部实现
    // ------------------------------------------------------------------

    private Map<String, Object> postSafe(String path, Object body) {
        try {
            Map<String, Object> result = restClient.post()
                    .uri(path)
                    .body(body)
                    .retrieve()
                    .body(MAP_TYPE);
            return result == null ? unreachable("智能体返回空响应") : result;
        } catch (Exception ex) {
            log.warn("调用智能体失败 {} -> {}", path, ex.getMessage());
            return unreachable(ex.getMessage());
        }
    }

    private Map<String, Object> getSafe(String path) {
        try {
            Map<String, Object> body = restClient.get()
                    .uri(path)
                    .retrieve()
                    .body(MAP_TYPE);
            return body == null ? unreachable("智能体返回空响应") : body;
        } catch (Exception ex) {
            log.warn("调用智能体失败 {} -> {}", path, ex.getMessage());
            return unreachable(ex.getMessage());
        }
    }

    private Map<String, Object> unreachable(String message) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("ok", false);
        result.put("coreOk", false);
        result.put("unreachable", true);
        result.put("baseUrl", props.baseUrl());
        result.put("error", message);
        result.put("hint", "智能体未启动。请在 PyCharm 中运行 beibei-agent/run.py，"
                + "或执行 D:\\conda-envs\\beibei\\python.exe run.py");
        return result;
    }
}
