using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Markup.Xaml;
using Avalonia.Styling;
using Ngeoltx.Drivers;

namespace Ngeoltx.App;

public partial class App : Application
{
    public override void Initialize() => AvaloniaXamlLoader.Load(this);

    public override void OnFrameworkInitializationCompleted()
    {
        // Verbs must be registered before a program is loaded, or validation
        // would report every row as an unknown verb.
        Catalog.Register();

        if (Program.Startup.Light) RequestedThemeVariant = ThemeVariant.Light;

        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            var station = new Station(Program.Startup);
            desktop.MainWindow = new MainWindow(station);
            desktop.ShutdownRequested += (_, _) => station.Dispose();
        }
        base.OnFrameworkInitializationCompleted();
    }
}
