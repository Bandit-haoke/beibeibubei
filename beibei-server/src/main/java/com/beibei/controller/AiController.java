package com.beibei.controller;

import com.beibei.common.Result;
import com.beibei.dto.AiDto;
import com.beibei.service.AiConfigService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * AI 配置接口：厂商、任务路由、Prompt 模板。
 *
 * <p>API Key 一律脱敏返回；保存时留空表示「不改动原来的值」。
 */
@RestController
@RequestMapping("/api/ai")
@RequiredArgsConstructor
@Tag(name = "AI 配置", description = "厂商管理、连通性测试、任务路由、Prompt 模板")
public class AiController {

    private final AiConfigService aiConfigService;

    // ---------------- 厂商 ----------------

    @GetMapping("/provider/list")
    @Operation(summary = "厂商列表（Key 已脱敏）")
    public Result<List<AiDto.ProviderVO>> listProviders() {
        return Result.ok(aiConfigService.listProviders());
    }

    @PostMapping("/provider")
    @Operation(summary = "新增厂商")
    public Result<AiDto.ProviderVO> createProvider(@RequestBody AiDto.ProviderSaveReq req) {
        return Result.ok(aiConfigService.create(req));
    }

    @PutMapping("/provider/{id}")
    @Operation(summary = "修改厂商（apiKey 留空则不改动）")
    public Result<AiDto.ProviderVO> updateProvider(@PathVariable Long id,
                                                   @RequestBody AiDto.ProviderSaveReq req) {
        return Result.ok(aiConfigService.update(id, req));
    }

    @DeleteMapping("/provider/{id}")
    @Operation(summary = "删除厂商（锁定项不允许删除）")
    public Result<Void> deleteProvider(@PathVariable Long id) {
        aiConfigService.delete(id);
        return Result.ok();
    }

    @PostMapping("/provider/{id}/test")
    @Operation(summary = "连通性测试（发一个真实的最小请求）")
    public Result<AiDto.TestResultVO> testProvider(@PathVariable Long id) {
        return Result.ok(aiConfigService.test(id));
    }

    @PostMapping("/provider/{id}/activate")
    @Operation(summary = "设为该能力的当前使用项")
    public Result<Void> activateProvider(@PathVariable Long id) {
        aiConfigService.activate(id);
        return Result.ok();
    }

    // ---------------- 任务路由 ----------------

    @GetMapping("/route")
    @Operation(summary = "任务路由列表")
    public Result<List<AiDto.RouteVO>> listRoutes() {
        return Result.ok(aiConfigService.listRoutes());
    }

    @PutMapping("/route")
    @Operation(summary = "保存任务路由")
    public Result<Void> saveRoute(@RequestBody AiDto.RouteSaveReq req) {
        aiConfigService.saveRoute(req);
        return Result.ok();
    }

    // ---------------- Prompt 模板 ----------------

    @GetMapping("/prompt/list")
    @Operation(summary = "Prompt 模板分组列表（含所有历史版本）")
    public Result<List<AiDto.PromptGroupVO>> listPrompts() {
        return Result.ok(aiConfigService.listPromptGroups());
    }

    @GetMapping("/prompt/{id}")
    @Operation(summary = "Prompt 模板详情（含全文）")
    public Result<AiDto.PromptVO> getPrompt(@PathVariable Long id) {
        return Result.ok(aiConfigService.getPrompt(id));
    }

    @GetMapping("/prompt/code/{code}/versions")
    @Operation(summary = "某个模板的所有版本")
    public Result<List<AiDto.PromptVO>> promptVersions(@PathVariable String code) {
        return Result.ok(aiConfigService.listPromptVersions(code));
    }

    @PutMapping("/prompt/{id}")
    @Operation(summary = "保存为新的 Prompt 版本（旧版本自动停用，可回滚）")
    public Result<AiDto.PromptVO> savePrompt(@PathVariable Long id,
                                             @RequestBody AiDto.PromptSaveReq req) {
        return Result.ok(aiConfigService.savePromptVersion(id, req));
    }

    @PostMapping("/prompt/rollback/{versionId}")
    @Operation(summary = "回滚到指定版本（生成一个新版本，历史不断链）")
    public Result<AiDto.PromptVO> rollbackPrompt(@PathVariable Long versionId) {
        return Result.ok(aiConfigService.rollback(versionId));
    }
}
