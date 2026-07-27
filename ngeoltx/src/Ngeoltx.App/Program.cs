using Avalonia;

namespace Ngeoltx.App;

public static class Program
{
    /// <summary>Parsed here so the Application can read it once it starts.</summary>
    public static Options Startup { get; private set; } = new();

    [STAThread]
    public static int Main(string[] args)
    {
        Options? options;
        try { options = Options.Parse(args); }
        catch (ArgumentException exc)
        {
            Console.Error.WriteLine("ngeoltx: " + exc.Message);
            Console.Error.WriteLine();
            Console.Error.WriteLine(Ngeoltx.App.Options.Usage);
            return 2;
        }
        if (options is null) { Console.WriteLine(Ngeoltx.App.Options.Usage); return 0; }

        Startup = options;
        return BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);
    }

    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<App>()
                  .UsePlatformDetect()
                  .WithInterFont()
                  .LogToTrace();
}
