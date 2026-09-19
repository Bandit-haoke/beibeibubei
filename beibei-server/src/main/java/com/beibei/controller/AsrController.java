package com.beibei.controller;

import com.beibei.common.Result;
import com.beibei.service.AgentClient;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 语音转文字接口。
 *
 * <p>前端 {@code MediaRecorder} 录出来的通常是 webm/opus，
 * Java 只做转发，真正的转码与识别在 Python 侧完成。
 *
 * <p>服务不可用时返回 {@code code=5032}，前端据此隐藏录音按钮而不是弹错误。
 */
@Slf4j
@RestController
@RequestMapping("/api/asr")
@RequiredArgsConstructor
@Tag(name = "语音", description = "录音转文字（含专有名词热词纠错）")
public class AsrController {

    private final AgentClient agentClient;

    @PostMapping("/transcribe")
    @Operation(summary = "语音转文字")
    public Result<Map<String, Object>> transcribe(
            @RequestParam("audio") MultipartFile audio,
            @RequestParam(required = false) Long kbId,
            @RequestParam(defaultValue = "true") boolean applyHotwords) {

        if (audio == null || audio.isEmpty()) {
            return Result.fail(Result.BAD_REQUEST, "音频文件为空");
        }

        byte[] data;
        try {
            data = audio.getBytes();
        } catch (Exception e) {
            return Result.fail(Result.BAD_REQUEST, "读取音频失败：" + e.getMessage());
        }

        Map<String, Object> response = agentClient.transcribe(
                data, audio.getOriginalFilename() == null ? "audio.webm" : audio.getOriginalFilename(),
                kbId, applyHotwords);

        if (Boolean.TRUE.equals(response.get("asrUnavailable"))) {
            Map<String, Object> data2 = new LinkedHashMap<>(response);
            data2.put("text", "");
            return new Result<>(Result.ASR_UNAVAILABLE,
                    String.valueOf(response.getOrDefault("error", "语音服务不可用")),
                    data2, null);
        }

        return Result.ok(response);
    }

    /**
     * 热词纠错（调试用）。
     *
     * <p>单独暴露，方便在**没有 ASR 凭据**时也能验证纠错效果，
     * 或者排查「某个专有名词老是识别错」的问题。
     */
    @PostMapping("/correct-hotwords")
    @Operation(summary = "热词纠错（不需要 ASR 凭据）")
    public Result<Map<String, Object>> correctHotwords(@RequestBody Map<String, Object> body) {
        return Result.ok(agentClient.correctHotwords(body));
    }

    @GetMapping("/hotwords")
    @Operation(summary = "查看当前热词表")
    public Result<Map<String, Object>> hotwords(@RequestParam(required = false) Long kbId) {
        return Result.ok(agentClient.listHotwords(kbId));
    }
}
