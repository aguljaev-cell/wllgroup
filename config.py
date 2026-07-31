from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "PDFMathTranslate WLL"
APP_VERSION = "0.5.0"
ORGANIZATION_NAME = "WorldLogicLine"

def _default_local_app_data() -> Path:
    if os.name == "nt":
        value = os.environ.get("LOCALAPPDATA")
        if value:
            return Path(value)
        return Path.home() / "AppData" / "Local"
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home)
    return Path.home() / ".local" / "share"

def app_data_dir() -> Path:
    path = (_default_local_app_data() / ORGANIZATION_NAME / "PDFMathTranslate_WLL")
    path.mkdir(parents=True, exist_ok=True)
    return path

def models_dir() -> Path:
    path = app_data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path

def logs_dir() -> Path:
    path = app_data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path

def temp_dir() -> Path:
    path = app_data_dir() / "temp"
    path.mkdir(parents=True, exist_ok=True)
    return path

def _default_threads() -> int:
    cpu_count = os.cpu_count() or 4
    return max(1, cpu_count - 1)

@dataclass(slots=True)
class AppConfig:
    model_url: str = (
        "https://huggingface.co/bartowski/"
        "Qwen2.5-7B-Instruct-GGUF/resolve/main/"
        "Qwen2.5-7B-Instruct-Q4_K_M.gguf?download=true"
    )
    model_filename: str = "Qwen2.5-7B-Instruct-Q4_K_M.gguf"

    model_size: int | None = None
    model_sha256: str | None = None

    server_host: str = "127.0.0.1"
    server_port: int = 8091

    context_size: int = 8192
    batch_size: int = 256
    threads: int = 0
    gpu_layers: int = 99

    temperature: float = 0.05
    request_timeout: int = 900

    def __post_init__(self) -> None:
        if self.threads <= 0:
            self.threads = _default_threads()
        self.server_port = max(1, min(65535, int(self.server_port)))
        self.context_size = max(2048, int(self.context_size))
        self.batch_size = max(32, int(self.batch_size))
        self.gpu_layers = max(0, int(self.gpu_layers))
        self.temperature = max(0.0, min(1.0, float(self.temperature)))
        self.request_timeout = max(60, int(self.request_timeout))

    @property
    def model_path(self) -> Path:
        return models_dir() / self.model_filename

    @property
    def server_url(self) -> str:
        return f"http://{self.server_host}:{self.server_port}"

    @property
    def log_file(self) -> Path:
        return logs_dir() / "application.log"
