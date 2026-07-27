using System.Globalization;
using Ngeoltx.Drivers.Backends;
using Ngeoltx.Engine;

namespace Ngeoltx.Drivers;

/// <summary>VISA / SCPI instrument verbs, registered as GlobalVISAManager.</summary>
public static class InstrumentVerbs
{
    public const string Module = "GlobalVISAManager";
    private const string State = "visa";

    private static Dictionary<string, IInstrument> Table(RunContext ctx)
    {
        var state = ctx.DriverState(State);
        if (!state.TryGetValue("instruments", out var value) || value is null)
            state["instruments"] = value = new Dictionary<string, IInstrument>();
        return (Dictionary<string, IInstrument>)value;
    }

    /// <summary>
    /// Resolve an instrument by the id a program uses, usually its serial.
    /// </summary>
    /// <remarks>
    /// In simulation an unknown id is created on demand, so a program can be
    /// dry-run without first describing the whole bench.
    /// </remarks>
    private static IInstrument Get(RunContext ctx, string id)
    {
        var instruments = Table(ctx);
        if (instruments.TryGetValue(id, out var found)) return found;

        foreach (var (resource, instrument) in instruments)
            if (id.Length > 0 && resource.Contains(id))
            {
                instruments[id] = instrument;
                return instrument;
            }

        if (ctx.Simulate)
        {
            var simulated = Hardware.MakeInstrument(true, "SIM::" + id + "::INSTR");
            instruments[id] = simulated;
            ctx.Log("VISA: simulating instrument '" + id + "'");
            return simulated;
        }

        var known = instruments.Count > 0
            ? string.Join(", ", instruments.Keys.OrderBy(k => k)) : "none";
        throw new HardwareException(
            "VISA instrument '" + id + "' was not opened (known: " + known + ")");
    }

    /// <summary>Enumerate the bus and open everything on it.</summary>
    [Verb(Module, "OPENALL", Args = "2:timeout_ms?,3:include_serial?", ConfigOnly = true)]
    public static void OpenAll(RunContext ctx, Row row)
    {
        var timeout = 10000;
        if (row.Has(2) && !int.TryParse(ctx.Text(row.Raw(2)), out timeout))
            throw new VerbException("OPENALL: '" + row.Raw(2) + "' is not a timeout in ms");
        ctx.DriverState(State)["timeout"] = timeout;

        var resources = (ctx.Simulate ? Sim.VisaResources : Instruments.Resources()).ToList();

        // ASRL resources are the machine's COM ports, which FINDPORT has already
        // opened by hardware id. Opening them through VISA as well yields a
        // resource-busy error at best and takes the port away from the running
        // test at worst. v1 filtered them with a `len(resource) < 40` heuristic;
        // filtering on the interface type says what it means.
        var includeSerial = ctx.Text(row.Raw(3)).Trim().ToUpperInvariant() is "ALL" or "SERIAL";
        if (!includeSerial)
        {
            var skipped = resources.Count(r => r.StartsWith("ASRL",
                StringComparison.OrdinalIgnoreCase));
            resources = resources.Where(r => !r.StartsWith("ASRL",
                StringComparison.OrdinalIgnoreCase)).ToList();
            if (skipped > 0)
                ctx.Log("VISA: ignoring " + skipped + " serial resource(s) "
                        + "(pass ALL in column 3 to include them)");
        }

        var instruments = Table(ctx);
        foreach (var resource in resources)
        {
            IInstrument instrument;
            try { instrument = Hardware.MakeInstrument(ctx.Simulate, resource, timeout); }
            catch (HardwareException exc)
            {
                ctx.Log("VISA: skipping " + resource + ": " + exc.Message, "warn");
                continue;
            }

            instruments[resource] = instrument;
            var identity = "";
            try { identity = instrument.Query("*IDN?"); } catch { /* optional */ }
            ctx.Log("VISA opened " + resource + " " + identity);

            // Index by serial too, since tables address instruments by serial.
            foreach (var part in resource.Split("::"))
                if (part.Length > 0 && part is not ("INSTR" or "USB0")
                    && !part.StartsWith("0x"))
                    instruments.TryAdd(part, instrument);
        }

        if (instruments.Count == 0) ctx.Log("VISA: no instruments found", "warn");
    }

    [Verb(Module, "WRITE", Args = "2:id,3:command")]
    public static void Write(RunContext ctx, Row row)
    {
        var id = ctx.Text(row.Raw(2));
        var command = ctx.Text(row.Raw(3));
        ctx.Log("VISA " + id + " << " + command);
        Get(ctx, id).Write(command);
    }

    [Verb(Module, "EXCHANGE", Args = "2:id,3:query,4:dest")]
    public static void Exchange(RunContext ctx, Row row)
    {
        var id = ctx.Text(row.Raw(2));
        var reply = Get(ctx, id).Query(ctx.Text(row.Raw(3)));
        ctx.Log("VISA " + id + " >> " + reply);
        ctx.SetData(row.Raw(4), reply);
    }

    /// <summary>One measurement. Destination is column 5, as in v1.</summary>
    [Verb(Module, "MEASURE", Args = "2:id,3:query,5:dest")]
    public static void Measure(RunContext ctx, Row row)
    {
        var id = ctx.Text(row.Raw(2));
        var value = AsDouble(Get(ctx, id).Query(ctx.Text(row.Raw(3))), row.Verb);
        ctx.Log("VISA " + id + " measured " + value);
        ctx.SetData(row.Raw(5), value);
    }

    [Verb(Module, "MASS_MEASURE", Args = "2:id,3:query,5:dests")]
    public static void MassMeasure(RunContext ctx, Row row)
    {
        var id = ctx.Text(row.Raw(2));
        var query = ctx.Text(row.Raw(3));
        var dests = ctx.Text(row.Raw(5)).Split(';', StringSplitOptions.RemoveEmptyEntries)
                       .Select(d => d.Trim()).Where(d => d.Length > 0).ToList();
        if (dests.Count == 0)
            throw new VerbException("MASS_MEASURE: no destination indexes given");

        var instrument = Get(ctx, id);
        foreach (var dest in dests)
            ctx.SetData(dest, AsDouble(instrument.Query(query), row.Verb));
    }

    /// <summary>
    /// Measure, judge against limits, record the point and kill on failure.
    /// </summary>
    /// <remarks>
    /// Retries are honoured: a value outside limits is re-measured before the
    /// UUT is failed, which is what the bench wants for a supply still settling.
    /// </remarks>
    [Verb(Module, "MEASURE_FEVAL", Args = "2:id,3:query,4:limits,5:dest,6:extra")]
    public static void MeasureAndEvaluate(RunContext ctx, Row row)
    {
        var id = ctx.Text(row.Raw(2));
        var query = ctx.Text(row.Raw(3));

        var limits = ctx.Text(row.Raw(4)).Split(',').Select(x => x.Trim()).ToList();
        if (limits.Count < 2)
            throw new VerbException("MEASURE_FEVAL: limits must be 'lower,upper', got '"
                + row.Raw(4) + "'");
        if (!double.TryParse(limits[0], NumberStyles.Float, CultureInfo.InvariantCulture,
                             out var low)
            || !double.TryParse(limits[1], NumberStyles.Float, CultureInfo.InvariantCulture,
                                out var high))
            throw new VerbException("MEASURE_FEVAL: limits '" + row.Raw(4)
                + "' are not numbers");

        var extra = ctx.Text(row.Raw(6)).Split(',', StringSplitOptions.RemoveEmptyEntries)
                       .Select(x => x.Trim()).ToList();
        if (extra.Count < 3)
            throw new VerbException(
                "MEASURE_FEVAL: column 6 must be 'tries,kill_index,test_name'");
        if (!int.TryParse(extra[0], out var tries) || !int.TryParse(extra[1], out var killIndex))
            throw new VerbException(
                "MEASURE_FEVAL: tries and kill_index must be whole numbers");
        tries = Math.Max(tries, 1);
        var testName = extra[2];

        var instrument = Get(ctx, id);
        var value = 0.0;
        for (var attempt = 1; attempt <= tries; attempt++)
        {
            value = AsDouble(instrument.Query(query), row.Verb);
            if (value >= low && value <= high) break;
            if (attempt < tries)
                ctx.Log(testName + ": " + value + " outside [" + low + ", " + high
                        + "], retry " + attempt + "/" + tries, "warn");
        }

        var result = value >= low && value <= high ? "PASS" : "FAIL";
        ctx.SetData(row.Raw(5), value);
        ctx.Log(testName + ": " + value + " in [" + low + ", " + high + "] -> " + result,
                result == "PASS" ? "pass" : "fail");
        ctx.Record.AddPoint(new TestPoint(testName, killIndex, result,
            value.ToString("0.######", CultureInfo.InvariantCulture),
            low.ToString(CultureInfo.InvariantCulture),
            high.ToString(CultureInfo.InvariantCulture), row.Index));
        ctx.Emit(new GridEvent(killIndex + 1, "add", new[]
        {
            testName, (killIndex + 1).ToString(), low.ToString(CultureInfo.InvariantCulture),
            high.ToString(CultureInfo.InvariantCulture),
            value.ToString("0.######", CultureInfo.InvariantCulture), result,
        }, result));
        if (result == "FAIL") ctx.Kill(killIndex, testName);
    }

    private static double AsDouble(string reply, string what)
    {
        var head = reply.Trim().Split(',')[0];
        if (double.TryParse(head, NumberStyles.Float, CultureInfo.InvariantCulture,
                            out var value))
            return value;
        throw new VerbException(
            what + ": instrument returned '" + reply + "', which is not a number");
    }
}
