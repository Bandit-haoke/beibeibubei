package com.beibei.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 与 beibei-agent 通信的配置。
 *
 * <p>对应 application-dev.yml：
 * <pre>
 * beibei:
 *   agent:
 *     base-url: http://127.0.0.1:8000
 *     internal-token: bb_internal_xxx
 *     timeout-seconds: 120
 * </pre>
 */
@ConfigurationProperties(prefix = "beibei.agent")
public record AgentProperties(
        String baseUrl,
        String internalToken,
        Integer timeoutSeconds
) {
    public AgentProperties {
        if (baseUrl == null || baseUrl.isBlank()) {
            baseUrl = "http://127.0.0.1:8000";
        }
        if (timeoutSeconds == null || timeoutSeconds <= 0) {
            timeoutSeconds = 120;
        }
    }
}
