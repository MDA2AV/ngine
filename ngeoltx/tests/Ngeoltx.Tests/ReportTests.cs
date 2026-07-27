using System.Text.Json;
using System.Xml.Linq;
using Ngeoltx.Engine;
using Xunit;
using static Ngeoltx.Tests.Fixtures;

namespace Ngeoltx.Tests;

public class ReportTests
{
    private static RunRecord Sample()
    {
        var record = new RunRecord { ProgramName = "cargo", Station = "BENCH1" };
        record.AddPoint(new TestPoint("VBAT", 0, "PASS", "13.5", "13.0", "14.0"));
        record.AddPoint(new TestPoint("CURR", 1, "FAIL", "2.1", "0.0", "1.0"));
        record.SetBarcode(0, "AB12345");
        record.Finish(new[] { 1, 0 });
        return record;
    }

    [Fact]
    public void XmlCarriesOneBlockPerUnitWithItsBarcode()
    {
        var xml = XDocument.Parse(Reports.ToXml(Sample()));

        var blocks = xml.Descendants("LOG_XML").ToList();
        Assert.Equal(2, blocks.Count);
        Assert.Equal("AB12345", blocks[0].Element("serialnumber")?.Value);
        Assert.Equal("PASS", blocks[0].Element("result")?.Value);
        Assert.Equal("FAIL", blocks[1].Element("result")?.Value);
    }

    /// <summary>
    /// A simulated run is marked, so it cannot be mistaken downstream for a
    /// real one.
    /// </summary>
    [Fact]
    public void SimulatedRunsAreFlaggedInTheXml()
    {
        var record = new RunRecord { ProgramName = "cargo", Simulated = true };
        record.AddPoint(new TestPoint("VBAT", 0, "PASS"));
        record.Finish(new[] { 1 });

        var xml = XDocument.Parse(Reports.ToXml(record));

        Assert.Equal("true", xml.Descendants("simulated").Single().Value);
    }

    [Fact]
    public void CsvEscapesCommasInMeasuredValues()
    {
        var record = new RunRecord();
        record.AddPoint(new TestPoint("COLOUR", 0, "PASS", "20,220,40"));
        record.Finish(new[] { 1 });

        var csv = Reports.ToCsv(record);

        Assert.Contains("\"20,220,40\"", csv);
    }

    [Fact]
    public void JsonCarriesTheSummaryPointsAndSteps()
    {
        using var document = JsonDocument.Parse(Sample().ToJson());

        var root = document.RootElement;
        Assert.Equal(2, root.GetProperty("points").GetArrayLength());
        Assert.Equal(1, root.GetProperty("summary").GetProperty("FailedPoints").GetInt32());
    }

    [Fact]
    public void AnUnknownFormatIsRejectedWithTheSupportedList()
    {
        var exception = Assert.Throws<ArgumentException>(
            () => Reports.Write(Sample(), TempFile(".pdf"), "pdf"));

        Assert.Contains("xml, json, csv", exception.Message);
    }

    /// <summary>
    /// The report is built from recorded points, not by re-reading the data
    /// store.
    /// </summary>
    /// <remarks>
    /// v1 generated its XML at the end from whatever was still in the array, so
    /// any point whose coordinate had been reused mid-run was simply lost.
    /// </remarks>
    [Fact]
    public void ReusingADataCellDoesNotLoseTheEarlierPoint()
    {
        var program = Program(
            R("<Config>"),
            R("TestData", "INITDATA", "10", "10", "4"),
            R("TestData", "initAlive", "1"),
            R("<Config/>"),
            R("<Exec>"),
            R("FlowManager", "STORE", "1.0", "0,0,0"),
            R("FlowManager", "EVAFLOAT", "0,2", "*0,0,0", "1,0,0", "min", "0,FIRST"),
            // Same destination cells, a second measurement.
            R("FlowManager", "STORE", "9.0", "0,0,0"),
            R("FlowManager", "EVAFLOAT", "0,2", "*0,0,0", "1,0,0", "min", "0,SECOND"),
            R("<Exec/>"));

        var (record, _) = Run(program);
        var xml = XDocument.Parse(Reports.ToXml(record));

        var names = xml.Descendants("task")
                       .Select(t => t.Attribute("name")?.Value).ToList();
        Assert.Contains("FIRST", names);
        Assert.Contains("SECOND", names);
    }
}
