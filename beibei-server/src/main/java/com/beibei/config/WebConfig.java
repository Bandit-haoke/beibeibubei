package com.beibei.config;

import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.ResourceHandlerRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

import java.io.File;

/**
 * Web 层配置。
 *
 * <p>CORS 仅用于开发期：Vite dev server 跑在 5173，需要跨域访问 8080。
 * 生产形态是前端构建产物直接由本服务托管在同一个 8080 端口，同源，不需要 CORS。
 *
 * <p>另外把上传目录映射成 /files/** 静态资源，便于前端预览原文档。
 */
@Slf4j
@Configuration
public class WebConfig implements WebMvcConfigurer {

    private final UploadProperties uploadProperties;

    public WebConfig(UploadProperties uploadProperties) {
        this.uploadProperties = uploadProperties;
    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/api/**")
                .allowedOriginPatterns("http://localhost:*", "http://127.0.0.1:*")
                .allowedMethods("GET", "POST", "PUT", "DELETE", "OPTIONS")
                .allowedHeaders("*")
                .allowCredentials(true)
                .maxAge(3600);
    }

    @Override
    public void addResourceHandlers(ResourceHandlerRegistry registry) {
        String dir = uploadProperties.dir();
        if (dir == null || dir.isBlank()) {
            return;
        }
        File base = new File(dir);
        if (!base.exists()) {
            // 首次启动时目录还不存在，先建出来，避免静态资源映射指向一个不存在的路径
            //noinspection ResultOfMethodCallIgnored
            base.mkdirs();
        }
        String location = base.toURI().toString();
        registry.addResourceHandler("/files/**").addResourceLocations(location);
        log.info("上传目录静态映射: /files/** -> {}", location);
    }
}
