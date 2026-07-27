using System.Collections.ObjectModel;
using Ngeoltx.Engine;

namespace Ngeoltx.App;

/// <summary>
/// Yield, Pareto and point search over the run history.
/// </summary>
/// <remarks>
/// Two scopes, because they answer different questions. <b>Session</b> is what
/// this shift has produced and is what an operator watches; <b>overall</b> is
/// every run this station ever stored and is what a process engineer looks at.
/// Mixing them hides a bad batch inside a good history, so they are never
/// blended.
///
/// Aggregation runs in SQL rather than over materialised rows: after a few
/// hundred thousand points, recomputing a yield in memory on every keystroke
/// stops being instant, and a search box that stutters does not get used.
/// </remarks>
public sealed class Stats : Notifier
{
    private readonly Station _station;

    private bool _sessionOnly = true;
    private bool _includeSimulated;
    private string _search = "";
    private string _resultFilter = "All";
    private string _programFilter = "All programs";
    private HistorySummary _summary = new();

    public Stats(Station station)
    {
        _station = station;
        station.RunFinished += _ => Refresh();
        Refresh();
    }

    /// <summary>
    /// Replaced wholesale on every refresh rather than mutated.
    /// </summary>
    /// <remarks>
    /// The chart renders from the value it is handed, so it has to see a new
    /// reference to know anything changed -- mutating a collection in place
    /// leaves the last drawing on screen.
    /// </remarks>
    public IReadOnlyList<ParetoEntry> Pareto { get; private set; } = Array.Empty<ParetoEntry>();

    public ObservableCollection<PointRow> Points { get; } = new();
    public ObservableCollection<string> Programs { get; } = new() { "All programs" };

    public IReadOnlyList<string> ResultFilters { get; } = new[] { "All", "PASS", "FAIL" };

    // -- filters ---------------------------------------------------------------

    /// <summary>Session scope: only the runs this instance recorded.</summary>
    public bool SessionOnly
    {
        get => _sessionOnly;
        set { if (Set(ref _sessionOnly, value)) { Raise(nameof(ScopeLabel)); Refresh(); } }
    }

    /// <summary>
    /// Simulated runs are excluded by default.
    /// </summary>
    /// <remarks>
    /// Folding a dry run into a yield figure quietly corrupts the number the
    /// whole line is judged on, so including them is an explicit choice.
    /// </remarks>
    public bool IncludeSimulated
    {
        get => _includeSimulated;
        set { if (Set(ref _includeSimulated, value)) Refresh(); }
    }

    public string Search
    {
        get => _search;
        set { if (Set(ref _search, value)) RefreshPoints(); }
    }

    public string ResultFilter
    {
        get => _resultFilter;
        set { if (Set(ref _resultFilter, value)) RefreshPoints(); }
    }

    public string ProgramFilter
    {
        get => _programFilter;
        set { if (Set(ref _programFilter, value)) RefreshPoints(); }
    }

    public string ScopeLabel => _sessionOnly ? "This session" : "All stored runs";

    // -- figures ----------------------------------------------------------------

    public string Runs => _summary.Runs.ToString();
    public string Units => _summary.Units.ToString();

    /// <summary>
    /// First-pass yield, counted in <b>units</b>.
    /// </summary>
    /// <remarks>
    /// Not in test points. A board that fails one of forty tests is one reject,
    /// not a 97.5% pass -- counting points makes a line with a single chronic
    /// failure look almost perfect.
    /// </remarks>
    public string Yield => _summary.Units == 0 ? "--" : _summary.YieldPercent.ToString("0.0") + "%";

    public string PointPass =>
        _summary.Points == 0 ? "--" : _summary.PointPassPercent.ToString("0.0") + "%";

    public string PointCount => _summary.Points.ToString();
    public string FailedCount => _summary.Failed.ToString();
    public string AbortedCount => _summary.Aborted.ToString();

    public string AverageDuration => _summary.Runs == 0
        ? "--"
        : (_summary.DurationSeconds / _summary.Runs).ToString("0.0") + " s";

    public string Availability => _station.History is { Available: true }
        ? ""
        : "History is unavailable: " + (_station.History?.Error ?? "disabled at startup")
          + ". Statistics cover this session only while it stays that way.";

    public bool HistoryUnavailable => _station.History is not { Available: true };

    // -- refresh ------------------------------------------------------------------

    private IReadOnlyList<long>? Scope =>
        _sessionOnly ? _station.SessionRuns.ToList() : null;

    public void Refresh()
    {
        var history = _station.History;
        if (history is not { Available: true })
        {
            Raise(nameof(Availability));
            Raise(nameof(HistoryUnavailable));
            return;
        }

        _summary = history.Summary(Scope, _includeSimulated);
        foreach (var name in new[]
        {
            nameof(Runs), nameof(Units), nameof(Yield), nameof(PointPass),
            nameof(PointCount), nameof(FailedCount), nameof(AbortedCount),
            nameof(AverageDuration), nameof(Availability), nameof(HistoryUnavailable),
        })
            RaiseNamed(name);

        Pareto = history.Pareto(Scope, 12, _includeSimulated);
        Raise(nameof(Pareto));

        var known = Programs.ToHashSet();
        foreach (var program in history.Programs())
            if (known.Add(program)) Programs.Add(program);

        RefreshPoints();
    }

    private void RefreshPoints()
    {
        var history = _station.History;
        if (history is not { Available: true }) return;

        var rows = history.Search(
            _search.Trim(),
            _resultFilter == "All" ? "" : _resultFilter,
            _programFilter == "All programs" ? "" : _programFilter,
            includeSimulated: _includeSimulated,
            runIds: Scope);

        Points.Clear();
        foreach (var row in rows.Take(500)) Points.Add(row);
        Raise(nameof(PointsSummary));
    }

    public string PointsSummary =>
        Points.Count == 0 ? "No matching results." :
        Points.Count >= 500 ? "Showing the 500 most recent matches." :
        Points.Count + " matching result" + (Points.Count == 1 ? "" : "s") + ".";

    private void RaiseNamed(string name) => Raise(name);
}
