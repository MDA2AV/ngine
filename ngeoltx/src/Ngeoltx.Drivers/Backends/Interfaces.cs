namespace Ngeoltx.Drivers.Backends;

/// <summary>
/// Hardware abstraction.
/// </summary>
/// <remarks>
/// Every instrument sits behind a small interface with two implementations: a
/// real one and a simulated one. The verb layer only ever sees the interface,
/// so a program runs unchanged on the bench, in CI, or on a laptop with nothing
/// plugged in.
///
/// v1 had no such seam -- <c>import serial</c> and <c>import mvIMPACT</c> sat
/// at module scope, so the application could not even be imported without the
/// vendor SDKs installed, let alone tested.
/// </remarks>
public interface ISerialPort : IDisposable
{
    bool IsOpen { get; }
    void Open();
    void Close();
    int Write(byte[] data);
    byte[] Read(int count);
    byte[] ReadLine();
    void ResetBuffers();
}

public interface IInstrument : IDisposable
{
    void Write(string command);
    string Query(string command);
}

/// <summary>
/// What the camera verbs need.
/// </summary>
/// <remarks>
/// Deliberately richer than get/set of scalar properties. Binning, a centred
/// area of interest and a white-balance parameter set are not independent
/// scalars, and a setter that cannot report "I could not apply that" is how a
/// camera ends up at its default geometry with every downstream coordinate
/// missing by a few hundred pixels.
/// </remarks>
public interface ICamera : IDisposable
{
    string Serial { get; }
    bool IsOpen { get; }
    void Open();
    void Close();

    /// <summary>Apply properties; report what stuck, what did not, and why.</summary>
    ConfigureResult Configure(IReadOnlyDictionary<string, double> properties);

    /// <summary>Set manual exposure; returns the value actually applied.</summary>
    double SetExposure(double microseconds);

    /// <summary>Calibrate and lock gains; returns (red, green, blue).</summary>
    (double Red, double Green, double Blue) CalibrateWhiteBalance(
        double exposureMicroseconds, int warmupFrames);

    (double Red, double Green, double Blue)? WhiteBalanceGains { get; }

    /// <summary>Grab a frame as an 8-bit BGR image.</summary>
    Frame Capture();
}

/// <param name="Applied">Properties that stuck, for the log.</param>
/// <param name="Ignored">
/// Properties the backend could not apply. Treated as an error by SETPROPS: a
/// silently dropped area of interest leaves the camera at its default geometry,
/// which still produces a perfectly good image of the wrong pixels.
/// </param>
/// <param name="Notes">
/// Properties that legitimately do not exist on this sensor -- focus and hue on
/// a BlueFOX. v1 ignores them too, so they must not fail a run.
/// </param>
public sealed record ConfigureResult(
    IReadOnlyDictionary<string, string> Applied,
    IReadOnlyList<string> Ignored,
    IReadOnlyList<string> Notes)
{
    public static ConfigureResult Empty => new(
        new Dictionary<string, string>(), Array.Empty<string>(), Array.Empty<string>());
}

/// <summary>
/// An 8-bit image, BGR interleaved or single-channel greyscale.
/// </summary>
/// <remarks>
/// A plain buffer rather than a library type, because the whole vision path
/// here is written in managed code -- see VisionVerbs. Pulling in a native
/// imaging library for threshold and blob detection would add a deployment
/// problem to a test station for no gain.
/// </remarks>
public sealed class Frame
{
    public Frame(int width, int height, int channels, byte[] pixels)
    {
        Width = width;
        Height = height;
        Channels = channels;
        Pixels = pixels;
    }

    public int Width { get; }
    public int Height { get; }
    public int Channels { get; }
    public byte[] Pixels { get; }

    public int Stride => Width * Channels;

    public byte At(int x, int y, int channel = 0) =>
        Pixels[y * Stride + x * Channels + channel];

    public static Frame Grey(int width, int height) =>
        new(width, height, 1, new byte[width * height]);

    /// <summary>Rec. 601 luma, the same weighting OpenCV's BGR2GRAY uses.</summary>
    public Frame ToGrey()
    {
        if (Channels == 1) return this;
        var grey = Grey(Width, Height);
        for (var y = 0; y < Height; y++)
            for (var x = 0; x < Width; x++)
            {
                var i = y * Stride + x * Channels;
                grey.Pixels[y * Width + x] = (byte)(
                    0.114 * Pixels[i] + 0.587 * Pixels[i + 1] + 0.299 * Pixels[i + 2]);
            }
        return grey;
    }

    public Frame Threshold(double level)
    {
        var source = ToGrey();
        var binary = Grey(Width, Height);
        for (var i = 0; i < source.Pixels.Length; i++)
            binary.Pixels[i] = source.Pixels[i] > level ? (byte)255 : (byte)0;
        return binary;
    }
}
