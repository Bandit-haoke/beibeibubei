package com.beibei.controller;

import com.beibei.common.Result;
import com.beibei.dto.ExamDto;
import com.beibei.service.ExamService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 答题与判分接口。
 *
 * <p>交卷后判分是异步的：POST 立刻返回 taskId，
 * 前端订阅 {@code /api/task/{taskId}/stream} 看判分进度。
 */
@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
@Tag(name = "答题与判分", description = "开始作答、存草稿、交卷判分、查看结果、申诉重判")
public class ExamController {

    private final ExamService examService;

    @PostMapping("/exam/start")
    @Operation(summary = "开始作答（为每道题预建作答记录，支持断点续答）")
    public Result<ExamDto.StartVO> start(@Valid @RequestBody ExamDto.StartReq req) {
        return Result.ok(examService.start(req));
    }

    @GetMapping("/exam/list")
    @Operation(summary = "答卷列表")
    public Result<List<ExamDto.ExamVO>> list(@RequestParam(required = false) Long kbId) {
        return Result.ok(examService.list(kbId));
    }

    @PostMapping("/exam/{id}/save-draft")
    @Operation(summary = "自动存草稿")
    public Result<Void> saveDraft(@PathVariable Long id, @RequestBody ExamDto.SaveDraftReq req) {
        examService.saveDraft(id, req);
        return Result.ok();
    }

    @PostMapping("/exam/{id}/submit")
    @Operation(summary = "交卷并触发判分，返回 taskId")
    public Result<Long> submit(@PathVariable Long id, @RequestBody ExamDto.SubmitReq req) {
        return Result.ok(examService.submit(id, req));
    }

    @GetMapping("/exam/{id}/result")
    @Operation(summary = "判分结果（含命中/遗漏要点与原文引用）")
    public Result<ExamDto.ResultVO> result(@PathVariable Long id) {
        return Result.ok(examService.result(id));
    }

    @PostMapping("/answer/{answerItemId}/appeal")
    @Operation(summary = "申诉重判单题，返回 taskId")
    public Result<Long> appeal(@PathVariable Long answerItemId,
                               @RequestBody ExamDto.AppealReq req) {
        return Result.ok(examService.appeal(answerItemId, req == null ? "" : req.reason()));
    }
}
