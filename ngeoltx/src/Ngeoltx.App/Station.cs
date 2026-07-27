using System.Collections.ObjectModel;
using System.Diagnostics;
using Avalonia.Threading;
using Ngeoltx.Engine;
using Ngeoltx.Engine.Loaders;

namespace Ngeoltx.App;

/// <summary>
/// The operator station: everything the window binds to.
/// </summary>
/// <remarks>
/// The engine runs on a worker thread and publishes plain records. This class is
/// the only place that knows about both, and it marshals every event onto the UI
/// thread before touching a bound collection.
///
/// That seam is the whole reason the display stays live during a run. v1 drove
/// Tk from the same loop that performed blocking serial reads, so the window
/// stopped repainting on every exchange -- which operators read, reasonably, as
/// the software having crashed.
/// </remarks>
public sealed class Station : Notifier, IEngineListener, IDisposable
{
    private readonly Options _options;
    private readonly DispatcherTimer _clock;
    private readonly Stopwatch _watch = new();
    private readonly List<long> _sessionRuns = new();

    private TestProgram? _program;
    private Sequencer? _sequencer;
    private Thread? _worker;
    private Stats? _statistics;

    private string _programName = "";
    private string _programPath = "";
    private string _state = "idle";
    private string _statusText = "Load a program to begin.";
    private string _statusKind = "idle";
    private string _elapsed = "0.0 s";
    private double _progress;
    private int _points;
    private int _failed;
    private bool _busy;
    private int _declaredUnits;

    public Station(Options options)
    {
        _options = options;
        Simulate = options.Simulate;
        History = options.HistoryPath.Length > 0 ? new RunHistory(options.HistoryPath) : null;

        _clock = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(200) };
        _clock.Tick += (_, _) => Elapsed = _watch.Elapsed.TotalSeconds.ToString("0.0") + " s";

        Units.CollectionChanged += (_, _) => Raise(nameof(HasUnits));

        if (History is { Available: false })
            Log("History disabled: " + History.Error, "warn");
        if (Simulate)
            Log("Simulation mode -- no hardware will be touched.", "warn");
        if (options.Program is { Length: > 0 } path) Load(path);
    }

    // -- state exposed to the window -----------------------------------------

    public bool Simulate { get; }
    public RunHistory? History { get; }
    public ObservableCollection<UnitPanel> Units { get; } = new();
    public ObservableCollection<LogLine> LogLines { get; } = new();

    /// <summary>Runs recorded since the application started, for session stats.</summary>
    public IReadOnlyList<long> SessionRuns => _sessionRuns;

    /// <summary>
    /// The statistics page's view model, reached through the station.
    /// </summary>
    /// <remarks>
    /// Exposed as a property so the markup can say
    /// <c>DataContext="{Binding Statistics}"</c>. Assigning it in code-behind
    /// does not work: a TabItem's content is not realised until its tab is
    /// selected, so there is nothing to assign to at construction, and the page
    /// would render once against the wrong context first.
    /// </remarks>
    public Stats Statistics => _statistics ??= new Stats(this);

    public string ProgramName
    {
        get => _programName;
        private set { if (Set(ref _programName, value)) Raise(nameof(Title)); }
    }

    public string ProgramPath
    {
        get => _programPath;
        private set => Set(ref _programPath, value);
    }

    public string Title => "NGEOLTX" + (ProgramName.Length > 0 ? "  ·  " + ProgramName : "")
                           + (Simulate ? "  ·  SIMULATED" : "");

    /// <summary>idle | validating | running | stopping | teardown</summary>
    public string State
    {
        get => _state;
        private set
        {
            if (!Set(ref _state, value)) return;
            Raise(nameof(CanRun));
            Raise(nameof(CanStop));
            Raise(nameof(IsRunning));
        }
    }

    public string StatusText
    {
        get => _statusText;
        private set => Set(ref _statusText, value);
    }

    /// <summary>pass | fail | warn | idle -- picks the banner colour.</summary>
    public string StatusKind
    {
        get => _statusKind;
        private set => Set(ref _statusKind, value);
    }

    public string Elapsed
    {
        get => _elapsed;
        private set => Set(ref _elapsed, value);
    }

    public double Progress
    {
        get => _progress;
        private set => Set(ref _progress, value);
    }

    public int Points
    {
        get => _points;
        private set => Set(ref _points, value);
    }

    public int Failed
    {
        get => _failed;
        private set => Set(ref _failed, value);
    }

    public bool IsRunning => _busy;
    public bool CanRun => !_busy && _program is not null;
    public bool CanStop => _busy;

    /// <summary>
    /// False until a program says how many units this fixture holds.
    /// </summary>
    /// <remarks>
    /// The window shows a hint instead of panels while this is false. An empty
    /// panel implies a unit is present and untested, which is a different claim
    /// from "nothing is loaded" -- and the reason four phantom UUTs appeared
    /// before any program had been opened.
    /// </remarks>
    public bool HasUnits => Units.Count > 0;

    public event Action<RunRecord>? RunFinished;

    // -- loading --------------------------------------------------------------

    public void Load(string path)
    {
        if (_busy)
        {
            Log("Cannot load a program while a run is in progress.", "warn");
            return;
        }

        try
        {
            var program = ProgramLoader.Load(path);
            var report = Validator.Validate(program, VerbRegistry.Default);

            _program = program;
            ProgramPath = path;
            ProgramName = program.Meta.TryGetValue("name", out var name)
                ? name : Path.GetFileNameWithoutExtension(path);

            // Size the panels from what the program declares, so the window
            // shows the units this fixture actually holds rather than a fixed
            // four that may be wrong.
            _declaredUnits = Validator.DeclaredAliveSize(program) ?? 0;
            BuildUnits(_declaredUnits);

            Log("Loaded " + path + " (" + program.Rows.Count + " rows, "
                + program.Labels.Count + " labels).");
            foreach (var diagnostic in report)
                Log(diagnostic.ToString(), diagnostic.IsError ? "error" : "warn");

            if (report.Ok)
            {
                Status(report.Summary() + (_declaredUnits > 0
                    ? "  ·  " + _declaredUnits + " unit(s)" : ""), "pass");
            }
            else
            {
                Status(report.Summary() + " -- fix these before running.", "fail");
            }
            Raise(nameof(CanRun));
        }
        catch (Exception exc)
        {
            _program = null;
            Log("Cannot load '" + path + "': " + exc.Message, "error");
            Status("Program failed to load.", "fail");
            Raise(nameof(CanRun));
        }
    }

    private void BuildUnits(int count)
    {
        Units.Clear();
        for (var i = 0; i < count; i++) Units.Add(new UnitPanel(i));
    }

    // -- running ---------------------------------------------------------------

    public void Start()
    {
        if (_program is null || _busy) return;

        foreach (var unit in Units) unit.Clear();
        Points = 0;
        Failed = 0;
        Progress = 0;
        _busy = true;
        State = "running";
        Raise(nameof(CanRun));
        Raise(nameof(CanStop));
        Raise(nameof(IsRunning));

        _watch.Restart();
        _clock.Start();
        Status("Running…", "idle");

        var options = new RunOptions
        {
            Simulate = Simulate,
            Station = _options.Station,
            Operator = _options.Operator,
            WorkDir = Path.GetDirectoryName(Path.GetFullPath(ProgramPath)) ?? ".",
        };
        var sequencer = new Sequencer(VerbRegistry.Default, this, options);
        _sequencer = sequencer;

        var program = _program;
        _worker = new Thread(() =>
        {
            RunRecord? record = null;
            try { record = sequencer.Run(program); }
            catch (Exception exc)
            {
                Dispatcher.UIThread.Post(() => Log("Run crashed: " + exc.Message, "error"));
            }
            finally
            {
                Dispatcher.UIThread.Post(() => Finish(record));
            }
        })
        {
            IsBackground = true,
            Name = "ngeoltx-run",
        };
        _worker.Start();
    }

    public void Stop()
    {
        if (!_busy) return;
        State = "stopping";
        Status("Stopping — teardown will still run.", "warn");
        _sequencer?.Stop();
    }

    private void Finish(RunRecord? record)
    {
        _watch.Stop();
        _clock.Stop();
        Elapsed = _watch.Elapsed.TotalSeconds.ToString("0.0") + " s";
        _busy = false;
        State = "idle";
        Raise(nameof(CanRun));
        Raise(nameof(CanStop));
        Raise(nameof(IsRunning));
        Progress = 1;

        if (record is null) return;

        var id = History?.AddRun(record);
        if (id is not null) _sessionRuns.Add(id.Value);
        else if (History is { Available: true })
            Log("Run not stored in history: " + History.Error, "warn");

        RunFinished?.Invoke(record);
    }

    // -- engine events ----------------------------------------------------------

    /// <summary>
    /// Called from the engine thread.
    /// </summary>
    /// <remarks>
    /// Every mutation of a bound collection is posted to the UI thread. Posting
    /// rather than invoking keeps the engine from waiting on the renderer, which
    /// on a table that emits a few hundred grid rows a second is the difference
    /// between a run that takes 40 seconds and one that takes two minutes.
    /// </remarks>
    public void Emit(IEngineEvent e) => Dispatcher.UIThread.Post(() => Apply(e));

    private void Apply(IEngineEvent e)
    {
        switch (e)
        {
            case LogEvent log:
                Log(log.Message, log.Level);
                break;

            case StatusEvent status:
                Status(status.Text, status.Colour ?? "idle");
                break;

            case ProgressEvent progress:
                if (progress.Value >= 0) Progress = Math.Clamp(progress.Value, 0, 1);
                break;

            case AliveEvent alive:
                ApplyAlive(alive.Alive);
                break;

            case GridEvent grid:
                ApplyGrid(grid);
                break;

            case FieldEvent field:
                ApplyField(field);
                break;

            case RunStateEvent runState:
                State = runState.State;
                break;

            case ResultEvent result:
                Status(result.Passed ? "PASS" : "FAIL", result.Passed ? "pass" : "fail");
                if (result.Detail.Length > 0) Log(result.Detail, result.Passed ? "info" : "error");
                break;
        }
    }

    private void ApplyAlive(IReadOnlyList<int> alive)
    {
        // The program is the authority on how many units exist. A table that
        // never calls initAlive leaves the panel row empty rather than inventing
        // units nobody is testing.
        while (Units.Count < alive.Count) Units.Add(new UnitPanel(Units.Count));
        for (var i = 0; i < alive.Count && i < Units.Count; i++)
            Units[i].Alive = alive[i] != 0;
    }

    private void ApplyGrid(GridEvent grid)
    {
        // Grid n holds UUT n-1: the evaluators publish kill_index + 1.
        var index = grid.Grid - 1;
        if (index < 0) return;
        while (Units.Count <= index) Units.Add(new UnitPanel(Units.Count));
        var unit = Units[index];

        switch (grid.Op)
        {
            case "clear":
                unit.Clear();
                break;

            case "add" when grid.Values is { Count: > 0 }:
                var row = ResultRow.FromGrid(grid.Values);
                unit.Add(row);
                Points++;
                if (row.IsFail) Failed++;
                break;
        }
    }

    private void ApplyField(FieldEvent field)
    {
        switch (field.Name)
        {
            case "barcode1" or "barcode2":
                var slot = field.Name == "barcode1" ? 0 : 1;
                if (slot < Units.Count) Units[slot].Barcode = field.Value;
                break;

            case "log" when field.Colour == "clear":
                LogLines.Clear();
                break;
        }
    }

    // -- log ---------------------------------------------------------------------

    /// <summary>Cap on retained log lines; a long run emits tens of thousands.</summary>
    private const int LogLimit = 4000;

    public void Log(string message, string level = "info")
    {
        LogLines.Add(LogLine.Create(message, level));
        if (LogLines.Count > LogLimit) LogLines.RemoveAt(0);
    }

    private void Status(string text, string kind)
    {
        StatusText = text;
        StatusKind = kind;
    }

    public void Dispose()
    {
        _sequencer?.Stop();
        _clock.Stop();
        History?.Dispose();
    }
}
