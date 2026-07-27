using System.IO.Compression;
using System.Text;
using System.Xml.Linq;

namespace Ngeoltx.Engine.Loaders;

/// <summary>
/// OpenDocument spreadsheet reader and writer, with no third-party dependency.
/// </summary>
/// <remarks>
/// v1 reached for pandas_ods_reader plus pyexcel_ods, dragging in pandas and
/// numpy purely to read a grid of strings, and routed every cell through a
/// DataFrame -- so integers came back as floats and empty cells as the float
/// nan, which is why v1's loader is littered with <c>if word == "nan"</c>.
/// Reading the XML directly avoids all of it: a cell's displayed text is
/// exactly what the engineer typed.
/// </remarks>
public static class OdsReader
{
    private static readonly XNamespace Table =
        "urn:oasis:names:tc:opendocument:xmlns:table:1.0";
    private static readonly XNamespace Office =
        "urn:oasis:names:tc:opendocument:xmlns:office:1.0";
    private static readonly XNamespace Text =
        "urn:oasis:names:tc:opendocument:xmlns:text:1.0";

    /// <summary>
    /// ODS pads rows out to the sheet width with a huge repeat count. Anything
    /// above this is padding, not real columns.
    /// </summary>
    private const int RepeatCap = 64;

    public static List<List<string>> Read(string path, int sheet = 0)
    {
        XDocument document;
        try
        {
            using var archive = ZipFile.OpenRead(path);
            var entry = archive.GetEntry("content.xml")
                        ?? throw new LoaderException("'" + path + "' has no content.xml");
            using var stream = entry.Open();
            document = XDocument.Load(stream);
        }
        catch (LoaderException) { throw; }
        catch (Exception exc)
        {
            throw new LoaderException("cannot read ODS file '" + path + "': " + exc.Message, exc);
        }

        var tables = document.Descendants(Table + "table").ToList();
        if (tables.Count == 0)
            throw new LoaderException("no sheets found in '" + path + "'");
        if (sheet >= tables.Count)
            throw new LoaderException(
                "'" + path + "' has " + tables.Count + " sheet(s); sheet " + sheet
                + " requested");

        var rows = new List<List<string>>();
        foreach (var element in tables[sheet].Descendants(Table + "table-row"))
        {
            var repeatRow = IntAttribute(element, "number-rows-repeated", 1);
            if (repeatRow > RepeatCap) repeatRow = 1;

            var cells = new List<string>();
            foreach (var cell in element.Elements())
            {
                if (cell.Name != Table + "table-cell"
                    && cell.Name != Table + "covered-table-cell") continue;
                var repeat = IntAttribute(cell, "number-columns-repeated", 1);
                if (repeat > RepeatCap) repeat = 1;
                var value = CellText(cell);
                for (var i = 0; i < repeat; i++) cells.Add(value);
            }
            while (cells.Count > 0 && cells[^1].Length == 0) cells.RemoveAt(cells.Count - 1);
            for (var i = 0; i < repeatRow; i++) rows.Add(new List<string>(cells));
        }

        while (rows.Count > 0 && rows[^1].All(c => c.Length == 0))
            rows.RemoveAt(rows.Count - 1);
        return rows;
    }

    private static int IntAttribute(XElement element, string name, int fallback)
    {
        var raw = element.Attribute(Table + name)?.Value;
        return raw is not null && int.TryParse(raw, out var value) ? value : fallback;
    }

    /// <summary>
    /// Displayed text of a cell.
    /// </summary>
    /// <remarks>
    /// Several text:p children mean hard line breaks inside the cell; they are
    /// joined with a space rather than losing the separation, since test tables
    /// occasionally wrap a long comment.
    /// </remarks>
    private static string CellText(XElement cell)
    {
        var parts = cell.Elements()
                        .Select(child => child.Value.Trim())
                        .Where(text => text.Length > 0);
        return string.Join(" ", parts).Trim();
    }

    // -- writing ----------------------------------------------------------

    private const string MimeType = "application/vnd.oasis.opendocument.spreadsheet";

    /// <summary>
    /// Write rows back to a minimal but valid ODS.
    /// </summary>
    /// <remarks>
    /// Enough for LibreOffice and Excel to open, which lets the program editor
    /// round-trip a legacy table without the engineer leaving the spreadsheet
    /// world.
    /// </remarks>
    public static void Write(string path, IReadOnlyList<IReadOnlyList<string>> rows,
                             string sheetName = "Sheet1")
    {
        var content = new XDocument(
            new XElement(Office + "document-content",
                new XAttribute(XNamespace.Xmlns + "office", Office),
                new XAttribute(XNamespace.Xmlns + "table", Table),
                new XAttribute(XNamespace.Xmlns + "text", Text),
                new XAttribute(Office + "version", "1.2"),
                new XElement(Office + "body",
                    new XElement(Office + "spreadsheet",
                        new XElement(Table + "table",
                            new XAttribute(Table + "name", sheetName),
                            rows.Select(row => new XElement(Table + "table-row",
                                row.Select(cell =>
                                    string.IsNullOrEmpty(cell)
                                        ? new XElement(Table + "table-cell")
                                        : new XElement(Table + "table-cell",
                                            new XAttribute(Office + "value-type", "string"),
                                            new XElement(Text + "p", cell))))))))));

        try
        {
            using var stream = File.Create(path);
            using var archive = new ZipArchive(stream, ZipArchiveMode.Create);

            // The mimetype entry must come first and be stored uncompressed.
            var mime = archive.CreateEntry("mimetype", CompressionLevel.NoCompression);
            using (var writer = new StreamWriter(mime.Open(), Encoding.ASCII))
                writer.Write(MimeType);

            var manifest = archive.CreateEntry("META-INF/manifest.xml");
            using (var writer = new StreamWriter(manifest.Open(), Encoding.UTF8))
                writer.Write(
                    "<?xml version=\"1.0\" encoding=\"UTF-8\"?>"
                    + "<manifest:manifest xmlns:manifest=\"urn:oasis:names:tc:"
                    + "opendocument:xmlns:manifest:1.0\" manifest:version=\"1.2\">"
                    + "<manifest:file-entry manifest:full-path=\"/\" "
                    + "manifest:media-type=\"" + MimeType + "\"/>"
                    + "<manifest:file-entry manifest:full-path=\"content.xml\" "
                    + "manifest:media-type=\"text/xml\"/></manifest:manifest>");

            var entry = archive.CreateEntry("content.xml");
            using var contentWriter = new StreamWriter(entry.Open(), Encoding.UTF8);
            contentWriter.Write(content.Declaration + content.ToString(SaveOptions.DisableFormatting));
        }
        catch (Exception exc)
        {
            throw new LoaderException("cannot write ODS file '" + path + "': " + exc.Message, exc);
        }
    }
}
