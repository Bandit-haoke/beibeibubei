package com.beibei.controller;

import com.beibei.common.Result;
import com.beibei.dto.StatDto;
import com.beibei.service.StatService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 统计看板接口。
 */
@RestController
@RequestMapping("/api/stat")
@RequiredArgsConstructor
@Tag(name = "统计", description = "首页概览、知识点掌握度、正确率趋势、Token 成本")
public class StatController {

    private final StatService statService;

    @GetMapping("/overview")
    @Operation(summary = "首页概览（含今日待复习与连续打卡）")
    public Result<StatDto.OverviewVO> overview() {
        return Result.ok(statService.overview());
    }

    @GetMapping("/radar")
    @Operation(summary = "知识点掌握度（雷达图数据源）")
    public Result<List<StatDto.RadarItemVO>> radar(@RequestParam Long kbId) {
        return Result.ok(statService.radar(kbId));
    }

    @GetMapping("/trend")
    @Operation(summary = "正确率趋势")
    public Result<List<StatDto.TrendPointVO>> trend(@RequestParam(defaultValue = "30") int days) {
        return Result.ok(statService.trend(days));
    }

    @GetMapping("/cost")
    @Operation(summary = "Token 用量与成本")
    public Result<StatDto.CostSummaryVO> cost(@RequestParam(defaultValue = "30") int days) {
        return Result.ok(statService.cost(days));
    }

    @GetMapping("/kb-mastery")
    @Operation(summary = "每个知识库的掌握情况")
    public Result<List<StatDto.KbMasteryVO>> kbMastery() {
        return Result.ok(statService.kbMastery());
    }
}
