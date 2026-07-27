using Ngeoltx.Engine;

namespace Ngeoltx.Drivers;

/// <summary>
/// Core state verbs, registered under the module name TestData.
/// </summary>
/// <remarks>
/// Legacy tables call these without declaring them in Modules -- v1 reached
/// them through <c>globals()["TestData"]</c> -- so the module name is matched
/// literally.
/// </remarks>
public static class CoreVerbs
{
    public const string Module = "TestData";

    [Verb(Module, "initAlive", Args = "2:count", ConfigOnly = true)]
    public static void InitAlive(RunContext ctx, Row row)
    {
        var raw = ctx.Text(row.Raw(2));
        if (!int.TryParse(raw, out var count))
            throw new VerbException("initAlive: '" + raw + "' is not a whole number");
        if (count <= 0)
            throw new VerbException("initAlive: need at least one UUT, got " + count);
        ctx.InitAlive(count);
        ctx.Log("Alive mask initialised with " + count + " unit(s).");
    }

    /// <summary>
    /// Index the program's labels.
    /// </summary>
    /// <remarks>
    /// Kept for table compatibility only. v2 builds the label index at load
    /// time, so this reports what was already found; v1 rescanned the whole
    /// table here on every run.
    /// </remarks>
    [Verb(Module, "updateLabels", ConfigOnly = true)]
    public static void UpdateLabels(RunContext ctx, Row row)
    {
        ctx.Log("Labels indexed: " + ctx.Program.Labels.Count);
        var (start, end) = ctx.Program.Span;
        ctx.Log("Test span: " + (end - start) + " rows");
    }

    [Verb(Module, "STARTALIVE")]
    public static void StartAlive(RunContext ctx, Row row)
    {
        if (ctx.Alive.Count == 0)
            throw new VerbException(
                "STARTALIVE: alive mask not sized -- call initAlive first");
        ctx.StartAlive();
        ctx.Log("All units alive.");
    }

    [Verb(Module, "AKILL", Args = "2:targets")]
    public static void Kill(RunContext ctx, Row row)
    {
        var targets = ctx.Text(row.Raw(2))
                         .Split(',', StringSplitOptions.RemoveEmptyEntries)
                         .Select(t => t.Trim()).Where(t => t.Length > 0).ToList();
        if (targets.Count == 0) throw new VerbException("AKILL: no targets given");

        foreach (var target in targets)
        {
            if (!int.TryParse(target, out var index))
                throw new VerbException("AKILL: '" + target + "' is not a UUT index");
            ctx.Kill(index, row.Comment.Length > 0 ? row.Comment : "AKILL");
        }
    }

    [Verb(Module, "INITDATA", Args = "2:lines,3:cols,4:pages")]
    public static void InitData(RunContext ctx, Row row)
    {
        if (!int.TryParse(ctx.Text(row.Raw(2)), out var lines)
            || !int.TryParse(ctx.Text(row.Raw(3)), out var cols)
            || !int.TryParse(ctx.Text(row.Raw(4)), out var pages))
            throw new VerbException("INITDATA: dimensions must be whole numbers");
        if (Math.Min(lines, Math.Min(cols, pages)) <= 0)
            throw new VerbException("INITDATA: dimensions must be positive, got "
                + lines + "x" + cols + "x" + pages);

        ctx.InitData(lines, cols, pages);
        ctx.Log("Data initialised: " + lines + " lines, " + cols + " cols, "
                + pages + " pages.");
    }

    [Verb(Module, "SETDATACODES", Args = "2:datecode_index,3:extended_index")]
    public static void SetDatecodes(RunContext ctx, Row row)
    {
        var (date, time) = ctx.SetDatecodes();
        ctx.SetData(row.Raw(2), date);
        ctx.SetData(row.Raw(3), time);
        ctx.Log("Datecode: " + date + "  Extended: " + time);
    }

    /// <summary>
    /// Silence or restore the operator log.
    /// </summary>
    /// <remarks>
    /// Tables use this around polling loops that would otherwise flood the view.
    /// </remarks>
    [Verb(Module, "LOG_FLAG", Args = "2:state")]
    public static void LogFlag(RunContext ctx, Row row)
    {
        var state = ctx.Text(row.Raw(2)).Trim().ToUpperInvariant();
        if (state is not ("ON" or "OFF"))
            throw new VerbException("LOG_FLAG: expected ON or OFF, got '" + state + "'");
        ctx.LogEnabled = state == "ON";
        if (ctx.LogEnabled) ctx.Log("Logging resumed.");
    }

    [Verb(Module, "SAVELOG", Args = "2:path")]
    public static void SaveLog(RunContext ctx, Row row)
    {
        var path = ctx.Text(row.Raw(2));
        EnsureParent(path);
        var lines = ctx.Record.Steps.Select(s =>
            s.Started.ToString("HH:mm:ss") + " [" + s.Row + "] " + s.Module + "." + s.Verb
            + " -> " + s.Outcome + (s.Detail.Length > 0 ? ": " + s.Detail : ""));
        try { File.WriteAllLines(path, lines); }
        catch (Exception exc)
        {
            throw new VerbException("SAVELOG: cannot write '" + path + "': " + exc.Message,
                                    inner: exc);
        }
        ctx.Log("Log saved to " + path);
    }

    /// <summary>
    /// Dump the data store, one line per populated cell.
    /// </summary>
    /// <remarks>
    /// v1 hard-coded three columns here and silently dropped anything in column
    /// 3 or beyond. This walks the real dimensions.
    /// </remarks>
    [Verb(Module, "SAVEDATA", Args = "2:path")]
    public static void SaveData(RunContext ctx, Row row)
    {
        if (ctx.Data is null) throw new VerbException("SAVEDATA: data store not initialised");
        var path = ctx.Text(row.Raw(2));
        EnsureParent(path);

        var (lines, cols, pages) = ctx.Dims;
        var output = new List<string>();
        for (var page = 0; page < pages; page++)
        {
            output.Add("PAGE " + page + "::");
            for (var line = 0; line < lines; line++)
            {
                var cells = Enumerable.Range(0, cols).Select(c => ctx.Data[line, c, page]).ToList();
                if (cells.All(c => c is null)) continue;
                output.Add(string.Join("\t|| ", cells.Select((value, c) =>
                    "[" + line + "," + c + "," + page + "]: " + (value?.ToString() ?? "-"))));
            }
        }

        try { File.WriteAllLines(path, output); }
        catch (Exception exc)
        {
            throw new VerbException("SAVEDATA: cannot write '" + path + "': " + exc.Message,
                                    inner: exc);
        }
        ctx.Log("Data saved to " + path);
    }

    /// <summary>
    /// Write the structured run record.
    /// </summary>
    /// <remarks>
    /// Generated from recorded points rather than by re-reading the data store,
    /// so nothing overwritten mid-run is lost.
    /// </remarks>
    [Verb(Module, "SAVEREPORT", Args = "2:path,3:format?")]
    public static void SaveReport(RunContext ctx, Row row)
    {
        var path = ctx.Text(row.Raw(2));
        var format = ctx.Text(row.Raw(3));
        if (format.Length == 0) format = "json";
        try { Reports.Write(ctx.Record, path, format); }
        catch (ArgumentException exc)
        {
            throw new VerbException("SAVEREPORT: " + exc.Message, inner: exc);
        }
        ctx.Log("Report (" + format + ") saved to " + path);
    }

    private static void EnsureParent(string path)
    {
        var parent = Path.GetDirectoryName(Path.GetFullPath(path));
        if (string.IsNullOrEmpty(parent)) return;
        try { Directory.CreateDirectory(parent); }
        catch (Exception exc)
        {
            throw new VerbException(
                "cannot create directory '" + parent + "': " + exc.Message, inner: exc);
        }
    }
}
