using System.Globalization;
using Ngeoltx.Engine;

namespace Ngeoltx.Drivers;

/// <summary>
/// Control flow, arithmetic, strings, files and limit evaluation.
/// </summary>
/// <remarks>
/// Registered as FlowManager so existing Modules lines keep resolving.
///
/// The evaluation verbs do three things at once: store a result, paint a grid
/// row, and kill the UUT on failure. In v1 each of them repeated a four-way
/// <c>if kill_index == "0"/"1"/"2"/"3"</c> chain three times over -- twelve
/// near-identical blocks per verb. Here the grid is simply kill index plus one.
/// </remarks>
public static class FlowVerbs
{
    public const string Module = "FlowManager";

    // -- helpers -----------------------------------------------------------

    private static void JumpIf(RunContext ctx, Row row, bool condition)
    {
        var label = row.Raw(2);
        if (condition) { ctx.Log("Jumping to " + label); ctx.Jump(label); }
        else ctx.Log("Not jumping to " + label);
    }

    private static (string First, string Second) Pair(RunContext ctx, string cell, string what)
    {
        var parts = ctx.Text(cell).Split(',').Select(p => p.Trim()).ToList();
        if (parts.Count != 2)
            throw new VerbException(
                what + ": expected two comma-separated values, got '" + cell + "'");
        return (parts[0], parts[1]);
    }

    /// <summary>
    /// Decimal, falling back to hexadecimal -- v1's to_float.
    /// </summary>
    /// <remarks>
    /// Only JL uses this, and only because it has to: the cargo fixture's
    /// control board answers its detection poll in hex ("1F" is 31, that is
    /// 16 plus all four slots occupied), and a plain parse rejects it.
    ///
    /// The decimal-first order is v1's and is kept deliberately, but note what
    /// it implies: a reply of "10" parses as ten, not sixteen. Any reply whose
    /// digits are all 0-9 reads as decimal; only replies containing A-F read as
    /// hex. That ambiguity is inherent to an unprefixed hex value and cannot be
    /// resolved by a cleverer parser -- if the board can answer "10", the table
    /// needs an explicit radix.
    /// </remarks>
    private static double NumberOrHex(RunContext ctx, string cell, string what)
    {
        var raw = ctx.Text(cell).Trim();
        if (double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture,
                            out var value))
            return value;
        if (long.TryParse(raw, NumberStyles.HexNumber, CultureInfo.InvariantCulture,
                          out var hex))
            return hex;
        throw new VerbException(
            what + ": '" + raw + "' is neither a decimal nor a hex number");
    }

    // -- jumps -------------------------------------------------------------

    [Verb(Module, "J", Args = "2:label")]
    public static void Jump(RunContext ctx, Row row) => JumpIf(ctx, row, true);

    [Verb(Module, "JC", Args = "2:label,3:haystack,4:needle")]
    public static void JumpContains(RunContext ctx, Row row) =>
        JumpIf(ctx, row, ctx.Text(row.Raw(3)).Contains(ctx.Text(row.Raw(4))));

    [Verb(Module, "JCM", Args = "2:label,3:haystack,4:needles")]
    public static void JumpContainsAll(RunContext ctx, Row row)
    {
        var haystack = ctx.Text(row.Raw(3));
        var words = ctx.Text(row.Raw(4)).Split(';', StringSplitOptions.RemoveEmptyEntries);
        JumpIf(ctx, row, words.All(haystack.Contains));
    }

    [Verb(Module, "JNC", Args = "2:label,3:haystack,4:needle")]
    public static void JumpNotContains(RunContext ctx, Row row) =>
        JumpIf(ctx, row, !ctx.Text(row.Raw(3)).Contains(ctx.Text(row.Raw(4))));

    [Verb(Module, "JE", Args = "2:label,3:a,4:b")]
    public static void JumpEqual(RunContext ctx, Row row) =>
        JumpIf(ctx, row, ctx.Text(row.Raw(3)) == ctx.Text(row.Raw(4)));

    [Verb(Module, "JNE", Args = "2:label,3:a,4:b")]
    public static void JumpNotEqual(RunContext ctx, Row row) =>
        JumpIf(ctx, row, ctx.Text(row.Raw(3)) != ctx.Text(row.Raw(4)));

    [Verb(Module, "JET", Args = "2:label,3:a,4:b,5:tolerance")]
    public static void JumpEqualTolerance(RunContext ctx, Row row) =>
        JumpIf(ctx, row, Math.Abs(ctx.Number(row.Raw(3), "JET") - ctx.Number(row.Raw(4), "JET"))
                         <= Math.Abs(ctx.Number(row.Raw(5), "JET")));

    [Verb(Module, "JNET", Args = "2:label,3:a,4:b,5:tolerance")]
    public static void JumpNotEqualTolerance(RunContext ctx, Row row) =>
        JumpIf(ctx, row, Math.Abs(ctx.Number(row.Raw(3), "JNET") - ctx.Number(row.Raw(4), "JNET"))
                         > Math.Abs(ctx.Number(row.Raw(5), "JNET")));

    [Verb(Module, "JG", Args = "2:label,3:a,4:b")]
    public static void JumpGreater(RunContext ctx, Row row) =>
        JumpIf(ctx, row, ctx.Number(row.Raw(3), "JG") > ctx.Number(row.Raw(4), "JG"));

    /// <summary>Jump if less. Accepts hex, which the detection poll returns.</summary>
    [Verb(Module, "JL", Args = "2:label,3:a,4:b")]
    public static void JumpLess(RunContext ctx, Row row) =>
        JumpIf(ctx, row, NumberOrHex(ctx, row.Raw(3), "JL")
                         < NumberOrHex(ctx, row.Raw(4), "JL"));

    [Verb(Module, "JGE", Args = "2:label,3:a,4:b")]
    public static void JumpGreaterEqual(RunContext ctx, Row row) =>
        JumpIf(ctx, row, ctx.Number(row.Raw(3), "JGE") >= ctx.Number(row.Raw(4), "JGE"));

    [Verb(Module, "JLE", Args = "2:label,3:a,4:b")]
    public static void JumpLessEqual(RunContext ctx, Row row) =>
        JumpIf(ctx, row, ctx.Number(row.Raw(3), "JLE") <= ctx.Number(row.Raw(4), "JLE"));

    /// <summary>A jump target, optionally updating the status banner.</summary>
    [Verb(Module, "LABEL", Args = "2:name,3:status?,5:colour?")]
    public static void Label(RunContext ctx, Row row)
    {
        var text = ctx.Text(row.Raw(3));
        var colour = ctx.Text(row.Raw(5));
        if (text.Length > 0)
            ctx.Emit(new StatusEvent(text, colour.Length > 0 ? colour : null));
        ctx.Log("== " + row.Raw(2) + " ==");
    }

    // -- timing ------------------------------------------------------------

    /// <summary>
    /// Wait, staying responsive to a stop request.
    /// </summary>
    /// <remarks>
    /// Chunked so pressing stop takes effect within 50 ms rather than at the end
    /// of a multi-second delay.
    /// </remarks>
    [Verb(Module, "DELAY", Args = "2:seconds")]
    public static void Delay(RunContext ctx, Row row)
    {
        var seconds = ctx.Number(row.Raw(2), "DELAY");
        if (seconds < 0)
            throw new VerbException("DELAY: negative duration " + seconds);
        ctx.Log("Delay " + seconds + "s");

        var deadline = DateTime.UtcNow.AddSeconds(seconds);
        while (DateTime.UtcNow < deadline)
        {
            if (ctx.StopToken.IsCancellationRequested) return;
            var remaining = (deadline - DateTime.UtcNow).TotalMilliseconds;
            Thread.Sleep((int)Math.Clamp(remaining, 0, 50));
        }
    }

    [Verb(Module, "RESET_TIMER")]
    public static void ResetTimer(RunContext ctx, Row row)
    {
        ctx.DriverState("flow")["started"] = DateTime.UtcNow;
        ctx.Emit(new TimerEvent(0));
    }

    [Verb(Module, "ENABLE_TIMER")]
    public static void EnableTimer(RunContext ctx, Row row)
    {
        ctx.DriverState("flow")["timer"] = true;
        ctx.DriverState("flow").TryAdd("started", DateTime.UtcNow);
    }

    [Verb(Module, "DISABLE_TIMER")]
    public static void DisableTimer(RunContext ctx, Row row) =>
        ctx.DriverState("flow")["timer"] = false;

    [Verb(Module, "START_TIME", Args = "2:index")]
    public static void StartTime(RunContext ctx, Row row) =>
        ctx.SetData(row.Raw(2), DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss"));

    // -- data movement ------------------------------------------------------

    [Verb(Module, "STORE", Args = "2:value,3:index")]
    public static void Store(RunContext ctx, Row row) =>
        ctx.SetData(row.Raw(3), ctx.Text(row.Raw(2)));

    /// <summary>
    /// Store a formatted string.
    /// </summary>
    /// <remarks>
    /// "template;arg0;arg1" with %0 and %1 placeholders. Used heavily to build
    /// log paths.
    /// </remarks>
    [Verb(Module, "STOREF", Args = "2:template,3:index")]
    public static void StoreFormatted(RunContext ctx, Row row)
    {
        var parts = row.Raw(2).Split(';');
        var template = parts[0];
        for (var i = 1; i < parts.Length; i++)
            template = template.Replace("%" + (i - 1), ctx.Text(parts[i]));
        ctx.SetData(row.Raw(3), template);
    }

    [Verb(Module, "COPY", Args = "2:source,3:dest")]
    public static void Copy(RunContext ctx, Row row) =>
        ctx.SetData(row.Raw(3), ctx.Text(row.Raw(2)));

    // -- arithmetic ---------------------------------------------------------

    [Verb(Module, "ADD", Args = "2:dest,3:a,4:b")]
    public static void Add(RunContext ctx, Row row) =>
        ctx.SetData(row.Raw(2), ctx.Number(row.Raw(3), "ADD") + ctx.Number(row.Raw(4), "ADD"));

    [Verb(Module, "SUB", Args = "2:dest,3:a,4:b")]
    public static void Subtract(RunContext ctx, Row row) =>
        ctx.SetData(row.Raw(2), ctx.Number(row.Raw(3), "SUB") - ctx.Number(row.Raw(4), "SUB"));

    [Verb(Module, "MULT", Args = "2:dest,3:a,4:b")]
    public static void Multiply(RunContext ctx, Row row) =>
        ctx.SetData(row.Raw(2), ctx.Number(row.Raw(3), "MULT") * ctx.Number(row.Raw(4), "MULT"));

    [Verb(Module, "DIV", Args = "2:dest,3:a,4:b")]
    public static void Divide(RunContext ctx, Row row)
    {
        var divisor = ctx.Number(row.Raw(4), "DIV");
        if (divisor == 0) throw new VerbException("DIV: division by zero");
        ctx.SetData(row.Raw(2), ctx.Number(row.Raw(3), "DIV") / divisor);
    }

    // -- strings ------------------------------------------------------------

    [Verb(Module, "EQUAL", Args = "2:a,3:b,4:dest,5:if_true,6:if_false")]
    public static void Equal(RunContext ctx, Row row)
    {
        var hit = ctx.Text(row.Raw(2)) == ctx.Text(row.Raw(3));
        ctx.SetData(row.Raw(4), ctx.Text(hit ? row.Raw(5) : row.Raw(6)));
    }

    [Verb(Module, "CONTAIN", Args = "2:haystack,3:needle,4:dest,5:if_true,6:if_false")]
    public static void Contain(RunContext ctx, Row row)
    {
        var hit = ctx.Text(row.Raw(2)).Contains(ctx.Text(row.Raw(3)));
        ctx.SetData(row.Raw(4), ctx.Text(hit ? row.Raw(5) : row.Raw(6)));
    }

    [Verb(Module, "REPLACE", Args = "2:index,3:find,4:replace")]
    public static void Replace(RunContext ctx, Row row)
    {
        var current = ctx.GetData(row.Raw(2))?.ToString() ?? "";
        ctx.SetData(row.Raw(2),
            current.Replace(ctx.Text(row.Raw(3)), ctx.Text(row.Raw(4))));
    }

    [Verb(Module, "SUBSTRING", Args = "2:source,3:start,4:end,5:dest")]
    public static void Substring(RunContext ctx, Row row)
    {
        var text = ctx.Text(row.Raw(2));
        if (!int.TryParse(ctx.Text(row.Raw(3)), out var start)
            || !int.TryParse(ctx.Text(row.Raw(4)), out var end))
            throw new VerbException("SUBSTRING: start and end must be whole numbers");
        if (start < 0 || end > text.Length || start > end)
            throw new VerbException("SUBSTRING: [" + start + ":" + end
                + "] is outside a string of length " + text.Length);
        ctx.SetData(row.Raw(5), text[start..end]);
    }

    [Verb(Module, "COUNT", Args = "2:haystack,3:needle,4:dest")]
    public static void Count(RunContext ctx, Row row)
    {
        var haystack = ctx.Text(row.Raw(2));
        var needle = ctx.Text(row.Raw(3));
        if (needle.Length == 0) { ctx.SetData(row.Raw(4), 0); return; }

        var count = 0;
        for (var i = haystack.IndexOf(needle, StringComparison.Ordinal); i >= 0;
             i = haystack.IndexOf(needle, i + needle.Length, StringComparison.Ordinal))
            count++;
        ctx.SetData(row.Raw(4), count);
    }

    // -- files ---------------------------------------------------------------

    [Verb(Module, "READTXT", Args = "2:path,3:dest")]
    public static void ReadText(RunContext ctx, Row row)
    {
        var path = ctx.Text(row.Raw(2));
        try { ctx.SetData(row.Raw(3), File.ReadAllText(path)); }
        catch (Exception exc)
        {
            throw new VerbException("READTXT: cannot read '" + path + "': " + exc.Message,
                                    inner: exc);
        }
    }

    private static void WriteText(RunContext ctx, Row row, bool append, string what)
    {
        var path = ctx.Text(row.Raw(2));
        try
        {
            var parent = Path.GetDirectoryName(Path.GetFullPath(path));
            if (!string.IsNullOrEmpty(parent)) Directory.CreateDirectory(parent);
            if (append) File.AppendAllText(path, ctx.Text(row.Raw(3)));
            else File.WriteAllText(path, ctx.Text(row.Raw(3)));
        }
        catch (Exception exc)
        {
            throw new VerbException(what + ": cannot write '" + path + "': " + exc.Message,
                                    inner: exc);
        }
    }

    [Verb(Module, "WRITETXT", Args = "2:path,3:content")]
    public static void WriteTextVerb(RunContext ctx, Row row) =>
        WriteText(ctx, row, false, "WRITETXT");

    [Verb(Module, "APPENDTXT", Args = "2:path,3:content")]
    public static void AppendText(RunContext ctx, Row row) =>
        WriteText(ctx, row, true, "APPENDTXT");

    [Verb(Module, "DELFILE", Args = "2:path")]
    public static void DeleteFile(RunContext ctx, Row row)
    {
        var path = ctx.Text(row.Raw(2));
        if (Directory.Exists(path))
            throw new VerbException("DELFILE: '" + path + "' is a directory");
        try { if (File.Exists(path)) File.Delete(path); }
        catch (Exception exc)
        {
            throw new VerbException("DELFILE: cannot delete '" + path + "': " + exc.Message,
                                    inner: exc);
        }
    }

    [Verb(Module, "CREATEDIR", Args = "2:path")]
    public static void CreateDirectory(RunContext ctx, Row row)
    {
        var path = ctx.Text(row.Raw(2));
        try { Directory.CreateDirectory(path); }
        catch (Exception exc)
        {
            throw new VerbException("CREATEDIR: cannot create '" + path + "': " + exc.Message,
                                    inner: exc);
        }
    }

    /// <summary>Alias of CREATEDIR, because both names appear in legacy tables.</summary>
    [Verb(Module, "MAKEDIR", Args = "2:path", Legacy = true)]
    public static void MakeDirectory(RunContext ctx, Row row) => CreateDirectory(ctx, row);

    [Verb(Module, "COPYFILE", Args = "2:source,3:dest")]
    public static void CopyFile(RunContext ctx, Row row)
    {
        var source = ctx.Text(row.Raw(2));
        var destination = ctx.Text(row.Raw(3));
        try
        {
            var parent = Path.GetDirectoryName(Path.GetFullPath(destination));
            if (!string.IsNullOrEmpty(parent)) Directory.CreateDirectory(parent);
            File.Copy(source, destination, true);
        }
        catch (Exception exc)
        {
            throw new VerbException(
                "COPYFILE: " + source + " -> " + destination + ": " + exc.Message, inner: exc);
        }
    }

    // -- evaluation -----------------------------------------------------------

    /// <summary>Judge a float against limits, record it, and kill on failure.</summary>
    [Verb(Module, "EVAFLOAT",
          Args = "2:limits,3:value,4:result_indexes,5:grid_style?,6:kill_and_id")]
    public static void EvaluateFloat(RunContext ctx, Row row)
    {
        var (lowText, highText) = Pair(ctx, row.Raw(2), "EVAFLOAT limits");
        if (!double.TryParse(lowText, NumberStyles.Float, CultureInfo.InvariantCulture,
                             out var low)
            || !double.TryParse(highText, NumberStyles.Float, CultureInfo.InvariantCulture,
                                out var high))
            throw new VerbException("EVAFLOAT: limits '" + row.Raw(2) + "' are not numbers");
        if (low > high)
            throw new VerbException(
                "EVAFLOAT: lower limit " + low + " exceeds upper limit " + high);

        var (killIndex, testId) = KillAndId(ctx, row);
        var style = ctx.Text(row.Raw(5));
        var raw = ctx.Text(row.Raw(3));

        if (!double.TryParse(raw, NumberStyles.Float, CultureInfo.InvariantCulture,
                             out var measured))
        {
            // An unreadable measurement is a failure, not a crash -- the same as
            // v1, but without the malformed grid row v1 produced on this path.
            ctx.Log(testId + ": '" + raw + "' is not a number -> FAIL", "fail");
            StoreTriplet(ctx, row.Raw(4), "None", "FAIL", testId);
            Publish(ctx, row, killIndex, testId, low, high, "None", "FAIL", style);
            return;
        }

        var result = measured >= low && measured <= high ? "PASS" : "FAIL";
        ctx.Log(testId + ": " + measured + " in [" + low + ", " + high + "] -> " + result,
                result == "PASS" ? "pass" : "fail");
        StoreTriplet(ctx, row.Raw(4), measured.ToString("0.######",
            CultureInfo.InvariantCulture), result, testId);
        Publish(ctx, row, killIndex, testId, low, high, measured, result, style);
    }

    [Verb(Module, "EVACSTR",
          Args = "2:target,3:value,4:result_indexes,5:grid_style?,6:kill_and_id")]
    public static void EvaluateString(RunContext ctx, Row row)
    {
        var target = ctx.Text(row.Raw(2));
        var measured = ctx.Text(row.Raw(3));
        var (killIndex, testId) = KillAndId(ctx, row);
        var style = ctx.Text(row.Raw(5));

        var result = target == measured ? "PASS" : "FAIL";
        ctx.Log(testId + ": '" + measured + "' vs '" + target + "' -> " + result,
                result == "PASS" ? "pass" : "fail");
        StoreTriplet(ctx, row.Raw(4), measured, result, testId);
        Publish(ctx, row, killIndex, testId, target, target, measured, result, style);
    }

    /// <summary>Limit check that branches instead of killing.</summary>
    [Verb(Module, "EVALIM", Args = "2:value,3:limits,4:dest,5:jumps?,6:arg?")]
    public static void EvaluateLimit(RunContext ctx, Row row)
    {
        var (lowText, highText) = Pair(ctx, row.Raw(3), "EVALIM limits");
        if (!double.TryParse(lowText, NumberStyles.Float, CultureInfo.InvariantCulture,
                             out var low)
            || !double.TryParse(highText, NumberStyles.Float, CultureInfo.InvariantCulture,
                                out var high))
            throw new VerbException("EVALIM: limits '" + row.Raw(3) + "' are not numbers");

        var measured = ctx.Number(row.Raw(2), "EVALIM");
        var ok = measured >= low && measured <= high;
        if (row.Has(4)) ctx.SetData(row.Raw(4), ok ? "PASS" : "FAIL");
        ctx.Log("EVALIM: " + measured + " in [" + low + ", " + high + "] -> "
                + (ok ? "PASS" : "FAIL"), ok ? "pass" : "fail");

        if (!row.Has(5)) return;
        var (good, bad) = Pair(ctx, row.Raw(5), "EVALIM jumps");
        var target = ok ? good : bad;
        if (target.Length > 0 && target != "-") ctx.Jump(target);
    }

    // -- shared tails ---------------------------------------------------------

    internal static (int KillIndex, string TestId) KillAndId(RunContext ctx, Row row)
    {
        var parts = ctx.Text(row.Raw(6)).Split(',').Select(p => p.Trim()).ToList();
        if (parts.Count < 2)
            throw new VerbException(
                row.Verb + ": column 6 must be 'kill_index,test_id', got '"
                + row.Raw(6) + "'");
        if (!int.TryParse(parts[0], out var killIndex))
            throw new VerbException(row.Verb + ": '" + parts[0] + "' is not a UUT index");
        // Field 1 only: cargo.ods writes "0,COLOR_A,min" and the id is COLOR_A.
        return (killIndex, parts[1]);
    }

    /// <summary>
    /// Write results, paint the grid, kill on failure -- once, for all evaluators.
    /// </summary>
    internal static void Publish(RunContext ctx, Row row, int killIndex, string testId,
                                 object low, object high, object measured, string result,
                                 string style)
    {
        var device = (killIndex + 1).ToString();
        var values = style == "min"
            ? new List<string> { testId, device, low.ToString() ?? "", high.ToString() ?? "",
                                 measured.ToString() ?? "", result }
            : new List<string> { testId, device, low.ToString() ?? "", "-",
                                 high.ToString() ?? "", measured.ToString() ?? "",
                                 "-", "-", result };

        ctx.Emit(new GridEvent(killIndex + 1, "add", values, result));
        ctx.Record.AddPoint(new TestPoint(testId, killIndex, result,
            measured.ToString() ?? "", low.ToString() ?? "", high.ToString() ?? "", row.Index));
        if (result == "FAIL") ctx.Kill(killIndex, testId);
    }

    /// <summary>
    /// Write value, result and test id to column 4's destinations.
    /// </summary>
    /// <remarks>
    /// Two forms, both in use: three explicit cells separated by semicolons, or
    /// one cell from which the other two are derived by incrementing the
    /// <em>column</em> -- v1's getTripleIndex, and what the cargo table writes.
    /// Supporting only the explicit form silently dropped the verdict, leaving
    /// the measured value stored with no result anywhere.
    /// </remarks>
    internal static void StoreTriplet(RunContext ctx, string cell, string measured,
                                      string result, string testId)
    {
        var raw = ctx.Text(cell).Trim();
        if (raw.Length == 0) return;

        var cells = raw.Split(';', StringSplitOptions.RemoveEmptyEntries)
                       .Select(c => c.Trim()).ToList();
        if (cells.Count == 1)
        {
            var parts = cells[0].Split(',').Select(p => p.Trim()).ToList();
            if (parts.Count == 3 && int.TryParse(parts[1], out var column))
                cells = Enumerable.Range(0, 3)
                    .Select(offset => parts[0] + "," + (column + offset) + "," + parts[2])
                    .ToList();
        }

        var payload = new[] { measured, result, testId };
        for (var i = 0; i < Math.Min(cells.Count, payload.Length); i++)
            ctx.SetData(cells[i], payload[i]);
    }
}
