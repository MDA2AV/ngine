using Ngeoltx.Drivers.Backends;

namespace Ngeoltx.Drivers;

/// <summary>
/// Image primitives, in managed code.
/// </summary>
/// <remarks>
/// Threshold, connected-component labelling and a PPM/BMP codec are a page of
/// code each, and keep a native imaging library off a machine somebody has to
/// install software on. JPEG and PNG decoding are not attempted -- a station
/// that needs them should register a decoder rather than have one guessed at
/// here, and <see cref="Load"/> says so rather than returning a blank frame.
/// </remarks>
public static class Images
{
    /// <summary>A station can plug in a real codec for formats not handled here.</summary>
    public static Func<string, Frame>? Decoder { get; set; }

    public static Frame Load(string path)
    {
        if (!File.Exists(path)) throw new FileNotFoundException("no such image", path);

        var extension = Path.GetExtension(path).ToLowerInvariant();
        if (extension is ".ppm" or ".pgm") return LoadNetpbm(path);
        if (extension == ".bmp") return LoadBmp(path);

        if (Decoder is not null) return Decoder(path);
        throw new NotSupportedException(
            "cannot decode '" + extension + "'. Images.Decoder is unset, so only "
            + "BMP and PPM/PGM are readable. Register a decoder for JPEG or PNG.");
    }

    public static void Save(Frame frame, string path)
    {
        var extension = Path.GetExtension(path).ToLowerInvariant();
        if (extension is ".pgm" && frame.Channels == 1) { SaveNetpbm(frame, path); return; }
        if (extension is ".ppm") { SaveNetpbm(frame, path); return; }
        SaveBmp(frame, path);
    }

    // -- Netpbm -------------------------------------------------------------

    private static Frame LoadNetpbm(string path)
    {
        using var stream = File.OpenRead(path);
        var magic = ReadToken(stream);
        var channels = magic switch
        {
            "P5" => 1,
            "P6" => 3,
            _ => throw new NotSupportedException("unsupported Netpbm magic " + magic),
        };
        var width = int.Parse(ReadToken(stream));
        var height = int.Parse(ReadToken(stream));
        _ = ReadToken(stream);                 // max value

        var pixels = new byte[width * height * channels];
        var read = 0;
        while (read < pixels.Length)
        {
            var chunk = stream.Read(pixels, read, pixels.Length - read);
            if (chunk <= 0) break;
            read += chunk;
        }
        return new Frame(width, height, channels, pixels);
    }

    private static string ReadToken(Stream stream)
    {
        var token = new System.Text.StringBuilder();
        int value;
        var inComment = false;
        while ((value = stream.ReadByte()) >= 0)
        {
            var c = (char)value;
            if (inComment) { if (c is '\n' or '\r') inComment = false; continue; }
            if (c == '#') { inComment = true; continue; }
            if (char.IsWhiteSpace(c)) { if (token.Length > 0) break; continue; }
            token.Append(c);
        }
        return token.ToString();
    }

    private static void SaveNetpbm(Frame frame, string path)
    {
        using var stream = File.Create(path);
        var header = (frame.Channels == 1 ? "P5\n" : "P6\n")
                     + frame.Width + " " + frame.Height + "\n255\n";
        var bytes = System.Text.Encoding.ASCII.GetBytes(header);
        stream.Write(bytes, 0, bytes.Length);
        stream.Write(frame.Pixels, 0, frame.Pixels.Length);
    }

    // -- BMP ----------------------------------------------------------------

    private static Frame LoadBmp(string path)
    {
        var data = File.ReadAllBytes(path);
        if (data.Length < 54 || data[0] != 'B' || data[1] != 'M')
            throw new NotSupportedException("not a BMP file: " + path);

        var offset = BitConverter.ToInt32(data, 10);
        var width = BitConverter.ToInt32(data, 18);
        var height = BitConverter.ToInt32(data, 22);
        var bits = BitConverter.ToInt16(data, 28);
        if (bits != 24)
            throw new NotSupportedException("only 24-bit BMP is supported, got " + bits);

        var flip = height > 0;                 // positive height means bottom-up
        height = Math.Abs(height);
        var stride = (width * 3 + 3) & ~3;     // rows are padded to 4 bytes
        var frame = new Frame(width, height, 3, new byte[width * height * 3]);

        for (var y = 0; y < height; y++)
        {
            var source = offset + (flip ? height - 1 - y : y) * stride;
            Array.Copy(data, source, frame.Pixels, y * frame.Stride, width * 3);
        }
        return frame;
    }

    private static void SaveBmp(Frame frame, string path)
    {
        var source = frame.Channels == 3 ? frame : Expand(frame);
        var stride = (source.Width * 3 + 3) & ~3;
        var size = 54 + stride * source.Height;
        var data = new byte[size];

        data[0] = (byte)'B';
        data[1] = (byte)'M';
        BitConverter.GetBytes(size).CopyTo(data, 2);
        BitConverter.GetBytes(54).CopyTo(data, 10);
        BitConverter.GetBytes(40).CopyTo(data, 14);
        BitConverter.GetBytes(source.Width).CopyTo(data, 18);
        BitConverter.GetBytes(source.Height).CopyTo(data, 22);
        BitConverter.GetBytes((short)1).CopyTo(data, 26);
        BitConverter.GetBytes((short)24).CopyTo(data, 28);
        BitConverter.GetBytes(stride * source.Height).CopyTo(data, 34);

        for (var y = 0; y < source.Height; y++)
            Array.Copy(source.Pixels, y * source.Stride, data,
                       54 + (source.Height - 1 - y) * stride, source.Width * 3);
        File.WriteAllBytes(path, data);
    }

    private static Frame Expand(Frame grey)
    {
        var frame = new Frame(grey.Width, grey.Height, 3,
                              new byte[grey.Width * grey.Height * 3]);
        for (var i = 0; i < grey.Pixels.Length; i++)
        {
            frame.Pixels[i * 3] = grey.Pixels[i];
            frame.Pixels[i * 3 + 1] = grey.Pixels[i];
            frame.Pixels[i * 3 + 2] = grey.Pixels[i];
        }
        return frame;
    }

    // -- analysis ------------------------------------------------------------

    /// <summary>
    /// Connected-component labelling over a binary frame, 8-connected.
    /// </summary>
    /// <remarks>
    /// Iterative flood fill rather than recursion: a large lit region on a
    /// 1296x972 frame is tens of thousands of pixels deep and would overflow
    /// the stack.
    /// </remarks>
    public static List<Blob> FindBlobs(Frame binary, int minimumArea = 1)
    {
        var frame = binary.Channels == 1 ? binary : binary.ToGrey();
        var width = frame.Width;
        var height = frame.Height;
        var seen = new bool[width * height];
        var blobs = new List<Blob>();
        var stack = new Stack<int>();

        for (var start = 0; start < seen.Length; start++)
        {
            if (seen[start] || frame.Pixels[start] == 0) continue;

            stack.Clear();
            stack.Push(start);
            seen[start] = true;

            long area = 0, sumX = 0, sumY = 0;
            int minX = width, minY = height, maxX = 0, maxY = 0;

            while (stack.Count > 0)
            {
                var index = stack.Pop();
                var x = index % width;
                var y = index / width;

                area++;
                sumX += x;
                sumY += y;
                minX = Math.Min(minX, x);
                minY = Math.Min(minY, y);
                maxX = Math.Max(maxX, x);
                maxY = Math.Max(maxY, y);

                for (var dy = -1; dy <= 1; dy++)
                for (var dx = -1; dx <= 1; dx++)
                {
                    if (dx == 0 && dy == 0) continue;
                    var nx = x + dx;
                    var ny = y + dy;
                    if (nx < 0 || ny < 0 || nx >= width || ny >= height) continue;
                    var neighbour = ny * width + nx;
                    if (seen[neighbour] || frame.Pixels[neighbour] == 0) continue;
                    seen[neighbour] = true;
                    stack.Push(neighbour);
                }
            }

            if (area < minimumArea) continue;
            blobs.Add(new Blob((int)area, (int)(sumX / area), (int)(sumY / area),
                               minX, minY, maxX, maxY));
        }
        return blobs.OrderByDescending(b => b.Area).ToList();
    }

    /// <summary>
    /// Dominant colour of a square crop: the mean of its brightest quartile.
    /// </summary>
    /// <remarks>
    /// Stabler than a plain mean on a mostly-dark inspection frame, where the
    /// background would otherwise drag the answer toward black, and it needs no
    /// clustering. Not the same arithmetic as v1's k-means, which is why the
    /// colour limits want re-qualifying against real captures.
    /// </remarks>
    public static (int Blue, int Green, int Red)? DominantColour(
        Frame frame, int centreX, int centreY, int radius)
    {
        if (frame.Channels < 3) return null;

        var x0 = Math.Max(centreX - radius, 0);
        var y0 = Math.Max(centreY - radius, 0);
        var x1 = Math.Min(centreX + radius, frame.Width);
        var y1 = Math.Min(centreY + radius, frame.Height);
        if (x0 >= x1 || y0 >= y1) return null;

        var pixels = new List<(int Luma, int B, int G, int R)>();
        for (var y = y0; y < y1; y++)
        for (var x = x0; x < x1; x++)
        {
            var offset = y * frame.Stride + x * frame.Channels;
            int b = frame.Pixels[offset], g = frame.Pixels[offset + 1],
                r = frame.Pixels[offset + 2];
            pixels.Add(((int)(0.114 * b + 0.587 * g + 0.299 * r), b, g, r));
        }
        if (pixels.Count == 0) return null;

        var take = Math.Max(1, pixels.Count / 4);
        var brightest = pixels.OrderByDescending(p => p.Luma).Take(take).ToList();
        return ((int)brightest.Average(p => p.B),
                (int)brightest.Average(p => p.G),
                (int)brightest.Average(p => p.R));
    }

    public static Frame Crop(Frame frame, int centreX, int centreY, int radius)
    {
        var x0 = Math.Max(centreX - radius, 0);
        var y0 = Math.Max(centreY - radius, 0);
        var x1 = Math.Min(centreX + radius, frame.Width);
        var y1 = Math.Min(centreY + radius, frame.Height);
        if (x0 >= x1 || y0 >= y1)
            throw new ArgumentException("crop at (" + centreX + ", " + centreY
                + ") falls outside the " + frame.Width + "x" + frame.Height + " image");

        var width = x1 - x0;
        var height = y1 - y0;
        var crop = new Frame(width, height, frame.Channels,
                             new byte[width * height * frame.Channels]);
        for (var y = 0; y < height; y++)
            Array.Copy(frame.Pixels, (y0 + y) * frame.Stride + x0 * frame.Channels,
                       crop.Pixels, y * crop.Stride, crop.Stride);
        return crop;
    }
}
