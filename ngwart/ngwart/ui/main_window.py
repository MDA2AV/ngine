"""The operator station window."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QFrame,
                               QSizePolicy,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QMainWindow, QMessageBox, QProgressBar,
                               QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout,
                               QWidget)

from .. import __version__
from ..engine import REGISTRY, Context, RunOptions, RunThread, Sequencer, validate
from ..engine import loaders
from ..engine.loaders import load
from ..engine.program import Program
from . import theme
from .bridge import QtBridge
from .stats import StatsTab
from .widgets import (Badge, Card, LogView, ScanField, Stat,
                      StatusBanner, UutGrid)

MAX_UUTS = 4


class MainWindow(QMainWindow):
    def __init__(self, program_path: str | None = None, simulate: bool = False,
                 dark: bool = True, station: str = "", operator: str = "",
                 debug_dir: str | None = None,
                 telemetry_port: int | None = None,
                 legacy_dir: str | None = None,
                 history_path: str | None = None) -> None:
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
        self.legacy_dir = legacy_dir
        self._last_record = None
        self._points = 0
        self._failed = 0
        self._program_ok = False
        self._active = False
        #: Step count when the current run is a hand-picked selection, else 0.
        self._partial_run = 0

        # What this station offers, which is what the statistics should be
        # scoped to -- not every product name the history file has accumulated.
        self.programs_dir = loaders.pick_program_dir(program=program_path)

        # Yield, Pareto and "has this ever failed here" are questions about many
        # runs, so they need a store that outlives the process.
        self.history = None
        if history_path != "":
            from ..history import DEFAULT_PATH, History

            self.history = History(history_path or DEFAULT_PATH)

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

        self.simulate_action.setChecked(simulate)
        self.debug_action.setChecked(bool(debug_dir))
        self._refresh_badges()
        if program_path:
            self.open_program(program_path)

    # -- construction -----------------------------------------------------

    def _build_ui(self) -> None:
        self._build_menus()

        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_header())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 8, 12, 8)
        body_layout.setSpacing(8)

        body_layout.addWidget(self._build_command_bar())

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_operator_tab(), "Operator")
        self.tabs.addTab(self._build_program_tab(), "Program")
        self.stats_tab = StatsTab(self.history, programs_dir=self.programs_dir)
        self.tabs.addTab(self.stats_tab, "Stats")
        self.tabs.addTab(self._build_verbs_tab(), "Verbs")
        body_layout.addWidget(self.tabs, 1)
        layout.addWidget(body, 1)
        self.setCentralWidget(root)
        if self.telemetry is not None:
            self.statusBar().showMessage(
                f"Telemetry live on http://localhost:{self.telemetry.bound_port}")
        else:
            self.statusBar().showMessage("No program loaded.")

    def _build_menus(self) -> None:
        """A real menu bar.

        The controls an operator uses constantly -- Run, Stop -- stay on the
        footer as large targets. Everything else is setup, and setup belongs in
        a menu rather than competing for space with the readout.
        """
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        self._action(file_menu, "&Open program…", self._choose_program,
                     QKeySequence.Open)
        self._action(file_menu, "&Reload", self._reload_program, "F5")
        self.recent_menu = file_menu.addMenu("Open &recent")
        self.recent_menu.setEnabled(False)
        file_menu.addSeparator()
        self.save_report_action = self._action(
            file_menu, "&Save report…", self._save_report, "Ctrl+S")
        self.save_report_action.setEnabled(False)
        file_menu.addSeparator()
        self._action(file_menu, "E&xit", self.close, QKeySequence.Quit)

        run_menu = bar.addMenu("&Run")
        self.start_action = self._action(run_menu, "&Start", self.start_run, "F9")
        self.stop_action = self._action(run_menu, "S&top", self.stop_run, "Esc")
        self.stop_action.setEnabled(False)
        self.step_action = self._action(
            run_menu, "Run &selected step(s)", self.run_selected_steps,
            "Ctrl+Return")
        self.step_action.setToolTip(
            "Execute only the rows selected in the Program tab. "
            "Available while stopped.")
        self.step_action.setEnabled(False)
        run_menu.addSeparator()

        self.simulate_action = self._toggle(
            run_menu, "Si&mulate hardware",
            "Run against simulated instruments. Reports produced this way are "
            "tagged, so they cannot be mistaken for a real run.")
        self.simulate_action.toggled.connect(self._refresh_badges)
        self.debug_action = self._toggle(
            run_menu, "Write &debug bundle",
            "Save captures, binary images, contour overlays, the data store "
            "and the full log to ./debug.")
        self.debug_action.toggled.connect(self._refresh_badges)

        view_menu = bar.addMenu("&View")
        for index, (name, key) in enumerate(
                (("&Operator", "Ctrl+1"), ("&Program", "Ctrl+2"),
                 ("&Statistics", "Ctrl+3"), ("&Verbs", "Ctrl+4"))):
            self._action(view_menu, name,
                         lambda _=False, i=index: self.tabs.setCurrentIndex(i),
                         key)
        view_menu.addSeparator()
        self.log_action = self._toggle(
            view_menu, "Show &log",
            "Collapse the log to give the result panels the full width.")
        self.log_action.setChecked(True)
        self.log_action.setShortcut("Ctrl+L")
        self.log_action.toggled.connect(self._toggle_log)
        view_menu.addSeparator()
        self._action(view_menu, "Toggle &theme", self._toggle_theme, "Ctrl+T")

        help_menu = bar.addMenu("&Help")
        self._action(help_menu, "&About NGWART", self._about)

    def _action(self, menu, text, slot, shortcut=None):
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        menu.addAction(action)
        return action

    def _toggle(self, menu, text, tip):
        action = QAction(text, self)
        action.setCheckable(True)
        action.setToolTip(tip)
        menu.addAction(action)
        return action

    def _about(self) -> None:
        from ..engine import REGISTRY

        QMessageBox.about(
            self, "NGWART",
            f"<b>NGWART {__version__}</b><br>"
            f"Functional test sequencer<br><br>"
            f"{len(REGISTRY)} verbs across {len(REGISTRY.modules())} modules.")

    def _build_header(self) -> QWidget:
        """One row: what is loaded, what state it is in, and the live figures.

        Deliberately compact. The header is glanced at, not read, so it earns a
        single line -- the screen belongs to the results.
        """
        frame = QFrame()
        frame.setObjectName("Identity")
        row = QHBoxLayout(frame)
        row.setContentsMargins(16, 7, 16, 7)
        row.setSpacing(14)

        identity = QVBoxLayout()
        identity.setSpacing(0)
        self.program_label = QLabel("No program loaded")
        self.program_label.setObjectName("ProgramName")
        self.program_meta = QLabel("Open one from the File menu")
        self.program_meta.setObjectName("ProgramMeta")
        identity.addWidget(self.program_label)
        identity.addWidget(self.program_meta)

        holder = QWidget()
        holder.setLayout(identity)
        holder.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row.addWidget(holder, 1)

        self.badges = QHBoxLayout()
        self.badges.setSpacing(6)
        self.badges.setAlignment(Qt.AlignVCenter)
        row.addLayout(self.badges)

        # Scanned values appear here only once a program sets them. A fixture
        # may scan none, one, or several, and empty boxes for values that may
        # never arrive are just noise.
        self.scans = QHBoxLayout()
        self.scans.setSpacing(8)
        self.scans.setAlignment(Qt.AlignVCenter)
        self._scan_chips: dict[str, QLabel] = {}
        row.addLayout(self.scans)
        row.addSpacing(14)

        # Units, not points. A four-up fixture running a 60-point program made
        # "points 240" the headline number, which is the one figure an operator
        # never needs -- what they act on is how many boards are good.
        self.stat_elapsed = Stat("elapsed", "0.0s")
        self.stat_passed = Stat("passed", "0")
        self.stat_failed = Stat("failed", "0")
        for stat in (self.stat_elapsed, self.stat_passed, self.stat_failed):
            stat.setMinimumWidth(78)
            row.addWidget(stat, 0, Qt.AlignVCenter)
            row.addSpacing(14)
        return frame

    def _set_scan(self, name: str, value: str) -> None:
        """Show a scanned value, creating its chip on first sight."""
        caption = {"barcode1": "BCODE 1", "barcode2": "BCODE 2",
                   "worker_id": "WORKER"}.get(name, name.upper())
        chip = self._scan_chips.get(name)
        if not value:
            if chip is not None:
                chip.hide()
            return
        if chip is None:
            chip = QLabel()
            chip.setObjectName("ScanChip")
            self.scans.addWidget(chip)
            self._scan_chips[name] = chip
        palette = theme.palette(self.dark)
        chip.setText(f"{caption}  {value}")
        chip.setStyleSheet(
            f"background: {palette['elevated']}; color: {palette['text']};"
            f"border: 1px solid {palette['border']}; border-radius: 6px;"
            f"padding: 5px 10px; font-family: {theme.MONO}; font-size: 10.5pt;")
        chip.show()

    def _refresh_badges(self) -> None:
        """Show what is unusual about this run, permanently and in the header.

        A simulated run that an operator takes for a real one is the worst thing
        this application can produce, so it is a badge rather than a tick in a
        menu they will not reopen.
        """
        while self.badges.count():
            item = self.badges.takeAt(0)
            widget = item.widget()
            if widget is not None:
                # Reparent now, do not merely schedule the delete. deleteLater()
                # runs when the event loop next collects, and until it does the
                # badge is still a visible child of the header -- but no longer
                # laid out, so it sits at Qt's default 640x480 and paints a
                # coloured rectangle across the whole strip.
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()

        palette = theme.palette(self.dark)
        if self.simulate_action.isChecked():
            self.badges.addWidget(self._badge("simulated", "warn", palette))
        if self.debug_action.isChecked():
            self.badges.addWidget(self._badge("debug", "info", palette))
        if self.legacy_dir:
            self.badges.addWidget(self._badge("site drivers", "accent", palette))

    def _badge(self, text: str, tone: str, palette: dict) -> Badge:
        badge = Badge(text, tone)
        badge.apply_palette(palette)
        return badge

    def _build_operator_tab(self) -> QWidget:
        splitter = QSplitter(Qt.Horizontal)
        self.op_splitter = splitter

        self.log_card = Card("Log")
        self.log = LogView()
        self.log_card.add(self.log, 1)
        splitter.addWidget(self.log_card)

        self.grid_host = QWidget()
        self.grid_layout = QGridLayout(self.grid_host)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        self.grid_layout.setSpacing(10)

        # Nothing is known about the fixture until a program declares it, so
        # start with a placeholder rather than four panels for units that may
        # not exist.
        self.uut_placeholder = QLabel(
            "No units yet.\n\n"
            "Panels appear once a program declares how many units the "
            "fixture holds.")
        self.uut_placeholder.setObjectName("Placeholder")
        self.uut_placeholder.setAlignment(Qt.AlignCenter)
        self.uut_placeholder.setWordWrap(True)
        self.grid_layout.addWidget(self.uut_placeholder, 0, 0)

        self.uut_grids: list[UutGrid] = []
        splitter.addWidget(self.grid_host)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        splitter.setSizes([420, 1050])
        # Draggable all the way shut, as well as toggleable from the View menu:
        # during a run the log is the thing to watch, and between boards it is
        # just taking width from the results.
        splitter.setCollapsible(0, True)
        splitter.setCollapsible(1, False)
        self._log_width = 420
        return splitter

    def _toggle_log(self, show: bool) -> None:
        sizes = self.op_splitter.sizes()
        total = sum(sizes) or 1470
        if show:
            width = self._log_width or 420
            self.op_splitter.setSizes([width, max(total - width, 200)])
        else:
            # Remember how wide it was, so showing it again restores the
            # operator's layout rather than a default.
            if sizes and sizes[0]:
                self._log_width = sizes[0]
            self.op_splitter.setSizes([0, total])

    def _set_uut_count(self, count: int) -> None:
        """Build exactly as many panels as the fixture has units.

        Called when a program is loaded -- from its initAlive row -- and again
        when the engine reports the live mask, in case the two disagree.
        """
        count = max(0, int(count))
        if count == len(self.uut_grids):
            return

        for panel in self.uut_grids:
            self.grid_layout.removeWidget(panel)
            panel.deleteLater()
        self.uut_grids = []

        self.uut_placeholder.setVisible(count == 0)
        if count == 0:
            self.grid_layout.addWidget(self.uut_placeholder, 0, 0)
            return

        self.grid_layout.removeWidget(self.uut_placeholder)
        columns = 1 if count == 1 else 2
        palette = theme.palette(self.dark)
        for i in range(count):
            panel = UutGrid(i)
            panel._palette = palette
            panel.verdict._palette = palette
            panel.verdict.set_state("--")
            self.uut_grids.append(panel)
            self.grid_layout.addWidget(panel, i // columns, i % columns)

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
        self.program_table.setObjectName("ProgramTable")
        self.program_table.verticalHeader().setDefaultSectionSize(22)
        self.program_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.program_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        # Several steps at once: ctrl-click to pick them out, shift-click for a
        # block. The selection is what "run selected" acts on.
        self.program_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.program_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.program_table.customContextMenuRequested.connect(
            self._program_context_menu)
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

    def _build_command_bar(self) -> QWidget:
        """Controls, state and progress on one line.

        These were three stacked strips -- banner, then tabs, then a footer of
        buttons -- which spent roughly a hundred vertical pixels saying things
        that fit comfortably side by side. The results are what the screen is
        for, so the chrome shares a row and gives the height back.
        """
        card = Card()
        card._layout.setContentsMargins(10, 7, 10, 7)
        row = QHBoxLayout()
        row.setSpacing(12)

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

        self.progress_label = QLabel("0%")
        self.progress_label.setObjectName("StatValue")
        self.progress_label.setMinimumWidth(56)
        self.progress_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.step_label = QLabel("—")
        self.step_label.setObjectName("ProgramMeta")
        self.step_label.setFont(QFont(theme.MONO.split(",")[0], 9))
        # A long comment on a step must not be able to push the banner around.
        self.step_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self.banner = StatusBanner()
        self.banner.setMinimumWidth(240)

        progress = QVBoxLayout()
        progress.setSpacing(2)
        progress.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        bar.setSpacing(theme.SPACE["sm"])
        bar.addWidget(self.progress, 1)
        bar.addWidget(self.progress_label)
        progress.addLayout(bar)
        progress.addWidget(self.step_label)
        progress_host = QWidget()
        progress_host.setObjectName("Bare")     # a layout holder, not a surface
        progress_host.setLayout(progress)

        row.addWidget(self.run_button)
        row.addWidget(self.stop_button)
        row.addSpacing(theme.SPACE["sm"])
        row.addWidget(self.banner, 3)
        row.addSpacing(theme.SPACE["sm"])
        row.addWidget(progress_host, 4)
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
            panel.repaint_tone()
        if hasattr(self, "stat_passed"):
            self._retally_units()
        for name, chip in list(self._scan_chips.items()):
            if chip.isVisible():
                self._set_scan(name, chip.text().split("  ", 1)[-1])
        self.uut_placeholder.setStyleSheet(f"color: {palette['muted']};")
        if hasattr(self, "stats_tab"):
            self.stats_tab.apply_palette(palette)
        self.banner.repaint_status()
        self._refresh_badges()

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
        self.program_label.setText(program.meta.get("name", os.path.basename(path)))
        # Last few path components rather than the absolute path: enough to
        # tell two similarly-named tables apart without pushing the badges off
        # the strip. The full path is on the tooltip.
        parts = os.path.abspath(path).split(os.sep)
        short = os.sep.join(parts[-3:]) if len(parts) > 3 else os.path.abspath(path)
        bits = [short, f"{len(program.rows)} rows", f"{len(program.labels)} labels"]
        if self.station:
            bits.append(f"station {self.station}")
        if self.operator:
            bits.append(f"operator {self.operator}")
        self.program_meta.setText("  ·  ".join(bits))
        self.program_meta.setToolTip(os.path.abspath(path))
        self.setWindowTitle(
            f"{program.meta.get('name', os.path.basename(path))} — "
            f"NGWART {__version__}")

        from ..engine.validator import _declared_alive_size

        self._set_uut_count(_declared_alive_size(program) or 0)
        self._populate_program_table(program)
        report = self._show_diagnostics(program)

        self._program_ok = report.ok
        self._sync_run_actions()
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

    def _program_context_menu(self, point) -> None:
        from PySide6.QtWidgets import QMenu

        rows = self._selected_exec_rows()
        menu = QMenu(self)
        action = menu.addAction(
            f"Run selected step{'s' if len(rows) != 1 else ''}"
            + (f"  ({len(rows)})" if rows else ""))
        # Says why it is unavailable rather than just being grey.
        if self.is_running:
            action.setEnabled(False)
            action.setToolTip("A run is in progress.")
        elif not rows:
            action.setEnabled(False)
            action.setToolTip("Select one or more executable steps.")
        else:
            action.triggered.connect(self.run_selected_steps)
        menu.exec(self.program_table.viewport().mapToGlobal(point))

    def _goto_diagnostic(self, row: int, _column: int) -> None:
        item = self.diagnostics.item(row, 1)
        if item and item.text().isdigit():
            target = int(item.text())
            self.program_table.selectRow(target)
            self.program_table.scrollToItem(self.program_table.item(target, 0),
                                            QAbstractItemView.PositionAtCenter)

    # -- running ----------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """True from launch until the run reports finished.

        Not ``thread.is_alive()``: the controls have to lock the instant a run
        is launched, and the thread has not started running by then -- which is
        how "run selected" stayed clickable during its own run.
        """
        return self._active

    def start_run(self) -> None:
        if self.program is None or self.is_running:
            return
        self._launch(self.program)

    def run_selected_steps(self) -> None:
        """Execute just the rows selected in the Program tab.

        For bring-up: energise one supply, poke one relay, re-read one
        measurement, without sitting through the whole table. Only while
        stopped -- interleaving hand-picked steps with a running sequence would
        drive the fixture from two places at once.
        """
        if self.program is None or self.is_running:
            return
        rows = self._selected_exec_rows()
        if not rows:
            QMessageBox.information(
                self, "Nothing to run",
                "Select one or more executable steps in the Program tab.\n\n"
                "Section markers, blank rows and rows with no module in "
                "column 0 are not steps.")
            return
        self._launch(self.program.subset(rows), partial=len(rows))

    def _selected_exec_rows(self) -> list[int]:
        """Selected rows that are actually steps inside <Exec>."""
        if self.program is None:
            return []
        body = self.program.body("Exec")
        chosen = {index.row() for index in
                  self.program_table.selectionModel().selectedRows()}
        return sorted(
            i for i in chosen
            if i in body and i < len(self.program.rows)
            and self.program.rows[i].module.strip()
            and not self.program.rows[i].is_marker)

    def _sync_run_actions(self) -> None:
        """Run controls follow one rule: nothing starts while something runs."""
        loaded = self.program is not None
        idle = not self.is_running
        self.run_button.setEnabled(loaded and idle and self._program_ok)
        self.start_action.setEnabled(loaded and idle and self._program_ok)
        self.stop_button.setEnabled(not idle)
        self.stop_action.setEnabled(not idle)
        self.step_action.setEnabled(loaded and idle and self._program_ok)

    def _launch(self, program: Program, partial: int = 0) -> None:
        self._partial_run = partial

        self.log.clear_log()
        for panel in self.uut_grids:
            panel.apply("clear", [], "", {})
            panel.set_verdict("RUN")
        self.progress.setValue(0)
        for name in list(self._scan_chips):
            self._set_scan(name, "")
        self._points = self._failed = 0
        self._retally_units()
        self.stat_elapsed.set_value("0.0s")

        options = RunOptions(
            simulate=self.simulate_action.isChecked(),
            strict=True,
            operator=self.operator,
            station=self.station,
            workdir=os.path.dirname(self.program.source or ".") or ".",
            debug_dir=(self.debug_dir or "debug") if self.debug_action.isChecked() else None,
            telemetry=self.telemetry,
        )
        self.sequencer = Sequencer(REGISTRY, self.bridge, options)
        ctx = Context(program, self.bridge, simulate=options.simulate,
                      workdir=options.workdir)
        self.thread = RunThread(self.sequencer, program, ctx)

        if partial:
            self.banner.show_status(
                f"STEP RUN — {partial} step(s)", theme.palette(self.dark)["warn"])
            self.log.append(
                f"Running {partial} selected step(s). Config and teardown still "
                f"run; this is not a board result and is not recorded.", "warn")

        self._active = True
        self._sync_run_actions()
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
        # Safety net: if a run thread ever dies without reporting, unlock the
        # controls rather than leave the station stuck. ident is None until the
        # thread has actually started, so this cannot fire in the launch window.
        if (self._active and self.thread is not None
                and self.thread.ident is not None):
            self._active = False
            self._sync_run_actions()

    # -- engine events ----------------------------------------------------

    def _connect_bridge(self) -> None:
        b = self.bridge
        b.logged.connect(self._on_log)
        b.stepped.connect(self._on_step)
        b.status_changed.connect(self._on_status)
        b.progressed.connect(self._on_progress)
        b.ticked.connect(lambda s: self.stat_elapsed.set_value(f"{s:.1f}s"))
        b.grid_changed.connect(self._on_grid)
        b.field_changed.connect(self._on_field)
        b.alive_changed.connect(self._on_alive)
        b.state_changed.connect(self._on_state)
        b.verdict_reached.connect(self._on_verdict)
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
            self.progress_label.setText("··")
        else:
            fraction = max(0.0, min(value, 1.0))
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(fraction * 1000))
            self.progress_label.setText(f"{fraction * 100:.0f}%")

    def _on_grid(self, grid: int, op: str, values: list, tag: str, config: dict) -> None:
        index = grid - 1
        if 0 <= index < len(self.uut_grids):
            self.uut_grids[index].apply(op, values, tag, config)

        if op == "add":
            self._points += 1
            if str(tag).upper() == "FAIL":
                self._failed += 1
            self._retally_units()

    def _on_verdict(self, uut: int, passed: bool, detail: str) -> None:
        """A program decided a unit's fate -- show it now, not at run end.

        cargo's table loops at REMOVE and never reaches a terminal result, so
        waiting for _on_finished left every panel showing RUN indefinitely.
        """
        if 0 <= uut < len(self.uut_grids):
            self.uut_grids[uut].set_verdict("PASS" if passed else "FAIL")
        self._retally_units()

    def _retally_units(self) -> None:
        """Count boards, not measurements.

        A unit is failed the moment it takes a failing point or is killed --
        which is also when the operator can stop caring about it. Everything
        else that has produced a result so far is passing; a unit still waiting
        for its first point is in neither column, so the two never add up to
        more than the units actually under test.
        """
        palette = theme.palette(self.dark)
        outcomes = [p.outcome() for p in self.uut_grids]
        passed = outcomes.count("pass")
        failed = outcomes.count("fail")
        self.stat_passed.set_value(str(passed), "pass" if passed else None, palette)
        self.stat_failed.set_value(str(failed), "fail" if failed else None, palette)

    def _on_field(self, name: str, value: str, colour) -> None:
        if name in ("barcode1", "barcode2", "worker_id"):
            self._set_scan(name, value)
        elif name == "log" and colour == "clear":
            self.log.clear_log()

    def _on_alive(self, alive: list) -> None:
        self._set_uut_count(len(alive))
        for i, panel in enumerate(self.uut_grids):
            if i < len(alive) and not alive[i]:
                panel.set_alive(False)
        self._retally_units()

    def _on_state(self, state: str, detail: str) -> None:
        self.statusBar().showMessage(f"{state.title()}{': ' + detail if detail else ''}")
        if state == "teardown":
            self.banner.show_status("TEARDOWN", theme.palette(self.dark)["warn"])

    def _on_finished(self, passed: bool, per_uut: dict, detail: str) -> None:
        palette = theme.palette(self.dark)
        record = self.thread.record if self.thread else None
        if record is not None:
            summary = record.summary()
            self.statusBar().showMessage(
                f"{summary['points']} points · {summary['failed_points']} failed"
                f" · {summary['duration_s']}s"
                + (f" · {summary['abort_reason']}" if summary["aborted"] else ""))
        self._active = False
        self.thread = None
        self._sync_run_actions()
        self._clock.stop()
        self._last_record = record
        self.save_report_action.setEnabled(self._last_record is not None)

        partial, self._partial_run = self._partial_run, 0
        if partial:
            # A hand-picked set of steps is not a board. Folding it into the
            # history would put a fictional unit into the yield figure.
            self.log.append(f"Step run finished ({partial} step(s)). "
                            f"Not recorded in history.", "warn")
        elif self.history is not None and self._last_record is not None:
            run_id = self.history.add_run(self._last_record)
            if run_id is None and self.history.error:
                self.log.append(f"History not written: {self.history.error}",
                                "warn")
            self.stats_tab.note_run(run_id)

        for index, panel in enumerate(self.uut_grids):
            if index in per_uut:
                panel.set_verdict("PASS" if per_uut[index] else "FAIL")
            elif panel.verdict.text() == "RUN":
                panel.set_verdict("--")
        self._retally_units()

        self.progress.setRange(0, 1000)
        if partial:
            # PASS on a handful of hand-picked steps would read as "the board
            # passed", which is the one thing it does not mean.
            aborted = record is not None and record.summary()["aborted"]
            self.banner.show_status(
                "STEP RUN FAILED" if aborted else "STEP RUN DONE",
                palette["fail"] if aborted else palette["warn"])
            self.progress.setValue(1000)
            return

        if passed:
            self.banner.show_status("PASS", palette["pass"])
        else:
            self.banner.show_status("FAIL" if not detail else f"FAIL — {detail}"[:80],
                                    palette["fail"])
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
        if self.history is not None:
            self.history.close()
        event.accept()
