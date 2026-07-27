using Ngeoltx.Drivers.Backends;
using Ngeoltx.Engine;

namespace Ngeoltx.Drivers;

/// <summary>
/// Camera verbs, registered as BaluffManager with CameraManager aliased.
/// </summary>
/// <remarks>
/// v1 kept two near-identical modules, one per camera family, and a table chose
/// between them by editing its Modules line. Both names still resolve here, and
/// the backend picks the SDK at open time.
///
/// The verbs talk to the backend through Configure, CalibrateWhiteBalance and
/// SetExposure rather than a generic set-property call. That distinction
/// matters: binning, a centred area of interest and a white-balance parameter
/// set are not independent scalars, and pretending otherwise is how a camera
/// ends up capturing a perfectly good image of the wrong pixels.
/// </remarks>
public static class CameraVerbs
{
    public const string Module = "BaluffManager";
    private const string State = "camera";

    /// <summary>SETPROPS packs its values into four comma-separated groups.</summary>
    private static readonly (int Column, string[] Names)[] PropertyGroups =
    {
        (3, new[] { "buffersize", "width", "height" }),
        (4, new[] { "autofocus", "focus" }),
        (5, new[] { "autoexposure", "exposure" }),
        (6, new[] { "hue", "saturation", "brightness", "temperature" }),
    };

    private static Dictionary<string, ICamera> Cameras(RunContext ctx)
    {
        var state = ctx.DriverState(State);
        if (!state.TryGetValue("cameras", out var value) || value is null)
            state["cameras"] = value = new Dictionary<string, ICamera>();
        return (Dictionary<string, ICamera>)value;
    }

    private static ICamera Get(RunContext ctx, string serial)
    {
        var cameras = Cameras(ctx);
        if (cameras.TryGetValue(serial, out var found)) return found;
        foreach (var (key, camera) in cameras)
            if (serial.Length > 0 && key.Contains(serial)) return camera;

        if (ctx.Simulate)
        {
            var simulated = Hardware.MakeCamera(true, serial);
            simulated.Open();
            cameras[serial] = simulated;
            ctx.Log("Camera: simulating '" + serial + "'");
            return simulated;
        }

        var known = cameras.Count > 0
            ? string.Join(", ", cameras.Keys.OrderBy(k => k)) : "none";
        throw new HardwareException(
            "camera '" + serial + "' is not open (known: " + known + ")");
    }

    private static ICamera OpenCamera(RunContext ctx, string serial)
    {
        var camera = Hardware.MakeCamera(ctx.Simulate, serial);
        if (!camera.IsOpen) camera.Open();
        Cameras(ctx)[serial] = camera;
        return camera;
    }

    [Verb(Module, "OPEN", Args = "2:serial", ConfigOnly = true)]
    public static void Open(RunContext ctx, Row row)
    {
        var serial = ctx.Text(row.Raw(2));
        OpenCamera(ctx, serial);
        ctx.Log("Camera " + serial + " opened.");
    }

    [Verb(Module, "OPENALL", ConfigOnly = true)]
    public static void OpenAll(RunContext ctx, Row row)
    {
        var serials = ctx.Simulate ? Sim.Cameras : Array.Empty<string>();
        if (serials.Length == 0)
        {
            ctx.Log("Camera: none found", "warn");
            return;
        }
        foreach (var serial in serials)
        {
            try
            {
                OpenCamera(ctx, serial);
                ctx.Log("Camera " + serial + " opened.");
            }
            catch (HardwareException exc)
            {
                ctx.Log("Camera " + serial + ": " + exc.Message, "warn");
            }
        }
    }

    /// <summary>
    /// Apply capture properties.
    /// </summary>
    /// <remarks>
    /// Fails if the backend could not apply something it was asked for. A
    /// property that silently does not stick leaves the camera at its default
    /// geometry, which still produces a good-looking image of the wrong pixels
    /// -- and then every coordinate in the program misses, with nothing in the
    /// log to say why.
    ///
    /// Properties the sensor genuinely lacks -- focus and hue on a BlueFOX --
    /// are reported as notes, because v1 ignores them too.
    /// </remarks>
    [Verb(Module, "SETPROPS",
          Args = "2:serial,3:buffer_wh,4:focus?,5:exposure?,6:image?")]
    public static void SetProperties(RunContext ctx, Row row)
    {
        var serial = ctx.Text(row.Raw(2));
        var camera = Get(ctx, serial);

        var properties = new Dictionary<string, double>();
        foreach (var (column, names) in PropertyGroups)
        {
            if (!row.Has(column)) continue;
            var values = ctx.Text(row.Raw(column)).Split(',').Select(v => v.Trim()).ToList();
            for (var i = 0; i < Math.Min(values.Count, names.Length); i++)
            {
                if (values[i].Length == 0 || values[i] == "-") continue;
                if (!double.TryParse(values[i], out var value))
                    throw new VerbException("SETPROPS: '" + values[i]
                        + "' is not a number for " + names[i]);
                properties[names[i]] = value;
            }
        }

        var result = camera.Configure(properties);
        foreach (var note in result.Notes) ctx.Log("Camera " + serial + ": " + note);
        if (result.Ignored.Count > 0)
            throw new VerbException("SETPROPS: camera " + serial + " could not apply "
                + string.Join(", ", result.Ignored)
                + ". The frame geometry would not match what the program expects.");

        var summary = string.Join(", ", result.Applied.Select(p => p.Key + "=" + p.Value));
        ctx.Log("Camera " + serial + " configured: "
                + (summary.Length > 0 ? summary : "nothing to do"));
    }

    [Verb(Module, "SETEXPOSURE", Args = "2:serial,3:exposure_us")]
    public static void SetExposure(RunContext ctx, Row row)
    {
        var serial = ctx.Text(row.Raw(2));
        if (!double.TryParse(ctx.Text(row.Raw(3)), out var wanted))
            throw new VerbException("SETEXPOSURE: '" + row.Raw(3) + "' is not a number");

        var applied = Get(ctx, serial).SetExposure(wanted);
        if (Math.Abs(applied - wanted) > 1e-6)
            ctx.Log("Camera " + serial + ": exposure " + wanted + "us clamped to "
                    + applied + "us", "warn");
        else ctx.Log("Camera " + serial + ": exposure " + applied + "us");
    }

    /// <summary>
    /// Calibrate white balance once and lock the gains.
    /// </summary>
    /// <remarks>
    /// Run against a well-lit neutral reference. CAPTURE then reuses these gains
    /// on every frame instead of recalibrating -- grey-world auto white balance
    /// on a mostly-black inspection frame computes gains of about 1.0, that is
    /// no correction at all, which is what leaves a colour cast.
    /// </remarks>
    [Verb(Module, "CALIBRATEWB", Args = "2:serial,3:exposure_us?,4:warmup?",
          ConfigOnly = true)]
    public static void CalibrateWhiteBalance(RunContext ctx, Row row)
    {
        var serial = ctx.Text(row.Raw(2));
        var exposure = OptionalNumber(ctx, row.Raw(3), 20000.0);
        var warmup = (int)OptionalNumber(ctx, row.Raw(4), 5.0);

        var (red, green, blue) = Get(ctx, serial).CalibrateWhiteBalance(exposure, warmup);
        ctx.Log("Camera " + serial + " WB calibrated: R=" + red.ToString("0.00")
                + " G=" + green.ToString("0.00") + " B=" + blue.ToString("0.00"));

        // Neutral gains mean the reference was too dark to measure anything, so
        // the calibration was a no-op and any colour cast is still there.
        if (Math.Abs(red - 1.0) < 0.02 && Math.Abs(blue - 1.0) < 0.02)
            ctx.Log("Camera " + serial + ": WB gains are ~1.0 -- the reference was too "
                    + "dark to measure. Calibrate on a brighter white target.", "warn");
    }

    [Verb(Module, "CAPTURE", Args = "2:serial,3:path?,4:dest?")]
    public static void Capture(RunContext ctx, Row row)
    {
        var serial = ctx.Text(row.Raw(2));
        var camera = Get(ctx, serial);
        var frame = camera.Capture();
        ctx.Log("Camera " + serial + " captured " + frame.Width + "x" + frame.Height
                + "x" + frame.Channels);

        if (camera.WhiteBalanceGains is { } gains)
            ctx.Log("Camera " + serial + " WB gains: R=" + gains.Red.ToString("0.00")
                    + " G=" + gains.Green.ToString("0.00")
                    + " B=" + gains.Blue.ToString("0.00"));

        if (row.Has(3))
        {
            var path = ctx.Text(row.Raw(3));
            var parent = Path.GetDirectoryName(Path.GetFullPath(path));
            if (!string.IsNullOrEmpty(parent)) Directory.CreateDirectory(parent);
            Images.Save(frame, path);
            ctx.Log("Capture saved to " + path);
        }

        // Frames stay live objects; stringifying one would turn a megabyte image
        // into text.
        if (row.Has(4)) ctx.SetData(row.Raw(4), frame, false);

        if (!row.Has(3) && !row.Has(4))
            throw new VerbException("CAPTURE: give a path, a destination index, or both");
    }

    private static double OptionalNumber(RunContext ctx, string cell, double fallback)
    {
        var text = ctx.Text(cell);
        if (text.Length == 0 || text == "-") return fallback;
        if (!double.TryParse(text, out var value))
            throw new VerbException("'" + text + "' is not a number");
        return value;
    }
}
