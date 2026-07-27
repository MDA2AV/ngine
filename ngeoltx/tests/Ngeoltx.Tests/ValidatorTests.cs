using Ngeoltx.Engine;
using Xunit;
using static Ngeoltx.Tests.Fixtures;

namespace Ngeoltx.Tests;

/// <summary>
/// The pre-flight checks. Everything caught here is a failure v1 would only
/// have discovered with the fixture powered up.
/// </summary>
public class ValidatorTests
{
    private static ValidationReport Check(params string[][] rows) =>
        Validator.Validate(Program(rows), VerbRegistry.Default);

    [Fact]
    public void UnknownVerbIsAnErrorWithASuggestion()
    {
        var report = Check(
            R("<Exec>"),
            R("FlowManager", "STOER", "x", "0,0,0"),
            R("<Exec/>"));

        var error = Assert.Single(report.Errors);
        Assert.Contains("STOER", error.Message);
        Assert.Contains("did you mean STORE", error.Message);
    }

    [Fact]
    public void UnknownModuleIsAnError()
    {
        var report = Check(
            R("<Modules>"),
            R("Widget", "WidgetManager"),
            R("<Modules/>"),
            R("<Exec>"),
            R("<Exec/>"));

        Assert.Contains(report.Errors, d => d.Message.Contains("not a registered driver"));
    }

    [Fact]
    public void MissingRequiredArgumentNamesTheColumn()
    {
        var report = Check(
            R("<Exec>"),
            R("FlowManager", "STORE", "value"),          // no destination in column 3
            R("<Exec/>"));

        var error = Assert.Single(report.Errors);
        Assert.Contains("index", error.Message);
        Assert.Contains("column 3", error.Message);
    }

    [Fact]
    public void JumpToAnUndefinedLabelIsAnError()
    {
        var report = Check(
            R("<Exec>"),
            R("FlowManager", "J", "NOWHERE"),
            R("<Exec/>"));

        Assert.Contains(report.Errors, d => d.Message.Contains("undefined label"));
    }

    /// <summary>
    /// A reference outside the declared store is caught before it runs.
    /// </summary>
    [Fact]
    public void DataReferenceBeyondInitdataIsAnError()
    {
        var report = Check(
            R("<Config>"),
            R("TestData", "INITDATA", "4", "4", "1"),
            R("<Config/>"),
            R("<Exec>"),
            R("FlowManager", "COPY", "*9,0,0", "0,0,0"),
            R("<Exec/>"));

        Assert.Contains(report.Errors, d => d.Message.Contains("outside the data store"));
    }

    [Fact]
    public void UndeclaredVariableIsAnErrorWithASuggestion()
    {
        var report = Check(
            R("<Vars>"),
            R("vbat", "0,1,2"),
            R("<Vars/>"),
            R("<Config>"),
            R("TestData", "INITDATA", "4", "4", "4"),
            R("<Config/>"),
            R("<Exec>"),
            R("FlowManager", "COPY", "*vbatt", "0,0,0"),
            R("<Exec/>"));

        var error = report.Errors.Single(d => d.Message.Contains("vbatt"));
        Assert.Contains("did you mean *vbat", error.Message);
    }

    [Fact]
    public void AliveMaskBeyondInitAliveIsAnError()
    {
        var report = Check(
            R("<Config>"),
            R("TestData", "initAlive", "2"),
            R("<Config/>"),
            R("<Exec>"),
            Guarded("FlowManager", "STORE", "", "3", "x", "0,0,0"),
            R("<Exec/>"));

        Assert.Contains(report.Errors, d => d.Message.Contains("alive mask references UUT 3"));
    }

    [Fact]
    public void MissingTeardownIsAWarningNotAnError()
    {
        var report = Check(
            R("<Exec>"),
            R("<Exec/>"));

        Assert.True(report.Ok);
        Assert.Contains(report.Warnings, d => d.Message.Contains("<Teardown>"));
    }

    /// <summary>
    /// A blank module cell downgrades the row to a warning.
    /// </summary>
    /// <remarks>
    /// Blocking the load would be stricter than v1, which raised KeyError on
    /// <c>globals[""]</c> and diverted to the row's handler -- the step never
    /// executed there either, so refusing to open the whole table is not an
    /// improvement.
    /// </remarks>
    [Fact]
    public void BlankModuleCellIsOnlyAWarning()
    {
        var report = Check(
            R("<Exec>"),
            R("", "STORE", "x", "0,0,0"),
            R("<Exec/>"));

        Assert.True(report.Ok);
        Assert.Contains(report.Warnings, d => d.Message.Contains("no module in column 0"));
    }

    [Fact]
    public void UnexpectedExtraArgumentIsAWarning()
    {
        var report = Check(
            R("<Exec>"),
            R("FlowManager", "STORE", "value", "0,0,0", "stray"),
            R("<Exec/>"));

        Assert.True(report.Ok);
        Assert.Contains(report.Warnings, d => d.Message.Contains("unexpected argument in column 4"));
    }

    [Fact]
    public void ExceptionLabelWithNoLabelRowIsAWarning()
    {
        var report = Check(
            R("<Exec>"),
            Guarded("FlowManager", "STORE", "NO_SUCH_HANDLER", "-", "x", "0,0,0"),
            R("<Exec/>"));

        Assert.Contains(report.Warnings, d => d.Message.Contains("NO_SUCH_HANDLER"));
    }

    [Fact]
    public void MissingExecSectionIsAnError()
    {
        var report = Check(R("<Config>"), R("<Config/>"));

        Assert.Contains(report.Errors, d => d.Message.Contains("no <Exec> section"));
    }

    [Fact]
    public void DuplicateLabelIsRejectedAtLoad()
    {
        var exception = Assert.Throws<ProgramException>(() => Program(
            R("<Exec>"),
            R("FlowManager", "LABEL", "TWICE"),
            R("FlowManager", "LABEL", "TWICE"),
            R("<Exec/>")));

        Assert.Contains("duplicate label", exception.Message);
    }
}
