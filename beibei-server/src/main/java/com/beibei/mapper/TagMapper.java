package com.beibei.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.beibei.entity.Tag;
import org.apache.ibatis.annotations.Mapper;

/**
 * Tag 的 Mapper。复杂查询用 XML（src/main/resources/mapper/），简单 CRUD 走 BaseMapper。
 */
@Mapper
public interface TagMapper extends BaseMapper<Tag> {
}
