# -*- coding: utf-8 -*-
"""面经本地清洗的回归测试。

这部分不依赖任何外部 API，所以可以当单元测试反复跑。
运行：python scripts/test_clean.py
"""
import sys

sys.path.insert(0, r'E:\学习资源\背书工具\beibei-agent')

from app.services.interview_note import (  # noqa: E402
    _is_question,
    classify_question,
    clean_text_locally,
)

CASES = [
    # (原句, 期望清洗结果)
    ('嗯，那个，我先自我介绍一下，我叫张三。', '我先自我介绍一下，我叫张三。'),
    ('啊，这个这个问题，我我我觉得是这样的。', '这个问题，我觉得是这样的。'),
    ('额……就是说，缓存穿透是是指查询一个不存在的数据。',
     '缓存穿透是是指查询一个不存在的数据。'),
    ('然后呢，嗯，我们当时用的是 Redis，对，Redis。',
     '然后呢，我们当时用的是 Redis，对，Redis。'),
    ('哈哈哈，这个我确实不太清楚。', '哈，这个我确实不太清楚。'),
    ('我们项目里用到了 Spring Boot，还有，那个，MyBatis。',
     '我们项目里用到了 Spring Boot，还有，MyBatis。'),
    # 句尾的语气助词有语义，必须保留
    ('真的啊，那挺好的。', '真的啊，那挺好的。'),
    ('就是就是，我觉得应该应该先做限流。', '就是，我觉得应该先做限流。'),
    ('啊啊啊，不好意思。', '不好意思。'),
    ('好的，谢谢面试官。', '好的，谢谢面试官。'),
    # 技术内容不能被"顺"掉
    ('嗯，我用 Redis 做缓存，QPS 大概 3000 左右。',
     '我用 Redis 做缓存，QPS 大概 3000 左右。'),
    ('那个，MyBatis-Plus 的 Wrapper 我一般用 lambda 写法。',
     'MyBatis-Plus 的 Wrapper 我一般用 lambda 写法。'),
    ('呃，这个接口的响应时间是 200ms，额，还可以再优化。',
     '这个接口的响应时间是 200ms，还可以再优化。'),
    ('', ''),
]

QUESTIONS = [
    ('请你介绍一下这个项目的难点', True),
    ('缓存击穿怎么解决？', True),
    ('嗯我平时喜欢看技术书', False),
    ('你有什么想问我的吗', False),
    ('你先说说这块怎么做的', True),
    ('我用的是 Spring Boot', False),
]


def main() -> int:
    failed = 0

    print('===== 本地口语清洗 =====')
    for raw, expect in CASES:
        got, removed = clean_text_locally(raw)
        ok = got == expect
        if not ok:
            failed += 1
        print('  %s 原: %s' % ('OK ' if ok else 'BAD', raw or '(空)'))
        print('       后: %s' % got)
        if not ok:
            print('       期望: %s' % expect)
        if removed:
            print('       去掉: %s' % removed)
    print('  用例 %d 条，失败 %d 条' % (len(CASES), failed))
    print()

    print('===== 提问识别 =====')
    qfail = 0
    for text, expect in QUESTIONS:
        got = _is_question(text)
        ok = got == expect
        if not ok:
            qfail += 1
        print('  %s is_question=%-5s type=%-8s %s'
              % ('OK ' if ok else 'BAD', got, classify_question(text), text))
    print('  用例 %d 条，失败 %d 条' % (len(QUESTIONS), qfail))
    print()

    total = failed + qfail
    print('总计失败 %d 条' % total)
    return 1 if total else 0


if __name__ == '__main__':
    raise SystemExit(main())
