package com.beibei;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * 背备不悲 · 后端网关启动类
 *
 * <p>定位：唯一对外入口。浏览器只跟本服务通信，AI 能力全部通过 {@code beibei-agent} 转发。
 *
 * <p>IDEA 里直接右键本文件 → Run 'BeibeiApplication'。
 */
@SpringBootApplication
@ConfigurationPropertiesScan
@MapperScan("com.beibei.mapper")
@EnableAsync
@EnableScheduling
public class BeibeiApplication {

    public static void main(String[] args) {
        SpringApplication.run(BeibeiApplication.class, args);
    }
}
