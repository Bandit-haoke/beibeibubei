package com.beibei.common;

import com.baomidou.mybatisplus.core.metadata.IPage;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.io.Serializable;
import java.util.Collections;
import java.util.List;
import java.util.function.Function;

/**
 * 分页结果。与前端约定：{@code { total, list, pageNum, pageSize, pages }}。
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
public class PageResult<T> implements Serializable {

    private long total;
    private List<T> list;
    private long pageNum;
    private long pageSize;
    private long pages;

    public static <T> PageResult<T> of(IPage<T> page) {
        return new PageResult<>(
                page.getTotal(),
                page.getRecords(),
                page.getCurrent(),
                page.getSize(),
                page.getPages()
        );
    }

    /** 分页对象里的实体转成 VO */
    public static <E, V> PageResult<V> of(IPage<E> page, Function<E, V> mapper) {
        List<V> list = page.getRecords() == null
                ? Collections.emptyList()
                : page.getRecords().stream().map(mapper).toList();
        return new PageResult<>(page.getTotal(), list, page.getCurrent(), page.getSize(), page.getPages());
    }

    public static <T> PageResult<T> empty(long pageNum, long pageSize) {
        return new PageResult<>(0L, Collections.emptyList(), pageNum, pageSize, 0L);
    }
}
