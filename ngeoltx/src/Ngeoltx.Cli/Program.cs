using Ngeoltx.Drivers;
using Ngeoltx.Engine;
using Ngeoltx.Engine.Loaders;

namespace Ngeoltx.Cli;

/// <summary>
/// Headless companion to the desktop station.
/// </summary>
/// <remarks>
/// Everything here is scriptable, which is what makes a test program reviewable
/// like code: `check` in a pull request, `run --simulate` in CI, `convert` to
/// diff a spreadsheet as text. v1 had no entry point but the GUI, so a table
/// could only be verified by energising a fixture and watching.
/// </remarks>
public static class Program
{
    private const string Usage = """
        ngeoltx-cli <command> [options]

          run <program>        execute a program without a UI
            --simulate           use simulated hardware
            --no-strict          run even if validation reports errors (bench only)
            --report PATH        write a report (.xml / .json / .csv)
            --history PATH       record the run in this history database
            --quiet              only print the verdict
          check <program>      validate without executing
            --warnings-as-errors
          convert <in> <out>   .ods / .csv / .txt / .yaml, any direction
          verbs                list every registered verb
            --module NAME        one module only
          stats                summarise the run history
            --history PATH       database to read (default ngeoltx-history.db)
            --include-simulated
            --search TEXT        list matching points

        Exit codes: 0 pass, 1 fail or invalid, 2 bad usage.
        """;

    public static int Main(string[] args)
    {
        Catalog.Register();

        if (args.Length == 0) { Console.WriteLine(Usage); return 0; }
        var rest = args.Skip(1).ToArray();

        try
        {
            return args[0] switch
            {
                "run" => Run(rest),
                "check" => Check(rest),
                "convert" => Convert(rest),
                "verbs" => Verbs(rest),
                "stats" => Stats(rest),
                "--help" or "-h" or "help" => Print(Usage),
                _ => Fail("unknown command '" + args[0] + "'"),
            };
        }
        catch (NgeoltxException exc)
        {
            Console.Error.WriteLine("ngeoltx: " + exc);
            return 1;
        }
        catch (ArgumentException exc)
        {
            return Fail(exc.Message);
        }
    }

    private static int Print(string text) { Console.WriteLine(text); return 0; }

    private static int Fail(string message)
    {
        Console.Error.WriteLine("ngeoltx: " + message);
        Console.Error.WriteLine();
        Console.Error.WriteLine(Usage);
        return 2;
    }

    // -- run -------------------------------------------------------------------

    private static int Run(string[] args)
    {
        var options = Flags.Parse(args, "run");
        var path = options.Positional(0, "program");

        var program = ProgramLoader.Load(path);
        var listener = new ConsoleListener(options.Has("--quiet"));
        var sequencer = new Sequencer(VerbRegistry.Default, listener, new RunOptions
        {
            Simulate = options.Has("--simulate"),
            Strict = !options.Has("--no-strict"),
            Station = Environment.MachineName,
            WorkDir = Path.GetDirectoryName(Path.GetFullPath(path)) ?? ".",
        });

        // Ctrl+C must wind the fixture down rather than abandon it energised.
        Console.CancelKeyPress += (_, e) =>
        {
            e.Cancel = true;
            Console.Error.WriteLine("Stopping — teardown will still run.");
            sequencer.Stop();
        };

        var record = sequencer.Run(program);
        var summary = record.Summary();

        if (options.Value("--report") is { Length: > 0 } report)
        {
            var extension = Path.GetExtension(report).TrimStart('.').ToLowerInvariant();
            Reports.Write(record, report, extension.Length > 0 ? extension : "json");
            Console.WriteLine("Report written to " + report);
        }

        if (options.Value("--history") is { Length: > 0 } dbPath)
        {
            using var history = new RunHistory(dbPath);
            if (history.AddRun(record) is null)
                Console.Error.WriteLine("History not written: "
                    + (history.Error ?? "unknown error"));
        }

        Console.WriteLine();
        Console.WriteLine((record.Passed() ? "PASS" : "FAIL")
            + "  ·  " + summary.Points + " point(s), " + summary.FailedPoints + " failed"
            + "  ·  " + summary.DurationSeconds.ToString("0.0") + " s");
        // Zero-based, matching the log and the alive-mask column a table author
        // writes. Only the operator's panels count from one.
        foreach (var (uut, passed) in summary.PerUut.OrderBy(p => p.Key))
            Console.WriteLine("  UUT " + uut + ": " + (passed ? "PASS" : "FAIL"));
        if (summary.Aborted) Console.WriteLine("  Aborted: " + summary.AbortReason);

        return record.Passed() ? 0 : 1;
    }

    // -- check ------------------------------------------------------------------

    private static int Check(string[] args)
    {
        var options = Flags.Parse(args, "check");
        var program = ProgramLoader.Load(options.Positional(0, "program"));
        var report = Validator.Validate(program, VerbRegistry.Default);

        foreach (var diagnostic in report)
        {
            Console.WriteLine(diagnostic.Severity.ToUpperInvariant() + " " + diagnostic);
            if (diagnostic.Detail.Length > 0) Console.WriteLine("        " + diagnostic.Detail);
        }
        Console.WriteLine(report.Summary());

        var strict = options.Has("--warnings-as-errors");
        return report.Ok && (!strict || report.Warnings.Count == 0) ? 0 : 1;
    }

    // -- convert -----------------------------------------------------------------

    private static int Convert(string[] args)
    {
        var options = Flags.Parse(args, "convert");
        var source = options.Positional(0, "source");
        var destination = options.Positional(1, "destination");

        var program = ProgramLoader.Load(source);
        ProgramLoader.Save(program, destination);
        Console.WriteLine(source + " -> " + destination + " (" + program.Rows.Count + " rows)");
        return 0;
    }

    // -- verbs --------------------------------------------------------------------

    private static int Verbs(string[] args)
    {
        var options = Flags.Parse(args, "verbs");
        var only = options.Value("--module");

        foreach (var module in VerbRegistry.Default.Modules())
        {
            if (only is { Length: > 0 } && !module.Equals(only, StringComparison.OrdinalIgnoreCase))
                continue;
            var names = VerbRegistry.Default.VerbsFor(module);
            Console.WriteLine(module + "  (" + names.Count + ")");
            foreach (var name in names)
            {
                var spec = VerbRegistry.Default.Lookup(module, name);
                var arguments = spec is null || spec.Params.Count == 0
                    ? ""
                    : "  " + string.Join(" ", spec.Params.Select(p =>
                        p.Required ? p.Name : "[" + p.Name + "]"));
                Console.WriteLine("    " + name.PadRight(24) + arguments
                    + (spec?.Legacy == true ? "   (legacy)" : ""));
            }
        }
        Console.WriteLine();
        Console.WriteLine(VerbRegistry.Default.Count + " verbs in "
            + VerbRegistry.Default.Modules().Count + " modules.");
        return 0;
    }

    // -- stats ---------------------------------------------------------------------

    private static int Stats(string[] args)
    {
        var options = Flags.Parse(args, "stats");
        var path = options.Value("--history") ?? RunHistory.DefaultPath;
        var includeSimulated = options.Has("--include-simulated");

        using var history = new RunHistory(path);
        if (!history.Available)
        {
            Console.Error.WriteLine("Cannot open '" + path + "': " + history.Error);
            return 1;
        }

        var summary = history.Summary(includeSimulated: includeSimulated);
        Console.WriteLine("History: " + path
            + (includeSimulated ? "  (including simulated runs)" : ""));
        Console.WriteLine("  runs              " + summary.Runs);
        Console.WriteLine("  units tested      " + summary.Units);
        // Units, not points: one board failing one of forty tests is one reject.
        Console.WriteLine("  first-pass yield  "
            + (summary.Units == 0 ? "--" : summary.YieldPercent.ToString("0.0") + "%"));
        Console.WriteLine("  test points       " + summary.Points
            + " (" + summary.Failed + " failed)");
        Console.WriteLine("  aborted runs      " + summary.Aborted);

        var pareto = history.Pareto(includeSimulated: includeSimulated);
        if (pareto.Count > 0)
        {
            var total = pareto.Sum(p => (double)p.Failures);
            var cumulative = 0.0;
            Console.WriteLine();
            Console.WriteLine("Failures by test:");
            foreach (var entry in pareto)
            {
                var share = 100.0 * entry.Failures / total;
                cumulative += share;
                Console.WriteLine("  " + entry.Name.PadRight(28)
                    + entry.Failures.ToString().PadLeft(6)
                    + share.ToString("0.0").PadLeft(8) + "%"
                    + cumulative.ToString("0.0").PadLeft(9) + "% cumulative"
                    + "   (" + entry.FailRate.ToString("0.0") + "% of "
                    + entry.Attempts + " attempts)");
            }
        }

        if (options.Value("--search") is { } text)
        {
            var rows = history.Search(text, includeSimulated: includeSimulated, limit: 50);
            Console.WriteLine();
            Console.WriteLine("Matching points (" + rows.Count + "):");
            foreach (var row in rows)
                Console.WriteLine("  " + row.Started + "  " + row.Name.PadRight(24)
                    + " UUT " + row.Uut + "  " + row.Result.PadRight(5)
                    + " " + row.Measured
                    + (row.Barcode.Length > 0 ? "   " + row.Barcode : ""));
        }
        return 0;
    }
}

/// <summary>A very small flag parser: enough for six subcommands.</summary>
internal sealed class Flags
{
    private readonly List<string> _positional = new();
    private readonly Dictionary<string, string?> _options = new(StringComparer.Ordinal);
    private readonly string _command;

    private Flags(string command) => _command = command;

    /// <summary>Options that take a value; everything else is a switch.</summary>
    private static readonly HashSet<string> Valued = new()
    {
        "--report", "--history", "--module", "--search",
    };

    public static Flags Parse(string[] args, string command)
    {
        var flags = new Flags(command);
        for (var i = 0; i < args.Length; i++)
        {
            var argument = args[i];
            if (!argument.StartsWith("--")) { flags._positional.Add(argument); continue; }

            if (Valued.Contains(argument))
            {
                if (i + 1 >= args.Length)
                    throw new ArgumentException(argument + " needs a value");
                flags._options[argument] = args[++i];
            }
            else flags._options[argument] = null;
        }
        return flags;
    }

    public bool Has(string name) => _options.ContainsKey(name);

    public string? Value(string name) =>
        _options.TryGetValue(name, out var value) ? value : null;

    public string Positional(int index, string name) =>
        index < _positional.Count
            ? _positional[index]
            : throw new ArgumentException(_command + " needs a " + name);
}

/// <summary>
/// Prints engine events as they happen.
/// </summary>
/// <remarks>
/// Grid rows are printed too, because in a headless run they are the only place
/// a measurement appears at all.
/// </remarks>
internal sealed class ConsoleListener : IEngineListener
{
    private readonly bool _quiet;

    public ConsoleListener(bool quiet) => _quiet = quiet;

    public void Emit(IEngineEvent e)
    {
        switch (e)
        {
            case LogEvent log when !_quiet || log.Level is "error" or "fail":
                Console.WriteLine(Tag(log.Level) + log.Message);
                break;

            case GridEvent { Op: "add", Values: { Count: > 0 } values } grid when !_quiet:
                Console.WriteLine("  [UUT " + grid.Grid + "] " + string.Join("  ", values));
                break;

            case RunStateEvent state when !_quiet:
                Console.WriteLine("-- " + state.State + " --");
                break;
        }
    }

    private static string Tag(string level) => level switch
    {
        "error" => "ERROR  ",
        "fail" => "FAIL   ",
        "warn" => "WARN   ",
        "pass" => "PASS   ",
        _ => "       ",
    };
}
