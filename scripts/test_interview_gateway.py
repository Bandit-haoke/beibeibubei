"""
背备不悲 · 模拟面试「过网关」验证

和 test_interview.py 的区别：
    test_interview.py         直连 Python 8000，验证 AI 流水线本身
    test_interview_gateway.py 走 Java 8080，验证**浏览器实际经过的那条路**：
                              上传落盘 → 建异步任务 → SSE 代理 → DTO 映射 → 联动出题

用法：
    python scripts/test_interview_gateway.py
    python scripts/test_interview_gateway.py --turns 6 --kb 19
    python scripts/test_interview_gateway.py --keep
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests
from sqlalchemy import text as sql_text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "beibei-agent"))

from app.config import get_settings  # noqa: E402
from app.db.mysql import get_engine  # noqa: E402

JAVA = "http://127.0.0.1:8080"

# ---------------------------------------------------------------------------
#  候选人回答库
#
#  为什么不是「一个固定顺序的答案列表」：
#  Mock 模式下面试官按固定顺序轮换技能，固定答案列表看起来没问题；
#  但换成真实模型后，面试官是**自适应提问**的（问了 A，你答得含糊它就追问 A），
#  固定顺序必然答非所问 —— 实测出现过 0 分、18 分，报告直接写「严重跑题」。
#
#  所以改成：按问题里的关键词从回答库里挑一条最贴切的来答。
#  这样脚本才是真的在「被面试」，而不是在念稿。
#
#  库里的答案刻意有好有坏，用来验证评分确实有区分度：
#    - 「JVM」那条只给结论不给过程 → 应该触发 FOLLOWUP 并拉低「项目具体性」
#    - 「分布式事务」那条直接承认不会 → 应该明显拉低「技术准确性 / 岗位匹配度」
# ---------------------------------------------------------------------------

ANSWER_BANK: list[tuple[list[str], str]] = [
    (["自我介绍", "介绍一下", "教育背景", "学习经历", "为什么想找", "求职意向"], (
        "面试官好，我是张小明，某某大学软件工程专业本科，2027 年 6 月毕业，"
        "目前还没有正式的工作经历，求职意向是后端开发。"
        "技术栈主要是 Java 后端这一套：Java 基础、JVM、JUC、MySQL、Redis，"
        "框架上熟练 Spring、SpringMVC、MyBatis、SpringBoot，微服务了解 SpringCloud 和 Nacos。"
        "在校期间我自己做了两个项目，校园外卖订餐系统和社交电商平台，"
        "两个都是前后端分离，后端部分由我独立完成。"
        "想做后端是因为我比较喜欢琢磨「一个请求进来之后到底发生了什么」，"
        "写业务代码之外也愿意去看源码，比如 HashMap 的扩容机制。"
    )),

    (["双写", "一致性", "主从", "哨兵", "延迟双删", "缓存一致", "营业状态",
      "cacheaside", "cache aside", "第二次删除", "补偿", "缓存设计", "旁路"], (
        "校园外卖订餐系统的缓存一致性是我踩得最狠的一个坑。背景是营业状态、菜品分类"
        "这些数据读多写少，一开始我的做法是「更新数据库之后直接删缓存」，"
        "压测的时候发现有脏数据：两个线程一个读到旧值准备写缓存，另一个刚好把新值写进库"
        "又删了缓存，结果旧值被写了进去。后来我改成先更新数据库、再延迟双删缓存，"
        "并且给缓存本身加了过期时间做最终兜底。缓存我用的是 Redis 主从加哨兵集群，"
        "不是单机，哨兵负责主节点挂掉之后的自动故障转移。"
    )),

    (["分布式锁", "一人一单", "setnx", "lua", "超卖", "秒杀", "优惠券", "并发下单"], (
        "星选电商的优惠券秒杀是我做的，核心要解决超卖和一人一单。"
        "一人一单我用 Redis 分布式锁，key 是优惠券 id 加用户 id，用 setnx 加过期时间；"
        "关键是「判断有没有加过锁」和「加锁」这两步必须原子，所以我把它们写成一段 Lua 脚本，"
        "避免 setnx 成功了但还没设过期时间就宕机导致死锁。"
        "超卖是在扣减库存那一步，同样用 Lua 把「查库存 + 判断是否足够 + 扣减」合成一个原子操作，"
        "而不是先 GET 再 DECR。压测一千并发下单，库存没有超卖，重复下单也被拦住了。"
    )),

    (["布隆", "工厂模式", "策略模式", "bitmap", "误判", "穿透", "防穿透"], (
        "布隆过滤器我是用工厂模式加策略模式做的。因为有好几个需要防穿透的场景，"
        "所以抽象了一个 BloomFilterStrategy 接口，用工厂按场景名取具体实现，"
        "这样以后加新场景不用改调用方。底层我用的是 Redis 的 bitmap，"
        "而不是 Guava 的本地 BloomFilter —— 因为服务是多实例部署的，"
        "用本地的话每个实例一份，数据不一致，所以用 Guava 算哈希位置、写到 Redis 上共享。"
        "误判率设的是百分之一，根据这个反推位数组大小和哈希函数个数。"
        "另外额外加了一层空值缓存，防止同一个不存在的 key 反复打到数据库。"
    )),

    (["线程池", "juc", "executors", "corepoolsize", "拒绝策略", "cas", "aqs", "锁机制", "读写锁"], (
        "线程池我一般不用 Executors 直接创建，因为 newFixedThreadPool 和 newSingleThreadExecutor "
        "用的是无界队列，任务堆积会 OOM；newCachedThreadPool 和 newScheduledThreadPool "
        "最大线程数是 Integer.MAX_VALUE，会无限创建线程。所以我都是用 ThreadPoolExecutor "
        "显式指定七个参数：核心线程数、最大线程数、空闲存活时间、时间单位、工作队列、"
        "线程工厂、拒绝策略。核心线程数和最大线程数我一般按任务类型定，"
        "CPU 密集型大概是核数加一，IO 密集型会大一些。"
        "拒绝策略默认是 AbortPolicy 直接抛异常，我一般会自定义一个，"
        "把被拒绝的任务落库或者打到日志里，方便事后补偿。"
        "执行流程是：核心线程没满就新建核心线程，满了进队列，队列满了再建非核心线程，"
        "都满了才走拒绝策略。"
    )),

    (["threadlocal", "内存泄漏", "弱引用", "线程复用"], (
        "ThreadLocal 的原理是每个 Thread 对象里有一个 ThreadLocalMap，"
        "key 是 ThreadLocal 实例本身，而且是个弱引用，value 是强引用。"
        "所以 get/set 其实是拿当前线程的 map 去存取，天然线程隔离。"
        "内存泄漏就出在这个弱引用上：如果 ThreadLocal 实例被回收了，"
        "key 变成 null，但 value 还被线程强引用着；在线程池里线程是复用的、"
        "生命周期很长，这些 value 就一直回收不掉。"
        "ThreadLocal 自己会在 get/set 时顺带清理 key 为 null 的 Entry，但不可靠。"
        "所以规范做法是在 finally 里显式 remove。"
        "我在项目里用它存登录用户信息，配合拦截器，请求结束就 remove，"
        "既能免去一路传 userId，也不会串号。"
    )),

    (["jwt", "鉴权", "登录", "拦截器", "token", "权限", "认证"], (
        "鉴权这块我是用 JWT 加 ThreadLocal 做的。用户登录之后签发 JWT，"
        "之后每个请求带在 Header 里；我写了一个自定义拦截器统一校验 token 和权限，"
        "校验通过之后把用户信息放进 ThreadLocal，这样 Service 层不用一路往下传 userId。"
        "需要注意的两点是：ThreadLocal 一定要在请求结束时 remove，"
        "否则 Tomcat 线程池复用线程会造成内存泄漏和串号；"
        "还有就是要区分哪些接口放行、哪些必须登录。"
    )),

    (["索引", "explain", "最左前缀", "联合索引", "回表", "覆盖索引", "sql", "慢查询"], (
        "MySQL 索引我熟悉最左前缀原则。之前订单表按用户查历史订单很慢，"
        "我先用 EXPLAIN 看执行计划，发现 type 是 ALL，也就是全表扫描，rows 有几十万。"
        "然后我建了 (user_id, create_time) 的联合索引，再看 EXPLAIN 就变成 ref 了，"
        "扫描行数降到几百行。这块我也注意了回表问题，"
        "如果查询字段都在索引里就会走覆盖索引，避免回表；"
        "另外写 SQL 的时候要避免在索引列上做函数运算或者隐式类型转换，那样索引会失效。"
    )),

    (["hashmap", "红黑树", "树化", "扩容", "put", "底层结构", "concurrenthashmap", "集合"], (
        "HashMap 底层是数组加链表加红黑树。put 的流程：先用 key 的 hashCode 经过扰动函数"
        "算出 hash，再用 (n-1) & hash 定位数组下标；位置为空就直接放；"
        "不为空就比较 hash 和 equals，相同就覆盖 value，不同就挂到链表尾部。"
        "链表长度到 8 并且数组容量到 64 时树化成红黑树，元素减少到 6 时退化成链表"
        "（容量不到 64 时优先扩容而不是树化）。"
        "扩容的负载因子是 0.75，容量翻倍；1.8 之后扩容用的是高低位链表，"
        "不需要重新计算 hash，只需要判断新增的那一位是 0 还是 1。"
        "HashMap 线程不安全，1.7 头插法并发扩容会形成环形链表导致死循环，"
        "1.8 改成尾插避免了成环，但并发下依然会丢数据，多线程要用 ConcurrentHashMap。"
    )),

    (["项目来源", "课程设计", "个人练手", "角色", "独立完成", "谁做的", "团队", "参与", "是不是跟着"], (
        "这两个项目都是我一个人做的，不是团队项目，也不是照着教程抄的。"
        "校园外卖订餐系统最早是课程设计，做完之后我觉得功能太浅，"
        "就自己加了 Redis 主从加哨兵、布隆过滤器、还有 Websocket 来单提醒，"
        "这部分是课外自己查资料加上去的。"
        "社交电商平台是我为了练高并发场景自己立项做的，"
        "从需求、表设计到接口和压测都是我一个人。"
        "所以我对里面每一块都比较清楚；但也因为是一个人做，没有经过 code review，"
        "代码规范和边界情况的处理肯定有不足。"
    )),

    (["消息队列", "redisstream", "redis stream", "异步", "削峰", "解耦", "mq", "rabbitmq",
      "pending", "ack", "重试", "幂等", "死信"], (
        "削峰这块我用的是 RedisStream 而不是 RabbitMQ，主要是考虑不额外引入中间件、部署简单。"
        "做法是秒杀请求进来先做前置校验和库存预扣，校验通过就把下单消息丢到 Stream 里直接返回，"
        "真正的落库由消费者异步处理，接口响应时间从同步写库的几十毫秒降到几毫秒。"
        "异步之后最难的是消息可靠性。我用的是消费者组加手动 ACK，"
        "处理失败就不 ACK，消息会留在 pending 列表里。"
        "重试是靠一个定时任务，用 XPENDING 扫描每个消费者组里超过阈值还没 ACK 的消息，"
        "拿到消息 id 之后用 XCLAIM 把所有权转给健康的消费者重新消费；"
        "超过最大重试次数就投到死信队列里人工处理。"
        "幂等是下单消息带一个业务唯一键，消费端先查这张单是否已经处理过，"
        "处理过就直接 ACK，避免重复扣库存。"
    )),

    (["nginx", "负载均衡", "反向代理", "websocket", "来单", "部署", "linux", "docker"], (
        "Nginx 我主要用它做反向代理和负载均衡，把前端静态资源和后端接口分开转发。"
        "校园外卖订餐系统里的「来单提醒」用的是 Websocket，"
        "Nginx 转发 Websocket 需要额外配 Upgrade 和 Connection 头，"
        "不然握手会失败，这个我调了挺久。Linux 上我主要是用命令行排查，"
        "top 看负载、看日志定位报错，也会用 Docker 把服务打起来。"
    )),

    # ↓ 这条是「半懂」，简历上只写了「对事务有一定理解」，
    #   所以 MVCC 这类深水区答不上来才符合真实情况，也顺便验证评分不会因为
    #   候选人硬扯到别的知识点上就给高分
    (["mvcc", "隔离级别", "不可重复读", "幻读", "readview", "read view", "事务隔离", "undo log"], (
        "MVCC 我了解得不深。我知道它是靠 undo log 里的版本链加一个 ReadView 来实现的，"
        "读的时候根据 ReadView 判断这个版本对自己可不可见，"
        "所以普通 select 不用加锁也能读到一致性快照。"
        "RR 和 RC 的区别好像就在于 ReadView 生成的时机不一样："
        "RC 是每次查询都生成一个新的，RR 是事务里第一次查询生成之后就复用。"
        "但具体可见性判断的规则我记不清了，之前看的时候没完全看懂，"
        "这块我确实需要再补。"
    )),

    # ↓ 这条故意是「只给结论不给过程」，用来验证追问与具体性评分是真的在起作用
    (["jvm", "类加载", "双亲委派", "gc", "内存模型", "调优", "垃圾回收"], (
        "JVM 这块我熟悉内存模型和类加载机制，双亲委派也知道，就是先找父加载器加载，"
        "加载不到再自己加载。调优的话我了解一些参数。"
    )),

    # ↓ 这条故意是「直接承认不会」，用来验证技术准确性与匹配度评分确实有区分度
    (["分布式事务", "seata", "最终一致性", "两阶段", "tcc"], (
        "分布式事务我没有实际用过，只在资料上看过 Seata 的 AT 模式，"
        "原理理解得不深，真让我在生产环境配我是不敢的。这块是我的短板。"
    )),

    (["优势", "不足", "规划", "评价自己", "还有什么", "反问", "想问", "职业", "怎么学", "未来",
      "收获", "学到", "困难", "挑战", "反思", "成长", "最大的"], (
        "我的优势是基础打得比较扎实，Java 基础、JVM、JUC 这些都有系统学过，"
        "两个项目也都是自己从零写出来的，遇到问题习惯先看源码和官方文档。"
        "不足主要有两点：一是没有真实的工作经验，工程规范和生产问题的排查经验不够；"
        "二是分布式这块，像分布式事务、服务治理，我只停留在理论，缺少实践。"
        "接下来的计划是把这两个项目再做深一点，然后补分布式和 JVM 调优的实战。"
    )),
]

DEFAULT_ANSWER = (
    "这个问题我理解得不算特别深，我按我知道的说一下。"
    "我在两个项目里接触过相关的东西，主要是从「先保证正确、再考虑性能」这个思路去做的，"
    "具体实现细节和踩过的坑我可能讲不全，如果哪里不对希望您指出来，我回去补一下。"
)


def pick_answer(question: str, used: set[int]) -> str:
    """
    按问题里的关键词挑一条最贴切的答案。

    优先挑**没用过**的：面试官常在追问里复述上一个话题（「HashMap 你答得不错，
    那我问个 JUC 的问题」），如果只看命中数，候选人会把 HashMap 那段再念一遍 ——
    实测就这么连出过两个 0 分。所以只要有没用过的条目命中，就先从里面挑。
    """
    q = question.lower()
    scored = [(sum(1 for k in keywords if k in q), idx)
              for idx, (keywords, _) in enumerate(ANSWER_BANK)]
    scored = [item for item in scored if item[0] > 0]
    if not scored:
        return DEFAULT_ANSWER
    fresh = [item for item in scored if item[1] not in used]
    hits, idx = max(fresh or scored)
    used.add(idx)
    return ANSWER_BANK[idx][1]


def unwrap(resp: requests.Response, what: str) -> object:
    if resp.status_code != 200:
        raise RuntimeError(f"{what} HTTP {resp.status_code}: {resp.text[:300]}")
    body = resp.json()
    if body.get("code") != 0:
        raise RuntimeError(f"{what} 业务失败：{body.get('msg')}")
    return body.get("data")


def wait_task(task_id: int, timeout: int = 600) -> dict:
    """订阅 Java 的 SSE，把进度打到屏幕上。"""
    resp = requests.get(f"{JAVA}/api/task/{task_id}/stream", stream=True, timeout=timeout)
    event = None
    last: dict = {}
    for raw in resp.iter_lines(decode_unicode=True):
        if raw is None:
            continue
        line = raw.strip()
        if not line:
            continue
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data = json.loads(line[5:].strip())
            if event == "progress":
                print(f"    [{data.get('progress'):>3}%] {data.get('stage', '')}")
            elif event in ("done", "error"):
                last = data
                break
    return last


def find_resume_pdf() -> Path:
    for path in sorted(Path("D:/beibei-data/upload").rglob("*.pdf")):
        return path
    raise SystemExit("D:/beibei-data/upload 下找不到 PDF，请用 --resume 指定")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--turns", type=int, default=5)
    parser.add_argument("--kb", type=int, default=0, help="联动出题用哪个知识库，0=自动挑一个")
    parser.add_argument("--resume", type=str, default="")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--no-seed-tags", action="store_true",
                        help="不临时造标签。默认会造，否则「按知识点名匹配标签」这条路径测不到")
    args = parser.parse_args()
    args.seed_linkage_tags = not args.no_seed_tags

    turns = max(5, min(20, args.turns))
    engine = get_engine()
    resume_path = Path(args.resume) if args.resume else find_resume_pdf()

    print("=" * 78)
    print("  背备不悲 · 模拟面试过网关验证（浏览器实际路径）")
    print("=" * 78)
    print(f"  网关：{JAVA}   简历：{resume_path.name}   轮数：{turns}")

    kb_id = args.kb
    kb_name = ""
    if not kb_id:
        with engine.connect() as conn:
            row = conn.execute(sql_text(
                "SELECT id, name FROM bb_knowledge_base ORDER BY id LIMIT 1")).fetchone()
        if row:
            kb_id, kb_name = int(row[0]), row[1]
    else:
        with engine.connect() as conn:
            kb_name = conn.execute(sql_text("SELECT name FROM bb_knowledge_base WHERE id=:i"),
                                   {"i": kb_id}).scalar() or ""
    print(f"  关联知识库：{kb_id or '（无）'} {kb_name}")
    print()

    # ---------- 1. 上传简历 ----------
    print("[1/6] 上传简历到 Java 网关")
    with open(resume_path, "rb") as fh:
        resp = requests.post(
            f"{JAVA}/api/resume/upload",
            files={"file": (resume_path.name, fh, "application/pdf")},
            timeout=120,
        )
    upload = unwrap(resp, "上传简历")
    resume_id, task_id = upload["resumeId"], upload["taskId"]
    print(f"    resumeId={resume_id}  taskId={task_id}  {upload['message']}")
    print()

    # ---------- 2. 等解析 ----------
    print("[2/6] 等解析完成（Java SSE 代理）")
    started = time.time()
    result = wait_task(task_id)
    print(f"    耗时 {time.time() - started:.1f}s，结果：{result}")
    if result.get("status") == 3:
        raise SystemExit(f"解析失败：{result.get('errorMsg')}")
    print()

    # ---------- 3. 简历详情 ----------
    print("[3/6] 简历详情（Java DTO 映射）")
    detail = unwrap(requests.get(f"{JAVA}/api/resume/{resume_id}", timeout=60), "简历详情")
    resume_vo, profile = detail["resume"], detail["profile"]
    print(f"    状态={resume_vo['status']} 字数={resume_vo['charCount']} "
          f"技能={resume_vo['skillCount']} 项目={resume_vo['projectCount']} 待核实={resume_vo['riskCount']}")
    print(f"    技能：{'、'.join(profile.get('skills') or [])}")
    print(f"    原文长度：{len(detail.get('rawText') or '')}")
    print()

    # ---------- 4. 面试 ----------
    print("[4/6] 开始面试并作答")
    start_body = {
        "resumeId": resume_id, "jobTitle": "Java 后端开发工程师",
        "kbId": kb_id or None, "difficulty": 2, "maxTurns": turns,
    }
    started_vo = unwrap(requests.post(f"{JAVA}/api/interview/start", json=start_body, timeout=180),
                        "开始面试")
    interview_id = started_vo["interviewId"]
    question = started_vo["question"]
    print(f"    interviewId={interview_id}")
    print(f"    第 1 题 [{question['type']}] {question['question'][:70]}")
    if question.get("basedOn"):
        print(f"           依据：{question['basedOn'][:60]}")

    finished = False
    scores: list[float] = []
    used_answers: set[int] = set()
    current_question = question["question"]

    for round_no in range(1, turns + 1):
        # 按当前问题的关键词挑答案，而不是按固定顺序念稿
        answer = pick_answer(current_question, used_answers)
        vo = unwrap(requests.post(f"{JAVA}/api/interview/{interview_id}/answer",
                                  json={"answer": answer}, timeout=180), "提交回答")
        evaluation = vo["evaluation"]
        scores.append(evaluation["score"])
        dims = evaluation["scores"]
        print(f"    第 {round_no:>2} 轮  得分 {evaluation['score']:>5.1f}  "
              f"(准确 {dims['techAccuracy']:.0f} / 具体 {dims['specificity']:.0f} / "
              f"结构 {dims['structure']:.0f} / 一致 {dims['consistency']:.0f} / "
              f"匹配 {dims['relevance']:.0f})")
        for problem in (evaluation.get("problems") or [])[:1]:
            print(f"           ⚠ {problem}")
        if vo.get("nextQuestion"):
            current_question = vo["nextQuestion"]["question"]
            print(f"           → [{vo['nextQuestion']['type']}] {current_question[:64]}")
        finished = vo["finished"]
        if finished:
            print("           轮数已用完")
            break
    print()

    # ---------- 5. 报告 ----------
    print("[5/6] 生成评估报告")
    started = time.time()
    detail = unwrap(requests.post(f"{JAVA}/api/interview/{interview_id}/finish", timeout=300),
                    "生成报告")
    report = detail["report"]
    print(f"    耗时 {time.time() - started:.1f}s，总分 {report.get('overallScore')}")
    print(f"    总评：{str(report.get('summary'))[:120]}")
    print(f"    薄弱知识点：{'、'.join(report.get('knowledgePoints') or [])}")
    print()

    # ---------- 6. 联动出题 ----------
    linkage = None
    seeded_tags: list[int] = []
    if kb_id:
        print("[6/6] 联动出题（薄弱知识点 → 专项题卷）")

        # 关联知识库里往往没有跟报告知识点同名的标签，那样就永远退化成分库出题，
        # 「按名字匹配」这条路径实际上从来没被测到。所以临时造两个标签来验证：
        #   一个与知识点完全同名，一个故意带层级后缀「篇」——
        # 后者专门验证 normalize() 会剥掉后缀（真实模型给的标签树就长这样：
        # 「MySQL篇」「Redis篇」，不剥的话 MySQL 永远匹配不上 MySQL篇）。
        points = report.get("knowledgePoints") or []
        if args.seed_linkage_tags and points:
            seed_names = [points[0], points[1] + "篇"] if len(points) > 1 else [points[0]]
            with engine.begin() as conn:
                root = conn.execute(sql_text(
                    "SELECT id FROM bb_tag WHERE kb_id=:k AND parent_id=0 ORDER BY id LIMIT 1"),
                    {"k": kb_id}).scalar() or 0
                for name in seed_names:
                    # chunk_count 给 1 是刻意的：Java 侧只拿「有内容的知识点」当候选
                    # （零分块的标签出不了题，匹配上也是白匹配）。
                    # 这里验证的是「知识点名 → 标签名」这段匹配逻辑，所以必须让它进候选集。
                    conn.execute(sql_text(
                        "INSERT INTO bb_tag (kb_id, parent_id, name, level, sort_order, origin, "
                        "chunk_count, question_count) "
                        "VALUES (:k, :p, :n, 2, 99, 2, 1, 0)"),
                        {"k": kb_id, "p": root, "n": name})
                    seeded_tags.append(conn.execute(sql_text("SELECT LAST_INSERT_ID()")).scalar())
            print(f"    （临时造了 {len(seeded_tags)} 个标签验证匹配：{'、'.join(seed_names)}）")

        linkage = unwrap(requests.post(
            f"{JAVA}/api/interview/{interview_id}/linkage-paper",
            json={"kbId": kb_id, "count": 5, "selfCheck": False}, timeout=180), "联动出题")
        print(f"    paperId={linkage['paperId']} taskId={linkage['taskId']}")
        for m in linkage.get("matches") or []:
            print(f"      · 「{m['point']}」 → 标签「{m['tagName']}」"
                  f"（#{m['tagId']}，{m['chunkCount']} 个分块）")
        print(f"    命中标签：{'、'.join(linkage['matchedTags']) or '（无）'}")
        print(f"    未匹配：{'、'.join(linkage['unmatchedPoints']) or '（无）'}")
        print(f"    说明：{linkage['message']}")
    else:
        print("[6/6] 跳过联动出题（没有可用知识库）")
    print()

    # ---------- 核对 ----------
    print("=" * 78)
    print("  核对")
    print("=" * 78)
    with engine.connect() as conn:
        iv = conn.execute(sql_text(
            "SELECT status, turn_count, total_score FROM bb_interview WHERE id=:i"),
            {"i": interview_id}).fetchone()
        candidates = conn.execute(sql_text(
            "SELECT COUNT(*) FROM bb_interview_turn WHERE interview_id=:i AND role=2"),
            {"i": interview_id}).scalar()
        interviewers = conn.execute(sql_text(
            "SELECT COUNT(*) FROM bb_interview_turn WHERE interview_id=:i AND role=1"),
            {"i": interview_id}).scalar()
        rstatus = conn.execute(sql_text("SELECT status FROM bb_resume WHERE id=:i"),
                               {"i": resume_id}).scalar()
        paper_ok = False
        if linkage:
            paper_ok = conn.execute(sql_text("SELECT COUNT(*) FROM bb_paper WHERE id=:i"),
                                    {"i": linkage["paperId"]}).scalar() == 1

    checks = [
        ("简历解析成功（status=2）", rstatus == 2, f"实际 {rstatus}"),
        ("面试已结束（status=2）", iv[0] == 2, f"实际 {iv[0]}"),
        ("提问数 = 回答数", interviewers == candidates, f"{interviewers} vs {candidates}"),
        ("轮数与回答数一致", iv[1] == candidates, f"{iv[1]} vs {candidates}"),
        ("总分已落库", iv[2] is not None, "total_score 为空"),
        ("报告有薄弱知识点", bool(report.get("knowledgePoints")), "knowledgePoints 为空"),
        ("联动题卷已创建", (not kb_id) or paper_ok, "bb_paper 里没有这张卷"),
        # 造了标签还匹配不上，说明 normalize() 的「剥层级后缀」没生效
        ("薄弱点能匹配到标签", (not seeded_tags) or len(linkage["matchedTags"]) >= len(seeded_tags),
         f"造了 {len(seeded_tags)} 个标签，只命中 {len(linkage['matchedTags']) if linkage else 0} 个"),
        # 零分块的标签出不了题，不该被当成命中项（kb 里全是这种残留标签时尤其明显）
        ("命中的标签都有分块", (not linkage) or all(
            (m.get("chunkCount") or 0) > 0 for m in linkage.get("matches") or []),
         "命中了零分块的标签：" + "、".join(
             m["tagName"] for m in (linkage or {}).get("matches") or []
             if (m.get("chunkCount") or 0) <= 0)),
    ]
    all_ok = True
    for name, ok, hint in checks:
        print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + ("" if ok else f"  ← {hint}"))
        all_ok = all_ok and ok

    print()
    print(f"  问答轮数 {candidates}，平均分 {sum(scores) / max(1, len(scores)):.1f}")
    print(f"  结论：{'全部通过 ✅' if all_ok else '存在失败项 ❌'}")

    if not args.keep:
        with engine.begin() as conn:
            # 先删临时造的验证标签，再删题卷 —— 顺序反了会留下悬空标签
            for tag_id in seeded_tags:
                conn.execute(sql_text("DELETE FROM bb_tag WHERE id=:t"), {"t": tag_id})
            if linkage:
                conn.execute(sql_text("DELETE FROM bb_paper_item WHERE paper_id=:p"),
                             {"p": linkage["paperId"]})
                conn.execute(sql_text("DELETE FROM bb_paper WHERE id=:p"), {"p": linkage["paperId"]})
                conn.execute(sql_text(
                    "DELETE q FROM bb_question q WHERE NOT EXISTS "
                    "(SELECT 1 FROM bb_paper_item pi WHERE pi.question_id = q.id)"))
            conn.execute(sql_text("DELETE FROM bb_interview_turn WHERE interview_id=:i"),
                         {"i": interview_id})
            conn.execute(sql_text("DELETE FROM bb_interview WHERE id=:i"), {"i": interview_id})
            conn.execute(sql_text("DELETE FROM bb_resume WHERE id=:i"), {"i": resume_id})
        print("  测试数据已清理（--keep 可保留）")
    else:
        print(f"  已保留：interviewId={interview_id} resumeId={resume_id} "
              f"临时标签={seeded_tags}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
