package com.beibei.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * AI 厂商配置。表 bb_ai_provider。
 *
 * <p>{@code capability} 用逗号分隔，一个厂商可同时提供多种能力
 * （例如本地服务既是 EMBED 又是 OCR）。
 */
@Data
@TableName("bb_ai_provider")
public class AiProvider implements Serializable {

    public static final String CAP_CHAT = "CHAT";
    public static final String CAP_EMBED = "EMBED";
    public static final String CAP_ASR = "ASR";
    public static final String CAP_OCR = "OCR";

    @TableId(type = IdType.AUTO)
    private Long id;

    private String name;

    /** deepseek / qwen / zhipu / moonshot / openai / claude / ollama / xfyun / aliyun / local / mock */
    private String vendor;

    /** openai-compatible / anthropic / gemini / ollama / custom */
    private String protocol;

    private String baseUrl;
    private String model;

    /** AES 加密存储，接口返回时脱敏 */
    private String apiKeyEnc;
    private String apiSecretEnc;
    private String appId;

    private String capability;

    /** temperature / max_tokens / price_in / price_out 等 */
    private String extraParams;

    private Integer enabled;
    private Integer priority;
    private Integer isActive;

    /** 1 = 锁定不可切换（本地 embedding / OCR 用） */
    private Integer locked;

    private LocalDateTime lastTestAt;
    private Integer lastTestOk;
    private String lastTestMsg;
    private String remark;

    @TableField(fill = FieldFill.INSERT)
    private LocalDateTime createdAt;

    @TableField(fill = FieldFill.INSERT_UPDATE)
    private LocalDateTime updatedAt;
}