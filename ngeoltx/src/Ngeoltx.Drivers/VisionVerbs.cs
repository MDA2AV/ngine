using System.Globalization;
using Ngeoltx.Drivers.Backends;
using Ngeoltx.Engine;

namespace Ngeoltx.Drivers;

/// <summary>One connected region of a thresholded image.</summary>
public sealed record Blob(int Area, int CentroidX, int CentroidY,
                          int MinX, int MinY, int MaxX, int MaxY);

/// <summary>
/// Image processing, registered as ImageProcessManager.
/// </summary>
/// <remarks>
/// Written in managed code rather than against a native imaging library. A test
/// station is a machine somebody has to install software on, and a native
/// dependency is a deployment problem; threshold and connected-component
/// labelling are a page of code.
///
/// <para><b>This is not bit-identical to the Python station's OpenCV path.</b>
/// OpenCV's findContours traces boundaries and measures the polygon area, while
/// this counts pixels in a connected region. The numbers are close but not
/// equal, so area limits carried over from the Python or v1 tables must be
/// re-qualified against real captures before this drives a fixture. Saying so
/// here because a silently different area is exactly the kind of thing that
/// passes bad boards.</para>
/// </remarks>
public static class VisionVerbs
{
    public const string Module = "ImageProcessManager";

    /// <summary>Regions smaller than this are noise. v1's value.</summary>
    public const int MinBlobPixels = 50;

    // -- image sourcing -----------------------------------------------------

    private static Frame Load(RunContext ctx, Row row, int dataColumn = 2, int pathColumn = 3)
    {
        if (row.Has(dataColumn))
        {
            var value = ctx.Content(row.Raw(dataColumn));
            if (value is Frame frame) return frame;
            // v1's EVALLEDS stores a *path* in the data cell and reads it back
            // through imread, so both forms must work.
            if (value is string path && path.Trim().Length > 0) return Read(path, row.Verb);
            throw new VerbException(row.Verb + ": " + row.Raw(dataColumn)
                + " holds no image");
        }
        if (row.Has(pathColumn)) return Read(ctx.Text(row.Raw(pathColumn)), row.Verb);
        throw new VerbException(row.Verb + ": give an image index (column " + dataColumn
            + ") or a path (column " + pathColumn + ")");
    }

    private static Frame Read(string path, string what)
    {
        try { return Images.Load(path); }
        catch (Exception exc)
        {
            throw new VerbException(what + ": cannot read image '" + path + "': "
                + exc.Message, inner: exc);
        }
    }

    private static void Emit(RunContext ctx, Row row, Frame frame,
                             int dataColumn = 4, int pathColumn = 5)
    {
        var wrote = false;
        if (row.Has(dataColumn)) { ctx.SetData(row.Raw(dataColumn), frame, false); wrote = true; }
        if (row.Has(pathColumn))
        {
            var path = ctx.Text(row.Raw(pathColumn));
            var parent = Path.GetDirectoryName(Path.GetFullPath(path));
            if (!string.IsNullOrEmpty(parent)) Directory.CreateDirectory(parent);
            Images.Save(frame, path);
            wrote = true;
        }
        if (!wrote)
            throw new VerbException(row.Verb + ": give a destination index (column "
                + dataColumn + ") or a save path (column " + pathColumn + ")");
    }

    // -- the conversion pipeline ---------------------------------------------

    private enum Stage { Grey, Binary, Blobs }

    private static void Convert(RunContext ctx, Row row, Stage stage)
    {
        var image = Load(ctx, row);
        var grey = image.ToGrey();

        if (stage == Stage.Grey) { Emit(ctx, row, grey); return; }

        var threshold = 127.0;
        if (row.Has(6) && !double.TryParse(ctx.Text(row.Raw(6)), NumberStyles.Float,
                                           CultureInfo.InvariantCulture, out threshold))
            throw new VerbException(row.Verb + ": threshold '" + row.Raw(6)
                + "' is not a number");

        var binary = image.Channels == 1 && stage == Stage.Blobs && !row.Has(6)
            ? image                                   // already binary
            : grey.Threshold(threshold);

        if (stage == Stage.Binary) { Emit(ctx, row, binary); return; }

        var blobs = Images.FindBlobs(binary, MinBlobPixels);
        ctx.Log(row.Verb + ": " + blobs.Count + " region(s) found (threshold " + threshold
                + ", frame " + image.Width + "x" + image.Height + ")");
        if (!row.Has(4))
            throw new VerbException(row.Verb
                + ": column 4 must name where to store the regions");
        ctx.SetData(row.Raw(4), blobs, false);
    }

    private static readonly Param[] ConvertParams =
    {
        new(2, "image_index", false, "source image held in the data store"),
        new(3, "image_path", false, "source image on disk"),
        new(4, "dest_index", false),
        new(5, "save_path", false),
        new(6, "threshold", false, "binary threshold, default 127"),
    };

    /// <summary>Register the nine conversion names onto one pipeline.</summary>
    public static void RegisterConversions(VerbRegistry registry)
    {
        foreach (var (name, stage) in new (string, Stage)[]
        {
            ("RGB2GRAY", Stage.Grey), ("BGR2GRAY", Stage.Grey),
            ("GRAY2BIN", Stage.Binary), ("RGB2BIN", Stage.Binary), ("BGR2BIN", Stage.Binary),
            ("BIN2CONT", Stage.Blobs), ("GRAY2CONT", Stage.Blobs),
            ("BGR2CONT", Stage.Blobs), ("RGB2CONT", Stage.Blobs),
        })
        {
            var target = stage;
            registry.Add(new VerbSpec
            {
                Module = Module,
                Name = name,
                Handler = (ctx, row) => Convert(ctx, row, target),
                Params = ConvertParams,
                Doc = "Convert to " + stage + ".",
            });
        }
    }

    // -- region measurement ---------------------------------------------------

    private static List<Blob> Blobs(RunContext ctx, string cell) =>
        ctx.Content(cell) as List<Blob> ?? new List<Blob>();

    /// <summary>
    /// Largest in-window region above the noise floor.
    /// </summary>
    /// <remarks>
    /// Selection is by <b>area</b>, not proximity. An area test wants the blob
    /// it is measuring, and a stray speck nearer the nominal centre would
    /// otherwise win and fail the limit -- which is exactly the bug that failed
    /// INTENSITY_A on the real fixture.
    /// </remarks>
    private static (double? Area, (int X, int Y)? Centroid) FindAt(
        IEnumerable<Blob> blobs, double cx, double cy, double tolerance, double calibration)
    {
        double? bestArea = null;
        (int X, int Y)? bestCentroid = null;

        var minX = Math.Max(0, cx - tolerance);
        var minY = Math.Max(0, cy - tolerance);

        foreach (var blob in blobs)
        {
            if (blob.Area < MinBlobPixels) continue;
            if (blob.CentroidX < minX || blob.CentroidX > cx + tolerance) continue;
            if (blob.CentroidY < minY || blob.CentroidY > cy + tolerance) continue;

            var area = blob.Area * calibration;
            if (bestArea is null || area > bestArea)
            {
                bestArea = area;
                bestCentroid = (blob.CentroidX, blob.CentroidY);
            }
        }
        return (bestArea, bestCentroid);
    }

    private static double[] Numbers(RunContext ctx, string cell, int count, string what)
    {
        var parts = ctx.Text(cell).Split(',', StringSplitOptions.RemoveEmptyEntries)
                       .Select(p => p.Trim()).ToList();
        if (parts.Count < count)
            throw new VerbException(what + ": expected " + count
                + " comma-separated numbers, got '" + cell + "'");
        return parts.Take(count).Select(p =>
            double.TryParse(p, NumberStyles.Float, CultureInfo.InvariantCulture, out var v)
                ? v
                : throw new VerbException(what + ": '" + cell + "' contains a non-number"))
            .ToArray();
    }

    [Verb(Module, "MEASCONT", Args = "2:regions,3:target,4:dest")]
    public static void MeasureRegion(RunContext ctx, Row row)
    {
        var spec = Numbers(ctx, row.Raw(3), 3, "MEASCONT");
        var (area, _) = FindAt(Blobs(ctx, row.Raw(2)), spec[0], spec[1], spec[2], 1.0);
        ctx.Log("MEASCONT at (" + spec[0] + ", " + spec[1] + "): area " + (area ?? 0));
        ctx.SetData(row.Raw(4), area ?? 0.0);
    }

    [Verb(Module, "EVALCONT",
          Args = "2:regions,3:spec,4:dest,5:grid_style?,6:kill_and_id")]
    public static void EvaluateRegion(RunContext ctx, Row row)
    {
        var spec = Numbers(ctx, row.Raw(3), 5, "EVALCONT");
        var (killIndex, testId) = FlowVerbs.KillAndId(ctx, row);
        var (area, centroid) = FindAt(Blobs(ctx, row.Raw(2)), spec[0], spec[1], spec[2], spec[4]);

        if (area is not null)
            ctx.Log(testId + ": region at (" + centroid!.Value.X + ", " + centroid.Value.Y
                    + "), calibrated area " + area);
        else
            ctx.Log(testId + ": no region within " + spec[2] + "px of ("
                    + spec[0] + ", " + spec[1] + ")", "warn");

        var result = area is not null && area > spec[3] ? "PASS" : "FAIL";
        object measured = area is not null
            ? area.Value.ToString("0.##", CultureInfo.InvariantCulture) : "NOT_FOUND";
        FlowVerbs.Publish(ctx, row, killIndex, testId, spec[3], "-", measured, result,
                          ctx.Text(row.Raw(5)));
        FlowVerbs.StoreTriplet(ctx, row.Raw(4), measured.ToString() ?? "", result, testId);
    }

    /// <summary>Inverse of EVALCONT: passes when nothing is present.</summary>
    [Verb(Module, "EVALCONTN",
          Args = "2:regions,3:spec,4:dest,5:grid_style?,6:kill_and_id")]
    public static void EvaluateRegionAbsent(RunContext ctx, Row row)
    {
        var spec = Numbers(ctx, row.Raw(3), 5, "EVALCONTN");
        var (killIndex, testId) = FlowVerbs.KillAndId(ctx, row);
        var (area, _) = FindAt(Blobs(ctx, row.Raw(2)), spec[0], spec[1], spec[2], spec[4]);

        var result = area is null || area <= spec[3] ? "PASS" : "FAIL";
        object measured = area is not null
            ? area.Value.ToString("0.##", CultureInfo.InvariantCulture) : "NOT_FOUND";
        FlowVerbs.Publish(ctx, row, killIndex, testId, spec[3], "-", measured, result,
                          ctx.Text(row.Raw(5)));
        FlowVerbs.StoreTriplet(ctx, row.Raw(4), measured.ToString() ?? "", result, testId);
    }

    /// <summary>
    /// Check that each named site shows the expected colour.
    /// </summary>
    /// <remarks>
    /// v1 crops each site, runs k-means for the dominant colours and checks a
    /// cluster centre against a target BGR within a tolerance. Here the crop's
    /// dominant colour is taken as the mean of its brightest quartile, which is
    /// stabler than a plain mean on a mostly-dark frame and needs no clustering.
    /// Different arithmetic, same judgement -- and another reason the limits
    /// want re-qualifying against real captures.
    /// </remarks>
    [Verb(Module, "EVALLEDS", Args = "2:image,3:leds,4:dest,5:target_bgr,6:kill_and_id")]
    public static void EvaluateLeds(RunContext ctx, Row row)
    {
        const int tolerance = 30;

        var frame = Load(ctx, row, 2, 2);
        var (killIndex, testId) = FlowVerbs.KillAndId(ctx, row);

        var target = ctx.Text(row.Raw(5)).Split(',').Select(t => t.Trim()).ToList();
        if (target.Count < 3)
            throw new VerbException("EVALLEDS: column 5 must be 'blue,green,red', got '"
                + row.Raw(5) + "'");
        var targetBgr = target.Take(3).Select(t =>
            int.TryParse(t, out var v) ? v
                : throw new VerbException("EVALLEDS: target colour '" + row.Raw(5)
                    + "' is not numeric")).ToArray();

        var groups = ctx.Text(row.Raw(3)).Split(';', StringSplitOptions.RemoveEmptyEntries)
                        .Select(g => g.Trim()).Where(g => g.Length > 0).ToList();
        if (groups.Count == 0) throw new VerbException("EVALLEDS: no LED coordinates given");

        var matched = false;
        var colour = "";
        foreach (var group in groups)
        {
            var parts = group.Split(',').Select(p => p.Trim()).ToList();
            if (parts.Count < 4)
            {
                ctx.Log("EVALLEDS: '" + group + "' is not 'x,y,crop_radius,threshold'", "warn");
                matched = false;
                break;
            }
            if (!int.TryParse(parts[0], out var x) || !int.TryParse(parts[1], out var y)
                || !int.TryParse(parts[2], out var radius))
            {
                ctx.Log("EVALLEDS: '" + group + "' has non-numeric coordinates", "warn");
                matched = false;
                break;
            }

            var dominant = Images.DominantColour(frame, x, y, radius);
            if (dominant is null)
            {
                ctx.Log("EVALLEDS: crop at (" + x + ", " + y + ") is empty", "warn");
                matched = false;
                break;
            }

            var (b, g, r) = dominant.Value;
            ctx.Log("EVALLEDS: site (" + x + ", " + y + ") dominant BGR ["
                    + b + ", " + g + ", " + r + "]");
            matched = Math.Abs(b - targetBgr[0]) <= tolerance
                   && Math.Abs(g - targetBgr[1]) <= tolerance
                   && Math.Abs(r - targetBgr[2]) <= tolerance;
            if (matched) colour = b + "-" + g + "-" + r + "-";
        }

        var result = matched ? "PASS" : "FAIL";
        var low = string.Join("-", targetBgr.Select(v => v - tolerance));
        var high = string.Join("-", targetBgr.Select(v => v + tolerance));
        ctx.Log(testId + ": target BGR [" + string.Join(", ", targetBgr) + "] +/-"
                + tolerance + " -> " + result, matched ? "pass" : "fail");

        FlowVerbs.StoreTriplet(ctx, row.Raw(4), colour, result, testId);
        FlowVerbs.Publish(ctx, row, killIndex, testId, low, high,
                          colour.Length > 0 ? colour : "no match", result,
                          ctx.Text(row.Raw(5)));
    }

    [Verb(Module, "MASSCROP", Args = "2:image,3:centres,4:radius,5:dests")]
    public static void MassCrop(RunContext ctx, Row row)
    {
        var frame = Load(ctx, row, 2, 2);
        if (!int.TryParse(ctx.Text(row.Raw(4)), out var radius) || radius <= 0)
            throw new VerbException("MASSCROP: radius must be positive, got '"
                + row.Raw(4) + "'");

        var centres = new List<(int X, int Y)>();
        foreach (var pair in ctx.Text(row.Raw(3))
                     .Split(';', StringSplitOptions.RemoveEmptyEntries))
        {
            var parts = pair.Split(',').Select(p => p.Trim()).ToList();
            if (parts.Count < 2 || !int.TryParse(parts[0], out var x)
                || !int.TryParse(parts[1], out var y))
                throw new VerbException("MASSCROP: '" + pair + "' is not 'cx,cy'");
            centres.Add((x, y));
        }

        var dests = ctx.Text(row.Raw(5)).Split(';', StringSplitOptions.RemoveEmptyEntries)
                       .Select(d => d.Trim()).Where(d => d.Length > 0).ToList();
        if (dests.Count != centres.Count)
            throw new VerbException("MASSCROP: " + centres.Count + " centre(s) but "
                + dests.Count + " destination index(es)");

        for (var i = 0; i < centres.Count; i++)
            ctx.SetData(dests[i], Images.Crop(frame, centres[i].X, centres[i].Y, radius), false);
        ctx.Log("MASSCROP: " + centres.Count + " crop(s) stored");
    }
}
