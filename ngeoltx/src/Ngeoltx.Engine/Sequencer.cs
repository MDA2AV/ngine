using System.Diagnostics;

namespace Ngeoltx.Engine;

public sealed class RunOptions
{
    public bool Simulate { get; init; }

    /// <summary>
    /// Refuse to start when validation reports errors. Turning this off is for
    /// bench debugging only; the UI never does.
    /// </summary>
    public bool Strict { get; init; } = true;

    public int MaxParallel { get; init; } = 8;
    public string Operator { get; init; } = "";
    public string Station { get; init; } = "";
    public string WorkDir { get; init; } = ".";

    /// <summary>Emit a progress update at most this often, to keep the UI cheap.</summary>
    public TimeSpan ProgressInterval { get; init; } = TimeSpan.FromMilliseconds(100);
}

/// <summary>
/// The run loop.
/// </summary>
/// <remarks>
/// Differences from v1 that matter:
/// <list type="number">
/// <item>It runs on a worker thread, not on the UI's event loop. Blocking driver
/// calls therefore cannot freeze the display -- which is what actually made v1
/// feel broken during every serial read.</item>
/// <item>Teardown is guaranteed. v1 ended a failed run with <c>break</c>, leaving
/// supplies energised and relays closed until the <em>next</em> run's opening
/// rows happened to reset them. Here it executes in a finally.</item>
/// <item>Parallel blocks are real. v1 gathered coroutines that performed blocking
/// I/O, so "parallel" steps ran strictly one after another.</item>
/// <item>Errors carry a routing label as a property rather than being packed into
/// the message string and split back out.</item>
/// </list>
/// </remarks>
public sealed class Sequencer
{
    public const string ParallelOpen = "<ParallelTask>";
    public const string ParallelClose = "<ParallelTask/>";

    /// <summary>
    /// Label a failure falls back to when its row names no handler.
    /// </summary>
    /// <remarks>
    /// Established by v1's tables, which put it in an Ehandling block alongside
    /// the per-subsystem handlers. Most rows leave column 7 empty on purpose.
    /// </remarks>
    public const string DefaultRoute = "STD_EX";

    private readonly VerbRegistry _registry;
    private readonly IEngineListener _listener;
    private readonly RunOptions _options;
    private CancellationTokenSource _stop = new();
    private long _lastProgressTicks;

    public Sequencer(VerbRegistry? registry = null, IEngineListener? listener = null,
                     RunOptions? options = null)
    {
        _registry = registry ?? VerbRegistry.Default;
        _listener = listener ?? NullListener.Instance;
        _options = options ?? new RunOptions();
    }

    public bool Running { get; private set; }

    /// <summary>Ask the run to wind up. Teardown still executes.</summary>
    public void Stop() => _stop.Cancel();

    public RunRecord Run(TestProgram program, RunContext? context = null)
    {
        _stop = new CancellationTokenSource();
        Running = true;

        var ctx = context ?? new RunContext(program, _listener, _options.Simulate,
                                            _options.WorkDir);
        ctx.StopToken = _stop.Token;

        var record = new RunRecord
        {
            ProgramName = program.Meta.TryGetValue("name", out var name) ? name : program.Source,
            Operator = _options.Operator,
            Station = _options.Station,
            Simulated = _options.Simulate,
        };
        ctx.Record = record;

        var aborted = false;
        var reason = "";
        try
        {
            Emit(new RunStateEvent("validating"));
            var report = Validator.Validate(program, _registry);
            foreach (var diagnostic in report)
                ctx.Log(diagnostic.ToString(), diagnostic.IsError ? "error" : "warn");
            if (_options.Strict && !report.Ok)
                throw new AbortRunException(
                    "program failed validation: " + report.Summary()
                    + " -- nothing was executed");

            Emit(new RunStateEvent("running"));
            if (program.SectionOrNull("Config") is not null)
                RunSection(ctx, program, "Config");
            RunExec(ctx, program);
        }
        catch (AbortRunException exc)
        {
            aborted = true;
            reason = exc.Message;
            ctx.Log(exc.Message, "error");
        }
        catch (NgeoltxException exc)
        {
            aborted = true;
            reason = exc.ToString();
            ctx.Log("Run aborted: " + exc, "error");
        }
        catch (Exception exc)
        {
            aborted = true;
            reason = "internal error: " + exc.Message;
            ctx.Log("Run aborted, internal error: " + exc, "error");
        }
        finally
        {
            RunTeardown(ctx, program);
            record.Finish(ctx.Alive, aborted, reason);
            Running = false;
            Emit(new RunStateEvent("idle"));
            Emit(new ResultEvent(
                !aborted && record.Passed(),
                record.Uuts().ToDictionary(u => u, u => record.Passed(u)),
                reason));
        }
        return record;
    }

    // -- sections ---------------------------------------------------------

    private void RunSection(RunContext ctx, TestProgram program, string name)
    {
        var section = program.SectionOrNull(name);
        if (section is null) return;
        ctx.Log("--- " + name + " ---");

        foreach (var index in section.Body)
        {
            if (index >= program.Rows.Count) break;
            if (_stop.IsCancellationRequested && name != "Teardown")
                throw new AbortRunException("stopped by operator");

            var row = program.Rows[index];
            ctx.Pointer = index;
            if (Skippable(row)) continue;
            Dispatch(ctx, row);
            ctx.TakeJump();          // jumps are meaningless outside Exec
        }
    }

    /// <summary>
    /// Always-run safe-state block.
    /// </summary>
    /// <remarks>
    /// Deliberately tolerant: a teardown step that fails must not stop the
    /// remaining steps, or one stuck relay would leave the supply on. Failures
    /// are logged and recorded, never re-thrown.
    /// </remarks>
    private void RunTeardown(RunContext ctx, TestProgram program)
    {
        var section = program.SectionOrNull("Teardown");
        if (section is null) return;

        Emit(new RunStateEvent("teardown"));
        ctx.Log("--- Teardown ---");
        foreach (var index in section.Body)
        {
            if (index >= program.Rows.Count) break;
            var row = program.Rows[index];
            ctx.Pointer = index;
            if (Skippable(row)) continue;
            try { Dispatch(ctx, row); }
            catch (Exception exc)
            {
                ctx.Log("Teardown step failed (continuing): " + exc.Message, "error");
            }
            finally { ctx.TakeJump(); }
        }
    }

    private void RunExec(RunContext ctx, TestProgram program)
    {
        var section = program.SectionOrNull("Exec")
                      ?? throw new ProgramException("program has no <Exec> section");

        var end = Math.Min(program.ExecEnd, program.Rows.Count);
        var (spanStart, spanEnd) = program.Span;
        var span = Math.Max(spanEnd - spanStart, 1);

        ctx.Pointer = section.Start + 1;
        while (ctx.Pointer < end)
        {
            if (_stop.IsCancellationRequested)
                throw new AbortRunException("stopped by operator");

            var row = program.Rows[ctx.Pointer];
            ReportProgress(ctx, spanStart, span);

            // Loud, because it is silent data loss: v1 raised KeyError on
            // globals[""] and diverted to the row's handler, so the step never
            // ran and nobody noticed.
            if (row.Verb.Length > 0 && row.Module.Length == 0)
            {
                ctx.Log(row.Index + "- '" + row.Verb
                        + "' has no module in column 0 -- step skipped", "warn");
                ctx.Pointer++;
                continue;
            }

            if (Skippable(row)) { ctx.Pointer++; continue; }

            if (row.Module == ParallelOpen)
            {
                ctx.Pointer = RunParallel(ctx, program, ctx.Pointer, end);
                continue;
            }
            if (row.Module == ParallelClose) { ctx.Pointer++; continue; }

            if (!ctx.IsAnyAlive(row.Alive))
            {
                RecordSkip(ctx, row, "no live UUT in mask '" + row.Alive + "'");
                ctx.Pointer++;
                continue;
            }

            try
            {
                Dispatch(ctx, row);
            }
            catch (NgeoltxException exc)
            {
                var target = Route(ctx, exc, row);
                if (target is null) throw;
                ctx.Pointer = program.LabelIndex(target);
                continue;
            }

            var jump = ctx.TakeJump();
            if (jump is not null) { ctx.Pointer = program.LabelIndex(jump); continue; }
            ctx.Pointer++;
        }
        ctx.Progress(1.0);
    }

    // -- dispatch ---------------------------------------------------------

    private void Dispatch(RunContext ctx, Row row)
    {
        var module = ctx.Program.Modules.TryGetValue(row.Module, out var mapped)
            ? mapped : row.Module;
        var spec = _registry.Require(module, row.Verb, row.Index);

        Emit(new StepEvent(row.Index, row.ToString(), row.Comment));
        var started = DateTime.Now;
        var watch = Stopwatch.StartNew();
        var outcome = "ok";
        var detail = "";

        try
        {
            spec.Handler(ctx, row);
        }
        catch (NgeoltxException exc)
        {
            exc.WithContext(row.Route, row.Index);
            outcome = "failed";
            detail = exc.ToString();
            throw;
        }
        catch (Exception exc)
        {
            outcome = "failed";
            detail = exc.GetType().Name + ": " + exc.Message;
            // Wrap, preserving the original as InnerException so the stack
            // survives -- the thing v1's string-formatted exceptions destroyed.
            throw new VerbException(row.Module + "." + row.Verb + ": " + detail,
                                    row.Route, row.Index, exc);
        }
        finally
        {
            ctx.Record.AddStep(new StepRecord(
                row.Index, row.Module, row.Verb, row.Args, row.Comment,
                started, Math.Round(watch.Elapsed.TotalSeconds, 4), outcome, detail));
        }
    }

    /// <summary>
    /// Decide where a failure goes.
    /// </summary>
    /// <remarks>
    /// A ProgramException is never routable: a malformed program must stop, not
    /// limp along on its own error handlers.
    /// </remarks>
    private static string? Route(RunContext ctx, NgeoltxException exc, Row row)
    {
        if (exc is ProgramException)
        {
            ctx.Log("Program error: " + exc, "error");
            return null;
        }

        var target = exc.Route ?? row.Route;
        if (target is null && ctx.Program.Labels.ContainsKey(DefaultRoute))
            target = DefaultRoute;

        if (target is null)
        {
            ctx.Log("Unhandled failure: " + exc, "error");
            return null;
        }
        if (!ctx.Program.Labels.ContainsKey(target))
        {
            // v1 left the pointer untouched here, which re-executed the failing
            // row forever. Aborting is the honest outcome.
            ctx.Log("Failure routed to '" + target + "', which is not a label: " + exc,
                    "error");
            return null;
        }

        ctx.Log(exc + " -> jumping to " + target, "warn");
        ctx.Record.MarkLastRouted();
        return target;
    }

    // -- parallel ---------------------------------------------------------

    private int RunParallel(RunContext ctx, TestProgram program, int start, int end)
    {
        var rows = new List<Row>();
        var i = start + 1;
        while (i < end && program.Rows[i].Module != ParallelClose)
        {
            if (!Skippable(program.Rows[i])) rows.Add(program.Rows[i]);
            i++;
        }
        if (i >= end)
            throw new ProgramException("<ParallelTask> is never closed", start);

        var runnable = new List<Row>();
        foreach (var row in rows)
        {
            if (ctx.IsAnyAlive(row.Alive)) runnable.Add(row);
            else RecordSkip(ctx, row, "no live UUT in mask '" + row.Alive + "'");
        }
        if (runnable.Count == 0) return i + 1;

        ctx.Log("Parallel block: " + runnable.Count + " task(s)");
        var errors = new List<NgeoltxException>();
        var gate = new Lock();

        Parallel.ForEach(runnable,
            new ParallelOptions { MaxDegreeOfParallelism = Math.Max(1, _options.MaxParallel) },
            row =>
            {
                try
                {
                    Dispatch(ctx, row);
                }
                catch (NgeoltxException exc)
                {
                    ctx.Log("Parallel task failed: " + exc, "error");
                    lock (gate) errors.Add(exc);
                }
                catch (Exception exc)
                {
                    lock (gate) errors.Add(new VerbException(exc.Message, row.Route, row.Index));
                }
                finally
                {
                    // A jump requested inside a parallel block has no defined
                    // ordering, so it is dropped rather than silently racing.
                    if (ctx.TakeJump() is { } dropped)
                        ctx.Log("Ignoring jump to '" + dropped
                                + "' requested inside a parallel block (row "
                                + row.Index + ")", "warn");
                }
            });

        if (errors.Count > 0) throw errors[0];
        return i + 1;
    }

    // -- helpers ----------------------------------------------------------

    internal static bool Skippable(Row row)
    {
        var module = row.Module;
        // Parallel markers carry no verb but are handled by the exec loop.
        if (module == ParallelOpen || module == ParallelClose) return false;
        if (row.IsBlank) return true;
        if (module.Length == 0 || module == "-") return true;
        if (module.StartsWith("<")) return true;
        return row.Verb.Length == 0;
    }

    private static void RecordSkip(RunContext ctx, Row row, string why)
    {
        ctx.Log(row.Index + "- skipped: " + why);
        ctx.Record.AddStep(new StepRecord(
            row.Index, row.Module, row.Verb, row.Args, row.Comment,
            DateTime.Now, 0.0, "skipped", why));
    }

    private void ReportProgress(RunContext ctx, int spanStart, int span)
    {
        var now = Stopwatch.GetTimestamp();
        var elapsed = TimeSpan.FromSeconds(
            (now - _lastProgressTicks) / (double)Stopwatch.Frequency);
        if (elapsed < _options.ProgressInterval) return;
        _lastProgressTicks = now;

        var value = (ctx.Pointer - spanStart) / (double)span;
        if (value is >= 0.0 and <= 1.0) Emit(new ProgressEvent(value));
    }

    private void Emit(IEngineEvent e) => _listener.Emit(e);
}
