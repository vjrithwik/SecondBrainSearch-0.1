# PyQt6 main window and dark stylesheet.
"""PyQt6 main window and dark stylesheet."""

from __future__ import annotations

import logging
from contextlib import suppress
from pathlib import Path
from typing import Any

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from second_brain.config import DEFAULT_DB_PATH
from second_brain.controller import AppController
from second_brain.queues import TelemetryQueue
from second_brain.services.open_document import open_document_with_default_handler

logger = logging.getLogger(__name__)

DARK_STYLESHEET = """
/* Golden-ratio typography and spacing for readability. */
QMainWindow, QWidget {
    background-color: #1e1e1e;
    color: #e0e0e0;
    font-family: Segoe UI, sans-serif;
    font-size: 15px;
}
QLineEdit {
    background-color: #2d2d2d;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    padding: 10px 13px;
    min-height: 21px;
    color: #e0e0e0;
    font-size: 15px;
}
QPushButton {
    background-color: #0078d4;
    border: 1px solid #0078d4;
    border-radius: 4px;
    padding: 10px 18px;
    min-height: 21px;
    color: white;
    font-size: 15px;
    font-weight: 600;
}
QPushButton:disabled {
    background-color: #3c3c3c;
    border: 1px solid #555555;
    color: #a0a0a0;
}
QPushButton:hover:!disabled {
    background-color: #006cbe;
    border: 1px solid #006cbe;
}
QPushButton:pressed:!disabled {
    background-color: #005a9e;
    border: 1px solid #005a9e;
}
QComboBox {
    background-color: #2d2d2d;
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    padding: 9px 13px;
    min-height: 21px;
    color: #e0e0e0;
    font-size: 15px;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QComboBox QAbstractItemView {
    background-color: #2d2d2d;
    color: #e0e0e0;
    selection-background-color: #0078d4;
    border: 1px solid #3c3c3c;
}
QListWidget {
    background-color: #252526;
    border: 1px solid #3c3c3c;
    color: #e0e0e0;
}
QListWidget::item:selected {
    background-color: #0078d4;
}
QTableWidget {
    background-color: #252526;
    border: 1px solid #3c3c3c;
    color: #e0e0e0;
    gridline-color: #3c3c3c;
    font-size: 14px;
}
QTableWidget::item:selected {
    background-color: #0078d4;
    color: #ffffff;
    border: 1px solid #83beec;
}
QTableWidget::item {
    padding: 8px;
}
QTableWidget:focus {
    border: 1px solid #0078d4;
}
QHeaderView::section {
    background-color: #2d2d2d;
    color: #e0e0e0;
    padding: 10px 13px;
    border: 1px solid #3c3c3c;
    font-size: 14px;
    font-weight: 600;
}
QProgressBar {
    border: 1px solid #3c3c3c;
    border-radius: 4px;
    text-align: center;
    color: #e0e0e0;
    min-height: 21px;
    font-size: 13px;
}
QProgressBar::chunk {
    background-color: #0078d4;
    border-radius: 3px;
}
QLabel {
    color: #e0e0e0;
    font-size: 15px;
}
QLabel#overlay_title {
    font-size: 19px;
    font-weight: bold;
}
QMenuBar, QMenu {
    background-color: #2d2d2d;
    color: #e0e0e0;
    font-size: 14px;
}
QMenu::item:selected {
    background-color: #0078d4;
}
QToolTip {
    background-color: #2d2d2d;
    color: #e0e0e0;
    border: 1px solid #3c3c3c;
    padding: 6px 10px;
    font-size: 13px;
}
"""


class _IndexingThread(QThread):
    """Background thread for indexing runs."""

    progress = pyqtSignal(dict)
    finished_signal = pyqtSignal(object)
    error = pyqtSignal(str)
    run_started = pyqtSignal(str)

    def __init__(
        self,
        controller: AppController,
        directory_path: str,
        resume_run_id: str | None = None,
    ) -> None:
        super().__init__()
        self._controller = controller
        self._directory_path = directory_path
        self._resume_run_id = resume_run_id

    def run(self) -> None:
        try:
            # Indexing runs synchronously in the service, but the service emits
            # telemetry events as files are processed. Poll the queue and relay
            # progress to the UI so the progress bar can be determinate.
            summary = self._controller.start_indexing(
                self._directory_path,
                resume_run_id=self._resume_run_id,
                on_started=lambda run_id: self.run_started.emit(run_id),
            )
            self.finished_signal.emit(summary)
        except Exception as exc:  # noqa: BLE001 - thread boundary
            self.error.emit(str(exc))


class MainWindow(QMainWindow):
    """Primary application window."""

    def __init__(self, db_path: Path | None = None) -> None:
        super().__init__()
        self._db_path = db_path or DEFAULT_DB_PATH
        self._telemetry = TelemetryQueue()
        self._controller = AppController(
            db_path=self._db_path, telemetry=self._telemetry
        )
        self._indexing_thread: _IndexingThread | None = None

        self.setWindowTitle("SecondBrainSearch")
        self.setMinimumSize(1100, 750)
        self.setStyleSheet(DARK_STYLESHEET)

        self._build_menu()
        self._build_ui()
        self._refresh_scope_selector()
        self._refresh_status()

    def _build_menu(self) -> None:
        menu_bar = self.menuBar()
        file_menu = menu_bar.addMenu("Menu")

        select_action = file_menu.addAction("Select Directory...")
        select_action.triggered.connect(self._select_directory)

        file_menu.addSeparator()

        purge_menu = QMenu("Advanced", self)
        purge_action = purge_menu.addAction("Purge all Indices")
        purge_action.triggered.connect(self._purge_index)
        file_menu.addMenu(purge_menu)

        file_menu.addSeparator()
        quit_action = file_menu.addAction("Quit")
        quit_action.triggered.connect(self.close)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setSpacing(13)
        layout.setContentsMargins(21, 21, 21, 21)

        # Search bar
        search_layout = QHBoxLayout()
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("Search your documents...")
        self._search_input.returnPressed.connect(self._run_search)
        search_button = QPushButton("Search")
        search_button.clicked.connect(self._run_search)
        clear_button = QPushButton("Clear")
        clear_button.setToolTip("Clear search text and results")
        clear_button.clicked.connect(self._clear_search)
        search_layout.addWidget(self._search_input)
        search_layout.addWidget(search_button)
        search_layout.addWidget(clear_button)
        layout.addLayout(search_layout)

        # Scope selector
        scope_layout = QHBoxLayout()
        scope_label = QLabel("Existing indexes:")
        self._scope_selector = QComboBox()
        self._scope_selector.setToolTip(
            "Choose a named index to search, or search all indexes."
        )
        self._scope_selector.currentIndexChanged.connect(
            self._on_scope_changed
        )
        self._scope_purge_button = QPushButton("Purge index")
        self._scope_purge_button.setToolTip(
            "Purge the selected index"
        )
        self._scope_purge_button.clicked.connect(
            self._purge_selected_directory
        )
        self._scope_purge_button.setEnabled(False)
        scope_layout.addWidget(scope_label)
        scope_layout.addWidget(self._scope_selector, stretch=1)
        scope_layout.addWidget(self._scope_purge_button)
        layout.addLayout(scope_layout)

        # Results table
        # Indexing overlay panel (shown above the results table while indexing)
        self._indexing_overlay = self._build_indexing_overlay()
        layout.addWidget(self._indexing_overlay)

        self._results_table = QTableWidget()
        self._results_table.setColumnCount(5)
        self._results_table.setHorizontalHeaderLabels(
            ["S.No", "File name", "Semantic score", "Relevance", "Description"]
        )
        header = self._results_table.horizontalHeader()
        header.setSectionResizeMode(0, header.ResizeMode.Fixed)
        header.setSectionResizeMode(1, header.ResizeMode.Stretch)
        header.setSectionResizeMode(2, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, header.ResizeMode.ResizeToContents)
        header.resizeSection(0, 55)
        self._results_table.verticalHeader().setVisible(False)
        self._results_table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._results_table.setEditTriggers(
            QTableWidget.EditTrigger.NoEditTriggers
        )
        self._results_table.setSelectionMode(
            QTableWidget.SelectionMode.SingleSelection
        )
        self._results_table.doubleClicked.connect(self._open_selected_row)
        layout.addWidget(self._results_table)

        # Indexing controls
        indexing_layout = QHBoxLayout()
        self._index_button = QPushButton("Index Directory...")
        self._index_button.clicked.connect(self._select_directory)
        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(False)
        self._status_label = QLabel("Ready")
        indexing_layout.addWidget(self._index_button)
        indexing_layout.addWidget(self._progress_bar)
        indexing_layout.addWidget(self._status_label)
        layout.addLayout(indexing_layout)

    def _build_indexing_overlay(self) -> QWidget:
        """Build the overlay shown above results while indexing is active."""
        overlay = QWidget()
        overlay.setObjectName("indexing_overlay")
        overlay.setStyleSheet(
            "#indexing_overlay { background-color: #252526; border: 1px solid #3c3c3c; }"
        )
        overlay_layout = QVBoxLayout(overlay)
        overlay_layout.setSpacing(13)
        overlay_layout.setContentsMargins(21, 21, 21, 21)

        self._overlay_title = QLabel("Indexing in progress")
        self._overlay_title.setObjectName("overlay_title")
        overlay_layout.addWidget(self._overlay_title)

        self._overlay_current_file = QLabel("Current file: -")
        overlay_layout.addWidget(self._overlay_current_file)

        self._overlay_file_progress = QProgressBar()
        self._overlay_file_progress.setRange(0, 0)  # indeterminate per-file
        overlay_layout.addWidget(self._overlay_file_progress)

        stats_layout = QHBoxLayout()
        self._overlay_chunks = QLabel("Chunks: 0")
        self._overlay_embeddings = QLabel("Embeddings: 0")
        self._overlay_db = QLabel(f"DB: {DEFAULT_DB_PATH}")
        stats_layout.addWidget(self._overlay_chunks)
        stats_layout.addWidget(self._overlay_embeddings)
        stats_layout.addStretch()
        overlay_layout.addLayout(stats_layout)
        overlay_layout.addWidget(self._overlay_db)

        buttons_layout = QHBoxLayout()
        self._stop_button = QPushButton("Stop after current file")
        self._stop_button.setToolTip(
            "Finish indexing the current file, then stop and make the index searchable."
        )
        self._stop_button.clicked.connect(self._on_stop_indexing)
        self._cancel_button = QPushButton("Cancel and purge")
        self._cancel_button.setToolTip(
            "Stop immediately and delete all index data created so far."
        )
        self._cancel_button.clicked.connect(self._on_cancel_and_purge)
        buttons_layout.addWidget(self._stop_button)
        buttons_layout.addWidget(self._cancel_button)
        buttons_layout.addStretch()
        overlay_layout.addLayout(buttons_layout)

        overlay.setVisible(False)
        return overlay

    def _score_relevance(self, score: float) -> tuple[str, str, QColor]:
        """Return (relevance label, description, text color) for a score."""
        if score > 0.6:
            return (
                "Strong",
                "Strong semantic match, likely what you're looking for",
                QColor("#90EE90"),
            )
        if score >= 0.30:
            return (
                "Moderate",
                "Moderate relevance, worth checking",
                QColor("#FFD700"),
            )
        return (
            "Weak",
            "Weak match, results may be noise",
            QColor("#FF6B6B"),
        )

    def _add_result_row(
        self, file_name: str, score: float, file_path: str
    ) -> None:
        relevance, description, color = self._score_relevance(score)
        row = self._results_table.rowCount()
        self._results_table.insertRow(row)

        serial_item = QTableWidgetItem(str(row + 1))
        serial_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        name_item = QTableWidgetItem(file_name)
        score_item = QTableWidgetItem(f"{score:.3f}")
        rel_item = QTableWidgetItem(relevance)
        desc_item = QTableWidgetItem(description)

        for item in (serial_item, name_item, score_item, rel_item, desc_item):
            item.setForeground(color)
            item.setData(int(Qt.ItemDataRole.UserRole), file_path)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        self._results_table.setItem(row, 0, serial_item)
        self._results_table.setItem(row, 1, name_item)
        self._results_table.setItem(row, 2, score_item)
        self._results_table.setItem(row, 3, rel_item)
        self._results_table.setItem(row, 4, desc_item)

    def _on_scope_changed(self) -> None:
        """Re-run the current query when the user changes search scope."""
        self._update_scope_purge_button()
        if self._search_input.text().strip():
            self._run_search()

    def _get_selected_scope(self) -> str | None:
        """Return the selected directory scope path, or None for all indexes."""
        data = self._scope_selector.currentData()
        if not data or not isinstance(data, dict):
            return None
        return data.get("directory_path")

    def _refresh_scope_selector(self) -> None:
        """Populate the scope selector with named indexed directories."""
        current_scope = self._get_selected_scope()
        self._scope_selector.blockSignals(True)
        self._scope_selector.clear()
        self._scope_selector.addItem("All indexes", "")
        try:
            directories = self._controller.get_indexed_directories()
            for directory in directories:
                path = directory["directory_path"]
                name = directory.get("display_name") or Path(path).name
                count = directory["document_count"]
                label = f"{name} ({count} documents)"
                self._scope_selector.addItem(
                    label,
                    {
                        "directory_id": directory["directory_id"],
                        "directory_path": path,
                    },
                )
        except Exception:  # noqa: BLE001
            pass
        # Restore previous selection if it still exists.
        if current_scope:
            for index in range(self._scope_selector.count()):
                data = self._scope_selector.itemData(index)
                if (
                    isinstance(data, dict)
                    and data.get("directory_path") == current_scope
                ):
                    self._scope_selector.setCurrentIndex(index)
                    break
        self._scope_selector.blockSignals(False)
        self._on_scope_changed()
        self._update_scope_purge_button()

    def _update_scope_purge_button(self) -> None:
        """Enable the per-index purge button only when an index is selected."""
        data = self._scope_selector.currentData()
        self._scope_purge_button.setEnabled(isinstance(data, dict))

    def _run_search(self) -> None:
        query_text = self._search_input.text().strip()
        if not query_text:
            return
        try:
            page = self._controller.search(
                query_text, directory_scope=self._get_selected_scope()
            )
            self._results_table.setRowCount(0)
            self._results_table.setColumnCount(5)
            self._results_table.setHorizontalHeaderLabels(
                ["S.No", "File name", "Semantic score", "Relevance", "Description"]
            )
            if not page.results:
                self._results_table.setColumnCount(1)
                self._results_table.setHorizontalHeaderLabels([""])
                self._results_table.setRowCount(1)
                item = QTableWidgetItem("No results found")
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self._results_table.setItem(0, 0, item)
                return
            for result in page.results:
                self._add_result_row(
                    result.file_name, result.score, result.file_path
                )
        except Exception as exc:  # noqa: BLE001 - UI boundary
            QMessageBox.warning(self, "Search failed", str(exc))

    def _clear_search(self) -> None:
        """Clear the search input and results table."""
        self._search_input.clear()
        self._results_table.setRowCount(0)

    def _purge_selected_directory(self) -> None:
        """Purge the index selected in the scope dropdown after confirmation."""
        data = self._scope_selector.currentData()
        if not isinstance(data, dict):
            return
        directory_id = data["directory_id"]
        name = self._scope_selector.currentText().split(" (")[0]
        reply = QMessageBox.question(
            self,
            "Purge index?",
            "purging an index will require rebuilding it again for "
            "personalised index level semantic search, are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._controller.purge_directory(directory_id)
            self._refresh_scope_selector()
            self._refresh_status()
            self._results_table.setRowCount(0)
            self._status_label.setText(f"Index '{name}' purged")
        except Exception as exc:  # noqa: BLE001 - UI boundary
            QMessageBox.warning(self, "Purge failed", str(exc))

    def _open_selected_row(self) -> None:
        row = self._results_table.currentRow()
        if row < 0:
            return
        item = self._results_table.item(row, 0)
        if item is None:
            return
        file_path = item.data(int(Qt.ItemDataRole.UserRole))
        if not isinstance(file_path, str):
            return
        try:
            open_document_with_default_handler(file_path)
        except Exception as exc:  # noqa: BLE001 - UI boundary
            QMessageBox.warning(self, "Could not open file", str(exc))

    def _select_directory(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Select directory to index")
        if not path:
            return

        display_name = self._prompt_index_name(path)
        if display_name is None:
            return

        try:
            self._controller.select_directory(path, display_name=display_name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Invalid directory", str(exc))
            return

        resume = self._controller.get_resume_prompt(path)
        if resume is not None:
            reply = QMessageBox.question(
                self,
                "Resume indexing?",
                f"An unfinished indexing run was found for this directory\n"
                f"({resume.files_processed} files already processed).\n\n"
                f"Resume from where it left off?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Cancel:
                return
            if reply == QMessageBox.StandardButton.Yes:
                self._start_indexing(path, resume_run_id=resume.run_id)
                return

        self._start_indexing(path)

    def _prompt_index_name(self, directory_path: str) -> str | None:
        """Ask the user for a short (<=10 chars) name for the new index.

        Returns the validated name, or None if the user cancelled.
        """
        default = Path(directory_path).name[:10]
        while True:
            name, ok = QInputDialog.getText(
                self,
                "Name this index",
                "Enter a short name for this index (max 10 characters):",
                text=default,
            )
            if not ok:
                return None
            cleaned = name.strip()
            if not cleaned:
                QMessageBox.warning(
                    self, "Name required", "Please enter a name for the index."
                )
                continue
            if len(cleaned) > 10:
                QMessageBox.warning(
                    self,
                    "Name too long",
                    "Index names must be 10 characters or fewer.",
                )
                continue
            return cleaned

    def _start_indexing(
        self, directory_path: str, resume_run_id: str | None = None
    ) -> None:
        self._index_button.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._status_label.setText("Indexing...")

        self._indexing_overlay.setVisible(True)
        self._results_table.setVisible(False)
        self._active_run_id: str | None = None
        self._pending_purge_after_cancel = False
        self._overlay_title.setText("Indexing in progress")
        self._stop_button.setEnabled(False)
        self._cancel_button.setEnabled(False)
        self._reset_overlay_stats()

        self._indexing_thread = _IndexingThread(
            self._controller, directory_path, resume_run_id=resume_run_id
        )
        self._indexing_thread.progress.connect(self._on_indexing_progress)
        self._indexing_thread.finished_signal.connect(self._indexing_finished)
        self._indexing_thread.error.connect(self._indexing_error)
        self._indexing_thread.run_started.connect(self._on_indexing_started)
        self._indexing_thread.start()

        # Drain telemetry events from the controller's queue and update the UI.
        self._progress_timer = self.startTimer(200)

    def _reset_overlay_stats(self) -> None:
        self._overlay_current_file.setText("Current file: -")
        self._overlay_chunks.setText("Chunks: 0")
        self._overlay_embeddings.setText("Embeddings: 0")
        self._overlay_db.setText(f"DB: {DEFAULT_DB_PATH}")

    def _on_indexing_started(self, run_id: str) -> None:
        """Capture the run id as soon as the service creates the run."""
        self._active_run_id = run_id
        self._stop_button.setEnabled(True)
        self._cancel_button.setEnabled(True)

    def _on_indexing_progress(self, payload: dict[str, Any]) -> None:
        processed = payload.get("files_processed", 0)
        skipped = payload.get("files_skipped", 0)
        total = payload.get("total_files", 0)
        percent = payload.get("percent_complete", 0)
        current_file = payload.get("current_file", "")
        chunks = payload.get("chunks_count", 0)
        embeddings = payload.get("embeddings_count", 0)
        db_path = payload.get("db_path", str(DEFAULT_DB_PATH))

        self._progress_bar.setValue(percent)
        self._status_label.setText(
            f"Indexing... {processed}/{total} files "
            f"({skipped} skipped)"
        )

        if current_file:
            self._overlay_current_file.setText(f"Current file: {current_file}")
        self._overlay_chunks.setText(f"Chunks: {chunks}")
        self._overlay_embeddings.setText(f"Embeddings: {embeddings}")
        self._overlay_db.setText(f"DB: {db_path}")

    def _on_stop_indexing(self) -> None:
        """Ask the background run to stop after the current file."""
        if not self._active_run_id or not self._indexing_thread:
            return
        try:
            self._controller.request_stop_indexing(self._active_run_id)
            self._stop_button.setEnabled(False)
            self._cancel_button.setEnabled(False)
            self._overlay_title.setText("Stopping after current file...")
        except Exception as exc:  # noqa: BLE001 - UI boundary
            QMessageBox.warning(self, "Stop failed", str(exc))

    def _on_cancel_and_purge(self) -> None:
        """Cancel the run and purge the index after confirmation."""
        if not self._active_run_id or not self._indexing_thread:
            return
        reply = QMessageBox.question(
            self,
            "Cancel and purge?",
            "This will stop indexing immediately and delete all index data "
            "created so far. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self._controller.indexing_service.cancel_run(self._active_run_id)
        except Exception as exc:  # noqa: BLE001 - UI boundary
            QMessageBox.warning(self, "Cancel failed", str(exc))
            return

        self._pending_purge_after_cancel = True
        self._stop_button.setEnabled(False)
        self._cancel_button.setEnabled(False)
        self._overlay_title.setText("Cancelling and purging...")
        QTimer.singleShot(100, self._finalize_cancel_and_purge)

    def _finalize_cancel_and_purge(self) -> None:
        """Terminate the background thread and purge the index immediately."""
        thread = self._indexing_thread
        if thread is not None and thread.isRunning():
            thread.wait(1000)
            if thread.isRunning():
                thread.terminate()
                thread.wait(1000)
        self._active_run_id = None
        self._indexing_thread = None
        self._perform_purge()
        self._reset_ui_after_indexing()
        self._status_label.setText("Indexing cancelled and index purged")
        self._refresh_status()

    def _perform_purge(self) -> None:
        """Purge the index without asking for confirmation again."""
        try:
            result = self._controller.purge(confirmed=True)
            self._results_table.setRowCount(0)
            self._status_label.setText(
                f"Index purged at {result.deleted_at}"
            )
        except Exception as exc:  # noqa: BLE001 - UI boundary
            QMessageBox.warning(self, "Purge failed", str(exc))

    def timerEvent(self, event: Any) -> None:  # noqa: N802
        """Relay telemetry events from the background indexing run."""
        if event.timerId() != getattr(self, "_progress_timer", None):
            super().timerEvent(event)
            return
        while True:
            evt = self._telemetry.get(timeout=0)
            if evt is None:
                break
            if evt.event_type == "started":
                self._active_run_id = str(evt.payload.get("run_id", ""))
            elif evt.event_type == "progress":
                self._indexing_thread.progress.emit(evt.payload)
            elif evt.event_type == "failed":
                self._indexing_thread.error.emit(
                    str(evt.payload.get("error", "Indexing failed"))
                )
                break

    def _reset_ui_after_indexing(self) -> None:
        """Common cleanup for when indexing ends by any path."""
        if hasattr(self, "_progress_timer"):
            self.killTimer(self._progress_timer)
            del self._progress_timer
        self._index_button.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._indexing_overlay.setVisible(False)
        self._results_table.setVisible(True)
        self._active_run_id = None
        self._indexing_thread = None

    def _indexing_finished(self, summary: Any) -> None:
        # Early-exit if _finalize_cancel_and_purge already handled cleanup.
        if getattr(self, "_pending_purge_after_cancel", False):
            return
        self._reset_ui_after_indexing()

        if summary.status == "CANCELLED":
            self._status_label.setText(
                f"Indexing stopped ({summary.files_processed} files, "
                f"{summary.files_skipped} skipped)"
            )
        else:
            self._status_label.setText(
                f"Indexed {summary.files_processed} files, "
                f"skipped {summary.files_skipped}"
            )
        self._refresh_scope_selector()
        self._refresh_status()

    def _indexing_error(self, message: str) -> None:
        if getattr(self, "_pending_purge_after_cancel", False):
            return
        self._reset_ui_after_indexing()
        self._pending_purge_after_cancel = False
        self._status_label.setText("Indexing failed")
        QMessageBox.warning(self, "Indexing failed", message)

    def _purge_index(self) -> None:
        reply = QMessageBox.question(
            self,
            "Purge index?",
            "This will permanently delete the local search index. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # If indexing is active, cancel and terminate it first so the purge
        # does not race against the background worker.
        if self._active_run_id and self._indexing_thread is not None:
            with suppress(Exception):
                self._controller.indexing_service.cancel_run(
                    self._active_run_id
                )
            thread = self._indexing_thread
            if thread.isRunning():
                thread.wait(1000)
                if thread.isRunning():
                    thread.terminate()
                    thread.wait(1000)
            self._indexing_thread = None
            self._active_run_id = None
            if hasattr(self, "_progress_timer"):
                self.killTimer(self._progress_timer)
                del self._progress_timer

        try:
            result = self._controller.purge(confirmed=True)
            self._results_table.setRowCount(0)
            self._status_label.setText(
                f"Index purged at {result.deleted_at}"
            )
        except Exception as exc:  # noqa: BLE001 - UI boundary
            QMessageBox.warning(self, "Purge failed", str(exc))
        self._refresh_scope_selector()

    def _refresh_status(self) -> None:
        try:
            status = self._controller.get_status()
            reason = "Ready" if status["status"] == "ACTIVE" else status["status"]
            self._status_label.setText(
                f"{reason} | {status['document_count']} documents"
            )
        except Exception:  # noqa: BLE001
            self._status_label.setText("No index")

    def closeEvent(self, event: Any) -> None:  # noqa: N802
        self._controller.close()
        event.accept()
