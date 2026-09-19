package com.beibei.controller;

import com.beibei.common.Result;
import com.beibei.dto.InterviewDto;
import com.beibei.service.InterviewService;
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
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * AI 模拟面试接口。
 *
 * <p>分两段：
 * <ul>
 *   <li><b>简历库</b> {@code /api/resume/*} —— 上传是异步的，返回 taskId，
 *       前端订阅 {@code /api/task/{taskId}/stream} 看解析进度；</li>
 *   <li><b>面试</b> {@code /api/interview/*} —— 每轮问答同步返回，
 *       一轮就是一次大模型调用，几秒钟。</li>
 * </ul>
 *
 * <p>最后的 {@code /linkage-paper} 是本模块与学习模块唯一的连接点：
 * 把报告里的薄弱知识点变成一张专项题卷。
 */
@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
@Tag(name = "AI 模拟面试", description = "简历库、面试对话、评估报告、薄弱点出题")
public class InterviewController {

    private final InterviewService interviewService;

    // ------------------------------------------------------------------
    //  简历库
    // ------------------------------------------------------------------

    @PostMapping("/resume/upload")
    @Operation(summary = "上传简历（PDF/Word，异步解析抽取档案）")
    public Result<InterviewDto.ResumeUploadResult> uploadResume(
            @RequestParam("file") MultipartFile file) {
        return Result.ok(interviewService.uploadResume(file));
    }

    @PostMapping("/resume/paste")
    @Operation(summary = "手动粘贴简历文字")
    public Result<InterviewDto.ResumeUploadResult> pasteResume(
            @RequestBody InterviewDto.ResumePasteReq req) {
        return Result.ok(interviewService.pasteResume(req));
    }

    @PostMapping("/resume/{id}/reparse")
    @Operation(summary = "重新解析简历，返回 taskId")
    public Result<Long> reparseResume(@PathVariable Long id) {
        return Result.ok(interviewService.reparseResume(id));
    }

    @GetMapping("/resume/list")
    @Operation(summary = "简历列表")
    public Result<List<InterviewDto.ResumeVO>> listResumes() {
        return Result.ok(interviewService.listResumes());
    }

    @GetMapping("/resume/{id}")
    @Operation(summary = "简历详情（结构化档案 + 原文，便于人工核对）")
    public Result<InterviewDto.ResumeDetailVO> resumeDetail(@PathVariable Long id) {
        return Result.ok(interviewService.resumeDetail(id));
    }

    @DeleteMapping("/resume/{id}")
    @Operation(summary = "删除简历（连带它的所有面试场次）")
    public Result<Void> deleteResume(@PathVariable Long id) {
        interviewService.deleteResume(id);
        return Result.ok();
    }

    // ------------------------------------------------------------------
    //  面试
    // ------------------------------------------------------------------

    @PostMapping("/interview/start")
    @Operation(summary = "开始一场模拟面试，同步返回第一题")
    public Result<InterviewDto.StartVO> start(@Valid @RequestBody InterviewDto.StartReq req) {
        return Result.ok(interviewService.startInterview(req));
    }

    @PostMapping("/interview/{id}/answer")
    @Operation(summary = "提交一轮回答：评分 + 追问")
    public Result<InterviewDto.AnswerVO> answer(@PathVariable Long id,
                                                @RequestBody InterviewDto.AnswerReq req) {
        return Result.ok(interviewService.answer(id, req));
    }

    @PostMapping("/interview/{id}/finish")
    @Operation(summary = "结束面试并生成评估报告")
    public Result<InterviewDto.DetailVO> finish(@PathVariable Long id) {
        return Result.ok(interviewService.finish(id));
    }

    @GetMapping("/interview/list")
    @Operation(summary = "面试场次列表")
    public Result<List<InterviewDto.InterviewVO>> listInterviews() {
        return Result.ok(interviewService.listInterviews());
    }

    @GetMapping("/interview/{id}")
    @Operation(summary = "面试详情（完整对话 + 报告）")
    public Result<InterviewDto.DetailVO> detail(@PathVariable Long id) {
        return Result.ok(interviewService.detail(id));
    }

    @DeleteMapping("/interview/{id}")
    @Operation(summary = "删除面试场次")
    public Result<Void> deleteInterview(@PathVariable Long id) {
        interviewService.deleteInterview(id);
        return Result.ok();
    }

    // ------------------------------------------------------------------
    //  联动学习模块
    // ------------------------------------------------------------------

    @PostMapping("/interview/{id}/linkage-paper")
    @Operation(summary = "按报告里的薄弱知识点生成专项题卷，返回 paperId + taskId")
    public Result<InterviewDto.LinkageVO> linkagePaper(@PathVariable Long id,
                                                       @Valid @RequestBody InterviewDto.LinkageReq req) {
        return Result.ok(interviewService.createLinkagePaper(id, req));
    }
}
