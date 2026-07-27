using Ngeoltx.Drivers;
using Ngeoltx.Drivers.Backends;
using Ngeoltx.Engine;
using Xunit;
using static Ngeoltx.Tests.Fixtures;

namespace Ngeoltx.Tests;

/// <summary>Image primitives and the vision verbs built on them.</summary>
public class VisionTests
{
    private static Frame Blank(int width, int height, byte value = 0)
    {
        var frame = new Frame(width, height, 1, new byte[width * height]);
        Array.Fill(frame.Pixels, value);
        return frame;
    }

    private static void Disc(Frame frame, int cx, int cy, int radius, byte value = 255)
    {
        for (var y = Math.Max(cy - radius, 0); y < Math.Min(cy + radius, frame.Height); y++)
        for (var x = Math.Max(cx - radius, 0); x < Math.Min(cx + radius, frame.Width); x++)
        {
            var dx = x - cx;
            var dy = y - cy;
            if (dx * dx + dy * dy <= radius * radius)
                frame.Pixels[y * frame.Stride + x * frame.Channels] = value;
        }
    }

    [Fact]
    public void BlobLabellingFindsEachSeparateRegion()
    {
        var frame = Blank(200, 100);
        Disc(frame, 50, 50, 15);
        Disc(frame, 150, 50, 20);

        var blobs = Images.FindBlobs(frame, VisionVerbs.MinBlobPixels);

        Assert.Equal(2, blobs.Count);
        // Sorted largest first.
        Assert.True(blobs[0].Area > blobs[1].Area);
        Assert.InRange(blobs[0].CentroidX, 145, 155);
        Assert.InRange(blobs[0].CentroidY, 45, 55);
    }

    /// <summary>
    /// Specks below the noise floor are discarded.
    /// </summary>
    /// <remarks>
    /// Without a floor a single hot pixel counts as a region, and on an area
    /// test it can be the one the search window picks.
    /// </remarks>
    [Fact]
    public void RegionsBelowTheNoiseFloorAreIgnored()
    {
        var frame = Blank(100, 100);
        Disc(frame, 50, 50, 12);
        frame.Pixels[10 * 100 + 10] = 255;      // one lit pixel

        var blobs = Images.FindBlobs(frame, VisionVerbs.MinBlobPixels);

        Assert.Single(blobs);
    }

    /// <summary>
    /// A large region must not overflow the stack.
    /// </summary>
    /// <remarks>
    /// A recursive flood fill dies here: a lit area on a 1296x972 capture is
    /// tens of thousands of pixels deep.
    /// </remarks>
    [Fact]
    public void ALargeRegionIsLabelledWithoutRecursing()
    {
        var frame = Blank(600, 600, 255);

        var blobs = Images.FindBlobs(frame, 1);

        Assert.Single(blobs);
        Assert.Equal(600 * 600, blobs[0].Area);
    }

    [Fact]
    public void ThresholdSplitsAtTheGivenLevel()
    {
        var frame = Blank(10, 10, 100);

        Assert.Equal(0, frame.Threshold(150).Pixels[0]);
        Assert.Equal(255, frame.Threshold(50).Pixels[0]);
    }

    [Fact]
    public void BmpSurvivesASaveAndLoad()
    {
        var path = TempFile(".bmp");
        var frame = new Frame(7, 5, 3, new byte[7 * 5 * 3]);      // odd width: tests padding
        for (var i = 0; i < frame.Pixels.Length; i++) frame.Pixels[i] = (byte)(i % 251);

        Images.Save(frame, path);
        var reloaded = Images.Load(path);

        Assert.Equal(frame.Width, reloaded.Width);
        Assert.Equal(frame.Height, reloaded.Height);
        Assert.Equal(frame.Pixels, reloaded.Pixels);
        File.Delete(path);
    }

    [Fact]
    public void NetpbmSurvivesASaveAndLoad()
    {
        var path = TempFile(".ppm");
        var frame = new Frame(4, 3, 3, new byte[4 * 3 * 3]);
        for (var i = 0; i < frame.Pixels.Length; i++) frame.Pixels[i] = (byte)(i * 3 % 255);

        Images.Save(frame, path);
        var reloaded = Images.Load(path);

        Assert.Equal(frame.Pixels, reloaded.Pixels);
        File.Delete(path);
    }

    /// <summary>
    /// An undecodable format says so instead of returning a blank frame.
    /// </summary>
    /// <remarks>
    /// A blank frame would sail through threshold and blob detection and fail
    /// the area test, sending an engineer to look at the fixture optics for a
    /// problem that is a missing codec.
    /// </remarks>
    [Fact]
    public void AnUnsupportedFormatIsRefusedLoudly()
    {
        var path = TempFile(".jpg");
        File.WriteAllBytes(path, new byte[] { 0xFF, 0xD8, 0xFF });
        Images.Decoder = null;

        var exception = Assert.Throws<NotSupportedException>(() => Images.Load(path));

        Assert.Contains("Images.Decoder", exception.Message);
        File.Delete(path);
    }

    [Fact]
    public void CropStaysInsideTheFrame()
    {
        var frame = new Frame(20, 20, 3, new byte[20 * 20 * 3]);

        var crop = Images.Crop(frame, 2, 2, 8);

        Assert.Equal(10, crop.Width);      // clipped at the left and top edges
        Assert.Equal(10, crop.Height);
        Assert.Throws<ArgumentException>(() => Images.Crop(frame, 500, 500, 4));
    }

    [Fact]
    public void DominantColourReadsTheBrightPartOfTheCrop()
    {
        var frame = new Frame(60, 60, 3, new byte[60 * 60 * 3]);
        for (var y = 25; y < 35; y++)
        for (var x = 25; x < 35; x++)
        {
            var offset = y * frame.Stride + x * 3;
            frame.Pixels[offset] = 20;          // blue
            frame.Pixels[offset + 1] = 220;     // green
            frame.Pixels[offset + 2] = 40;      // red
        }

        var dominant = Images.DominantColour(frame, 30, 30, 6);

        Assert.NotNull(dominant);
        Assert.InRange(dominant!.Value.Green, 180, 255);
        Assert.InRange(dominant.Value.Blue, 0, 80);
    }

    // -- the verbs -----------------------------------------------------------------

    private static (RunRecord Record, RecordingListener Events) Exec(params string[][] rows)
    {
        var all = new List<string[]>
        {
            R("<Config>"),
            R("TestData", "INITDATA", "20", "20", "4"),
            R("TestData", "initAlive", "4"),
            R("<Config/>"),
            R("<Exec>"),
        };
        all.AddRange(rows);
        all.Add(R("<Exec/>"));
        return Run(Program(all.ToArray()));
    }

    [Fact]
    public void CaptureThresholdAndEvaluateRunEndToEnd()
    {
        var (record, _) = Exec(
            R("BaluffManager", "OPEN", "UB101256"),
            R("BaluffManager", "SETPROPS", "UB101256", "1,640,480"),
            R("BaluffManager", "CAPTURE", "UB101256", "", "0,0,0"),
            R("ImageProcessManager", "BGR2CONT", "*0,0,0", "", "0,1,0", "", "60"),
            // The simulated scene puts four discs across the middle of the frame.
            R("ImageProcessManager", "EVALCONT", "*0,1,0", "128,240,60,10,1",
              "1,0,0", "min", "0,LED_A"));

        var point = Assert.Single(record.Points);
        Assert.Equal("LED_A", point.Name);
        Assert.Equal("PASS", point.Result);
    }

    /// <summary>
    /// Selection inside the window is by area, not by proximity.
    /// </summary>
    /// <remarks>
    /// Picking the nearest region lets a stray speck beat the blob being
    /// measured and fail the limit. That is the bug that failed INTENSITY_A on
    /// the real fixture.
    /// </remarks>
    [Fact]
    public void EvaluationPicksTheLargestRegionInTheWindow()
    {
        var frame = Blank(400, 200);
        Disc(frame, 200, 100, 5);        // a speck, dead centre
        Disc(frame, 215, 100, 25);       // the real one, off to the side

        var path = TempFile(".pgm");
        Images.Save(frame, path);

        var (record, _) = Exec(
            R("ImageProcessManager", "BIN2CONT", "", path, "0,0,0"),
            R("ImageProcessManager", "EVALCONT", "*0,0,0", "200,100,40,500,1",
              "1,0,0", "min", "0,AREA"));

        // The speck is about 78 px; the real region is about 1960. Only the
        // larger one clears the 500 px limit.
        Assert.Equal("PASS", Assert.Single(record.Points).Result);
        File.Delete(path);
    }

    [Fact]
    public void EvaluationReportsNotFoundRatherThanZero()
    {
        var frame = Blank(200, 200);
        Disc(frame, 20, 20, 12);

        var path = TempFile(".pgm");
        Images.Save(frame, path);

        var (record, _) = Exec(
            R("ImageProcessManager", "BIN2CONT", "", path, "0,0,0"),
            R("ImageProcessManager", "EVALCONT", "*0,0,0", "180,180,10,10,1",
              "1,0,0", "min", "0,AREA"));

        var point = Assert.Single(record.Points);
        Assert.Equal("FAIL", point.Result);
        Assert.Equal("NOT_FOUND", point.Measured);
        File.Delete(path);
    }

    /// <summary>A camera with no backend refuses rather than inventing a frame.</summary>
    [Fact]
    public void ARealCaptureWithNoBackendFailsWithAnExplanation()
    {
        EnsureDrivers();
        var camera = new UnavailableCamera("UB101256");

        var exception = Assert.Throws<HardwareException>(() => camera.Capture());

        Assert.Contains("no camera backend is registered", exception.Message);
    }
}
