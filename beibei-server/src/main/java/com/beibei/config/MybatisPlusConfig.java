package com.beibei.config;

import com.baomidou.mybatisplus.annotation.DbType;
import com.baomidou.mybatisplus.core.handlers.MetaObjectHandler;
import com.baomidou.mybatisplus.extension.plugins.MybatisPlusInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.BlockAttackInnerInterceptor;
import com.baomidou.mybatisplus.extension.plugins.inner.PaginationInnerInterceptor;
import org.apache.ibatis.reflection.MetaObject;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.EnableTransactionManagement;

import java.time.LocalDateTime;

/**
 * MyBatis-Plus 配置。
 *
 * <p>注意：表名不使用全局 table-prefix，而是每个实体显式写 {@code @TableName("bb_xxx")}，
 * 避免「全局前缀 + 注解表名」叠加导致的表名错乱。
 */
@Configuration
@EnableTransactionManagement
public class MybatisPlusConfig {

    public static final String FIELD_CREATED_AT = "createdAt";
    public static final String FIELD_UPDATED_AT = "updatedAt";

    @Bean
    public MybatisPlusInterceptor mybatisPlusInterceptor() {
        MybatisPlusInterceptor interceptor = new MybatisPlusInterceptor();

        // 分页
        PaginationInnerInterceptor pagination = new PaginationInnerInterceptor(DbType.MYSQL);
        pagination.setMaxLimit(500L);          // 单页最大 500 条，防误查
        pagination.setOverflow(false);          // 页码越界时返回空而不是回到第一页
        interceptor.addInnerInterceptor(pagination);

        // 阻断全表更新 / 全表删除
        interceptor.addInnerInterceptor(new BlockAttackInnerInterceptor());

        return interceptor;
    }

    /**
     * 自动填充创建/更新时间，省得每个 Service 手动 set。
     * 数据库侧也有 DEFAULT CURRENT_TIMESTAMP，两边一致不冲突。
     */
    @Component
    public static class AutoFillHandler implements MetaObjectHandler {

        @Override
        public void insertFill(MetaObject metaObject) {
            LocalDateTime now = LocalDateTime.now();
            strictInsertFill(metaObject, FIELD_CREATED_AT, LocalDateTime.class, now);
            strictInsertFill(metaObject, FIELD_UPDATED_AT, LocalDateTime.class, now);
        }

        @Override
        public void updateFill(MetaObject metaObject) {
            strictUpdateFill(metaObject, FIELD_UPDATED_AT, LocalDateTime.class, LocalDateTime.now());
        }
    }
}
