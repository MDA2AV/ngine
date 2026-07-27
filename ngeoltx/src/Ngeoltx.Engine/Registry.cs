using System.Reflection;

namespace Ngeoltx.Engine;

/// <summary>
/// One argument column of a verb.
/// </summary>
/// <remarks>
/// Columns map onto the legacy layout: index 2 is the first argument, index 6
/// the last. Naming them is what lets an error say
/// "EXCHANGELINE_LVS: missing 'tries'" instead of "index out of range".
/// </remarks>
public sealed record Param(int Index, string Name, bool Required = true, string Doc = "");

/// <summary>A verb implementation: called as fn(context, row).</summary>
public delegate void VerbHandler(RunContext context, Row row);

public sealed class VerbSpec
{
    public required string Module { get; init; }
    public required string Name { get; init; }
    public required VerbHandler Handler { get; init; }
    public IReadOnlyList<Param> Params { get; init; } = Array.Empty<Param>();
    public string Doc { get; init; } = "";

    /// <summary>True for a name kept only so existing tables keep loading.</summary>
    public bool Legacy { get; init; }

    /// <summary>Verbs that only make sense while building up the fixture.</summary>
    public bool ConfigOnly { get; init; }

    public Param? ParamAt(int index) => Params.FirstOrDefault(p => p.Index == index);
}

/// <summary>
/// Declares a verb on a static method with the signature
/// <c>(RunContext, Row)</c>.
/// </summary>
/// <remarks>
/// v1 dispatched with <c>getattr(globals()[module], verb)</c>, so no signature
/// was known ahead of time and a typo in a spreadsheet cell surfaced as an
/// AttributeError partway through a run with the fixture powered up. Declaring
/// verbs is what makes it possible to lint a whole program before energising
/// anything.
/// </remarks>
[AttributeUsage(AttributeTargets.Method, AllowMultiple = true)]
public sealed class VerbAttribute : Attribute
{
    public VerbAttribute(string module, string name)
    {
        Module = module;
        Name = name;
    }

    public string Module { get; }
    public string Name { get; }

    /// <summary>"2:id,3:message?,5:tries?" -- index, name, optional marker.</summary>
    public string Args { get; set; } = "";

    public bool ConfigOnly { get; set; }
    public bool Legacy { get; set; }

    public IReadOnlyList<Param> ParseArgs()
    {
        if (Args.Length == 0) return Array.Empty<Param>();
        var result = new List<Param>();
        foreach (var chunk in Args.Split(',', StringSplitOptions.RemoveEmptyEntries))
        {
            var text = chunk.Trim();
            var colon = text.IndexOf(':');
            if (colon <= 0) continue;
            if (!int.TryParse(text[..colon], out var index)) continue;
            var name = text[(colon + 1)..];
            var required = !name.EndsWith("?");
            if (!required) name = name[..^1];
            result.Add(new Param(index, name, required));
        }
        return result;
    }
}

/// <summary>Maps (module, verb) onto an implementation, with alias support.</summary>
public sealed class VerbRegistry
{
    private readonly Dictionary<(string Module, string Name), VerbSpec> _verbs = new();
    private readonly Dictionary<string, string> _moduleAliases = new(StringComparer.Ordinal);

    public static VerbRegistry Default { get; } = new();

    public int Count => _verbs.Count;

    // -- registration ----------------------------------------------------

    public VerbSpec Add(VerbSpec spec, bool overwrite = false)
    {
        var key = (spec.Module, spec.Name);
        if (_verbs.ContainsKey(key) && !overwrite)
            throw new InvalidOperationException(
                "duplicate verb " + spec.Module + "." + spec.Name);
        _verbs[key] = spec;
        return spec;
    }

    /// <summary>
    /// Register <paramref name="newName"/> pointing at an existing verb.
    /// </summary>
    /// <remarks>
    /// This is how the 27 legacy serial verbs collapse onto one implementation:
    /// each old name becomes an alias that pre-binds its combination of
    /// operation, payload, terminator and validation level. Old programs keep
    /// working and there is one function to maintain.
    /// </remarks>
    public VerbSpec AliasVerb(string module, string newName, string target,
                              VerbHandler? handler = null)
    {
        if (!_verbs.TryGetValue((module, target), out var basis))
            throw new InvalidOperationException(
                "cannot alias " + newName + ": " + module + "." + target
                + " is not registered");
        return Add(new VerbSpec
        {
            Module = module,
            Name = newName,
            Handler = handler ?? basis.Handler,
            Params = basis.Params,
            Doc = basis.Doc,
            Legacy = true,
            ConfigOnly = basis.ConfigOnly,
        });
    }

    /// <summary>Make one module name resolve to another's verb table.</summary>
    public void AliasModule(string alias, string module) => _moduleAliases[alias] = module;

    /// <summary>Scan a type for [Verb] methods and register them.</summary>
    public int RegisterType(Type type)
    {
        var count = 0;
        foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.Static))
        {
            foreach (var attribute in method.GetCustomAttributes<VerbAttribute>())
            {
                var handler = (VerbHandler)Delegate.CreateDelegate(
                    typeof(VerbHandler), method);
                Add(new VerbSpec
                {
                    Module = attribute.Module,
                    Name = attribute.Name,
                    Handler = handler,
                    Params = attribute.ParseArgs(),
                    ConfigOnly = attribute.ConfigOnly,
                    Legacy = attribute.Legacy,
                    Doc = method.Name,
                });
                count++;
            }
        }
        return count;
    }

    // -- lookup ----------------------------------------------------------

    public string ResolveModule(string module)
    {
        var seen = new HashSet<string>();
        while (_moduleAliases.TryGetValue(module, out var next) && seen.Add(module))
            module = next;
        return module;
    }

    public VerbSpec? Lookup(string module, string verb) =>
        _verbs.TryGetValue((ResolveModule(module), verb), out var spec) ? spec : null;

    public VerbSpec Require(string module, string verb, int? row = null)
    {
        var spec = Lookup(module, verb);
        if (spec is not null) return spec;

        var known = VerbsFor(module);
        var hint = known.Count > 0
            ? Suggest(verb, known) is { } near ? " (did you mean " + near + "?)" : ""
            : " (module '" + module + "' has no registered verbs)";
        throw new ProgramException("unknown verb " + module + "." + verb + hint, row);
    }

    public IReadOnlyList<string> VerbsFor(string module)
    {
        var real = ResolveModule(module);
        return _verbs.Keys.Where(k => k.Module == real)
                          .Select(k => k.Name).OrderBy(n => n).ToList();
    }

    public IReadOnlyList<string> Modules() =>
        _verbs.Keys.Select(k => k.Module).Distinct().OrderBy(m => m).ToList();

    public IEnumerable<VerbSpec> All() => _verbs.Values;

    /// <summary>Cheap typo suggestion by edit distance.</summary>
    public static string? Suggest(string word, IReadOnlyList<string> candidates)
    {
        string? best = null;
        var bestScore = int.MaxValue;
        foreach (var candidate in candidates)
        {
            var score = Distance(word.ToUpperInvariant(), candidate.ToUpperInvariant());
            if (score < bestScore) { bestScore = score; best = candidate; }
        }
        // Only suggest when it is close enough to be plausible.
        return bestScore <= Math.Max(2, word.Length / 3) ? best : null;
    }

    private static int Distance(string a, string b)
    {
        var previous = new int[b.Length + 1];
        var current = new int[b.Length + 1];
        for (var j = 0; j <= b.Length; j++) previous[j] = j;

        for (var i = 1; i <= a.Length; i++)
        {
            current[0] = i;
            for (var j = 1; j <= b.Length; j++)
            {
                var cost = a[i - 1] == b[j - 1] ? 0 : 1;
                current[j] = Math.Min(Math.Min(current[j - 1] + 1, previous[j] + 1),
                                      previous[j - 1] + cost);
            }
            (previous, current) = (current, previous);
        }
        return previous[b.Length];
    }
}
