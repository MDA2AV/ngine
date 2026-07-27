using Ngeoltx.Drivers;
using Ngeoltx.Engine;
using Ngeoltx.Engine.Loaders;

namespace Ngeoltx.Tests;

/// <summary>
/// Shared setup: registered drivers and a program built from cells.
/// </summary>
/// <remarks>
/// Tests build programs from literal rows rather than from files wherever the
/// file format is not what is under test. That keeps a sequencer test about the
/// sequencer.
/// </remarks>
public static class Fixtures
{
    private static readonly object Gate = new();
    private static bool _registered;

    public static void EnsureDrivers()
    {
        lock (Gate)
        {
            if (_registered) return;
            Catalog.Register();
            _registered = true;
        }
    }

    /// <summary>Build a program from rows of cells, then finalise it.</summary>
    public static TestProgram Program(params string[][] rows)
    {
        EnsureDrivers();
        var program = new TestProgram();
        foreach (var cells in rows)
            program.Rows.Add(new Row(program.Rows.Count, cells));
        return program.Finalise();
    }

    /// <summary>Ten cells, padded, so a test only writes the ones it cares about.</summary>
    public static string[] R(params string[] cells)
    {
        var row = new string[Row.Columns];
        for (var i = 0; i < row.Length; i++) row[i] = i < cells.Length ? cells[i] : "";
        return row;
    }

    /// <summary>A row with its exception label and alive mask set explicitly.</summary>
    public static string[] Guarded(string module, string verb, string route, string alive,
                                   params string[] args)
    {
        var row = R(new[] { module, verb }.Concat(args).ToArray());
        row[7] = route;
        row[8] = alive;
        return row;
    }

    public static (RunRecord Record, RecordingListener Events) Run(
        TestProgram program, bool strict = true, bool simulate = true)
    {
        var listener = new RecordingListener();
        var sequencer = new Sequencer(VerbRegistry.Default, listener,
            new RunOptions { Simulate = simulate, Strict = strict });
        return (sequencer.Run(program), listener);
    }

    public static string TempFile(string extension)
    {
        var path = Path.Combine(Path.GetTempPath(),
            "ngeoltx-test-" + Guid.NewGuid().ToString("N") + extension);
        return path;
    }
}
