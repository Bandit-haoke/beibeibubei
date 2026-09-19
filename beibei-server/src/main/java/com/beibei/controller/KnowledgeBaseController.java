package com.beibei.controller;

import com.beibei.common.Result;
import com.beibei.dto.KbDto;
import com.beibei.service.KnowledgeBaseService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
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

import java.util.List;

/**
 * 知识库接口。
 */
@RestController
@RequestMapping("/api/kb")
@RequiredArgsConstructor
@Tag(name = "知识库", description = "知识库（科目）的增删改查与统计")
public class KnowledgeBaseController {

    private final KnowledgeBaseService kbService;

    @GetMapping("/list")
    @Operation(summary = "知识库列表")
    public Result<List<KbDto.VO>> list(@RequestParam(required = false) String keyword) {
        return Result.ok(kbService.list(keyword));
    }

    @GetMapping("/{id}")
    @Operation(summary = "知识库详情")
    public Result<KbDto.VO> get(@PathVariable Long id) {
        return Result.ok(kbService.toVO(kbService.require(id)));
    }

    @PostMapping
    @Operation(summary = "新建知识库")
    public Result<KbDto.VO> create(@Valid @RequestBody KbDto.CreateReq req) {
        return Result.ok(kbService.toVO(kbService.create(req)));
    }

    @PutMapping("/{id}")
    @Operation(summary = "修改知识库（不允许改向量模型）")
    public Result<KbDto.VO> update(@PathVariable Long id, @RequestBody KbDto.UpdateReq req) {
        return Result.ok(kbService.update(id, req));
    }

    @DeleteMapping("/{id}")
    @Operation(summary = "删除知识库（连带文档、分块、知识点、向量分区）")
    public Result<Void> delete(@PathVariable Long id) {
        kbService.delete(id);
        return Result.ok();
    }

    @GetMapping("/{id}/stat")
    @Operation(summary = "知识库统计（掌握度雷达图数据源）")
    public Result<KbDto.StatVO> stat(@PathVariable Long id) {
        return Result.ok(kbService.stat(id));
    }

    @PostMapping("/{id}/refresh")
    @Operation(summary = "重算冗余计数")
    public Result<Void> refresh(@PathVariable Long id) {
        kbService.refreshCounters(id);
        return Result.ok();
    }
}
