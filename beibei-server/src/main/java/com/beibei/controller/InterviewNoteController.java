package com.beibei.controller;

import com.beibei.common.Result;
import com.beibei.dto.InterviewNoteDto;
import com.beibei.service.InterviewNoteService;
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
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

import java.util.List;

/**
 * 面经接口。挂在「模拟面试」模块下。
 *
 * <p>和简历上传一样，上传是异步的：返回 {@code taskId}，
 * 前端订阅 {@code /api/task/{taskId}/stream} 看「转写 → 分角色 → 清洗 → 成文」的进度。
 *
 * <p>注意：进度除了走 SSE，Python 侧还会把 progress/stage 写进
 * {@code bb_interview_note}，所以刷新页面也能看到当前进行到哪一步。
 */
@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
@Tag(name = "面经", description = "上传真实面试录音，自动区分面试官与候选人并整理成面经")
public class InterviewNoteController {

    private final InterviewNoteService noteService;

    @PostMapping("/interview-note/upload")
    @Operation(summary = "上传面试录音（mp3/wav/m4a/flac/opus），异步转写并整理成面经")
    public Result<InterviewNoteDto.UploadResult> upload(
            @RequestParam("file") MultipartFile file,
            @RequestParam(value = "company", required = false) String company,
            @RequestParam(value = "position", required = false) String position) {
        return Result.ok(noteService.upload(file, company, position));
    }

    @GetMapping("/interview-note/list")
    @Operation(summary = "面经列表")
    public Result<List<InterviewNoteDto.NoteVO>> list() {
        return Result.ok(noteService.list());
    }

    @GetMapping("/interview-note/{id}")
    @Operation(summary = "面经详情（逐句对话 + 问题清单 + 正文）")
    public Result<InterviewNoteDto.DetailVO> detail(@PathVariable Long id) {
        return Result.ok(noteService.detail(id));
    }

    @PutMapping("/interview-note/{id}")
    @Operation(summary = "修改标题/公司/岗位")
    public Result<InterviewNoteDto.NoteVO> update(@PathVariable Long id,
                                                  @RequestBody InterviewNoteDto.UpdateReq req) {
        return Result.ok(noteService.update(id, req));
    }

    @PostMapping("/interview-note/{id}/retry")
    @Operation(summary = "重新整理（音频还在，不用重传），返回新的 taskId")
    public Result<Long> retry(@PathVariable Long id) {
        return Result.ok(noteService.retry(id));
    }

    @DeleteMapping("/interview-note/{id}")
    @Operation(summary = "删除面经（连带删除音频文件）")
    public Result<Void> delete(@PathVariable Long id) {
        noteService.delete(id);
        return Result.ok();
    }
}
