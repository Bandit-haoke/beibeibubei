package com.beibei.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.beibei.entity.Paper;
import com.beibei.entity.PaperItem;
import com.beibei.mapper.PaperItemMapper;
import com.beibei.mapper.PaperMapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 题卷状态收尾。
 *
 * <p>刻意从 {@link PaperService} 里抽出来：出题流程是
 * {@code PaperService → GenerationRunner → 状态收尾}，
 * 如果收尾方法还挂在 PaperService 上就会形成循环依赖，
 * Spring Boot 2.6+ 默认禁止循环引用，应用直接起不来。
 * 拆成独立组件后依赖是单向的：PaperService → GenerationRunner → PaperStatusService。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class PaperStatusService {

    private final PaperMapper paperMapper;
    private final PaperItemMapper paperItemMapper;
    private final KnowledgeBaseService kbService;
    private final ObjectMapper objectMapper;

    /** 出题成功后的收尾 */
    public void markGenerated(Long paperId, Map<String, Object> summary) {
        Paper paper = paperMapper.selectById(paperId);
        if (paper == null) {
            log.warn("题卷 #{} 不存在，跳过收尾", paperId);
            return;
        }
        int saved = summary.get("saved") instanceof Number n ? n.intValue() : 0;

        Paper patch = new Paper();
        patch.setId(paperId);
        patch.setStatus(saved > 0 ? Paper.STATUS_PENDING_REVIEW : Paper.STATUS_FAILED);
        patch.setGenSummary(toJson(summary));
        paperMapper.updateById(patch);

        recomputeTotals(paperId);

        // 题目是 Python 直接写库的，Java 这边不知道新增了几道，
        // 所以出题结束后统一重算知识库的「题目数」——否则知识库卡片上一直显示 0 题。
        if (saved > 0 && paper.getKbId() != null) {
            try {
                kbService.refreshCounters(paper.getKbId());
            } catch (Exception e) {
                log.warn("刷新知识库 #{} 计数失败（不影响出题结果）：{}",
                        paper.getKbId(), e.getMessage());
            }
        }

        log.info("出题收尾：paper=#{} 保存 {} 道，状态={}", paperId, saved,
                saved > 0 ? "待审" : "失败");
    }

    /** 出题失败 */
    public void markFailed(Long paperId, String errorMsg) {
        Paper patch = new Paper();
        patch.setId(paperId);
        patch.setStatus(Paper.STATUS_FAILED);
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("error", errorMsg == null ? "未知错误" : errorMsg);
        patch.setGenSummary(toJson(summary));
        paperMapper.updateById(patch);
        log.warn("题卷 #{} 标记为失败：{}", paperId, errorMsg);
    }

    /** 重算题卷的题目数与总分 */
    public void recomputeTotals(Long paperId) {
        List<PaperItem> items = paperItemMapper.selectList(
                Wrappers.<PaperItem>lambdaQuery().eq(PaperItem::getPaperId, paperId));
        BigDecimal total = items.stream()
                .map(i -> i.getScore() == null ? BigDecimal.ZERO : i.getScore())
                .reduce(BigDecimal.ZERO, BigDecimal::add);

        Paper patch = new Paper();
        patch.setId(paperId);
        patch.setTotalCount(items.size());
        patch.setTotalScore(total);
        paperMapper.updateById(patch);
    }

    private String toJson(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception e) {
            return null;
        }
    }
}
