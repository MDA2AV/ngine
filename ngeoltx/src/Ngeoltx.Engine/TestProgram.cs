namespace Ngeoltx.Engine;

/// <summary>
/// One instruction. Ten columns, inherited from the v1 spreadsheet layout.
/// </summary>
public sealed class Row
{
    public const int Columns = 10;
    public const int ArgStart = 2;
    public const int ArgEnd = 6;
    private const int ColModule = 0, ColVerb = 1, ColRoute = 7, ColAlive = 8, ColComment = 9;

    public Row(int index, IEnumerable<string> cells, int? sourceLine = null)
    {
        Index = index;
        var list = cells.Select(c => c ?? "").ToList();
        while (list.Count < Columns) list.Add("");
        Cells = list.Take(Columns).ToArray();
        SourceLine = sourceLine;
    }

    public int Index { get; }
    public string[] Cells { get; }
    public int? SourceLine { get; }

    public string Module => Cells[ColModule].Trim();
    public string Verb => Cells[ColVerb].Trim();

    /// <summary>Exception label from column 7, or null when blank.</summary>
    public string? Route
    {
        get
        {
            var v = Cells[ColRoute].Trim();
            return v.Length == 0 || v == "-" ? null : v;
        }
    }

    /// <summary>UUT mask from column 8. A dash means run regardless.</summary>
    public string Alive
    {
        get
        {
            var v = Cells[ColAlive].Trim();
            return v.Length == 0 ? "-" : v;
        }
    }

    public string Comment => Cells[ColComment].Trim();

    public string Raw(int index) =>
        index < 0 || index >= Cells.Length ? "" : Cells[index].Trim();

    /// <summary>True when the column holds something other than a placeholder.</summary>
    public bool Has(int index)
    {
        var v = Raw(index);
        return v.Length > 0 && v != "-";
    }

    public IReadOnlyList<string> Args =>
        Enumerable.Range(ArgStart, ArgEnd - ArgStart + 1).Select(Raw).ToList();

    public bool IsBlank => Cells.All(string.IsNullOrWhiteSpace);

    public bool IsMarker => Module.StartsWith("<") && Module.EndsWith(">");

    public override string ToString()
    {
        var parts = new[] { Module, Verb }.Concat(Args).Where(s => s.Length > 0);
        return "[" + Index + "] " + string.Join(" ", parts);
    }
}

public sealed record Section(string Name, int Start, int End)
{
    /// <summary>Row indices between the markers.</summary>
    public IEnumerable<int> Body =>
        Enumerable.Range(Start + 1, Math.Max(End - Start - 1, 0));
}

/// <summary>
/// A parsed, structurally validated test program.
/// </summary>
/// <remarks>
/// Keeps v1's shape -- a flat list of rows, one instruction each -- because
/// that shape is right for the domain: a test engineer reads a sequence top to
/// bottom, and nesting would not help. What changes is that the structure is
/// parsed once, up front, rather than rediscovered by scanning for marker
/// strings on every run.
/// </remarks>
public sealed class TestProgram
{
    /// <summary>
    /// Recognised section markers. Vars and Teardown are new; Ehandling is read
    /// because real v1 tables already put their handler labels there, after the
    /// closing Exec marker.
    /// </summary>
    public static readonly string[] SectionNames =
        { "Modules", "Vars", "Config", "Exec", "Ehandling", "Teardown" };

    /// <summary>Sections whose rows are declarations, not instructions.</summary>
    private static readonly string[] Declarative = { "Modules", "Vars" };

    public List<Row> Rows { get; } = new();
    public Dictionary<string, string> Modules { get; } = new();
    public Dictionary<string, string> Vars { get; } = new();
    public Dictionary<string, Section> Sections { get; } = new();
    public Dictionary<string, int> Labels { get; } = new();
    public Dictionary<string, string> Meta { get; } = new();
    public string Source { get; set; } = "";

    public Section? SectionOrNull(string name) =>
        Sections.TryGetValue(name, out var s) ? s : null;

    public int ExecStart
    {
        get
        {
            var exec = SectionOrNull("Exec")
                       ?? throw new ProgramException("program has no <Exec> section");
            return exec.Start + 1;
        }
    }

    /// <summary>
    /// One past the last row a jump may land on.
    /// </summary>
    /// <remarks>
    /// Everything from Exec to Teardown is reachable, because Ehandling lives
    /// past the closing Exec marker and its labels are jump targets. v1 had no
    /// upper bound at all and ran off the end of the table into an IndexError.
    /// </remarks>
    public int ExecEnd
    {
        get
        {
            var teardown = SectionOrNull("Teardown");
            return teardown is not null && teardown.Start > ExecStart
                ? teardown.Start
                : Rows.Count;
        }
    }

    public bool HasTeardown => Sections.ContainsKey("Teardown");

    public bool InDeclarativeSection(int index) =>
        Declarative.Any(name => Sections.TryGetValue(name, out var s)
                                && index >= s.Start && index <= s.End);

    public int LabelIndex(string name) =>
        Labels.TryGetValue(name, out var i)
            ? i
            : throw new ProgramException("jump to undefined label '" + name + "'");

    /// <summary>(START, END) indices, used for the progress bar.</summary>
    public (int Start, int End) Span
    {
        get
        {
            if (Labels.TryGetValue("START", out var start)
                && Labels.TryGetValue("END", out var end) && end > start)
                return (start, end);
            var exec = SectionOrNull("Exec");
            return exec is not null
                ? (exec.Start + 1, exec.End)
                : (0, Math.Max(Rows.Count - 1, 1));
        }
    }

    // -- construction ----------------------------------------------------

    public TestProgram Finalise()
    {
        ParseSections();
        ParseModules();
        ParseVars();
        BuildLabels();
        return this;
    }

    private void ParseSections()
    {
        var open = new Dictionary<string, int>();
        foreach (var row in Rows)
        {
            var token = row.Module;
            if (!token.StartsWith("<") || !token.EndsWith(">")) continue;

            var inner = token.Substring(1, token.Length - 2);
            var closing = inner.EndsWith("/");
            var name = closing ? inner[..^1] : inner;
            if (!SectionNames.Contains(name)) continue;

            if (closing)
            {
                if (!open.Remove(name, out var start))
                    throw new ProgramException(
                        "<" + name + "/> closes a section that was never opened",
                        row.Index);
                Sections[name] = new Section(name, start, row.Index);
            }
            else
            {
                if (open.ContainsKey(name))
                    throw new ProgramException("<" + name + "> opened twice", row.Index);
                open[name] = row.Index;
            }
        }

        // Exec conventionally has no closing marker in v1 tables: it simply runs
        // to the end of the sheet. Accept that, bounded by Teardown if present.
        foreach (var pair in open)
        {
            var end = Rows.Count;
            if (pair.Key == "Exec" && Sections.TryGetValue("Teardown", out var td)
                && td.Start > pair.Value)
                end = td.Start;
            Sections[pair.Key] = new Section(pair.Key, pair.Value, end);
        }
    }

    private void ParseModules()
    {
        var section = SectionOrNull("Modules");
        if (section is null) return;
        foreach (var i in section.Body)
        {
            if (i >= Rows.Count) break;
            var row = Rows[i];
            if (row.IsBlank || row.Module.Length == 0) continue;
            if (row.Verb.Length == 0)
                throw new ProgramException(
                    "module alias '" + row.Module + "' has no target module", row.Index);
            Modules[row.Module] = row.Verb;
        }
    }

    /// <summary>
    /// Read Vars: friendly name to l,c,p coordinate.
    /// </summary>
    /// <remarks>
    /// The readability fix for data[39][0][29]. Purely additive: a program with
    /// no Vars section behaves exactly as it did in v1.
    /// </remarks>
    private void ParseVars()
    {
        var section = SectionOrNull("Vars");
        if (section is null) return;
        foreach (var i in section.Body)
        {
            if (i >= Rows.Count) break;
            var row = Rows[i];
            if (row.IsBlank || row.Module.Length == 0) continue;
            if (row.Verb.Length == 0)
                throw new ProgramException(
                    "variable '" + row.Module + "' has no coordinate", row.Index);
            if (row.Module.StartsWith("*"))
                throw new ProgramException(
                    "variable name '" + row.Module + "' must not start with '*'",
                    row.Index);
            Vars[row.Module] = row.Verb;
        }
    }

    /// <summary>
    /// Index every LABEL row.
    /// </summary>
    /// <remarks>
    /// Matched on column 1 regardless of module, preserving v1 behaviour:
    /// existing tables call it as "Flow LABEL" and occasionally with a blank
    /// module.
    /// </remarks>
    public void BuildLabels()
    {
        Labels.Clear();
        foreach (var row in Rows)
        {
            if (row.Verb != "LABEL" || !row.Has(2)) continue;
            var name = row.Raw(2);
            if (Labels.TryGetValue(name, out var first))
                throw new ProgramException(
                    "duplicate label '" + name + "' at rows " + first + " and " + row.Index,
                    row.Index);
            Labels[name] = row.Index;
        }
    }
}
