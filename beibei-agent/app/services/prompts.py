"""
背备不悲 · Prompt 模板服务

模板存在 MySQL 的 bb_prompt_template，界面上可以改，改完自动生成新版本。
这里带进程内缓存，避免每次调用都查库。

⚠️ 渲染**不能用 str.format**：我们的模板里含有大量字面量花括号
（比如出题模板里的 JSON 示例 `{"questions":[...]}`），format 会直接抛 KeyError。
所以改成「只替换已知变量名」的策略。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from app.core.logging import get_logger
from app.db.mysql import get_engine

logger = get_logger(__name__)

# 内置兜底模板：数据库里查不到时用它，保证流程不中断
FALLBACKS: dict[str, str] = {
    "CLASSIFY_TAG": (
        "你是资深课程知识体系设计专家。下面是《{kb_name}》学习资料的内容。\n"
        "抽取一份层级化知识点树，最多 3 层。顶层是主要模块（5~12 个），"
        "第二层是核心考点，第三层只在必要时出现。命名用标准术语。\n"
        "【资料内容】\n{content}\n"
        '严格只输出 JSON：{"tags":[{"name":"","description":"","children":[]}]}'
    ),
    "CHUNK_TAG": (
        "判断下面这段资料原文主要讲解哪些知识点，从候选列表里选，最多 3 个，宁少勿滥。\n"
        "【候选知识点】\n{candidate_tags}\n【原文】\n{chunk_content}\n"
        '严格只输出 JSON：{"tagIds":[],"reason":""}'
    ),
    "QUESTION_GEN": (
        "你是《{kb_name}》课程的命题老师。基于下面材料出 {count} 道题。\n"
        "【材料】\n{context}\n【覆盖知识点】{tags}\n"
        "【题型配比】{q_type_ratio}\n【难度配比】{difficulty_ratio}\n"
        '严格只输出 JSON：{"questions":[]}'
    ),
    "GRADING_SUBJECTIVE": (
        "按评分要点给下面这道题打分。\n【题目】{stem}\n【参考答案】{reference_answer}\n"
        "【评分要点】{rubric}\n【原文依据】{context}\n【学生答案】{user_answer}\n"
        "【满分】{full_score}\n"
        '严格只输出 JSON：{"score":0,"hitPoints":[],"missPoints":[],"wrongPoints":[],"citations":[],"feedback":""}'
    ),
    "SELF_CHECK": (
        "判断这道 AI 生成的题是否合格（答案能否从原文推出、有无歧义、选项是否自洽）。\n"
        "【题目】\n{question_json}\n【原文片段】\n{context}\n"
        '严格只输出 JSON：{"pass":true,"score":0.0,"reason":""}'
    ),
    "RECITE_CHECK": (
        "学生复述了一段材料，请核对覆盖度。\n【原文】\n{content}\n【学生复述】\n{user_recite}\n"
        '严格只输出 JSON：{"coverageScore":0,"hitPoints":[],"missPoints":[],"wrongPoints":[],"feedback":""}'
    ),
    # ---------------- 模拟面试（与 docs/sql/interview.sql 保持一致） ----------------
    "RESUME_PARSE": (
        "你是资深 HR 兼技术面试官。下面是一份候选人简历的原文，请抽取结构化档案。\n"
        "【简历原文】\n{resume_text}\n"
        "只抽取原文真实出现的信息，不要脑补；没有的字段留空；\n"
        "projects 每条都要带 evidence（简历原文原话），后面要靠它追问核实；\n"
        "risks 填可疑或模糊的点（时间线断档、只有名词没有成果），供重点追问。\n"
        '严格只输出 JSON：{"name":"","years":0,"education":"","school":"","major":"",'
        '"currentCompany":"","currentTitle":"","targetPosition":"","skills":[],'
        '"projects":[{"name":"","role":"","period":"","techStack":[],"highlights":[],"evidence":""}],'
        '"workExperience":[{"company":"","title":"","period":"","duty":""}],'
        '"selfEvaluation":"","highlights":[],"risks":[]}'
    ),
    "INTERVIEW_ASK": (
        "你是一场模拟技术面试的面试官。请根据候选人简历、目标岗位和已进行的对话，提出下一个问题。\n"
        "【目标岗位】{job_title}\n【难度要求】{difficulty}\n"
        "【候选人简历档案】\n{resume_profile}\n"
        "【已问过的问题】\n{asked_questions}\n"
        "【最近一轮问答】\n{recent_qa}\n"
        "【进度】本场共 {max_turns} 轮，这是第 {turn_no} 轮\n"
        "第 1 轮让候选人自我介绍；之后顺着简历项目深度追问；每 3 轮穿插一道原理题；\n"
        "候选人上一轮含糊就优先追问（type=FOLLOWUP）；不要重复已问过的问题，一次只问一个。\n"
        '严格只输出 JSON：{"question":"","type":"INTRO","basedOn":"","expects":[""]}'
    ),
    "INTERVIEW_EVAL": (
        "你是模拟面试的面试官，请对候选人这一轮的回答打分并给出反馈。\n"
        "【目标岗位】{job_title}\n【面试问题】{question}\n"
        "【本题类型】{question_type}\n【期望覆盖的要点】{expects}\n"
        "【简历相关原文】{resume_evidence}\n【候选人回答】\n{answer}\n"
        "评分维度（各 0~100）：techAccuracy 技术准确性 / specificity 项目具体性 / "
        "structure 表达结构 / consistency 与简历一致性 / relevance 岗位匹配度。\n"
        "score 是综合得分（0~100 整数）。contradiction 只在确实与简历矛盾时填写并引用简历原话。\n"
        '严格只输出 JSON：{"scores":{"techAccuracy":0,"specificity":0,"structure":0,'
        '"consistency":0,"relevance":0},"score":0,"goodPoints":[],"problems":[],'
        '"suggestion":"","contradiction":"","followUpNeeded":true}'
    ),
    "INTERVIEW_REPORT": (
        "你是模拟面试的主考官，一场面试已经结束，请出具书面评估报告。\n"
        "【目标岗位】{job_title}\n【难度要求】{difficulty}\n"
        "【候选人简历档案】\n{resume_profile}\n"
        "【完整面试记录】\n{transcript}\n"
        "要求：overallScore 是整场综合得分，要和各轮得分吻合；\n"
        "weakPoints 只列得分低或答不上来的技能项，每项都要有 evidence 和 suggestion；\n"
        "knowledgePoints 给 3~6 条最该优先补的知识点，用标准技术术语、每条不超过 20 字（要直接拿去出题）；\n"
        "summary 是 150 字以内总评，直说问题和差距。\n"
        '严格只输出 JSON：{"overallScore":0,"summary":"","dimensions":[{"name":"","score":0,"comment":""}],'
        '"strengths":[],"weakPoints":[{"skill":"","level":"","evidence":"","suggestion":""}],'
        '"knowledgePoints":[],"nextSteps":[]}'
    ),
    # ---------------- 面经（与 docs/sql/interview_note.sql 保持一致） ----------------
    "INTERVIEW_NOTE_SPEAKER_MAP": (
        "下面是一场面试的转写片段。转写引擎已经区分了说话人并给出编号，"
        "但编号只是引擎内部标识，没有语义。请判断每个编号是「面试官」还是「候选人（我）」。\n"
        "面试官负责提问、追问、宣布流程；候选人负责回答、介绍经历。\n"
        "【带编号的发言片段】\n{speaker_samples}\n【出现过的编号】{speaker_ids}\n"
        '严格只输出 JSON：{"mapping":{"1":1,"2":2},"reason":""}（1=面试官 2=候选人）'
    ),
    "INTERVIEW_NOTE_SEGMENT": (
        "下面是一段面试录音的转写文本。转写没有说话人标记，而且标点并不可靠 —— "
        "两个人的话经常被连成一串。请按「谁在说话」切分成若干句并标注角色。\n"
        "这场技术面试只有两个人：面试官 和 候选人（我）。\n"
        "典型情况：原文「你好，请先做一个自我介绍面试官好，我叫张三」其实是两句 —— "
        "「你好，请先做一个自我介绍」是面试官提问，"
        "「面试官好，我叫张三」是候选人回答。\n"
        "规则：同一个人连续说的一段话算一句，换人就切开；"
        "面试官多为问句且较短，候选人多为回答且较长；"
        "只做切分和标注，不要改写、不要润色、不要增删任何字词；"
        "切分结果按顺序拼起来必须和原文完全一致。\n"
        "【转写文本】\n{text}\n"
        '严格只输出 JSON：{"items":[{"text":"","role":1}]}（1=面试官 2=候选人）'
    ),
    "INTERVIEW_NOTE_POLISH": (
        "下面的面试录音转写口语痕迹很重，请逐句清洗成通顺的书面表达。\n"
        "处理：语气词与口头禅（啊/额/嗯/那个/就是说）、重复（我我我）、"
        "口误与自我纠正（只保留最终意思）、无意义填充。\n"
        "硬性要求：不改变原意、不增删事实、不合并也不拆分句子、"
        "保留专业术语和数据；清洗后无有效内容的句子 cleanText 留空。\n"
        "【待清洗文本】每行格式 `序号|角色|内容`\n{lines}\n"
        '严格只输出 JSON：{"items":[{"seq":1,"cleanText":""}]}'
    ),
    "INTERVIEW_NOTE_SUMMARY": (
        "你是一位求职辅导专家。下面是一场真实面试的完整记录（已区分面试官和候选人，已清洗口语）。\n"
        "请整理成一篇对后来者有参考价值的面经。\n"
        "【公司】{company}\n【岗位】{position}\n【面试记录】\n{transcript}\n"
        "questions 每条含 question（问题原文）、answer（回答要点摘要 2~3 句）、"
        "category（自我介绍/项目经历/技术原理/场景设计/算法/反问环节/其他）；"
        "highlights 给 3~6 条具体经验点；content 是 Markdown 正文，"
        "分「## 面试流程」「## 问题与回答要点」「## 复盘与建议」三节。\n"
        '严格只输出 JSON：{"title":"","summary":"",'
        '"questions":[{"question":"","answer":"","category":""}],"highlights":[],"content":""}'
    ),
}


class PromptService:
    """从数据库读 Prompt 模板并渲染。"""

    def __init__(self) -> None:
        self._cache: dict[str, str] = {}

    def get(self, code: str, *, use_cache: bool = True) -> str:
        if use_cache and code in self._cache:
            return self._cache[code]

        content = self._load_from_db(code)
        if content is None:
            content = FALLBACKS.get(code)
            if content is None:
                raise KeyError(f"Prompt 模板不存在: {code}")
            logger.warning("模板 %s 未在数据库中找到，使用内置兜底版本", code)

        self._cache[code] = content
        return content

    def _load_from_db(self, code: str) -> str | None:
        try:
            with get_engine().connect() as conn:
                row = conn.execute(
                    text(
                        "SELECT content FROM bb_prompt_template "
                        "WHERE code = :code AND is_active = 1 "
                        "ORDER BY version DESC LIMIT 1"
                    ),
                    {"code": code},
                ).fetchone()
                return row[0] if row else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取 Prompt 模板失败（code=%s）：%s", code, exc)
            return None

    def render(self, code: str, **variables: Any) -> str:
        """
        只替换传入的变量，模板里其它花括号原样保留。
        这样 JSON 示例里的 `{"questions": [...]}` 不会被误伤。
        """
        template = self.get(code)
        for key, value in variables.items():
            placeholder = "{" + key + "}"
            if placeholder in template:
                template = template.replace(placeholder, "" if value is None else str(value))
        return template

    def clear_cache(self) -> None:
        self._cache.clear()


prompt_service = PromptService()
