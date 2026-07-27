using Avalonia;
using Avalonia.Controls;
using Avalonia.Media;
using Ngeoltx.Engine;

namespace Ngeoltx.App;

/// <summary>
/// Failures by test: bars for each test's share, a line for the running total.
/// </summary>
/// <remarks>
/// Both series are percentages of the same total, so they share <b>one</b> 0-100%
/// axis. The usual Pareto chart puts counts on the left and cumulative percent
/// on the right, and a two-scale chart lets whoever drew it decide which line
/// looks alarming -- the reader cannot tell. Here a bar at 30% and a cumulative
/// point at 30% are at the same height because they mean the same thing.
///
/// The count still matters, so it is printed on the bar rather than encoded in a
/// second axis.
/// </remarks>
public sealed class ParetoChart : Control
{
    /// <summary>The share of failures conventionally treated as "the vital few".</summary>
    public const double Cutoff = 80.0;

    private static readonly Typeface Face = new(FontFamily.Default);

    public static readonly StyledProperty<IReadOnlyList<ParetoEntry>?> EntriesProperty =
        AvaloniaProperty.Register<ParetoChart, IReadOnlyList<ParetoEntry>?>(nameof(Entries));

    static ParetoChart()
    {
        AffectsRender<ParetoChart>(EntriesProperty);
        AffectsMeasure<ParetoChart>(EntriesProperty);
    }

    public IReadOnlyList<ParetoEntry>? Entries
    {
        get => GetValue(EntriesProperty);
        set => SetValue(EntriesProperty, value);
    }

    public override void Render(DrawingContext context)
    {
        var entries = Entries;
        var ink = VerdictBrush.Lookup("Ink");
        var muted = VerdictBrush.Lookup("Muted");
        var faint = VerdictBrush.Lookup("Faint");

        if (entries is null || entries.Count == 0)
        {
            Draw(context, "No failures recorded in this scope.", muted, 13,
                 new Point(12, Bounds.Height / 2 - 8));
            return;
        }

        var total = entries.Sum(e => (double)e.Failures);
        if (total <= 0) return;

        const double left = 44, right = 12, top = 14, labels = 54;
        var plotWidth = Math.Max(Bounds.Width - left - right, 10);
        var plotHeight = Math.Max(Bounds.Height - top - labels, 10);
        var baseline = top + plotHeight;

        // -- grid, at 25% steps ------------------------------------------------
        var gridPen = new Pen(faint, 1, new DashStyle(new double[] { 2, 4 }, 0));
        for (var percent = 0; percent <= 100; percent += 25)
        {
            var y = baseline - plotHeight * percent / 100.0;
            context.DrawLine(gridPen, new Point(left, y), new Point(left + plotWidth, y));
            Draw(context, percent + "%", faint, 10, new Point(6, y - 7));
        }

        // -- the 80% line, which is the whole point of the chart ---------------
        var cutoffY = baseline - plotHeight * Cutoff / 100.0;
        var cutoffPen = new Pen(VerdictBrush.Lookup("Warn"), 1,
                                new DashStyle(new double[] { 6, 4 }, 0));
        context.DrawLine(cutoffPen, new Point(left, cutoffY),
                         new Point(left + plotWidth, cutoffY));

        // -- bars ---------------------------------------------------------------
        var slot = plotWidth / entries.Count;
        var barWidth = Math.Max(Math.Min(slot * 0.56, 46), 4);
        var accent = VerdictBrush.Lookup("Accent");
        var fail = VerdictBrush.Lookup("Fail");
        var surface = VerdictBrush.Lookup("Panel");

        var cumulative = 0.0;
        var line = new List<Point>();

        for (var i = 0; i < entries.Count; i++)
        {
            var entry = entries[i];
            var share = 100.0 * entry.Failures / total;
            cumulative += share;

            var centre = left + slot * (i + 0.5);
            var height = plotHeight * share / 100.0;
            var bar = new Rect(centre - barWidth / 2, baseline - height, barWidth, height);

            // Bars inside the vital few read as the ones to act on.
            context.DrawRectangle(cumulative <= Cutoff + 1e-9 ? fail : accent, null,
                                  new RoundedRect(bar, 4, 4, 0, 0));
            // A 2px surface gap keeps adjacent bars from reading as one block.
            context.DrawRectangle(null, new Pen(surface, 2),
                                  new RoundedRect(bar, 4, 4, 0, 0));

            line.Add(new Point(centre, baseline - plotHeight * cumulative / 100.0));

            if (height > 16)
                Draw(context, entry.Failures.ToString(), surface, 11,
                     new Point(centre - 6, baseline - height + 3));

            DrawRotated(context, Shorten(entry.Name), muted, 11,
                        new Point(centre, baseline + 6));
        }

        // -- cumulative line -----------------------------------------------------
        var linePen = new Pen(ink, 2, lineCap: PenLineCap.Round,
                              lineJoin: PenLineJoin.Round);
        for (var i = 1; i < line.Count; i++)
            context.DrawLine(linePen, line[i - 1], line[i]);
        foreach (var point in line)
        {
            context.DrawEllipse(ink, null, point, 4, 4);
            context.DrawEllipse(null, new Pen(surface, 2), point, 4, 4);
        }
    }

    protected override Size MeasureOverride(Size availableSize)
    {
        var count = Entries?.Count ?? 0;
        // Enough width that the rotated labels do not collide, and a fixed
        // height so the panel does not jump as tests come and go.
        return new Size(Math.Max(count * 62 + 56, 320), 300);
    }

    private static string Shorten(string name) =>
        name.Length <= 16 ? name : name[..15] + "…";

    private static void Draw(DrawingContext context, string text, IBrush brush,
                             double size, Point at) =>
        context.DrawText(new FormattedText(text, System.Globalization.CultureInfo.InvariantCulture,
            FlowDirection.LeftToRight, Face, size, brush), at);

    /// <summary>
    /// Test ids are long, so their labels are set at an angle rather than
    /// truncated to nothing or dropped.
    /// </summary>
    private static void DrawRotated(DrawingContext context, string text, IBrush brush,
                                    double size, Point at)
    {
        using var _ = context.PushTransform(
            Matrix.CreateRotation(Math.PI / 4) * Matrix.CreateTranslation(at.X, at.Y));
        context.DrawText(new FormattedText(text, System.Globalization.CultureInfo.InvariantCulture,
            FlowDirection.LeftToRight, Face, size, brush), new Point(0, 0));
    }
}
