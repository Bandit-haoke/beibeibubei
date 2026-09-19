package com.beibei.controller;

import com.beibei.common.PageResult;
import com.beibei.common.Result;
import com.beibei.dto.QuestionDto;
import com.beibei.service.ExportService;
import com.beibei.service.KnowledgeBaseService;
import com.beibei.service.QuestionService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;

/**
 * 题库接口。
 */
@RestController
@RequestMapping("/api/question")
@RequiredArgsConstructor
@Tag(name = "题库", description = "题目的查询、编辑、审核、手动录入与导出")
public class QuestionController {

    private final QuestionService questionService;
    private final KnowledgeBaseService kbService;
    private final ExportService exportService;

    @GetMapping("/list")
    @Operation(summary = "题库分页查询")
    public Result<PageResult<QuestionDto.VO>> list(
            @RequestParam(required = false) Long kbId,
            @RequestParam(required = false) Integer status,
            @RequestParam(required = false) Integer qType,
            @RequestParam(required = false) Integer difficulty,
            @RequestParam(required = false) Long tagId,
            @RequestParam(required = false) String keyword,
            @RequestParam(defaultValue = "1") long pageNum,
            @RequestParam(defaultValue = "20") long pageSize) {
        return Result.ok(questionService.list(kbId, status, qType, difficulty, tagId, keyword,
                pageNum, pageSize));
    }

    @GetMapping("/meta")
    @Operation(summary = "题型与难度字典")
    public Result<Map<String, Object>> meta() {
        return Result.ok(Map.of(
                "qTypes", List.of(
                        Map.of("value", 1, "label", "单选题"),
                        Map.of("value", 2, "label", "多选题"),
                        Map.of("value", 3, "label", "判断题"),
                        Map.of("value", 4, "label", "填空题"),
                        Map.of("value", 5, "label", "名词解释"),
                        Map.of("value", 6, "label", "简答题"),
                        Map.of("value", 7, "label", "论述题"),
                        Map.of("value", 8, "label", "代码题"),
                        Map.of("value", 9, "label", "对比辨析")
                ),
                "difficulties", List.of(
                        Map.of("value", 1, "label", "易"),
                        Map.of("value", 2, "label", "中"),
                        Map.of("value", 3, "label", "难")
                ),
                "statuses", List.of(
                        Map.of("value", 0, "label", "待审"),
                        Map.of("value", 1, "label", "已发布"),
                        Map.of("value", 2, "label", "已停用")
                )
        ));
    }

    @GetMapping("/{id}")
    @Operation(summary = "题目详情")
    public Result<QuestionDto.VO> detail(@PathVariable Long id) {
        return Result.ok(questionService.detail(id));
    }

    @PutMapping("/{id}")
    @Operation(summary = "编辑题目")
    public Result<Void> update(@PathVariable Long id, @RequestBody QuestionDto.UpdateReq req) {
        questionService.update(id, req);
        return Result.ok();
    }

    @PostMapping("/approve")
    @Operation(summary = "审核通过（批量）")
    public Result<Integer> approve(@RequestBody QuestionDto.ApproveReq req) {
        return Result.ok(questionService.approve(req.questionIds()));
    }

    @PostMapping("/{id}/disable")
    @Operation(summary = "停用题目")
    public Result<Void> disable(@PathVariable Long id) {
        questionService.disable(id);
        return Result.ok();
    }

    @PostMapping("/manual")
    @Operation(summary = "手动新增题目（直接发布）")
    public Result<Long> manual(@Valid @RequestBody QuestionDto.ManualReq req) {
        return Result.ok(questionService.create(req));
    }

    @DeleteMapping("/{id}")
    @Operation(summary = "删除题目")
    public Result<Void> delete(@PathVariable Long id) {
        questionService.delete(id);
        return Result.ok();
    }

    // ------------------------------------------------------------------
    //  导出
    // ------------------------------------------------------------------

    @GetMapping("/export")
    @Operation(summary = "导出题库（anki / csv / json）")
    public ResponseEntity<byte[]> export(
            @RequestParam(required = false) Long kbId,
            @RequestParam(required = false) Integer status,
            @RequestParam(defaultValue = "anki") String format) {

        String kbName = kbId == null ? "全部题库" : kbService.nameOf(kbId);
        ExportService.ExportFile file = exportService.exportQuestions(kbId, status, format, kbName);

        String encodedName;
        try {
            encodedName = URLEncoder.encode(file.filename(), StandardCharsets.UTF_8)
                    .replace("+", "%20");
        } catch (Exception e) {
            encodedName = "questions.txt";
        }

        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION,
                        "attachment; filename*=UTF-8''" + encodedName)
                .header(HttpHeaders.CACHE_CONTROL, "no-cache")
                .contentType(MediaType.parseMediaType(file.contentType() + ";charset=UTF-8"))
                .body(file.content());
    }
}
