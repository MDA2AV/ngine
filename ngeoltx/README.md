# NGEOLTX

A functional test sequencer for end-of-line PCBA testing. C# and Avalonia,
targeting .NET 10. It is a rewrite of **NGWART** (Python/Qt), which is itself a
rewrite of **NGINE v1** (Python/Tk) — and it runs v1's existing `.ods` test
tables unchanged.

```
ngeoltx                                   the operator station
ngeoltx programs/demo.yaml --simulate     load a program and dry-run it

ngeoltx-cli check programs/demo.yaml      validate without executing
ngeoltx-cli run   programs/demo.yaml --simulate
ngeoltx-cli stats --history ngeoltx-history.db
```

## What a test program is

A flat list of instructions, ten columns each, read top to bottom. That shape is
inherited from v1 and kept on purpose: a test engineer reads a sequence, and
nesting would not help.

| Column | Holds |
|---|---|
| 0 | module (a driver, or a `<Section>` marker) |
| 1 | verb |
| 2–6 | arguments |
| 7 | exception label — where a failure jumps |
| 8 | alive mask — which units this row applies to |
| 9 | comment |

Sections are `<Modules>`, `<Vars>`, `<Config>`, `<Exec>`, `<Ehandling>` and
`<Teardown>`. `<ParallelTask>` … `<ParallelTask/>` runs its rows concurrently.

**The alive mask** decides whether a row runs at all:

- `-` or blank — always
- `0,2` — if UUT 0 **or** 2 is still alive
- `-,0,2` — only if 0 **and** 2 are both alive

**Data** lives in a three-dimensional store sized by `INITDATA`. `*0,1,2`
dereferences a cell; anything without a leading `*` is a literal. A `<Vars>`
section names coordinates, so a program can say `*vbat` instead of `*39,0,29`.
Both resolve through the same accessor, so a table can mix them while it is
being migrated.

Four formats load into the same model: `.ods`, `.txt` (v1's dollar-separated
export), `.csv`, and `.yaml`. Convert between any of them:

```
ngeoltx-cli convert TestTables/cargo.ods cargo.yaml
```

## What changed from v1, and why

These are the things the rewrite exists for. Each one is pinned by a test.

**Programs are validated before anything is energised.** v1 dispatched through
`getattr(globals()[module], verb)`, so a mistyped verb surfaced as an
`AttributeError` at row 200 with the supply at 13.5 V and relays closed. Verbs
now declare their arguments, so `check` catches unknown verbs and modules,
missing arguments, jumps to undefined labels, data references outside the
declared store, alive masks naming units that do not exist, and unclosed
parallel blocks — while the fixture is still cold. The station refuses to arm
Run until the program is clean.

**Teardown is guaranteed.** v1 ended a failed run with `break`, leaving supplies
energised and relays closed until the *next* run's opening rows happened to
reset them. `<Teardown>` executes in a `finally`, after a pass, a failure, a
crash, or a stop — and a teardown step that fails itself does not stop the rest
of the block.

**Errors carry their route as a field.** v1 signalled failures with
`raise Exception(line[7] + "::" + str(e))` and split on `"::"` in the run loop.
That destroyed stack traces, made every failure the same type, and mis-routed
anything whose message happened to contain `::`. Exceptions now have a `Route`
property, and a `ProgramException` is deliberately *not* routable: a malformed
program stops rather than limping along on its own error handlers.

**Parallel blocks are actually parallel.** v1 gathered coroutines that performed
blocking I/O, so "parallel" steps ran strictly one after another.

**The UI cannot be blocked by a driver.** The engine runs on a worker thread and
publishes plain records to a listener; the Avalonia layer marshals them onto the
dispatcher. v1 drove Tk from the same loop that did the serial reads, so the
window froze on every exchange — which operators reasonably read as a crash.

**Reports are built from what happened.** v1 generated its XML at the end by
re-reading the data store, so any point whose coordinate had been reused
mid-run was lost, and the report logic had to know each product's coordinate
layout. The sequencer now appends a record as each row executes, and report
writers are pure functions over it.

**27 serial verbs became one.** `READ`/`EXCHANGE` × `LINE`/`BYTES` ×
line-terminated × five validation levels is four switches, not 27 functions. All
27 names still resolve, each pre-binding a combination. The same applies to the
four result grids (24 copy-pasted functions in v1), nine image conversions, and
seven process verbs.

**Hardware sits behind interfaces.** v1 imported `serial`, `pyvisa` and the
camera SDK at module scope, so the application could not start — let alone be
tested — without every vendor stack installed. Each instrument now has a real
and a simulated implementation, and `--simulate` swaps them.

## Simulation

The simulated backends are not stubs that return zeros. The relay boards echo
their command frames, the control board answers the detection poll (16 + a
4-bit mask, in hex, a set bit meaning the slot is **occupied**), and the supply
tracks per-channel voltage and output state — so a program that sets 13.5 V and
measures reads back 13.5 V, and one that measures with the output off reads
about zero. The camera renders four lit discs on a dark field, at whatever
geometry `SETPROPS` asked for.

That fidelity is what lets a program be written and dry-run at a desk, and lets
the tests assert on behaviour rather than on mocks.

## Statistics

The station stores every run in SQLite (one file, no daemon) and the
**Statistics** tab reads it.

- **First-pass yield is counted in units, not points.** A board that fails one
  of forty tests is one reject, not a 97.5% pass. The point-level figure is
  reported separately, never blended into the yield.
- **Simulated runs are excluded by default.** Folding a dry run into the number
  the line is judged on has to be an explicit choice.
- **Session and overall are separate scopes.** What this shift produced is a
  different question from what the station has ever produced, and mixing them
  hides a bad batch inside a good history.
- **The Pareto chart uses one 0–100% axis.** Bars are each test's share of all
  failures; the line is the running total. Both are percentages of the same
  total, so they belong on the same scale — the usual counts-left,
  cumulative-right chart lets whoever drew it decide which line looks alarming,
  and the reader cannot tell. Failure counts are printed on the bars instead.

## Not carried over from v1

Deliberate omissions, stated rather than silently dropped:

- **`shell=True` on commands assembled from spreadsheet cells.** A test table is
  data; handing it to a shell means any cell can become a command. The `*SH`
  aliases still load but launch the argument list directly. Set `allow_shell` in
  the shell driver's state if a program genuinely needs metacharacters.
- **`os.system("pkill adb")` at import time.**
- **A real camera backend.** `UnavailableCamera` fails with an explanation
  rather than returning a plausible frame. The Balluff path carries knowledge
  learned against hardware — 2×2 binning with a centred area of interest, packed
  buffer geometry, white-balance gains held in a parameter set — and none of it
  can be re-derived without the camera present. Register an `ICamera` through
  `Hardware.CameraFactory` to plug one in.
- **A VISA backend.** .NET has no in-box VISA. Register an `IInstrumentFactory`
  wrapping the station's IVI library through `Instruments.Factory`.

### Vision is not bit-identical to the Python station

Image processing here is managed code — threshold and connected-component
labelling are a page each, and a native imaging library is a deployment problem
on a machine somebody has to install software on. But OpenCV's `findContours`
traces boundaries and measures the polygon area, while this counts pixels in a
connected region. The numbers are close, **not equal**. Area limits carried over
from a Python or v1 table must be re-qualified against real captures before this
drives a fixture. The same applies to `EVALLEDS`: v1 runs k-means for the
dominant colour, this takes the mean of the crop's brightest quartile.

JPEG and PNG are not decoded; BMP and PPM/PGM are. `Images.Decoder` takes a
codec if a station needs more, and `Images.Load` says so rather than returning a
blank frame — a blank frame would sail through threshold and blob detection and
fail the area test, sending an engineer to look at the optics for a missing
codec.

## Layout

```
src/Ngeoltx.Engine     program model, loaders, validator, sequencer, history, reports
src/Ngeoltx.Drivers    verb implementations and the hardware backends
src/Ngeoltx.App        the Avalonia operator station  (ngeoltx)
src/Ngeoltx.Cli        the headless companion         (ngeoltx-cli)
tests/Ngeoltx.Tests    xunit
programs/demo.yaml     a complete runnable program
```

## Building

```
dotnet build
dotnet test
```

The target framework is a property, so the tree can be compile-verified on a
machine that only has an older SDK:

```
dotnet build -p:NgeoltxFramework=net9.0
dotnet test  -p:NgeoltxFramework=net9.0
```

Shipping code that was never built is how bugs travel; overriding the property
is how it gets built anyway.
