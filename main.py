from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QUrl
from PySide6.QtGui import QCloseEvent, QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from config import APP_VERSION, AppConfig
from model_runtime import model_installed
from worker import SetupWorker, TranslationWorker


APP_STYLE = """
QMainWindow {
    background: #f3f6fb;
}
QFrame#card {
    background: white;
    border: 1px solid #e5e9f2;
    border-radius: 16px;
}
QLabel#title {
    font-size: 28px;
    font-weight: 700;
    color: #15223b;
}
QLabel#subtitle {
    font-size: 13px;
    color: #667085;
}
QLabel#version {
    font-size: 11px;
    color: #98a2b3;
}
QLabel#runtimeReady {
    color: #067647;
    font-weight: 600;
}
QLabel#runtimeMissing {
    color: #b54708;
    font-weight: 600;
}
QPushButton {
    background: #2457d6;
    color: white;
    border: none;
    border-radius: 9px;
    padding: 11px 17px;
    font-weight: 600;
}
QPushButton:hover {
    background: #1948bd;
}
QPushButton:pressed {
    background: #123b9f;
}
QPushButton:disabled {
    background: #98a2b3;
    color: #f2f4f7;
}
QPushButton#secondary {
    background: #eef3ff;
    color: #2457d6;
    border: 1px solid #cdd9fb;
}
QPushButton#secondary:hover {
    background: #dfe8ff;
}
QPushButton#danger {
    background: #d92d20;
}
QPushButton#danger:hover {
    background: #b42318;
}
QLineEdit, QTextEdit {
    background: white;
    border: 1px solid #d0d5dd;
    border-radius: 8px;
    padding: 9px;
}
QLineEdit:focus, QTextEdit:focus {
    border: 1px solid #2457d6;
}
QProgressBar {
    border: 1px solid #d0d5dd;
    border-radius: 7px;
    text-align: center;
    background: white;
    min-height: 20px;
}
QProgressBar::chunk {
    background: #2457d6;
    border-radius: 6px;
}
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PDFMathTranslate WLL")
        self.resize(1040, 760)
        self.setAcceptDrops(True)

        self.config = AppConfig()
        self.source: Path | None = None
        self.thread: QThread | None = None
        self.worker: SetupWorker | TranslationWorker | None = None
        self.last_output: Path | None = None
        self.last_report: Path | None = None
        self._active_operation = ""

        self._build_ui()
        self._update_state()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(16)

        header = QHBoxLayout()
        text_box = QVBoxLayout()

        title = QLabel("PDFMathTranslate WLL")
        title.setObjectName("title")

        subtitle = QLabel(
            "Технический перевод PDF и DOCX на русский язык "
            "с сохранением структуры"
        )
        subtitle.setObjectName("subtitle")

        text_box.addWidget(title)
        text_box.addWidget(subtitle)

        header.addLayout(text_box)
        header.addStretch(1)

        version = QLabel(f"Версия {APP_VERSION}")
        version.setObjectName("version")
        header.addWidget(version, alignment=Qt.AlignmentFlag.AlignTop)

        layout.addLayout(header)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(22, 22, 22, 22)
        card_layout.setSpacing(14)

        self.runtime_status = QLabel()
        card_layout.addWidget(self.runtime_status)

        self.install_btn = QPushButton("Установить языковую модель")
        self.install_btn.clicked.connect(self.install_model)
        card_layout.addWidget(self.install_btn)

        row = QHBoxLayout()

        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        self.file_edit.setPlaceholderText(
            "Выберите PDF или DOCX либо перетащите файл в окно"
        )

        self.choose_btn = QPushButton("Выбрать файл")
        self.choose_btn.clicked.connect(self.choose_file)

        row.addWidget(self.file_edit, 1)
        row.addWidget(self.choose_btn)
        card_layout.addLayout(row)

        action_row = QHBoxLayout()

        self.start_btn = QPushButton("Перевести и сохранить")
        self.start_btn.clicked.connect(self.start_translation)

        self.cancel_btn = QPushButton("Отменить")
        self.cancel_btn.setObjectName("danger")
        self.cancel_btn.clicked.connect(self.cancel_operation)
        self.cancel_btn.setVisible(False)

        action_row.addWidget(self.start_btn, 1)
        action_row.addWidget(self.cancel_btn)

        card_layout.addLayout(action_row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        card_layout.addWidget(self.progress)

        self.status = QLabel("Готово к работе")
        card_layout.addWidget(self.status)

        result_row = QHBoxLayout()

        self.open_output_btn = QPushButton("Открыть результат")
        self.open_output_btn.setObjectName("secondary")
        self.open_output_btn.clicked.connect(self.open_output)

        self.open_report_btn = QPushButton("Открыть QA-отчёт")
        self.open_report_btn.setObjectName("secondary")
        self.open_report_btn.clicked.connect(self.open_report)

        self.open_folder_btn = QPushButton("Открыть папку")
        self.open_folder_btn.setObjectName("secondary")
        self.open_folder_btn.clicked.connect(self.open_result_folder)

        result_row.addWidget(self.open_output_btn)
        result_row.addWidget(self.open_report_btn)
        result_row.addWidget(self.open_folder_btn)
        result_row.addStretch(1)

        card_layout.addLayout(result_row)
        layout.addWidget(card)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Журнал работы")
        layout.addWidget(self.log, 1)

        self.setCentralWidget(root)

    def _is_busy(self) -> bool:
        return self.thread is not None

    def _append_log(self, message: str) -> None:
        if not message:
            return
        self.log.append(message)
        scrollbar = self.log.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _update_state(self) -> None:
        ready = model_installed(self.config)
        busy = self._is_busy()

        if ready:
            self.runtime_status.setText("✓ Языковая модель установлена")
            self.runtime_status.setObjectName("runtimeReady")
        else:
            self.runtime_status.setText(
                "Для первого запуска требуется загрузка языковой модели (~4,7 ГБ)"
            )
            self.runtime_status.setObjectName("runtimeMissing")

        self.runtime_status.style().unpolish(self.runtime_status)
        self.runtime_status.style().polish(self.runtime_status)

        self.install_btn.setVisible(not ready)
        self.install_btn.setEnabled(not busy)

        self.choose_btn.setEnabled(not busy)
        self.start_btn.setEnabled(
            ready and not busy and self.source is not None
        )
        self.cancel_btn.setVisible(busy)
        self.cancel_btn.setEnabled(busy)

        output_exists = (
            self.last_output is not None and self.last_output.exists()
        )
        report_exists = (
            self.last_report is not None and self.last_report.exists()
        )

        self.open_output_btn.setEnabled(output_exists)
        self.open_report_btn.setEnabled(report_exists)
        self.open_folder_btn.setEnabled(output_exists or report_exists)

    def _set_source(self, path: Path) -> None:
        if path.suffix.casefold() not in {".pdf", ".docx"}:
            QMessageBox.warning(
                self,
                "Неподдерживаемый формат",
                "Поддерживаются только файлы PDF и DOCX.",
            )
            return

        if not path.exists() or not path.is_file():
            QMessageBox.warning(
                self,
                "Файл не найден",
                f"Не удалось открыть файл:\n{path}",
            )
            return

        self.source = path
        self.file_edit.setText(str(path))
        self.status.setText(f"Выбран файл: {path.name}")
        self._append_log(f"Выбран исходный файл: {path}")
        self._update_state()

    def choose_file(self) -> None:
        name, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите документ",
            "",
            "Документы (*.pdf *.docx)",
        )
        if name:
            self._set_source(Path(name))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._is_busy():
            event.ignore()
            return

        urls = event.mimeData().urls()
        if len(urls) == 1:
            path = Path(urls[0].toLocalFile())
            if path.suffix.casefold() in {".pdf", ".docx"}:
                event.acceptProposedAction()
                return

        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if len(urls) == 1:
            self._set_source(Path(urls[0].toLocalFile()))
            event.acceptProposedAction()
        else:
            event.ignore()

    def install_model(self) -> None:
        if self._is_busy():
            return

        answer = QMessageBox.question(
            self,
            "Загрузка модели",
            "Будет загружено около 4,7 ГБ. После установки перевод "
            "будет работать локально.\n\nПродолжить?",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._run_worker(
                SetupWorker(self.config),
                "Установка языковой модели…",
                setup=True,
            )

    def start_translation(self) -> None:
        if self._is_busy():
            return

        if not self.source:
            QMessageBox.warning(
                self,
                "Нет файла",
                "Сначала выберите PDF или DOCX.",
            )
            return

        suffix = self.source.suffix.casefold()
        suggested = self.source.with_name(f"{self.source.stem}_RU{suffix}")

        name, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить перевод",
            str(suggested),
            "Документы (*.pdf *.docx)",
        )
        if not name:
            return

        destination = Path(name)
        if destination.suffix.casefold() != suffix:
            destination = destination.with_suffix(suffix)

        if destination.resolve() == self.source.resolve():
            QMessageBox.warning(
                self,
                "Неверный путь",
                "Нельзя сохранять перевод поверх исходного файла.",
            )
            return

        self.last_output = None
        self.last_report = None

        self._run_worker(
            TranslationWorker(
                self.source,
                destination,
                self.config,
            ),
            "Перевод выполняется…",
            setup=False,
        )

    def _run_worker(
        self,
        worker: SetupWorker | TranslationWorker,
        message: str,
        *,
        setup: bool,
    ) -> None:
        if self._is_busy():
            return

        self.thread = QThread(self)
        self.worker = worker
        self._active_operation = "setup" if setup else "translation"

        worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run)

        worker.progress.connect(self.on_progress)
        worker.failed.connect(self.on_failed)
        worker.failed.connect(self.thread.quit)

        if setup:
            worker.finished.connect(self.on_setup_finished)
        else:
            worker.finished.connect(self.on_finished)

        worker.finished.connect(self.thread.quit)
        self.thread.finished.connect(self.cleanup)

        self.progress.setValue(0)
        self.log.clear()
        self.status.setText(message)
        self._append_log(message)
        self._update_state()

        self.thread.start()

    def cancel_operation(self) -> None:
        if not self.worker:
            return

        answer = QMessageBox.question(
            self,
            "Отмена операции",
            "Прервать текущую операцию?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self.status.setText("Отмена операции…")
        self._append_log("Запрошена отмена операции.")

        try:
            self.worker.cancel()
        except Exception as exc:
            self._append_log(f"Не удалось передать команду отмены: {exc}")

        self.cancel_btn.setEnabled(False)

    def on_progress(self, value: int, message: str) -> None:
        self.progress.setValue(max(0, min(100, value)))
        self.status.setText(message)

        last_line = self.log.toPlainText().splitlines()
        if not last_line or last_line[-1] != message:
            self._append_log(message)

    def on_setup_finished(self) -> None:
        self.status.setText("Модель установлена")
        self.progress.setValue(100)
        self._append_log("Языковая модель установлена и готова к работе.")

        QMessageBox.information(
            self,
            "Готово",
            "Компоненты перевода установлены.",
        )

    def on_finished(self, output: str, report: str) -> None:
        self.last_output = Path(output)
        self.last_report = Path(report)

        self.status.setText("Перевод завершён")
        self.progress.setValue(100)

        self._append_log(f"Результат: {output}")
        self._append_log(f"QA-отчёт: {report}")

        QMessageBox.information(
            self,
            "Готово",
            f"Файл сохранён:\n{output}\n\n"
            f"Отчёт проверки:\n{report}",
        )

    def on_failed(self, message: str) -> None:
        self.status.setText("Ошибка")
        self._append_log("ОШИБКА:")
        self._append_log(message)

        QMessageBox.critical(
            self,
            "Ошибка",
            message,
        )

    def open_output(self) -> None:
        if self.last_output and self.last_output.exists():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self.last_output))
            )

    def open_report(self) -> None:
        if self.last_report and self.last_report.exists():
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(self.last_report))
            )

    def open_result_folder(self) -> None:
        target: Path | None = None

        if self.last_output and self.last_output.exists():
            target = self.last_output.parent
        elif self.last_report and self.last_report.exists():
            target = self.last_report.parent

        if target:
            QDesktopServices.openUrl(
                QUrl.fromLocalFile(str(target))
            )

    def cleanup(self) -> None:
        if self.worker:
            self.worker.deleteLater()
        if self.thread:
            self.thread.deleteLater()

        self.worker = None
        self.thread = None
        self._active_operation = ""
        self._update_state()

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._is_busy():
            event.accept()
            return

        answer = QMessageBox.question(
            self,
            "Операция выполняется",
            "Сейчас выполняется операция. Отменить её и закрыть программу?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            event.ignore()
            return

        if self.worker:
            try:
                self.worker.cancel()
            except Exception:
                pass

        event.ignore()
        self.status.setText(
            "Отмена операции. Закройте программу после завершения остановки."
        )


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("PDFMathTranslate WLL")
    app.setOrganizationName("WorldLogicLine")
    app.setStyleSheet(APP_STYLE)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())
