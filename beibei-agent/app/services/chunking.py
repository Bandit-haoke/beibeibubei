"""
背备不悲 · 智能分块

策略：**优先按标题层级切，再按 token 预算切，最后加重叠**。

  1. 把解析出的 Block 拆成「最小单元」（段落 → 句子 → 硬切），
     每个单元都带页码、标题路径、字符偏移
  2. 贪心累加单元到 target_size token
  3. 遇到标题路径变化且当前块已经过半，就提前断开（不让两个章节混在一块里）
  4. 新块开头带上上一块尾部约 overlap token 的内容，保证跨块语义连续

token 估算：中文约 1 token/字，英文约 1 token/4 字符。
BGE-M3 用的 XLM-R 分词器大致符合这个比例；分块只需要「量级正确」，
不追求与真实分词器完全一致，因此不额外加载分词器（省内存、启动快）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.logging import get_logger
from app.services.parsing import Block

logger = get_logger(__name__)

SENTENCE_END = re.compile(r"(?<=[。！？；!?;])\s*")


@dataclass
class Chunk:
    index: int
    content: str
    token_count: int
    page_no: int
    section_path: str
    char_start: int
    char_end: int


@dataclass
class _Unit:
    text: str
    tokens: int
    page_no: int
    section_path: str
    char_start: int
    char_end: int


def estimate_tokens(text: str) -> int:
    """中文按 1 字 1 token，其余按 4 字符 1 token 估算。"""
    if not text:
        return 0
    cjk = 0
    other = 0
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff" or "\u3000" <= ch <= "\u303f" or "\uff00" <= ch <= "\uffef":
            cjk += 1
        else:
            other += 1
    return cjk + max(1, other // 4) if (cjk or other) else 0


def chunk_blocks(blocks: list[Block], target_size: int = 700, overlap: int = 105) -> list[Chunk]:
    """主入口。"""
    target_size = max(120, target_size)
    overlap = max(0, min(overlap, target_size // 2))

    units = _to_units(blocks, max_unit_tokens=int(target_size * 1.6))
    if not units:
        return []

    chunks: list[Chunk] = []
    buf: list[_Unit] = []
    buf_tokens = 0

    def flush() -> None:
        nonlocal buf, buf_tokens
        if not buf:
            return
        content = "\n".join(u.text for u in buf).strip()
        if content:
            chunks.append(Chunk(
                index=len(chunks),
                content=content,
                token_count=estimate_tokens(content),
                page_no=buf[0].page_no,
                section_path=buf[0].section_path or buf[-1].section_path,
                char_start=buf[0].char_start,
                char_end=buf[-1].char_end,
            ))
        # 保留尾部作为下一块的重叠
        carry: list[_Unit] = []
        carry_tokens = 0
        for unit in reversed(buf):
            if carry_tokens + unit.tokens > overlap:
                break
            carry.insert(0, unit)
            carry_tokens += unit.tokens
        buf = carry
        buf_tokens = carry_tokens

    for unit in units:
        # 标题路径变了，且当前块已经装了过半，就先收一块
        if (buf and unit.section_path
                and buf[-1].section_path
                and unit.section_path != buf[-1].section_path
                and buf_tokens >= target_size * 0.5):
            flush()

        buf.append(unit)
        buf_tokens += unit.tokens

        if buf_tokens >= target_size:
            flush()

    # 最后一块：flush 会把尾巴留下，所以先把尾巴清掉再收
    if buf:
        content = "\n".join(u.text for u in buf).strip()
        if content and (not chunks or chunks[-1].content != content):
            chunks.append(Chunk(
                index=len(chunks),
                content=content,
                token_count=estimate_tokens(content),
                page_no=buf[0].page_no,
                section_path=buf[0].section_path or buf[-1].section_path,
                char_start=buf[0].char_start,
                char_end=buf[-1].char_end,
            ))

    logger.info("分块完成：%d 个单元 -> %d 个分块（目标 %d token，重叠 %d）",
                len(units), len(chunks), target_size, overlap)
    return chunks


def _to_units(blocks: list[Block], *, max_unit_tokens: int) -> list[_Unit]:
    """把 Block 拆成不超过 max_unit_tokens 的单元。"""
    units: list[_Unit] = []

    for block in blocks:
        text = (block.text or "").strip()
        if not text:
            continue

        if estimate_tokens(text) <= max_unit_tokens:
            units.append(_Unit(
                text=text, tokens=estimate_tokens(text), page_no=block.page_no,
                section_path=block.section_path, char_start=block.char_start, char_end=block.char_end,
            ))
            continue

        # 超长段落 → 先按句子切
        sentences = [s for s in SENTENCE_END.split(text) if s and s.strip()]
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if estimate_tokens(sentence) <= max_unit_tokens:
                units.append(_Unit(
                    text=sentence, tokens=estimate_tokens(sentence), page_no=block.page_no,
                    section_path=block.section_path,
                    char_start=block.char_start, char_end=block.char_end,
                ))
            else:
                # 单句还是太长（比如一整段代码）→ 硬切
                for piece in _hard_split(sentence, max_unit_tokens):
                    units.append(_Unit(
                        text=piece, tokens=estimate_tokens(piece), page_no=block.page_no,
                        section_path=block.section_path,
                        char_start=block.char_start, char_end=block.char_end,
                    ))

    return units


def _hard_split(text: str, max_tokens: int) -> list[str]:
    """按字符硬切。max_tokens 按「中文 1 token/字」保守折算成字符数。"""
    size = max(80, max_tokens)
    return [text[i:i + size] for i in range(0, len(text), size) if text[i:i + size].strip()]
