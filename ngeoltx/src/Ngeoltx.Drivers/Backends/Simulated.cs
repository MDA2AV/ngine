using System.Text;
using System.Text.RegularExpressions;

namespace Ngeoltx.Drivers.Backends;

/// <summary>
/// Simulated instruments.
/// </summary>
/// <remarks>
/// Not stubs that return zeros. They model the fixture well enough to exercise
/// a real test program: the relay boards echo their command frames, the control
/// board answers the detection poll, and the supply tracks per-channel voltage
/// so a measurement reads back something consistent with what was written.
///
/// That fidelity is what lets a program be written and dry-run at a desk, and
/// lets tests assert on behaviour rather than on mocks.
/// </remarks>
public static class Sim
{
    /// <summary>
    /// Deterministic by default: a simulated run should be reproducible, so a
    /// failing test is a real failure rather than luck.
    /// </summary>
    public static Random Rng { get; private set; } = new(0xC0FFEE);

    public static void Seed(int seed) => Rng = new Random(seed);

    /// <summary>
    /// Devices keyed by the hardware id a program's FINDPORT looks for.
    /// Mirrors the cargo fixture: one control board and two relay boards.
    /// </summary>
    public static readonly (string HardwareId, string Device, string Description)[] Ports =
    {
        ("066CFF3833554B3043165348 LOCATION=1-1:x.2", "COM11", "Control board (sim)"),
        ("DAE006GCA", "COM12", "Denkovi DAE 1 (sim)"),
        ("DAE00646A", "COM13", "Denkovi DAE 2 (sim)"),
    };

    public static readonly string[] VisaResources =
        { "USB0::0x1AB1::0x0E11::DP2A243200206::INSTR" };

    public static readonly string[] Cameras = { "UB101256", "GX002467" };
}

public sealed class SimSerialPort : ISerialPort
{
    private readonly Lock _gate = new();
    private readonly List<byte> _rx = new();
    private readonly List<(Regex Pattern, byte[] Response)> _rules = new();
    private int _pollCount;

    public SimSerialPort(string port, int baudRate = 115200, double timeoutSeconds = 1.0,
                         int detectAfter = 2)
    {
        Port = port;
        BaudRate = baudRate;
        TimeoutSeconds = timeoutSeconds;
        DetectAfter = detectAfter;
        IsOpen = true;
    }

    public string Port { get; }
    public int BaudRate { get; }
    public double TimeoutSeconds { get; }

    /// <summary>How many detection polls before the simulated boards appear.</summary>
    public int DetectAfter { get; }

    public List<byte[]> History { get; } = new();
    public bool IsOpen { get; private set; }

    public void Open() => IsOpen = true;
    public void Close() => IsOpen = false;
    public void Dispose() => Close();

    public void ResetBuffers()
    {
        lock (_gate) _rx.Clear();
    }

    public void AddRule(string pattern, string response) =>
        _rules.Add((new Regex(pattern, RegexOptions.IgnoreCase | RegexOptions.Singleline),
                    Encoding.Latin1.GetBytes(response)));

    public int Write(byte[] data)
    {
        if (!IsOpen) throw new IOException("write to closed simulated port " + Port);
        lock (_gate)
        {
            History.Add(data.ToArray());
            _rx.AddRange(Respond(data));
        }
        return data.Length;
    }

    public byte[] Read(int count)
    {
        lock (_gate)
        {
            var take = Math.Min(count, _rx.Count);
            var result = _rx.Take(take).ToArray();
            _rx.RemoveRange(0, take);
            return result;
        }
    }

    public byte[] ReadLine()
    {
        var deadline = DateTime.UtcNow.AddSeconds(Math.Max(TimeoutSeconds, 0.01));
        while (true)
        {
            lock (_gate)
            {
                var index = _rx.IndexOf((byte)'\n');
                if (index >= 0)
                {
                    var line = _rx.Take(index + 1).ToArray();
                    _rx.RemoveRange(0, index + 1);
                    return line;
                }
                if (DateTime.UtcNow > deadline)
                {
                    var rest = _rx.ToArray();     // timeout: whatever arrived
                    _rx.Clear();
                    return rest;
                }
            }
            Thread.Sleep(1);
        }
    }

    private byte[] Respond(byte[] data)
    {
        var text = Encoding.Latin1.GetString(data);
        foreach (var (pattern, response) in _rules)
            if (pattern.IsMatch(text)) return response;

        // The control board answers the detection poll in HEX with 16 + a
        // 4-bit mask in which a SET bit means the slot is OCCUPIED -- so "1F"
        // is all four present and "10" an empty fixture. Both details were
        // confirmed against the bench, and both matter: an earlier model used
        // decimal and the opposite polarity, so a simulated run exercised the
        // reverse of what the hardware does.
        if (text.Trim() is "d" or "d\r")
        {
            _pollCount++;
            var present = _pollCount >= DetectAfter ? 0x0F : 0x00;
            return Encoding.ASCII.GetBytes((16 + present).ToString("X") + "\n");
        }
        if (text.Trim() is "r" or "r\r")
            return Encoding.ASCII.GetBytes("Outputs Reset\n");

        // Denkovi-style relay frames end with "//" and are echoed verbatim.
        if (data.Length >= 2 && data[^1] == (byte)'/' && data[^2] == (byte)'/')
            return data.Concat(new[] { (byte)'\n' }).ToArray();

        return data.Length > 0 && data[^1] == (byte)'\n'
            ? data
            : data.Concat(new[] { (byte)'\n' }).ToArray();
    }
}

/// <summary>
/// A simulated SCPI supply.
/// </summary>
/// <remarks>
/// Tracks per-channel setpoints and output state, so a program that sets 13.5 V
/// and then measures gets 13.5 V back plus a little noise, and one that measures
/// with the output off gets about zero. Behaviour a flat mock cannot give.
/// </remarks>
public sealed class SimInstrument : IInstrument
{
    private sealed class Channel
    {
        public double Volt, Curr;
        public bool Output;
    }

    private readonly Dictionary<int, Channel> _channels = new();
    private int _selected = 1;

    public SimInstrument(string resource, int channels = 3)
    {
        Resource = resource;
        for (var i = 1; i <= channels; i++) _channels[i] = new Channel();
    }

    public string Resource { get; }
    public List<string> History { get; } = new();

    public void Dispose() { }

    private Channel Current
    {
        get
        {
            if (!_channels.TryGetValue(_selected, out var channel))
                _channels[_selected] = channel = new Channel();
            return channel;
        }
    }

    public void Write(string command)
    {
        History.Add(command);
        var text = command.Trim().ToUpperInvariant();

        var select = Regex.Match(text, @"^INST(?::NSEL)?\s+(\d+)");
        if (select.Success) { _selected = int.Parse(select.Groups[1].Value); return; }

        var volt = Regex.Match(text, @"^VOLT\s+([\d.]+)");
        if (volt.Success) { Current.Volt = double.Parse(volt.Groups[1].Value); return; }

        var curr = Regex.Match(text, @"^CURR\s+([\d.]+)");
        if (curr.Success) { Current.Curr = double.Parse(curr.Groups[1].Value); return; }

        var output = Regex.Match(text, @"^OUTP(?:UT)?\s+(ON|OFF|1|0)");
        if (output.Success)
            Current.Output = output.Groups[1].Value is "ON" or "1";
    }

    public string Query(string command)
    {
        History.Add(command);
        var text = command.Trim().ToUpperInvariant();
        if (text.Contains("IDN"))
            return "RIGOL TECHNOLOGIES,DP832,SIM0001,00.01.16";

        var channel = Current;
        if (text.Contains("MEAS") && text.Contains("CURR"))
        {
            if (!channel.Output) return (Sim.Rng.NextDouble() * 1e-4).ToString("0.000000");
            // A plausible load: roughly a third of the compliance setting.
            var draw = channel.Curr > 0 ? channel.Curr * 0.33 : 0.15;
            return (draw + (Sim.Rng.NextDouble() - 0.5) * 0.004).ToString("0.000000");
        }
        if (text.Contains("MEAS"))
            return channel.Output
                ? (channel.Volt + (Sim.Rng.NextDouble() - 0.5) * 0.02).ToString("0.000000")
                : (Sim.Rng.NextDouble() * 0.002).ToString("0.000000");
        return "0";
    }
}

/// <summary>
/// Generates a synthetic scene with lit indicators.
/// </summary>
/// <remarks>
/// Four bright discs on a dark field, so the blob and LED verbs have something
/// real to find. <see cref="Lit"/> controls which are on, which lets a test
/// drive a failure without hardware.
/// </remarks>
public sealed class SimCamera : ICamera
{
    private (double Red, double Green, double Blue)? _gains;

    public SimCamera(string serial, int width = 640, int height = 480)
    {
        Serial = serial;
        Width = width;
        Height = height;
        Lit = new[] { true, true, true, true };
    }

    public string Serial { get; }
    public int Width { get; private set; }
    public int Height { get; private set; }
    public bool[] Lit { get; set; }
    public bool IsOpen { get; private set; }
    public Dictionary<string, double> Properties { get; } = new();

    public void Open() => IsOpen = true;
    public void Close() => IsOpen = false;
    public void Dispose() => Close();

    /// <summary>
    /// Accept everything, and honour the geometry.
    /// </summary>
    /// <remarks>
    /// Honouring width and height matters: a program that asks for 1296x972 and
    /// then evaluates a blob at (895, 659) must get a frame those coordinates
    /// fall inside, or the simulation tests nothing useful.
    /// </remarks>
    public ConfigureResult Configure(IReadOnlyDictionary<string, double> properties)
    {
        var applied = new Dictionary<string, string>();
        foreach (var (name, value) in properties)
        {
            Properties[name] = value;
            if (name == "width" && value > 0) Width = (int)value;
            if (name == "height" && value > 0) Height = (int)value;
            applied[name] = value.ToString("0.###");
        }
        return new ConfigureResult(applied, Array.Empty<string>(), Array.Empty<string>());
    }

    public double SetExposure(double microseconds)
    {
        Properties["exposure"] = microseconds;
        return microseconds;
    }

    public (double Red, double Green, double Blue) CalibrateWhiteBalance(
        double exposureMicroseconds, int warmupFrames)
    {
        SetExposure(exposureMicroseconds);
        _gains = (2.0, 1.0, 1.9);
        return _gains.Value;
    }

    public (double Red, double Green, double Blue)? WhiteBalanceGains => _gains;

    public Frame Capture()
    {
        if (!IsOpen) throw new IOException("capture from closed simulated camera " + Serial);

        var frame = new Frame(Width, Height, 3, new byte[Width * Height * 3]);
        for (var i = 0; i < frame.Pixels.Length; i++) frame.Pixels[i] = 18;

        var step = Width / (Lit.Length + 1);
        var radius = Math.Max(12, Math.Min(Height, step) / 5);
        for (var index = 0; index < Lit.Length; index++)
        {
            var cx = step * (index + 1);
            var cy = Height / 2;
            for (var y = Math.Max(cy - radius, 0); y < Math.Min(cy + radius, Height); y++)
                for (var x = Math.Max(cx - radius, 0); x < Math.Min(cx + radius, Width); x++)
                {
                    var dx = x - cx;
                    var dy = y - cy;
                    if (dx * dx + dy * dy > radius * radius) continue;
                    var offset = y * frame.Stride + x * 3;
                    frame.Pixels[offset] = Lit[index] ? (byte)60 : (byte)30;
                    frame.Pixels[offset + 1] = Lit[index] ? (byte)220 : (byte)30;
                    frame.Pixels[offset + 2] = Lit[index] ? (byte)90 : (byte)30;
                }
        }
        return frame;
    }
}
