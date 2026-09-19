package com.beibei.service;

import com.beibei.common.BusinessException;
import com.beibei.config.UploadProperties;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Stream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;
import java.util.zip.ZipOutputStream;

/**
 * 数据备份与恢复。
 *
 * <p><b>不用 mysqldump</b>：宿主机上没有 MySQL 客户端，虚拟机里有但不方便编排。
 * 改成「读出所有 bb_ 表 → 写成一个 JSON + 打包上传目录 → 存成 zip」，
 * 这样备份文件自带数据与原始资料，换台机器也能恢复。
 *
 * <p>向量库**不进备份**：Milvus 里的向量可以从 MySQL 的分块重新算出来，
 * 备份它只会让文件膨胀好几倍。恢复后跑一次「重新解析」即可。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class BackupService {

    /** 备份要覆盖的表，顺序无所谓（恢复时先全清再插） */
    private static final List<String> TABLES = List.of(
            "bb_user", "bb_knowledge_base", "bb_document", "bb_doc_chunk", "bb_tag",
            "bb_chunk_tag", "bb_question", "bb_question_option", "bb_question_tag",
            "bb_paper", "bb_paper_item", "bb_exam_record", "bb_answer_item",
            "bb_mistake", "bb_review_log", "bb_ai_provider", "bb_model_route",
            "bb_prompt_template", "bb_async_task", "bb_setting"
    );

    private static final DateTimeFormatter STAMP = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss");

    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;
    private final UploadProperties uploadProperties;

    @Value("${beibei.storage.backup-dir:D:/beibei-data/backup}")
    private String backupDir;

    // ------------------------------------------------------------------
    //  备份
    // ------------------------------------------------------------------

    public record BackupResult(String filename, String path, long sizeBytes, int tableCount,
                               long rowCount, int fileCount) {
    }

    public BackupResult backup() {
        Path dir = Paths.get(backupDir);
        try {
            Files.createDirectories(dir);
        } catch (IOException e) {
            throw new BusinessException("无法创建备份目录：" + backupDir);
        }

        Map<String, List<Map<String, Object>>> dump = new LinkedHashMap<>();
        long rows = 0;
        for (String table : TABLES) {
            try {
                List<Map<String, Object>> data = jdbc.queryForList("SELECT * FROM `" + table + "`");
                dump.put(table, data);
                rows += data.size();
            } catch (Exception e) {
                // 表不存在（比如版本升级新增的）不应该让整个备份失败
                log.warn("表 {} 读取失败，跳过：{}", table, e.getMessage());
            }
        }

        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("app", "背备不悲");
        meta.put("version", "0.1.0");
        meta.put("createdAt", LocalDateTime.now().toString());
        meta.put("tableCount", dump.size());
        meta.put("rowCount", rows);
        meta.put("schemaVersion", 1);

        String filename = "beibei-backup-" + LocalDateTime.now().format(STAMP) + ".zip";
        Path target = dir.resolve(filename);

        int fileCount = 0;
        try (ZipOutputStream zos = new ZipOutputStream(Files.newOutputStream(target))) {
            zos.putNextEntry(new ZipEntry("manifest.json"));
            zos.write(objectMapper.writerWithDefaultPrettyPrinter()
                    .writeValueAsBytes(meta));
            zos.closeEntry();

            zos.putNextEntry(new ZipEntry("data.json"));
            zos.write(objectMapper.writerWithDefaultPrettyPrinter()
                    .writeValueAsBytes(dump));
            zos.closeEntry();

            // 上传的原始资料也一起打包，否则恢复后文档只有记录没有文件
            Path uploadRoot = Paths.get(uploadProperties.dir());
            if (Files.isDirectory(uploadRoot)) {
                List<Path> files;
                try (Stream<Path> stream = Files.walk(uploadRoot)) {
                    files = stream.filter(Files::isRegularFile).toList();
                }
                for (Path file : files) {
                    String entryName = "upload/" + uploadRoot.relativize(file)
                            .toString().replace('\\', '/');
                    zos.putNextEntry(new ZipEntry(entryName));
                    Files.copy(file, zos);
                    zos.closeEntry();
                    fileCount++;
                }
            }
        } catch (IOException e) {
            throw new BusinessException("写备份文件失败：" + e.getMessage());
        }

        long size;
        try {
            size = Files.size(target);
        } catch (IOException e) {
            size = 0;
        }

        log.info("备份完成：{}（{} 张表 / {} 行 / {} 个文件 / {} KB）",
                filename, dump.size(), rows, fileCount, size / 1024);
        return new BackupResult(filename, target.toString(), size, dump.size(), rows, fileCount);
    }

    public List<Map<String, Object>> listBackups() {
        Path dir = Paths.get(backupDir);
        List<Map<String, Object>> out = new ArrayList<>();
        if (!Files.isDirectory(dir)) {
            return out;
        }
        try (Stream<Path> stream = Files.list(dir)) {
            stream.filter(p -> p.getFileName().toString().endsWith(".zip"))
                    .sorted((a, b) -> b.getFileName().toString().compareTo(a.getFileName().toString()))
                    .forEach(p -> {
                        Map<String, Object> row = new LinkedHashMap<>();
                        row.put("filename", p.getFileName().toString());
                        row.put("path", p.toString());
                        try {
                            row.put("sizeBytes", Files.size(p));
                            row.put("modifiedAt", Files.getLastModifiedTime(p).toString());
                        } catch (IOException e) {
                            row.put("sizeBytes", 0);
                        }
                        out.add(row);
                    });
        } catch (IOException e) {
            log.warn("列出备份失败：{}", e.getMessage());
        }
        return out;
    }

    public void deleteBackup(String filename) {
        Path file = safeResolve(filename);
        try {
            Files.deleteIfExists(file);
            log.info("已删除备份 {}", filename);
        } catch (IOException e) {
            throw new BusinessException("删除备份失败：" + e.getMessage());
        }
    }

    // ------------------------------------------------------------------
    //  恢复
    // ------------------------------------------------------------------

    public record RestoreResult(int tableCount, long rowCount, int fileCount) {
    }

    @Transactional(rollbackFor = Exception.class)
    public RestoreResult restore(String filename) {
        Path file = safeResolve(filename);
        if (!Files.isRegularFile(file)) {
            throw new BusinessException("备份文件不存在：" + filename);
        }

        Map<String, List<Map<String, Object>>> dump = null;
        int fileCount = 0;

        try (ZipInputStream zis = new ZipInputStream(Files.newInputStream(file))) {
            ZipEntry entry;
            byte[] buffer = new byte[8192];
            while ((entry = zis.getNextEntry()) != null) {
                if ("data.json".equals(entry.getName())) {
                    dump = objectMapper.readValue(zis.readAllBytes(),
                            new TypeReference<Map<String, List<Map<String, Object>>>>() {
                            });
                } else if (entry.getName().startsWith("upload/") && !entry.isDirectory()) {
                    Path out = Paths.get(uploadProperties.dir())
                            .resolve(entry.getName().substring("upload/".length()));
                    Files.createDirectories(out.getParent());
                    Files.copy(zis, out, java.nio.file.StandardCopyOption.REPLACE_EXISTING);
                    fileCount++;
                }
                zis.closeEntry();
            }
        } catch (IOException e) {
            throw new BusinessException("读取备份文件失败：" + e.getMessage());
        }

        if (dump == null || dump.isEmpty()) {
            throw new BusinessException("备份文件里没有数据（缺少 data.json）");
        }

        // 先清空再插入。顺序上先删子表再删主表，避免逻辑外键错乱
        long rows = 0;
        List<String> reversed = new ArrayList<>(TABLES);
        java.util.Collections.reverse(reversed);

        jdbc.execute("SET FOREIGN_KEY_CHECKS = 0");
        try {
            for (String table : reversed) {
                if (tableExists(table)) {
                    jdbc.execute("DELETE FROM `" + table + "`");
                }
            }
            for (String table : TABLES) {
                List<Map<String, Object>> data = dump.get(table);
                if (data == null || data.isEmpty() || !tableExists(table)) {
                    continue;
                }
                rows += insertRows(table, data);
            }
        } finally {
            jdbc.execute("SET FOREIGN_KEY_CHECKS = 1");
        }

        log.info("恢复完成：{}（{} 张表 / {} 行 / {} 个文件）", filename, dump.size(), rows, fileCount);
        return new RestoreResult(dump.size(), rows, fileCount);
    }

    private int insertRows(String table, List<Map<String, Object>> rows) {
        if (rows.isEmpty()) {
            return 0;
        }
        List<String> columns = new ArrayList<>(rows.get(0).keySet());
        String columnList = String.join("`, `", columns);
        String placeholders = String.join(", ", columns.stream().map(c -> "?").toList());
        String sql = "INSERT INTO `" + table + "` (`" + columnList + "`) VALUES (" + placeholders + ")";

        List<Object[]> batch = new ArrayList<>(rows.size());
        for (Map<String, Object> row : rows) {
            Object[] values = new Object[columns.size()];
            for (int i = 0; i < columns.size(); i++) {
                Object v = row.get(columns.get(i));
                // JSON 列在 dump 里可能是 Map/List，要转回字符串
                if (v instanceof Map || v instanceof List) {
                    try {
                        v = objectMapper.writeValueAsString(v);
                    } catch (Exception ignored) {
                        v = null;
                    }
                }
                values[i] = v;
            }
            batch.add(values);
        }
        jdbc.batchUpdate(sql, batch);
        return batch.size();
    }

    private boolean tableExists(String table) {
        try {
            Integer n = jdbc.queryForObject(
                    "SELECT COUNT(*) FROM information_schema.TABLES "
                            + "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = ?",
                    Integer.class, table);
            return n != null && n > 0;
        } catch (Exception e) {
            return false;
        }
    }

    /** 防止 ../ 之类的路径穿越 */
    private Path safeResolve(String filename) {
        if (filename == null || filename.isBlank()
                || filename.contains("..") || filename.contains("/") || filename.contains("\\")) {
            throw BusinessException.invalid("非法的备份文件名");
        }
        return Paths.get(backupDir).resolve(filename);
    }

    /** 备份目录（前端展示用） */
    public String backupDir() {
        return backupDir;
    }
}
