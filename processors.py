from __future__ import annotations

from pathlib import Path
from typing import Callable
import fitz
from docx import Document

from .config import AppConfig
from .translator import translate_text, split_long_text

Progress = Callable[[int, str], None]


def _translate_preserving_linebreaks(text: str, config: AppConfig) -> str:
    chunks = list(split_long_text(text))
    return "".join(translate_text(chunk, config) for chunk in chunks)


def translate_docx(source: Path, destination: Path, config: AppConfig, progress: Progress) -> None:
    doc = Document(str(source))
    items: list[tuple[str, object]] = []
    for paragraph in doc.paragraphs:
        if paragraph.text.strip():
            items.append(("paragraph", paragraph))
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    if paragraph.text.strip():
                        items.append(("paragraph", paragraph))

    total = max(len(items), 1)
    for index, (_, paragraph) in enumerate(items, start=1):
        original = paragraph.text
        translated = _translate_preserving_linebreaks(original, config)
        if paragraph.runs:
            paragraph.runs[0].text = translated
            for run in paragraph.runs[1:]:
                run.text = ""
        else:
            paragraph.text = translated
        progress(int(index / total * 100), f"DOCX: {index}/{total}")

    doc.save(str(destination))


def _fit_font_size(page: fitz.Page, rect: fitz.Rect, text: str, start_size: float) -> float:
    size = max(6.0, start_size)
    while size > 6.0:
        rc = page.insert_textbox(rect, text, fontsize=size, fontname="helv", render_mode=3)
        if rc >= 0:
            return size
        size -= 0.5
    return 6.0


def translate_pdf(source: Path, destination: Path, config: AppConfig, progress: Progress) -> None:
    doc = fitz.open(str(source))
    total_pages = max(doc.page_count, 1)

    for page_index in range(doc.page_count):
        page = doc[page_index]
        blocks = page.get_text("dict").get("blocks", [])
        text_blocks = []
        for block in blocks:
            if block.get("type") != 0:
                continue
            lines = block.get("lines", [])
            spans = [span for line in lines for span in line.get("spans", [])]
            text = "\n".join(
                "".join(span.get("text", "") for span in line.get("spans", []))
                for line in lines
            ).strip()
            if not text:
                continue
            bbox = fitz.Rect(block["bbox"])
            avg_size = sum(float(s.get("size", 10)) for s in spans) / max(len(spans), 1)
            text_blocks.append((bbox, text, avg_size))

        for bbox, _, _ in text_blocks:
            page.add_redact_annot(bbox, fill=(1, 1, 1))
        if text_blocks:
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        for block_number, (bbox, original, avg_size) in enumerate(text_blocks, start=1):
            translated = _translate_preserving_linebreaks(original, config)
            font_size = max(6.0, min(avg_size, 16.0))
            result = page.insert_textbox(
                bbox,
                translated,
                fontsize=font_size,
                fontname="helv",
                align=fitz.TEXT_ALIGN_LEFT,
                color=(0, 0, 0),
            )
            if result < 0:
                page.insert_textbox(
                    bbox,
                    translated,
                    fontsize=max(6.0, font_size * 0.75),
                    fontname="helv",
                    align=fitz.TEXT_ALIGN_LEFT,
                    color=(0, 0, 0),
                )
            progress(
                int(((page_index + block_number / max(len(text_blocks), 1)) / total_pages) * 100),
                f"PDF: страница {page_index + 1}/{doc.page_count}, блок {block_number}/{len(text_blocks)}",
            )

    doc.save(str(destination), garbage=4, deflate=True)
    doc.close()
