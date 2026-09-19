package com.beibei.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.beibei.entity.Question;
import org.apache.ibatis.annotations.Mapper;

/**
 * Question 的 Mapper。
 */
@Mapper
public interface QuestionMapper extends BaseMapper<Question> {
}