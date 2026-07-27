using System.Collections.Specialized;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Interactivity;
using Avalonia.Markup.Xaml;
using Avalonia.Platform.Storage;
using Ngeoltx.Drivers;
using Ngeoltx.Engine;
using Ngeoltx.Engine.Loaders;

namespace Ngeoltx.App;

public partial class MainWindow : Window
{
    private readonly Station _station;

    // Parameterless constructor for the XAML previewer only.
    public MainWindow() : this(new Station(new Options())) { }

    public MainWindow(Station station)
    {
        _station = station;

        InitializeComponent();
        DataContext = station;

        station.PropertyChanged += (_, e) =>
        {
            if (e.PropertyName == nameof(Station.Title)) Title = station.Title;
        };
        Title = station.Title;

        // Follow the log unless the operator has scrolled up to read something.
        station.LogLines.CollectionChanged += OnLogChanged;
    }

    private void InitializeComponent() => AvaloniaXamlLoader.Load(this);

    private void OnLogChanged(object? sender, NotifyCollectionChangedEventArgs e)
    {
        if (e.Action != NotifyCollectionChangedAction.Add) return;
        var scroll = this.FindControl<ScrollViewer>("LogScroll");
        if (scroll is null) return;

        // Within a line of the bottom counts as "following". Snapping back from
        // wherever the operator scrolled to would make the log unreadable during
        // a run, which is exactly when it is worth reading.
        var atBottom = scroll.Offset.Y >= scroll.Extent.Height - scroll.Viewport.Height - 24;
        if (atBottom) scroll.ScrollToEnd();
    }

    // -- menu ------------------------------------------------------------------

    private async void OnOpen(object? sender, RoutedEventArgs e)
    {
        var files = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = "Open test program",
            AllowMultiple = false,
            FileTypeFilter = new[]
            {
                new FilePickerFileType("Test programs")
                {
                    Patterns = ProgramLoader.LegacyExtensions
                        .Concat(ProgramLoader.NativeExtensions)
                        .Select(extension => "*" + extension).ToList(),
                },
                new FilePickerFileType("All files") { Patterns = new[] { "*" } },
            },
        });

        var path = files.FirstOrDefault()?.TryGetLocalPath();
        if (path is { Length: > 0 }) _station.Load(path);
    }

    private void OnReload(object? sender, RoutedEventArgs e)
    {
        if (_station.ProgramPath.Length > 0) _station.Load(_station.ProgramPath);
    }

    private void OnStart(object? sender, RoutedEventArgs e) => _station.Start();

    private void OnStop(object? sender, RoutedEventArgs e) => _station.Stop();

    private void OnClearLog(object? sender, RoutedEventArgs e) => _station.LogLines.Clear();

    private void OnShowStation(object? sender, RoutedEventArgs e) => Select(0);

    private void OnShowStats(object? sender, RoutedEventArgs e)
    {
        _station.Statistics.Refresh();
        Select(1);
    }

    private void OnRefreshStats(object? sender, RoutedEventArgs e) => _station.Statistics.Refresh();

    private void Select(int index)
    {
        var tabs = this.FindControl<TabControl>("Pages");
        if (tabs is not null) tabs.SelectedIndex = index;
    }

    private void OnExit(object? sender, RoutedEventArgs e)
    {
        if (Avalonia.Application.Current?.ApplicationLifetime
            is IClassicDesktopStyleApplicationLifetime desktop)
            desktop.Shutdown();
        else Close();
    }

    private void OnShowVerbs(object? sender, RoutedEventArgs e)
    {
        var lines = Catalog.Summary()
            .Select(entry => entry.Key + "  —  " + entry.Value + " verbs");
        Message("Registered verbs",
            VerbRegistry.Default.Count + " verbs across "
            + VerbRegistry.Default.Modules().Count + " modules.\n\n"
            + string.Join("\n", lines));
    }

    private void OnAbout(object? sender, RoutedEventArgs e) =>
        Message("About NGEOLTX",
            "NGEOLTX — functional test sequencer\n"
            + "A C# rewrite of NGWART, itself a rewrite of NGINE v1.\n\n"
            + "Station: " + Environment.MachineName + "\n"
            + "Runtime: " + Environment.Version + "\n"
            + "History: " + (_station.History?.Path ?? "disabled"));

    /// <summary>
    /// A modal note.
    /// </summary>
    /// <remarks>
    /// Hand-built rather than pulled from a dialog package: two dialogs do not
    /// justify a dependency on a station that has to be installed by hand.
    /// </remarks>
    private void Message(string title, string body)
    {
        var window = new Window
        {
            Title = title,
            Width = 520,
            SizeToContent = SizeToContent.Height,
            CanResize = false,
            WindowStartupLocation = WindowStartupLocation.CenterOwner,
            Background = this.FindResource("Surface") as Avalonia.Media.IBrush,
        };

        var close = new Button { Content = "Close", HorizontalAlignment =
            Avalonia.Layout.HorizontalAlignment.Right };
        close.Classes.Add("primary");
        close.Click += (_, _) => window.Close();

        window.Content = new StackPanel
        {
            Margin = new Avalonia.Thickness(18),
            Spacing = 14,
            Children =
            {
                new TextBlock
                {
                    Text = body,
                    TextWrapping = Avalonia.Media.TextWrapping.Wrap,
                    FontSize = 12,
                },
                close,
            },
        };
        window.ShowDialog(this);
    }
}
