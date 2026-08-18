from __future__ import annotations

import os
import hashlib
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

import requests

from config import AppConfig, app_data_dir


Progress = Callable[[float, str], None]

_MIN_MODEL_SIZE = 500_000_000
_DOWNLOAD_CHUNK_SIZE = 4 * 1024 * 1024
_DOWNLOAD_RETRIES = 4
_SERVER_START_TIMEOUT = 180


def resource_path(relative: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root / relative


def llama_server_candidates(config: AppConfig) -> list[tuple[str, Path, int]]:
    """Возвращает безопасные варианты Vulkan, затем CPU."""
    name = "llama-server.exe" if os.name == "nt" else "llama-server"
    vulkan_path = resource_path(f"vendor/llama/vulkan/{name}")
    cpu_path = resource_path(f"vendor/llama/cpu/{name}")
    layer_options = tuple(getattr(config, "gpu_layer_candidates", (20, 12, 4)))
    candidates = [
        (f"Vulkan GPU ({layers} слоёв)", vulkan_path, int(layers))
        for layers in layer_options
        if int(layers) > 0
    ]
    candidates.append(("CPU", cpu_path, 0))
    return [(label, path, layers) for label, path, layers in candidates if path.exists()]


def model_installed(config: AppConfig) -> bool:
    path = Path(config.model_path)
    try:
        return path.is_file() and path.stat().st_size >= _MIN_MODEL_SIZE
    except OSError:
        return False


def _expected_model_size(config: AppConfig) -> int | None:
    value = getattr(config, "model_size", None)
    try:
        return int(value) if value else None
    except (TypeError, ValueError):
        return None


def _model_sha256(config: AppConfig) -> str | None:
    value = getattr(config, "model_sha256", None)
    if not value:
        return None
    normalized = str(value).strip().casefold()
    return normalized if len(normalized) == 64 else None


def _verify_sha256(path: Path, expected: str, progress: Progress) -> None:
    digest = hashlib.sha256()
    total = max(path.stat().st_size, 1)
    processed = 0

    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8 * 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            processed += len(chunk)
            progress(
                int(processed * 100 / total),
                "Проверка контрольной суммы модели…",
            )

    actual = digest.hexdigest().casefold()
    if actual != expected:
        raise RuntimeError(
            "Контрольная сумма модели не совпадает. "
            "Файл мог быть повреждён при загрузке."
        )


def _human_size(value: int) -> str:
    return f"{value / 1_000_000_000:.2f} ГБ"


def download_model(config: AppConfig, progress: Progress) -> Path:
    destination = Path(config.model_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")

    if model_installed(config):
        progress(100, "Языковая модель уже установлена")
        return destination

    last_error: Exception | None = None

    for attempt in range(1, _DOWNLOAD_RETRIES + 1):
        try:
            existing = partial.stat().st_size if partial.exists() else 0
            headers: dict[str, str] = {}
            if existing:
                headers["Range"] = f"bytes={existing}-"

            progress(
                0,
                f"Подключение к серверу модели"
                + (f" (попытка {attempt}/{_DOWNLOAD_RETRIES})" if attempt > 1 else ""),
            )

            with requests.get(
                str(config.model_url),
                stream=True,
                timeout=(30, 180),
                headers=headers,
                allow_redirects=True,
            ) as response:
                if response.status_code == 416 and partial.exists():
                    partial.unlink(missing_ok=True)
                    continue

                response.raise_for_status()

                resumed = response.status_code == 206 and existing > 0
                mode = "ab" if resumed else "wb"
                downloaded = existing if resumed else 0

                content_length = int(response.headers.get("content-length", "0") or 0)
                total = downloaded + content_length if content_length else 0

                with partial.open(mode) as handle:
                    last_flush = time.monotonic()

                    for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_SIZE):
                        if not chunk:
                            continue

                        handle.write(chunk)
                        downloaded += len(chunk)

                        if time.monotonic() - last_flush >= 2:
                            handle.flush()
                            os.fsync(handle.fileno())
                            last_flush = time.monotonic()

                        percent = int(downloaded * 100 / total) if total else 0
                        message = f"Загрузка модели: {_human_size(downloaded)}"
                        if total:
                            message += f" из {_human_size(total)}"
                        progress(min(percent, 99), message)

                    handle.flush()
                    os.fsync(handle.fileno())

            actual_size = partial.stat().st_size
            expected_size = _expected_model_size(config)

            if actual_size < _MIN_MODEL_SIZE:
                raise RuntimeError(
                    f"Загруженный файл слишком мал: {_human_size(actual_size)}"
                )

            if expected_size and actual_size != expected_size:
                raise RuntimeError(
                    "Размер модели не совпадает с ожидаемым: "
                    f"{_human_size(actual_size)} вместо {_human_size(expected_size)}"
                )

            expected_hash = _model_sha256(config)
            if expected_hash:
                _verify_sha256(partial, expected_hash, progress)

            if destination.exists():
                destination.unlink()

            partial.replace(destination)
            progress(100, "Языковая модель установлена")
            return destination

        except Exception as exc:
            last_error = exc
            if attempt >= _DOWNLOAD_RETRIES:
                break

            wait_seconds = min(attempt * 3, 10)
            progress(
                0,
                f"Ошибка загрузки. Повтор через {wait_seconds} сек.: {exc}",
            )
            time.sleep(wait_seconds)

    assert last_error is not None
    raise RuntimeError(
        "Не удалось загрузить языковую модель. "
        "Проверьте интернет-соединение и свободное место на диске. "
        f"Причина: {last_error}"
    ) from last_error


def _port_is_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


class LocalModelServer:
    def __init__(self, config: AppConfig):
        self.config = config
        self.process: subprocess.Popen | None = None
        self._log_handle = None
        self._owns_process = False

    @property
    def log_path(self) -> Path:
        path = app_data_dir() / "logs" / "llama-server.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def is_ready(self) -> bool:
        try:
            response = requests.get(
                f"{str(self.config.server_url).rstrip('/')}/health",
                timeout=2,
            )
            return response.status_code == 200
        except requests.RequestException:
            return False

    def _base_args(self, executable: Path, gpu_layers: int) -> list[str]:
        threads = int(getattr(self.config, "threads", max((os.cpu_count() or 4) - 1, 1)))
        batch_size = int(getattr(self.config, "batch_size", 256))

        return [
            str(executable),
            "-m",
            str(self.config.model_path),
            "--host",
            str(self.config.server_host),
            "--port",
            str(self.config.server_port),
            "-c",
            str(self.config.context_size),
            "-ngl",
            str(gpu_layers),
            "--parallel",
            "1",
            "--threads",
            str(threads),
            "--batch-size",
            str(batch_size),
            # TranslateGemma ships a structured multimodal Jinja template
            # that older llama.cpp builds cannot parse.  Translation uses a
            # purpose-built text prompt with the stable Gemma chat template.
            "--no-jinja",
            "--chat-template",
            "gemma",
        ]

    def _start_process(self, args: list[str]) -> None:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

        self._log_handle = self.log_path.open("a", encoding="utf-8")
        self._log_handle.write(
            "\n\n=== Запуск llama-server "
            + time.strftime("%Y-%m-%d %H:%M:%S")
            + " ===\n"
        )
        self._log_handle.write("Команда: " + " ".join(args) + "\n")
        self._log_handle.flush()

        self.process = subprocess.Popen(
            args,
            stdout=self._log_handle,
            stderr=subprocess.STDOUT,
            creationflags=creationflags,
            cwd=str(app_data_dir()),
        )
        self._owns_process = True

    def _wait_until_ready(
        self,
        progress: Progress,
        timeout_seconds: int,
        stage_message: str,
    ) -> bool:
        started = time.monotonic()

        while time.monotonic() - started < timeout_seconds:
            if self.is_ready():
                return True

            if self.process and self.process.poll() is not None:
                return False

            elapsed = int(time.monotonic() - started)
            progress(
                min(99, int(elapsed * 100 / max(timeout_seconds, 1))),
                stage_message,
            )
            time.sleep(1)

        return False

    def _close_process_only(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass

        self.process = None
        self._owns_process = False

        if self._log_handle:
            self._log_handle.flush()
            self._log_handle.close()
            self._log_handle = None

    def start(self, progress: Progress) -> None:
        if self.is_ready():
            progress(100, "Локальный переводчик уже запущен")
            self._owns_process = False
            return

        runtimes = llama_server_candidates(self.config)
        if not runtimes:
            raise RuntimeError(
                "В сборке отсутствуют локальные движки Vulkan и CPU"
            )

        if not model_installed(self.config):
            raise RuntimeError("Языковая модель ещё не установлена")

        host = str(self.config.server_host)
        port = int(self.config.server_port)

        if _port_is_open(host, port) and not self.is_ready():
            raise RuntimeError(
                f"Порт {port} уже занят другой программой. "
                "Закройте её или измените порт локальной модели."
            )

        last_reason = ""

        for attempt, (runtime_label, executable, layers) in enumerate(runtimes, start=1):
            if layers > 0:
                message = f"Запуск модели через видеокарту: {layers} слоёв…"
            else:
                message = "Видеокарта не подошла. Запуск модели на процессоре…"
            progress(0, message)
            args = self._base_args(executable, layers)
            self._start_process(args)

            if self._wait_until_ready(
                progress,
                _SERVER_START_TIMEOUT,
                message,
            ):
                progress(100, "Локальный переводчик запущен")
                return

            exit_code = self.process.poll() if self.process else None
            last_reason = (
                f"процесс завершился с кодом {exit_code}"
                if exit_code is not None
                else "превышено время ожидания"
            )
            self._close_process_only()

            if attempt < len(runtimes):
                next_label = runtimes[attempt][0]
                progress(0, f"Вариант {runtime_label} не запустился. Пробуем {next_label}…")

        raise RuntimeError(
            "Не удалось запустить локальную модель: "
            f"{last_reason}. Подробности: {self.log_path}"
        )

    def stop(self) -> None:
        if not self._owns_process:
            return
        self._close_process_only()
