using Ngeoltx.Engine;
using Ngeoltx.Engine.Loaders;
using Xunit;
using static Ngeoltx.Tests.Fixtures;

namespace Ngeoltx.Tests;

public class LoaderTests
{
    [Fact]
    public void ReadsTheLegacyDollarFormat()
    {
        var path = TempFile(".txt");
        File.WriteAllLines(path, new[]
        {
            "<Exec>$-$-$-$-$-$-$-$-$-$",
            "FlowManager$STORE$hello$0,0,0$-$-$-$-$-$-$",
            "<Exec/>$-$-$-$-$-$-$-$-$-$",
        });

        var program = ProgramLoader.Load(path);

        Assert.Equal(3, program.Rows.Count);
        Assert.Equal("FlowManager", program.Rows[1].Module);
        Assert.Equal("hello", program.Rows[1].Raw(2));
        // "-" is a placeholder, not a value.
        Assert.Equal("", program.Rows[1].Raw(4));
        File.Delete(path);
    }

    [Fact]
    public void ReadsCsvAndStripsAHeaderRow()
    {
        var path = TempFile(".csv");
        File.WriteAllLines(path, new[]
        {
            "C0,C1,C2,C3,C4,C5,C6,EXCEPTION,ALIVE,COMMENT",
            "<Exec>,,,,,,,,,",
            "FlowManager,STORE,\"a,b\",0.0.0,,,,,,",
            "<Exec/>,,,,,,,,,",
        });

        var program = ProgramLoader.Load(path);

        Assert.Equal("<Exec>", program.Rows[0].Module);
        Assert.Equal("a,b", program.Rows[1].Raw(2));
        File.Delete(path);
    }

    [Fact]
    public void NativeYamlRoundTripsThroughTheSameModel()
    {
        var path = TempFile(".yaml");
        File.WriteAllText(path, """
            meta:
              name: demo
            modules:
              Flow: FlowManager
            vars:
              vbat: 0,1,2
            config:
              - module: TestData
                verb: INITDATA
                args: [10, 10, 4]
            exec:
              - module: Flow
                verb: STORE
                args: ["12.6", "*vbat"]
                comment: store the reading
            teardown:
              - [FlowManager, STORE, done, "0,0,0"]
            """);

        var program = ProgramLoader.Load(path);

        Assert.Equal("demo", program.Meta["name"]);
        Assert.Equal("FlowManager", program.Modules["Flow"]);
        Assert.Equal("0,1,2", program.Vars["vbat"]);
        Assert.NotNull(program.SectionOrNull("Config"));
        Assert.NotNull(program.SectionOrNull("Teardown"));

        // Sections become real marker rows, so everything downstream sees the
        // structure it would get from a legacy spreadsheet.
        Assert.Contains(program.Rows, r => r.Module == "<Exec>");
        File.Delete(path);
    }

    [Fact]
    public void OdsSurvivesASaveAndLoad()
    {
        var path = TempFile(".ods");
        var original = Program(
            R("<Exec>"),
            R("FlowManager", "STORE", "hello", "0,0,0"),
            R("<Exec/>"));

        ProgramLoader.Save(original, path);
        var reloaded = ProgramLoader.Load(path);

        Assert.Equal("FlowManager", reloaded.Rows[1].Module);
        Assert.Equal("STORE", reloaded.Rows[1].Verb);
        Assert.Equal("hello", reloaded.Rows[1].Raw(2));
        File.Delete(path);
    }

    [Fact]
    public void ConvertsBetweenFormatsWithoutLosingRows()
    {
        var source = TempFile(".csv");
        var destination = TempFile(".yaml");
        File.WriteAllLines(source, new[]
        {
            "<Exec>,,,,,,,,,",
            "FlowManager,STORE,hello,\"0,0,0\",,,,,,",
            "<Exec/>,,,,,,,,,",
        });

        ProgramLoader.Save(ProgramLoader.Load(source), destination);
        var reloaded = ProgramLoader.Load(destination);

        Assert.Contains(reloaded.Rows,
            r => r.Verb == "STORE" && r.Raw(2) == "hello" && r.Raw(3) == "0,0,0");
        File.Delete(source);
        File.Delete(destination);
    }

    [Fact]
    public void UnknownExtensionIsRejectedWithTheSupportedList()
    {
        var exception = Assert.Throws<LoaderException>(() => ProgramLoader.DetectFormat("x.docx"));

        Assert.Contains(".ods", exception.Message);
    }

    [Fact]
    public void MissingFileSaysSoRatherThanThrowingIo()
    {
        Assert.Throws<LoaderException>(() => ProgramLoader.Load("no-such-program.csv"));
    }

    /// <summary>
    /// A native entry cannot carry more arguments than the row layout holds.
    /// </summary>
    /// <remarks>
    /// Silently dropping the seventh argument would leave a verb reading a blank
    /// cell it was told had a value in it.
    /// </remarks>
    [Fact]
    public void TooManyNativeArgumentsIsAnError()
    {
        var path = TempFile(".yaml");
        File.WriteAllText(path, """
            exec:
              - module: FlowManager
                verb: STORE
                args: [1, 2, 3, 4, 5, 6, 7]
            """);

        var exception = Assert.Throws<LoaderException>(() => ProgramLoader.Load(path));

        Assert.Contains("at most", exception.Message);
        File.Delete(path);
    }
}
