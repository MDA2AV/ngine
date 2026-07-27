using System.Text.Json;

namespace Ngeoltx.Engine;

public sealed record StepRecord(
    int Row, string Module, string Verb, IReadOnlyList<string> Args,
    string Comment, DateTime Started, double DurationSeconds,
    string Outcome, string Detail = "")
{
    public string Outcome { get; set; } = Outcome;   // ok | skipped | failed | routed
}

/// <summary>A named pass/fail judgement -- the unit a quality system cares about.</summary>
public sealed record TestPoint(
    string Name, int? Uut, string Result,
    string Measured = "", string Low = "", string High = "",
    int? Row = null, DateTime? At = null);

/// <summary>
/// Append-only log of one execution. Thread safe.
/// </summary>
/// <remarks>
/// v1 produced its traceability XML by re-reading the data store at the end,
/// so the report could only contain whatever happened to still be in the array
/// -- anything overwritten mid-run was lost, and the report logic had to know
/// the coordinate layout of every product. Here the sequencer appends as each
/// row executes, and report writers are pure functions over the record.
/// </remarks>
public sealed class RunRecord
{
    private readonly Lock _gate = new();
    private readonly List<StepRecord> _steps = new();
    private readonly List<TestPoint> _points = new();
    private readonly Dictionary<int, string> _barcodes = new();

    public string ProgramName { get; init; } = "";
    public string Station { get; init; } = "";
    public string Operator { get; init; } = "";
    public bool Simulated { get; init; }

    public DateTime Started { get; } = DateTime.Now;
    public DateTime? Ended { get; private set; }
    public bool Aborted { get; private set; }
    public string AbortReason { get; private set; } = "";
    public IReadOnlyList<int> FinalAlive { get; private set; } = Array.Empty<int>();

    public IReadOnlyList<StepRecord> Steps { get { lock (_gate) return _steps.ToList(); } }
    public IReadOnlyList<TestPoint> Points { get { lock (_gate) return _points.ToList(); } }
    public IReadOnlyDictionary<int, string> Barcodes
    {
        get { lock (_gate) return new Dictionary<int, string>(_barcodes); }
    }

    public double DurationSeconds => ((Ended ?? DateTime.Now) - Started).TotalSeconds;

    // -- writing ----------------------------------------------------------

    public void AddStep(StepRecord step)
    {
        lock (_gate) _steps.Add(step);
    }

    public void AddPoint(TestPoint point)
    {
        lock (_gate) _points.Add(point with { At = point.At ?? DateTime.Now });
    }

    public void SetBarcode(int uut, string code)
    {
        lock (_gate) _barcodes[uut] = code;
    }

    public void Finish(IEnumerable<int> alive, bool aborted = false, string reason = "")
    {
        lock (_gate)
        {
            Ended = DateTime.Now;
            FinalAlive = alive.ToList();
            Aborted = aborted;
            AbortReason = reason;
        }
    }

    /// <summary>Mark the most recent step as diverted to an error handler.</summary>
    public void MarkLastRouted()
    {
        lock (_gate)
            if (_steps.Count > 0) _steps[^1].Outcome = "routed";
    }

    // -- reading ----------------------------------------------------------

    public IReadOnlyList<TestPoint> PointsFor(int uut) =>
        Points.Where(p => p.Uut == uut).ToList();

    /// <summary>True when any step failed or was routed to an error handler.</summary>
    public bool Diverted =>
        Steps.Any(s => s.Outcome is "failed" or "routed");

    /// <summary>
    /// A unit passes with at least one judged point and none failed.
    /// </summary>
    /// <remarks>
    /// Requiring a point is deliberate: a run that fell over before testing
    /// anything must not report a pass. The overall verdict additionally
    /// requires that nothing was diverted -- otherwise a vision stage could
    /// raise, jump to its handler, skip every optical test, and still report
    /// PASS on the measurements that ran beforehand.
    /// </remarks>
    public bool Passed(int? uut = null)
    {
        var points = uut is null ? Points : PointsFor(uut.Value);
        if (points.Count == 0) return false;
        if (points.Any(p => p.Result == "FAIL")) return false;
        return uut is not null || !Diverted;
    }

    public IReadOnlyList<int> Uuts() =>
        Points.Where(p => p.Uut is not null).Select(p => p.Uut!.Value)
              .Distinct().OrderBy(u => u).ToList();

    public RunSummary Summary() => new()
    {
        Program = ProgramName,
        Station = Station,
        Operator = Operator,
        Simulated = Simulated,
        Started = Started,
        Ended = Ended,
        DurationSeconds = Math.Round(DurationSeconds, 3),
        Aborted = Aborted,
        AbortReason = AbortReason,
        Steps = Steps.Count,
        Points = Points.Count,
        FailedPoints = Points.Count(p => p.Result == "FAIL"),
        DivertedSteps = Steps.Count(s => s.Outcome is "failed" or "routed"),
        PerUut = Uuts().ToDictionary(u => u, u => Passed(u)),
        Barcodes = Barcodes.ToDictionary(kv => kv.Key, kv => kv.Value),
    };

    public string ToJson() => JsonSerializer.Serialize(new
    {
        summary = Summary(),
        points = Points,
        steps = Steps,
    }, new JsonSerializerOptions { WriteIndented = true });
}

public sealed class RunSummary
{
    public string Program { get; init; } = "";
    public string Station { get; init; } = "";
    public string Operator { get; init; } = "";
    public bool Simulated { get; init; }
    public DateTime Started { get; init; }
    public DateTime? Ended { get; init; }
    public double DurationSeconds { get; init; }
    public bool Aborted { get; init; }
    public string AbortReason { get; init; } = "";
    public int Steps { get; init; }
    public int Points { get; init; }
    public int FailedPoints { get; init; }
    public int DivertedSteps { get; init; }
    public Dictionary<int, bool> PerUut { get; init; } = new();
    public Dictionary<int, string> Barcodes { get; init; } = new();
}
