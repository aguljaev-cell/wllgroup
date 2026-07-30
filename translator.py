from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass

import requests

from config import AppConfig

SYSTEM_PROMPT = """Ты профессиональный технический переводчик промышленной документации с китайского и английского на русский язык.

Обязательные правила:
1. Переводи точно, естественно и единообразно.
2. Не добавляй пояснений, комментариев и предисловий.
3. Сохраняй числа, единицы измерения, артикулы, коды ошибок, обозначения, формулы и структуру строк.
4. Не переводи названия моделей, марки оборудования, номера деталей, переменные и программные команды.
5. Не оставляй китайские или английские фрагменты, кроме общепринятых технических обозначений.
6. Используй нормативную русскую терминологию, а не буквальные кальки.
7. Верни только перевод исходного текста.

Предпочтительная терминология:
clamping unit = узел смыкания
injection unit = узел впрыска
mold / mould = пресс-форма
nozzle = сопло
screw = шнек
barrel = материальный цилиндр
hydraulic oil = гидравлическое масло
control panel = панель управления
limit switch = концевой выключатель
proximity switch = датчик приближения
servo motor = серводвигатель
emergency stop = аварийная остановка
cooling water = охлаждающая вода
lubrication = смазка
pressure gauge = манометр
solenoid valve = электромагнитный клапан
check valve = обратный клапан
safety door = защитная дверь
moving platen = подвижная плита
fixed platen = неподвижная плита
tie bar = колонна
PET preform = ПЭТ-преформа
robot arm = манипулятор
pick-and-place = захват и укладка
"""

GLOSSARY: dict[str, str] = {
    "clamping unit": "узел смыкания",
    "injection unit": "узел впрыска",
    "hydraulic oil": "гидравлическое масло",
    "control panel": "панель управления",
    "limit switch": "концевой выключатель",
    "proximity switch": "датчик приближения",
    "servo motor": "серводвигатель",
    "emergency stop": "аварийная остановка",
    "cooling water": "охлаждающая вода",
    "pressure gauge": "манометр",
    "solenoid valve": "электромагнитный клапан",
    "check valve": "обратный клапан",
    "safety door": "защитная дверь",
    "moving platen": "подвижная плита",
    "fixed platen": "неподвижная плита",
    "tie bar": "колонна",
    "pet preform": "ПЭТ-преформа",
    "robot arm": "манипулятор",
    "nozzle": "сопло",
    "screw": "шнек",
    "barrel": "материальный цилиндр",
    "mould": "пресс-форма",
    "mold": "пресс-форма",
}

BAD_TRANSLATIONS: tuple[str, ...] = (
    "кламп",
    "инъекция guidance",
    "зелёная палочка",
    "метаморфоз масла",
    "жижа",
    "впрыскивающий блок",
)

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_WORD_RE = re.compile(r"\b[A-Za-z]{4,}\b")


@dataclass(slots=True)
class QAResult:
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.warnings


def split_long_text(text: str, max_chars: int = 2400) -> Iterator[str]:
    if len(text) <= max_chars:
        yield text
        return
    parts = re.split(r"(?<=[.!?。！？;；\n])", text)
    current = ""
    for part in parts:
        if len(current) + len(part) > max_chars and current:
            yield current
            current = part
        else:
            current += part
    if current:
        yield current


def should_translate(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    letters = sum(ch.isalpha() for ch in stripped)
    if letters == 0:
        return False
    if len(stripped) <= 2:
        return False
    return True


def _clean_model_output(text: str) -> str:
    text = text.strip()
    prefixes = (
        "Перевод:",
        "Переведенный текст:",
        "Переведённый текст:",
        "Russian translation:",
    )
    for prefix in prefixes:
        if text.lower().startswith(prefix.lower()):
            text = text[len(prefix):].lstrip()
    return text.strip('"')


def translate_text(text: str, config: AppConfig) -> str:
    if not should_translate(text):
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
    response = requests.post(
        f"{config.server_url}/v1/chat/completions",
        json=payload,
        timeout=config.request_timeout,
    )
    response.raise_for_status()
    data = response.json()
    translated = _clean_model_output(data["choices"][0]["message"]["content"])
    return translated or text


def qa_text(text: str, label: str = "текст") -> QAResult:
    warnings: list[str] = []
    cjk_count = len(_CJK_RE.findall(text))
    if cjk_count:
        warnings.append(f"{label}: осталось китайских иероглифов — {cjk_count}")

    bad = [term for term in BAD_TRANSLATIONS if term.casefold() in text.casefold()]
    if bad:
        warnings.append(f"{label}: подозрительные переводы — {', '.join(bad)}")

    latin_words = [w for w in _LATIN_WORD_RE.findall(text) if w.casefold() not in {
        "error", "reset", "start", "stop", "manual", "auto", "mode", "alarm",
        "servo", "input", "output", "open", "close", "setup", "home",
    }]
    if len(latin_words) > 20:
        warnings.append(f"{label}: много непереведённых английских слов — {len(latin_words)}")

    return QAResult(warnings)
