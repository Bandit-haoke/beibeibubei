package com.beibei.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 上传相关配置。
 *
 * <p>注意：上传文件默认落在 D 盘（E 盘空间紧张），
 * 对应 application-dev.yml 的 {@code beibei.upload.dir}。
 */
@ConfigurationProperties(prefix = "beibei.upload")
public record UploadProperties(
        String dir,
        Long maxSizeMb,
        String allowedExt
) {
    public UploadProperties {
        if (dir == null || dir.isBlank()) {
            dir = "D:/beibei-data/upload";
        }
        if (maxSizeMb == null || maxSizeMb <= 0) {
            maxSizeMb = 100L;
        }
        if (allowedExt == null || allowedExt.isBlank()) {
            allowedExt = "pdf,doc,docx,ppt,pptx,txt,md,xlsx,jpg,jpeg,png,bmp,webp";
        }
    }

    public String[] allowedExtArray() {
        return allowedExt.toLowerCase().split("\\s*,\\s*");
    }
}
