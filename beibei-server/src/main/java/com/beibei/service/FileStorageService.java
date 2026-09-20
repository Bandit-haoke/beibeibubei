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
        return storeInto(String.valueOf(kbId), file, props.allowedExtArray(),
                props.maxSizeMb(), "不支持的文件类型", props.allowedExt());
    }

    /** 面经录音的体积上限：500MB，与讯飞语音转写的单文件上限对齐 */
    public static final long AUDIO_MAX_SIZE_MB = 500L;

    /** 音频格式白名单，和学习资料的白名单刻意分开 */
    private static final String[] AUDIO_EXTS = {
            "mp3", "wav", "m4a", "flac", "opus", "aac", "ogg", "wma", "amr"
    };

    /**
     * 面经录音落盘。
     *
     * <p>单独开一个入口，而不是把音频格式加进 {@code beibei.upload.allowed-ext}：
     * 那样用户就能把 mp3 当"学习资料"传进知识库，然后在解析阶段才失败，提示很绕。
     * 这里用独立目录 {@code audio/} + 独立白名单 + 独立体积上限。
     */
    public StoredFile storeAudio(MultipartFile file) {
        return storeInto("audio", file, AUDIO_EXTS, AUDIO_MAX_SIZE_MB,
                "不支持的音频格式", String.join(",", AUDIO_EXTS));
    }

    private StoredFile storeInto(String dirName, MultipartFile file, String[] allowedExts,
                                 long maxSizeMb, String typeErrorPrefix, String allowedDesc) {
        if (file == null || file.isEmpty()) {
            throw BusinessException.invalid("上传文件为空");
        }

        String originalName = file.getOriginalFilename() == null ? "unnamed" : file.getOriginalFilename();
        String ext = extensionOf(originalName);

        // 扩展名校验
        boolean allowed = false;
        for (String e : allowedExts) {
            if (e.equals(ext)) {
                allowed = true;
                break;
            }
        }
        if (!allowed) {
            throw BusinessException.invalid(typeErrorPrefix + " ." + ext + "，允许：" + allowedDesc);
        }

        // 体积校验（Spring 的 multipart 限制之外再兜一层，给出更友好的错误）
        long maxBytes = maxSizeMb * 1024 * 1024;
        if (file.getSize() > maxBytes) {
            throw BusinessException.invalid(
                    "文件 " + originalName + " 超过 " + maxSizeMb + " MB 限制");
        }

        String month = LocalDate.now().toString().substring(0, 7).replace("-", "");
        String fileName = UUID.randomUUID().toString().replace("-", "") + "." + ext;
        Path dir = Paths.get(props.dir(), dirName, month);
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

            String relative = Paths.get(dirName, month, fileName).toString().replace('\\', '/');
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
