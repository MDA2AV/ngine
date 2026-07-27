using Microsoft.Data.Sqlite;

namespace Ngeoltx.Engine;

/// <summary>Headline figures for a set of runs.</summary>
public sealed class HistorySummary
{
    public int Runs { get; init; }
    public int Units { get; init; }
    public int UnitsPassed { get; init; }
    public int Points { get; init; }
    public int Failed { get; init; }
    public int Aborted { get; init; }
    public double DurationSeconds { get; init; }

    /// <summary>First-pass yield: units passed as a share of units tested.</summary>
    public double YieldPercent => Units == 0 ? 0.0 : 100.0 * UnitsPassed / Units;

    public double PointPassPercent =>
        Points == 0 ? 0.0 : 100.0 * (Points - Failed) / Points;
}

public sealed record ParetoEntry(string Name, int Failures, int Attempts)
{
    public double FailRate => Attempts == 0 ? 0.0 : 100.0 * Failures / Attempts;
}

public sealed record PointRow(
    string Name, int? Uut, string Result, string Measured, string Low, string High,
    string Barcode, string Started, string Program, string Station, bool Simulated);

/// <summary>
/// Durable history of every run, in SQLite.
/// </summary>
/// <remarks>
/// A <see cref="RunRecord"/> answers "how did this board do". Yield, Pareto and
/// "has this test ever failed on this station" are questions about <em>many</em>
/// runs, so they need a store that outlives the process.
///
/// SQLite because a test station should not acquire a database server: one
/// file, no daemon. It also gives real queries, which matters once there are a
/// few hundred thousand points -- aggregating those in memory on every
/// keystroke of a search box would not stay responsive.
///
/// Writes are deliberately forgiving. Losing a history row is an annoyance;
/// failing a test run because the history file was locked is not acceptable.
/// </remarks>
public sealed class RunHistory : IDisposable
{
    public const string DefaultPath = "ngeoltx-history.db";

    private const string Schema = """
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
            passed        INTEGER NOT NULL DEFAULT 0);

        CREATE TABLE IF NOT EXISTS points (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id    INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
            at        TEXT,
            name      TEXT    NOT NULL,
            uut       INTEGER,
            result    TEXT    NOT NULL,
            measured  TEXT, low TEXT, high TEXT, row INTEGER, barcode TEXT);

        CREATE INDEX IF NOT EXISTS points_name   ON points(name);
        CREATE INDEX IF NOT EXISTS points_result ON points(result);
        CREATE INDEX IF NOT EXISTS points_run    ON points(run_id);
        CREATE INDEX IF NOT EXISTS runs_started  ON runs(started);
        """;

    private readonly Lock _gate = new();
    private SqliteConnection? _connection;

    public RunHistory(string path = DefaultPath)
    {
        Path = path;
        try
        {
            var parent = System.IO.Path.GetDirectoryName(System.IO.Path.GetFullPath(path));
            if (!string.IsNullOrEmpty(parent)) Directory.CreateDirectory(parent);

            _connection = new SqliteConnection("Data Source=" + path);
            _connection.Open();
            using var command = _connection.CreateCommand();
            command.CommandText = Schema;
            command.ExecuteNonQuery();
        }
        catch (Exception exc)
        {
            _connection = null;
            Error = exc.Message;
        }
    }

    public string Path { get; }
    public string? Error { get; private set; }
    public bool Available => _connection is not null;

    public void Dispose()
    {
        lock (_gate)
        {
            _connection?.Dispose();
            _connection = null;
        }
    }

    // -- writing -----------------------------------------------------------

    /// <summary>Store a finished run. Returns its id, or null if it could not be.</summary>
    public long? AddRun(RunRecord record)
    {
        if (_connection is null) return null;
        var summary = record.Summary();
        try
        {
            lock (_gate)
            {
                using var transaction = _connection.BeginTransaction();
                using var insert = _connection.CreateCommand();
                insert.Transaction = transaction;
                insert.CommandText = """
                    INSERT INTO runs (started, ended, duration_s, program, station,
                                      operator, simulated, aborted, abort_reason,
                                      points, failed_points, passed)
                    VALUES ($started,$ended,$duration,$program,$station,$operator,
                            $simulated,$aborted,$reason,$points,$failed,$passed);
                    SELECT last_insert_rowid();
                    """;
                insert.Parameters.AddWithValue("$started", summary.Started.ToString("s"));
                insert.Parameters.AddWithValue("$ended",
                    (object?)summary.Ended?.ToString("s") ?? DBNull.Value);
                insert.Parameters.AddWithValue("$duration", summary.DurationSeconds);
                insert.Parameters.AddWithValue("$program", summary.Program);
                insert.Parameters.AddWithValue("$station", summary.Station);
                insert.Parameters.AddWithValue("$operator", summary.Operator);
                insert.Parameters.AddWithValue("$simulated", summary.Simulated ? 1 : 0);
                insert.Parameters.AddWithValue("$aborted", summary.Aborted ? 1 : 0);
                insert.Parameters.AddWithValue("$reason", summary.AbortReason);
                insert.Parameters.AddWithValue("$points", summary.Points);
                insert.Parameters.AddWithValue("$failed", summary.FailedPoints);
                insert.Parameters.AddWithValue("$passed", record.Passed() ? 1 : 0);
                var runId = (long)(insert.ExecuteScalar() ?? 0L);

                foreach (var point in record.Points)
                {
                    using var add = _connection.CreateCommand();
                    add.Transaction = transaction;
                    add.CommandText = """
                        INSERT INTO points (run_id, at, name, uut, result, measured,
                                            low, high, row, barcode)
                        VALUES ($run,$at,$name,$uut,$result,$measured,$low,$high,$row,$barcode)
                        """;
                    add.Parameters.AddWithValue("$run", runId);
                    add.Parameters.AddWithValue("$at",
                        (object?)point.At?.ToString("s") ?? DBNull.Value);
                    add.Parameters.AddWithValue("$name", point.Name);
                    add.Parameters.AddWithValue("$uut", (object?)point.Uut ?? DBNull.Value);
                    add.Parameters.AddWithValue("$result", point.Result);
                    add.Parameters.AddWithValue("$measured", point.Measured);
                    add.Parameters.AddWithValue("$low", point.Low);
                    add.Parameters.AddWithValue("$high", point.High);
                    add.Parameters.AddWithValue("$row", (object?)point.Row ?? DBNull.Value);
                    add.Parameters.AddWithValue("$barcode",
                        point.Uut is not null && record.Barcodes.TryGetValue(point.Uut.Value,
                            out var code) ? code : "");
                    add.ExecuteNonQuery();
                }
                transaction.Commit();
                return runId;
            }
        }
        catch (Exception exc)
        {
            Error = exc.Message;
            return null;
        }
    }

    // -- reading -----------------------------------------------------------

    private List<T> Query<T>(string sql, Action<SqliteCommand> bind,
                             Func<SqliteDataReader, T> read)
    {
        var results = new List<T>();
        if (_connection is null) return results;
        try
        {
            lock (_gate)
            {
                using var command = _connection.CreateCommand();
                command.CommandText = sql;
                bind(command);
                using var reader = command.ExecuteReader();
                while (reader.Read()) results.Add(read(reader));
            }
        }
        catch (Exception exc) { Error = exc.Message; }
        return results;
    }

    /// <summary>
    /// Build the shared WHERE clause. Every query aliases runs as r.
    /// </summary>
    /// <remarks>
    /// Simulated runs are excluded by default: folding dry runs into a yield
    /// figure would quietly corrupt the number that matters most.
    /// </remarks>
    private static string Scope(IReadOnlyList<long>? runIds, bool includeSimulated)
    {
        var clauses = new List<string>();
        if (!includeSimulated) clauses.Add("r.simulated = 0");
        if (runIds is not null)
            clauses.Add(runIds.Count == 0
                ? "1 = 0"
                : "r.id IN (" + string.Join(",", runIds) + ")");
        return clauses.Count > 0 ? "WHERE " + string.Join(" AND ", clauses) : "";
    }

    public HistorySummary Summary(IReadOnlyList<long>? runIds = null,
                                  bool includeSimulated = false)
    {
        var where = Scope(runIds, includeSimulated);

        var totals = Query(
            "SELECT COUNT(*) AS runs, IFNULL(SUM(points),0) AS points, "
            + "IFNULL(SUM(failed_points),0) AS failed, IFNULL(SUM(aborted),0) AS aborted, "
            + "IFNULL(SUM(duration_s),0) AS duration FROM runs r " + where,
            _ => { },
            r => (Runs: r.GetInt32(0), Points: r.GetInt32(1), Failed: r.GetInt32(2),
                  Aborted: r.GetInt32(3), Duration: r.GetDouble(4))).FirstOrDefault();

        var units = Query(
            "SELECT COUNT(*) AS units, IFNULL(SUM(CASE WHEN fails = 0 THEN 1 ELSE 0 END),0) "
            + "AS passed FROM (SELECT p.run_id, p.uut, "
            + "SUM(CASE WHEN p.result = 'FAIL' THEN 1 ELSE 0 END) AS fails "
            + "FROM points p JOIN runs r ON r.id = p.run_id " + where
            + " GROUP BY p.run_id, p.uut)",
            _ => { },
            r => (Units: r.GetInt32(0), Passed: r.GetInt32(1))).FirstOrDefault();

        return new HistorySummary
        {
            Runs = totals.Runs,
            Units = units.Units,
            UnitsPassed = units.Passed,
            Points = totals.Points,
            Failed = totals.Failed,
            Aborted = totals.Aborted,
            DurationSeconds = totals.Duration,
        };
    }

    /// <summary>
    /// Failures by test, worst first.
    /// </summary>
    /// <remarks>
    /// Attempts come along because "5 failures out of 5" and "5 out of 500" are
    /// very different problems, and a bare count cannot tell them apart.
    /// </remarks>
    public List<ParetoEntry> Pareto(IReadOnlyList<long>? runIds = null, int limit = 12,
                                    bool includeSimulated = false) =>
        Query(
            "SELECT p.name, SUM(CASE WHEN p.result = 'FAIL' THEN 1 ELSE 0 END) AS fails, "
            + "COUNT(*) AS attempts FROM points p JOIN runs r ON r.id = p.run_id "
            + Scope(runIds, includeSimulated)
            + " GROUP BY p.name HAVING fails > 0 ORDER BY fails DESC, attempts DESC LIMIT $n",
            c => c.Parameters.AddWithValue("$n", limit),
            r => new ParetoEntry(r.GetString(0), r.GetInt32(1), r.GetInt32(2)));

    /// <summary>
    /// Point-level search.
    /// </summary>
    /// <remarks>
    /// <paramref name="runIds"/> scopes the search the same way the summary and
    /// Pareto queries are scoped, so "this session" means the same set of runs
    /// everywhere on the statistics page. An empty list means no runs, which is
    /// not the same as no filter -- passing null is how you ask for everything.
    /// </remarks>
    public List<PointRow> Search(string text = "", string result = "", string program = "",
                                 int limit = 2000, bool includeSimulated = false,
                                 IReadOnlyList<long>? runIds = null)
    {
        var clauses = new List<string>();
        if (!includeSimulated) clauses.Add("r.simulated = 0");
        if (runIds is not null)
            clauses.Add(runIds.Count == 0
                ? "1 = 0"
                : "r.id IN (" + string.Join(",", runIds) + ")");
        if (text.Length > 0) clauses.Add("(p.name LIKE $text OR p.barcode LIKE $text)");
        if (result.Length > 0) clauses.Add("p.result = $result");
        if (program.Length > 0) clauses.Add("r.program = $program");
        var where = clauses.Count > 0 ? "WHERE " + string.Join(" AND ", clauses) : "";

        return Query(
            "SELECT p.name, p.uut, p.result, p.measured, p.low, p.high, p.barcode, "
            + "r.started, r.program, r.station, r.simulated "
            + "FROM points p JOIN runs r ON r.id = p.run_id " + where
            + " ORDER BY r.started DESC, p.id DESC LIMIT $n",
            c =>
            {
                if (text.Length > 0) c.Parameters.AddWithValue("$text", "%" + text + "%");
                if (result.Length > 0) c.Parameters.AddWithValue("$result", result);
                if (program.Length > 0) c.Parameters.AddWithValue("$program", program);
                c.Parameters.AddWithValue("$n", limit);
            },
            r => new PointRow(
                r.GetString(0), r.IsDBNull(1) ? null : r.GetInt32(1), r.GetString(2),
                r.IsDBNull(3) ? "" : r.GetString(3), r.IsDBNull(4) ? "" : r.GetString(4),
                r.IsDBNull(5) ? "" : r.GetString(5), r.IsDBNull(6) ? "" : r.GetString(6),
                r.GetString(7), r.IsDBNull(8) ? "" : r.GetString(8),
                r.IsDBNull(9) ? "" : r.GetString(9), r.GetInt32(10) != 0));
    }

    public List<string> Programs() =>
        Query("SELECT DISTINCT program FROM runs WHERE program IS NOT NULL "
              + "AND program <> '' ORDER BY program",
              _ => { }, r => r.GetString(0));
}
