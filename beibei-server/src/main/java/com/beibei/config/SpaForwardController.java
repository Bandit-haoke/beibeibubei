package com.beibei.config;

import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;

/**
 * SPA 前端路由回退。
 *
 * <p>前端用的是 history 模式（{@code createWebHistory}）。
 * 好处是地址栏干净（{@code /interview/2/room} 而不是 {@code /#/interview/2/room}），
 * 代价是：在这种地址上**按 F5 刷新**，请求会真的打到后端，而后端没有这个物理路径，
 * 于是返回 404 —— 用户看到的就是「刷新一下页面就白了」。
 *
 * <p>所以要把「看起来像前端路由」的地址统统转发到 index.html，交给 vue-router 处理。
 *
 * <p>⚠️ 刻意用白名单写法，而不是 {@code /{path:[^\\.]*}} 这种通配：
 * 通配会把 {@code /api/...} 也吞掉（api 段里没有点号），所有接口一起废掉。
 * **前端新增一级路由时，记得同步下面这个列表。**
 */
@Controller
public class SpaForwardController {

    /** 一级路由名（与 beibei-web/src/router/index.ts 保持一致） */
    private static final String ROOT =
            "{p1:kb|paper|exam|interview|resume|mistake|review|stat|settings}";

    @GetMapping({
            "/" + ROOT,
            "/" + ROOT + "/{p2}",
            "/" + ROOT + "/{p2}/{p3}",
    })
    public String forward() {
        return "forward:/index.html";
    }
}
