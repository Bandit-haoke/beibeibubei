package com.beibei.dto;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

/**
 * AI 配置相关的请求/响应对象。
 */
public final class AiDto {

    private AiDto() {
    }

    // ---------------- 厂商 ----------------

    /** 厂商配置（Key 全部脱敏，只回是否已配置） */
    public record ProviderVO(
            Long id,
            String name,
            String vendor,
            String protocol,
            String baseUrl,
            String model,
            String apiKeyMasked,
            boolean hasApiKey,
            String apiSecretMasked,
            boolean hasApiSecret,
            String appId,
            String capability,
            Map<String, Object> extraParams,
            Integer enabled,
            Integer priority,
            Integer isActive,
            Integer locked,
            LocalDateTime lastTestAt,
            Integer lastTestOk,
            String lastTestMsg,
            String remark
    ) {
    }

    /** 保存厂商。apiKey / apiSecret 留空表示「不改动原来的值」。 */
    public record ProviderSaveReq(
            String name,
            String vendor,
            String protocol,
            String baseUrl,
            String model,
            String apiKey,
            String apiSecret,
            String appId,
            String capability,
            Map<String, Object> extraParams,
            Integer enabled,
            Integer priority,
            String remark
    ) {
    }

    /** 连通性测试结果 */
    public record TestResultVO(
            boolean ok,
            String message,
            int latencyMs,
            String model,
            String endpoint
    ) {
    }

    // ---------------- 任务路由 ----------------

    public record RouteVO(
            String taskType,
            String taskName,
            String description,
            Long providerId,
            String providerName,
            Long fallbackProviderId,
            String fallbackProviderName,
            String remark
    ) {
    }

    public record RouteSaveReq(
            String taskType,
            Long providerId,
            Long fallbackProviderId,
            String remark
    ) {
    }

    // ---------------- Prompt 模板 ----------------

    public record PromptVO(
            Long id,
            String code,
            String name,
            String content,
            String variables,
            Integer version,
            Integer isActive,
            Integer builtin,
            String remark,
            LocalDateTime createdAt
    ) {
    }

    /** 保存 Prompt：会插入新版本，旧版本自动置为非激活 */
    public record PromptSaveReq(String content, String remark) {
    }

    /** 模板版本列表项 */
    public record PromptVersionVO(
            Long id,
            Integer version,
            Integer isActive,
            String remark,
            LocalDateTime createdAt,
            int contentLength
    ) {
    }

    /** 所有模板的概览（按 code 分组） */
    public record PromptGroupVO(
            String code,
            String name,
            String remark,
            int activeVersion,
            int versionCount,
            List<PromptVersionVO> versions
    ) {
    }
}
