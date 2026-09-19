package com.beibei.service;

import com.beibei.dto.TaskDto;
import com.beibei.entity.AsyncTask;
import com.beibei.mapper.AsyncTaskMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CopyOnWriteArrayList;

/**
 * 异步任务的生命周期管理 + SSE 进度推送。
 *
 * <p>前端流程：
 * <pre>
 *   POST /api/doc/upload          → 返回 taskId
 *   GET  /api/task/{taskId}/stream  → SSE，收 progress / done / error 事件
 * </pre>
 *
 * <p>设计取舍：这是单用户本地部署，用进程内的 Map 存 emitter 就够，
 * 不引入 Redis 发布订阅。Java 重启后正在跑的任务会丢推送，前端可以靠轮询兜底。
 */
@Slf4j
@Service
public class AsyncTaskService {

    /** SSE 连接最长存活时间：1 小时，够跑完超长文档的解析 */
    private static final long SSE_TIMEOUT_MS = 60 * 60 * 1000L;

    private final AsyncTaskMapper taskMapper;
    private final ObjectMapper objectMapper;

    /** taskId -> 订阅者列表 */
    private final Map<Long, List<SseEmitter>> subscribers = new ConcurrentHashMap<>();

    public AsyncTaskService(AsyncTaskMapper taskMapper, ObjectMapper objectMapper) {
        this.taskMapper = taskMapper;
        this.objectMapper = objectMapper;
    }

    // ------------------------------------------------------------------
    //  任务生命周期
    // ------------------------------------------------------------------

    public AsyncTask create(String taskType, Long bizId, Long userId) {
        AsyncTask task = new AsyncTask();
        task.setTaskType(taskType);
        task.setBizId(bizId == null ? 0L : bizId);
        task.setUserId(userId == null ? 1L : userId);
        task.setStatus(AsyncTask.STATUS_PENDING);
        task.setProgress(0);
        task.setStage("排队中");
        task.setMessage("");
        task.setErrorMsg("");
        taskMapper.insert(task);
        log.info("创建异步任务 #{} type={} bizId={}", task.getId(), taskType, bizId);
        return task;
    }

    public void running(Long taskId, String stage) {
        update(taskId, t -> {
            t.setStatus(AsyncTask.STATUS_RUNNING);
            t.setStage(stage);
            if (t.getStartedAt() == null) {
                t.setStartedAt(LocalDateTime.now());
            }
        });
        pushProgress(taskId);
    }

    public void progress(Long taskId, int progress, String stage) {
        int clamped = Math.max(0, Math.min(100, progress));
        update(taskId, t -> {
            t.setStatus(AsyncTask.STATUS_RUNNING);
            t.setProgress(clamped);
            if (stage != null && !stage.isBlank()) {
                t.setStage(stage);
            }
            if (t.getStartedAt() == null) {
                t.setStartedAt(LocalDateTime.now());
            }
        });
        pushProgress(taskId);
    }

    public void success(Long taskId, Object result) {
        String json = toJson(result);
        update(taskId, t -> {
            t.setStatus(AsyncTask.STATUS_SUCCESS);
            t.setProgress(100);
            t.setStage("已完成");
            t.setResultJson(json);
            t.setFinishedAt(LocalDateTime.now());
        });
        emitDone(taskId, json);
    }

    public void fail(Long taskId, String errorMsg) {
        String msg = errorMsg == null ? "未知错误" : errorMsg;
        if (msg.length() > 1900) {
            msg = msg.substring(0, 1900) + " ...";
        }
        String finalMsg = msg;
        update(taskId, t -> {
            t.setStatus(AsyncTask.STATUS_FAILED);
            t.setErrorMsg(finalMsg);
            t.setStage("失败：" + finalMsg);
            t.setFinishedAt(LocalDateTime.now());
        });
        emitError(taskId, finalMsg);
    }

    public AsyncTask get(Long taskId) {
        return taskMapper.selectById(taskId);
    }

    public TaskDto.VO toVO(AsyncTask t) {
        if (t == null) {
            return null;
        }
        return new TaskDto.VO(
                t.getId(), t.getTaskType(), t.getBizId(), t.getStatus(), t.getProgress(),
                t.getStage(), t.getMessage(), t.getResultJson(), t.getErrorMsg(),
                t.getStartedAt(), t.getFinishedAt(), t.getCreatedAt()
        );
    }

    private void update(Long taskId, java.util.function.Consumer<AsyncTask> mutator) {
        AsyncTask t = taskMapper.selectById(taskId);
        if (t == null) {
            log.warn("任务 #{} 不存在，跳过状态更新", taskId);
            return;
        }
        mutator.accept(t);
        taskMapper.updateById(t);
    }

    // ------------------------------------------------------------------
    //  SSE 订阅
    // ------------------------------------------------------------------

    public SseEmitter subscribe(Long taskId) {
        SseEmitter emitter = new SseEmitter(SSE_TIMEOUT_MS);

        emitter.onCompletion(() -> remove(taskId, emitter));
        emitter.onTimeout(() -> {
            log.debug("任务 #{} 的 SSE 连接超时关闭", taskId);
            remove(taskId, emitter);
            emitter.complete();
        });
        emitter.onError(e -> remove(taskId, emitter));

        AsyncTask task = get(taskId);
        if (task == null) {
            try {
                emitter.send(SseEmitter.event().name("error")
                        .data(Map.of("taskId", taskId, "errorMsg", "任务不存在")));
            } catch (IOException ignored) {
                // 客户端已断开
            }
            emitter.complete();
            return emitter;
        }

        // 已经结束的任务，直接把终态发出去并关闭
        if (task.getStatus() == AsyncTask.STATUS_SUCCESS || task.getStatus() == AsyncTask.STATUS_FAILED) {
            try {
                emitter.send(SseEmitter.event().name("progress").data(snapshot(task)));
                if (task.getStatus() == AsyncTask.STATUS_SUCCESS) {
                    emitter.send(SseEmitter.event().name("done").data(snapshot(task)));
                } else {
                    emitter.send(SseEmitter.event().name("error").data(snapshot(task)));
                }
            } catch (IOException ignored) {
                // 忽略
            }
            emitter.complete();
            return emitter;
        }

        subscribers.computeIfAbsent(taskId, k -> new CopyOnWriteArrayList<>()).add(emitter);
        try {
            emitter.send(SseEmitter.event().name("progress").data(snapshot(task)));
        } catch (IOException e) {
            remove(taskId, emitter);
        }
        log.debug("任务 #{} 新增 SSE 订阅者，当前 {} 个", taskId, subscribers.getOrDefault(taskId, List.of()).size());
        return emitter;
    }

    private void pushProgress(Long taskId) {
        AsyncTask task = get(taskId);
        if (task == null) {
            return;
        }
        broadcast(taskId, "progress", snapshot(task));
    }

    private void emitDone(Long taskId, String resultJson) {
        AsyncTask task = get(taskId);
        if (task == null) {
            return;
        }
        Map<String, Object> payload = snapshot(task);
        payload.put("result", parseJson(resultJson));
        broadcast(taskId, "done", payload);
        completeAll(taskId);
    }

    private void emitError(Long taskId, String errorMsg) {
        AsyncTask task = get(taskId);
        Map<String, Object> payload = task == null
                ? Map.of("taskId", taskId, "errorMsg", errorMsg)
                : snapshot(task);
        broadcast(taskId, "error", payload);
        completeAll(taskId);
    }

    private Map<String, Object> snapshot(AsyncTask t) {
        Map<String, Object> m = new java.util.LinkedHashMap<>();
        m.put("taskId", t.getId());
        m.put("taskType", t.getTaskType());
        m.put("bizId", t.getBizId());
        m.put("status", t.getStatus());
        m.put("progress", t.getProgress());
        m.put("stage", t.getStage() == null ? "" : t.getStage());
        m.put("errorMsg", t.getErrorMsg() == null ? "" : t.getErrorMsg());
        return m;
    }

    private void broadcast(Long taskId, String event, Object data) {
        List<SseEmitter> list = subscribers.get(taskId);
        if (list == null || list.isEmpty()) {
            return;
        }
        for (SseEmitter emitter : list) {
            try {
                emitter.send(SseEmitter.event().name(event).data(data));
            } catch (Exception e) {
                // 客户端已断开
                remove(taskId, emitter);
            }
        }
    }

    private void completeAll(Long taskId) {
        List<SseEmitter> list = subscribers.remove(taskId);
        if (list == null) {
            return;
        }
        for (SseEmitter emitter : list) {
            try {
                emitter.complete();
            } catch (Exception ignored) {
                // 忽略
            }
        }
    }

    private void remove(Long taskId, SseEmitter emitter) {
        List<SseEmitter> list = subscribers.get(taskId);
        if (list != null) {
            list.remove(emitter);
            if (list.isEmpty()) {
                subscribers.remove(taskId);
            }
        }
    }

    private String toJson(Object o) {
        if (o == null) {
            return null;
        }
        if (o instanceof String s) {
            return s;
        }
        try {
            return objectMapper.writeValueAsString(o);
        } catch (Exception e) {
            log.warn("结果序列化失败: {}", e.getMessage());
            return null;
        }
    }

    private Object parseJson(String json) {
        if (json == null || json.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readValue(json, Object.class);
        } catch (Exception e) {
            return json;
        }
    }
}
