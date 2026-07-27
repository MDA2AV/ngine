using System.Text;
using Ngeoltx.Drivers.Backends;
using Ngeoltx.Engine;

namespace Ngeoltx.Drivers;

/// <summary>
/// Serial verbs, registered as WinSerialManager.
/// </summary>
/// <remarks>
/// v1 shipped 27 near-identical serial functions. Decoding the names shows they
/// are one operation with four independent switches:
/// <list type="bullet">
/// <item>READ or EXCHANGE -- read only, or write then read</item>
/// <item>LINE or BYTES -- text, or a comma-separated byte list</item>
/// <item>_LT_ -- read to a newline rather than a fixed byte count</item>
/// <item>_LV0.._LV3 and _LVS -- what to do with the response: store it, judge
/// it, judge with retries, judge and kill the UUT, or strict (retry then throw)</item>
/// </list>
/// So there is one implementation here and 27 registered names that pre-bind a
/// combination. Fixing a bug in the retry logic now fixes it everywhere, which
/// was emphatically not true before.
/// </remarks>
public static class SerialVerbs
{
    public const string Module = "WinSerialManager";
    private const string State = "serial";

    private enum Op { Read, Exchange }
    private enum Payload { Line, Bytes }

    // -- port table ---------------------------------------------------------

    private static Dictionary<string, ISerialPort> Ports(RunContext ctx)
    {
        var state = ctx.DriverState(State);
        if (!state.TryGetValue("ports", out var value) || value is null)
            state["ports"] = value = new Dictionary<string, ISerialPort>();
        return (Dictionary<string, ISerialPort>)value;
    }

    private static ISerialPort Port(RunContext ctx, string id)
    {
        var ports = Ports(ctx);
        if (ports.TryGetValue(id, out var port)) return port;
        var known = ports.Count > 0 ? string.Join(", ", ports.Keys.OrderBy(k => k))
                                    : "none opened";
        throw new VerbException("serial port '" + id + "' is not open (known: " + known + ")");
    }

    [Verb(Module, "RESETPORTLIST", ConfigOnly = true)]
    public static void ResetPortList(RunContext ctx, Row row)
    {
        foreach (var port in Ports(ctx).Values)
            try { port.Close(); } catch { /* closing must not abort a run */ }
        Ports(ctx).Clear();
        ctx.Log("Serial port list reset.");
    }

    /// <summary>
    /// Locate a port by its USB hardware id and bind it to a name.
    /// </summary>
    /// <remarks>
    /// Matching is a substring test on the full hardware id. v1 sliced
    /// <c>hwid[26:]</c> and compared for equality -- a magic offset that broke
    /// whenever the driver reported a slightly different prefix.
    /// </remarks>
    [Verb(Module, "FINDPORT", Args = "2:baud_timeout,3:hwid,4:id", ConfigOnly = true)]
    public static void FindPort(RunContext ctx, Row row)
    {
        var parts = ctx.Text(row.Raw(2)).Split(',');
        if (parts.Length < 1 || !int.TryParse(parts[0].Trim(), out var baudRate))
            throw new VerbException(
                "FINDPORT: '" + row.Raw(2) + "' is not 'baudrate,timeout'");
        var timeout = parts.Length > 1 && double.TryParse(parts[1].Trim(), out var t) ? t : 1.0;

        var target = ctx.Text(row.Raw(3)).Trim();
        var id = ctx.Text(row.Raw(4)).Trim();
        if (id.Length == 0) throw new VerbException("FINDPORT: no id given for the port");

        var available = Hardware.ListSerialPorts(ctx.Simulate);
        foreach (var (device, description, hardwareId) in available)
        {
            if (target.Length > 0 && !hardwareId.Contains(target)
                && !description.Contains(target)) continue;
            Ports(ctx)[id] = Hardware.MakeSerial(ctx.Simulate, device, baudRate, timeout);
            ctx.Log("Port " + device + " bound to '" + id + "' (" + description + ")");
            return;
        }

        var listing = available.Count > 0
            ? string.Join(", ", available.Select(p => p.Device + " [" + p.HardwareId + "]"))
            : "none";
        throw new HardwareException(
            "FINDPORT: no serial port matching '" + target + "' for id '" + id
            + "'. Available: " + listing);
    }

    [Verb(Module, "OPEN", Args = "2:id")]
    public static void OpenPort(RunContext ctx, Row row)
    {
        var port = Port(ctx, ctx.Text(row.Raw(2)));
        if (port.IsOpen) port.Close();
        port.Open();
        port.ResetBuffers();
    }

    [Verb(Module, "CLOSE", Args = "2:id")]
    public static void ClosePort(RunContext ctx, Row row)
    {
        var port = Port(ctx, ctx.Text(row.Raw(2)));
        if (port.IsOpen) port.Close();
    }

    // -- encoding -----------------------------------------------------------

    private static byte[] Encode(RunContext ctx, Payload payload, string cell, string what)
    {
        var text = ctx.Text(cell);
        if (payload == Payload.Line)
            // Tables write "/n" for a newline because a real newline cannot be
            // typed into a spreadsheet cell.
            return Encoding.Latin1.GetBytes(text.Replace("/n", "\n").Replace("/r", "\r"));

        var bytes = new List<byte>();
        foreach (var token in text.Split(',', StringSplitOptions.RemoveEmptyEntries))
        {
            var trimmed = token.Trim();
            if (trimmed.Length == 0) continue;
            if (!int.TryParse(trimmed, out var value))
                throw new VerbException(what + ": '" + trimmed + "' is not a byte value");
            if (value is < 0 or > 255)
                throw new VerbException(what + ": byte value " + value + " is outside 0-255");
            bytes.Add((byte)value);
        }
        return bytes.ToArray();
    }

    private static string Decode(Payload payload, byte[] raw) =>
        payload == Payload.Line
            ? Encoding.Latin1.GetString(raw).TrimEnd('\r', '\n')
            : string.Join(",", raw.Select(b => b.ToString()));

    private static bool Matches(Payload payload, string received, string target)
    {
        if (payload == Payload.Line) return received.Contains(target);   // substring, as v1
        var got = received.Split(',', StringSplitOptions.RemoveEmptyEntries);
        var want = target.Split(',', StringSplitOptions.RemoveEmptyEntries)
                         .Select(x => x.Trim()).ToArray();
        return got.Length == want.Length && got.SequenceEqual(want);
    }

    // -- the one implementation ----------------------------------------------

    private static void Transfer(RunContext ctx, Row row, Op op, Payload payload,
                                 bool lineTerminated, string level)
    {
        var id = ctx.Text(row.Raw(2));
        var port = Port(ctx, id);
        port.ResetBuffers();

        var readLine = lineTerminated || payload == Payload.Line;
        var extra = ctx.Text(row.Raw(5)).Split(',', StringSplitOptions.RemoveEmptyEntries)
                       .Select(x => x.Trim()).ToList();

        int byteCount = 0, tries = 1, killIndex = -1;
        var testName = "";

        if (level == "3")
        {
            if (extra.Count < 3)
                throw new VerbException(row.Verb
                    + ": column 5 must be 'tries,kill_index,test_name', got '"
                    + row.Raw(5) + "'");
            tries = int.Parse(extra[0]);
            killIndex = int.Parse(extra[1]);
            testName = extra[2];
        }
        else if (level is "S" or "2")
        {
            if (readLine) tries = extra.Count > 0 ? int.Parse(extra[0]) : 1;
            else
            {
                if (extra.Count < 2)
                    throw new VerbException(row.Verb
                        + ": column 5 must be 'nbytes,tries', got '" + row.Raw(5) + "'");
                byteCount = int.Parse(extra[0]);
                tries = int.Parse(extra[1]);
            }
        }
        else if (!readLine)
        {
            if (extra.Count == 0)
                throw new VerbException(row.Verb
                    + ": column 5 must give the byte count to read");
            byteCount = int.Parse(extra[0]);
        }

        if (tries < 1)
            throw new VerbException(row.Verb + ": tries must be at least 1, got " + tries);

        var message = op == Op.Exchange
            ? Encode(ctx, payload, row.Raw(3), row.Verb)
            : Array.Empty<byte>();
        var target = level == "0" ? "" : ctx.Text(row.Raw(4));

        var received = "";
        var matched = false;

        for (var attempt = 1; attempt <= tries; attempt++)
        {
            if (ctx.StopToken.IsCancellationRequested)
                throw new VerbException(row.Verb + ": stopped by operator");

            if (op == Op.Exchange)
            {
                ctx.Log(id + " << " + row.Raw(3)
                        + (tries > 1 ? " (attempt " + attempt + "/" + tries + ")" : ""));
                port.Write(message);
            }

            var raw = readLine ? port.ReadLine() : port.Read(byteCount);
            received = Decode(payload, raw);
            ctx.Log(id + " >> " + received);

            if (level == "0") break;
            if (Matches(payload, received, target)) { matched = true; break; }
        }

        ApplyLevel(ctx, row, level, matched, received, target, id, killIndex, testName);
    }

    /// <summary>Everything after the wire exchange: store, judge, kill, or throw.</summary>
    private static void ApplyLevel(RunContext ctx, Row row, string level, bool matched,
                                   string received, string target, string id,
                                   int killIndex, string testName)
    {
        if (level == "0")
        {
            if (row.Has(6)) ctx.SetData(row.Raw(6), received);
            return;
        }

        if (level == "S")
        {
            if (!matched)
                throw new VerbException(row.Verb + ": " + id + " never returned '"
                    + target + "' (last response '" + received + "')");
            return;
        }

        var result = matched ? "PASS" : "FAIL";
        var indexes = ctx.Text(row.Raw(6))
                         .Split(';', StringSplitOptions.RemoveEmptyEntries)
                         .Select(x => x.Trim()).ToList();
        if (indexes.Count == 0)
            throw new VerbException(row.Verb
                + ": column 6 must name where to store the result");

        ctx.SetData(indexes[0], result);
        if (indexes.Count > 1) ctx.SetData(indexes[1], received);

        var name = testName.Length > 0
            ? testName
            : id + ":" + (row.Comment.Length > 0 ? row.Comment : row.Verb);
        ctx.Record.AddPoint(new TestPoint(name, killIndex >= 0 ? killIndex : null, result,
                                          received, target, target, row.Index));
        ctx.Log(name + ": " + result, matched ? "pass" : "fail");

        if (level != "3") return;
        var grid = Math.Max(killIndex, 0) + 1;
        ctx.Emit(new GridEvent(grid, "add",
            new[] { name, grid.ToString(), target, target, received, result }, result));
        if (!matched && killIndex >= 0) ctx.Kill(killIndex, name);
    }

    // -- plain writes ---------------------------------------------------------

    [Verb(Module, "WRITE", Args = "2:id,3:text")]
    public static void Write(RunContext ctx, Row row)
    {
        var id = ctx.Text(row.Raw(2));
        ctx.Log(id + " << " + row.Raw(3));
        Port(ctx, id).Write(Encode(ctx, Payload.Line, row.Raw(3), row.Verb));
    }

    [Verb(Module, "WRITELINE", Args = "2:id,3:text")]
    public static void WriteLine(RunContext ctx, Row row)
    {
        var id = ctx.Text(row.Raw(2));
        var data = Encode(ctx, Payload.Line, row.Raw(3), row.Verb);
        if (data.Length == 0 || data[^1] != (byte)'\n')
            data = data.Concat(new[] { (byte)'\n' }).ToArray();
        ctx.Log(id + " << " + row.Raw(3));
        Port(ctx, id).Write(data);
    }

    [Verb(Module, "WRITEBYTES", Args = "2:id,3:bytes")]
    public static void WriteBytes(RunContext ctx, Row row)
    {
        var id = ctx.Text(row.Raw(2));
        ctx.Log(id + " << " + row.Raw(3));
        Port(ctx, id).Write(Encode(ctx, Payload.Bytes, row.Raw(3), row.Verb));
    }

    // -- the alias matrix ------------------------------------------------------

    private static readonly Param[] MatrixParams =
    {
        new(2, "id", true, "port name bound by FINDPORT"),
        new(3, "message", false, "text, or comma-separated bytes"),
        new(4, "target", false, "expected response (levels 1-3 and S)"),
        new(5, "extra", false, "tries / nbytes,tries / tries,kill_index,test_name"),
        new(6, "store", false, "destination index, or 'result;response'"),
    };

    /// <summary>Register every name in the four-switch matrix.</summary>
    public static void RegisterMatrix(VerbRegistry registry)
    {
        foreach (var (op, opName) in new[] { (Op.Read, "READ"), (Op.Exchange, "EXCHANGE") })
        foreach (var (payload, payName) in new[] { (Payload.Line, "LINE"), (Payload.Bytes, "BYTES") })
        foreach (var (lt, ltName) in new[] { (false, ""), (true, "_LT") })
        foreach (var level in new[] { "0", "1", "2", "3", "S" })
        {
            var name = opName + payName + ltName + "_LV" + level;
            Register(registry, name, op, payload, lt, level);
        }

        // LVS never carries the _LT infix in v1's naming: it always reads a line
        // for text and a fixed count for bytes.
        Register(registry, "EXCHANGELINE_LVS", Op.Exchange, Payload.Line, true, "S", true);
        Register(registry, "EXCHANGEBYTES_LVS", Op.Exchange, Payload.Bytes, false, "S", true);
        Register(registry, "READVKING", Op.Read, Payload.Line, true, "0", true);
    }

    private static void Register(VerbRegistry registry, string name, Op op, Payload payload,
                                 bool lineTerminated, string level, bool overwrite = false)
    {
        registry.Add(new VerbSpec
        {
            Module = Module,
            Name = name,
            Handler = (ctx, row) => Transfer(ctx, row, op, payload, lineTerminated, level),
            Params = MatrixParams,
            Legacy = true,
            Doc = op + " " + payload + (lineTerminated ? ", line-terminated" : "")
                  + ", validation level " + level,
        }, overwrite);
    }
}
