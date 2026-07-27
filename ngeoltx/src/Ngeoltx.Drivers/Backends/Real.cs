using System.IO.Ports;
using Ngeoltx.Engine;

namespace Ngeoltx.Drivers.Backends;

/// <summary>
/// Real instrument backends.
/// </summary>
/// <remarks>
/// Vendor access is resolved lazily so that importing the application -- or
/// running its tests -- never requires a driver stack to be present. v1 imported
/// pyserial, pyvisa and the camera SDK at module scope, which is why the app
/// could not start on a machine missing any one of them.
///
/// The camera here is a stub that fails loudly. The Balluff path in the Python
/// station carries knowledge learned against hardware -- 2x2 binning with a
/// centred area of interest, packed-pixel buffer geometry, white-balance gains
/// held in a parameter set -- and none of that can be re-derived without the
/// camera in front of you. It is deliberately not guessed at here.
/// </remarks>
public sealed class RealSerialPort : ISerialPort
{
    private readonly SerialPort _port;

    public RealSerialPort(string port, int baudRate, double timeoutSeconds)
    {
        try
        {
            _port = new SerialPort(port, baudRate)
            {
                ReadTimeout = (int)(timeoutSeconds * 1000),
                WriteTimeout = (int)(timeoutSeconds * 1000),
            };
            _port.Open();
        }
        catch (Exception exc)
        {
            throw new HardwareException(
                "cannot open serial port " + port + ": " + exc.Message, inner: exc);
        }
        Name = port;
    }

    public string Name { get; }
    public bool IsOpen => _port.IsOpen;

    public void Open()
    {
        if (!_port.IsOpen) _port.Open();
    }

    public void Close()
    {
        if (_port.IsOpen) _port.Close();
    }

    public void Dispose() => _port.Dispose();

    public int Write(byte[] data)
    {
        try
        {
            _port.Write(data, 0, data.Length);
            return data.Length;
        }
        catch (Exception exc)
        {
            throw new HardwareException("write failed on " + Name + ": " + exc.Message,
                                        inner: exc);
        }
    }

    public byte[] Read(int count)
    {
        var buffer = new byte[count];
        var read = 0;
        try
        {
            while (read < count)
            {
                var chunk = _port.Read(buffer, read, count - read);
                if (chunk <= 0) break;
                read += chunk;
            }
        }
        catch (TimeoutException) { /* a short read is a result, not a fault */ }
        catch (Exception exc)
        {
            throw new HardwareException("read failed on " + Name + ": " + exc.Message,
                                        inner: exc);
        }
        return buffer.Take(read).ToArray();
    }

    public byte[] ReadLine()
    {
        var bytes = new List<byte>();
        try
        {
            while (true)
            {
                var value = _port.ReadByte();
                if (value < 0) break;
                bytes.Add((byte)value);
                if (value == '\n') break;
            }
        }
        catch (TimeoutException) { /* return what arrived, as pyserial does */ }
        catch (Exception exc)
        {
            throw new HardwareException("readline failed on " + Name + ": " + exc.Message,
                                        inner: exc);
        }
        return bytes.ToArray();
    }

    public void ResetBuffers()
    {
        // Flushing must never abort a run.
        try { _port.DiscardInBuffer(); _port.DiscardOutBuffer(); }
        catch { /* ignored on purpose */ }
    }

    public static IReadOnlyList<(string Device, string Description, string HardwareId)> List()
    {
        // System.IO.Ports gives names only. Hardware ids come from WMI on
        // Windows, which is added where the station needs FINDPORT matching by
        // USB serial; the device name is enough to open a known port.
        return SerialPort.GetPortNames()
                         .Select(name => (name, name, name))
                         .ToList();
    }
}

/// <summary>
/// A VISA instrument.
/// </summary>
/// <remarks>
/// .NET has no in-box VISA. A station supplies one through an
/// <see cref="IInstrumentFactory"/> -- typically a thin wrapper over the
/// vendor's IVI library. Until one is registered this throws with instructions
/// rather than pretending to talk to a supply.
/// </remarks>
public interface IInstrumentFactory
{
    IReadOnlyList<string> Resources();
    IInstrument Open(string resource, int timeoutMilliseconds);
}

public static class Instruments
{
    public static IInstrumentFactory? Factory { get; set; }

    public static IInstrument Open(string resource, int timeoutMilliseconds)
    {
        if (Factory is null)
            throw new HardwareException(
                "no VISA backend is registered. Set Instruments.Factory to a wrapper "
                + "over the station's IVI/VISA library, or run with --simulate.");
        return Factory.Open(resource, timeoutMilliseconds);
    }

    public static IReadOnlyList<string> Resources() =>
        Factory?.Resources() ?? Array.Empty<string>();
}

/// <summary>
/// Placeholder for a real camera.
/// </summary>
/// <remarks>
/// Fails with an explanation instead of returning a plausible-looking frame.
/// A camera left at its default geometry still captures a perfectly good image
/// -- of the wrong pixels -- and every coordinate in the program then misses
/// with nothing in the log to say why. That failure mode is worse than an
/// outright refusal, so this refuses.
/// </remarks>
public sealed class UnavailableCamera : ICamera
{
    public UnavailableCamera(string serial) => Serial = serial;

    public string Serial { get; }
    public bool IsOpen => false;

    private HardwareException Unavailable() => new(
        "camera " + Serial + ": no camera backend is registered. The Balluff path "
        + "needs binning, a centred area of interest and User1 white balance, which "
        + "cannot be re-derived without the hardware -- register an ICamera "
        + "implementation, or run with --simulate.");

    public void Open() => throw Unavailable();
    public void Close() { }
    public void Dispose() { }
    public ConfigureResult Configure(IReadOnlyDictionary<string, double> properties) =>
        throw Unavailable();
    public double SetExposure(double microseconds) => throw Unavailable();
    public (double Red, double Green, double Blue) CalibrateWhiteBalance(
        double exposureMicroseconds, int warmupFrames) => throw Unavailable();
    public (double Red, double Green, double Blue)? WhiteBalanceGains => null;
    public Frame Capture() => throw Unavailable();
}

/// <summary>
/// Chooses simulated or real hardware for every driver.
/// </summary>
/// <remarks>
/// Named Hardware rather than Backends because the enclosing namespace is
/// already Backends, and a type sharing its namespace's name cannot be
/// referenced from inside it.
/// </remarks>
public static class Hardware
{
    public static Func<string, ICamera>? CameraFactory { get; set; }

    public static ISerialPort MakeSerial(bool simulate, string port, int baudRate,
                                         double timeoutSeconds) =>
        simulate
            ? new SimSerialPort(port, baudRate, timeoutSeconds)
            : new RealSerialPort(port, baudRate, timeoutSeconds);

    public static IInstrument MakeInstrument(bool simulate, string resource,
                                             int timeoutMilliseconds = 10000) =>
        simulate ? new SimInstrument(resource) : Instruments.Open(resource, timeoutMilliseconds);

    public static ICamera MakeCamera(bool simulate, string serial) =>
        simulate ? new SimCamera(serial)
                 : CameraFactory?.Invoke(serial) ?? new UnavailableCamera(serial);

    public static IReadOnlyList<(string Device, string Description, string HardwareId)>
        ListSerialPorts(bool simulate) =>
        simulate
            ? Sim.Ports.Select(p => (p.Device, p.Description,
                                     "USB VID:PID=0483:5740 SER=" + p.HardwareId)).ToList()
            : RealSerialPort.List();
}
