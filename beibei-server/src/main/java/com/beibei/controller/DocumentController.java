package com.beibei.controller;

import com.beibei.common.PageResult;
import com.beibei.common.Result;
import com.beibei.dto.DocDto;
import com.beibei.entity.Document;
import com.beibei.service.DocumentService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
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
 * 文档接口：上传 → 解析入库 → 查看分块。
 *
 * <p>上传是异步的：立刻返回 taskId，前端订阅 {@code /api/task/{taskId}/stream} 拿进度。
 */
@Slf4j
@RestController
@RequestMapping("/api/doc")
@RequiredArgsConstructor
@Tag(name = "文档", description = "上传、解析、分块查看")
public class DocumentController {

    private final DocumentService documentService;

    @PostMapping("/upload")
    @Operation(summary = "上传文件（支持多选，异步解析）")
    public Result<List<DocumentService.UploadResult>> upload(
            @RequestParam Long kbId,
            @RequestParam("files") MultipartFile[] files) {
        return Result.ok(documentService.upload(kbId, files, Document.SOURCE_FILE));
    }

    @PostMapping("/upload-image")
    @Operation(summary = "上传照片（走 OCR，支持多图合并为一个文档）")
    public Result<List<DocumentService.UploadResult>> uploadImage(
            @RequestParam Long kbId,
            @RequestParam("files") MultipartFile[] files) {
        return Result.ok(documentService.upload(kbId, files, Document.SOURCE_IMAGE));
    }

    @PostMapping("/paste")
    @Operation(summary = "手动粘贴文本入库")
    public Result<DocumentService.UploadResult> paste(@RequestBody DocDto.PasteReq req) {
        return Result.ok(documentService.paste(req));
    }

    @GetMapping("/list")
    @Operation(summary = "文档列表")
    public Result<PageResult<DocDto.VO>> list(
            @RequestParam(required = false) Long kbId,
            @RequestParam(required = false) Integer status,
            @RequestParam(required = false) String keyword,
            @RequestParam(defaultValue = "1") long pageNum,
            @RequestParam(defaultValue = "20") long pageSize) {
        return Result.ok(documentService.list(kbId, status, keyword, pageNum, pageSize));
    }

    @GetMapping("/{id}")
    @Operation(summary = "文档详情（含分块预览与知识点列表）")
    public Result<DocDto.DetailVO> detail(
            @PathVariable Long id,
            @RequestParam(defaultValue = "50") int chunkLimit) {
        return Result.ok(documentService.detail(id, chunkLimit));
    }

    @GetMapping("/{id}/chunks")
    @Operation(summary = "文档分块分页列表")
    public Result<PageResult<DocDto.ChunkVO>> chunks(
            @PathVariable Long id,
            @RequestParam(defaultValue = "1") long pageNum,
            @RequestParam(defaultValue = "20") long pageSize) {
        return Result.ok(documentService.chunkPage(id, pageNum, pageSize));
    }

    @DeleteMapping("/{id}")
    @Operation(summary = "删除文档（连带分块与向量）")
    public Result<Void> delete(@PathVariable Long id) {
        documentService.delete(id);
        return Result.ok();
    }

    @PostMapping("/{id}/reindex")
    @Operation(summary = "重新解析入库")
    public Result<Long> reindex(@PathVariable Long id) {
        return Result.ok(documentService.reindex(id));
    }
}
