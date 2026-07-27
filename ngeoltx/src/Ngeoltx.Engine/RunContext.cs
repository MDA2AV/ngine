using System.Globalization;
using System.Text.RegularExpressions;

namespace Ngeoltx.Engine;

/// <summary>
/// Everything a verb is handed, besides its own row.
/// </summary>
/// <remarks>
/// One instance per run. Drivers keep their state in <see cref="DriverState"/>
/// keyed by driver name rather than in statics -- v1 had 29 <c>global</c>
/// statements in TestData alone, which meant two runs could never be isolated
/// and nothing could be unit tested without restarting the process.
///
/// The data store keeps v1's <c>data[line][col][page]</c> shape and its
/// <c>*l,c,p</c> reference syntax, because existing tables are full of both.
/// What is added is a name layer: a Vars section maps friendly names onto
/// coordinates, so a new program says <c>*uut1.vbat</c> where an old one said
/// <c>*0,1,2</c>. Both resolve through the same accessor, so a table can mix
/// them while it is being migrated.
/// </remarks>
public sealed class RunContext
{
    private static readonly Regex CoordPattern =
        new(@"^\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$", RegexOptions.Compiled);

    private readonly Lock _gate = new();
    private readonly Dictionary<string, Dictionary<string, object?>> _driverState = new();

    public RunContext(TestProgram program, IEngineListener? listener = null,
                      bool simulate = false, string workDir = ".")
    {
        Program = program;
        Listener = listener ?? NullListener.Instance;
        Simulate = simulate;
        WorkDir = workDir;
    }

    public TestProgram Program { get; }
    public IEngineListener Listener { get; set; }
    public bool Simulate { get; }
    public string WorkDir { get; }

    /// <summary>Allocated by INITDATA, matching v1's lazy behaviour.</summary>
    public object?[,,]? Data { get; private set; }
    public (int Lines, int Cols, int Pages) Dims { get; private set; }

    public List<int> Alive { get; } = new();
    public int Pointer { get; set; }
    public bool LogEnabled { get; set; } = true;
    public RunRecord Record { get; set; } = new();

    /// <summary>Set by the sequencer when the operator asks to stop.</summary>
    public CancellationToken StopToken { get; set; } = CancellationToken.None;

    /// <summary>
    /// Label a verb has asked to jump to, consumed after the verb returns.
    /// </summary>
    /// <remarks>
    /// v1's jump() poked <c>pointer = index - 1</c> directly so the loop's
    /// unconditional increment landed on target: an off-by-one waiting to
    /// happen, and impossible from a worker thread. Requesting a jump and
    /// letting the loop own the pointer keeps control flow in one place.
    /// </remarks>
    public string? PendingJump { get; private set; }

    public string? DebugDirectory { get; set; }

    public DateTime? Datecode { get; private set; }
    public string ElapsedSource { get; set; } = "";

    // -- driver scratch ---------------------------------------------------

    public Dictionary<string, object?> DriverState(string name)
    {
        lock (_gate)
        {
            if (!_driverState.TryGetValue(name, out var state))
                _driverState[name] = state = new Dictionary<string, object?>();
            return state;
        }
    }

    // -- events -----------------------------------------------------------

    public void Emit(IEngineEvent e) => Listener.Emit(e);

    /// <summary>
    /// Operator-visible log line.
    /// </summary>
    /// <remarks>
    /// Honours LOG_FLAG, which v1 tables use to silence the noisy detection
    /// polling loop.
    /// </remarks>
    public void Log(string message, string level = "info")
    {
        if (!LogEnabled && level == "info") return;
        Emit(new LogEvent(message, level, Pointer));
    }

    public void Field(string name, string value, string? colour = null) =>
        Emit(new FieldEvent(name, value, colour));

    public void Progress(double value) => Emit(new ProgressEvent(value));

    // -- control flow ------------------------------------------------------

    /// <summary>Ask the sequencer to continue at a label after this verb returns.</summary>
    public void Jump(string label)
    {
        if (!Program.Labels.ContainsKey(label))
            throw new ProgramException("jump to undefined label '" + label + "'", Pointer);
        PendingJump = label;
    }

    public string? TakeJump()
    {
        var label = PendingJump;
        PendingJump = null;
        return label;
    }

    // -- data store --------------------------------------------------------

    public void InitData(int lines, int cols, int pages)
    {
        lock (_gate)
        {
            Dims = (lines, cols, pages);
            Data = new object?[lines, cols, pages];
        }
    }

    /// <summary>
    /// Turn a friendly variable name into an l,c,p coordinate.
    /// </summary>
    /// <remarks>
    /// Unknown names pass through untouched, so a literal like PASS is not
    /// mistaken for a variable.
    /// </remarks>
    public string ResolveName(string reference) =>
        Program.Vars.TryGetValue(reference, out var coord) ? coord : reference;

    public (int L, int C, int P) ParseCoord(string reference)
    {
        // A destination is conventionally written bare and a source with a
        // leading star. Accepting the star on both removes a whole class of
        // authoring slips at no cost: a destination cannot mean anything else.
        var trimmed = reference.Trim().TrimStart('*').Trim();
        var coord = ResolveName(trimmed);
        var match = CoordPattern.Match(coord);
        if (!match.Success)
        {
            var known = string.Join(", ", Program.Vars.Keys.OrderBy(k => k).Take(6));
            var hint = Program.Vars.Count > 0 ? " (known variables: " + known + ")" : "";
            throw new ProgramException(
                "bad data reference '" + reference + "'" + hint, Pointer);
        }
        return (int.Parse(match.Groups[1].Value), int.Parse(match.Groups[2].Value),
                int.Parse(match.Groups[3].Value));
    }

    public object? GetData(string reference)
    {
        if (Data is null)
            throw new VerbException("data store not initialised -- call INITDATA first");
        var (l, c, p) = ParseCoord(reference);
        GuardBounds(l, c, p);
        return Data[l, c, p];
    }

    public void SetData(string reference, object? value, bool stringify = true)
    {
        if (Data is null)
            throw new VerbException("data store not initialised -- call INITDATA first");
        var (l, c, p) = ParseCoord(reference);
        GuardBounds(l, c, p);
        Data[l, c, p] = stringify ? Stringify(value) : value;
    }

    private static string Stringify(object? value) => value switch
    {
        null => "",
        double d => d.ToString("0.######", CultureInfo.InvariantCulture),
        float f => f.ToString("0.######", CultureInfo.InvariantCulture),
        _ => value.ToString() ?? "",
    };

    private void GuardBounds(int l, int c, int p)
    {
        if (l < 0 || l >= Dims.Lines || c < 0 || c >= Dims.Cols
            || p < 0 || p >= Dims.Pages)
            throw new ProgramException(
                "data reference " + l + "," + c + "," + p
                + " is outside the allocated store "
                + Dims.Lines + "x" + Dims.Cols + "x" + Dims.Pages, Pointer);
    }

    /// <summary>
    /// Resolve one cell: a leading star dereferences, anything else is literal.
    /// </summary>
    public object? Content(string? value)
    {
        if (value is null) return "";
        var text = value.Trim();
        return text.StartsWith("*") ? GetData(text[1..]) : text;
    }

    /// <summary>Content coerced to a string, with null becoming empty.</summary>
    public string Text(string? value) => Content(value)?.ToString() ?? "";

    public double Number(string? value, string what)
    {
        var raw = Text(value).Trim();
        if (double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture,
                            out var result))
            return result;
        throw new VerbException(what + ": '" + raw + "' is not a number");
    }

    // -- alive mask ---------------------------------------------------------

    public void InitAlive(int count)
    {
        lock (_gate)
        {
            Alive.Clear();
            Alive.AddRange(Enumerable.Repeat(1, count));
        }
        Emit(new AliveEvent(Alive.ToList()));
    }

    public void StartAlive()
    {
        lock (_gate)
            for (var i = 0; i < Alive.Count; i++) Alive[i] = 1;
        Emit(new AliveEvent(Alive.ToList()));
    }

    public void Kill(int index, string reason = "")
    {
        bool already;
        lock (_gate)
        {
            if (index < 0 || index >= Alive.Count)
                throw new VerbException(
                    "cannot kill UUT " + index + ": alive mask holds "
                    + Alive.Count + " unit(s)");
            already = Alive[index] == 0;
            Alive[index] = 0;
        }
        if (already) return;
        Log("UUT " + index + " killed" + (reason.Length > 0 ? ": " + reason : ""), "fail");
        Emit(new AliveEvent(Alive.ToList()));
    }

    /// <summary>
    /// Evaluate column 8.
    /// </summary>
    /// <remarks>
    /// <list type="bullet">
    /// <item>"-" runs unconditionally.</item>
    /// <item>"0,2" runs if UUT 0 <b>or</b> 2 is still alive.</item>
    /// <item>"-,0,2" runs only if 0 <b>and</b> 2 are both alive.</item>
    /// </list>
    /// The leading-dash "all of" form is v1 behaviour, and several tables rely
    /// on it for steps that only make sense when a whole group survived.
    /// </remarks>
    public bool IsAnyAlive(string mask)
    {
        mask = (mask ?? "-").Trim();
        if (mask.Length == 0 || mask == "-") return true;

        var parts = mask.Split(',', StringSplitOptions.RemoveEmptyEntries)
                        .Select(p => p.Trim()).Where(p => p.Length > 0).ToList();
        if (parts.Count == 0) return true;

        int At(string token)
        {
            if (!int.TryParse(token, out var index))
                throw new ProgramException("bad alive mask entry '" + token + "'", Pointer);
            if (index < 0 || index >= Alive.Count)
                throw new ProgramException(
                    "alive mask references UUT " + index + " but only "
                    + Alive.Count + " are configured", Pointer);
            return Alive[index];
        }

        return parts[0] == "-"
            ? parts.Skip(1).All(t => At(t) == 1)
            : parts.Any(t => At(t) == 1);
    }

    public bool AnyAlive => Alive.Count == 0 || Alive.Any(a => a != 0);

    // -- datecodes ----------------------------------------------------------

    public (string Date, string Time) SetDatecodes(DateTime? now = null)
    {
        var stamp = now ?? DateTime.Now;
        Datecode = stamp;
        return ($"{stamp.Year}y_{stamp.Month}m_{stamp.Day}d",
                $"{stamp.Hour}h_{stamp.Minute}m_{stamp.Second}s");
    }
}
