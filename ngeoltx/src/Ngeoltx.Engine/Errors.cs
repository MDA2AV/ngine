namespace Ngeoltx.Engine;

/// <summary>
/// Base for every engine-raised error.
/// </summary>
/// <remarks>
/// NGINE v1 signalled errors by formatting them into a string --
/// <c>raise Exception(line[7] + "::" + str(e))</c> -- and splitting on "::"
/// back in the run loop. That destroyed stack traces, made every failure the
/// same type, and corrupted routing whenever a driver message contained "::".
/// Here the routing label is a property.
/// </remarks>
public class NgeoltxException : Exception
{
    public NgeoltxException(string message, string? route = null, int? row = null,
                            Exception? inner = null)
        : base(message, inner)
    {
        Route = route;
        Row = row;
    }

    /// <summary>Label to jump to for recovery, or null to abort the run.</summary>
    public string? Route { get; set; }

    /// <summary>Program row that failed, filled in by the sequencer if unset.</summary>
    public int? Row { get; set; }

    /// <summary>Attach routing discovered by the caller, without overwriting.</summary>
    public NgeoltxException WithContext(string? route, int? row)
    {
        Route ??= route;
        Row ??= row;
        return this;
    }

    public override string ToString() =>
        Row is null ? Message : $"row {Row}: {Message}";
}

/// <summary>A driver verb failed. Routable: the row's exception label applies.</summary>
public class VerbException : NgeoltxException
{
    public VerbException(string message, string? route = null, int? row = null,
                         Exception? inner = null)
        : base(message, route, row, inner) { }
}

/// <summary>
/// The instrument misbehaved or is absent -- the rig is at fault, not the board.
/// </summary>
/// <remarks>
/// Separate from <see cref="VerbException"/> so the UI can distinguish "this
/// board failed" from "this station is broken". Operators react differently,
/// and only one of the two is a real reject.
/// </remarks>
public class HardwareException : VerbException
{
    public HardwareException(string message, string? route = null, int? row = null,
                             Exception? inner = null)
        : base(message, route, row, inner) { }
}

/// <summary>A measurement was taken successfully but fell outside limits.</summary>
public class LimitException : VerbException
{
    public LimitException(string message, string? route = null, int? row = null)
        : base(message, route, row) { }

    public string? Measured { get; init; }
    public string? Low { get; init; }
    public string? High { get; init; }
}

/// <summary>
/// The program itself is malformed. Never routable.
/// </summary>
/// <remarks>
/// A broken program must stop rather than limp along on its own error
/// handlers; that is how v1 ended up running past real problems.
/// </remarks>
public class ProgramException : NgeoltxException
{
    public ProgramException(string message, int? row = null, Exception? inner = null)
        : base(message, null, row, inner) { }
}

/// <summary>Operator stop, or an unrecoverable condition. Teardown still runs.</summary>
public class AbortRunException : NgeoltxException
{
    public AbortRunException(string message) : base(message) { }
}

/// <summary>A program file could not be parsed.</summary>
public class LoaderException : NgeoltxException
{
    public LoaderException(string message, Exception? inner = null)
        : base(message, null, null, inner) { }
}
