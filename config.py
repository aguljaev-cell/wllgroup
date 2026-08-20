from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "PDFMathTranslate WLL"
APP_VERSION = "0.6.2"
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
        "https://huggingface.co/mradermacher/"
        "translategemma-4b-it-GGUF/resolve/"
        "35a7486e128b19642cdc72d7b91b21ba388aaf42/"
        "translategemma-4b-it.Q4_K_M.gguf?download=true"
    )
    model_filename: str = "translategemma-4b-it.Q4_K_M.gguf"

    model_size: int | None = 2_489_909_760
    model_sha256: str | None = (
        "81200d03e843d2ec1ece6eeafe7d13cb"
        "6e5211e1fcd336ade55790b683a08330"
    )

    server_host: str = "127.0.0.1"
    server_port: int = 8091

    context_size: int = 4096
    batch_size: int = 128
    threads: int = 0
    gpu_layers: int = 28
    gpu_layer_candidates: tuple[int, ...] = (28, 20, 12, 4)

    temperature: float = 0.05
    request_timeout: int = 300
    max_output_tokens: int = 1536

    def __post_init__(self) -> None:
        if self.threads <= 0:
            self.threads = _default_threads()
        self.server_port = max(1, min(65535, int(self.server_port)))
        self.context_size = max(2048, int(self.context_size))
        self.batch_size = max(32, int(self.batch_size))
        self.gpu_layers = max(0, int(self.gpu_layers))
        self.gpu_layer_candidates = tuple(
            sorted(
                {
                    max(0, int(value))
                    for value in self.gpu_layer_candidates
                    if int(value) > 0
                },
                reverse=True,
            )
        )
        self.temperature = max(0.0, min(1.0, float(self.temperature)))
        self.request_timeout = max(60, int(self.request_timeout))
        self.max_output_tokens = max(256, min(4096, int(self.max_output_tokens)))

    @property
    def model_path(self) -> Path:
        return models_dir() / self.model_filename

    @property
    def server_url(self) -> str:
        return f"http://{self.server_host}:{self.server_port}"

    @property
    def log_file(self) -> Path:
        return logs_dir() / "application.log"
