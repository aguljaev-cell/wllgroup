from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from config import AppConfig
from model_runtime import LocalModelServer, download_model, model_installed
from processors import translate_docx, translate_pdf


class SetupWorker(QObject):
    progress = Signal(int, str)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config

    @Slot()
    def run(self) -> None:
        try:
            if not model_installed(self.config):
                download_model(self.config, lambda value, message: self.progress.emit(value, message))
            self.finished.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


class TranslationWorker(QObject):
    progress = Signal(int, str)
    finished = Signal(str, str)
    failed = Signal(str)

    def __init__(self, source: Path, destination: Path, config: AppConfig):
        super().__init__()
        self.source = source
        self.destination = destination
        self.config = config
        self.server = LocalModelServer(config)

    @Slot()
    def run(self) -> None:
        try:
            self.server.start(lambda value, message: self.progress.emit(min(value, 10), message))

            def mapped(value: int, message: str) -> None:
                self.progress.emit(10 + int(value * 0.9), message)

            suffix = self.source.suffix.lower()
            if suffix == ".pdf":
                report = translate_pdf(self.source, self.destination, self.config, mapped)
            elif suffix == ".docx":
                report = translate_docx(self.source, self.destination, self.config, mapped)
            else:
                raise ValueError("Поддерживаются только PDF и DOCX")

            self.finished.emit(str(self.destination), str(report))
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.server.stop()
