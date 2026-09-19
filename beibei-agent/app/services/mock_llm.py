"""
背备不悲 · Mock 模型（无 API Key 的演示 / 测试模式）

它**不是返回硬编码假数据**，而是真的从 Prompt 里的材料中抽取内容来构造结果：
  - 出题：从检索到的原文分块里抽句子，生成填空/单选/简答题
  - 知识点树：从材料的标题路径里还原层级
  - 判分：按 rubric 要点与答案的字面重合度给分

这样做的价值：
  1. 没有 API Key 时也能把「出题 → 自检 → 查重 → 审核 → 入库」整条链路跑通并验证
  2. 开发期不必反复烧 Token
  3. 单元测试与回归测试有一个稳定、可复现的模型替代品

⚠️ 它是**功能演示**，不是命题质量方案。真实的题目质量请配置 DeepSeek 等云端模型。
"""

from __future__ import annotations

import json
import logging
import random
import re
from typing import Any

logger = logging.getLogger(__name__)

# 句末标点：中英文都覆盖
SENT_SPLIT = re.compile(r"(?<=[。！？；!?;])\s*")
# 出题材料里每个分块的头部：[chunkId=123 | 文档：xx | 第5页 | 第3章 > Redis]
CHUNK_HEAD = re.compile(
    r"\[chunkId=(\d+)(?:\s*\|([^\]]*))?\]\s*\n(.*?)(?=\n\[chunkId=|\Z)", re.S
)
# 中文里的关键术语：连续的中英文/数字串，长度 2~18
TERM = re.compile(r"[A-Za-z][A-Za-z0-9+#.\-]{1,17}|[\u4e00-\u9fff]{2,10}")
STOP = {
    "一个", "这个", "可以", "就是", "因为", "所以", "如果", "以及", "或者", "通过",
    "使用", "进行", "实现", "需要", "我们", "他们", "它们", "这些", "那些", "什么",
    "以下", "上述", "例如", "比如", "注意", "但是", "而且", "并且", "用于", "属于",
}


# ---------------------------------------------------------------------------
#  入口
# ---------------------------------------------------------------------------

def mock_completion(task_type: str, messages: list[dict[str, str]]) -> str:
    """按任务类型分派，返回一个 JSON 字符串（和真实模型一样）。"""
    prompt = messages[-1].get("content", "") if messages else ""

    handlers = {
        "QUESTION_GEN": _gen_questions,
        "CLASSIFY": _gen_tag_tree,
        "CLASSIFY_TAG": _gen_tag_tree,
        "CHUNK_TAG": _tag_chunk,
        "SELF_CHECK": _self_check,
        "GRADING": _grade,
        "RECITE_CHECK": _recite_check,
        # 模拟面试四件套
        "RESUME_PARSE": _resume_parse,
        "INTERVIEW_ASK": _interview_ask,
        "INTERVIEW_EVAL": _interview_eval,
        "INTERVIEW_REPORT": _interview_report,
    }
    handler = handlers.get(task_type or "", _fallback)
    try:
        return json.dumps(handler(prompt), ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Mock 生成失败（%s）：%s", task_type, exc)
        return json.dumps(handler and {"ok": True} or {}, ensure_ascii=False)


def _fallback(prompt: str) -> dict[str, Any]:
    return {"ok": True, "mock": True, "note": "Mock 模型未针对该任务实现具体逻辑"}


# ---------------------------------------------------------------------------
#  出题
# ---------------------------------------------------------------------------

def _parse_chunks(prompt: str) -> list[dict[str, Any]]:
    """从【命题材料】里解析出分块。"""
    head = prompt.find("【命题材料】")
    tail = prompt.find("【命题要求】")
    segment = prompt[head:tail] if head != -1 and tail > head else prompt

    chunks: list[dict[str, Any]] = []
    for match in CHUNK_HEAD.finditer(segment):
        meta = match.group(2) or ""
        body = (match.group(3) or "").strip()
        if not body:
            continue
        page = 0
        pm = re.search(r"第(\d+)页", meta)
        if pm:
            page = int(pm.group(1))
        chunks.append({
            "chunkId": int(match.group(1)),
            "meta": meta.strip(),
            "text": body,
        })

    # 没有 [chunkId=] 格式时，退化成按空行切
    if not chunks and segment.strip():
        chunks = [{"chunkId": 0, "meta": "", "text": p.strip()}
                  for p in re.split(r"\n\s*\n", segment) if len(p.strip()) > 30]
    return chunks


def _sentences(text: str) -> list[str]:
    """切句，并过滤掉代码碎片 —— 只含少量中文、大量符号的句子做不了好题面。"""
    out = []
    for s in SENT_SPLIT.split(text):
        s = re.sub(r"\s+", " ", s).strip()
        if not (12 <= len(s) <= 220):
            continue
        cjk = sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff")
        # 至少 8 个汉字才算一句正常的知识陈述；否则多半是代码或表格残片
        if cjk < 8 and not s.isascii():
            continue
        if cjk < 8 and s.count("`") + s.count("{") + s.count("}") > 2:
            continue
        out.append(s)
    return out


def _terms(text: str, limit: int = 8) -> list[str]:
    seen: list[str] = []
    for m in TERM.finditer(text):
        t = m.group(0)
        if t in STOP or t in seen:
            continue
        seen.append(t)
        if len(seen) >= limit:
            break
    return seen


def _gen_questions(prompt: str) -> dict[str, Any]:
    rng = random.Random(20260917)   # 固定种子 => 结果可复现，便于回归测试

    count = 10
    m = re.search(r"生成\s*(\d+)\s*道题", prompt)
    if m:
        count = max(1, min(60, int(m.group(1))))

    q_type_ratio = _parse_json_field(prompt, "题型配比") or {
        "SINGLE": 0.4, "JUDGE": 0.2, "BLANK": 0.2, "SHORT": 0.2
    }
    diff_ratio = _parse_json_field(prompt, "难度配比") or {"EASY": 0.3, "MEDIUM": 0.5, "HARD": 0.2}
    tag_hint = _parse_text_field(prompt, "覆盖知识点") or ""
    tag_ids = [int(t) for t in re.findall(r"#(\d+)", tag_hint)][:2]
    chunks = _parse_chunks(prompt)
    if not chunks:
        return {"questions": []}

    # 把所有分块的句子汇集起来，按分块分组以便正确标注 sourceChunkIds
    pool: list[tuple[int, str]] = []
    for ch in chunks:
        for s in _sentences(ch["text"]):
            pool.append((ch["chunkId"], s))
    if not pool:
        return {"questions": []}
    rng.shuffle(pool)

    types = _expand_ratio(q_type_ratio, count)
    # 难度必须用 _DIFF_ALIAS，不能用题型别名表
    diffs = _expand_ratio(diff_ratio, count, _DIFF_ALIAS)

    # 干扰项素材：所有句子
    all_sentences = [s for _, s in pool]

    questions: list[dict[str, Any]] = []
    used_sentences: set[str] = set()

    for index in range(count):
        q_type = types[index] if index < len(types) else "SHORT"
        difficulty = _diff_code(diffs[index] if index < len(diffs) else "MEDIUM")

        # 找一个没用过的句子
        picked = None
        for chunk_id, sentence in pool:
            if sentence not in used_sentences:
                picked = (chunk_id, sentence)
                used_sentences.add(sentence)
                break
        if picked is None:
            break
        chunk_id, sentence = picked

        tag_ids = [int(t) for t in re.findall(r"#(\d+)", tag_hint)][:2]
        base = {
            "difficulty": difficulty,
            "tagIds": tag_ids,
            "sourceChunkIds": [chunk_id] if chunk_id else [],
        }

        if q_type == "SINGLE":
            base.update(_make_single(sentence, all_sentences, rng))
        elif q_type == "MULTI":
            base.update(_make_multi(sentence, all_sentences, rng))
        elif q_type == "JUDGE":
            base.update(_make_judge(sentence, rng))
        elif q_type == "BLANK":
            base.update(_make_blank(sentence))
        else:
            base.update(_make_short(sentence))

        base["qType"] = q_type
        base["fullScore"] = 5 if q_type in ("SINGLE", "MULTI", "JUDGE", "BLANK") else 10
        questions.append(base)

    return {"questions": questions}


def _make_single(sentence: str, others: list[str], rng: random.Random) -> dict[str, Any]:
    """
    用「同一批材料里的其它句子」当干扰项。

    早先的做法是从句子里切中文片段当选项，切出来的是「在的数据」这种碎片，毫无意义。
    改成整句作选项后，干扰项都是真实的知识点陈述，学生必须真正理解才能选对。
    """
    keys = _terms(sentence, limit=3)
    topic = keys[0] if keys else sentence[:10]

    correct = _shorten(sentence, 90)
    distractors: list[str] = []
    for candidate in others:
        if candidate == sentence or _shorten(candidate, 90) == correct:
            continue
        # 干扰项要「像但不是」：优先选同章节附近的句子
        text = _shorten(candidate, 90)
        if text not in distractors:
            distractors.append(text)
        if len(distractors) >= 3:
            break
    while len(distractors) < 3:
        distractors.append(f"（材料中未提及的说法 {len(distractors) + 1}）")

    options = [{"key": k, "content": c} for k, c in zip("ABCD", [correct] + distractors)]
    rng.shuffle(options)
    correct_key = next(o["key"] for o in options if o["content"] == correct)

    return {
        "stem": f"关于「{topic}」，下列说法与讲义一致的是？",
        "options": options,
        "answer": correct_key,
        "analysis": f"原文：「{sentence[:80]}」",
        "codeSnippet": None,
        "rubric": None,
    }


def _make_multi(sentence: str, others: list[str], rng: random.Random) -> dict[str, Any]:
    """多选：正确项来自原句，干扰项来自其它句子。"""
    keys = _terms(sentence, limit=2)
    correct = [_shorten(sentence, 80)]
    if len(keys) >= 2:
        correct.append(f"材料强调了「{keys[1]}」这一点")

    distractors: list[str] = []
    for candidate in others:
        if candidate == sentence:
            continue
        text = _shorten(candidate, 80)
        if text not in distractors and text not in correct:
            distractors.append(text)
        if len(distractors) >= 2:
            break
    while len(distractors) < 2:
        distractors.append(f"（材料中未提及的说法 {len(distractors) + 1}）")

    options = [{"key": k, "content": c} for k, c in zip("ABCD", correct + distractors)]
    rng.shuffle(options)
    correct_keys = sorted(o["key"] for o in options if o["content"] in correct)

    return {
        "stem": f"多选：下列关于「{keys[0] if keys else sentence[:8]}」的表述，哪些在材料中出现过？",
        "options": options,
        "answer": "".join(correct_keys),
        "analysis": f"原文：「{sentence[:80]}」",
        "codeSnippet": None,
        "rubric": None,
    }


def _make_judge(sentence: str, rng: random.Random) -> dict[str, Any]:
    """
    判断题：约 40% 的概率制造错误说法。

    制造方式只在**英文/技术术语之间互换**（Redis ↔ Spring Boot 这种），
    不动中文 —— 早先按中文片段替换会切出「Boot Boot 的自动装配」这种鬼东西。
    """
    latin = [t for t in _terms(sentence, limit=6) if t.isascii() and len(t) >= 3]
    if rng.random() < 0.4 and len(latin) >= 2:
        wrong = sentence.replace(latin[0], latin[1], 1)
        if wrong != sentence:
            return {
                "stem": f"判断：{wrong}",
                "options": None,
                "answer": "错误",
                "analysis": f"题面把「{latin[0]}」换成了「{latin[1]}」，与原文不符。原文：{sentence[:70]}",
                "codeSnippet": None,
                "rubric": None,
            }
    return {
        "stem": f"判断：{sentence}",
        "options": None,
        "answer": "正确",
        "analysis": "该说法与讲义原文一致。",
        "codeSnippet": None,
        "rubric": None,
    }


def _shorten(text: str, limit: int) -> str:
    """清洗并截断。顺手去掉首尾的代码符号，避免出现「` 并由 JDBC 设置参数」这种碎片。"""
    text = re.sub(r"\s+", " ", text).strip().strip("`*#> -")
    if len(text) > limit:
        text = text[:limit] + "…"
    return text


def _make_blank(sentence: str) -> dict[str, Any]:
    keys = _terms(sentence, limit=3)
    answer = keys[0] if keys else ""
    stem = sentence.replace(answer, "______", 1) if answer else sentence
    return {
        "stem": f"填空：{stem}",
        "options": None,
        "answer": answer or sentence[:20],
        "analysis": f"原文：{sentence[:70]}…",
        "codeSnippet": None,
        "rubric": None,
    }


def _make_short(sentence: str) -> dict[str, Any]:
    keys = _terms(sentence, limit=6)
    topic = keys[0] if keys else sentence[:12]

    points: list[dict[str, Any]] = []
    if len(sentence) > 70:
        parts = [p.strip() for p in re.split(r"[，,；;]", sentence) if len(p.strip()) > 6]
        for part in parts[:3]:
            points.append({"point": part[:60], "score": round(10 / max(1, min(3, len(parts))), 1)})
    if not points:
        points = [{"point": sentence[:60], "score": 10.0}]

    total = sum(p["score"] for p in points)
    if total != 10:
        points[-1]["score"] = round(points[-1]["score"] + (10 - total), 1)

    return {
        "stem": f"请简述「{topic}」的相关要点。",
        "options": None,
        "answer": sentence,
        "analysis": f"答案要点来自原文：「{sentence[:70]}…」。",
        "codeSnippet": None,
        "rubric": points,
    }


# ---------------------------------------------------------------------------
#  知识点树
# ---------------------------------------------------------------------------

def _gen_tag_tree(prompt: str) -> dict[str, Any]:
    """
    从材料里的标题路径还原多级知识点树。

    文档解析阶段已经还原出了「A > B > C」形式的 section_path，
    这里直接按 ' > ' 拆开就能得到真实的层级结构 —— 比让模型凭空猜准得多。
    """
    tree: dict[str, Any] = {}

    # 优先用「A > B > C」形式的标题路径
    for raw_line in prompt.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("【", "#", "-", "{")):
            continue
        parts = [p.strip() for p in line.split(">")]
        if len(parts) < 2:
            continue
        if any(not p or len(p) > 40 for p in parts):
            continue
        # 顶层如果是文档名，跳过它，让章节成为顶层
        if len(parts) >= 3 and ("讲义" in parts[0] or "教材" in parts[0] or len(parts[0]) > 20):
            parts = parts[1:]
        node = tree
        for part in parts[:3]:
            node = node.setdefault(part, {})

    # 没找到路径就用「第X章 XXX」这种标题
    if not tree:
        for m in re.finditer(r"第[一二三四五六七八九十百\d]+[章节部分][ 　]*([^\n，。>]{2,24})", prompt):
            name = m.group(1).strip()
            if name:
                tree.setdefault(name, {})

    # 还是没有就从术语里凑
    if not tree:
        for t in _terms(prompt, limit=8):
            tree[t] = {}

    def render(node: dict[str, Any], parent: str = "") -> list[dict[str, Any]]:
        out = []
        for name, children in list(node.items())[:12]:
            desc = f"{parent}下的考点：{name}" if parent else f"材料中的模块：{name}"
            out.append({
                "name": name[:30],
                "description": desc[:80],
                "children": render(children, name) if children else [],
            })
        return out

    return {"tags": render(tree)}


def _tag_chunk(prompt: str) -> dict[str, Any]:
    """按词面重合度给分块挑知识点。"""
    candidates = re.findall(r"^(\d+):\s*(.+?)\s*-\s*(.*)$", prompt, re.M)
    body = prompt.split("【原文】")[-1] if "【原文】" in prompt else prompt

    scored: list[tuple[int, int]] = []
    for cid, name, _desc in candidates:
        name = name.strip()
        if not name:
            continue
        score = body.count(name)
        # 名称里的每个字都出现也算弱相关
        if score == 0 and len(name) >= 2:
            if all(ch in body for ch in name):
                score = 1
        if score > 0:
            scored.append((score, int(cid)))

    scored.sort(reverse=True)
    picked = [cid for _, cid in scored[:3]]
    return {"tagIds": picked, "reason": "Mock：按知识点名称在原文中的出现次数匹配"}


# ---------------------------------------------------------------------------
#  判分
# ---------------------------------------------------------------------------

def _grade(prompt: str) -> dict[str, Any]:
    rubric = _parse_rubric(prompt)
    user_answer = _parse_text_field(prompt, "学生答案") or ""
    context = _parse_text_field(prompt, "教材原文依据") or ""
    full_score = _parse_float(prompt, r"本题满分\s*[:：]?\s*([\d.]+)") or 10.0

    if not user_answer.strip():
        return {
            "score": 0.0,
            "hitPoints": [],
            "missPoints": [{"point": p["point"], "hint": "未作答"} for p in rubric],
            "wrongPoints": [],
            "citations": [],
            "feedback": "未作答。",
        }

    hit, miss, wrong = [], [], []
    total = 0.0
    answer_compact = re.sub(r"\s+", "", user_answer)

    for point in rubric:
        text = point["point"]
        keywords = [k for k in _terms(text, limit=6) if len(k) >= 2]
        matched = sum(1 for k in keywords if k in answer_compact)
        ratio = matched / len(keywords) if keywords else 0.0

        if ratio >= 0.5:
            hit.append({"point": text, "score": point["score"]})
            total += point["score"]
        elif ratio > 0:
            half = round(point["score"] / 2 * 2) / 2
            hit.append({"point": text, "score": half})
            total += half
            miss.append({"point": text, "hint": f"只答出一部分，还差：{'、'.join(k for k in keywords if k not in answer_compact)[:40]}"})
        else:
            miss.append({"point": text, "hint": f"未提及该要点，应包含：{'、'.join(keywords[:3])}"})

    total = min(total, full_score)

    citations = []
    for m in re.finditer(r"\[chunkId=(\d+)", context):
        citations.append({"chunkId": int(m.group(1)), "quote": "（Mock 模式未生成引文）"})
        if len(citations) >= 2:
            break

    feedback = (
        f"命中 {len(hit)} 个要点，漏掉 {len(miss)} 个。"
        if miss else f"要点全部命中，得 {total} 分。"
    )
    return {
        "score": round(total, 1),
        "hitPoints": hit,
        "missPoints": miss,
        "wrongPoints": wrong,
        "citations": citations,
        "feedback": feedback + "（Mock 模式按要点关键词重合度估算，仅用于流程验证）",
    }


def _recite_check(prompt: str) -> dict[str, Any]:
    content = _parse_text_field(prompt, "原文") or ""
    recite = _parse_text_field(prompt, "学生复述") or ""

    src_terms = set(_terms(content, limit=40))
    said = set(_terms(recite, limit=40))
    hit = sorted(src_terms & said)
    miss = sorted(src_terms - said)
    coverage = int(100 * len(hit) / max(1, len(src_terms)))

    return {
        "coverageScore": coverage,
        "hitPoints": hit[:10],
        "missPoints": miss[:10],
        "wrongPoints": [],
        "feedback": f"覆盖了 {len(hit)}/{len(src_terms)} 个关键术语。（Mock 模式估算）",
    }


def _self_check(prompt: str) -> dict[str, Any]:
    """Mock 的自检：检查题目 JSON 是否结构完整。"""
    question_json = _parse_text_field(prompt, "题目") or ""
    try:
        start = question_json.find("{")
        end = question_json.rfind("}")
        q = json.loads(question_json[start:end + 1]) if start != -1 else {}
    except (json.JSONDecodeError, ValueError):
        q = {}

    problems = []
    if not q.get("stem"):
        problems.append("缺少题干")
    if q.get("qType") in ("SINGLE", "MULTI"):
        options = q.get("options") or []
        if len(options) < 4:
            problems.append(f"{q.get('qType')} 题只有 {len(options)} 个选项")
        if not q.get("answer"):
            problems.append("选择题没有答案")
    if q.get("qType") in ("SHORT", "TERM", "ESSAY", "COMPARE"):
        rubric = q.get("rubric") or []
        if not rubric:
            problems.append("主观题缺少 rubric")
        else:
            total = sum(float(p.get("score", 0)) for p in rubric)
            full = float(q.get("fullScore") or 0)
            if full and abs(total - full) > 0.01:
                problems.append(f"rubric 分值合计 {total} 与满分 {full} 不一致")

    passed = not problems
    return {
        "pass": passed,
        "score": 0.9 if passed else 0.4,
        "reason": "结构完整。" if passed else "；".join(problems),
    }


# ---------------------------------------------------------------------------
#  模拟面试（Mock）
#  没有真实 API Key 时，用规则法把整条面试链路跑通：
#  从简历原文抽技能 → 按技能逐轮提问 → 按「回答长度 + 关键词命中」打分 → 汇总报告。
#  ⚠️ 这不是「假数据」：技能和项目名都真的来自那份简历，
#     所以链路验证（落库、轮次、报告结构、联动出题）是完全可信的。
# ---------------------------------------------------------------------------

# 常见技术名词，用来从简历原文里捞技能
_TECH_WORDS = (
    "Java", "Spring Boot", "Spring Cloud", "Spring MVC", "Spring", "MyBatis",
    "MyBatis-Plus", "MySQL", "Redis", "MongoDB", "Elasticsearch", "Kafka",
    "RabbitMQ", "RocketMQ", "Nginx", "Docker", "Kubernetes", "K8s", "Linux",
    "Nacos", "Sentinel", "Gateway", "Feign", "Seata", "ShardingSphere",
    "JVM", "GC", "多线程", "并发", "集合", "锁", "分布式", "微服务", "缓存",
    "SQL 优化", "索引", "事务", "设计模式", "Netty", "Dubbo", "Zookeeper",
    "Vue", "React", "JavaScript", "TypeScript", "Python", "Go", "Git", "Maven",
    "Jenkins", "Prometheus", "Grafana", "SkyWalking", "ELK", "MinIO", "OSS",
    "RESTful", "JWT", "OAuth2", "微服务治理", "限流", "熔断", "幂等",
    "Tomcat", "Hadoop", "Spark", "Flink", "Hive",
)

_TECH_ALIASES = {
    "k8s": "Kubernetes", "springboot": "Spring Boot", "springcloud": "Spring Cloud",
    "mybatisplus": "MyBatis-Plus", "mysql索引": "索引", "juc": "并发",
}

# 简历里出现这些词 → 面试官应该追问核实
_RISK_WORDS = ("精通", "熟练掌握", "架构", "主导", "负责整体", "高并发",
               "千万级", "从 0 到 1", "亿级", "优化了", "提升了")


def _mock_skills(text: str, limit: int = 12) -> list[str]:
    """从简历原文里捞技术名词，按技术词表顺序去重。"""
    lowered = text.lower()
    found: list[str] = []
    for word in _TECH_WORDS:
        if word.lower() in lowered and word not in found:
            found.append(word)
    for alias, canonical in _TECH_ALIASES.items():
        if alias in lowered and canonical not in found:
            found.append(canonical)
    return found[:limit]


def _resume_parse(prompt: str) -> dict[str, Any]:
    """从简历原文抽一份结构化档案（规则法）。"""
    raw = _parse_text_field(prompt, "简历原文") or prompt
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]

    name = ""
    for ln in lines[:6]:
        candidate = re.sub(r"[\s|·•]+", "", ln)
        if 2 <= len(candidate) <= 4 and all("\u4e00" <= ch <= "\u9fff" for ch in candidate):
            name = candidate
            break

    years = 0
    ym = re.search(r"(\d+)\s*年(?:以上)?(?:工作)?经验", raw)
    if ym:
        years = int(ym.group(1))

    education = ""
    for degree in ("博士", "硕士", "本科", "大专", "专科"):
        if degree in raw:
            education = degree
            break

    school = ""
    sm = re.search(r"([\u4e00-\u9fff]{2,12}(?:大学|学院|职业技术学院))", raw)
    if sm:
        school = sm.group(1)

    major = ""
    mm = re.search(r"(计算机科学与技术|软件工程|信息管理|电子信息工程|网络工程|通信工程|人工智能|数据科学)", raw)
    if mm:
        major = mm.group(1)

    skills = _mock_skills(raw)

    projects: list[dict[str, Any]] = []
    for line in lines:
        if not any(k in line for k in ("项目", "系统", "平台")) or len(line) < 8:
            continue
        if len(projects) >= 4:
            break
        title = re.split(r"[：:，,。.、]", line)[0][:40]
        stack = [s for s in skills if s.lower() in line.lower()]
        period_match = re.search(r"20\d{2}[.\-/年]\d{1,2}", line)
        projects.append({
            "name": title,
            "role": "开发" if "开发" in line else "",
            "period": period_match.group(0) if period_match else "",
            "techStack": stack,
            "highlights": [line[:120]],
            "evidence": line[:160],
        })

    risks = [w for w in _RISK_WORDS if w in raw][:5]

    return {
        "name": name,
        "years": years,
        "education": education,
        "school": school,
        "major": major,
        "currentCompany": "",
        "currentTitle": "Java 开发工程师" if "Java" in raw else "",
        "targetPosition": "Java 后端开发工程师" if "Java" in raw else "",
        "skills": skills,
        "projects": projects,
        "workExperience": [],
        "selfEvaluation": "",
        "highlights": skills[:5],
        "risks": risks,
    }


def _interview_skills_from_profile(prompt: str) -> tuple[list[str], list[str], list[str]]:
    """从渲染后的 prompt 里取（技能, 项目名, 风险点）。"""
    profile = _parse_text_field(prompt, "候选人简历档案") or ""
    skills: list[str] = []
    for line in profile.splitlines():
        if line.strip().startswith("- 技能："):
            skills = [s.strip() for s in line.split("：", 1)[1].split("、") if s.strip()]
            break
    projects = re.findall(r"《(.+?)》", profile)
    risks: list[str] = []
    in_risk = False
    for line in profile.splitlines():
        if "需要面试官重点核实的点" in line:
            in_risk = True
            continue
        if in_risk:
            stripped = line.strip()
            if stripped.startswith("·"):
                risks.append(stripped.lstrip("· ").strip())
            elif stripped.startswith("-"):
                break
    return skills, projects, risks


def _interview_ask(prompt: str) -> dict[str, Any]:
    """按轮次轮换提问：自我介绍 → 项目追问 → 技能八股 → 风险点核实。"""
    m = re.search(r"这是第\s*(\d+)\s*轮", prompt)
    turn_no = int(m.group(1)) if m else 1

    skills, projects, risks = _interview_skills_from_profile(prompt)
    asked_block = _parse_text_field(prompt, "已问过的问题") or ""
    asked_count = len(re.findall(r"^\s*\d+\.", asked_block, re.M))

    if turn_no == 1:
        return {
            "question": "先做个自我介绍吧，重点讲一下你最近一段工作/项目里主要负责什么。",
            "type": "INTRO",
            "basedOn": "简历开头",
            "expects": ["教育背景", "技术栈", "最近一段经历", "自己负责的部分"],
        }

    # 第 2~3 轮先追问项目，之后技能与风险点交替
    pool: list[tuple[str, str]] = []
    for i, proj in enumerate(projects):
        pool.append((
            f"你简历里的《{proj}》，能展开讲讲你具体做了哪部分吗？"
            f"遇到的最大技术难点是什么，最后怎么解决的？",
            proj,
        ))
    for skill in skills:
        pool.append((
            f"你简历里写了 {skill}，说说你在项目里是怎么用它的？"
            f"如果让你重新设计一遍，你会改哪里？",
            skill,
        ))
    for risk in risks:
        pool.append((
            f"简历里提到「{risk}」，能用一个具体的例子说明吗？"
            f"当时的数据或指标是多少？",
            risk,
        ))
    if not pool:
        pool = [("讲讲你最近解决过的一个线上问题，从发现到修复的完整过程。", "")]

    question, based_on = pool[asked_count % len(pool)]
    qtype = "PROJECT" if based_on in projects else ("FOLLOWUP" if based_on in risks else "TECH")
    return {
        "question": question,
        "type": qtype,
        "basedOn": based_on,
        "expects": [based_on] if based_on else [],
    }


def _interview_eval(prompt: str) -> dict[str, Any]:
    """评分：回答长度 + 与期望要点/简历关键词的重合度。"""
    answer = _parse_text_field(prompt, "候选人回答") or ""
    expects_block = _parse_text_field(prompt, "期望覆盖的要点") or ""
    evidence = _parse_text_field(prompt, "简历相关原文") or ""

    answer_terms = set(_terms(answer, limit=30))
    key_terms = set(_terms(expects_block + evidence, limit=30))
    hit = answer_terms & key_terms
    overlap = len(hit) / max(1, len(key_terms))

    length = len(answer)
    if length >= 220:
        length_score = 90
    elif length >= 120:
        length_score = 78
    elif length >= 60:
        length_score = 62
    elif length >= 25:
        length_score = 45
    else:
        length_score = 28

    specificity = min(100, int(length_score * 0.6 + overlap * 100 * 0.4))
    tech = min(100, int(50 + overlap * 100 * 0.5)) if answer_terms else 30
    structure = 85 if any(w in answer for w in ("首先", "其次", "然后", "最后", "第一步", "背景")) else length_score
    consistency = 88  # 规则法无法真正核对，给中性偏上
    relevance = min(100, int(length_score * 0.5 + overlap * 100 * 0.5))

    scores = {
        "techAccuracy": max(0, min(100, tech)),
        "specificity": max(0, min(100, specificity)),
        "structure": max(0, min(100, structure)),
        "consistency": consistency,
        "relevance": max(0, min(100, relevance)),
    }
    total = round(sum(scores.values()) / len(scores))

    problems: list[str] = []
    good: list[str] = []
    if length < 60:
        problems.append("回答过短，只有结论没有过程，面试官无法判断深度")
    else:
        good.append(f"回答长度 {length} 字，展开程度可以")
    if overlap > 0:
        good.append("命中关键要点：" + "、".join(sorted(hit)[:5]))
    else:
        problems.append("没有提到问题关心的关键技术点")
    if not any(w in answer for w in ("首先", "其次", "然后", "背景", "结果")):
        problems.append("缺少「背景 → 方案 → 结果」的结构")

    return {
        "scores": scores,
        "score": total,
        "goodPoints": good,
        "problems": problems,
        "suggestion": "补充具体数据与个人取舍，把「我负责」讲成「我做了什么、为什么这么做、结果如何」。",
        "contradiction": "",
        "followUpNeeded": length < 120,
    }


def _transcript_block(prompt: str) -> str:
    """
    取【完整面试记录】那一段。

    不能直接用 `_parse_text_field` —— 转录文本自己就含 `【面试官·...】` / `【候选人】`
    这样的行首标记，按 `(?=\\n【)` 截断会只剩第一题。这里改成找结尾哨兵。
    """
    head = prompt.find("【完整面试记录】")
    if head == -1:
        return ""
    body = prompt[head + len("【完整面试记录】"):].lstrip("\n")
    for marker in ("\n要求：", "\n严格只输出"):
        idx = body.find(marker)
        if idx != -1:
            body = body[:idx]
    return body.strip()


def _interview_report(prompt: str) -> dict[str, Any]:
    """汇总报告：简历里写了但候选人**从没在回答里提到**的技能 → 薄弱项。"""
    transcript = _transcript_block(prompt)
    profile = _parse_text_field(prompt, "候选人简历档案") or ""

    round_scores = [float(x) for x in re.findall(r"本轮得分\s*(\d+(?:\.\d+)?)", transcript)]
    overall = round(sum(round_scores) / len(round_scores)) if round_scores else 60

    skills: list[str] = []
    for line in profile.splitlines():
        if line.strip().startswith("- 技能："):
            skills = [s.strip() for s in line.split("：", 1)[1].split("、") if s.strip()]
            break

    answers = "\n".join(re.findall(r"【候选人】[^\n]*\n(.*?)(?=\n【|\Z)", transcript, re.S))
    mentioned = {s for s in skills if s.lower() in answers.lower()}
    missing = [s for s in skills if s not in mentioned]

    weak_points = [
        {
            "skill": s,
            "level": "未验证",
            "evidence": f"简历里写了 {s}，但整场面试的回答中没有展开讲过它",
            "suggestion": f"准备一个用到 {s} 的具体案例：场景、你的做法、踩过的坑、最终指标。",
        }
        for s in missing[:6]
    ]
    for skill in list(mentioned)[:2]:
        weak_points.append({
            "skill": skill,
            "level": "待深化",
            "evidence": f"提到了 {skill}，但缺少量化结果",
            "suggestion": f"给 {skill} 的案例补上前后对比数据。",
        })

    dimensions = [
        {"name": "技术准确性", "score": overall, "comment": "Mock 模式按关键词命中估算。"},
        {"name": "项目具体性", "score": max(30, overall - 8), "comment": "回答普遍偏结论，缺少个人取舍。"},
        {"name": "表达结构", "score": max(30, overall - 3), "comment": "结构尚可，可再强化结论先行。"},
        {"name": "与简历一致性", "score": 88, "comment": "Mock 模式不做真实核对。"},
        {"name": "岗位匹配度", "score": overall, "comment": "技能栈与岗位基本吻合。"},
    ]

    knowledge_points = [w["skill"] for w in weak_points][:6] or skills[:5]

    return {
        "overallScore": overall,
        "summary": (
            f"整场面试共 {len(round_scores)} 轮，综合得分 {overall}。"
            + ("技能覆盖面尚可，但回答普遍停留在「做了什么」，缺少「为什么这么做」和量化结果。"
               if overall < 75 else
               "整体表达与技术基础合格，个别技能点缺少实证，建议按薄弱项逐个补案例。")
            + "（Mock 模式估算，配置真实 API Key 后结论才有参考价值）"
        ),
        "dimensions": dimensions,
        "strengths": list(mentioned)[:5] or ["表达流畅"],
        "weakPoints": weak_points,
        "knowledgePoints": knowledge_points,
        "nextSteps": [f"针对 {kp} 各准备一个 STAR 案例" for kp in knowledge_points[:3]],
    }


# ---------------------------------------------------------------------------
#  解析工具
# ---------------------------------------------------------------------------

def _parse_json_field(prompt: str, label: str) -> dict[str, Any] | None:
    """解析 `label：{...}` 形式，兼容列表写法 `label：[SINGLE, SHORT]`。"""
    m = re.search(re.escape(label) + r"[^\n]*(\{.*?\}|\[.*?\])", prompt, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1).replace("'", '"'))
    except json.JSONDecodeError:
        # 兼容 [SINGLE, SHORT] 这种不加引号的写法
        raw = m.group(1).strip("[]")
        items = [x.strip().strip('"\'') for x in raw.split(",") if x.strip()]
        return {item: 1.0 for item in items} if items else None


def _parse_text_field(prompt: str, label: str) -> str | None:
    """
    取字段值。支持两种写法：
      【label】\n值...
      - label：值            （单行）
    两种都找不到返回 None —— 调用方**必须**处理 None，
    否则 re.findall(pattern, None) 会抛 TypeError。
    """
    m = re.search(r"【" + re.escape(label) + r"】[^\n]*\n(.*?)(?=\n【|\Z)", prompt, re.S)
    if m:
        return m.group(1).strip()

    m = re.search(r"[-*]?\s*" + re.escape(label) + r"\s*[:：]\s*(.+)", prompt)
    if m:
        return m.group(1).strip()
    return None


def _parse_float(prompt: str, pattern: str) -> float | None:
    m = re.search(pattern, prompt)
    return float(m.group(1)) if m else None


def _parse_rubric(prompt: str) -> list[dict[str, Any]]:
    block = _parse_text_field(prompt, "评分要点 rubric") or _parse_text_field(prompt, "评分要点") or ""
    if block:
        try:
            data = json.loads(block[block.find("["):block.rfind("]") + 1])
            if isinstance(data, list):
                return [{"point": str(p.get("point", "")), "score": float(p.get("score", 0))}
                        for p in data if isinstance(p, dict)]
        except (json.JSONDecodeError, ValueError):
            pass
    # 退化成按行解析「- 要点（3分）」
    out = []
    for line in re.findall(r"[-*]\s*(.+?)[（(](\d+(?:\.\d+)?)\s*分[)）]", block):
        out.append({"point": line[0].strip(), "score": float(line[1])})
    return out


_RATIO_ALIAS = {
    "SINGLE": "SINGLE", "单选": "SINGLE",
    "MULTI": "MULTI", "多选": "MULTI",
    "JUDGE": "JUDGE", "判断": "JUDGE",
    "BLANK": "BLANK", "填空": "BLANK",
    "TERM": "TERM", "名词解释": "TERM",
    "SHORT": "SHORT", "简答": "SHORT",
    "ESSAY": "ESSAY", "论述": "ESSAY",
    "CODE": "CODE", "代码": "CODE",
    "COMPARE": "COMPARE", "对比": "COMPARE",
}

_DIFF_ALIAS = {"EASY": "EASY", "易": "EASY", "MEDIUM": "MEDIUM", "中": "MEDIUM",
               "HARD": "HARD", "难": "HARD"}


def _expand_ratio(ratio: Any, count: int, aliases: dict[str, str] | None = None) -> list[str]:
    """
    把配比展开成长度为 count 的序列。

    支持两种入参：
      - 列表 ["SINGLE","SHORT","JUDGE"]  —— 调用方已经展开好了（Java 侧就是这么传的）
      - 字典 {"SINGLE": 0.4, "SHORT": 0.6} —— 按权重展开

    ⚠️ 必须传入对应的别名表：题型用 _RATIO_ALIAS，难度用 _DIFF_ALIAS。
    早先两处都用了题型表，导致 ["EASY","MEDIUM","HARD"] 被全部过滤掉。
    """
    table = aliases or _RATIO_ALIAS
    fallback = "SHORT" if table is _RATIO_ALIAS else "MEDIUM"

    def resolve(raw: Any) -> str | None:
        key = str(raw).strip()
        return table.get(key.upper()) or table.get(key)

    if isinstance(ratio, (list, tuple)):
        out = [n for n in (resolve(item) for item in ratio) if n]
        if not out:
            return [fallback] * count
        while len(out) < count:
            out.append(out[-1])
        return out[:count]

    if not isinstance(ratio, dict):
        return [fallback] * count

    items: list[tuple[str, float]] = []
    for key, value in ratio.items():
        name = resolve(key)
        if name is None:
            continue
        try:
            items.append((name, float(value)))
        except (TypeError, ValueError):
            continue

    if not items:
        items = [(fallback, 1.0)]

    total = sum(w for _, w in items) or 1.0
    out = []
    for name, weight in items:
        out.extend([name] * int(round(count * weight / total)))
    while len(out) < count:
        out.append(items[0][0])
    return out[:count]


def _diff_code(raw: str) -> int:
    name = _DIFF_ALIAS.get(str(raw).strip().upper(), _DIFF_ALIAS.get(str(raw).strip(), "MEDIUM"))
    return {"EASY": 1, "MEDIUM": 2, "HARD": 3}[name]
