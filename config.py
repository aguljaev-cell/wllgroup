from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

APP_NAME = "PDFMathTranslate WLL"
APP_VERSION = "0.3.0"


def app_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    path = base / "WorldLogicLine" / "PDFMathTranslate_WLL"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class AppConfig:
    model_url: str = (
        "https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/"
        "qwen2.5-7b-instruct-q4_k_m.gguf"
    )
    model_filename: str = "qwen2.5-7b-instruct-q4_k_m.gguf"
    server_host: str = "127.0.0.1"
    server_port: int = 8091
    context_size: int = 8192
    temperature: float = 0.1

    @property
    def model_path(self) -> Path:
        return app_data_dir() / "models" / self.model_filename

    @property
    def server_url(self) -> str:
        return f"http://{self.server_host}:{self.server_port}"
