from __future__ import annotations

import sys
from pathlib import Path
from PySide6.QtCore import QThread
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QProgressBar, QTextEdit, QMessageBox, QFrame,
    QLineEdit
)

from .config import AppConfig
from .model_runtime import model_installed
from .worker import SetupWorker, TranslationWorker

APP_STYLE = """
QMainWindow { background: #f3f6fb; }
QFrame#card { background: white; border: 1px solid #e5e9f2; border-radius: 16px; }
QLabel#title { font-size: 28px; font-weight: 700; color: #15223b; }
QLabel#subtitle { font-size: 13px; color: #667085; }
QPushButton { background: #2457d6; color: white; border: none; border-radius: 9px; padding: 11px 17px; font-weight: 600; }
QPushButton:hover { background: #1948bd; }
QPushButton:disabled { background: #98a2b3; }
QLineEdit, QTextEdit { background: white; border: 1px solid #d0d5dd; border-radius: 8px; padding: 9px; }
QProgressBar { border: 1px solid #d0d5dd; border-radius: 7px; text-align: center; background: white; }
QProgressBar::chunk { background: #2457d6; border-radius: 6px; }
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PDFMathTranslate WLL")
        self.resize(920, 650)
        self.config = AppConfig()
        self.source: Path | None = None
        self.thread: QThread | None = None
        self.worker = None
        self._build_ui()
        self._update_state()

    def _build_ui(self) -> None:
        root = QWidget(); layout = QVBoxLayout(root)
        layout.setContentsMargins(30, 26, 30, 26); layout.setSpacing(16)
        title = QLabel("PDFMathTranslate WLL"); title.setObjectName("title")
        subtitle = QLabel("Технический перевод PDF и DOCX на русский язык с сохранением структуры")
        subtitle.setObjectName("subtitle")
        layout.addWidget(title); layout.addWidget(subtitle)

        card = QFrame(); card.setObjectName("card")
        card_layout = QVBoxLayout(card); card_layout.setContentsMargins(22,22,22,22); card_layout.setSpacing(14)
        self.runtime_status = QLabel()
        card_layout.addWidget(self.runtime_status)
        self.install_btn = QPushButton("Установить языковую модель")
        self.install_btn.clicked.connect(self.install_model)
        card_layout.addWidget(self.install_btn)
        row = QHBoxLayout()
        self.file_edit = QLineEdit(); self.file_edit.setReadOnly(True); self.file_edit.setPlaceholderText("Выберите PDF или DOCX")
        choose = QPushButton("Выбрать файл"); choose.clicked.connect(self.choose_file)
        row.addWidget(self.file_edit,1); row.addWidget(choose)
        card_layout.addLayout(row)
        self.start_btn = QPushButton("Перевести и сохранить"); self.start_btn.clicked.connect(self.start_translation)
        card_layout.addWidget(self.start_btn)
        self.progress = QProgressBar(); card_layout.addWidget(self.progress)
        self.status = QLabel("Готово к работе"); card_layout.addWidget(self.status)
        layout.addWidget(card)
        self.log = QTextEdit(); self.log.setReadOnly(True); self.log.setPlaceholderText("Журнал работы")
        layout.addWidget(self.log,1)
        self.setCentralWidget(root)

    def _update_state(self) -> None:
        ready = model_installed(self.config)
        self.runtime_status.setText("✓ Языковая модель установлена" if ready else "Для первого запуска требуется загрузка языковой модели (~4,7 ГБ)")
        self.install_btn.setVisible(not ready)
        self.start_btn.setEnabled(ready and self.thread is None)

    def choose_file(self) -> None:
        name, _ = QFileDialog.getOpenFileName(self, "Выберите документ", "", "Документы (*.pdf *.docx)")
        if name:
            self.source = Path(name); self.file_edit.setText(name)

    def install_model(self) -> None:
        self._run_worker(SetupWorker(self.config), "Установка языковой модели…", setup=True)

    def start_translation(self) -> None:
        if not self.source:
            QMessageBox.warning(self, "Нет файла", "Сначала выберите PDF или DOCX."); return
        suffix = self.source.suffix.lower(); suggested = self.source.with_name(f"{self.source.stem}_RU{suffix}")
        name, _ = QFileDialog.getSaveFileName(self, "Сохранить перевод", str(suggested), "Документы (*.pdf *.docx)")
        if name:
            self._run_worker(TranslationWorker(self.source, Path(name), self.config), "Перевод выполняется…", setup=False)

    def _run_worker(self, worker, message: str, setup: bool) -> None:
        self.thread = QThread(self); self.worker = worker; worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run); worker.progress.connect(self.on_progress)
        worker.failed.connect(self.on_failed); worker.failed.connect(self.thread.quit)
        if setup:
            worker.finished.connect(self.on_setup_finished)
        else:
            worker.finished.connect(self.on_finished)
        worker.finished.connect(self.thread.quit); self.thread.finished.connect(self.cleanup)
        self.progress.setValue(0); self.log.clear(); self.status.setText(message); self.start_btn.setEnabled(False); self.install_btn.setEnabled(False)
        self.thread.start()

    def on_progress(self, value: int, message: str) -> None:
        self.progress.setValue(max(0,min(100,value))); self.status.setText(message); self.log.append(message)

    def on_setup_finished(self) -> None:
        self.status.setText("Модель установлена"); self.progress.setValue(100); QMessageBox.information(self,"Готово","Компоненты перевода установлены.")

    def on_finished(self, output: str) -> None:
        self.status.setText("Перевод завершён"); self.progress.setValue(100); QMessageBox.information(self,"Готово",f"Файл сохранён:\n{output}")

    def on_failed(self, message: str) -> None:
        self.status.setText("Ошибка"); self.log.append("ОШИБКА: " + message); QMessageBox.critical(self,"Ошибка",message)

    def cleanup(self) -> None:
        if self.worker: self.worker.deleteLater()
        if self.thread: self.thread.deleteLater()
        self.worker = None; self.thread = None; self.install_btn.setEnabled(True); self._update_state()


def main() -> None:
    app = QApplication(sys.argv); app.setStyleSheet(APP_STYLE)
    window = MainWindow(); window.show(); sys.exit(app.exec())
