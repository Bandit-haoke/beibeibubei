package com.beibei.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.beibei.common.AesCipher;
import com.beibei.common.BusinessException;
import com.beibei.dto.AiDto;
import com.beibei.entity.AiProvider;
import com.beibei.entity.ModelRoute;
import com.beibei.entity.PromptTemplate;
import com.beibei.mapper.AiProviderMapper;
import com.beibei.mapper.ModelRouteMapper;
import com.beibei.mapper.PromptTemplateMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.client.RestClient;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * AI 厂商、任务路由、Prompt 模板的配置管理。
 *
 * <p>安全约定：API Key / Secret 用 AES-GCM 加密后落库，接口返回时一律脱敏。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AiConfigService {

    /** 任务类型 → 展示名与说明 */
    public static final Map<String, String[]> TASK_META = new LinkedHashMap<>() {{
        put("QUESTION_GEN", new String[]{"AI 出题", "建议用最强的模型，题目质量直接决定使用体验"});
        put("GRADING", new String[]{"主观题判分", "需要理解语义与要点对齐"});
        put("CLASSIFY", new String[]{"知识点树抽取", "每份文档只调一次"});
        put("CHUNK_TAG", new String[]{"分块打标", "调用量最大，可以用便宜模型"});
        put("SELF_CHECK", new String[]{"题目自检", "防幻觉，调用量等于出题量"});
        put("RECITE_CHECK", new String[]{"口述复述核对", "费曼模式"});
        put("ASR", new String[]{"语音转文字", "讯飞 / 阿里，按优先级降级"});
    }};

    private final AiProviderMapper providerMapper;
    private final ModelRouteMapper routeMapper;
    private final PromptTemplateMapper promptMapper;
    private final ObjectMapper objectMapper;

    /**
     * 用于「测试连通」时探测只有 Python 才知道怎么测的能力：
     * 讯飞的 WebSocket 握手签名、以及本地向量/OCR 的自检状态。
     */
    private final AgentClient agentClient;

    @Value("${beibei.security.secret:}")
    private String secret;

    // ==================================================================
    //  厂商
    // ==================================================================

    public List<AiDto.ProviderVO> listProviders() {
        return providerMapper.selectList(
                        Wrappers.<AiProvider>lambdaQuery()
                                .orderByAsc(AiProvider::getPriority)
                                .orderByAsc(AiProvider::getId))
                .stream().map(this::toVO).toList();
    }

    public AiProvider require(Long id) {
        AiProvider provider = providerMapper.selectById(id);
        if (provider == null) {
            throw BusinessException.notFound("AI 厂商", id);
        }
        return provider;
    }

    @Transactional(rollbackFor = Exception.class)
    public AiDto.ProviderVO create(AiDto.ProviderSaveReq req) {
        if (req.name() == null || req.name().isBlank()) {
            throw BusinessException.invalid("厂商名称不能为空");
        }
        AiProvider provider = new AiProvider();
        applySave(provider, req);
        provider.setLastTestOk(0);
        provider.setIsActive(0);
        provider.setLocked(0);
        providerMapper.insert(provider);
        log.info("新增 AI 厂商 #{} {}", provider.getId(), provider.getName());
        return toVO(provider);
    }

    @Transactional(rollbackFor = Exception.class)
    public AiDto.ProviderVO update(Long id, AiDto.ProviderSaveReq req) {
        AiProvider provider = require(id);
        applySave(provider, req);
        providerMapper.updateById(provider);
        return toVO(require(id));
    }

    private void applySave(AiProvider provider, AiDto.ProviderSaveReq req) {
        if (req.name() != null) {
            provider.setName(req.name().trim());
        }
        if (req.vendor() != null) {
            provider.setVendor(req.vendor().trim());
        }
        if (req.protocol() != null) {
            provider.setProtocol(req.protocol().trim());
        }
        if (req.baseUrl() != null) {
            provider.setBaseUrl(req.baseUrl().trim());
        }
        if (req.model() != null) {
            provider.setModel(req.model().trim());
        }
        if (req.appId() != null) {
            provider.setAppId(req.appId().trim());
        }
        if (req.capability() != null) {
            provider.setCapability(req.capability().trim().toUpperCase());
        }
        if (req.enabled() != null) {
            provider.setEnabled(req.enabled());
        }
        if (req.priority() != null) {
            provider.setPriority(req.priority());
        }
        if (req.remark() != null) {
            provider.setRemark(req.remark());
        }
        if (req.extraParams() != null) {
            provider.setExtraParams(toJson(req.extraParams()));
        }
        // Key 留空表示不改动 —— 否则用户每次改个备注都要重填 Key
        if (req.apiKey() != null && !req.apiKey().isBlank()) {
            provider.setApiKeyEnc(AesCipher.encrypt(req.apiKey().trim(), secret));
        }
        if (req.apiSecret() != null && !req.apiSecret().isBlank()) {
            provider.setApiSecretEnc(AesCipher.encrypt(req.apiSecret().trim(), secret));
        }
    }

    @Transactional(rollbackFor = Exception.class)
    public void delete(Long id) {
        AiProvider provider = require(id);
        if (provider.getLocked() != null && provider.getLocked() == 1) {
            throw BusinessException.invalid(
                    "「" + provider.getName() + "」是本地锁定项，不能删除。"
                    + "它是向量化 / OCR 的固定依赖，换了会导致已入库数据不可用。");
        }
        // 被任务路由引用的先清掉引用，避免留下悬空 ID
        routeMapper.delete(Wrappers.<ModelRoute>lambdaQuery().eq(ModelRoute::getProviderId, id));
        routeMapper.update(null, Wrappers.<ModelRoute>lambdaUpdate()
                .eq(ModelRoute::getFallbackProviderId, id)
                .set(ModelRoute::getFallbackProviderId, 0L));
        providerMapper.deleteById(id);
        log.info("删除 AI 厂商 #{} {}", id, provider.getName());
    }

    /** 设为该能力的当前使用项 */
    @Transactional(rollbackFor = Exception.class)
    public void activate(Long id) {
        AiProvider provider = require(id);
        if (provider.getLocked() != null && provider.getLocked() == 1) {
            throw BusinessException.invalid("该项目已锁定，无需切换");
        }
        if (provider.getEnabled() == null || provider.getEnabled() == 0) {
            throw BusinessException.invalid("请先启用该厂商");
        }
        // 同一能力下只留一个 active
        for (String cap : provider.getCapability().split(",")) {
            providerMapper.update(null, Wrappers.<AiProvider>lambdaUpdate()
                    .like(AiProvider::getCapability, cap.trim())
                    .set(AiProvider::getIsActive, 0));
            providerMapper.update(null, Wrappers.<AiProvider>lambdaUpdate()
                    .like(AiProvider::getCapability, cap.trim())
                    .eq(AiProvider::getId, id)
                    .set(AiProvider::getIsActive, 1));
        }
        log.info("切换当前使用厂商：#{} {}", id, provider.getName());
    }

    /**
     * 连通性测试：按**能力**分派，不是所有厂商都发 chat 请求。
     *
     * <p>踩过的坑：以前这里不分能力，一律拼 `/v1/chat/completions`。
     * 于是给讯飞语音听写点「测试连通」，它会拿 WebSocket 地址去拼 HTTP 路径，
     * 报 `Illegal character in scheme name at index 2: ws%5Bs%5D://…` ——
     * 用户完全看不懂，还以为是自己填错了。
     *
     * <p>现在的分派：
     * <ul>
     *   <li>CHAT：发一条最小 chat 请求（真的验证 Key 有效）</li>
     *   <li>ASR（讯飞）：让 Python 用三个值做一次真实 WebSocket 握手 ——
     *       签名逻辑只有一份，Java 不重复实现</li>
     *   <li>EMBED / OCR（本地）：直接读 beibei-agent 的自检结果，
     *       这两项是进程内能力，本来就没有独立端点可探</li>
     * </ul>
     */
    public AiDto.TestResultVO test(Long id) {
        AiProvider provider = require(id);

        if ("mock".equalsIgnoreCase(provider.getVendor())) {
            return new AiDto.TestResultVO(true, "Mock 模式无需联网，始终可用", 0,
                    provider.getModel(), "local");
        }

        String capability = provider.getCapability() == null
                ? "" : provider.getCapability().toUpperCase();
        if (capability.contains(AiProvider.CAP_ASR)) {
            return testAsr(provider);
        }
        if (capability.contains(AiProvider.CAP_EMBED) || capability.contains(AiProvider.CAP_OCR)) {
            return testLocalCapability(provider);
        }

        return testChat(provider);
    }

    /** 对话模型：发一条最小请求，真实验证 Key 是否有效。 */
    private AiDto.TestResultVO testChat(AiProvider provider) {
        String apiKey = AesCipher.decrypt(provider.getApiKeyEnc(), secret);

        if (apiKey.isBlank() && !"ollama".equalsIgnoreCase(provider.getProtocol())) {
            return new AiDto.TestResultVO(false, "还没有填写 API Key", 0,
                    provider.getModel(), "");
        }

        String base = provider.getBaseUrl() == null ? "" : provider.getBaseUrl().replaceAll("/+$", "");
        String schemeError = validateHttpBase(base);
        if (schemeError != null) {
            markTest(provider.getId(), false, schemeError);
            return new AiDto.TestResultVO(false, schemeError, 0, provider.getModel(), base);
        }

        String endpoint;
        String body;
        if ("ollama".equalsIgnoreCase(provider.getProtocol())) {
            endpoint = base + "/api/tags";
            body = null;
        } else {
            endpoint = base.endsWith("/v1") ? base + "/chat/completions" : base + "/v1/chat/completions";
            body = toJson(Map.of(
                    "model", provider.getModel(),
                    "messages", List.of(Map.of("role", "user", "content", "ping")),
                    "max_tokens", 1,
                    "stream", false));
        }

        long started = System.currentTimeMillis();
        try {
            RestClient client = RestClient.builder()
                    .requestFactory(timeoutFactory())
                    .build();

            String response;
            if (body == null) {
                response = client.get().uri(endpoint).retrieve().body(String.class);
            } else {
                RestClient.RequestBodySpec spec = client.post()
                        .uri(endpoint)
                        .contentType(MediaType.APPLICATION_JSON);
                if (!apiKey.isBlank()) {
                    spec = spec.header("Authorization", "Bearer " + apiKey);
                }
                response = spec.body(body).retrieve().body(String.class);
            }

            int latency = (int) (System.currentTimeMillis() - started);
            String preview = response == null ? "" : response.replaceAll("\\s+", " ")
                    .substring(0, Math.min(120, response.length()));
            markTest(provider.getId(), true, "连通正常（" + latency + " ms）");
            return new AiDto.TestResultVO(true,
                    "连通正常，模型返回：" + (preview.isBlank() ? "（空响应）" : preview),
                    latency, provider.getModel(), endpoint);
        } catch (Exception e) {
            int latency = (int) (System.currentTimeMillis() - started);
            String msg = friendly(e);
            markTest(provider.getId(), false, msg);
            return new AiDto.TestResultVO(false, msg, latency, provider.getModel(), endpoint);
        }
    }

    /**
     * 语音识别：交给 Python 做真实 WebSocket 握手。
     *
     * <p>讯飞是 APPID + APIKey + APISecret 三个值一起决定成败的，
     * 填错任何一个只有握手才知道 —— 检查「字段非空」毫无意义。
     */
    private AiDto.TestResultVO testAsr(AiProvider provider) {
        String vendor = provider.getVendor() == null ? "" : provider.getVendor().toLowerCase();

        // 语音转写（面经用它做角色分离）：地址与协议都不同，走单独的探测接口
        if ("xfyun_lfasr".equals(vendor)) {
            long startedLfasr = System.currentTimeMillis();
            Map<String, Object> body = agentClient.probeLfasr(provider.getId());
            boolean ok = Boolean.TRUE.equals(body.get("ok"));
            int latency = body.get("latencyMs") instanceof Number n
                    ? n.intValue() : (int) (System.currentTimeMillis() - startedLfasr);
            String endpoint = String.valueOf(body.getOrDefault("endpoint", provider.getBaseUrl()));

            String message;
            if (ok) {
                message = "语音转写可用（" + latency + " ms）—— "
                        + body.getOrDefault("message", "角色分离已开启");
            } else {
                message = String.valueOf(body.getOrDefault("error", "探测失败"));
                Object hint = body.get("hint");
                if (hint != null && !String.valueOf(hint).isBlank()) {
                    message = message + " —— " + hint;
                }
            }
            markTest(provider.getId(), ok, message);
            return new AiDto.TestResultVO(ok, message, latency, provider.getModel(), endpoint);
        }

        if (!"xfyun".equalsIgnoreCase(provider.getVendor())) {
            String msg = "暂时只支持自动测试讯飞语音听写；"
                    + "「" + provider.getVendor() + "」请录音实测，或用打字作答";
            markTest(provider.getId(), false, msg);
            return new AiDto.TestResultVO(false, msg, 0, provider.getModel(), "");
        }

        Map<String, Object> body = agentClient.probeAsr(provider.getId());
        boolean ok = Boolean.TRUE.equals(body.get("ok"));
        int latency = body.get("latencyMs") instanceof Number n ? n.intValue() : 0;
        String endpoint = String.valueOf(body.getOrDefault("endpoint", ""));

        String message;
        if (ok) {
            message = "连通正常（" + latency + " ms）—— "
                    + body.getOrDefault("message", "三个值都有效");
        } else {
            message = String.valueOf(body.getOrDefault("error", "探测失败"));
            Object hint = body.get("hint");
            if (hint != null && !String.valueOf(hint).isBlank()) {
                message = message + " —— " + hint;
            }
        }
        markTest(provider.getId(), ok, message);
        return new AiDto.TestResultVO(ok, message, latency, provider.getModel(), endpoint);
    }

    /**
     * 本地能力（BGE-M3 向量 / PaddleOCR）：直接读智能体的自检结果。
     *
     * <p>这两项跑在 beibei-agent 进程**内部**，没有独立端点。
     * 数据库里那个 `http://127.0.0.1:8001` 只是占位，去探它必然失败，
     * 会让人误以为功能坏了 —— 所以改成采纳自检的结论。
     */
    private AiDto.TestResultVO testLocalCapability(AiProvider provider) {
        String cap = provider.getCapability() == null ? "" : provider.getCapability().toUpperCase();
        String checkKey = cap.contains(AiProvider.CAP_EMBED) ? "embedding" : "ocr";

        long started = System.currentTimeMillis();
        try {
            Map<String, Object> health = agentClient.health();
            if (Boolean.TRUE.equals(health.get("unreachable"))) {
                String msg = "智能体未启动，无法自检本地能力";
                markTest(provider.getId(), false, msg);
                return new AiDto.TestResultVO(false, msg,
                        (int) (System.currentTimeMillis() - started), provider.getModel(), "");
            }
            Object checks = health.get("checks");
            if (checks instanceof List<?> list) {
                for (Object item : list) {
                    if (!(item instanceof Map<?, ?> check)) {
                        continue;
                    }
                    if (!checkKey.equals(String.valueOf(check.get("key")))) {
                        continue;
                    }
                    boolean ok = Boolean.TRUE.equals(check.get("ok"));
                    // 注意：check 是 Map<?,?>，不能写 check.getOrDefault("detail", "")
                    // ——通配符捕获之后，默认值参数只接受 capture of ?，传 String 编译不过
                    Object detailRaw = check.get("detail");
                    String detail = detailRaw == null ? "" : String.valueOf(detailRaw);
                    int latency = (int) (System.currentTimeMillis() - started);
                    String msg = (ok ? "本地能力就绪：" : "本地能力异常：") + detail;
                    markTest(provider.getId(), ok, msg);
                    return new AiDto.TestResultVO(ok, msg, latency, provider.getModel(), "进程内");
                }
            }
            String msg = "自检结果里没有找到「" + checkKey + "」这一项";
            markTest(provider.getId(), false, msg);
            return new AiDto.TestResultVO(false, msg,
                    (int) (System.currentTimeMillis() - started), provider.getModel(), "");
        } catch (Exception e) {
            String msg = friendly(e);
            markTest(provider.getId(), false, msg);
            return new AiDto.TestResultVO(false, msg,
                    (int) (System.currentTimeMillis() - started), provider.getModel(), "");
        }
    }

    /**
     * 提前拦掉「把 WebSocket 地址填进对话模型」这类错误。
     *
     * <p>不拦的话会在 URI 解析阶段抛 `Illegal character in scheme name`，
     * 那句英文对用户没有任何指导意义。
     *
     * @return null 表示没问题，否则返回给用户看的错误文案
     */
    private String validateHttpBase(String base) {
        if (base.isBlank()) {
            return "Base URL 不能为空";
        }
        String lower = base.toLowerCase();
        if (lower.startsWith("ws://") || lower.startsWith("wss://") || lower.contains("ws[s]")) {
            return "这是一个 WebSocket 地址。对话模型要用 http(s):// 开头的 HTTP 接口地址；"
                    + "语音听写的 wss 地址请填在「讯飞语音听写」那条记录里";
        }
        if (!lower.startsWith("http://") && !lower.startsWith("https://")) {
            return "Base URL 要以 http:// 或 https:// 开头，当前是：" + base;
        }
        return null;
    }

    private SimpleClientHttpRequestFactory timeoutFactory() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(8000);
        factory.setReadTimeout(30000);
        return factory;
    }

    private String friendly(Exception e) {
        String msg = e.getMessage() == null ? e.getClass().getSimpleName() : e.getMessage();
        if (msg.contains("Illegal character in scheme name")) {
            // 典型场景：把讯飞文档里的 `ws[s]://…` 整个复制进了对话模型的 Base URL
            return "Base URL 格式不对（含非法字符，比如从文档复制的 ws[s]:// 简写）。"
                    + "对话模型要填 http(s):// 开头的地址";
        }
        if (msg.contains("401") || msg.contains("Unauthorized")) {
            return "认证失败（401）—— API Key 不正确或已失效";
        }
        if (msg.contains("403")) {
            return "被拒绝（403）—— 可能是 Key 权限不足或地区限制";
        }
        if (msg.contains("404")) {
            return "接口不存在（404）—— 检查 Base URL 与模型名是否正确";
        }
        if (msg.contains("429")) {
            return "请求过于频繁（429）或余额不足";
        }
        if (msg.contains("timed out") || msg.contains("Timeout")) {
            return "请求超时 —— 检查网络能否访问该厂商";
        }
        if (msg.contains("Connection refused") || msg.contains("ConnectException")) {
            return "无法连接 —— 检查 Base URL 与网络";
        }
        return msg.length() > 300 ? msg.substring(0, 300) : msg;
    }

    private void markTest(Long id, boolean ok, String msg) {
        AiProvider patch = new AiProvider();
        patch.setId(id);
        patch.setLastTestAt(LocalDateTime.now());
        patch.setLastTestOk(ok ? 1 : 0);
        patch.setLastTestMsg(msg.length() > 490 ? msg.substring(0, 490) : msg);
        providerMapper.updateById(patch);
    }

    public AiDto.ProviderVO toVO(AiProvider p) {
        String key = AesCipher.decrypt(p.getApiKeyEnc(), secret);
        String apiSecret = AesCipher.decrypt(p.getApiSecretEnc(), secret);
        return new AiDto.ProviderVO(
                p.getId(), p.getName(), p.getVendor(), p.getProtocol(), p.getBaseUrl(), p.getModel(),
                AesCipher.mask(key), !key.isBlank(),
                AesCipher.mask(apiSecret), !apiSecret.isBlank(),
                p.getAppId() == null ? "" : p.getAppId(),
                p.getCapability(),
                parseMap(p.getExtraParams()),
                p.getEnabled(), p.getPriority(), p.getIsActive(), p.getLocked(),
                p.getLastTestAt(), p.getLastTestOk(), p.getLastTestMsg(),
                p.getRemark() == null ? "" : p.getRemark()
        );
    }

    // ==================================================================
    //  任务路由
    // ==================================================================

    public List<AiDto.RouteVO> listRoutes() {
        Map<String, ModelRoute> existing = routeMapper.selectList(null).stream()
                .collect(Collectors.toMap(ModelRoute::getTaskType, r -> r, (a, b) -> a));
        Map<Long, String> providerNames = providerMapper.selectList(null).stream()
                .collect(Collectors.toMap(AiProvider::getId, AiProvider::getName));

        List<AiDto.RouteVO> out = new ArrayList<>();
        for (Map.Entry<String, String[]> entry : TASK_META.entrySet()) {
            String task = entry.getKey();
            ModelRoute route = existing.get(task);
            Long pid = route == null ? null : route.getProviderId();
            Long fid = route == null ? null : route.getFallbackProviderId();
            out.add(new AiDto.RouteVO(
                    task, entry.getValue()[0], entry.getValue()[1],
                    pid == null || pid == 0 ? null : pid,
                    pid == null ? "" : providerNames.getOrDefault(pid, "（已删除）"),
                    fid == null || fid == 0 ? null : fid,
                    fid == null ? "" : providerNames.getOrDefault(fid, ""),
                    route == null ? "" : route.getRemark()
            ));
        }
        return out;
    }

    @Transactional(rollbackFor = Exception.class)
    public void saveRoute(AiDto.RouteSaveReq req) {
        if (!TASK_META.containsKey(req.taskType())) {
            throw BusinessException.invalid("未知任务类型：" + req.taskType());
        }
        ModelRoute existing = routeMapper.selectOne(
                Wrappers.<ModelRoute>lambdaQuery().eq(ModelRoute::getTaskType, req.taskType()));
        ModelRoute route = existing == null ? new ModelRoute() : existing;
        route.setTaskType(req.taskType());
        route.setProviderId(req.providerId() == null ? 0L : req.providerId());
        route.setFallbackProviderId(req.fallbackProviderId() == null ? 0L : req.fallbackProviderId());
        route.setRemark(req.remark() == null ? "" : req.remark());
        if (existing == null) {
            routeMapper.insert(route);
        } else {
            routeMapper.updateById(route);
        }
        log.info("任务路由更新：{} → provider={}", req.taskType(), route.getProviderId());
    }

    // ==================================================================
    //  Prompt 模板
    // ==================================================================

    /** 按 code 分组返回所有模板及版本 */
    public List<AiDto.PromptGroupVO> listPromptGroups() {
        List<PromptTemplate> all = promptMapper.selectList(
                Wrappers.<PromptTemplate>lambdaQuery()
                        .orderByAsc(PromptTemplate::getCode)
                        .orderByDesc(PromptTemplate::getVersion));

        Map<String, List<PromptTemplate>> byCode = new LinkedHashMap<>();
        for (PromptTemplate t : all) {
            byCode.computeIfAbsent(t.getCode(), k -> new ArrayList<>()).add(t);
        }

        List<AiDto.PromptGroupVO> out = new ArrayList<>();
        for (Map.Entry<String, List<PromptTemplate>> entry : byCode.entrySet()) {
            List<PromptTemplate> versions = entry.getValue();
            PromptTemplate active = versions.stream()
                    .filter(t -> t.getIsActive() != null && t.getIsActive() == 1)
                    .findFirst().orElse(versions.get(0));
            out.add(new AiDto.PromptGroupVO(
                    entry.getKey(), active.getName(), active.getRemark(),
                    active.getVersion() == null ? 1 : active.getVersion(),
                    versions.size(),
                    versions.stream().map(t -> new AiDto.PromptVersionVO(
                            t.getId(), t.getVersion(), t.getIsActive(), t.getRemark(),
                            t.getCreatedAt(), t.getContent() == null ? 0 : t.getContent().length()
                    )).toList()
            ));
        }
        return out;
    }

    public List<AiDto.PromptVO> listPromptVersions(String code) {
        return promptMapper.selectList(
                        Wrappers.<PromptTemplate>lambdaQuery()
                                .eq(PromptTemplate::getCode, code)
                                .orderByDesc(PromptTemplate::getVersion))
                .stream().map(this::toPromptVO).toList();
    }

    public AiDto.PromptVO getPrompt(Long id) {
        PromptTemplate t = promptMapper.selectById(id);
        if (t == null) {
            throw BusinessException.notFound("Prompt 模板", id);
        }
        return toPromptVO(t);
    }

    /**
     * 保存 Prompt：**插入新版本**并把旧版本置为非激活。
     * 这样改坏了随时能回滚，也不会丢失历史调优记录。
     */
    @Transactional(rollbackFor = Exception.class)
    public AiDto.PromptVO savePromptVersion(Long id, AiDto.PromptSaveReq req) {
        PromptTemplate base = promptMapper.selectById(id);
        if (base == null) {
            throw BusinessException.notFound("Prompt 模板", id);
        }
        if (req.content() == null || req.content().isBlank()) {
            throw BusinessException.invalid("模板内容不能为空");
        }

        Integer maxVersion = promptMapper.selectList(
                        Wrappers.<PromptTemplate>lambdaQuery()
                                .eq(PromptTemplate::getCode, base.getCode()))
                .stream().map(t -> t.getVersion() == null ? 1 : t.getVersion())
                .max(Integer::compareTo).orElse(1);

        // 旧版本全部置为非激活
        promptMapper.update(null, Wrappers.<PromptTemplate>lambdaUpdate()
                .eq(PromptTemplate::getCode, base.getCode())
                .set(PromptTemplate::getIsActive, 0));

        PromptTemplate fresh = new PromptTemplate();
        fresh.setCode(base.getCode());
        fresh.setName(base.getName());
        fresh.setContent(req.content());
        fresh.setVariables(base.getVariables());
        fresh.setVersion(maxVersion + 1);
        fresh.setIsActive(1);
        fresh.setBuiltin(0);
        fresh.setRemark(req.remark() == null || req.remark().isBlank()
                ? "从 v" + maxVersion + " 修改" : req.remark());
        promptMapper.insert(fresh);

        log.info("Prompt {} 保存新版本 v{}（原激活版本 v{}）", base.getCode(), fresh.getVersion(), maxVersion);
        return toPromptVO(fresh);
    }

    /** 回滚到某个历史版本（做法是把它复制成一个新版本，历史链条不断） */
    @Transactional(rollbackFor = Exception.class)
    public AiDto.PromptVO rollback(Long versionId) {
        PromptTemplate target = promptMapper.selectById(versionId);
        if (target == null) {
            throw BusinessException.notFound("Prompt 版本", versionId);
        }
        return savePromptVersion(versionId,
                new AiDto.PromptSaveReq(target.getContent(), "回滚自 v" + target.getVersion()));
    }

    public AiDto.PromptVO toPromptVO(PromptTemplate t) {
        return new AiDto.PromptVO(
                t.getId(), t.getCode(), t.getName(), t.getContent(), t.getVariables(),
                t.getVersion(), t.getIsActive(), t.getBuiltin(),
                t.getRemark() == null ? "" : t.getRemark(), t.getCreatedAt()
        );
    }

    // ==================================================================

    private String toJson(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception e) {
            return null;
        }
    }

    @SuppressWarnings("unchecked")
    private Map<String, Object> parseMap(String json) {
        if (json == null || json.isBlank()) {
            return Map.of();
        }
        try {
            return objectMapper.readValue(json, Map.class);
        } catch (Exception e) {
            return Map.of();
        }
    }
}
