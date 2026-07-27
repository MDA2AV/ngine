"""The operator station window."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from .. import __version__
from ..engine import REGISTRY, Context, RunOptions, RunThread, Sequencer, validate
from ..engine.loaders import load
from ..engine.program import Program
from . import theme
from .bridge import QtBridge
from .widgets import Card, FieldRow, LogView, StatusBanner, UutGrid

MAX_UUTS = 4


class MainWindow(QMainWindow):
    def __init__(self, program_path: str | None = None, simulate: bool = False,
                 dark: bool = True, station: str = "", operator: str = "",
                 debug_dir: str | None = None,
                 telemetry_port: int | None = None) -> None:
        super().__init__()
        self.setWindowTitle(f"NGWART {__version__} — Functional Test")
        self.resize(1500, 900)
        self.setMinimumSize(1024, 680)

        self.program: Program | None = None
        self.thread: RunThread | None = None
        self.sequencer: Sequencer | None = None
        self.dark = dark
        self.station = station
        self.operator = operator
        self.debug_dir = debug_dir
        self._last_record = None

        # Owned by the window, not by a run: a dashboard stays connected while
        # the operator swaps boards.
        self.telemetry = None
        if telemetry_port:
            from ..engine.telemetry import TelemetryServer
            try:
                self.telemetry = TelemetryServer(port=int(telemetry_port)).start()
            except OSError as exc:
                print(f"telemetry disabled: {exc}")

        self.bridge = QtBridge()
        self._connect_bridge()

        self._build_ui()
        self._apply_theme()

        # Keeps the elapsed display moving between engine ticks.
        self._clock = QTimer(self)
        self._clock.setInterval(250)
        self._clock.timeout.connect(self._tick_clock)

        self.simulate_box.setChecked(simulate)
        self.debug_box.setChecked(bool(debug_dir))
        if program_path:
            self.open_program(program_path)

    # -- construction -----------------------------------------------------

    def _build_ui(self) -> None:
        self._build_toolbar()

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        layout.addWidget(self._build_header())
        self.banner = StatusBanner()
        layout.addWidget(self.banner)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_operator_tab(), "Operator")
        self.tabs.addTab(self._build_program_tab(), "Program")
        self.tabs.addTab(self._build_verbs_tab(), "Verbs")
        layout.addWidget(self.tabs, 1)

        layout.addWidget(self._build_footer())
        self.setCentralWidget(root)
        if self.telemetry is not None:
            self.statusBar().showMessage(
                f"Telemetry live on http://localhost:{self.telemetry.bound_port}")
        else:
            self.statusBar().showMessage("No program loaded.")

    def _build_toolbar(self) -> None:
        bar = self.addToolBar("Main")
        bar.setMovable(False)

        open_action = QAction("Open program…", self)
        open_action.setShortcut(QKeySequence.Open)
        open_action.triggered.connect(self._choose_program)
        bar.addAction(open_action)

        reload_action = QAction("Reload", self)
        reload_action.setShortcut("F5")
        reload_action.triggered.connect(self._reload_program)
        bar.addAction(reload_action)

        bar.addSeparator()
        self.debug_box = QCheckBox("Debug bundle")
        self.debug_box.setToolTip(
            "Write captures, binary images, contour overlays, the data store and "
            "the full log to ./debug. Turn on when a test fails unexpectedly.")

        self.simulate_box = QCheckBox("Simulate hardware")
        self.simulate_box.setToolTip(
            "Run against simulated instruments. Reports produced in this mode "
            "are tagged, so they cannot be mistaken for a real run.")
        bar.addWidget(self.simulate_box)
        bar.addWidget(self.debug_box)

        bar.addSeparator()
        theme_action = QAction("Toggle theme", self)
        theme_action.triggered.connect(self._toggle_theme)
        bar.addAction(theme_action)

        save_action = QAction("Save report…", self)
        save_action.triggered.connect(self._save_report)
        bar.addAction(save_action)

    def _build_header(self) -> QWidget:
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(26)
        self.field_program = FieldRow("program", "—")
        self.field_barcode1 = FieldRow("barcode 1")
        self.field_barcode2 = FieldRow("barcode 2")
        self.field_worker = FieldRow("worker")
        self.field_elapsed = FieldRow("elapsed", "0.0 s")
        self.field_station = FieldRow("station", self.station or "—")
        for field in (self.field_program, self.field_barcode1, self.field_barcode2,
                      self.field_worker, self.field_elapsed, self.field_station):
            row.addWidget(field)
        row.addStretch(1)
        card.add_layout(row)
        return card

    def _build_operator_tab(self) -> QWidget:
        splitter = QSplitter(Qt.Horizontal)

        log_card = Card("Log")
        self.log = LogView()
        log_card.add(self.log, 1)
        splitter.addWidget(log_card)

        grids = QWidget()
        grid_layout = QGridLayout(grids)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(10)
        self.uut_grids: list[UutGrid] = []
        for i in range(MAX_UUTS):
            panel = UutGrid(i)
            self.uut_grids.append(panel)
            grid_layout.addWidget(panel, i // 2, i % 2)
        splitter.addWidget(grids)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([420, 1050])
        return splitter

    def _build_program_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        splitter = QSplitter(Qt.Vertical)

        source_card = Card("Program")
        self.program_table = QTableWidget(0, 10)
        self.program_table.setHorizontalHeaderLabels(
            ["Module", "Verb", "A2", "A3", "A4", "A5", "A6",
             "On error", "Alive", "Comment"])
        self.program_table.verticalHeader().setDefaultSectionSize(22)
        self.program_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.program_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.program_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Interactive)
        self.program_table.horizontalHeader().setStretchLastSection(True)
        source_card.add(self.program_table, 1)
        splitter.addWidget(source_card)

        diag_card = Card("Validation")
        self.diagnostics = QTableWidget(0, 3)
        self.diagnostics.setHorizontalHeaderLabels(["Severity", "Row", "Message"])
        self.diagnostics.verticalHeader().setVisible(False)
        self.diagnostics.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.diagnostics.horizontalHeader().setStretchLastSection(True)
        self.diagnostics.setColumnWidth(0, 90)
        self.diagnostics.setColumnWidth(1, 60)
        self.diagnostics.cellDoubleClicked.connect(self._goto_diagnostic)
        diag_card.add(self.diagnostics, 1)
        splitter.addWidget(diag_card)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)
        return widget

    def _build_verbs_tab(self) -> QWidget:
        card = Card("Registered verbs")
        table = QTableWidget(0, 4)
        table.setHorizontalHeaderLabels(["Module", "Verb", "Arguments", "Notes"])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setStretchLastSection(True)

        specs = sorted(REGISTRY.all(), key=lambda s: (s.module, s.name))
        table.setRowCount(len(specs))
        for i, spec in enumerate(specs):
            args = ", ".join(f"{p.name}{'' if p.required else '?'}"
                             for p in spec.params) or "—"
            note = "legacy alias" if spec.legacy else ""
            if spec.config_only:
                note = (note + ", config only").strip(", ")
            for column, text in enumerate((spec.module, spec.name, args, note)):
                table.setItem(i, column, QTableWidgetItem(text))
        table.resizeColumnsToContents()
        card.add(table, 1)
        return card

    def _build_footer(self) -> QWidget:
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(14)

        self.run_button = QPushButton("▶  RUN")
        self.run_button.setObjectName("Run")
        self.run_button.setEnabled(False)
        self.run_button.clicked.connect(self.start_run)
        self.run_button.setShortcut("F9")

        self.stop_button = QPushButton("■  STOP")
        self.stop_button.setObjectName("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop_run)
        self.stop_button.setShortcut("Esc")

        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)

        self.step_label = QLabel("—")
        self.step_label.setFont(QFont(theme.MONO.split(",")[0], 9))

        row.addWidget(self.run_button)
        row.addWidget(self.stop_button)
        row.addWidget(self.progress, 1)
        row.addWidget(self.step_label, 2)
        card.add_layout(row)
        return card

    # -- theme ------------------------------------------------------------

    def _apply_theme(self) -> None:
        palette = theme.palette(self.dark)
        self.setStyleSheet(theme.stylesheet(self.dark))
        self.banner.set_palette_colours(palette)
        self.log._palette = palette
        for panel in self.uut_grids:
            panel._palette = palette
            panel.verdict._palette = palette
            panel.verdict.set_state(panel.verdict.text())
        self.banner.show_status(self.banner.text())

    def _toggle_theme(self) -> None:
        self.dark = not self.dark
        self._apply_theme()

    # -- program ----------------------------------------------------------

    def _choose_program(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open test program", "",
            "Test programs (*.ods *.yaml *.yml *.csv *.txt);;All files (*)")
        if path:
            self.open_program(path)

    def _reload_program(self) -> None:
        if self.program and self.program.source:
            self.open_program(self.program.source)

    def open_program(self, path: str) -> None:
        try:
            program = load(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Cannot open program", str(exc))
            return

        self.program = program
        self.field_program.set_value(program.meta.get("name", os.path.basename(path)))
        self._populate_program_table(program)
        report = self._show_diagnostics(program)

        self.run_button.setEnabled(report.ok)
        if report.ok:
            self.banner.show_status("READY")
            self.statusBar().showMessage(
                f"{os.path.basename(path)} — {len(program.rows)} rows, "
                f"{len(program.labels)} labels. {report.summary()}")
        else:
            self.banner.show_status("PROGRAM INVALID",
                                    theme.palette(self.dark)["fail"])
            self.statusBar().showMessage(
                f"{report.summary()} — fix the errors on the Program tab before running.")
            self.tabs.setCurrentIndex(1)

    def _populate_program_table(self, program: Program) -> None:
        table = self.program_table
        table.setRowCount(len(program.rows))
        for i, row in enumerate(program.rows):
            for column in range(10):
                table.setItem(i, column, QTableWidgetItem(row.cells[column]))
        table.resizeColumnsToContents()

    def _show_diagnostics(self, program: Program):
        report = validate(program, REGISTRY)
        palette = theme.palette(self.dark)
        self.diagnostics.setRowCount(len(report))
        for i, diag in enumerate(report):
            severity = QTableWidgetItem(diag.severity.upper())
            severity.setForeground(
                Qt.red if diag.is_error else Qt.darkYellow)
            colour = palette["fail"] if diag.is_error else palette["warn"]
            from PySide6.QtGui import QColor
            severity.setForeground(QColor(colour))
            self.diagnostics.setItem(i, 0, severity)
            self.diagnostics.setItem(
                i, 1, QTableWidgetItem("" if diag.row is None else str(diag.row)))
            message = QTableWidgetItem(diag.message)
            if diag.detail:
                message.setToolTip(diag.detail)
            self.diagnostics.setItem(i, 2, message)
        return report

    def _goto_diagnostic(self, row: int, _column: int) -> None:
        item = self.diagnostics.item(row, 1)
        if item and item.text().isdigit():
            target = int(item.text())
            self.program_table.selectRow(target)
            self.program_table.scrollToItem(self.program_table.item(target, 0),
                                            QAbstractItemView.PositionAtCenter)

    # -- running ----------------------------------------------------------

    def start_run(self) -> None:
        if self.program is None or (self.thread and self.thread.is_alive()):
            return

        self.log.clear_log()
        for panel in self.uut_grids:
            panel.apply("clear", [], "", {})
            panel.set_verdict("RUN")
        self.progress.setValue(0)
        self.field_barcode1.set_value("")
        self.field_barcode2.set_value("")

        options = RunOptions(
            simulate=self.simulate_box.isChecked(),
            strict=True,
            operator=self.operator,
            station=self.station,
            workdir=os.path.dirname(self.program.source or ".") or ".",
            debug_dir=(self.debug_dir or "debug") if self.debug_box.isChecked() else None,
            telemetry=self.telemetry,
        )
        self.sequencer = Sequencer(REGISTRY, self.bridge, options)
        ctx = Context(self.program, self.bridge, simulate=options.simulate,
                      workdir=options.workdir)
        self.thread = RunThread(self.sequencer, self.program, ctx)

        self.run_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self._clock.start()
        self.thread.start()

    def stop_run(self) -> None:
        if self.sequencer:
            self.sequencer.stop()
            self.statusBar().showMessage("Stopping — teardown will still run.")

    def _tick_clock(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self._clock.stop()

    # -- engine events ----------------------------------------------------

    def _connect_bridge(self) -> None:
        b = self.bridge
        b.logged.connect(self._on_log)
        b.stepped.connect(self._on_step)
        b.status_changed.connect(self._on_status)
        b.progressed.connect(self._on_progress)
        b.ticked.connect(lambda s: self.field_elapsed.set_value(f"{s:.1f} s"))
        b.grid_changed.connect(self._on_grid)
        b.field_changed.connect(self._on_field)
        b.alive_changed.connect(self._on_alive)
        b.state_changed.connect(self._on_state)
        b.finished.connect(self._on_finished)

    def _on_log(self, message: str, level: str, row) -> None:
        self.log.append(message, level, row)

    def _on_step(self, row: int, text: str, comment: str) -> None:
        self.step_label.setText(f"{text}   {comment}".strip())
        if self.tabs.currentIndex() == 1 and row < self.program_table.rowCount():
            self.program_table.selectRow(row)

    def _on_status(self, text: str, colour) -> None:
        self.banner.show_status(text, colour)

    def _on_progress(self, value: float) -> None:
        if value < 0:
            self.progress.setRange(0, 0)          # indeterminate
        else:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(max(0.0, min(value, 1.0)) * 1000))

    def _on_grid(self, grid: int, op: str, values: list, tag: str, config: dict) -> None:
        index = grid - 1
        if 0 <= index < len(self.uut_grids):
            self.uut_grids[index].apply(op, values, tag, config)

    def _on_field(self, name: str, value: str, colour) -> None:
        if name == "barcode1":
            self.field_barcode1.set_value(value)
        elif name == "barcode2":
            self.field_barcode2.set_value(value)
        elif name == "worker_id":
            self.field_worker.set_value(value)
        elif name == "log" and colour == "clear":
            self.log.clear_log()

    def _on_alive(self, alive: list) -> None:
        for i, panel in enumerate(self.uut_grids):
            panel.setVisible(i < len(alive))
            if i < len(alive) and not alive[i]:
                panel.set_alive(False)

    def _on_state(self, state: str, detail: str) -> None:
        self.statusBar().showMessage(f"{state.title()}{': ' + detail if detail else ''}")
        if state == "teardown":
            self.banner.show_status("TEARDOWN", theme.palette(self.dark)["warn"])

    def _on_finished(self, passed: bool, per_uut: dict, detail: str) -> None:
        palette = theme.palette(self.dark)
        self.run_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self._clock.stop()
        self._last_record = self.thread.record if self.thread else None

        for index, panel in enumerate(self.uut_grids):
            if index in per_uut:
                panel.set_verdict("PASS" if per_uut[index] else "FAIL")
            elif panel.verdict.text() == "RUN":
                panel.set_verdict("--")

        if passed:
            self.banner.show_status("PASS", palette["pass"])
        else:
            self.banner.show_status("FAIL" if not detail else f"FAIL — {detail}"[:80],
                                    palette["fail"])
        self.progress.setRange(0, 1000)
        self.progress.setValue(1000 if passed else self.progress.value())

    # -- reports ----------------------------------------------------------

    def _save_report(self) -> None:
        if self._last_record is None:
            QMessageBox.information(self, "No run yet",
                                    "Run a program before saving a report.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save report", "report.xml",
            "XML (*.xml);;JSON (*.json);;CSV (*.csv)")
        if not path:
            return
        from ..reports import write_report

        fmt = os.path.splitext(path)[1].lstrip(".").lower() or "json"
        try:
            write_report(self._last_record, path, fmt)
        except (ValueError, OSError) as exc:
            QMessageBox.critical(self, "Cannot save report", str(exc))
            return
        self.statusBar().showMessage(f"Report saved to {path}")

    # -- shutdown ---------------------------------------------------------

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt name
        if self.telemetry is not None and not (self.thread and self.thread.is_alive()):
            self.telemetry.stop()
        if self.thread and self.thread.is_alive():
            answer = QMessageBox.question(
                self, "Test in progress",
                "A test is running. Stop it and close?\n\n"
                "Teardown will run before the window closes.")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            if self.sequencer:
                self.sequencer.stop()
            self.thread.join(timeout=20)
        event.accept()
