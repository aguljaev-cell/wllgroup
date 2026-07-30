from __future__ import annotations

import re
from collections.abc import Iterator
import requests

from .config import AppConfig

SYSTEM_PROMPT = """Ты профессиональный технический переводчик с китайского и английского на русский язык.
Переводи точно, естественно и единообразно. Сохраняй числа, единицы измерения, обозначения,
артикулы, коды ошибок и структуру строк. Не добавляй пояснений. Не оставляй китайские и английские
фрагменты, кроме общепринятых обозначений. Для оборудования используй нормативную русскую терминологию.
Примеры: clamping unit = узел смыкания; injection unit = узел впрыска; mold = пресс-форма;
nozzle = сопло; screw = шнек; hydraulic oil = гидравлическое масло; control panel = панель управления.
Верни только перевод."""


def split_long_text(text: str, max_chars: int = 2800) -> Iterator[str]:
    if len(text) <= max_chars:
        yield text
        return
    parts = re.split(r"(?<=[.!?。！？\n])", text)
    current = ""
    for part in parts:
        if len(current) + len(part) > max_chars and current:
            yield current
            current = part
        else:
            current += part
    if current:
        yield current


def translate_text(text: str, config: AppConfig) -> str:
    if not text.strip():
        return text
    payload = {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": config.temperature,
        "stream": False,
        "max_tokens": 4096,
    }
    response = requests.post(f"{config.server_url}/v1/chat/completions", json=payload, timeout=600)
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"].strip()
