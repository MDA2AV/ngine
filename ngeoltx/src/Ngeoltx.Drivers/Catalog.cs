using Ngeoltx.Engine;

namespace Ngeoltx.Drivers;

/// <summary>
/// Populates the verb registry.
/// </summary>
/// <remarks>
/// In the Python version importing the drivers package had this side effect. C#
/// has no equivalent hook that fires reliably -- a type's static constructor
/// only runs when something touches the type -- so registration is an explicit
/// call. Every entry point makes it once, up front, before a program is loaded.
/// </remarks>
public static class Catalog
{
    private static readonly Lock Gate = new();
    private static bool _registered;

    /// <summary>Register every driver. Safe to call more than once.</summary>
    public static VerbRegistry Register(VerbRegistry? registry = null)
    {
        var target = registry ?? VerbRegistry.Default;

        lock (Gate)
        {
            if (registry is null)
            {
                if (_registered) return target;
                _registered = true;
            }

            target.RegisterType(typeof(CoreVerbs));
            target.RegisterType(typeof(FlowVerbs));
            target.RegisterType(typeof(SerialVerbs));
            target.RegisterType(typeof(InstrumentVerbs));
            target.RegisterType(typeof(CameraVerbs));
            target.RegisterType(typeof(VisionVerbs));
            target.RegisterType(typeof(ProductVerbs));
            target.RegisterType(typeof(UiVerbs));

            // Families registered from one implementation rather than as
            // attributed methods: the 27-name serial matrix, four result grids,
            // three single fields, nine image conversions, seven process verbs.
            SerialVerbs.RegisterMatrix(target);
            UiVerbs.RegisterGrids(target);
            UiVerbs.RegisterFields(target);
            VisionVerbs.RegisterConversions(target);
            ShellVerbs.RegisterProcesses(target);

            // Module names real tables use, pointing at the drivers above. Some
            // are v1 product modules whose contents were identical.
            foreach (var (alias, module) in new[]
            {
                ("Flow", FlowVerbs.Module),
                ("SerialManager", SerialVerbs.Module),
                ("Serial", SerialVerbs.Module),
                ("VISA", InstrumentVerbs.Module),
                ("CameraManager", CameraVerbs.Module),
                ("Camera", CameraVerbs.Module),
                ("ImageProcess", VisionVerbs.Module),
                ("Vision", VisionVerbs.Module),
                ("1211Manager", ProductVerbs.Module),
                ("Cargo", ProductVerbs.Module),
                ("UI", UiVerbs.Module),
                ("Shell", ShellVerbs.Module),
            })
                target.AliasModule(alias, module);
        }
        return target;
    }

    /// <summary>Verb count per module -- for the About box and `ngeoltx verbs`.</summary>
    public static SortedDictionary<string, int> Summary(VerbRegistry? registry = null)
    {
        var counts = new SortedDictionary<string, int>(StringComparer.Ordinal);
        foreach (var spec in (registry ?? VerbRegistry.Default).All())
            counts[spec.Module] = counts.TryGetValue(spec.Module, out var n) ? n + 1 : 1;
        return counts;
    }
}
