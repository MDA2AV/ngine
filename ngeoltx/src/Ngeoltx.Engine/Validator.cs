using System.Text.RegularExpressions;

namespace Ngeoltx.Engine;

public sealed record Diagnostic(string Severity, int? Row, string Message, string Detail = "")
{
    public const string Error = "error";
    public const string Warning = "warning";

    public bool IsError => Severity == Error;

    public override string ToString() =>
        (Row is null ? "program" : "row " + Row) + ": " + Message;
}

public sealed class ValidationReport : List<Diagnostic>
{
    public IReadOnlyList<Diagnostic> Errors => this.Where(d => d.IsError).ToList();
    public IReadOnlyList<Diagnostic> Warnings =>
        this.Where(d => d.Severity == Diagnostic.Warning).ToList();

    public bool Ok => Errors.Count == 0;

    public string Summary()
    {
        if (Ok && Warnings.Count == 0) return "Program valid.";
        var bits = new List<string>();
        if (Errors.Count > 0) bits.Add(Errors.Count + " error(s)");
        if (Warnings.Count > 0) bits.Add(Warnings.Count + " warning(s)");
        return string.Join(", ", bits);
    }
}

/// <summary>
/// Static checks run before a program is allowed to execute.
/// </summary>
/// <remarks>
/// The single highest-value addition over v1. There, a mistyped verb became an
/// AttributeError raised from getattr at row 200, with the supply already at
/// 13.5 V and relays closed. Everything checkable here is checked while the
/// fixture is still cold, and the UI refuses to arm Run until it is clean.
/// </remarks>
public static class Validator
{
    /// <summary>Verbs whose column-2 argument names a label.</summary>
    private static readonly HashSet<string> JumpVerbs = new()
    {
        "J", "JC", "JCM", "JNC", "JE", "JNE", "JET", "JNET", "JG", "JL", "JGE", "JLE",
    };

    private static readonly Regex ReferencePattern = new(@"^\*(.+)$", RegexOptions.Compiled);
    private static readonly Regex CoordPattern =
        new(@"^\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$", RegexOptions.Compiled);

    public static ValidationReport Validate(TestProgram program, VerbRegistry? registry = null)
    {
        registry ??= VerbRegistry.Default;
        var report = new ValidationReport();

        void Error(int? row, string message, string detail = "") =>
            report.Add(new Diagnostic(Diagnostic.Error, row, message, detail));
        void Warn(int? row, string message, string detail = "") =>
            report.Add(new Diagnostic(Diagnostic.Warning, row, message, detail));

        // -- structure ---------------------------------------------------
        if (program.SectionOrNull("Exec") is null)
            Error(null, "program has no <Exec> section -- nothing would run");
        if (program.Modules.Count == 0)
            Warn(null, "program declares no <Modules>; only built-in verbs will resolve");
        if (!program.HasTeardown)
            Warn(null, "program has no <Teardown> section",
                 "Without one, an aborted run leaves the fixture in whatever state it "
                 + "reached. Add <Teardown> to power down supplies and open relays.");

        // -- modules -----------------------------------------------------
        var knownModules = registry.Modules().ToHashSet();
        foreach (var (alias, target) in program.Modules)
            if (!knownModules.Contains(registry.ResolveModule(target)))
                Error(null,
                    "module alias '" + alias + "' -> '" + target
                    + "' is not a registered driver",
                    "Registered drivers: " + string.Join(", ", knownModules.OrderBy(m => m)));

        var aliveSize = DeclaredAliveSize(program);
        var dims = DeclaredDims(program);

        // -- rows --------------------------------------------------------
        foreach (var row in program.Rows)
        {
            if (row.IsBlank || row.IsMarker || row.Module == "-") continue;
            if (program.InDeclarativeSection(row.Index)) continue;

            if (row.Module.Length == 0)
            {
                // A warning, not an error: the row is skipped and the program
                // still loads. v1 raised KeyError on globals[""] and diverted to
                // the row's handler, so the step never ran there either --
                // blocking the load would be stricter than what this replaces.
                if (row.Verb.Length > 0)
                    Warn(row.Index,
                         "'" + row.Verb + "' has no module in column 0 -- row will be skipped",
                         "Fill in column 0 to make this step run. In v1 it raised KeyError "
                         + "and diverted to the row's exception handler, so it never "
                         + "executed there either.");
                continue;
            }

            var module = program.Modules.TryGetValue(row.Module, out var mapped)
                ? mapped : row.Module;
            var spec = registry.Lookup(module, row.Verb);
            if (spec is null)
            {
                if (!knownModules.Contains(registry.ResolveModule(module)))
                    Error(row.Index, "unknown module '" + row.Module + "'");
                else
                {
                    var near = VerbRegistry.Suggest(row.Verb, registry.VerbsFor(module));
                    Error(row.Index, "unknown verb " + row.Module + "." + row.Verb
                        + (near is null ? "" : " -- did you mean " + near + "?"));
                }
                continue;
            }

            foreach (var param in spec.Params.Where(p => p.Required))
                if (!row.Has(param.Index))
                    Error(row.Index,
                        row.Module + "." + row.Verb + ": missing required argument '"
                        + param.Name + "' (column " + param.Index + ")", param.Doc);

            // Arguments beyond what the verb declares are nearly always a
            // copy-paste slip from a neighbouring row.
            if (spec.Params.Count > 0)
                for (var i = Row.ArgStart; i <= Row.ArgEnd; i++)
                    if (row.Has(i) && spec.ParamAt(i) is null)
                        Warn(row.Index,
                            row.Module + "." + row.Verb + ": unexpected argument in column "
                            + i + " ('" + row.Raw(i) + "') -- this verb ignores it");

            if (JumpVerbs.Contains(row.Verb) && row.Has(2))
            {
                var target = row.Raw(2);
                if (!target.StartsWith("*") && !program.Labels.ContainsKey(target))
                {
                    var near = VerbRegistry.Suggest(target, program.Labels.Keys.ToList());
                    Error(row.Index, "jump to undefined label '" + target + "'"
                        + (near is null ? "" : " -- did you mean " + near + "?"));
                }
            }

            var route = row.Route;
            if (route is not null && !program.Labels.ContainsKey(route) && route != "STD_EX")
                Warn(row.Index,
                     "exception label '" + route + "' has no matching LABEL row",
                     "On failure the run will abort instead of recovering.");

            if (aliveSize is not null)
                foreach (var token in row.Alive.Split(',').Select(t => t.Trim()))
                {
                    if (token.Length == 0 || token == "-") continue;
                    if (!int.TryParse(token, out var index))
                        Error(row.Index, "bad alive mask entry '" + token + "'");
                    else if (index >= aliveSize)
                        Error(row.Index, "alive mask references UUT " + token
                            + " but initAlive declares " + aliveSize);
                }

            for (var i = Row.ArgStart; i <= Row.ArgEnd; i++)
            {
                var raw = row.Raw(i);
                var match = ReferencePattern.Match(raw);
                if (!match.Success) continue;

                var name = match.Groups[1].Value;
                var reference = program.Vars.TryGetValue(name, out var coord) ? coord : name;
                var parsed = CoordPattern.Match(reference);
                if (!parsed.Success)
                {
                    var near = VerbRegistry.Suggest(name, program.Vars.Keys.ToList());
                    Error(row.Index, "column " + i + ": '" + raw
                        + "' is neither an l,c,p coordinate nor a declared variable"
                        + (near is null ? "" : " -- did you mean *" + near + "?"));
                    continue;
                }
                if (dims is null) continue;
                var (l, c, p) = (int.Parse(parsed.Groups[1].Value),
                                 int.Parse(parsed.Groups[2].Value),
                                 int.Parse(parsed.Groups[3].Value));
                if (l >= dims.Value.Lines || c >= dims.Value.Cols || p >= dims.Value.Pages)
                    Error(row.Index, "column " + i + ": " + raw
                        + " is outside the data store declared by INITDATA ("
                        + dims.Value.Lines + "x" + dims.Value.Cols + "x"
                        + dims.Value.Pages + ")");
            }
        }

        CheckParallelBlocks(program, report);
        return report;
    }

    /// <summary>Every parallel block must be closed, and nesting is unsupported.</summary>
    private static void CheckParallelBlocks(TestProgram program, ValidationReport report)
    {
        int? openAt = null;
        foreach (var row in program.Rows)
        {
            var token = row.Module.Trim();
            if (token == Sequencer.ParallelOpen)
            {
                if (openAt is not null)
                    report.Add(new Diagnostic(Diagnostic.Error, row.Index,
                        "<ParallelTask> nested inside another parallel block",
                        "Outer block opened at row " + openAt + "."));
                openAt = row.Index;
            }
            else if (token == Sequencer.ParallelClose)
            {
                if (openAt is null)
                    report.Add(new Diagnostic(Diagnostic.Error, row.Index,
                        "<ParallelTask/> closes a block that was never opened"));
                openAt = null;
            }
        }
        if (openAt is not null)
            report.Add(new Diagnostic(Diagnostic.Error, openAt,
                "<ParallelTask> is never closed",
                "v1 would run off the end of the table here."));
    }

    public static int? DeclaredAliveSize(TestProgram program)
    {
        foreach (var row in program.Rows)
            if (row.Verb == "initAlive" && row.Has(2)
                && int.TryParse(row.Raw(2), out var count))
                return count;
        return null;
    }

    public static (int Lines, int Cols, int Pages)? DeclaredDims(TestProgram program)
    {
        foreach (var row in program.Rows)
        {
            if (row.Verb != "INITDATA") continue;
            if (int.TryParse(row.Raw(2), out var l) && int.TryParse(row.Raw(3), out var c)
                && int.TryParse(row.Raw(4), out var p))
                return (l, c, p);
        }
        return null;
    }
}
