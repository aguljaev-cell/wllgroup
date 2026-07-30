from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import fitz
from docx import Document
from docx.text.paragraph import Paragraph

from config import AppConfig
from translator import qa_text, should_translate, translate_text


Progress = Callable[[int, str], None]


@dataclass(slots=True)
class PdfTextBlock:
    rect: fitz.Rect
    text: str
    font_size: float
    color: tuple[float, float, float]
    alignment: int
    rotation: int = 0


def _safe_progress(progress: Progress, value: int, message: str) -> None:
    try:
        progress(max(0, min(100, int(value))), message)
    except Exception:
        # Ошибка интерфейсного callback не должна повреждать перевод файла.
        pass


def _write_qa_report(
    destination: Path,
    warnings: list[str],
    *,
    source: Path | None = None,
    processed_units: int = 0,
) -> Path:
    report = destination.with_name(f"{destination.stem}_QA_REPORT.txt")
    lines = [
        "PDFMathTranslate WLL — отчёт контроля качества",
        f"Исходный файл: {source.name if source else 'не указан'}",
        f"Результат: {destination.name}",
        f"Обработано элементов: {processed_units}",
        "",
    ]

    unique_warnings = list(dict.fromkeys(warnings))
    if unique_warnings:
        lines.append(f"Найдены замечания: {len(unique_warnings)}")
        lines.extend(f"- {warning}" for warning in unique_warnings)
    else:
        lines.append("Автоматическая проверка не выявила явных проблем.")

    report.write_text("\n".join(lines), encoding="utf-8")
    return report


def _paragraphs_in_document(doc: Document) -> list[Paragraph]:
    paragraphs: list[Paragraph] = []
    seen: set[int] = set()

    def add(paragraph: Paragraph) -> None:
        key = id(paragraph._p)
        if key in seen or not paragraph.text.strip():
            return
        seen.add(key)
        paragraphs.append(paragraph)

    for paragraph in doc.paragraphs:
        add(paragraph)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    add(paragraph)

    # Колонтитулы часто содержат технические заголовки и номера разделов.
    for section in doc.sections:
        for paragraph in section.header.paragraphs:
            add(paragraph)
        for paragraph in section.footer.paragraphs:
            add(paragraph)

    return paragraphs


def _replace_paragraph_text(paragraph: Paragraph, translated: str) -> None:
    """
    Сохраняет формат первого текстового run и не разрушает свойства абзаца.
    Для сложного смешанного форматирования это безопаснее, чем paragraph.text.
    """
    if not paragraph.runs:
        paragraph.add_run(translated)
        return

    nonempty_runs = [run for run in paragraph.runs if run.text]
    target = nonempty_runs[0] if nonempty_runs else paragraph.runs[0]
    target.text = translated

    for run in paragraph.runs:
        if run is not target:
            run.text = ""


def translate_docx(
    source: Path,
    destination: Path,
    config: AppConfig,
    progress: Progress,
) -> Path:
    doc = Document(str(source))
    paragraphs = _paragraphs_in_document(doc)

    warnings: list[str] = []
    total = max(len(paragraphs), 1)
    processed = 0

    for index, paragraph in enumerate(paragraphs, start=1):
        original = paragraph.text
        if not should_translate(original):
            _safe_progress(progress, int(index / total * 100), f"DOCX: обработано {index}/{total}")
            continue

        try:
            translated = translate_text(original, config)
            _replace_paragraph_text(paragraph, translated)
            processed += 1

            result = qa_text(
                translated,
                f"DOCX, абзац {index}",
                source_text=original,
            )
            warnings.extend(result.warnings)
        except Exception as exc:
            warnings.append(f"DOCX, абзац {index}: ошибка перевода — {exc}")

        _safe_progress(
            progress,
            int(index / total * 100),
            f"DOCX: обработано {index}/{total}",
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(destination))

    return _write_qa_report(
        destination,
        warnings,
        source=source,
        processed_units=processed,
    )


def _windows_cyrillic_font() -> str | None:
    if os.name != "nt":
        return None

    fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    candidates = (
        "arial.ttf",
        "segoeui.ttf",
        "calibri.ttf",
        "tahoma.ttf",
        "times.ttf",
    )
    for name in candidates:
        candidate = fonts_dir / name
        if candidate.exists():
            return str(candidate)
    return None


def _rgb_from_int(color_value: int | None) -> tuple[float, float, float]:
    if not isinstance(color_value, int):
        return (0.0, 0.0, 0.0)

    red = (color_value >> 16) & 255
    green = (color_value >> 8) & 255
    blue = color_value & 255
    return (red / 255.0, green / 255.0, blue / 255.0)


def _estimate_alignment(block_rect: fitz.Rect, line_rects: list[fitz.Rect]) -> int:
    if not line_rects:
        return fitz.TEXT_ALIGN_LEFT

    avg_left = sum(rect.x0 for rect in line_rects) / len(line_rects)
    avg_right = sum(rect.x1 for rect in line_rects) / len(line_rects)
    left_gap = avg_left - block_rect.x0
    right_gap = block_rect.x1 - avg_right

    if abs(left_gap - right_gap) <= max(2.0, block_rect.width * 0.05):
        return fitz.TEXT_ALIGN_CENTER
    if left_gap > right_gap * 1.8:
        return fitz.TEXT_ALIGN_RIGHT
    return fitz.TEXT_ALIGN_LEFT


def _extract_pdf_blocks(page: fitz.Page) -> list[PdfTextBlock]:
    data = page.get_text(
        "dict",
        flags=fitz.TEXT_PRESERVE_LIGATURES | fitz.TEXT_PRESERVE_WHITESPACE,
    )
    result: list[PdfTextBlock] = []

    for block in data.get("blocks", []):
        if block.get("type") != 0 or "bbox" not in block:
            continue

        lines = block.get("lines", [])
        spans = [span for line in lines for span in line.get("spans", [])]
        if not spans:
            continue

        text_lines: list[str] = []
        line_rects: list[fitz.Rect] = []

        for line in lines:
            line_text = "".join(span.get("text", "") for span in line.get("spans", []))
            text_lines.append(line_text.rstrip())
            if "bbox" in line:
                line_rects.append(fitz.Rect(line["bbox"]))

        text = "\n".join(text_lines).strip()
        if not should_translate(text):
            continue

        rect = fitz.Rect(block["bbox"])
        if rect.width < 8 or rect.height < 5:
            continue

        sizes = [float(span.get("size", 10.0)) for span in spans if float(span.get("size", 0)) > 0]
        font_size = sum(sizes) / max(len(sizes), 1)

        colors = [span.get("color") for span in spans if isinstance(span.get("color"), int)]
        color = _rgb_from_int(colors[0] if colors else None)

        direction = lines[0].get("dir", (1.0, 0.0)) if lines else (1.0, 0.0)
        rotation = 0
        if isinstance(direction, (list, tuple)) and len(direction) == 2:
            x, y = float(direction[0]), float(direction[1])
            if abs(y) > abs(x):
                rotation = 90 if y > 0 else 270

        result.append(
            PdfTextBlock(
                rect=rect,
                text=text,
                font_size=font_size,
                color=color,
                alignment=_estimate_alignment(rect, line_rects),
                rotation=rotation,
            )
        )

    return result


def _expanded_rect(rect: fitz.Rect, page_rect: fitz.Rect, margin: float = 0.6) -> fitz.Rect:
    expanded = fitz.Rect(
        max(page_rect.x0, rect.x0 - margin),
        max(page_rect.y0, rect.y0 - margin),
        min(page_rect.x1, rect.x1 + margin),
        min(page_rect.y1, rect.y1 + margin),
    )
    return expanded


def _insert_translated_text(
    page: fitz.Page,
    block: PdfTextBlock,
    text: str,
) -> tuple[bool, float]:
    fontfile = _windows_cyrillic_font()
    fontname = "wllfont" if fontfile else "helv"

    start_size = min(max(block.font_size, 6.0), 22.0)
    minimum_size = 4.5
    size = start_size

    rect = _expanded_rect(block.rect, page.rect, margin=0.5)

    while size >= minimum_size:
        result = page.insert_textbox(
            rect,
            text,
            fontsize=size,
            fontname=fontname,
            fontfile=fontfile,
            align=block.alignment,
            color=block.color,
            lineheight=1.0,
            rotate=block.rotation,
            overlay=True,
        )
        if result >= 0:
            return True, size
        size -= 0.35

    # Последняя попытка в слегка увеличенной области, не выходящей за страницу.
    fallback_rect = _expanded_rect(block.rect, page.rect, margin=2.0)
    result = page.insert_textbox(
        fallback_rect,
        text,
        fontsize=minimum_size,
        fontname=fontname,
        fontfile=fontfile,
        align=block.alignment,
        color=block.color,
        lineheight=0.95,
        rotate=block.rotation,
        overlay=True,
    )
    return result >= 0, minimum_size


def _page_has_images(page: fitz.Page) -> bool:
    try:
        return bool(page.get_images(full=True))
    except Exception:
        return False


def translate_pdf(
    source: Path,
    destination: Path,
    config: AppConfig,
    progress: Progress,
) -> Path:
    doc = fitz.open(str(source))
    total_pages = max(doc.page_count, 1)
    warnings: list[str] = []
    processed_blocks = 0

    try:
        for page_index in range(doc.page_count):
            page = doc[page_index]
            blocks = _extract_pdf_blocks(page)

            if not blocks:
                image_note = " На странице есть изображения." if _page_has_images(page) else ""
                warnings.append(
                    f"PDF, страница {page_index + 1}: текстовый слой не найден; "
                    f"возможно, требуется OCR.{image_note}"
                )
                _safe_progress(
                    progress,
                    int((page_index + 1) / total_pages * 100),
                    f"PDF: страница {page_index + 1}/{doc.page_count}",
                )
                continue

            # Сначала переводим. Если отдельный блок упадёт, оригинал останется на месте.
            translated_blocks: list[tuple[PdfTextBlock, str]] = []
            for block_number, block in enumerate(blocks, start=1):
                try:
                    translated = translate_text(block.text, config)
                    translated_blocks.append((block, translated))
                    warnings.extend(
                        qa_text(
                            translated,
                            f"PDF, страница {page_index + 1}, блок {block_number}",
                            source_text=block.text,
                        ).warnings
                    )
                except Exception as exc:
                    warnings.append(
                        f"PDF, страница {page_index + 1}, блок {block_number}: "
                        f"ошибка перевода — {exc}"
                    )

                _safe_progress(
                    progress,
                    int(((page_index + block_number / len(blocks)) / total_pages) * 100),
                    f"PDF: страница {page_index + 1}/{doc.page_count}, "
                    f"блок {block_number}/{len(blocks)}",
                )

            if not translated_blocks:
                continue

            # Удаляем только успешно переведённые блоки.
            for block, _ in translated_blocks:
                page.add_redact_annot(
                    _expanded_rect(block.rect, page.rect, margin=0.4),
                    fill=(1, 1, 1),
                )

            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

            for block_number, (block, translated) in enumerate(translated_blocks, start=1):
                inserted, used_size = _insert_translated_text(page, block, translated)
                processed_blocks += 1

                if not inserted:
                    warnings.append(
                        f"PDF, страница {page_index + 1}, блок {block_number}: "
                        "перевод не поместился даже при минимальном размере шрифта"
                    )
                elif used_size < max(5.0, block.font_size * 0.55):
                    warnings.append(
                        f"PDF, страница {page_index + 1}, блок {block_number}: "
                        f"шрифт сильно уменьшен до {used_size:.1f} pt"
                    )

            _safe_progress(
                progress,
                int((page_index + 1) / total_pages * 100),
                f"PDF: завершена страница {page_index + 1}/{doc.page_count}",
            )

        destination.parent.mkdir(parents=True, exist_ok=True)

        # incremental=False, так как destination является новым файлом.
        doc.save(
            str(destination),
            garbage=4,
            deflate=True,
            clean=True,
            pretty=False,
        )
    finally:
        doc.close()

    return _write_qa_report(
        destination,
        warnings,
        source=source,
        processed_units=processed_blocks,
    )
