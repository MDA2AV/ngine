using Ngeoltx.Engine;

namespace Ngeoltx.Drivers;

/// <summary>
/// UI verbs, registered as UIManager.
/// </summary>
/// <remarks>
/// v1 wrote GRID1 through GRID4, plus SYNCGRID1..4, GRID1_CONFIG..4 and
/// GRID1_D..2_D as separate copy-pasted functions -- 24 functions where there
/// is one behaviour parameterised by a grid number. Here it is written once and
/// registered for each grid.
///
/// The verbs emit events rather than touching controls, so they behave
/// identically under the desktop UI, headless, and in tests.
/// </remarks>
public static class UiVerbs
{
    public const string Module = "UIManager";

    private static readonly string[] GridOps = { "add", "clear", "place", "unplace" };
    private static readonly string[] ConfigOps =
        { "place", "add_columns", "edit_column", "edit_heading", "tag_config" };

    private static readonly Param[] GridParams =
    {
        new(2, "operation", true, "Add | Clear | Place | Unplace"),
        new(3, "source", false, "const | var (for Add)"),
        new(4, "payload", false, "';'-separated values, last field is the colour tag"),
        new(5, "extra", false),
        new(6, "extra2", false),
    };

    private static readonly Param[] ConfigParams =
    {
        new(2, "operation", true,
            "Place | Add_Columns | Edit_Column | Edit_Heading | Tag_Config"),
        new(3, "argument", false),
        new(4, "argument2", false),
        new(5, "argument3", false),
        new(6, "argument4", false),
    };

    /// <summary>Register GRIDn, SYNCGRIDn, GRIDn_CONFIG and the _D aliases.</summary>
    public static void RegisterGrids(VerbRegistry registry)
    {
        for (var n = 1; n <= 4; n++)
        {
            var grid = n;
            foreach (var prefix in new[] { "GRID", "SYNCGRID" })
            {
                registry.Add(new VerbSpec
                {
                    Module = Module,
                    Name = prefix + grid,
                    Handler = (ctx, row) => Grid(ctx, row, grid),
                    Params = GridParams,
                    Doc = "Result grid " + grid + ": add rows, clear, or place it.",
                });

                // The _D variants behave identically; v1 duplicated them so a
                // table could target a second pair of grids on a detail page.
                if (grid > 2) continue;
                registry.Add(new VerbSpec
                {
                    Module = Module,
                    Name = prefix + grid + "_D",
                    Handler = (ctx, row) => Grid(ctx, row, grid),
                    Params = GridParams,
                    Legacy = true,
                    Doc = "Alias of " + prefix + grid + ".",
                });
            }

            registry.Add(new VerbSpec
            {
                Module = Module,
                Name = "GRID" + grid + "_CONFIG",
                Handler = (ctx, row) => GridConfig(ctx, row, grid),
                Params = ConfigParams,
                ConfigOnly = true,
                Doc = "Configure result grid " + grid + ".",
            });
        }
    }

    private static void Grid(RunContext ctx, Row row, int grid)
    {
        var op = ctx.Text(row.Raw(2)).Trim().ToLowerInvariant();
        if (!GridOps.Contains(op))
            throw new VerbException("GRID" + grid + ": unknown operation '" + row.Raw(2)
                + "' (expected " + string.Join(", ", GridOps) + ")");

        switch (op)
        {
            case "clear":
                ctx.Emit(new GridEvent(grid, "clear"));
                return;
            case "unplace":
                ctx.Emit(new GridEvent(grid, "unplace"));
                return;
            case "place":
                ctx.Emit(new GridEvent(grid, "place", Config: PlaceConfig(ctx, row, 3)));
                return;
        }

        var source = ctx.Text(row.Raw(3)).Trim().ToLowerInvariant();
        if (source is not ("const" or "var"))
            throw new VerbException("GRID" + grid
                + " Add: expected 'const' or 'var', got '" + source + "'");

        var parts = ctx.Text(row.Raw(4)).Split(';');
        if (parts.Length == 0)
            throw new VerbException("GRID" + grid + " Add: nothing to add");

        // v1 convention: the final field is the colour tag, the rest are values.
        var tag = parts.Length > 1 ? parts[^1] : "";
        var values = parts.Length > 1 ? parts[..^1] : parts;
        ctx.Emit(new GridEvent(grid, "add", values, tag));
    }

    private static void GridConfig(RunContext ctx, Row row, int grid)
    {
        var op = ctx.Text(row.Raw(2)).Trim().ToLowerInvariant();
        if (!ConfigOps.Contains(op))
            throw new VerbException("GRID" + grid + "_CONFIG: unknown operation '"
                + row.Raw(2) + "' (expected " + string.Join(", ", ConfigOps) + ")");

        var config = new Dictionary<string, object>();
        switch (op)
        {
            case "place":
                ctx.Emit(new GridEvent(grid, "place", Config: PlaceConfig(ctx, row, 3)));
                return;

            case "add_columns":
            {
                var columns = ctx.Text(row.Raw(3))
                    .Split(',', StringSplitOptions.RemoveEmptyEntries)
                    .Select(c => c.Trim()).Where(c => c.Length > 0).ToList();
                if (columns.Count == 0)
                    throw new VerbException("GRID" + grid
                        + "_CONFIG Add_Columns: no column names given");
                config["columns"] = columns;
                break;
            }

            case "edit_column":
            {
                var parts = ctx.Text(row.Raw(3)).Split(',').Select(p => p.Trim()).ToList();
                if (parts.Count < 2)
                    throw new VerbException("GRID" + grid
                        + "_CONFIG Edit_Column: expected 'name,width[,stretch]'");
                config["column"] = parts[0];
                config["width"] = int.TryParse(parts[1], out var width) ? width : 100;
                break;
            }

            case "edit_heading":
            {
                var parts = ctx.Text(row.Raw(3)).Split(',').Select(p => p.Trim()).ToList();
                if (parts.Count < 2)
                    throw new VerbException("GRID" + grid
                        + "_CONFIG Edit_Heading: expected 'name,text'");
                config["heading"] = parts[0];
                config["text"] = parts[1];
                break;
            }

            default:
            {
                var parts = ctx.Text(row.Raw(3)).Split(',').Select(p => p.Trim()).ToList();
                if (parts.Count < 2)
                    throw new VerbException("GRID" + grid
                        + "_CONFIG Tag_Config: expected 'TAG,#rrggbb'");
                config["tag"] = parts[0];
                config["colour"] = parts[1];
                break;
            }
        }
        ctx.Emit(new GridEvent(grid, "config", Config: config));
    }

    private static Dictionary<string, object> PlaceConfig(RunContext ctx, Row row, int start)
    {
        var keys = new[] { "relx", "rely", "relwidth", "relheight" };
        var config = new Dictionary<string, object>();
        for (var i = 0; i < keys.Length; i++)
        {
            var cell = row.Raw(start + i);
            if (cell.Length == 0) continue;
            if (!double.TryParse(ctx.Text(cell), out var value))
                throw new VerbException("Place: '" + cell + "' is not a fraction");
            config[keys[i]] = value;
        }
        return config;
    }

    // -- single fields --------------------------------------------------------

    public static void RegisterFields(VerbRegistry registry)
    {
        foreach (var (name, field, doc) in new[]
        {
            ("BCODE1", "barcode1", "First barcode entry."),
            ("BCODE2", "barcode2", "Second barcode entry."),
            ("WID", "worker_id", "Worker or operator id field."),
        })
        {
            var target = field;
            registry.Add(new VerbSpec
            {
                Module = Module,
                Name = name,
                Handler = (ctx, row) =>
                {
                    var op = ctx.Text(row.Raw(2)).Trim().ToLowerInvariant();
                    ctx.Field(target, op switch
                    {
                        "clear" => "",
                        "set" => ctx.Text(row.Raw(3)),
                        // v1's default case set the field to the raw argument.
                        _ => ctx.Text(row.Raw(2)),
                    });
                },
                Params = new[]
                {
                    new Param(2, "operation", true, "Set | Clear"),
                    new Param(3, "value", false),
                },
                Doc = doc,
            });
        }
    }

    [Verb(Module, "STATUS", Args = "2:operation,3:text?,4:colour?")]
    public static void Status(RunContext ctx, Row row)
    {
        var op = ctx.Text(row.Raw(2)).Trim().ToLowerInvariant();
        if (op == "clear") { ctx.Emit(new StatusEvent("", null)); return; }
        var text = op == "set" ? ctx.Text(row.Raw(3)) : ctx.Text(row.Raw(2));
        var colour = ctx.Text(row.Raw(4));
        ctx.Emit(new StatusEvent(text, colour.Length > 0 ? colour : null));
    }

    [Verb(Module, "LBOX", Args = "2:operation")]
    public static void LogBox(RunContext ctx, Row row)
    {
        if (ctx.Text(row.Raw(2)).Trim().ToLowerInvariant() == "clear")
            ctx.Emit(new FieldEvent("log", "", "clear"));
        else ctx.Log(ctx.Text(row.Raw(2)));
    }

    [Verb(Module, "PBAR", Args = "2:value")]
    public static void ProgressBar(RunContext ctx, Row row)
    {
        var raw = ctx.Text(row.Raw(2));
        if (!double.TryParse(raw, out var value))
            throw new VerbException("PBAR: '" + raw + "' is not a number");
        ctx.Progress(value);
    }

    [Verb(Module, "RESETPBARCOLOR")]
    public static void ResetProgressColour(RunContext ctx, Row row) =>
        ctx.Emit(new FieldEvent("progress_colour", "", null));

    [Verb(Module, "CMONITOR", Args = "2:message,3:colour?,4:kill_index?")]
    public static void CurrentMonitor(RunContext ctx, Row row)
    {
        var index = ctx.Text(row.Raw(4));
        if (index.Length == 0) index = "1";
        var colour = ctx.Text(row.Raw(3));
        ctx.Field("monitor" + index, ctx.Text(row.Raw(2)),
                  colour.Length > 0 ? colour : null);
    }
}
