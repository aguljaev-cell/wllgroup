from __future__ import annotations

import traceback
from pathlib import Path
from threading import Event
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from config import AppConfig
from model_runtime import LocalModelServer, download_model, model_installed
from processors import translate_docx, translate_pdf


ProgressCallback = Callable[[float, str], None]


def _friendly_error(exc: Exception, context: str) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    lower = message.casefold()

    if "connection" in lower or "подключ" in lower:
        hint = "Не удалось подключиться к локальной языковой модели."
    elif "timeout" in lower or "timed out" in lower:
        hint = "Языковая модель не ответила за отведённое время."
    elif "memory" in lower or "out of memory" in lower:
        hint = "Недостаточно оперативной памяти для запуска модели или обработки файла."
    elif "permission" in lower or "access is denied" in lower or "отказано в доступе" in lower:
        hint = "Нет доступа к файлу или папке назначения."
    elif "pdf" in lower and "corrupt" in lower:
        hint = "PDF-файл повреждён или имеет неподдерживаемую структуру."
    elif "cancel" in lower or "отмен" in lower:
        hint = "Операция отменена пользователем."
    else:
        hint = context

    return f"{hint}\n\nТехнические сведения: {message}"


class _ProgressState:
    def __init__(self, emit: ProgressCallback):
        self._emit = emit
        self._last = -1

    def send(self, value: float, message: str) -> None:
        normalized = max(0.0, min(100.0, float(value)))
        if normalized < self._last:
            normalized = self._last
        self._last = normalized
        self._emit(normalized, message)


class SetupWorker(QObject):
    progress = Signal(float, str)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self._cancelled = Event()

    @Slot()
    def cancel(self) -> None:
        self._cancelled.set()

    @Slot()
    def run(self) -> None:
        state = _ProgressState(lambda value, message: self.progress.emit(value, message))

        try:
            if self._cancelled.is_set():
                raise RuntimeError("Установка модели отменена пользователем")

            if not model_installed(self.config):
                state.send(0, "Подготовка к загрузке языковой модели")

                def mapped(value: int, message: str) -> None:
                    if self._cancelled.is_set():
                        raise RuntimeError("Установка модели отменена пользователем")
                    state.send(value, message)

                download_model(self.config, mapped)

            if self._cancelled.is_set():
                raise RuntimeError("Установка модели отменена пользователем")

            state.send(100, "Языковая модель готова")
            self.finished.emit()

        except Exception as exc:
            self.failed.emit(
                _friendly_error(exc, "Не удалось установить языковую модель.")
            )


class TranslationWorker(QObject):
    progress = Signal(float, str)
    finished = Signal(str, str)
    failed = Signal(str)

    def __init__(
        self,
        source: Path,
        destination: Path,
        config: AppConfig,
        *,
        page_start: int | None = None,
        page_end: int | None = None,
    ):
        super().__init__()
        self.source = Path(source)
        self.destination = Path(destination)
        self.config = config
        self.page_start = page_start
        self.page_end = page_end
        self.server = LocalModelServer(config)
        self._cancelled = Event()
        self._server_started = False

    @Slot()
    def cancel(self) -> None:
        self._cancelled.set()

    def _check_cancelled(self) -> None:
        if self._cancelled.is_set():
            raise RuntimeError("Перевод отменён пользователем")

    def _validate_paths(self) -> None:
        if not self.source.exists():
            raise FileNotFoundError(f"Исходный файл не найден: {self.source}")
        if not self.source.is_file():
            raise ValueError(f"Указанный путь не является файлом: {self.source}")
        if self.source.resolve() == self.destination.resolve():
            raise ValueError("Исходный файл и файл результата не должны совпадать")

        self.destination.parent.mkdir(parents=True, exist_ok=True)

    @Slot()
    def run(self) -> None:
        state = _ProgressState(lambda value, message: self.progress.emit(value, message))

        try:
            self._validate_paths()
            self._check_cancelled()

            state.send(0, "Запуск локальной языковой модели")

            def server_progress(value: int, message: str) -> None:
                self._check_cancelled()
                state.send(min(10, max(0, int(value))), message)

            self.server.start(server_progress)
            self._server_started = True

            self._check_cancelled()
            state.send(10, "Языковая модель запущена")

            def mapped(value: int, message: str) -> None:
                self._check_cancelled()
                state.send(10.0 + max(0.0, min(100.0, float(value))) * 0.89, message)

            suffix = self.source.suffix.casefold()

            if suffix == ".pdf":
                report = translate_pdf(
                    self.source,
                    self.destination,
                    self.config,
                    mapped,
                    page_start=self.page_start,
                    page_end=self.page_end,
                )
            elif suffix == ".docx":
                report = translate_docx(
                    self.source,
                    self.destination,
                    self.config,
                    mapped,
                )
            else:
                raise ValueError(
                    f"Неподдерживаемый формат {suffix or 'без расширения'}. "
                    "Поддерживаются только PDF и DOCX."
                )

            self._check_cancelled()

            if not self.destination.exists():
                raise RuntimeError(
                    "Обработка завершилась без ошибки, но итоговый файл не был создан"
                )
            if not Path(report).exists():
                raise RuntimeError(
                    "Итоговый файл создан, но QA-отчёт отсутствует"
                )

            state.send(100, "Перевод завершён")
            self.finished.emit(str(self.destination), str(report))

        except Exception as exc:
            # Полный traceback оставляем в stderr для журнала PyInstaller / GitHub,
            # пользователю показываем понятное сообщение.
            traceback.print_exc()
            self.failed.emit(
                _friendly_error(exc, "Не удалось выполнить перевод файла.")
            )

        finally:
            if self._server_started:
                try:
                    self.server.stop()
                except Exception:
                    traceback.print_exc()
                finally:
                    self._server_started = False
