from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

import fitz
from docx import Document

from config import AppConfig
from translator import qa_text, should_translate, split_long_text, translate_text

Progress = Callable[[int, str], None]


def _translate_preserving_linebreaks(text: str, config: AppConfig) -> str:
    chunks = list(split_long_text(text))
    return "".join(translate_text(chunk, config) for chunk in chunks)


def _write_qa_report(destination: Path, warnings: list[str]) -> Path:
    report = destination.with_name(f"{destination.stem}_QA_REPORT.txt")
    lines = [
        "PDFMathTranslate WLL — отчёт контроля качества",
        f"Файл: {destination.name}",
        "",
    ]
    if warnings:
        lines.append("Найдены замечания:")
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("Автоматическая проверка не выявила явных проблем.")
    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def translate_docx(source: Path, destination: Path, config: AppConfig, progress: Progress) -> Path:
    doc = Document(str(source))
    paragraphs = []
    seen: set[int] = set()

    for paragraph in doc.paragraphs:
        if paragraph.text.strip() and id(paragraph._p) not in seen:
            paragraphs.append(paragraph)
            seen.add(id(paragraph._p))

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    if paragraph.text.strip() and id(paragraph._p) not in seen:
                        paragraphs.append(paragraph)
                        seen.add(id(paragraph._p))

    warnings: list[str] = []
    total = max(len(paragraphs), 1)
    for index, paragraph in enumerate(paragraphs, start=1):
        original = paragraph.text
        if not should_translate(original):
            continue
        translated = _translate_preserving_linebreaks(original, config)

        if paragraph.runs:
            first = paragraph.runs[0]
            first.text = translated
            for run in paragraph.runs[1:]:
                run.text = ""
        else:
            paragraph.text = translated

        warnings.extend(qa_text(translated, f"DOCX, абзац {index}").warnings)
        progress(int(index / total * 100), f"DOCX: обработано {index}/{total}")

    destination.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(destination))
    return _write_qa_report(destination, warnings)


def _windows_cyrillic_font() -> str | None:
    if os.name != "nt":
        return None
    candidates = (
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "arial.ttf",
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "calibri.ttf",
        Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segoeui.ttf",
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def _insert_translated_text(page: fitz.Page, rect: fitz.Rect, text: str, start_size: float) -> bool:
    fontfile = _windows_cyrillic_font()
    fontname = "wllfont" if fontfile else "helv"
    size = min(max(start_size, 6.0), 18.0)

    while size >= 5.0:
        result = page.insert_textbox(
            rect,
            text,
            fontsize=size,
            fontname=fontname,
            fontfile=fontfile,
            align=fitz.TEXT_ALIGN_LEFT,
            color=(0, 0, 0),
            lineheight=1.05,
        )
        if result >= 0:
            return True
        size -= 0.5
    return False


def translate_pdf(source: Path, destination: Path, config: AppConfig, progress: Progress) -> Path:
    doc = fitz.open(str(source))
    total_pages = max(doc.page_count, 1)
    warnings: list[str] = []

    try:
        for page_index in range(doc.page_count):
            page = doc[page_index]
            blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_LIGATURES).get("blocks", [])
            text_blocks: list[tuple[fitz.Rect, str, float]] = []

            for block in blocks:
                if block.get("type") != 0:
                    continue
                lines = block.get("lines", [])
                spans = [span for line in lines for span in line.get("spans", [])]
                text = "\n".join(
                    "".join(span.get("text", "") for span in line.get("spans", []))
                    for line in lines
                ).strip()
                if not should_translate(text):
                    continue
                bbox = fitz.Rect(block["bbox"])
                avg_size = sum(float(span.get("size", 10)) for span in spans) / max(len(spans), 1)
                if bbox.width < 8 or bbox.height < 5:
                    continue
                text_blocks.append((bbox, text, avg_size))

            if not text_blocks:
                warnings.append(f"PDF, страница {page_index + 1}: текстовый слой не найден; возможно, требуется OCR")
                progress(int((page_index + 1) / total_pages * 100), f"PDF: страница {page_index + 1}/{doc.page_count}")
                continue

            for bbox, _, _ in text_blocks:
                page.add_redact_annot(bbox, fill=(1, 1, 1))
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

            for block_number, (bbox, original, avg_size) in enumerate(text_blocks, start=1):
                translated = _translate_preserving_linebreaks(original, config)
                inserted = _insert_translated_text(page, bbox, translated, avg_size)
                if not inserted:
                    warnings.append(
                        f"PDF, страница {page_index + 1}, блок {block_number}: перевод не поместился в исходную область"
                    )
                warnings.extend(
                    qa_text(translated, f"PDF, страница {page_index + 1}, блок {block_number}").warnings
                )
                progress(
                    int(((page_index + block_number / len(text_blocks)) / total_pages) * 100),
                    f"PDF: страница {page_index + 1}/{doc.page_count}, блок {block_number}/{len(text_blocks)}",
                )

        destination.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(destination), garbage=4, deflate=True, clean=True)
    finally:
        doc.close()

    return _write_qa_report(destination, warnings)
