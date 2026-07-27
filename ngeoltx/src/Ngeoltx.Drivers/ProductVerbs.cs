using System.Globalization;
using Ngeoltx.Engine;

namespace Ngeoltx.Drivers;

/// <summary>
/// Product-specific validators, registered as CargoManager.
/// </summary>
/// <remarks>
/// v1 kept these in CargoManager and 1211Manager, where VALIDATE_BCODE was
/// byte-for-byte identical between the two files. Written once here and aliased
/// under both names, so existing Modules lines keep working.
/// </remarks>
public static class ProductVerbs
{
    public const string Module = "CargoManager";

    /// <summary>
    /// Kill whichever UUTs the fixture reports as absent.
    /// </summary>
    /// <remarks>
    /// The control board answers the detection poll with 16 + mask, in <b>hex</b>
    /// -- "1F" on the cargo fixture. A set bit means the slot is <b>occupied</b>,
    /// so the units to kill are the ones whose bit is clear: 0x1F gives mask
    /// 0b1111, all four present, nothing killed.
    ///
    /// Worth stating because it is the opposite of what an earlier revision of
    /// the site driver did, and reading it backwards kills every good board on
    /// the fixture while looking like it worked.
    ///
    /// <para>Column 3 gives the radix. Leave it blank and the reading is parsed
    /// v1's way -- decimal, falling back to hex -- which is ambiguous for any
    /// answer made only of digits: an empty fixture replies "10", meaning
    /// sixteen, and the legacy parser reads ten. No parser can resolve that, so
    /// a table on a hex fixture should say <c>hex</c> and mean it. Existing
    /// tables leave the cell blank and behave exactly as they did.</para>
    /// </remarks>
    [Verb(Module, "VALIDATE_DET", Args = "2:detection_value,3:radix?")]
    public static void ValidateDetection(RunContext ctx, Row row)
    {
        var raw = ctx.Text(row.Raw(2)).Trim();
        var value = ToInt(raw, ctx.Text(row.Raw(3)), "VALIDATE_DET") - 16;
        if (value is < 0 or > 15)
            throw new VerbException("VALIDATE_DET: detection value " + value
                + " is outside 0-15 (raw reading was '" + raw + "')");

        var absent = Enumerable.Range(0, 4).Where(bit => (value & (1 << bit)) == 0).ToList();
        if (absent.Count == 0)
        {
            ctx.Log("Detection: all units present.");
            return;
        }
        foreach (var bit in absent.Where(b => b < ctx.Alive.Count))
            ctx.Kill(bit, "not detected");
        ctx.Log("Detection: unit(s) " + string.Join(", ", absent) + " absent.", "warn");
    }

    /// <summary>Parse a reading in the stated radix, or the legacy guess.</summary>
    private static int ToInt(string raw, string radix, string what)
    {
        switch (radix.Trim().ToLowerInvariant())
        {
            case "hex" or "16" or "0x":
                if (int.TryParse(raw, NumberStyles.HexNumber, CultureInfo.InvariantCulture,
                                 out var asHex))
                    return asHex;
                throw new VerbException(what + ": '" + raw + "' is not a hex value");

            case "dec" or "10":
                if (int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture,
                                 out var asDecimal))
                    return asDecimal;
                throw new VerbException(what + ": '" + raw + "' is not a decimal value");

            case "":
                // v1's to_int: decimal first, hex second.
                if (int.TryParse(raw, NumberStyles.Integer, CultureInfo.InvariantCulture,
                                 out var guessed))
                    return guessed;
                if (int.TryParse(raw, NumberStyles.HexNumber, CultureInfo.InvariantCulture,
                                 out var fallback))
                    return fallback;
                throw new VerbException(
                    what + ": '" + raw + "' is neither a decimal nor a hex value");

            default:
                throw new VerbException(
                    what + ": radix '" + radix + "' is not 'hex', 'dec', or blank");
        }
    }

    [Verb(Module, "VALIDATE_BCODE",
          Args = "2:barcode,3:result_indexes,4:length,5:eng_level,6:kill_index")]
    public static void ValidateBarcode(RunContext ctx, Row row)
    {
        var barcode = ctx.Text(row.Raw(2));
        var cells = ctx.Text(row.Raw(3)).Split(';', StringSplitOptions.RemoveEmptyEntries)
                       .Select(c => c.Trim()).Where(c => c.Length > 0).ToList();

        if (!TryWhole(ctx.Text(row.Raw(4)), out var targetLength)
            || !TryWhole(ctx.Text(row.Raw(6)), out var killIndex))
            throw new VerbException(
                "VALIDATE_BCODE: length and kill_index must be whole numbers");
        var targetLevel = ctx.Text(row.Raw(5));

        if (barcode.Length != targetLength)
        {
            Fail(ctx, row, cells, killIndex, "BCODE Length", targetLength, barcode.Length);
            return;
        }

        var level = targetLevel.Length > 0 && barcode.Length >= targetLevel.Length
            ? barcode[..targetLevel.Length] : "";
        if (targetLevel.Length > 0 && level != targetLevel)
        {
            Fail(ctx, row, cells, killIndex, "BCODE Eng Level", targetLevel, level);
            return;
        }

        Store(ctx, cells, barcode, "PASS", "Bcode");
        GridRow(ctx, killIndex, targetLevel.Length > 0 ? targetLevel : targetLength,
                barcode, "PASS");
        ctx.Record.AddPoint(new TestPoint("BCODE", killIndex, "PASS", barcode,
                                          Row: row.Index));
        ctx.Record.SetBarcode(killIndex, barcode);
        ctx.Log("Barcode " + barcode + " accepted for UUT " + killIndex + ".", "pass");
    }

    /// <summary>
    /// Final per-UUT verdict, derived from the recorded test points.
    /// </summary>
    /// <remarks>
    /// v1 re-read a hard-coded list of data coordinates per product to work out
    /// whether a unit passed, so the list had to be edited whenever the test plan
    /// changed, and any point written after its coordinate was reused was simply
    /// lost. Here the verdict comes from the run record: correct by construction
    /// and product-independent.
    /// </remarks>
    [Verb(Module, "VALIDATE", Args = "2:expected_points?,3:result_index?")]
    public static void Validate(RunContext ctx, Row row)
    {
        int? expected = null;
        if (row.Has(2))
        {
            if (!TryWhole(ctx.Text(row.Raw(2)), out var count))
                throw new VerbException(
                    "VALIDATE: '" + row.Raw(2) + "' is not a point count");
            expected = count;
        }

        var verdicts = new SortedDictionary<int, bool>();
        for (var uut = 0; uut < ctx.Alive.Count; uut++)
        {
            var points = ctx.Record.PointsFor(uut);
            var failed = points.Count(p => p.Result == "FAIL");
            var enough = expected is null || points.Count >= expected;
            var alive = ctx.Alive[uut] == 1;
            var ok = alive && failed == 0 && points.Count > 0 && enough;

            verdicts[uut] = ok;
            var detail = points.Count + " point(s)"
                + (failed > 0 ? ", " + failed + " failed" : "")
                + (alive ? "" : ", killed")
                + (enough ? "" : ", expected " + expected);
            ctx.Log("UUT " + uut + ": " + (ok ? "PASS" : "FAIL") + " (" + detail + ")",
                    ok ? "pass" : "fail");
            if (!ok && alive) ctx.Kill(uut, "final validation");
        }

        if (row.Has(3))
            ctx.SetData(row.Raw(3), string.Join(";",
                verdicts.Select(v => v.Key + "=" + (v.Value ? "PASS" : "FAIL"))));
    }

    // -- shared tails ---------------------------------------------------------

    private static bool TryWhole(string text, out int value)
    {
        value = 0;
        // Spreadsheet cells often hold "4" as "4.0"; v1 went through float too.
        if (!double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture,
                             out var number))
            return false;
        value = (int)number;
        return true;
    }

    private static void GridRow(RunContext ctx, int killIndex, object expected,
                                object measured, string result) =>
        ctx.Emit(new GridEvent(killIndex + 1, "add", new[]
        {
            "BCODE", (killIndex + 1).ToString(), "-", expected.ToString() ?? "",
            measured.ToString() ?? "", result,
        }, result));

    private static void Fail(RunContext ctx, Row row, IReadOnlyList<string> cells,
                             int killIndex, string name, object expected, object measured)
    {
        Store(ctx, cells, measured.ToString() ?? "", "FAIL", name);
        ctx.Emit(new GridEvent(killIndex + 1, "add", new[]
        {
            name, (killIndex + 1).ToString(), "-", expected.ToString() ?? "",
            measured.ToString() ?? "", "FAIL",
        }, "FAIL"));
        ctx.Record.AddPoint(new TestPoint(name, killIndex, "FAIL",
            measured.ToString() ?? "", expected.ToString() ?? "", Row: row.Index));
        ctx.Log(name + ": expected " + expected + ", got " + measured + " -> FAIL", "fail");
        ctx.Kill(killIndex, name);
    }

    private static void Store(RunContext ctx, IReadOnlyList<string> cells,
                              string value, string result, string name)
    {
        var payload = new[] { value, result, name };
        for (var i = 0; i < Math.Min(cells.Count, payload.Length); i++)
            ctx.SetData(cells[i], payload[i]);
    }
}
