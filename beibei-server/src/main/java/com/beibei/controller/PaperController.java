package com.beibei.controller;

import com.beibei.common.Result;
import com.beibei.dto.PaperDto;
import com.beibei.service.PaperService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 题卷接口：AI 出题、审核、管理。
 *
 * <p>出题是异步的：POST 立刻返回 paperId + taskId，
 * 前端订阅 {@code /api/task/{taskId}/stream} 看生成进度。
 */
@RestController
@RequestMapping("/api/paper")
@RequiredArgsConstructor
@Tag(name = "题卷", description = "AI 出题、审核发布、题卷管理")
public class PaperController {

    private final PaperService paperService;

    @PostMapping("/generate")
    @Operation(summary = "AI 出题（异步，返回 paperId + taskId）")
    public Result<PaperDto.GenerateResult> generate(@Valid @RequestBody PaperDto.GenerateReq req) {
        return Result.ok(paperService.generate(req));
    }

    @GetMapping("/list")
    @Operation(summary = "题卷列表")
    public Result<List<PaperDto.VO>> list(@RequestParam(required = false) Long kbId) {
        return Result.ok(paperService.list(kbId));
    }

    @GetMapping("/{id}")
    @Operation(summary = "题卷详情（含全部题目）")
    public Result<PaperDto.DetailVO> detail(@PathVariable Long id) {
        return Result.ok(paperService.detail(id, false));
    }

    @GetMapping("/{id}/review")
    @Operation(summary = "审核视图（只返回待审的草稿题）")
    public Result<PaperDto.DetailVO> review(@PathVariable Long id) {
        return Result.ok(paperService.detail(id, true));
    }

    @PostMapping("/{id}/approve-all")
    @Operation(summary = "整卷通过审核")
    public Result<Integer> approveAll(@PathVariable Long id) {
        return Result.ok(paperService.approveAll(id));
    }

    @PostMapping("/{id}/regenerate")
    @Operation(summary = "重新出题（清掉本卷草稿后重跑）")
    public Result<PaperDto.GenerateResult> regenerate(
            @PathVariable Long id,
            @RequestParam(required = false) Integer count,
            @RequestParam(required = false, defaultValue = "true") Boolean selfCheck) {
        return Result.ok(paperService.regenerate(id, count, selfCheck));
    }

    @DeleteMapping("/{id}")
    @Operation(summary = "删除题卷")
    public Result<Void> delete(
            @PathVariable Long id,
            @RequestParam(defaultValue = "true") boolean withQuestions) {
        paperService.delete(id, withQuestions);
        return Result.ok();
    }
}
