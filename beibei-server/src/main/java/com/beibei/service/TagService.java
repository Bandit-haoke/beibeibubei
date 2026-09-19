package com.beibei.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.beibei.common.BusinessException;
import com.beibei.dto.TagDto;
import com.beibei.entity.ChunkTag;
import com.beibei.entity.Tag;
import com.beibei.mapper.ChunkTagMapper;
import com.beibei.mapper.TagMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 知识点树业务。最多 3 层，每个知识库一套独立体系。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class TagService {

    public static final int MAX_LEVEL = 3;

    private final TagMapper tagMapper;
    private final ChunkTagMapper chunkTagMapper;

    // ------------------------------------------------------------------
    //  查询
    // ------------------------------------------------------------------

    /** 返回知识点森林（顶层列表，children 递归填充） */
    public List<TagDto.NodeVO> tree(Long kbId) {
        List<Tag> all = tagMapper.selectList(
                Wrappers.<Tag>lambdaQuery()
                        .eq(Tag::getKbId, kbId)
                        .orderByAsc(Tag::getLevel)
                        .orderByAsc(Tag::getSortOrder)
                        .orderByAsc(Tag::getId));
        Map<Long, List<Tag>> byParent = all.stream()
                .collect(Collectors.groupingBy(t -> t.getParentId() == null ? 0L : t.getParentId(),
                        LinkedHashMap::new, Collectors.toList()));
        return buildForest(0L, byParent);
    }

    private List<TagDto.NodeVO> buildForest(Long parentId, Map<Long, List<Tag>> byParent) {
        List<Tag> children = byParent.get(parentId);
        if (children == null || children.isEmpty()) {
            return List.of();
        }
        List<TagDto.NodeVO> out = new ArrayList<>(children.size());
        for (Tag t : children) {
            out.add(new TagDto.NodeVO(
                    t.getId(), t.getParentId(), t.getName(), t.getLevel(), t.getSortOrder(),
                    t.getDescription(), t.getOrigin(), t.getChunkCount(), t.getQuestionCount(),
                    buildForest(t.getId(), byParent)
            ));
        }
        return out;
    }

    public Tag require(Long id) {
        Tag t = tagMapper.selectById(id);
        if (t == null) {
            throw BusinessException.notFound("知识点", id);
        }
        return t;
    }

    /** 批量取知识点（不存在的不报错，直接跳过） */
    public List<Tag> requireAll(List<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return List.of();
        }
        return tagMapper.selectByIds(ids);
    }

    /** 取某知识点及其所有子孙的 ID（出题时按范围检索用） */
    public List<Long> selfAndDescendantIds(Long kbId, List<Long> tagIds) {
        if (tagIds == null || tagIds.isEmpty()) {
            return List.of();
        }
        List<Tag> all = tagMapper.selectList(Wrappers.<Tag>lambdaQuery().eq(Tag::getKbId, kbId));
        Map<Long, List<Tag>> byParent = all.stream()
                .collect(Collectors.groupingBy(t -> t.getParentId() == null ? 0L : t.getParentId()));

        List<Long> result = new ArrayList<>();
        java.util.ArrayDeque<Long> queue = new java.util.ArrayDeque<>(tagIds);
        java.util.Set<Long> seen = new java.util.HashSet<>();
        while (!queue.isEmpty()) {
            Long id = queue.poll();
            if (!seen.add(id)) {
                continue;
            }
            result.add(id);
            for (Tag child : byParent.getOrDefault(id, List.of())) {
                queue.add(child.getId());
            }
        }
        return result;
    }

    // ------------------------------------------------------------------
    //  写
    // ------------------------------------------------------------------

    @Transactional(rollbackFor = Exception.class)
    public Tag create(TagDto.SaveReq req) {
        long parentId = req.parentId() == null ? 0L : req.parentId();
        int level = 1;
        if (parentId != 0L) {
            Tag parent = require(parentId);
            if (!parent.getKbId().equals(req.kbId())) {
                throw BusinessException.invalid("父知识点不属于该知识库");
            }
            level = parent.getLevel() + 1;
            if (level > MAX_LEVEL) {
                throw BusinessException.invalid("知识点最多 " + MAX_LEVEL + " 层");
            }
        }

        Tag tag = new Tag();
        tag.setKbId(req.kbId());
        tag.setParentId(parentId);
        tag.setName(req.name().trim());
        tag.setLevel(level);
        tag.setSortOrder(req.sortOrder() == null ? 0 : req.sortOrder());
        tag.setDescription(req.description() == null ? "" : req.description());
        tag.setOrigin(Tag.ORIGIN_MANUAL);
        tag.setChunkCount(0);
        tag.setQuestionCount(0);
        tagMapper.insert(tag);
        return tag;
    }

    public Tag update(Long id, TagDto.SaveReq req) {
        Tag tag = require(id);
        if (req.name() != null && !req.name().isBlank()) {
            tag.setName(req.name().trim());
        }
        if (req.description() != null) {
            tag.setDescription(req.description());
        }
        if (req.sortOrder() != null) {
            tag.setSortOrder(req.sortOrder());
        }
        tagMapper.updateById(tag);
        return tag;
    }

    /** 删除知识点（连同所有子孙和关联关系） */
    @Transactional(rollbackFor = Exception.class)
    public void delete(Long id) {
        Tag tag = require(id);
        List<Long> ids = selfAndDescendantIds(tag.getKbId(), List.of(id));

        chunkTagMapper.delete(Wrappers.<ChunkTag>lambdaQuery().in(ChunkTag::getTagId, ids));
        tagMapper.deleteByIds(ids);
        log.info("删除知识点 #{} 及其 {} 个子孙", id, ids.size() - 1);
    }

    /** 重算每个知识点挂了多少分块 */
    public void refreshChunkCounts(Long kbId) {
        List<Tag> tags = tagMapper.selectList(Wrappers.<Tag>lambdaQuery().eq(Tag::getKbId, kbId));
        for (Tag t : tags) {
            Long count = chunkTagMapper.selectCount(
                    Wrappers.<ChunkTag>lambdaQuery().eq(ChunkTag::getTagId, t.getId()));
            if (!count.equals((long) t.getChunkCount())) {
                Tag patch = new Tag();
                patch.setId(t.getId());
                patch.setChunkCount(count.intValue());
                tagMapper.updateById(patch);
            }
        }
    }

    /** 给一批分块批量取知识点，用于分块列表展示（避免 N+1） */
    public Map<Long, List<com.beibei.dto.DocDto.TagBrief>> tagBriefsByChunk(List<Long> chunkIds) {
        if (chunkIds == null || chunkIds.isEmpty()) {
            return Map.of();
        }
        List<ChunkTag> relations = chunkTagMapper.selectList(
                Wrappers.<ChunkTag>lambdaQuery().in(ChunkTag::getChunkId, chunkIds));
        if (relations.isEmpty()) {
            return Map.of();
        }
        List<Long> tagIds = relations.stream().map(ChunkTag::getTagId).distinct().toList();
        Map<Long, Tag> tagMap = tagMapper.selectByIds(tagIds).stream()
                .collect(Collectors.toMap(Tag::getId, t -> t));

        Map<Long, List<com.beibei.dto.DocDto.TagBrief>> result = new LinkedHashMap<>();
        for (ChunkTag rel : relations) {
            Tag t = tagMap.get(rel.getTagId());
            if (t == null) {
                continue;
            }
            result.computeIfAbsent(rel.getChunkId(), k -> new ArrayList<>())
                    .add(new com.beibei.dto.DocDto.TagBrief(t.getId(), t.getName(), t.getLevel()));
        }
        return result;
    }
}
