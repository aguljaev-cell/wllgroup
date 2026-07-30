from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

import requests

from .config import AppConfig, app_data_dir

Progress = Callable[[int, str], None]


def resource_path(relative: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return root / relative


def llama_server_path() -> Path:
    name = "llama-server.exe" if os.name == "nt" else "llama-server"
    return resource_path(f"vendor/llama/{name}")


def model_installed(config: AppConfig) -> bool:
    return config.model_path.exists() and config.model_path.stat().st_size > 1_000_000_000


def download_model(config: AppConfig, progress: Progress) -> Path:
    destination = config.model_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    headers = {}
    existing = partial.stat().st_size if partial.exists() else 0
    if existing:
        headers["Range"] = f"bytes={existing}-"

    with requests.get(config.model_url, stream=True, timeout=(30, 120), headers=headers) as response:
        if response.status_code not in (200, 206):
            response.raise_for_status()
        total = int(response.headers.get("content-length", "0")) + existing
        mode = "ab" if response.status_code == 206 and existing else "wb"
        downloaded = existing if mode == "ab" else 0
        with partial.open(mode) as handle:
            for chunk in response.iter_content(chunk_size=4 * 1024 * 1024):
                if not chunk:
                    continue
                handle.write(chunk)
                downloaded += len(chunk)
                percent = int(downloaded * 100 / total) if total else 0
                progress(percent, f"Загрузка языковой модели: {downloaded/1e9:.2f} из {total/1e9:.2f} ГБ")
    partial.replace(destination)
    progress(100, "Языковая модель установлена")
    return destination


class LocalModelServer:
    def __init__(self, config: AppConfig):
        self.config = config
        self.process: subprocess.Popen | None = None

    def is_ready(self) -> bool:
        try:
            response = requests.get(f"{self.config.server_url}/health", timeout=2)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def start(self, progress: Progress) -> None:
        if self.is_ready():
            return
        executable = llama_server_path()
        if not executable.exists():
            raise RuntimeError(f"В сборке отсутствует локальный движок: {executable}")
        if not model_installed(self.config):
            raise RuntimeError("Языковая модель ещё не установлена")

        log_dir = app_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = (log_dir / "llama-server.log").open("a", encoding="utf-8")
        args = [
            str(executable),
            "-m", str(self.config.model_path),
            "--host", self.config.server_host,
            "--port", str(self.config.server_port),
            "-c", str(self.config.context_size),
            "-ngl", "99",
        ]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            args,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
        )
        for second in range(120):
            if self.is_ready():
                progress(100, "Локальный переводчик запущен")
                return
            if self.process.poll() is not None:
                raise RuntimeError("Локальный переводчик завершился с ошибкой. См. журнал llama-server.log")
            progress(min(99, second), "Запуск локальной языковой модели…")
            time.sleep(1)
        raise RuntimeError("Не удалось запустить локальную модель за 120 секунд")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
