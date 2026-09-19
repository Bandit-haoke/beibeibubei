package com.beibei.controller;

import com.beibei.common.Result;
import com.beibei.config.AgentProperties;
import com.beibei.service.AgentClient;
import com.beibei.service.BackupService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.lang.management.ManagementFactory;
import java.time.Duration;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 系统接口：环境自检、备份恢复、向量一致性校验。
 */
@Slf4j
@RestController
@RequestMapping("/api/sys")
@RequiredArgsConstructor
@Tag(name = "系统", description = "环境自检、备份恢复、一致性校验")
public class SysController {

    private final AgentClient agentClient;
    private final AgentProperties agentProperties;
    private final BackupService backupService;

    // ---------------- 环境自检 ----------------

    @GetMapping("/health")
    @Operation(summary = "环境自检（Java + 智能体 全链路）")
    public Result<Map<String, Object>> health(
            @RequestParam(name = "probeLlm", defaultValue = "false") boolean probeLlm) {

        Map<String, Object> data = new LinkedHashMap<>();
        data.put("checkedAt", LocalDateTime.now().toString());
        data.put("java", javaStatus());
        data.put("agent", agentClient.health(probeLlm));

        Object agent = data.get("agent");
        boolean agentOk = agent instanceof Map<?, ?> m && Boolean.TRUE.equals(m.get("coreOk"));
        data.put("allOk", agentOk);

        return Result.ok(data);
    }

    @GetMapping("/ping")
    @Operation(summary = "存活探测")
    public Result<Map<String, Object>> ping() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("pong", true);
        data.put("service", "beibei-server");
        data.put("time", LocalDateTime.now().toString());
        return Result.ok(data);
    }

    @GetMapping("/info")
    @Operation(summary = "系统与运行时信息")
    public Result<Map<String, Object>> info() {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("javaStatus", javaStatus());
        data.put("agentBaseUrl", agentProperties.baseUrl());
        data.put("agentTimeoutSeconds", agentProperties.timeoutSeconds());
        data.put("tokenConfigured",
                agentProperties.internalToken() != null && !agentProperties.internalToken().isBlank());
        data.put("backupDir", backupService.backupDir());
        return Result.ok(data);
    }

    // ---------------- 备份 / 恢复 ----------------

    @PostMapping("/backup")
    @Operation(summary = "一键备份（业务数据 + 上传的原始资料）")
    public Result<BackupService.BackupResult> backup() {
        return Result.ok(backupService.backup());
    }

    @GetMapping("/backup/list")
    @Operation(summary = "备份文件列表")
    public Result<List<Map<String, Object>>> listBackups() {
        return Result.ok(backupService.listBackups());
    }

    @DeleteMapping("/backup/{filename}")
    @Operation(summary = "删除备份文件")
    public Result<Void> deleteBackup(@PathVariable String filename) {
        backupService.deleteBackup(filename);
        return Result.ok();
    }

    @PostMapping("/restore")
    @Operation(summary = "从备份恢复（会覆盖当前全部业务数据）")
    public Result<BackupService.RestoreResult> restore(@RequestParam String filename) {
        return Result.ok(backupService.restore(filename));
    }

    // ---------------- 一致性校验 ----------------

    @GetMapping("/consistency")
    @Operation(summary = "MySQL 分块 ↔ Milvus 向量 一致性校验")
    public Result<Map<String, Object>> consistency() {
        return Result.ok(agentClient.consistencyCheck());
    }

    @PostMapping("/consistency/repair")
    @Operation(summary = "清理 Milvus 里已经没有对应分块的孤儿向量")
    public Result<Map<String, Object>> repairConsistency() {
        return Result.ok(agentClient.repairConsistency());
    }

    // ------------------------------------------------------------------

    private Map<String, Object> javaStatus() {
        Runtime rt = Runtime.getRuntime();
        Map<String, Object> java = new LinkedHashMap<>();
        java.put("ok", true);
        java.put("version", System.getProperty("java.version"));
        java.put("vendor", System.getProperty("java.vendor"));
        java.put("pid", ProcessHandle.current().pid());
        java.put("uptimeSeconds", Duration.ofMillis(
                ManagementFactory.getRuntimeMXBean().getUptime()).toSeconds());
        java.put("heapUsedMb", (rt.totalMemory() - rt.freeMemory()) / 1024 / 1024);
        java.put("heapMaxMb", rt.maxMemory() / 1024 / 1024);
        java.put("processors", rt.availableProcessors());
        java.put("os", System.getProperty("os.name") + " " + System.getProperty("os.version"));
        return java;
    }
}
