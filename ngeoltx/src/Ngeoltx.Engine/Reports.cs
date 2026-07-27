using System.Text;
using System.Xml.Linq;

namespace Ngeoltx.Engine;

/// <summary>
/// Report generation from a <see cref="RunRecord"/>.
/// </summary>
/// <remarks>
/// Pure functions over the record, so adding a format costs nothing and needs
/// no knowledge of any product's data-store layout.
/// </remarks>
public static class Reports
{
    public static readonly string[] Formats = { "xml", "json", "csv" };

    public static string Write(RunRecord record, string path, string format = "json")
    {
        format = format.ToLowerInvariant();
        if (!Formats.Contains(format))
            throw new ArgumentException(
                "unknown report format '" + format + "' (expected "
                + string.Join(", ", Formats) + ")");

        var parent = Path.GetDirectoryName(Path.GetFullPath(path));
        if (!string.IsNullOrEmpty(parent)) Directory.CreateDirectory(parent);

        var text = format switch
        {
            "xml" => ToXml(record),
            "csv" => ToCsv(record),
            _ => record.ToJson(),
        };
        File.WriteAllText(path, text);
        return path;
    }

    public static string ToCsv(RunRecord record)
    {
        var builder = new StringBuilder("uut,test,result,measured,low,high,row,at\n");
        foreach (var point in record.Points)
            builder.Append(string.Join(",", new[]
            {
                point.Uut?.ToString() ?? "", point.Name, point.Result, point.Measured,
                point.Low, point.High, point.Row?.ToString() ?? "",
                point.At?.ToString("s") ?? "",
            }.Select(Escape))).Append('\n');
        return builder.ToString();
    }

    private static string Escape(string value) =>
        value.IndexOfAny(new[] { ',', '"', '\n' }) >= 0
            ? "\"" + value.Replace("\"", "\"\"") + "\""
            : value;

    /// <summary>
    /// One LOG_XML block per UUT, matching the shape v1 produced.
    /// </summary>
    /// <remarks>
    /// Kept close to the v1 output so whatever consumes these downstream needs
    /// no change -- but generated from recorded points, so nothing is lost to
    /// an overwritten data cell.
    /// </remarks>
    public static string ToXml(RunRecord record, int? uut = null)
    {
        var targets = uut is not null
            ? new List<int?> { uut }
            : record.Uuts().Count > 0
                ? record.Uuts().Select(u => (int?)u).ToList()
                : new List<int?> { null };

        var blocks = targets.Select(target => OneBlock(record, target)).ToList();
        if (blocks.Count == 1)
            return "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n" + blocks[0];

        return "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
               + new XElement("LOGS", blocks.Select(XElement.Parse));
    }

    private static string OneBlock(RunRecord record, int? uut)
    {
        var points = uut is not null ? record.PointsFor(uut.Value) : record.Points;
        var passed = uut is not null ? record.Passed(uut.Value) : record.Passed();
        var barcode = uut is not null && record.Barcodes.TryGetValue(uut.Value, out var code)
            ? code : "";

        var element = new XElement("LOG_XML",
            new XElement("filename",
                record.ProgramName + "_" + (uut?.ToString() ?? "ALL")),
            new XElement("serialnumber", barcode),
            new XElement("supplier", "UARTRONICA"),
            new XElement("station", record.Station),
            new XElement("operator", record.Operator),
            new XElement("starttime", record.Started.ToString("yyyy-MM-dd HH:mm:ss")),
            new XElement("endtime",
                (record.Ended ?? DateTime.Now).ToString("yyyy-MM-dd HH:mm:ss")),
            new XElement("duration", record.DurationSeconds.ToString("0.00")),
            new XElement("result", passed ? "PASS" : "FAIL"));

        // Never let a simulated run be mistaken for a real one downstream.
        if (record.Simulated) element.Add(new XElement("simulated", "true"));

        var tasks = new XElement("tasks");
        foreach (var point in points)
        {
            var task = new XElement("task", new XAttribute("name", point.Name),
                new XElement("result", point.Result));
            if (point.Measured.Length > 0) task.Add(new XElement("measured", point.Measured));
            if (point.Low.Length > 0) task.Add(new XElement("min", point.Low));
            if (point.High.Length > 0) task.Add(new XElement("max", point.High));
            tasks.Add(task);
        }
        element.Add(tasks);
        return element.ToString();
    }
}
