from __future__ import annotations

import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import requests

from config import AppConfig


SYSTEM_PROMPT = """Ты профессиональный технический переводчик промышленной документации с китайского и английского на русский язык.

ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА:
1. Переводи точно, естественно и единообразно.
2. Возвращай только перевод, без пояснений, комментариев, заголовков и кавычек.
3. Строго сохраняй абзацы, переносы строк, нумерацию, маркированные списки и порядок строк.
4. Не изменяй числа, единицы измерения, допуски, артикулы, обозначения, коды ошибок, формулы, переменные, команды, URL и адреса электронной почты.
5. Не переводи названия моделей, торговые марки, номера деталей и программные идентификаторы.
6. Не оставляй китайский или английский текст, кроме общепринятых обозначений и защищённых технических токенов.
7. Используй нормативную русскую техническую терминологию. Не применяй транслитерацию и буквальные кальки.
8. Не сокращай и не расширяй смысл. Не придумывай сведения, которых нет в исходнике.
9. Если термин допускает несколько вариантов, выбирай значение по контексту оборудования.
10. Любые фрагменты вида ⟦WLL_0001⟧ необходимо вернуть без изменений.

ПРЕДПОЧТИТЕЛЬНАЯ ТЕРМИНОЛОГИЯ:
clamping unit = узел смыкания
clamping part = узел смыкания
clamping force = усилие смыкания
injection unit = узел впрыска
injection part = узел впрыска
injection system = система впрыска
injection pressure = давление впрыска
injection molding = литьё пластмасс под давлением
injection molding machine = термопластавтомат
mold / mould = пресс-форма
nozzle = сопло
screw = шнек
barrel = материальный цилиндр
hydraulic oil = гидравлическое масло
control panel = панель управления
control cabinet = шкаф управления
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
preform = преформа
take-out robot = робот-съёмщик
robot arm = манипулятор
pick-and-place = захват и укладка
hopper = загрузочный бункер
heater band = ленточный нагреватель
back pressure = противодавление
holding pressure = давление выдержки
mold opening = раскрытие пресс-формы
mold closing = смыкание пресс-формы
ejector = выталкиватель
core pull = привод стержня
cycle time = время цикла
shot weight = масса впрыска
alarm history = журнал аварий
maintenance = техническое обслуживание
troubleshooting = поиск и устранение неисправностей
operation manual = руководство по эксплуатации
semi-automatic = полуавтоматический режим
manual operation = ручной режим
automatic operation = автоматический режим
hydraulic circuit = гидравлическая система
test run = пробный запуск
air bleeding = удаление воздуха
"""


GLOSSARY: dict[str, str] = {
    "alarm history": "журнал аварий",
    "back pressure": "противодавление",
    "barrel": "материальный цилиндр",
    "check valve": "обратный клапан",
    "clamping force": "усилие смыкания",
    "clamping part": "узел смыкания",
    "clamping unit": "узел смыкания",
    "control cabinet": "шкаф управления",
    "control panel": "панель управления",
    "cooling water": "охлаждающая вода",
    "core pull": "привод стержня",
    "cycle time": "время цикла",
    "emergency stop": "аварийная остановка",
    "ejector": "выталкиватель",
    "fixed platen": "неподвижная плита",
    "heater band": "ленточный нагреватель",
    "holding pressure": "давление выдержки",
    "hopper": "загрузочный бункер",
    "hydraulic oil": "гидравлическое масло",
    "injection pressure": "давление впрыска",
    "injection part": "узел впрыска",
    "injection system": "система впрыска",
    "injection molding machine": "термопластавтомат",
    "injection molding": "литьё пластмасс под давлением",
    "injection unit": "узел впрыска",
    "limit switch": "концевой выключатель",
    "lubrication": "смазка",
    "maintenance": "техническое обслуживание",
    "mold closing": "смыкание пресс-формы",
    "mold opening": "раскрытие пресс-формы",
    "moving platen": "подвижная плита",
    "mould": "пресс-форма",
    "mold": "пресс-форма",
    "nozzle": "сопло",
    "pet preform": "ПЭТ-преформа",
    "preform": "преформа",
    "pick-and-place": "захват и укладка",
    "pressure gauge": "манометр",
    "proximity switch": "датчик приближения",
    "robot arm": "манипулятор",
    "safety door": "защитная дверь",
    "screw": "шнек",
    "servo motor": "серводвигатель",
    "shot weight": "масса впрыска",
    "solenoid valve": "электромагнитный клапан",
    "tie bar": "колонна",
    "take-out robot": "робот-съёмщик",
    "troubleshooting": "поиск и устранение неисправностей",
    "operation manual": "руководство по эксплуатации",
    "semi-automatic": "полуавтоматический режим",
    "manual operation": "ручной режим",
    "automatic operation": "автоматический режим",
    "hydraulic circuit": "гидравлическая система",
    "test run": "пробный запуск",
    "air bleeding": "удаление воздуха",
}


BAD_TRANSLATIONS: tuple[str, ...] = (
    "кламп",
    "инъекция guidance",
    "зелёная палочка",
    "метаморфоз масла",
    "жижа",
    "впрыскивающий блок",
    "зажимной блок",
    "формовочная машина",
    "масляная дорога",
    "водяная дорога",
    "reciprocаль",
    "инжекционная мельница",
    "превмогу",
    "precision machinery serial",
    "монтажа оборудования для впрыска",
    "семиатомный",
    "токсичное масло",
    "замесить пластики",
    "впихнуть",
    "пластожиж",
    "каталог 1 (впрыска)",
)


_ALLOWED_LATIN_WORDS = {
    "alarm", "auto", "bar", "close", "error", "home", "input", "manual",
    "mode", "open", "output", "reset", "servo", "setup", "start", "stop",
    "test", "usb", "wifi", "ethernet", "plc", "hmi", "pid", "cnc", "cad",
    "cam", "pdf", "docx", "rpm", "pet", "abs", "pvc", "pa", "pc", "pp",
    "kronce", "hangzhou", "shanghai", "andy", "enterprise", "development",
    "precision", "machinery",
}


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
_LATIN_WORD_RE = re.compile(r"\b[A-Za-z][A-Za-z-]{3,}\b")
_CYRILLIC_WORD_RE = re.compile(r"\b[А-Яа-яЁё][А-Яа-яЁё-]{2,}\b")
_SPACE_BEFORE_PUNCT_RE = re.compile(r"\s+([,.;:!?%)\]])")
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_PLACEHOLDER_RE = re.compile(r"⟦WLL_\d{4}⟧")
_PLACEHOLDER_BODY_RE = re.compile(r"WLL_\d{4}")

_PROMPT_LEAK_MARKERS: tuple[str, ...] = (
    "исходный текст:",
    "термины, обязательные для этого фрагмента:",
    "переведи следующий фрагмент",
    "переведи текст ниже",
    "только русский перевод следующего текста",
    "обязательные правила:",
    "предпочтительная терминология:",
)

_PROTECTED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"https?://\S+", re.IGNORECASE),
    re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    # Standards must start with an uppercase standard prefix and contain a
    # separator or a number.  The previous case-insensitive expression also
    # matched ordinary words beginning with "en"/"un", such as Enterprise,
    # environment, enough and unit, causing valid translations to be rejected.
    re.compile(
        r"\b(?:UN|ISO|IEC|DIN|EN|GB|GOST|ГОСТ)"
        r"(?:[-– ]?\d[A-ZА-Я0-9./:-]*|[-– ][A-ZА-Я][A-ZА-Я0-9./:-]*)\b"
    ),
    re.compile(r"\b[A-Z]{1,8}[-_/][A-Z0-9][A-Z0-9._/-]*\b"),
    re.compile(r"\b[A-Z]{2,}\d[A-Z0-9._/-]*\b"),
    re.compile(r"\b\d+(?:[.,]\d+)?\s*(?:mm|cm|m|km|kg|g|mg|t|kN|N|MPa|kPa|Pa|bar|psi|°C|°F|V|kV|A|mA|W|kW|Hz|rpm|r/min|s|ms|min|h|L|ml|m³|cm³|mm²|mm³)\b", re.IGNORECASE),
    re.compile(r"\b\d+(?:[.,]\d+)?\s*[×xX]\s*\d+(?:[.,]\d+)?(?:\s*[×xX]\s*\d+(?:[.,]\d+)?)?\b"),
    re.compile(r"\b(?:0x)?[A-F0-9]{6,}\b", re.IGNORECASE),
)


@dataclass(slots=True)
class QAResult:
    warnings: list[str]
    metrics: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.warnings


@dataclass(slots=True)
class _ProtectedText:
    text: str
    values: dict[str, str]


def split_long_text(text: str, max_chars: int = 1100) -> Iterator[str]:
    if max_chars < 300:
        raise ValueError("max_chars must be at least 300")

    if len(text) <= max_chars:
        yield text
        return

    blocks = text.splitlines(keepends=True) or [text]
    current = ""

    for block in blocks:
        if not block:
            continue

        if len(current) + len(block) <= max_chars:
            current += block
            continue

        if current:
            yield current
            current = ""

        if len(block) <= max_chars:
            current = block
            continue

        sentences = re.split(r"(?<=[.!?。！？;；:：\n])", block)
        for sentence in sentences:
            if not sentence:
                continue
            if len(current) + len(sentence) <= max_chars:
                current += sentence
                continue
            if current:
                yield current
                current = ""

            while len(sentence) > max_chars:
                cut = sentence.rfind(" ", 0, max_chars)
                if cut < max_chars // 2:
                    cut = max_chars
                yield sentence[:cut]
                sentence = sentence[cut:]
            current = sentence

    if current:
        yield current


def should_translate(text: str) -> bool:
    stripped = text.strip()
    if not stripped or len(stripped) <= 2:
        return False

    letters = sum(ch.isalpha() for ch in stripped)
    if letters == 0:
        return False

    compact = re.sub(r"[\W_]+", "", stripped, flags=re.UNICODE)
    if compact and not any(ch.islower() for ch in compact) and not _CJK_RE.search(compact):
        if len(compact) <= 40:
            words = re.findall(r"[A-Z]{3,}", stripped)
            natural_heading = len(words) >= 2 or (
                len(words) == 1
                and len(words[0]) >= 8
                and not any(ch.isdigit() for ch in stripped)
            )
            if not natural_heading:
                return False

    return True


def _clean_model_output(text: str) -> str:
    text = text.replace("\r\n", "\n").strip()

    prefixes = (
        "Перевод:",
        "Переведенный текст:",
        "Переведённый текст:",
        "Russian translation:",
        "Translation:",
        "Ответ:",
    )
    for prefix in prefixes:
        if text.casefold().startswith(prefix.casefold()):
            text = text[len(prefix):].lstrip()

    if text.startswith("```") and text.endswith("```"):
        text = re.sub(r"^```[a-zA-Zа-яА-Я]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1]

    text = _SPACE_BEFORE_PUNCT_RE.sub(r"\1", text)
    text = "\n".join(_MULTI_SPACE_RE.sub(" ", line).rstrip() for line in text.splitlines())
    return text.strip()


def _protect_values(text: str) -> _ProtectedText:
    values: dict[str, str] = {}
    protected = text

    for pattern in _PROTECTED_PATTERNS:
        def replace(match: re.Match[str]) -> str:
            value = match.group(0)

            # Patterns are applied one after another.  Do not protect the body
            # of an internal marker created by an earlier pattern; otherwise
            # ⟦WLL_0001⟧ becomes a nested marker and cannot be restored.
            start, end = match.span()
            if (
                _PLACEHOLDER_BODY_RE.fullmatch(value)
                and start > 0
                and end < len(match.string)
                and match.string[start - 1] == "⟦"
                and match.string[end] == "⟧"
            ):
                return value

            token = f"⟦WLL_{len(values) + 1:04d}⟧"
            values[token] = value
            return token

        protected = pattern.sub(replace, protected)

    return _ProtectedText(protected, values)


def _restore_values(text: str, values: dict[str, str]) -> str:
    restored = text
    for token, value in values.items():
        restored = restored.replace(token, value)
    return restored


def _build_user_prompt(text: str) -> str:
    return (
        "Переведи текст ниже на русский язык. "
        "Выведи только перевод, без задания и исходного текста.\n\n"
        f"{text}"
    )


def _build_retry_prompt(text: str) -> str:
    return f"Только русский перевод следующего текста, без пояснений:\n{text}"


def _prompt_leak_markers(text: str) -> list[str]:
    lowered = re.sub(r"\s+", " ", text.casefold())
    return [
        marker
        for marker in _PROMPT_LEAK_MARKERS
        if re.sub(r"\s+", " ", marker.casefold()) in lowered
    ]


def _source_echo_is_excessive(source: str, translated: str) -> bool:
    source_lines = [line.strip() for line in source.splitlines() if line.strip()]
    if len(source_lines) < 4:
        return False

    candidates = [
        line
        for line in source_lines
        if len(line) >= 18
        and sum(ch.isascii() and ch.isalpha() for ch in line)
        >= max(8, sum(ch.isalpha() for ch in line) // 2)
    ]
    if len(candidates) < 3:
        return False

    normalized_translation = re.sub(r"\s+", " ", translated.casefold())
    echoed = sum(
        re.sub(r"\s+", " ", line.casefold()) in normalized_translation
        for line in candidates
    )
    return echoed >= max(3, (len(candidates) + 2) // 3)


def _validate_model_translation(source: str, translated: str) -> None:
    leaked = _prompt_leak_markers(translated)
    if leaked:
        raise RuntimeError("Модель повторила служебный текст задания")

    cjk_count = len(_CJK_RE.findall(translated))
    if cjk_count:
        raise RuntimeError(
            f"В ответе модели остались китайские иероглифы: {cjk_count}"
        )

    bad = [term for term in BAD_TRANSLATIONS if term.casefold() in translated.casefold()]
    if bad:
        raise RuntimeError(
            "Модель использовала недопустимые технические формулировки: "
            + ", ".join(bad[:4])
        )

    source_len = max(len(source.strip()), 1)
    if len(translated.strip()) > source_len * 2.2:
        raise RuntimeError("Ответ модели подозрительно длинный")

    if _source_echo_is_excessive(source, translated):
        raise RuntimeError("Модель повторила значительную часть исходного текста")

    source_lines = [line for line in source.splitlines() if line.strip()]
    result_lines = [line for line in translated.splitlines() if line.strip()]
    if len(source_lines) >= 3 and len(result_lines) < max(2, (len(source_lines) + 1) // 2):
        raise RuntimeError(
            "Модель нарушила структуру строк "
            f"({len(source_lines)} → {len(result_lines)})"
        )

    latin_words = [
        word
        for word in _LATIN_WORD_RE.findall(translated)
        if word.casefold() not in _ALLOWED_LATIN_WORDS
    ]
    cyrillic_words = _CYRILLIC_WORD_RE.findall(translated)
    source_latin_words = _LATIN_WORD_RE.findall(source)

    normalized_source = re.sub(r"\s+", " ", source.casefold()).strip()
    normalized_result = re.sub(r"\s+", " ", translated.casefold()).strip()
    if (
        normalized_source == normalized_result
        and len(source_latin_words) >= 2
        and latin_words
    ):
        raise RuntimeError("Модель вернула исходный английский текст без перевода")

    if cyrillic_words and latin_words:
        examples = ", ".join(dict.fromkeys(latin_words[:5]))
        raise RuntimeError("В переводе остались английские слова: " + examples)

    if (
        len(source_latin_words) >= 4
        and not cyrillic_words
        and len(latin_words) >= max(3, (len(source_latin_words) + 1) // 2)
    ):
        raise RuntimeError("Модель вернула непереведённый английский текст")


def _post_json(
    url: str,
    payload: dict[str, Any],
    timeout: float,
    retries: int = 1,
) -> dict[str, Any]:
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            response = requests.post(url, json=payload, timeout=timeout)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Сервер вернул JSON неправильного формата")
            return data
        except requests.Timeout as exc:
            raise RuntimeError(
                "Языковая модель превысила лимит времени. "
                "Повтор этого же блока отключён, чтобы программа не зациклилась."
            ) from exc
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
            if attempt == retries:
                break
            time.sleep(min(1.5 * attempt, 4.0))

    assert last_error is not None
    raise RuntimeError(f"Ошибка обращения к языковой модели: {last_error}") from last_error


def _extract_response_text(data: dict[str, Any]) -> str:
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        detail = data.get("error") if isinstance(data, dict) else None
        raise RuntimeError(f"Сервер модели вернул неожиданный ответ: {detail or data}") from exc

    if not isinstance(content, str):
        raise RuntimeError("Сервер модели не вернул текст перевода")
    return content


def _translate_chunk(text: str, config: AppConfig) -> str:
    protected = _protect_values(text)
    prompts = (_build_user_prompt(protected.text), _build_retry_prompt(protected.text))
    last_error: RuntimeError | None = None

    for attempt, user_prompt in enumerate(prompts):
        payload: dict[str, Any] = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0 if attempt else float(getattr(config, "temperature", 0.1)),
            "stream": False,
            "max_tokens": int(getattr(config, "max_output_tokens", 1536)),
        }

        model_name = getattr(config, "model_name", None) or getattr(config, "model", None)
        if model_name:
            payload["model"] = model_name

        server_url = str(config.server_url).rstrip("/")
        timeout = float(getattr(config, "request_timeout", 300))
        data = _post_json(
            f"{server_url}/v1/chat/completions",
            payload,
            timeout=timeout,
        )
        translated = _clean_model_output(_extract_response_text(data))
        translated = _restore_values(translated, protected.values)

        missing = [value for value in protected.values.values() if value not in translated]
        try:
            if missing:
                raise RuntimeError(
                    "Модель изменила защищённые технические значения: "
                    + ", ".join(missing[:5])
                )
            _validate_model_translation(text, translated)
            return translated or text
        except RuntimeError as exc:
            last_error = exc

    assert last_error is not None
    raise last_error


def _retry_split_position(text: str) -> int | None:
    """Choose a balanced semantic boundary for a smaller translation request."""
    if len(text.strip()) < 24 and "\n" not in text:
        return None

    midpoint = len(text) / 2
    minimum_side = max(4, min(48, len(text) // 5))
    patterns = (
        r"\n+",
        r"(?<=[.!?。！？;；:：])\s+",
        r"(?<=[,，])\s+",
        r"\s+",
    )
    for pattern in patterns:
        positions = [
            match.end()
            for match in re.finditer(pattern, text)
            if match.end() >= minimum_side
            and len(text) - match.end() >= minimum_side
        ]
        if positions:
            return min(positions, key=lambda value: abs(value - midpoint))
    return None


def _translate_resilient(
    text: str,
    config: AppConfig,
    *,
    depth: int = 0,
    max_depth: int = 6,
) -> str:
    """Translate a fragment, recursively reducing only rejected requests."""
    leading_match = re.match(r"^\s*", text)
    trailing_match = re.search(r"\s*$", text)
    leading = leading_match.group(0) if leading_match else ""
    trailing = trailing_match.group(0) if trailing_match else ""
    core_end = len(text) - len(trailing) if trailing else len(text)
    core = text[len(leading):core_end]

    if not should_translate(core):
        return text

    try:
        return leading + _translate_chunk(core, config) + trailing
    except RuntimeError as original_error:
        if depth >= max_depth:
            raise RuntimeError(
                "Фрагмент не прошёл проверку качества после дробления"
            ) from original_error

        position = _retry_split_position(core)
        if position is None:
            raise

        left = _translate_resilient(
            core[:position], config, depth=depth + 1, max_depth=max_depth
        )
        right = _translate_resilient(
            core[position:], config, depth=depth + 1, max_depth=max_depth
        )
        combined = left + right
        _validate_model_translation(core, combined)
        return leading + combined + trailing


def translate_text(text: str, config: AppConfig) -> str:
    if not should_translate(text):
        return text

    translated_chunks: list[str] = []

    for chunk in split_long_text(text):
        if should_translate(chunk):
            translated_chunks.append(_translate_resilient(chunk, config))
        else:
            translated_chunks.append(chunk)

    translated = "".join(translated_chunks)
    if translated.strip():
        _validate_model_translation(text, translated)
        return translated
    return text


def qa_text(
    text: str,
    label: str = "текст",
    source_text: str | None = None,
) -> QAResult:
    warnings: list[str] = []
    metrics: dict[str, int] = {}

    cjk_count = len(_CJK_RE.findall(text))
    metrics["cjk_characters"] = cjk_count
    if cjk_count:
        warnings.append(f"{label}: осталось китайских иероглифов — {cjk_count}")

    bad = [term for term in BAD_TRANSLATIONS if term.casefold() in text.casefold()]
    metrics["bad_terms"] = len(bad)
    if bad:
        warnings.append(f"{label}: подозрительные переводы — {', '.join(bad)}")

    latin_words = [
        word
        for word in _LATIN_WORD_RE.findall(text)
        if word.casefold() not in _ALLOWED_LATIN_WORDS
    ]
    metrics["latin_words"] = len(latin_words)
    if len(latin_words) > 20:
        examples = ", ".join(dict.fromkeys(latin_words[:8]))
        warnings.append(
            f"{label}: много непереведённых английских слов — "
            f"{len(latin_words)}; примеры: {examples}"
        )

    placeholders = _PLACEHOLDER_RE.findall(text)
    metrics["unrestored_placeholders"] = len(placeholders)
    if placeholders:
        warnings.append(
            f"{label}: остались внутренние маркеры защиты — {len(placeholders)}"
        )

    prompt_leaks = _prompt_leak_markers(text)
    metrics["prompt_leak_markers"] = len(prompt_leaks)
    if prompt_leaks:
        warnings.append(f"{label}: в перевод попал служебный текст задания")

    if source_text:
        source_len = max(len(source_text.strip()), 1)
        result_len = len(text.strip())
        ratio = result_len / source_len
        metrics["length_ratio_percent"] = round(ratio * 100)

        if result_len == 0:
            warnings.append(f"{label}: перевод пуст")
        elif ratio < 0.30:
            warnings.append(
                f"{label}: перевод подозрительно короткий "
                f"({round(ratio * 100)}% от исходного текста)"
            )
        elif ratio > 3.50:
            warnings.append(
                f"{label}: перевод подозрительно длинный "
                f"({round(ratio * 100)}% от исходного текста)"
            )

        source_lines = len(source_text.splitlines())
        result_lines = len(text.splitlines())
        metrics["source_lines"] = source_lines
        metrics["result_lines"] = result_lines

        if source_lines >= 3 and abs(source_lines - result_lines) > max(2, source_lines // 2):
            warnings.append(
                f"{label}: структура строк существенно изменилась "
                f"({source_lines} → {result_lines})"
            )

    return QAResult(warnings, metrics)


@lru_cache(maxsize=512)
def glossary_lookup(term: str) -> str | None:
    return GLOSSARY.get(term.strip().casefold())
