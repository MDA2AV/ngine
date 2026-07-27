using Ngeoltx.Engine;
using Xunit;
using static Ngeoltx.Tests.Fixtures;

namespace Ngeoltx.Tests;

/// <summary>
/// The run loop, including the four v1 behaviours the rewrite exists to fix.
/// </summary>
public class SequencerTests
{
    private static TestProgram Minimal(params string[][] execRows)
    {
        var rows = new List<string[]>
        {
            R("<Config>"),
            R("TestData", "INITDATA", "10", "10", "4"),
            R("TestData", "initAlive", "2"),
            R("<Config/>"),
            R("<Exec>"),
        };
        rows.AddRange(execRows);
        rows.Add(R("<Exec/>"));
        return Program(rows.ToArray());
    }

    [Fact]
    public void RunsConfigThenExec()
    {
        var (record, _) = Run(Minimal(R("FlowManager", "STORE", "hello", "0,0,0")));

        Assert.Contains(record.Steps, s => s.Verb == "INITDATA");
        Assert.Contains(record.Steps, s => s.Verb == "STORE" && s.Outcome == "ok");
    }

    /// <summary>
    /// v1 ended a failed run with <c>break</c>, leaving the supply energised
    /// until the next run's opening rows happened to reset it.
    /// </summary>
    [Fact]
    public void TeardownRunsAfterAFailure()
    {
        var program = Program(
            R("<Config>"),
            R("TestData", "INITDATA", "10", "10", "4"),
            R("TestData", "initAlive", "2"),
            R("<Config/>"),
            R("<Exec>"),
            R("FlowManager", "DIV", "0,0,0", "1", "0"),        // division by zero
            R("<Exec/>"),
            R("<Teardown>"),
            R("FlowManager", "STORE", "safe", "0,1,0"),
            R("<Teardown/>"));

        var (record, _) = Run(program);

        var teardown = record.Steps.Single(s => s.Verb == "STORE");
        Assert.Equal("ok", teardown.Outcome);
        Assert.Contains(record.Steps, s => s.Verb == "DIV" && s.Outcome == "failed");
    }

    /// <summary>A teardown step that itself fails must not stop the rest of it.</summary>
    [Fact]
    public void TeardownContinuesPastItsOwnFailures()
    {
        var program = Program(
            R("<Config>"),
            R("TestData", "INITDATA", "10", "10", "4"),
            R("<Config/>"),
            R("<Exec>"),
            R("<Exec/>"),
            R("<Teardown>"),
            R("FlowManager", "DIV", "0,0,0", "1", "0"),
            R("FlowManager", "STORE", "reached", "0,1,0"),
            R("<Teardown/>"));

        var (record, _) = Run(program);

        Assert.Contains(record.Steps, s => s.Verb == "STORE" && s.Outcome == "ok");
    }

    /// <summary>
    /// A failure follows column 7, and lands on the label rather than aborting.
    /// </summary>
    [Fact]
    public void FailureRoutesToItsLabel()
    {
        var program = Program(
            R("<Config>"),
            R("TestData", "INITDATA", "10", "10", "4"),
            R("<Config/>"),
            R("<Exec>"),
            Guarded("FlowManager", "DIV", "HANDLER", "-", "0,0,0", "1", "0"),
            R("FlowManager", "STORE", "not-reached", "0,1,0"),
            R("FlowManager", "J", "DONE"),
            R("FlowManager", "LABEL", "HANDLER"),
            R("FlowManager", "STORE", "handled", "0,2,0"),
            R("FlowManager", "LABEL", "DONE"),
            R("<Exec/>"));

        var (record, _) = Run(program);

        var reached = record.Steps.Where(s => s.Verb == "STORE").ToList();
        Assert.Single(reached);
        Assert.Contains(record.Steps, s => s.Outcome == "routed");
    }

    /// <summary>
    /// A malformed program is never routed.
    /// </summary>
    /// <remarks>
    /// Letting a ProgramException follow an exception label is how v1 ran past
    /// real problems: the handler recovered, and the broken row stayed broken.
    /// </remarks>
    [Fact]
    public void ProgramErrorsAreNotRoutable()
    {
        var program = Program(
            R("<Config>"),
            R("TestData", "INITDATA", "2", "2", "1"),
            R("<Config/>"),
            R("<Exec>"),
            // 9,9,0 is outside the declared 2x2x1 store.
            Guarded("FlowManager", "STORE", "HANDLER", "-", "x", "9,9,0"),
            R("FlowManager", "LABEL", "HANDLER"),
            R("FlowManager", "STORE", "handled", "0,1,0"),
            R("<Exec/>"));

        var (record, _) = Run(program, strict: false);

        Assert.True(record.Aborted);
        Assert.DoesNotContain(record.Steps,
            s => s.Verb == "STORE" && s.Args[0] == "handled" && s.Outcome == "ok");
    }

    /// <summary>
    /// Parallel markers are dispatched by the exec loop, not skipped.
    /// </summary>
    /// <remarks>
    /// An earlier version treated any row with no verb as skippable, which
    /// silently swallowed the block markers so its contents ran sequentially --
    /// the same outcome as v1, whose "parallel" coroutines performed blocking
    /// I/O one after another.
    /// </remarks>
    [Fact]
    public void ParallelBlockRunsEveryTask()
    {
        var program = Program(
            R("<Config>"),
            R("TestData", "INITDATA", "10", "10", "4"),
            R("<Config/>"),
            R("<Exec>"),
            R("<ParallelTask>"),
            R("FlowManager", "STORE", "a", "0,0,0"),
            R("FlowManager", "STORE", "b", "0,1,0"),
            R("FlowManager", "STORE", "c", "0,2,0"),
            R("<ParallelTask/>"),
            R("<Exec/>"));

        var (record, _) = Run(program);

        Assert.Equal(3, record.Steps.Count(s => s.Verb == "STORE" && s.Outcome == "ok"));
    }

    [Fact]
    public void UnclosedParallelBlockFailsValidation()
    {
        var program = Program(
            R("<Exec>"),
            R("<ParallelTask>"),
            R("FlowManager", "STORE", "a", "0,0,0"),
            R("<Exec/>"));

        var report = Validator.Validate(program, VerbRegistry.Default);

        Assert.Contains(report.Errors, d => d.Message.Contains("never closed"));
    }

    /// <summary>A row whose mask names only dead units is skipped, not run.</summary>
    [Fact]
    public void AliveMaskSkipsDeadUnits()
    {
        var program = Program(
            R("<Config>"),
            R("TestData", "INITDATA", "10", "10", "4"),
            R("TestData", "initAlive", "2"),
            R("<Config/>"),
            R("<Exec>"),
            R("TestData", "AKILL", "1"),
            Guarded("FlowManager", "STORE", "", "1", "dead", "0,0,0"),
            Guarded("FlowManager", "STORE", "", "0", "alive", "0,1,0"),
            R("<Exec/>"));

        var (record, _) = Run(program);

        var steps = record.Steps.Where(s => s.Verb == "STORE").ToList();
        Assert.Equal("skipped", steps[0].Outcome);
        Assert.Equal("ok", steps[1].Outcome);
    }

    /// <summary>
    /// A leading dash means "all of these", not "any of these".
    /// </summary>
    [Fact]
    public void AliveMaskLeadingDashMeansAllOf()
    {
        var program = Program(
            R("<Config>"),
            R("TestData", "INITDATA", "10", "10", "4"),
            R("TestData", "initAlive", "3"),
            R("<Config/>"),
            R("<Exec>"),
            R("TestData", "AKILL", "2"),
            Guarded("FlowManager", "STORE", "", "-,0,2", "all", "0,0,0"),
            Guarded("FlowManager", "STORE", "", "0,2", "any", "0,1,0"),
            R("<Exec/>"));

        var (record, _) = Run(program);

        var steps = record.Steps.Where(s => s.Verb == "STORE").ToList();
        Assert.Equal("skipped", steps[0].Outcome);   // 2 is dead, so not "all of"
        Assert.Equal("ok", steps[1].Outcome);        // 0 is alive, so "any of" holds
    }

    /// <summary>
    /// Ehandling sits past the closing Exec marker in real v1 tables, so its
    /// labels have to stay reachable.
    /// </summary>
    [Fact]
    public void EhandlingAfterExecCloseIsReachable()
    {
        var program = Program(
            R("<Config>"),
            R("TestData", "INITDATA", "10", "10", "4"),
            R("<Config/>"),
            R("<Exec>"),
            R("FlowManager", "J", "STD_EX"),
            R("<Exec/>"),
            R("<Ehandling>"),
            R("FlowManager", "LABEL", "STD_EX"),
            R("FlowManager", "STORE", "handled", "0,0,0"),
            R("<Ehandling/>"),
            R("<Teardown>"),
            R("<Teardown/>"));

        var (record, _) = Run(program);

        Assert.Contains(record.Steps,
            s => s.Verb == "STORE" && s.Args[0] == "handled" && s.Outcome == "ok");
    }

    /// <summary>An unrouted failure with an STD_EX label present goes there.</summary>
    [Fact]
    public void UnroutedFailureFallsBackToStdEx()
    {
        var program = Program(
            R("<Config>"),
            R("TestData", "INITDATA", "10", "10", "4"),
            R("<Config/>"),
            R("<Exec>"),
            R("FlowManager", "DIV", "0,0,0", "1", "0"),
            R("<Exec/>"),
            R("<Ehandling>"),
            R("FlowManager", "LABEL", "STD_EX"),
            R("FlowManager", "STORE", "caught", "0,1,0"),
            R("<Ehandling/>"),
            R("<Teardown>"),
            R("<Teardown/>"));

        var (record, _) = Run(program);

        Assert.Contains(record.Steps,
            s => s.Verb == "STORE" && s.Args[0] == "caught" && s.Outcome == "ok");
    }

    /// <summary>A row with a verb but no module is skipped with a warning.</summary>
    [Fact]
    public void RowWithoutAModuleIsSkippedNotFatal()
    {
        var program = Program(
            R("<Config>"),
            R("TestData", "INITDATA", "10", "10", "4"),
            R("<Config/>"),
            R("<Exec>"),
            R("", "STORE", "orphan", "0,0,0"),
            R("FlowManager", "STORE", "after", "0,1,0"),
            R("<Exec/>"));

        var report = Validator.Validate(program, VerbRegistry.Default);
        var (record, events) = Run(program);

        Assert.Empty(report.Errors);
        Assert.Contains(report.Warnings, d => d.Message.Contains("no module"));
        Assert.Contains(record.Steps,
            s => s.Verb == "STORE" && s.Args[0] == "after" && s.Outcome == "ok");
        Assert.Contains(events.OfType<LogEvent>(), l => l.Message.Contains("step skipped"));
    }

    /// <summary>
    /// Strict mode refuses to execute anything when validation fails.
    /// </summary>
    /// <remarks>
    /// The point of the validator: an unknown verb should be caught while the
    /// fixture is cold, not at row 200 with the supply at 13.5 V.
    /// </remarks>
    [Fact]
    public void StrictModeExecutesNothingWhenValidationFails()
    {
        var program = Program(
            R("<Exec>"),
            R("FlowManager", "NOSUCHVERB", "x"),
            R("<Exec/>"));

        var (record, _) = Run(program);

        Assert.True(record.Aborted);
        Assert.Empty(record.Steps);
    }

    /// <summary>A run that judged nothing must not report a pass.</summary>
    [Fact]
    public void NoTestPointsMeansNoPass()
    {
        var (record, _) = Run(Minimal(R("FlowManager", "STORE", "x", "0,0,0")));

        Assert.False(record.Passed());
    }
}
