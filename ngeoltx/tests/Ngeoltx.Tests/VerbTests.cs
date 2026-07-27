using Ngeoltx.Drivers;
using Ngeoltx.Engine;
using Xunit;
using static Ngeoltx.Tests.Fixtures;

namespace Ngeoltx.Tests;

/// <summary>Driver verbs, exercised through real programs.</summary>
public class VerbTests
{
    private static (RunRecord Record, RecordingListener Events) Exec(params string[][] rows)
    {
        var all = new List<string[]>
        {
            R("<Config>"),
            R("TestData", "INITDATA", "20", "20", "4"),
            R("TestData", "initAlive", "4"),
            R("<Config/>"),
            R("<Exec>"),
        };
        all.AddRange(rows);
        all.Add(R("<Exec/>"));
        return Run(Program(all.ToArray()));
    }

    // -- registry ---------------------------------------------------------------

    [Fact]
    public void EverySerialAliasResolvesToAnImplementation()
    {
        EnsureDrivers();

        // 2 operations x 2 payloads x 2 terminations x 5 levels, plus the three
        // names v1 spelled differently.
        foreach (var name in new[]
        {
            "READLINE_LV0", "EXCHANGEBYTES_LT_LV3", "EXCHANGELINE_LVS", "READVKING",
        })
            Assert.NotNull(VerbRegistry.Default.Lookup(SerialVerbs.Module, name));
    }

    [Fact]
    public void ModuleAliasesResolveToTheRealDriver()
    {
        EnsureDrivers();

        Assert.Equal(ProductVerbs.Module, VerbRegistry.Default.ResolveModule("1211Manager"));
        Assert.Equal(VisionVerbs.Module, VerbRegistry.Default.ResolveModule("Vision"));
        Assert.NotNull(VerbRegistry.Default.Lookup("Cargo", "VALIDATE_DET"));
    }

    // -- flow ---------------------------------------------------------------------

    [Fact]
    public void ArithmeticAndStringVerbsWriteWhereTheyAreTold()
    {
        var (record, _) = Exec(
            R("FlowManager", "STORE", "12.5", "0,0,0"),
            R("FlowManager", "ADD", "0,1,0", "*0,0,0", "1.5"),
            R("FlowManager", "SUBSTRING", "abcdef", "1", "4", "0,2,0"),
            R("FlowManager", "COUNT", "abcabc", "abc", "0,3,0"));

        Assert.All(record.Steps.Where(s => s.Module == "FlowManager"),
                   s => Assert.Equal("ok", s.Outcome));
    }

    [Fact]
    public void DivisionByZeroIsAVerbFailureNotACrash()
    {
        var (record, _) = Exec(R("FlowManager", "DIV", "0,0,0", "1", "0"));

        var step = record.Steps.Single(s => s.Verb == "DIV");
        Assert.Equal("failed", step.Outcome);
        Assert.Contains("division by zero", step.Detail);
    }

    /// <summary>
    /// JL accepts hex, because the cargo control board answers its detection
    /// poll that way.
    /// </summary>
    [Fact]
    public void JumpLessAcceptsAHexReading()
    {
        var (record, _) = Exec(
            R("FlowManager", "JL", "TARGET", "1F", "32"),
            R("FlowManager", "STORE", "skipped", "0,0,0"),
            R("FlowManager", "LABEL", "TARGET"),
            R("FlowManager", "STORE", "landed", "0,1,0"));

        Assert.DoesNotContain(record.Steps,
            s => s.Verb == "STORE" && s.Args[0] == "skipped");
        Assert.Contains(record.Steps, s => s.Verb == "STORE" && s.Args[0] == "landed");
    }

    [Fact]
    public void EvaluationRecordsAPointAndKillsOnFailure()
    {
        var (record, events) = Exec(
            R("FlowManager", "STORE", "13.6", "0,0,0"),
            R("FlowManager", "EVAFLOAT", "12.0,13.0", "*0,0,0", "0,1,0", "min", "2,VBAT"));

        var point = Assert.Single(record.Points);
        Assert.Equal("VBAT", point.Name);
        Assert.Equal("FAIL", point.Result);
        Assert.Equal(2, point.Uut);

        // Grid 3 holds UUT index 2.
        Assert.Contains(events.OfType<GridEvent>(), g => g.Grid == 3 && g.Tag == "FAIL");
        Assert.Contains(events.OfType<AliveEvent>(), a => a.Alive[2] == 0);
    }

    /// <summary>
    /// An unreadable measurement fails the point instead of throwing.
    /// </summary>
    [Fact]
    public void EvaluationOfANonNumberFailsCleanly()
    {
        var (record, _) = Exec(
            R("FlowManager", "STORE", "TIMEOUT", "0,0,0"),
            R("FlowManager", "EVAFLOAT", "1,2", "*0,0,0", "0,1,0", "min", "0,VBAT"));

        var point = Assert.Single(record.Points);
        Assert.Equal("FAIL", point.Result);
        Assert.Equal("None", point.Measured);
    }

    /// <summary>
    /// One destination cell derives three, by walking the column.
    /// </summary>
    /// <remarks>
    /// v1's getTripleIndex, and what the cargo table writes. Supporting only the
    /// explicit three-cell form dropped the verdict on the floor, leaving the
    /// measured value stored with no result anywhere.
    /// </remarks>
    [Fact]
    public void ASingleDestinationDerivesTheValueResultAndIdCells()
    {
        var (record, _) = Exec(
            R("FlowManager", "STORE", "1.0", "0,0,0"),
            R("FlowManager", "EVAFLOAT", "0,2", "*0,0,0", "1,0,0", "min", "0,VBAT"),
            R("FlowManager", "COPY", "*1,1,0", "5,0,0"),
            R("FlowManager", "COPY", "*1,2,0", "5,1,0"));

        Assert.All(record.Steps.Where(s => s.Verb == "COPY"),
                   s => Assert.Equal("ok", s.Outcome));
        Assert.Equal("PASS", Assert.Single(record.Points).Result);
    }

    // -- product ------------------------------------------------------------------

    /// <summary>
    /// A set bit means the slot is occupied.
    /// </summary>
    /// <remarks>
    /// 0x1F is 16 + 0b1111: all four present, nothing killed. Reading this
    /// backwards kills every good board on the fixture while looking like it
    /// worked, which is why it has a test of its own.
    /// </remarks>
    [Fact]
    public void DetectionMaskTreatsSetBitsAsPresent()
    {
        var (_, events) = Exec(R("CargoManager", "VALIDATE_DET", "1F"));

        Assert.DoesNotContain(events.OfType<AliveEvent>(), a => a.Alive.Any(v => v == 0));
    }

    /// <summary>
    /// Slots whose bit is clear are the ones that get killed.
    /// </summary>
    /// <remarks>
    /// 21 is 16 + 0b0101, so slots 0 and 2 are present and 1 and 3 are absent.
    /// Written in decimal on purpose: parsing is decimal-first, inherited from
    /// v1's to_int, so "15" would read as fifteen rather than 0x15. Only a
    /// reading containing A-F is unambiguous as hex.
    /// </remarks>
    [Fact]
    public void DetectionMaskKillsTheSlotsWhoseBitsAreClear()
    {
        var (_, events) = Exec(R("CargoManager", "VALIDATE_DET", "21"));

        var alive = events.OfType<AliveEvent>().Last().Alive;
        Assert.Equal(new[] { 1, 0, 1, 0 }, alive);
    }

    /// <summary>
    /// An unprefixed reading of all digits is read as decimal.
    /// </summary>
    /// <remarks>
    /// This is inherent to unprefixed hex, not a parser that could be made
    /// cleverer: "15" is a valid decimal and a valid hex value, and only the
    /// board knows which it meant. Pinned by a test because the alternative is
    /// discovering it on a fixture.
    /// </remarks>
    [Fact]
    public void AnAllDigitReadingIsDecimalNotHex()
    {
        var (record, _) = Exec(R("CargoManager", "VALIDATE_DET", "15"));

        // Decimal 15 minus the constant 16 is negative, so it is rejected
        // rather than silently treated as 0x15.
        var step = record.Steps.Single(s => s.Verb == "VALIDATE_DET");
        Assert.Equal("failed", step.Outcome);
        Assert.Contains("outside 0-15", step.Detail);
    }

    /// <summary>
    /// Stating the radix removes the ambiguity a guess cannot.
    /// </summary>
    /// <remarks>
    /// "10" from a hex fixture means sixteen, an empty board. The legacy parser
    /// reads ten and rejects it. A table that says <c>hex</c> gets the right
    /// answer, and one that leaves the cell blank keeps the old behaviour.
    /// </remarks>
    [Fact]
    public void AnExplicitHexRadixReadsTheEmptyFixtureCorrectly()
    {
        var (record, events) = Exec(R("CargoManager", "VALIDATE_DET", "10", "hex"));

        Assert.Equal("ok", record.Steps.Single(s => s.Verb == "VALIDATE_DET").Outcome);
        // 0x10 is 16 + 0b0000: nothing on the fixture, so every slot dies.
        Assert.Equal(new[] { 0, 0, 0, 0 }, events.OfType<AliveEvent>().Last().Alive);
    }

    [Fact]
    public void AnUnknownRadixNamesTheOnesThatWork()
    {
        var (record, _) = Exec(R("CargoManager", "VALIDATE_DET", "1F", "octal"));

        var step = record.Steps.Single(s => s.Verb == "VALIDATE_DET");
        Assert.Equal("failed", step.Outcome);
        Assert.Contains("'hex', 'dec', or blank", step.Detail);
    }

    [Fact]
    public void DetectionValueOutsideItsRangeIsRejected()
    {
        var (record, _) = Exec(R("CargoManager", "VALIDATE_DET", "99"));

        var step = record.Steps.Single(s => s.Verb == "VALIDATE_DET");
        Assert.Equal("failed", step.Outcome);
        Assert.Contains("outside 0-15", step.Detail);
    }

    [Fact]
    public void BarcodeLengthAndPrefixAreBothChecked()
    {
        var (record, _) = Exec(
            R("CargoManager", "VALIDATE_BCODE", "AB12345", "0,0,0;0,1,0;0,2,0",
              "7", "AB", "0"));

        var point = Assert.Single(record.Points);
        Assert.Equal("PASS", point.Result);
        Assert.Equal("AB12345", record.Barcodes[0]);
    }

    [Fact]
    public void AWrongLengthBarcodeFailsAndKills()
    {
        var (record, _) = Exec(
            R("CargoManager", "VALIDATE_BCODE", "SHORT", "0,0,0;0,1,0;0,2,0",
              "7", "AB", "1"));

        var point = Assert.Single(record.Points);
        Assert.Equal("FAIL", point.Result);
        Assert.Equal("BCODE Length", point.Name);
    }

    /// <summary>
    /// The final verdict comes from the run record, not a hard-coded list of
    /// data coordinates per product.
    /// </summary>
    [Fact]
    public void FinalValidationDerivesEachVerdictFromRecordedPoints()
    {
        var (record, _) = Exec(
            R("FlowManager", "STORE", "1.0", "0,0,0"),
            R("FlowManager", "EVAFLOAT", "0,2", "*0,0,0", "1,0,0", "min", "0,GOOD"),
            R("FlowManager", "EVAFLOAT", "5,6", "*0,0,0", "2,0,0", "min", "1,BAD"),
            R("CargoManager", "VALIDATE", "", "3,0,0"));

        Assert.True(record.Passed(0));
        Assert.False(record.Passed(1));
    }

    // -- serial ---------------------------------------------------------------------

    /// <summary>
    /// The simulated control board answers a real detection poll.
    /// </summary>
    /// <remarks>
    /// Exercised end to end -- find the port, open it, poll, read the answer --
    /// because the point of the simulation is that a program runs unchanged
    /// against it.
    /// </remarks>
    [Fact]
    public void SerialExchangeReachesTheSimulatedControlBoard()
    {
        var (record, _) = Exec(
            R("WinSerialManager", "FINDPORT", "115200,1", "066CFF3833554B3043165348", "CTRL"),
            R("WinSerialManager", "OPEN", "CTRL"),
            R("WinSerialManager", "EXCHANGELINE_LV0", "CTRL", "d", "", "", "0,0,0"),
            R("WinSerialManager", "EXCHANGELINE_LV0", "CTRL", "d", "", "", "0,1,0"),
            R("WinSerialManager", "EXCHANGELINE_LV0", "CTRL", "d", "", "", "0,2,0"));

        Assert.All(record.Steps.Where(s => s.Module == "WinSerialManager"),
                   s => Assert.Equal("ok", s.Outcome));
    }

    [Fact]
    public void FindportSaysWhatItSawWhenNothingMatches()
    {
        var (record, _) = Exec(
            R("WinSerialManager", "FINDPORT", "115200,1", "NO_SUCH_DEVICE", "X"));

        var step = record.Steps.Single(s => s.Verb == "FINDPORT");
        Assert.Equal("failed", step.Outcome);
        Assert.Contains("Available:", step.Detail);
    }

    [Fact]
    public void UsingAnUnopenedPortNamesTheOnesThatAreOpen()
    {
        var (record, _) = Exec(R("WinSerialManager", "OPEN", "GHOST"));

        var step = record.Steps.Single(s => s.Verb == "OPEN");
        Assert.Equal("failed", step.Outcome);
        Assert.Contains("is not open", step.Detail);
    }

    // -- instruments ------------------------------------------------------------------

    [Fact]
    public void MeasureFevalJudgesAndRecordsTheReading()
    {
        var (record, _) = Exec(
            R("GlobalVISAManager", "OPENALL", "2000"),
            R("GlobalVISAManager", "WRITE", "DP2A243200206", "INST 1"),
            R("GlobalVISAManager", "WRITE", "DP2A243200206", "VOLT 13.5"),
            R("GlobalVISAManager", "WRITE", "DP2A243200206", "OUTP ON"),
            R("GlobalVISAManager", "MEASURE_FEVAL", "DP2A243200206", "MEAS:VOLT?",
              "13.0,14.0", "0,0,0", "1,0,VBAT"));

        var point = Assert.Single(record.Points);
        Assert.Equal("VBAT", point.Name);
        Assert.Equal("PASS", point.Result);
    }

    /// <summary>
    /// The simulated supply tracks state, so a measurement is consistent with
    /// what was written -- a flat mock could not show this.
    /// </summary>
    [Fact]
    public void MeasuringWithTheOutputOffReadsAboutZero()
    {
        var (record, _) = Exec(
            R("GlobalVISAManager", "OPENALL", "2000"),
            R("GlobalVISAManager", "WRITE", "DP2A243200206", "INST 1"),
            R("GlobalVISAManager", "WRITE", "DP2A243200206", "VOLT 13.5"),
            R("GlobalVISAManager", "WRITE", "DP2A243200206", "OUTP OFF"),
            R("GlobalVISAManager", "MEASURE_FEVAL", "DP2A243200206", "MEAS:VOLT?",
              "13.0,14.0", "0,0,0", "1,0,VBAT"));

        Assert.Equal("FAIL", Assert.Single(record.Points).Result);
    }

    // -- UI -----------------------------------------------------------------------------

    [Fact]
    public void GridVerbsEmitEventsRatherThanTouchingControls()
    {
        var (_, events) = Exec(
            R("UIManager", "GRID1", "Clear"),
            R("UIManager", "GRID2", "Add", "const", "NAME;2;1;2;1.5;PASS;PASS"),
            R("UIManager", "STATUS", "Set", "Testing", "", "#00ff00"),
            R("UIManager", "PBAR", "0.5"));

        Assert.Contains(events.OfType<GridEvent>(), g => g.Grid == 1 && g.Op == "clear");
        Assert.Contains(events.OfType<GridEvent>(), g => g.Grid == 2 && g.Tag == "PASS");
        Assert.Contains(events.OfType<StatusEvent>(), s => s.Text == "Testing");
        Assert.Contains(events.OfType<ProgressEvent>(), p => Math.Abs(p.Value - 0.5) < 1e-9);
    }

    [Fact]
    public void AnUnknownGridOperationNamesTheValidOnes()
    {
        var (record, _) = Exec(R("UIManager", "GRID1", "Sideways"));

        var step = record.Steps.Single(s => s.Verb == "GRID1");
        Assert.Equal("failed", step.Outcome);
        Assert.Contains("expected add, clear, place, unplace", step.Detail);
    }
}
