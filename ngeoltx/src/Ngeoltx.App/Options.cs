using Ngeoltx.Engine;

namespace Ngeoltx.App;

/// <summary>Command line for the operator station.</summary>
public sealed class Options
{
    public string? Program { get; private set; }
    public bool Simulate { get; private set; }
    public string Station { get; private set; } = Environment.MachineName;
    public string Operator { get; private set; } = "";
    public string HistoryPath { get; private set; } = RunHistory.DefaultPath;
    public bool Light { get; private set; }

    public const string Usage = """
        ngeoltx [program] [options]

          program            test program to load (.ods, .csv, .txt, .yaml)
          --simulate         run against simulated hardware
          --station NAME     station id recorded with every run
          --operator NAME    operator id recorded with every run
          --history PATH     run-history database (empty string disables it)
          --light            light theme (default follows the system)
          --help             this text
        """;

    public static Options? Parse(string[] args)
    {
        var options = new Options();
        for (var i = 0; i < args.Length; i++)
        {
            var argument = args[i];
            string Next(string name) => i + 1 < args.Length
                ? args[++i]
                : throw new ArgumentException(name + " needs a value");

            switch (argument)
            {
                case "--help" or "-h" or "/?": return null;
                case "--simulate": options.Simulate = true; break;
                case "--light": options.Light = true; break;
                case "--station": options.Station = Next("--station"); break;
                case "--operator": options.Operator = Next("--operator"); break;
                case "--history": options.HistoryPath = Next("--history"); break;
                default:
                    if (argument.StartsWith("-"))
                        throw new ArgumentException("unknown option " + argument);
                    options.Program = argument;
                    break;
            }
        }
        return options;
    }
}
