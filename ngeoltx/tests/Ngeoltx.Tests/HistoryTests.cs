using Ngeoltx.Engine;
using Xunit;
using static Ngeoltx.Tests.Fixtures;

namespace Ngeoltx.Tests;

public class HistoryTests : IDisposable
{
    private readonly string _path = TempFile(".db");

    public void Dispose()
    {
        try { if (File.Exists(_path)) File.Delete(_path); } catch { /* best effort */ }
    }

    private static RunRecord Record(bool simulated = false,
                                    params (string Name, int Uut, string Result)[] points)
    {
        var record = new RunRecord
        {
            ProgramName = "cargo",
            Station = "BENCH1",
            Simulated = simulated,
        };
        foreach (var (name, uut, result) in points)
            record.AddPoint(new TestPoint(name, uut, result, "1.0", "0", "2"));
        record.Finish(new[] { 1, 1 });
        return record;
    }

    /// <summary>
    /// Yield counts units, not points.
    /// </summary>
    /// <remarks>
    /// A board failing one of forty tests is one reject. Counting points would
    /// report 97.5% for a unit that is going in the scrap bin, which makes a
    /// line with a single chronic failure look nearly perfect.
    /// </remarks>
    [Fact]
    public void YieldIsCountedInUnits()
    {
        using var history = new RunHistory(_path);

        // Two units, one of which fails a single point out of four.
        history.AddRun(Record(false,
            ("A", 0, "PASS"), ("B", 0, "PASS"),
            ("A", 1, "PASS"), ("B", 1, "FAIL")));

        var summary = history.Summary();

        Assert.Equal(2, summary.Units);
        Assert.Equal(1, summary.UnitsPassed);
        Assert.Equal(50.0, summary.YieldPercent, 3);
        // The point-level figure is deliberately different, and reported apart.
        Assert.Equal(75.0, summary.PointPassPercent, 3);
    }

    /// <summary>
    /// Simulated runs are excluded by default.
    /// </summary>
    /// <remarks>
    /// Folding a dry run into the yield quietly corrupts the number the line is
    /// judged on, so including it has to be an explicit choice.
    /// </remarks>
    [Fact]
    public void SimulatedRunsAreOutOfScopeUnlessAskedFor()
    {
        using var history = new RunHistory(_path);
        history.AddRun(Record(true, ("A", 0, "FAIL")));

        Assert.Equal(0, history.Summary().Runs);
        Assert.Equal(1, history.Summary(includeSimulated: true).Runs);
    }

    [Fact]
    public void ParetoRanksFailuresAndCarriesTheAttemptCount()
    {
        using var history = new RunHistory(_path);
        history.AddRun(Record(false,
            ("RARE", 0, "FAIL"),
            ("COMMON", 0, "FAIL"), ("COMMON", 1, "FAIL"), ("COMMON", 2, "FAIL")));

        var pareto = history.Pareto();

        Assert.Equal("COMMON", pareto[0].Name);
        Assert.Equal(3, pareto[0].Failures);
        // Attempts matter: "3 of 3" and "3 of 300" are different problems.
        Assert.Equal(3, pareto[0].Attempts);
        Assert.Equal(100.0, pareto[0].FailRate, 3);
        Assert.DoesNotContain(pareto, entry => entry.Failures == 0);
    }

    [Fact]
    public void SearchFiltersByNameAndResult()
    {
        using var history = new RunHistory(_path);
        history.AddRun(Record(false, ("VBAT", 0, "PASS"), ("CURRENT", 1, "FAIL")));

        Assert.Single(history.Search("VBAT"));
        Assert.Single(history.Search(result: "FAIL"));
        Assert.Equal(2, history.Search().Count);
        Assert.Empty(history.Search("NOTHING"));
    }

    /// <summary>
    /// Scoping by run id means "this session" is the same set everywhere.
    /// </summary>
    [Fact]
    public void RunScopeAppliesToSummaryParetoAndSearchAlike()
    {
        using var history = new RunHistory(_path);
        var first = history.AddRun(Record(false, ("VBAT", 0, "PASS")));
        history.AddRun(Record(false, ("VBAT", 0, "FAIL")));

        var scope = new[] { first!.Value };

        Assert.Equal(1, history.Summary(scope).Runs);
        Assert.Empty(history.Pareto(scope));
        Assert.Single(history.Search(runIds: scope));
        // An empty scope means no runs, not "no filter".
        Assert.Empty(history.Search(runIds: Array.Empty<long>()));
    }

    [Fact]
    public void BarcodesAreCarriedOntoEveryPointOfTheirUnit()
    {
        using var history = new RunHistory(_path);
        var record = Record(false, ("VBAT", 0, "PASS"));
        record.SetBarcode(0, "AB12345");
        history.AddRun(record);

        var rows = history.Search("AB123");

        Assert.Equal("AB12345", Assert.Single(rows).Barcode);
    }

    /// <summary>
    /// An unusable history file must not take a run down with it.
    /// </summary>
    /// <remarks>
    /// Losing a history row is an annoyance; failing a test because a database
    /// file was locked is not acceptable on a production line.
    /// </remarks>
    [Fact]
    public void AnUnusableDatabaseDegradesInsteadOfThrowing()
    {
        var directory = Path.Combine(Path.GetTempPath(), "ngeoltx-not-a-dir-" + Guid.NewGuid());
        Directory.CreateDirectory(directory);
        try
        {
            using var history = new RunHistory(directory);   // a directory, not a file

            Assert.False(history.Available);
            Assert.Null(history.AddRun(Record(false, ("A", 0, "PASS"))));
            Assert.Equal(0, history.Summary().Runs);
        }
        finally { Directory.Delete(directory, true); }
    }
}
