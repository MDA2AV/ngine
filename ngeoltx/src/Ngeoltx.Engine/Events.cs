namespace Ngeoltx.Engine;

/// <summary>
/// Engine to UI channel.
/// </summary>
/// <remarks>
/// The engine never references a UI framework. It publishes records to an
/// <see cref="IEngineListener"/>, and the Avalonia layer adapts those onto the
/// dispatcher. That keeps the sequencer testable headlessly, and means the
/// engine thread never touches a control -- the actual root cause of v1's
/// frozen UI, where the Tk update loop and the test loop shared one event loop.
/// </remarks>
public interface IEngineEvent { }

public sealed record LogEvent(string Message, string Level = "info", int? Row = null)
    : IEngineEvent;

public sealed record StepEvent(int Row, string Text, string Comment = "")
    : IEngineEvent;

public sealed record StatusEvent(string Text, string? Colour = null) : IEngineEvent;

/// <param name="Value">0..1, or -1 for indeterminate.</param>
public sealed record ProgressEvent(double Value) : IEngineEvent;

public sealed record TimerEvent(double Seconds) : IEngineEvent;

/// <summary>A mutation of one result grid.</summary>
public sealed record GridEvent(
    int Grid,
    string Op,                                  // add | clear | place | config
    IReadOnlyList<string>? Values = null,
    string Tag = "",
    IReadOnlyDictionary<string, object>? Config = null) : IEngineEvent;

/// <summary>A named single-value UI field: barcode entries, counters.</summary>
public sealed record FieldEvent(string Name, string Value, string? Colour = null)
    : IEngineEvent;

public sealed record AliveEvent(IReadOnlyList<int> Alive) : IEngineEvent;

/// <param name="State">idle | validating | running | stopping | teardown</param>
public sealed record RunStateEvent(string State, string Detail = "") : IEngineEvent;

public sealed record ResultEvent(
    bool Passed,
    IReadOnlyDictionary<int, bool> PerUut,
    string Detail = "") : IEngineEvent;


public interface IEngineListener
{
    void Emit(IEngineEvent e);
}

/// <summary>Discards everything, so the engine can run truly headless.</summary>
public sealed class NullListener : IEngineListener
{
    public static readonly NullListener Instance = new();
    public void Emit(IEngineEvent e) { }
}

/// <summary>Keeps every event. Used by tests and the run recorder.</summary>
public sealed class RecordingListener : IEngineListener
{
    private readonly List<IEngineEvent> _events = new();
    private readonly Lock _gate = new();

    public void Emit(IEngineEvent e)
    {
        lock (_gate) _events.Add(e);
    }

    public IReadOnlyList<IEngineEvent> Events
    {
        get { lock (_gate) return _events.ToList(); }
    }

    public IEnumerable<T> OfType<T>() where T : IEngineEvent =>
        Events.OfType<T>();

    public void Clear()
    {
        lock (_gate) _events.Clear();
    }
}

/// <summary>Broadcasts to several listeners.</summary>
public sealed class FanOut : IEngineListener
{
    private readonly List<IEngineListener> _listeners;
    private readonly Lock _gate = new();

    public FanOut(params IEngineListener[] listeners) => _listeners = listeners.ToList();

    public void Add(IEngineListener listener)
    {
        lock (_gate) _listeners.Add(listener);
    }

    public void Emit(IEngineEvent e)
    {
        List<IEngineListener> targets;
        lock (_gate) targets = _listeners.ToList();
        foreach (var listener in targets)
        {
            // A misbehaving listener must never take down a run mid-fixture.
            try { listener.Emit(e); }
            catch { /* ignored on purpose */ }
        }
    }
}
