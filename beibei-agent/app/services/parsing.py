"""
背备不悲 · 文档解析

输入：本地文件路径（或直接给的文本）
输出：带页码、标题路径、字符偏移的块列表

支持：pdf / docx / doc / pptx / txt / md / xlsx / 图片(OCR)

设计取舍：
  - PDF 优先用 PyMuPDF 抽文本层；抽不出文字的页再用 OCR（扫描版讲义常见）
  - 用 PDF 自带的书签目录（TOC）还原 section_path，这比按字号猜标题准得多
  - 解析阶段不做任何清洗以外的加工，分块交给 chunking.py
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)

IMAGE_EXT = {"jpg", "jpeg", "png", "bmp", "webp", "tif", "tiff"}
TEXT_EXT = {"txt", "md", "markdown", "log", "csv"}


# ---------------------------------------------------------------------------
#  数据结构
# ---------------------------------------------------------------------------

@dataclass
class Block:
    """一段连续的原文，带定位信息。"""

    text: str
    page_no: int = 0
    section_path: str = ""
    char_start: int = 0
    char_end: int = 0


@dataclass
class ParsedDocument:
    blocks: list[Block] = field(default_factory=list)
    full_text: str = ""
    page_count: int = 0
    char_count: int = 0
    used_ocr: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return self.char_count < 10


# ---------------------------------------------------------------------------
#  入口
# ---------------------------------------------------------------------------

def parse(
    file_path: str | None = None,
    file_type: str | None = None,
    *,
    text_content: str | None = None,
    file_name: str = "",
    ocr_enabled: bool = True,
) -> ParsedDocument:
    """
    解析文档。

    优先使用 text_content（手动粘贴场景）；否则按 file_type/file_path 分派。
    """
    if text_content is not None and text_content.strip():
        blocks = _blocks_from_plain_text(text_content, section_from_markdown=True)
        return _finalize(blocks, page_count=1, used_ocr=False, warnings=[])

    if not file_path:
        raise ValueError("既没有 textContent 也没有 filePath，无法解析")

    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{file_path}")

    ext = (file_type or path.suffix.lstrip(".") or "").lower()
    logger.info("解析文档 %s (类型=%s, 大小=%.1f KB)", path.name, ext, path.stat().st_size / 1024)

    if ext == "pdf":
        return _parse_pdf(path, ocr_enabled=ocr_enabled)
    if ext in ("docx", "doc"):
        return _parse_docx(path)
    if ext == "pptx":
        return _parse_pptx(path)
    if ext == "xlsx":
        return _parse_xlsx(path)
    if ext in TEXT_EXT:
        return _parse_text_file(path)
    if ext in IMAGE_EXT:
        return _parse_image(path, file_name or path.name)

    raise ValueError(f"不支持的文件类型：.{ext}")


# ---------------------------------------------------------------------------
#  PDF
# ---------------------------------------------------------------------------

def _parse_pdf(path: Path, *, ocr_enabled: bool) -> ParsedDocument:
    import pymupdf  # PyMuPDF 1.24+ 的包名

    doc = pymupdf.open(str(path))
    warnings: list[str] = []
    used_ocr = False

    toc_sections = _pdf_toc_to_page_sections(doc)

    blocks: list[Block] = []
    for page_index in range(doc.page_count):
        page = doc[page_index]
        page_no = page_index + 1
        section = toc_sections.get(page_no, "")

        page_text = page.get_text("text") or ""
        if len(page_text.strip()) < 20 and ocr_enabled:
            # 抽不出文字层 → 扫描页，走 OCR
            try:
                ocr_text = _ocr_page_image(page)
                if ocr_text.strip():
                    blocks.append(Block(text=ocr_text.strip(), page_no=page_no, section_path=section))
                    used_ocr = True
                    continue
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"第 {page_no} 页 OCR 失败：{exc}")
                logger.warning("第 %d 页 OCR 失败：%s", page_no, exc)

        for para in _split_paragraphs(page_text):
            blocks.append(Block(text=para, page_no=page_no, section_path=section))

    page_count = doc.page_count
    doc.close()
    return _finalize(blocks, page_count=page_count, used_ocr=used_ocr, warnings=warnings)


def _pdf_toc_to_page_sections(doc) -> dict[int, str]:
    """
    把 PDF 书签目录转成「页码 → 标题路径」。
    doc.get_toc() 返回 [[level, title, page], ...]，page 从 1 开始。
    """
    try:
        toc = doc.get_toc(simple=True)
    except Exception:  # noqa: BLE001
        return {}
    if not toc:
        return {}

    sections: dict[int, str] = {}
    stack: list[tuple[int, str]] = []
    for level, title, page in toc:
        if not title or not page or page < 1:
            continue
        title = str(title).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        sections[int(page)] = " > ".join(t for _, t in stack)

    # 把某页的路径向后填充到下一页出现新标题为止
    if sections:
        filled: dict[int, str] = {}
        current = ""
        max_page = max(sections)
        for p in range(1, max_page + 1):
            if p in sections:
                current = sections[p]
            if current:
                filled[p] = current
        return filled
    return sections


def _ocr_page_image(page) -> str:
    """把 PDF 页面渲染成图片再 OCR。"""
    import pymupdf

    pix = page.get_pixmap(matrix=pymupdf.Matrix(2.0, 2.0))  # 2 倍缩放，OCR 更准
    png_bytes = pix.tobytes("png")
    return _run_ocr_bytes(png_bytes)


# ---------------------------------------------------------------------------
#  Word / PPT / Excel / 纯文本
# ---------------------------------------------------------------------------

def _parse_docx(path: Path) -> ParsedDocument:
    import docx

    document = docx.Document(str(path))
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []

    for para in document.paragraphs:
        text = (para.text or "").strip()
        if not text:
            continue

        style = (para.style.name or "") if para.style else ""
        heading_level = _heading_level(style)
        if heading_level:
            while stack and stack[-1][0] >= heading_level:
                stack.pop()
            stack.append((heading_level, text))
            continue

        section = " > ".join(t for _, t in stack)
        blocks.append(Block(text=text, page_no=0, section_path=section))

    # 表格也抽出来，讲义里经常有对照表
    for t_index, table in enumerate(document.tables):
        rows = []
        for row in table.rows:
            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            blocks.append(Block(
                text=f"[表格 {t_index + 1}]\n" + "\n".join(rows),
                page_no=0,
                section_path="附录 > 表格",
            ))

    return _finalize(blocks, page_count=0, used_ocr=False, warnings=[])


def _heading_level(style_name: str) -> int:
    """从 Word 样式名里判断标题层级：Heading 1 / 标题 1 / Title"""
    if not style_name:
        return 0
    m = re.match(r"^(?:Heading|标题|Titre)\s*(\d+)$", style_name.strip(), re.I)
    if m:
        return int(m.group(1))
    if style_name.strip().lower() in ("title", "标题"):
        return 1
    return 0


def _parse_pptx(path: Path) -> ParsedDocument:
    from pptx import Presentation

    prs = Presentation(str(path))
    blocks: list[Block] = []

    for index, slide in enumerate(prs.slides, start=1):
        texts: list[str] = []
        for shape in slide.shapes:
            if not getattr(shape, "has_text_frame", False):
                continue
            content = (shape.text_frame.text or "").strip()
            if content:
                texts.append(content)
        if not texts:
            continue
        title = texts[0].split("\n")[0][:60]
        blocks.append(Block(
            text="\n".join(texts),
            page_no=index,
            section_path=f"第 {index} 页 > {title}",
        ))

    return _finalize(blocks, page_count=len(prs.slides), used_ocr=False, warnings=[])


def _parse_xlsx(path: Path) -> ParsedDocument:
    import openpyxl

    wb = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    blocks: list[Block] = []
    try:
        for sheet in wb.worksheets:
            rows: list[str] = []
            for row in sheet.iter_rows(values_only=True):
                cells = ["" if v is None else str(v).strip() for v in row]
                if any(cells):
                    rows.append(" | ".join(cells))
            if rows:
                blocks.append(Block(
                    text=f"[工作表：{sheet.title}]\n" + "\n".join(rows),
                    page_no=0,
                    section_path=f"工作表 > {sheet.title}",
                ))
    finally:
        wb.close()

    return _finalize(blocks, page_count=0, used_ocr=False, warnings=[])


def _parse_text_file(path: Path) -> ParsedDocument:
    raw = _read_text_with_fallback(path)
    blocks = _blocks_from_plain_text(raw, section_from_markdown=True)
    return _finalize(blocks, page_count=0, used_ocr=False, warnings=[])


def _read_text_with_fallback(path: Path) -> str:
    """中文资料常见 GBK/GB18030 编码，UTF-8 读失败时回退。"""
    data = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk", "big5"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _blocks_from_plain_text(raw: str, *, section_from_markdown: bool) -> list[Block]:
    blocks: list[Block] = []
    stack: list[tuple[int, str]] = []

    for para in _split_paragraphs(raw):
        if section_from_markdown:
            m = re.match(r"^(#{1,6})\s+(.+)$", para)
            if m:
                level = len(m.group(1))
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, m.group(2).strip()))
                continue

        if section_from_markdown:
            # 中文文档里「第X章 / 一、 / 1.1 」也算标题
            m = re.match(r"^(第[一二三四五六七八九十百零\d]+[章节部分]|[一二三四五六七八九十]+、|\d+(?:\.\d+){1,2}\s+\S)", para)
            if m and len(para) <= 60:
                level = para.count(".") + 1 if re.match(r"^\d", para) else 1
                while stack and stack[-1][0] >= level:
                    stack.pop()
                stack.append((level, para.strip()))
                continue

        blocks.append(Block(
            text=para,
            page_no=0,
            section_path=" > ".join(t for _, t in stack),
        ))

    return blocks


# ---------------------------------------------------------------------------
#  图片 OCR
# ---------------------------------------------------------------------------

def _parse_image(path: Path, file_name: str) -> ParsedDocument:
    text = _run_ocr_bytes(path.read_bytes())
    if not text.strip():
        raise ValueError("OCR 没有识别出任何文字，请确认图片清晰、文字方向正确")

    blocks = [Block(text=para, page_no=1, section_path=file_name)
              for para in _split_paragraphs(text)]
    return _finalize(blocks, page_count=1, used_ocr=True, warnings=[])


_ocr_instance = None


def _get_ocr():
    """懒加载 PaddleOCR（首次加载模型要几秒，不能放在模块导入时）。"""
    global _ocr_instance
    if _ocr_instance is not None:
        return _ocr_instance

    from app.config import get_settings

    settings = get_settings()
    from paddleocr import PaddleOCR  # 延迟导入，未装时给出明确报错

    logger.info("正在加载 PaddleOCR 模型（lang=%s, gpu=%s）...", settings.ocr_lang, settings.ocr_use_gpu)
    try:
        # PaddleOCR 3.x
        _ocr_instance = PaddleOCR(
            lang=settings.ocr_lang,
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            # ⚠️ 必须关掉 mkldnn：
            # paddlepaddle 3.3.x 的 PIR 新执行器 + oneDNN 组合在 CPU 上会抛
            # NotImplementedError: ConvertPirAttribute2RuntimeAttribute not support
            # [pir::ArrayAttribute<pir::DoubleAttribute>]
            # 关掉后精度不受影响，速度略降但完全可接受（一页 A4 约 1~3 秒）
            enable_mkldnn=False,
        )
    except TypeError:
        # PaddleOCR 2.x 的参数名不同
        _ocr_instance = PaddleOCR(use_angle_cls=True, lang=settings.ocr_lang,
                                  use_gpu=settings.ocr_use_gpu, show_log=False)
    logger.info("PaddleOCR 模型加载完成")
    return _ocr_instance


def _run_ocr_bytes(image_bytes: bytes) -> str:
    import io

    import numpy as np
    from PIL import Image

    ocr = _get_ocr()
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    array = np.array(image)

    lines: list[str] = []

    # PaddleOCR 3.x：有 predict() 就只走这条路。
    # 早期版本这里会「predict 返回空就退到 2.x 的 ocr()」，但 3.x 的 ocr() 已经
    # 不接受 cls 参数，会抛 TypeError，所以绝不能再回退。
    if hasattr(ocr, "predict"):
        results = ocr.predict(array)
        for res in results:
            lines.extend(_extract_texts_from_result(res))
        return "\n".join(lines)

    # PaddleOCR 2.x
    raw = ocr.ocr(array, cls=True)
    for page in raw or []:
        for item in page or []:
            try:
                lines.append(item[1][0])
            except (IndexError, TypeError):
                continue

    return "\n".join(lines)


def _extract_texts_from_result(res) -> list[str]:
    """
    取出识别文本。

    ⚠️ PaddleOCR 3.x 的 OCRResult 本身就是 dict 子类，
    rec_texts 就在**顶层**，不在 .json["res"] 里面 —— 这点和文档写的不一致，
    实测（3.7.0）确认顶层即可取到。
    """
    if isinstance(res, dict):
        texts = res.get("rec_texts") or res.get("texts")
        if texts:
            return [str(t) for t in texts]

    data = getattr(res, "json", None)
    if isinstance(data, dict):
        payload = data.get("res", data)
        if isinstance(payload, dict):
            texts = payload.get("rec_texts") or payload.get("texts")
            if texts:
                return [str(t) for t in texts]
    return []


# ---------------------------------------------------------------------------
#  公共工具
# ---------------------------------------------------------------------------

def _split_paragraphs(raw: str) -> list[str]:
    """按空行切段，顺手把段内换行合并（PDF 抽出来的文本经常一行一句）。"""
    if not raw:
        return []
    normalized = raw.replace("\r\n", "\n").replace("\r", "\n")
    parts = re.split(r"\n\s*\n", normalized)
    out: list[str] = []
    for part in parts:
        text = " ".join(line.strip() for line in part.split("\n") if line.strip())
        text = re.sub(r"\s{2,}", " ", text).strip()
        if text:
            out.append(text)
    return out


def _finalize(blocks: list[Block], *, page_count: int, used_ocr: bool,
              warnings: list[str]) -> ParsedDocument:
    """拼出 full_text 并回填每块的字符偏移。"""
    clean = [b for b in blocks if b.text and b.text.strip()]
    pieces: list[str] = []
    cursor = 0
    for block in clean:
        text = block.text.strip()
        block.char_start = cursor
        cursor += len(text)
        block.char_end = cursor
        pieces.append(text)
        cursor += 2  # \n\n 分隔符占 2 个字符

    full_text = "\n\n".join(pieces)
    return ParsedDocument(
        blocks=clean,
        full_text=full_text,
        page_count=page_count,
        char_count=len(full_text),
        used_ocr=used_ocr,
        warnings=warnings,
    )
