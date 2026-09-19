package com.beibei.controller;

import com.beibei.common.Result;
import com.beibei.dto.TaskDto;
import com.beibei.service.AsyncTaskService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

/**
 * 异步任务接口。
 *
 * <p>前端拿进度有两种方式：
 * <ul>
 *   <li>SSE：{@code GET /api/task/{id}/stream} —— 实时，优先用</li>
 *   <li>轮询：{@code GET /api/task/{id}} —— SSE 不可用时的兜底</li>
 * </ul>
 *
 * <p>SSE 事件：{@code progress} / {@code done} / {@code error}，
 * data 是 JSON，字段与 {@link TaskDto.VO} 对齐。
 */
@RestController
@RequestMapping("/api/task")
@RequiredArgsConstructor
@Tag(name = "异步任务", description = "解析/出题/判分等长任务的进度查询")
public class TaskController {

    private final AsyncTaskService taskService;

    @GetMapping("/{id}")
    @Operation(summary = "查询任务状态（轮询兜底）")
    public Result<TaskDto.VO> get(@PathVariable Long id) {
        return Result.ok(taskService.toVO(taskService.get(id)));
    }

    @GetMapping(value = "/{id}/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    @Operation(summary = "订阅任务进度（SSE）")
    public SseEmitter stream(@PathVariable Long id) {
        return taskService.subscribe(id);
    }
}
