using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Runtime.CompilerServices;

namespace Ngeoltx.App;

/// <summary>Minimal change notification, so no MVVM framework is needed.</summary>
public abstract class Notifier : INotifyPropertyChanged
{
    public event PropertyChangedEventHandler? PropertyChanged;

    protected void Raise([CallerMemberName] string? name = null) =>
        PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));

    protected bool Set<T>(ref T field, T value, [CallerMemberName] string? name = null)
    {
        if (EqualityComparer<T>.Default.Equals(field, value)) return false;
        field = value;
        Raise(name);
        return true;
    }
}

/// <summary>
/// One judged measurement, as the operator sees it.
/// </summary>
/// <remarks>
/// Built from a <c>GridEvent</c>, whose value list varies in length because
/// different evaluators publish different shapes. Mapping happens once, in
/// <see cref="FromGrid"/>, rather than in each verb.
/// </remarks>
public sealed class ResultRow
{
    public required string Name { get; init; }
    public string Low { get; init; } = "";
    public string High { get; init; } = "";
    public string Measured { get; init; } = "";
    public required string Result { get; init; }

    public bool IsFail => Result.Equals("FAIL", StringComparison.OrdinalIgnoreCase);
    public string Limits =>
        Low.Length == 0 && High.Length == 0 ? "" :
        High.Length == 0 || High == "-" ? Low :
        Low.Length == 0 || Low == "-" ? High : Low + " .. " + High;

    /// <summary>
    /// Interpret a grid event's values.
    /// </summary>
    /// <remarks>
    /// Two shapes are in use, both inherited from v1 tables:
    /// six columns (name, device, low, high, measured, result) and nine
    /// (name, device, low, -, high, measured, -, -, result). The name is always
    /// first and the verdict always last, so anything else is read relative to
    /// those two rather than by trusting a fixed index.
    /// </remarks>
    public static ResultRow FromGrid(IReadOnlyList<string> values)
    {
        string At(int index) => index >= 0 && index < values.Count ? values[index] : "";

        var name = At(0);
        var result = values.Count > 0 ? values[^1] : "";
        return values.Count switch
        {
            >= 9 => new ResultRow
            {
                Name = name, Low = At(2), High = At(4), Measured = At(5), Result = result,
            },
            >= 6 => new ResultRow
            {
                Name = name, Low = At(2), High = At(3), Measured = At(4), Result = result,
            },
            // An unexpected shape still shows the reading rather than a blank
            // row -- an operator staring at an empty cell learns nothing.
            _ => new ResultRow
            {
                Name = name, Measured = values.Count > 1 ? values[^2] : "", Result = result,
            },
        };
    }
}

/// <summary>One unit under test: its panel, its results, its verdict.</summary>
public sealed class UnitPanel : Notifier
{
    private bool _alive = true;
    private string _barcode = "";
    private int _failures;

    public UnitPanel(int index) => Index = index;

    public int Index { get; }
    public string Title => "UUT " + (Index + 1);

    public ObservableCollection<ResultRow> Rows { get; } = new();

    public bool Alive
    {
        get => _alive;
        set { if (Set(ref _alive, value)) { Raise(nameof(State)); Raise(nameof(IsFailed)); } }
    }

    public string Barcode
    {
        get => _barcode;
        set => Set(ref _barcode, value);
    }

    public int Failures
    {
        get => _failures;
        private set { if (Set(ref _failures, value)) Raise(nameof(Summary)); }
    }

    public bool IsFailed => !_alive;

    /// <summary>Headline word on the panel: what the operator reads first.</summary>
    public string State => _alive ? (Rows.Count == 0 ? "READY" : "TESTING") : "FAILED";

    public string Summary => Rows.Count + " test" + (Rows.Count == 1 ? "" : "s")
                             + (Failures > 0 ? ", " + Failures + " failed" : "");

    public void Add(ResultRow row)
    {
        Rows.Add(row);
        if (row.IsFail) Failures++;
        Raise(nameof(State));
        Raise(nameof(Summary));
    }

    public void Clear()
    {
        Rows.Clear();
        Failures = 0;
        Alive = true;
        Raise(nameof(State));
        Raise(nameof(Summary));
    }
}

/// <summary>A line in the operator log, coloured by severity.</summary>
public sealed class LogLine
{
    public required string Time { get; init; }
    public required string Text { get; init; }
    public required string Level { get; init; }

    public static LogLine Create(string text, string level) => new()
    {
        Time = DateTime.Now.ToString("HH:mm:ss"),
        Text = text,
        Level = level,
    };
}
