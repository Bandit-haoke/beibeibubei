package com.beibei.controller;

import com.beibei.common.PageResult;
import com.beibei.common.Result;
import com.beibei.dto.ReviewDto;
import com.beibei.service.ReviewService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 错题本与复习计划接口。
 */
@RestController
@RequestMapping("/api")
@RequiredArgsConstructor
@Tag(name = "错题本与复习", description = "今日待复习、错题本、发起复习、复习日历")
public class ReviewController {

    private final ReviewService reviewService;

    @GetMapping("/review/today")
    @Operation(summary = "今日待复习题目（按逾期时间排序）")
    public Result<List<ReviewDto.DueItemVO>> today(
            @RequestParam(required = false) Long kbId,
            @RequestParam(defaultValue = "50") int limit) {
        return Result.ok(reviewService.today(kbId, limit));
    }

    @PostMapping("/review/start")
    @Operation(summary = "发起复习（用待复习题组一份临时题卷，返回 paperId）")
    public Result<ReviewDto.StartReviewVO> start(
            @RequestParam(required = false) Long kbId,
            @RequestParam(required = false) Integer limit) {
        return Result.ok(reviewService.startReview(kbId, limit));
    }

    @GetMapping("/review/calendar")
    @Operation(summary = "复习日历（过去的复习量 + 未来的到期量）")
    public Result<List<ReviewDto.CalendarDayVO>> calendar(
            @RequestParam(defaultValue = "60") int pastDays,
            @RequestParam(defaultValue = "14") int futureDays) {
        return Result.ok(reviewService.calendar(pastDays, futureDays));
    }

    @GetMapping("/mistake/list")
    @Operation(summary = "错题本列表")
    public Result<PageResult<ReviewDto.MistakeVO>> mistakes(
            @RequestParam(required = false) Long kbId,
            @RequestParam(required = false) Integer mastered,
            @RequestParam(required = false) Long tagId,
            @RequestParam(defaultValue = "1") long pageNum,
            @RequestParam(defaultValue = "20") long pageSize) {
        return Result.ok(reviewService.listMistakes(kbId, mastered, tagId, pageNum, pageSize));
    }

    @PostMapping("/mistake/{id}/mastered")
    @Operation(summary = "标记已掌握 / 取消已掌握")
    public Result<Void> markMastered(@PathVariable Long id,
                                     @RequestParam(defaultValue = "true") boolean mastered) {
        reviewService.markMastered(id, mastered);
        return Result.ok();
    }

    @DeleteMapping("/mistake/{id}")
    @Operation(summary = "从错题本移除")
    public Result<Void> remove(@PathVariable Long id) {
        reviewService.remove(id);
        return Result.ok();
    }
}
