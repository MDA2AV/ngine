using System.Globalization;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Data.Converters;
using Avalonia.Media;

namespace Ngeoltx.App;

/// <summary>
/// Maps a verdict word onto a theme brush.
/// </summary>
/// <remarks>
/// Looked up from the application's resources rather than hard-coded, so the
/// light and dark palettes stay the single source of colour. A word this
/// converter does not know resolves to ordinary ink -- an unstyled row is
/// preferable to a crash mid-run.
/// </remarks>
public sealed class VerdictBrush : IValueConverter
{
    public static readonly VerdictBrush Instance = new();

    /// <summary>Set to "wash" for the soft row-background variant.</summary>
    public string Variant { get; init; } = "text";

    public object Convert(object? value, Type targetType, object? parameter,
                          CultureInfo culture)
    {
        var key = Key(value?.ToString() ?? "");
        if (key is null) return Brushes.Transparent;
        if (Variant == "wash") key += "Wash";
        return Lookup(key);
    }

    private static string? Key(string word) => word.Trim().ToUpperInvariant() switch
    {
        "PASS" => "Pass",
        "FAIL" or "ERROR" => "Fail",
        "WARN" or "WARNING" => "Warn",
        "INFO" => "Muted",
        _ => null,
    };

    public static IBrush Lookup(string key)
    {
        var application = Application.Current;
        if (application is null) return Brushes.Gray;
        return application.TryGetResource(key, application.ActualThemeVariant, out var found)
               && found is IBrush brush
            ? brush
            : Brushes.Gray;
    }

    public object ConvertBack(object? value, Type targetType, object? parameter,
                              CultureInfo culture) =>
        throw new NotSupportedException();
}

/// <summary>Soft background wash for a failed row.</summary>
public sealed class VerdictWash : IValueConverter
{
    public static readonly VerdictWash Instance = new();

    public object Convert(object? value, Type targetType, object? parameter,
                          CultureInfo culture) =>
        value is true ? VerdictBrush.Lookup("FailWash") : Brushes.Transparent;

    public object ConvertBack(object? value, Type targetType, object? parameter,
                              CultureInfo culture) =>
        throw new NotSupportedException();
}

/// <summary>Alive/failed pill colour for a unit panel header.</summary>
public sealed class AliveBrush : IValueConverter
{
    public static readonly AliveBrush Instance = new();

    public object Convert(object? value, Type targetType, object? parameter,
                          CultureInfo culture) =>
        VerdictBrush.Lookup(value is true ? "Pass" : "Fail");

    public object ConvertBack(object? value, Type targetType, object? parameter,
                              CultureInfo culture) =>
        throw new NotSupportedException();
}

/// <summary>True when a string is non-empty -- for hiding empty rows.</summary>
public sealed class NotEmpty : IValueConverter
{
    public static readonly NotEmpty Instance = new();

    public object Convert(object? value, Type targetType, object? parameter,
                          CultureInfo culture) =>
        !string.IsNullOrWhiteSpace(value?.ToString());

    public object ConvertBack(object? value, Type targetType, object? parameter,
                              CultureInfo culture) =>
        throw new NotSupportedException();
}
