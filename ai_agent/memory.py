import json
from pathlib import Path

MEMORY_PATH = Path(__file__).parent / "data" / "memory.json"


def _load() -> list[dict]:
    if not MEMORY_PATH.exists():
        return []
    return json.loads(MEMORY_PATH.read_text(encoding="utf-8"))


def remember(text: str) -> None:
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    items = _load()
    items.append({"text": text})
    MEMORY_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def recall(limit: int = 20) -> list[str]:
    return [item["text"] for item in _load()[-limit:]]
