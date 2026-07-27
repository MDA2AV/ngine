using YamlDotNet.Serialization;

namespace Ngeoltx.Engine.Loaders;

/// <summary>
/// Loads a program from any supported format.
/// </summary>
/// <remarks>
/// <list type="bullet">
/// <item><c>.ods</c> -- legacy spreadsheet, read without a spreadsheet library</item>
/// <item><c>.txt</c> -- legacy dollar-separated export</item>
/// <item><c>.csv</c> -- same ten-column layout</item>
/// <item><c>.yaml</c> -- native format: git-diffable, supports Vars and Teardown</item>
/// </list>
/// All four produce the same <see cref="TestProgram"/>, so the engine neither
/// knows nor cares which one an operator loaded.
/// </remarks>
public static class ProgramLoader
{
    public static readonly string[] LegacyExtensions = { ".ods", ".txt", ".csv" };
    public static readonly string[] NativeExtensions = { ".yaml", ".yml", ".ngw" };

    public static string DetectFormat(string path)
    {
        var extension = Path.GetExtension(path).ToLowerInvariant();
        if (NativeExtensions.Contains(extension)) return "native";
        if (LegacyExtensions.Contains(extension)) return extension.TrimStart('.');
        throw new LoaderException(
            "unsupported program format '" + extension + "' -- expected one of "
            + string.Join(", ", LegacyExtensions.Concat(NativeExtensions)));
    }

    public static TestProgram Load(string path)
    {
        if (!File.Exists(path))
            throw new LoaderException("program file not found: " + path);

        var kind = DetectFormat(path);
        var program = kind == "native" ? LoadNative(path) : LoadLegacy(path, kind);

        program.Source = path;
        if (!program.Meta.ContainsKey("name"))
            program.Meta["name"] = Path.GetFileNameWithoutExtension(path);
        return program.Finalise();
    }

    // -- legacy tables -----------------------------------------------------

    private static TestProgram LoadLegacy(string path, string kind)
    {
        var grid = kind switch
        {
            "ods" => OdsReader.Read(path),
            "txt" => ReadDollarText(path),
            "csv" => ReadCsv(path),
            _ => throw new LoaderException("'" + path + "' is not a legacy table"),
        };

        var program = new TestProgram();
        foreach (var row in Normalise(StripHeader(grid))) program.Rows.Add(row);
        return program;
    }

    /// <summary>v1's export: cells joined by dollars, "-" for empty.</summary>
    private static List<List<string>> ReadDollarText(string path)
    {
        var grid = new List<List<string>>();
        foreach (var line in File.ReadAllLines(path))
        {
            var cells = line.Split('$').ToList();
            if (cells.Count > 0 && cells[^1].Length == 0) cells.RemoveAt(cells.Count - 1);
            grid.Add(cells.Select(c => c == "-" ? "" : c.Trim()).ToList());
        }
        return grid;
    }

    private static List<List<string>> ReadCsv(string path)
    {
        var grid = new List<List<string>>();
        foreach (var line in File.ReadAllLines(path))
            grid.Add(SplitCsvLine(line).Select(c => c.Trim()).ToList());
        return grid;
    }

    private static List<string> SplitCsvLine(string line)
    {
        var cells = new List<string>();
        var current = new System.Text.StringBuilder();
        var quoted = false;
        for (var i = 0; i < line.Length; i++)
        {
            var c = line[i];
            if (quoted)
            {
                if (c == '"' && i + 1 < line.Length && line[i + 1] == '"') { current.Append('"'); i++; }
                else if (c == '"') quoted = false;
                else current.Append(c);
            }
            else if (c == '"') quoted = true;
            else if (c == ',') { cells.Add(current.ToString()); current.Clear(); }
            else current.Append(c);
        }
        cells.Add(current.ToString());
        return cells;
    }

    /// <summary>
    /// Drop the C0,C1,... header row if present.
    /// </summary>
    /// <remarks>
    /// v1's ODS path consumed it implicitly (pandas treats row 0 as column
    /// names) while its text path did not -- a genuine inconsistency between
    /// the two loaders. Detecting it explicitly makes both agree, and a table
    /// that opens straight into a section marker still works.
    /// </remarks>
    private static List<List<string>> StripHeader(List<List<string>> grid)
    {
        if (grid.Count == 0) return grid;
        var first = grid[0].Select(c => c.Trim()).ToList();
        if (first.Count == 0) return grid.Skip(1).ToList();

        var head = first[0];
        if (head.StartsWith("<")) return grid;          // no header
        var upper = head.ToUpperInvariant();
        return head.Length == 0 || upper is "C0" or "#" or "ID" or "MODULE"
            ? grid.Skip(1).ToList()
            : grid;
    }

    /// <summary>
    /// Pad or trim every row to the ten-column layout.
    /// </summary>
    /// <remarks>
    /// Some legacy tables carry a leading index column; v1 detected this with
    /// <c>len(words) &lt; 12</c> and shifted. Same rule, expressed once.
    /// </remarks>
    private static List<Row> Normalise(List<List<string>> grid)
    {
        var rows = new List<Row>();
        for (var i = 0; i < grid.Count; i++)
        {
            var cells = grid[i].Select(c => (c ?? "").Trim()).ToList();
            if (cells.Count > Row.Columns + 1) cells = cells.Skip(1).ToList();
            cells = cells.Select(c => c == "-" ? "" : c).ToList();
            while (cells.Count < Row.Columns) cells.Add("");
            rows.Add(new Row(rows.Count, cells.Take(Row.Columns), i + 1));
        }
        return rows;
    }

    // -- native format -----------------------------------------------------

    private static readonly (string Key, string Tag)[] NativeSections =
    {
        ("config", "Config"), ("exec", "Exec"),
        ("ehandling", "Ehandling"), ("teardown", "Teardown"),
    };

    private static TestProgram LoadNative(string path)
    {
        object? document;
        try
        {
            var deserializer = new DeserializerBuilder().Build();
            document = deserializer.Deserialize<object>(File.ReadAllText(path));
        }
        catch (Exception exc)
        {
            throw new LoaderException("malformed YAML in '" + path + "': " + exc.Message, exc);
        }

        if (document is not Dictionary<object, object> map)
            throw new LoaderException("'" + path + "' must contain a mapping at the top level");
        return FromDictionary(map);
    }

    /// <summary>
    /// Build a program from a parsed native document.
    /// </summary>
    /// <remarks>
    /// Sections are emitted as real marker rows so that everything downstream --
    /// sequencer, validator, editor -- sees exactly the structure it would get
    /// from a legacy ODS. There is one program model, not two.
    /// </remarks>
    public static TestProgram FromDictionary(Dictionary<object, object> document)
    {
        var program = new TestProgram();

        void Add(IEnumerable<string> cells) =>
            program.Rows.Add(new Row(program.Rows.Count, cells));
        void Marker(string tag) =>
            Add(new[] { tag }.Concat(Enumerable.Repeat("", Row.Columns - 1)));

        if (Get(document, "meta") is Dictionary<object, object> meta)
            foreach (var pair in meta)
                program.Meta[Str(pair.Key)] = Str(pair.Value);

        if (Get(document, "modules") is Dictionary<object, object> modules && modules.Count > 0)
        {
            Marker("<Modules>");
            foreach (var pair in modules)
                Add(new[] { Str(pair.Key), Str(pair.Value) }
                    .Concat(Enumerable.Repeat("", Row.Columns - 2)));
            Marker("<Modules/>");
        }

        if (Get(document, "vars") is Dictionary<object, object> vars && vars.Count > 0)
        {
            Marker("<Vars>");
            foreach (var pair in vars)
                Add(new[] { Str(pair.Key), Str(pair.Value) }
                    .Concat(Enumerable.Repeat("", Row.Columns - 2)));
            Marker("<Vars/>");
        }

        foreach (var (key, tag) in NativeSections)
        {
            if (Get(document, key) is not List<object> entries) continue;
            Marker("<" + tag + ">");
            foreach (var entry in entries) Add(EntryToCells(entry, key));
            Marker("<" + tag + "/>");
        }
        return program;
    }

    private static IEnumerable<string> EntryToCells(object? entry, string section)
    {
        var cells = Enumerable.Repeat("", Row.Columns).ToList();
        switch (entry)
        {
            case null:
                return cells;

            case List<object> list:
                for (var i = 0; i < Math.Min(list.Count, Row.Columns); i++)
                    cells[i] = Str(list[i]);
                return cells;

            // A bare string is a comment row -- handy for section headings.
            case string text:
                cells[9] = text;
                return cells;

            case Dictionary<object, object> map:
                cells[0] = Str(Get(map, "module"));
                cells[1] = Str(Get(map, "verb"));
                var args = Get(map, "args") switch
                {
                    List<object> many => many,
                    null => new List<object>(),
                    var single => new List<object> { single },
                };
                var capacity = Row.ArgEnd - Row.ArgStart + 1;
                if (args.Count > capacity)
                    throw new LoaderException(
                        section + " (" + cells[0] + "." + cells[1] + "): " + args.Count
                        + " arguments given, at most " + capacity + " fit the row layout");
                for (var i = 0; i < args.Count; i++) cells[Row.ArgStart + i] = Str(args[i]);
                cells[7] = Str(Get(map, "route") ?? Get(map, "on_error"));
                cells[8] = Str(Get(map, "alive"));
                cells[9] = Str(Get(map, "comment") ?? Get(map, "color"));
                return cells;

            default:
                throw new LoaderException(
                    section + ": expected a list or mapping, got " + entry.GetType().Name);
        }
    }

    private static object? Get(Dictionary<object, object> map, string key) =>
        map.TryGetValue(key, out var value) ? value : null;

    private static string Str(object? value) => value switch
    {
        null => "",
        bool flag => flag ? "TRUE" : "FALSE",
        _ => value.ToString()?.Trim() ?? "",
    };

    // -- writing ------------------------------------------------------------

    public static void Save(TestProgram program, string path)
    {
        var kind = DetectFormat(path);
        var grid = new List<IReadOnlyList<string>>
        {
            new[] { "C0", "C1", "C2", "C3", "C4", "C5", "C6",
                    "EXCEPTION", "ALIVE", "COMMENT/COLOR" },
        };
        foreach (var row in program.Rows) grid.Add(row.Cells);

        switch (kind)
        {
            case "ods":
                OdsReader.Write(path, grid,
                    program.Meta.TryGetValue("name", out var name) ? name : "Sheet1");
                break;

            case "csv":
                File.WriteAllLines(path, grid.Select(r =>
                    string.Join(",", r.Select(EscapeCsv))));
                break;

            case "txt":
                File.WriteAllLines(path, grid.Skip(1).Select(r =>
                    string.Join("", r.Select(c => (c.Length == 0 ? "-" : c) + "$"))));
                break;

            case "native":
                File.WriteAllText(path, ToYaml(program));
                break;
        }
    }

    private static string EscapeCsv(string value) =>
        value.IndexOfAny(new[] { ',', '"', '\n' }) >= 0
            ? "\"" + value.Replace("\"", "\"\"") + "\""
            : value;

    private static string ToYaml(TestProgram program)
    {
        var document = new Dictionary<string, object>();
        if (program.Meta.Count > 0) document["meta"] = program.Meta;
        if (program.Modules.Count > 0) document["modules"] = program.Modules;
        if (program.Vars.Count > 0) document["vars"] = program.Vars;

        foreach (var (key, tag) in NativeSections)
        {
            var section = program.SectionOrNull(tag);
            if (section is null) continue;
            var entries = new List<List<string>>();
            foreach (var i in section.Body)
            {
                if (i >= program.Rows.Count) break;
                var cells = program.Rows[i].Cells.ToList();
                while (cells.Count > 0 && cells[^1].Length == 0)
                    cells.RemoveAt(cells.Count - 1);
                entries.Add(cells);
            }
            document[key] = entries;
        }
        return new SerializerBuilder().Build().Serialize(document);
    }
}
