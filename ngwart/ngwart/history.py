"""Durable history of every run, in SQLite.

A RunRecord answers "how did this board do". Yield, Pareto and "has this test
ever failed on this station" are questions about *many* runs, so they need a
store that outlives the process.

SQLite because a test station should not acquire a database server: one file,
no daemon, and it ships with Python. It also gives real queries, which matters
once there are a few hundred thousand points -- aggregating those in Python on
every keystroke of a search box would not stay responsive.

Writes are deliberately forgiving. Losing a history row is an annoyance; failing
a test run because the history file was locked is not acceptable, so every write
path swallows its own errors after logging.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import dataclass

DEFAULT_PATH = "ngwart-history.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    started       TEXT    NOT NULL,
    ended         TEXT,
    duration_s    REAL,
    program       TEXT,
    station       TEXT,
    operator      TEXT,
    simulated     INTEGER NOT NULL DEFAULT 0,
    aborted       INTEGER NOT NULL DEFAULT 0,
    abort_reason  TEXT,
    points        INTEGER NOT NULL DEFAULT 0,
    failed_points INTEGER NOT NULL DEFAULT 0,
    passed        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS points (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    at        TEXT,
    name      TEXT    NOT NULL,
    uut       INTEGER,
    result    TEXT    NOT NULL,
    measured  TEXT,
    low       TEXT,
    high      TEXT,
    row       INTEGER,
    barcode   TEXT
);

CREATE INDEX IF NOT EXISTS points_name   ON points(name);
CREATE INDEX IF NOT EXISTS points_result ON points(result);
CREATE INDEX IF NOT EXISTS points_run    ON points(run_id);
CREATE INDEX IF NOT EXISTS runs_started  ON runs(started);
CREATE INDEX IF NOT EXISTS runs_program  ON runs(program);
"""


def _as_float(text) -> float | None:
    """Parse a stored measurement, or None if it is not a single number.

    Points store whatever the verb measured, as text: "0.2306", but also
    "NOT_FOUND", "None", and colour triples like "238,241,239". Only the first
    kind can be plotted on a value axis.
    """
    if text is None:
        return None
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


@dataclass
class Summary:
    """Headline figures for a set of runs."""

    runs: int = 0
    units: int = 0
    units_passed: int = 0
    points: int = 0
    failed: int = 0
    aborted: int = 0
    duration_s: float = 0.0

    @property
    def yield_pct(self) -> float:
        """First-pass yield: units passed as a share of units tested."""
        return 100.0 * self.units_passed / self.units if self.units else 0.0

    @property
    def point_pass_pct(self) -> float:
        return 100.0 * (self.points - self.failed) / self.points if self.points else 0.0


class History:
    """Append-only store of runs and their test points."""

    def __init__(self, path: str = DEFAULT_PATH) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self.error: str | None = None
        self._open()

    def _open(self) -> None:
        try:
            parent = os.path.dirname(os.path.abspath(self.path))
            if parent:
                os.makedirs(parent, exist_ok=True)
            # check_same_thread=False: the sequencer thread writes, the GUI
            # thread reads. Every access is serialised by self._lock.
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA)
            self._conn.commit()
        except sqlite3.Error as exc:
            self._conn = None
            self.error = str(exc)

    @property
    def available(self) -> bool:
        return self._conn is not None

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    # -- writing ----------------------------------------------------------

    def add_run(self, record) -> int | None:
        """Store a finished run. Returns its id, or None if it could not be.

        Never raises: a locked history file must not fail a test.
        """
        if self._conn is None:
            return None
        summary = record.summary()
        try:
            with self._lock, self._conn:
                cursor = self._conn.execute(
                    "INSERT INTO runs (started, ended, duration_s, program, "
                    "station, operator, simulated, aborted, abort_reason, "
                    "points, failed_points, passed) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (summary["started"], summary["ended"], summary["duration_s"],
                     summary["program"], summary["station"], summary["operator"],
                     int(bool(summary["simulated"])), int(bool(summary["aborted"])),
                     summary["abort_reason"], summary["points"],
                     summary["failed_points"], int(record.passed())))
                run_id = cursor.lastrowid
                self._conn.executemany(
                    "INSERT INTO points (run_id, at, name, uut, result, "
                    "measured, low, high, row, barcode) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [(run_id, p.at, p.name, p.uut, p.result, str(p.measured),
                      str(p.low), str(p.high), p.row,
                      record.barcodes.get(p.uut, ""))
                     for p in record.points])
            return run_id
        except sqlite3.Error as exc:
            self.error = str(exc)
            return None

    # -- reading ----------------------------------------------------------

    def _query(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        if self._conn is None:
            return []
        try:
            with self._lock:
                return list(self._conn.execute(sql, args))
        except sqlite3.Error as exc:
            self.error = str(exc)
            return []

    def summary(self, run_ids: list[int] | None = None,
                include_simulated: bool = False, program: str = "") -> Summary:
        """Headline figures, over everything or over a specific set of runs.

        Simulated runs are excluded by default. Folding dry runs into a yield
        figure would quietly corrupt the number that matters most.
        """
        where, args = self._scope(run_ids, include_simulated, program)
        rows = self._query(
            f"SELECT COUNT(*) AS runs, SUM(points) AS points, "
            f"SUM(failed_points) AS failed, SUM(aborted) AS aborted, "
            f"SUM(duration_s) AS duration FROM runs r {where}", args)
        if not rows:
            return Summary()
        row = rows[0]

        units = self._query(
            f"SELECT COUNT(*) AS units, "
            f"SUM(CASE WHEN fails = 0 THEN 1 ELSE 0 END) AS passed FROM ("
            f"  SELECT p.run_id, p.uut, "
            f"    SUM(CASE WHEN p.result = 'FAIL' THEN 1 ELSE 0 END) AS fails "
            f"  FROM points p JOIN runs r ON r.id = p.run_id {where} "
            f"  GROUP BY p.run_id, p.uut)", args)
        unit_row = units[0] if units else {"units": 0, "passed": 0}

        return Summary(
            runs=row["runs"] or 0,
            units=unit_row["units"] or 0,
            units_passed=unit_row["passed"] or 0,
            points=row["points"] or 0,
            failed=row["failed"] or 0,
            aborted=row["aborted"] or 0,
            duration_s=row["duration"] or 0.0,
        )

    def pareto(self, run_ids: list[int] | None = None, limit: int = 12,
               include_simulated: bool = False,
               program: str = "") -> list[tuple[str, int, int]]:
        """Failures by test, worst first: (name, failures, total attempts).

        Attempts come along because "5 failures out of 5" and "5 out of 500"
        are very different problems, and a bare count cannot tell them apart.
        """
        where, args = self._scope(run_ids, include_simulated, program)
        rows = self._query(
            f"SELECT p.name AS name, "
            f"  SUM(CASE WHEN p.result = 'FAIL' THEN 1 ELSE 0 END) AS fails, "
            f"  COUNT(*) AS attempts "
            f"FROM points p JOIN runs r ON r.id = p.run_id {where} "
            f"GROUP BY p.name HAVING fails > 0 "
            f"ORDER BY fails DESC, attempts DESC LIMIT ?", (*args, limit))
        return [(r["name"], r["fails"], r["attempts"]) for r in rows]

    def by_test(self, run_ids: list[int] | None = None,
                include_simulated: bool = False,
                program: str = "") -> list[tuple[str, int, int]]:
        """Every test with its pass and fail counts, worst rate first."""
        where, args = self._scope(run_ids, include_simulated, program)
        rows = self._query(
            f"SELECT p.name AS name, "
            f"  SUM(CASE WHEN p.result = 'FAIL' THEN 1 ELSE 0 END) AS fails, "
            f"  COUNT(*) AS attempts "
            f"FROM points p JOIN runs r ON r.id = p.run_id {where} "
            f"GROUP BY p.name ORDER BY (CAST(fails AS REAL) / attempts) DESC, "
            f"  attempts DESC", args)
        return [(r["name"], r["fails"], r["attempts"]) for r in rows]

    def search(self, text: str = "", result: str = "", program: str = "",
               since: str = "", limit: int = 2000,
               include_simulated: bool = False) -> list[dict]:
        """Points matching the filters, newest first."""
        clauses = []
        args: list = []
        if not include_simulated:
            clauses.append("r.simulated = 0")
        if text:
            clauses.append("(p.name LIKE ? OR p.barcode LIKE ?)")
            args += [f"%{text}%", f"%{text}%"]
        if result:
            clauses.append("p.result = ?")
            args.append(result)
        if program:
            clauses.append("r.program = ?")
            args.append(program)
        if since:
            clauses.append("r.started >= ?")
            args.append(since)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self._query(
            f"SELECT p.name, p.uut, p.result, p.measured, p.low, p.high, "
            f"       p.barcode, p.run_id, r.started, r.program, r.station, "
            f"       r.simulated "
            f"FROM points p JOIN runs r ON r.id = p.run_id {where} "
            f"ORDER BY r.started DESC, p.id DESC LIMIT ?", (*args, limit))
        return [dict(r) for r in rows]

    def trend(self, name: str, program: str = "", run_ids: list[int] | None = None,
              include_simulated: bool = False, limit: int = 500) -> list[dict]:
        """Every recorded point for one test, oldest first.

        Oldest first because a chart of it reads left to right, but the LIMIT has
        to keep the *newest* rows -- so the query takes them newest-first and the
        order is reversed here. Sorting ascending with a LIMIT would silently
        chart the oldest 500 points and call them current.

        ``value`` is the measurement parsed as a float, or None when the test
        records something that is not a number (a colour triple, a barcode). The
        caller decides what to do with those; the parse belongs here rather than
        in three places in the UI.
        """
        clauses = ["p.name = ?"]
        args: list = [name]
        if not include_simulated:
            clauses.append("r.simulated = 0")
        if program:
            clauses.append("r.program = ?")
            args.append(program)
        if run_ids is not None:
            if not run_ids:
                clauses.append("1 = 0")
            else:
                clauses.append(f"r.id IN ({','.join('?' * len(run_ids))})")
                args += list(run_ids)
        where = "WHERE " + " AND ".join(clauses)
        rows = self._query(
            f"SELECT p.id AS point_id, p.run_id, p.name, p.uut, p.result, "
            f"       p.measured, p.low, p.high, p.barcode, "
            f"       r.started, r.program "
            f"FROM points p JOIN runs r ON r.id = p.run_id {where} "
            f"ORDER BY r.started DESC, p.id DESC LIMIT ?", (*args, limit))

        out = []
        for r in reversed(rows):
            row = dict(r)
            row["value"] = _as_float(row["measured"])
            row["low_value"] = _as_float(row["low"])
            row["high_value"] = _as_float(row["high"])
            out.append(row)
        return out

    def test_names(self, program: str = "", run_ids: list[int] | None = None,
                   include_simulated: bool = False) -> list[str]:
        """Distinct test names in scope, most-recorded first."""
        where, args = self._scope(run_ids, include_simulated, program)
        rows = self._query(
            f"SELECT p.name AS name, COUNT(*) AS n "
            f"FROM points p JOIN runs r ON r.id = p.run_id {where} "
            f"GROUP BY p.name ORDER BY n DESC, p.name", args)
        return [r["name"] for r in rows]

    def programs(self) -> list[str]:
        return [r["program"] for r in
                self._query("SELECT DISTINCT program FROM runs "
                            "WHERE program IS NOT NULL ORDER BY program")
                if r["program"]]

    def recent_runs(self, limit: int = 50,
                    include_simulated: bool = False) -> list[dict]:
        where = "" if include_simulated else "WHERE simulated = 0"
        return [dict(r) for r in self._query(
            f"SELECT * FROM runs {where} ORDER BY started DESC LIMIT ?", (limit,))]

    # -- helpers ----------------------------------------------------------

    @staticmethod
    def _scope(run_ids: list[int] | None, include_simulated: bool,
               program: str = "") -> tuple[str, tuple]:
        """Build the shared WHERE clause. Every query aliases runs as `r`.

        ``program`` belongs here rather than in each caller: it used to be
        threaded into search() only, so picking a program narrowed the result
        table while the yield tile and the Pareto went on aggregating every
        product in the file -- and said nothing about it.
        """
        clauses = []
        args: list = []
        if not include_simulated:
            clauses.append("r.simulated = 0")
        if program:
            clauses.append("r.program = ?")
            args.append(program)
        if run_ids is not None:
            if not run_ids:
                clauses.append("1 = 0")          # an empty session matches nothing
            else:
                clauses.append(f"r.id IN ({','.join('?' * len(run_ids))})")
                args += list(run_ids)
        return ("WHERE " + " AND ".join(clauses)) if clauses else "", tuple(args)
