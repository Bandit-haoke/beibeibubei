package com.beibei.service;

import com.beibei.common.BusinessException;
import com.beibei.config.UploadProperties;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.nio.file.StandardCopyOption;
import java.security.DigestInputStream;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.LocalDate;
import java.util.HexFormat;
import java.util.Locale;
import java.util.UUID;

/**
 * 上传文件落盘。
 *
 * <p>目录结构：{@code {upload.dir}/{kbId}/{yyyyMM}/{uuid}.{ext}}
 * 默认 {@code upload.dir = D:/beibei-data/upload}（E 盘空间紧张，刻意放 D 盘）。
 *
 * <p>落盘的同时算 SHA-256，用于同一知识库内去重。
 */
@Slf4j
@Service
public class FileStorageService {

    private final UploadProperties props;

    public FileStorageService(UploadProperties props) {
        this.props = props;
    }

    /** 落盘结果 */
    public record StoredFile(
            String relativePath,
            String absolutePath,
            String sha256,
            long size,
            String ext,
            String originalName
    ) {
    }

    /**
     * 保存一个上传文件。
     *
     * @param kbId 知识库 ID，用于分目录
     */
    public StoredFile store(Long kbId, MultipartFile file) {
        if (file == null || file.isEmpty()) {
            throw BusinessException.invalid("上传文件为空");
        }

        String originalName = file.getOriginalFilename() == null ? "unnamed" : file.getOriginalFilename();
        String ext = extensionOf(originalName);

        // 扩展名校验
        boolean allowed = false;
        for (String e : props.allowedExtArray()) {
            if (e.equals(ext)) {
                allowed = true;
                break;
            }
        }
        if (!allowed) {
            throw BusinessException.invalid("不支持的文件类型 ." + ext + "，允许：" + props.allowedExt());
        }

        // 体积校验（Spring 的 multipart 限制之外再兜一层，给出更友好的错误）
        long maxBytes = props.maxSizeMb() * 1024 * 1024;
        if (file.getSize() > maxBytes) {
            throw BusinessException.invalid(
                    "文件 " + originalName + " 超过 " + props.maxSizeMb() + " MB 限制");
        }

        String month = LocalDate.now().toString().substring(0, 7).replace("-", "");
        String fileName = UUID.randomUUID().toString().replace("-", "") + "." + ext;
        Path dir = Paths.get(props.dir(), String.valueOf(kbId), month);
        Path target = dir.resolve(fileName);

        try {
            Files.createDirectories(dir);
            // 边写边算 SHA-256，避免再读一遍大文件
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            try (InputStream in = file.getInputStream();
                 DigestInputStream dis = new DigestInputStream(in, digest)) {
                Files.copy(dis, target, StandardCopyOption.REPLACE_EXISTING);
            }
            String sha256 = HexFormat.of().formatHex(digest.digest());

            String relative = Paths.get(String.valueOf(kbId), month, fileName).toString().replace('\\', '/');
            log.info("文件已落盘: {} -> {} ({} bytes, sha256={})",
                    originalName, target, file.getSize(), sha256.substring(0, 12));

            return new StoredFile(relative, target.toString(), sha256, file.getSize(), ext, originalName);

        } catch (NoSuchAlgorithmException e) {
            throw new BusinessException("当前 JVM 不支持 SHA-256");
        } catch (IOException e) {
            log.error("保存文件失败: {}", originalName, e);
            throw new BusinessException("保存文件失败：" + e.getMessage());
        }
    }

    /** 解析相对路径为绝对路径 */
    public Path resolve(String relativePath) {
        return Paths.get(props.dir()).resolve(relativePath).normalize();
    }

    /** 删除文件（不存在不报错） */
    public void delete(String relativePath) {
        if (relativePath == null || relativePath.isBlank()) {
            return;
        }
        try {
            boolean ok = Files.deleteIfExists(resolve(relativePath));
            if (ok) {
                log.info("已删除文件: {}", relativePath);
            }
        } catch (IOException e) {
            log.warn("删除文件失败 {}: {}", relativePath, e.getMessage());
        }
    }

    /** 取扩展名（小写，不含点） */
    private static String extensionOf(String name) {
        int dot = name.lastIndexOf('.');
        if (dot < 0 || dot == name.length() - 1) {
            throw BusinessException.invalid("文件 " + name + " 没有扩展名，无法判断类型");
        }
        return name.substring(dot + 1).toLowerCase(Locale.ROOT);
    }
}
