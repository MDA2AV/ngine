using System.Diagnostics;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Headless;
using Avalonia.Headless.XUnit;
using Avalonia.Threading;
using Ngeoltx.App;
using Ngeoltx.Engine;
using Xunit;
using static Ngeoltx.Tests.Fixtures;

[assembly: AvaloniaTestApplication(typeof(Ngeoltx.Tests.HeadlessApp))]

namespace Ngeoltx.Tests;

/// <summary>Boots the real application without a display.</summary>
public static class HeadlessApp
{
    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<Ngeoltx.App.App>()
                  .UseHeadless(new AvaloniaHeadlessPlatformOptions())
                  .LogToTrace();
}

/// <summary>
/// The window, rendered headlessly.
/// </summary>
/// <remarks>
/// Bindings, converters and resource lookups are resolved at runtime, so a
/// window that compiles can still throw the moment it opens or leave a control
/// silently blank. These tests open it for real and fail on any binding error
/// Avalonia reports.
/// </remarks>
public class WindowTests
{
    /// <summary>Collects Avalonia's trace output so a binding error can fail a test.</summary>
    private sealed class TraceCapture : TraceListener
    {
        private readonly List<string> _lines = new();

        public TraceCapture() => Trace.Listeners.Add(this);

        public override void Write(string? message) => Append(message);
        public override void WriteLine(string? message) => Append(message);

        private void Append(string? message)
        {
            if (!string.IsNullOrWhiteSpace(message)) _lines.Add(message);
        }

        public IReadOnlyList<string> Problems => _lines
            .Where(l => l.Contains("Error", StringComparison.OrdinalIgnoreCase)
                     || l.Contains("Unable to find", StringComparison.OrdinalIgnoreCase)
                     || l.Contains("Could not convert", StringComparison.OrdinalIgnoreCase))
            .ToList();

        protected override void Dispose(bool disposing)
        {
            if (disposing) Trace.Listeners.Remove(this);
            base.Dispose(disposing);
        }
    }

    /// <summary>
    /// A station with history disabled.
    /// </summary>
    /// <remarks>
    /// Otherwise every run of the suite leaves a database file in whatever
    /// directory the tests happened to start in.
    /// </remarks>
    private static Station NewStation() =>
        new(Options.Parse(new[] { "--history", "", "--simulate" })!);

    [AvaloniaFact]
    public void WindowOpensWithoutBindingErrors()
    {
        using var capture = new TraceCapture();
        var station = NewStation();

        var window = new MainWindow(station);
        window.Show();
        Dispatcher.UIThread.RunJobs();

        Assert.Empty(capture.Problems);
        window.Close();
        station.Dispose();
    }

    /// <summary>
    /// No unit panels appear before a program says how many units exist.
    /// </summary>
    /// <remarks>
    /// An empty panel claims a unit is present and untested, which is a
    /// different statement from "nothing is loaded".
    /// </remarks>
    [AvaloniaFact]
    public void NoUnitPanelsBeforeAProgramIsLoaded()
    {
        var station = NewStation();
        var window = new MainWindow(station);
        window.Show();
        Dispatcher.UIThread.RunJobs();

        Assert.Empty(station.Units);
        Assert.False(station.HasUnits);
        Assert.False(station.CanRun);

        window.Close();
        station.Dispose();
    }

    [AvaloniaFact]
    public void LoadingAProgramSizesThePanelsFromInitAlive()
    {
        using var capture = new TraceCapture();
        var path = TempFile(".yaml");
        File.WriteAllText(path, """
            config:
              - [TestData, INITDATA, "10", "10", "4"]
              - [TestData, initAlive, "3"]
            exec:
              - [FlowManager, LABEL, START]
            teardown:
              - [FlowManager, LABEL, DONE]
            """);

        var station = NewStation();
        var window = new MainWindow(station);
        window.Show();

        station.Load(path);
        Dispatcher.UIThread.RunJobs();

        Assert.Equal(3, station.Units.Count);
        Assert.Equal("UUT 1", station.Units[0].Title);
        Assert.True(station.CanRun);
        Assert.Empty(capture.Problems);

        window.Close();
        station.Dispose();
        File.Delete(path);
    }

    /// <summary>A result grid event paints the matching unit's panel.</summary>
    [AvaloniaFact]
    public void GridEventsLandOnTheRightUnit()
    {
        var station = NewStation();
        var window = new MainWindow(station);
        window.Show();

        // Grid 2 is UUT index 1: the evaluators publish kill_index + 1.
        station.Emit(new GridEvent(2, "add",
            new[] { "VBAT", "2", "13.0", "14.0", "13.5", "PASS" }, "PASS"));
        Dispatcher.UIThread.RunJobs();

        Assert.Equal(2, station.Units.Count);
        Assert.Empty(station.Units[0].Rows);

        var row = Assert.Single(station.Units[1].Rows);
        Assert.Equal("VBAT", row.Name);
        Assert.Equal("13.5", row.Measured);
        Assert.Equal("13.0 .. 14.0", row.Limits);
        Assert.False(row.IsFail);

        window.Close();
        station.Dispose();
    }

    /// <summary>
    /// The nine-column grid shape reads its limits from the right places.
    /// </summary>
    /// <remarks>
    /// Two shapes are in use, and the only fields at fixed positions are the
    /// name at the front and the verdict at the back.
    /// </remarks>
    [AvaloniaFact]
    public void TheWideGridShapeIsReadCorrectly()
    {
        var row = ResultRow.FromGrid(new[]
        {
            "AREA", "1", "500", "-", "900", "612", "-", "-", "FAIL",
        });

        Assert.Equal("AREA", row.Name);
        Assert.Equal("500", row.Low);
        Assert.Equal("900", row.High);
        Assert.Equal("612", row.Measured);
        Assert.True(row.IsFail);
    }

    [AvaloniaFact]
    public void AKilledUnitShowsAsFailed()
    {
        var station = NewStation();
        var window = new MainWindow(station);
        window.Show();

        station.Emit(new AliveEvent(new[] { 1, 0 }));
        Dispatcher.UIThread.RunJobs();

        Assert.Equal("READY", station.Units[0].State);
        Assert.Equal("FAILED", station.Units[1].State);
        Assert.True(station.Units[1].IsFailed);

        window.Close();
        station.Dispose();
    }

    [AvaloniaFact]
    public void SwitchingToStatisticsRendersWithoutErrors()
    {
        using var capture = new TraceCapture();
        var station = NewStation();
        var window = new MainWindow(station);
        window.Show();

        var tabs = window.FindControl<TabControl>("Pages");
        Assert.NotNull(tabs);
        tabs!.SelectedIndex = 1;
        Dispatcher.UIThread.RunJobs();

        Assert.Empty(capture.Problems);
        window.Close();
        station.Dispose();
    }
}
