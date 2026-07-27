using System.Diagnostics;
using System.Globalization;
using Ngeoltx.Engine;

namespace Ngeoltx.Drivers;

/// <summary>
/// External process verbs, registered as WinShellManager.
/// </summary>
/// <remarks>
/// v1 had seven functions (BLOCK, BLOCKSH, BLOCKSHT, BLOCKT, BLOCK2, NONBLOCK,
/// ASYNC) covering two switches: run through a shell or not, and wait or not.
/// They are registered here from one implementation.
///
/// Two v1 behaviours are deliberately not carried over:
/// <list type="bullet">
/// <item>Running a command assembled from spreadsheet cells <em>through a
/// shell</em>. A test table is data, and handing it to a shell means any cell
/// can become a command. The *SH aliases still exist so tables keep loading, but
/// they launch the argument list directly. Set "allow_shell" in the driver state
/// if a program genuinely needs shell metacharacters.</item>
/// <item><c>os.system("pkill adb")</c> at import time.</item>
/// </list>
/// </remarks>
public static class ShellVerbs
{
    public const string Module = "WinShellManager";
    private const string State = "shell";

    private static readonly Param[] Params =
    {
        new(2, "command", true, "comma-separated argv"),
        new(3, "stdout_index", false),
        new(4, "stderr_index", false),
        new(5, "exitcode_index", false),
        new(6, "timeout", false, "seconds[,handler]"),
    };

    public static void RegisterProcesses(VerbRegistry registry)
    {
        foreach (var (name, wait, useShell) in new (string, bool, bool)[]
        {
            ("BLOCK", true, false), ("BLOCK2", true, false), ("BLOCKT", true, false),
            ("BLOCKSH", true, true), ("BLOCKSHT", true, true),
            ("NONBLOCK", false, false), ("ASYNC", false, false),
        })
        {
            var (shouldWait, shell) = (wait, useShell);
            registry.Add(new VerbSpec
            {
                Module = Module,
                Name = name,
                Handler = (ctx, row) => Run(ctx, row, shouldWait, shell),
                Params = Params,
                Legacy = true,
                Doc = shouldWait
                    ? "Run a command and wait for it."
                    : "Start a command without waiting.",
            });
        }
    }

    private static void Run(RunContext ctx, Row row, bool wait, bool useShell)
    {
        var argv = ctx.Text(row.Raw(2)).Split(',', StringSplitOptions.RemoveEmptyEntries)
                      .Select(a => a.Trim()).Where(a => a.Length > 0).ToList();
        if (argv.Count == 0) throw new VerbException(row.Verb + ": no command given");

        var allowShell = ctx.DriverState(State).TryGetValue("allow_shell", out var flag)
                         && flag is true;
        if (useShell && !allowShell)
            ctx.Log("shell: launching argv directly rather than through a shell "
                    + "(set allow_shell to override)", "warn");

        double? timeout = null;
        if (row.Has(6))
        {
            var head = ctx.Text(row.Raw(6)).Split(',')[0].Trim();
            if (!double.TryParse(head, NumberStyles.Float, CultureInfo.InvariantCulture,
                                 out var seconds))
                throw new VerbException(row.Verb + ": '" + row.Raw(6)
                    + "' is not 'timeout[,handler]'");
            timeout = seconds;
        }

        var info = new ProcessStartInfo
        {
            FileName = argv[0],
            UseShellExecute = false,
            RedirectStandardOutput = wait,
            RedirectStandardError = wait,
            CreateNoWindow = true,
        };
        foreach (var argument in argv.Skip(1)) info.ArgumentList.Add(argument);

        ctx.Log("shell: " + string.Join(" ", argv));
        Process? process;
        try { process = Process.Start(info); }
        catch (Exception exc)
        {
            throw new VerbException(row.Verb + ": cannot start '" + argv[0] + "': "
                + exc.Message, inner: exc);
        }
        if (process is null)
            throw new VerbException(row.Verb + ": '" + argv[0] + "' did not start");

        if (!wait) return;

        // Read both pipes before waiting: a process that fills its stdout buffer
        // blocks forever if nobody is draining it, and then the timeout below
        // fires on a command that was working fine.
        var stdout = process.StandardOutput.ReadToEndAsync();
        var stderr = process.StandardError.ReadToEndAsync();

        var finished = timeout is null
            ? Wait(process, ctx)
            : process.WaitForExit((int)(timeout.Value * 1000));
        if (!finished)
        {
            try { process.Kill(true); } catch { /* already gone */ }
            throw new VerbException(row.Verb + ": '" + string.Join(" ", argv)
                + "' did not finish within " + timeout + "s");
        }

        Store(ctx, row, 3, stdout.GetAwaiter().GetResult());
        Store(ctx, row, 4, stderr.GetAwaiter().GetResult());
        Store(ctx, row, 5, process.ExitCode);

        if (process.ExitCode != 0)
        {
            var detail = stderr.GetAwaiter().GetResult().Trim();
            ctx.Log("shell: exit " + process.ExitCode
                    + (detail.Length > 0
                        ? ": " + detail[..Math.Min(detail.Length, 200)] : ""), "warn");
        }
    }

    /// <summary>Wait without a timeout, but still notice an operator stop.</summary>
    private static bool Wait(Process process, RunContext ctx)
    {
        while (!process.WaitForExit(100))
            if (ctx.StopToken.IsCancellationRequested)
            {
                try { process.Kill(true); } catch { /* already gone */ }
                return true;
            }
        return true;
    }

    private static void Store(RunContext ctx, Row row, int column, object value)
    {
        if (row.Has(column)) ctx.SetData(row.Raw(column), value);
    }
}
