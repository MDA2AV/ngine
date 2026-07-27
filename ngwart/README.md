# NGWART

Functional test sequencer for end-of-line PCBA testing. A rewrite of NGINE that
keeps what worked and replaces what did not.

**Kept:** the test program is a table, one row per instruction; a per-UUT
"alive" mask so one fixture tests four boards independently; per-step error
routing; module aliasing so a table picks its own drivers.

**Replaced:** the frozen UI, string-typed errors, the absence of any validation,
and the lack of a guaranteed teardown.

```bash
pip install -r requirements.txt

py run.py ui programs/demo.yaml --simulate    # operator station
py run.py run programs/demo.yaml --simulate   # headless
py run.py check ../cargobay/src/TestTables/cargo.ods
```

---

## Why the rewrite

| | NGINE v1 | NGWART |
|---|---|---|
| Threading | UI and test loop on one asyncio loop; 36 blocking `pyserial` calls inside `async def`, zero executors | engine on a worker thread, Qt on the main thread, events between |
| `<ParallelTask>` | `asyncio.gather` over blocking calls — ran sequentially | real thread pool |
| Errors | `raise Exception(label + "::" + msg)`, 129 times, `split("::")` to route | typed exceptions carrying the route as a field; tracebacks preserved |
| Validation | none — a typo surfaced as `AttributeError` at row 200 with the PSU at 13.5 V | whole program linted before anything energises |
| Teardown | none; a failed run `break`s, leaving supplies on until the next run | `<Teardown>` runs in a `finally` — on pass, fail, stop, or crash |
| Data refs | `data[39][0][29]` | `*uut1.vbat` via a `<Vars>` section, coordinates still work |
| Serial verbs | 27 copy-pasted functions | 1 implementation, 27 aliases |
| Grid verbs | 24 copy-pasted functions | 1 implementation, registered per grid |
| Program format | `.ods` only — binary, un-diffable, spawns lock files | `.ods` still loads; `.yaml` for review and history |
| Dependencies | pandas + numpy to read a grid of strings; vendor SDKs imported at module scope | stdlib zip+XML; every SDK import deferred |
| Testability | none — module-level globals, no hardware seam | 92 tests, simulated backends for every instrument |

## Architecture

```
ngwart/
  engine/           no UI imports, no vendor SDKs — runs headless
    registry.py     @verb with declared parameters -> makes linting possible
    program.py      rows, sections, labels
    context.py      data store (named + l,c,p), alive mask, events
    sequencer.py    the run loop: jumps, parallel blocks, guaranteed teardown
    validator.py    pre-flight checks
    errors.py       typed, routable exceptions
    events.py       engine -> UI channel (plain dataclasses)
    runrecord.py    structured record of everything that happened
    loaders/        .ods (no pandas), .txt, .csv, .yaml
  drivers/          the verbs
    backends/       sim + real behind one protocol
    legacy.py       adopt unported v1 managers as-is
  ui/               PySide6; bridge.py is the only Qt<->engine seam
  reports/          XML / JSON / CSV from the run record
```

The engine never imports Qt and the UI never touches the data store. That seam
is why the display cannot freeze: no widget is ever touched from the thread
doing serial I/O.

## The program

A row is 10 columns, unchanged from v1:

```
C0       C1                 C2..C6                    C7         C8     C9
module   verb               arguments                 on-error   alive  comment
Serial   EXCHANGEBYTES_LVS  D2 | 48,49,.. | .. | 5,5  SERIAL_EX  1      CH1 + ON
```

Sections: `<Modules>`, `<Vars>`, `<Config>`, `<Exec>`, `<Ehandling>`,
`<Teardown>`. The last two are new; `<Ehandling>` is recognised because real v1
tables already put their handler labels there, after `<Exec/>`.

### Named variables

```yaml
vars:
  uut0.vbat: '2,0,0'
```

Then `*uut0.vbat` works anywhere `*2,0,0` does. Both resolve through the same
accessor, so a table can be migrated a line at a time. A leading `*` is accepted
on destinations too.

### Guaranteed teardown

```yaml
teardown:
  - [VISA, WRITE, PSU1, 'OUTP OFF']
  - [Serial, EXCHANGEBYTES_LVS, D1, '111,102,102,47,47', '111,102,102,47,47', '5,5']
```

Runs on success, on failure, on operator stop, and on an internal error. A
teardown step that itself fails is logged and the remaining steps still run —
one stuck relay must not leave the supply on.

## Migrating from v1

**Existing `.ods` tables run unchanged.** All 138 v1 verbs resolve; 161 are
registered.

```bash
py run.py check TestTables/cargo.ods    # lint before anything else
py run.py convert TestTables/cargo.ods programs/cargo.yaml   # optional
```

### When the site driver should win

Some v1 drivers encode hardware knowledge a rewrite cannot re-derive. The
Balluff camera is the clearest case: `BaluffManager.py` holds the mvIMPACT
`DeviceManager` at module scope because letting it be collected unloads the
driver stack and turns every open handle into a dangling native pointer — the
next call crashes the process rather than raising. It also carries the
binning/AOI arithmetic, packed-pixel buffer geometry and the `User1`
white-balance parameter set.

Point NGWART at your v1 `src` and those drivers take precedence:

```bash
py run.py ui  TestTables/cargo.ods --legacy ../cargobay/src
py run.py run TestTables/cargo.ods --legacy ../cargobay/src
```

Only hardware drivers are replaced. `UIManager`, `FlowManager` and `TestData`
stay on the v2 implementations — v1's `UIManager` writes to Tk widgets and would
leave the Qt grids silently blank, and the v2 `FlowManager`/`TestData` declare
their parameters so the validator can see them. Override that with
`--legacy-only BaluffManager,WinSerialManager`.

For a manager you have not ported, adopt it wholesale:

```python
from ngwart.drivers.legacy import adopt
adopt("CANManager", "/path/to/v1/src/CANManager.py")
```

Each `async def VERB(line, UI)` becomes a registered verb; `line` is rebuilt as
the 11-element list v1 passed, a shim stands in for the Tk UI, `TestData`
globals are bound to the live context by reference, and `"LABEL::msg"`
exceptions are translated back into typed errors. Legacy verbs are opaque to the
validator — it confirms they exist, not that their arguments are sane. Port the
ones you touch most, in whatever order suits you.

## Simulation

`--simulate` swaps every backend for a model, not a stub: the supply tracks
per-channel setpoints (measure with the output off and you read ~0), the control
board answers the detection poll as absent-then-present so retry loops are
genuinely exercised, relay boards echo their frames, and the camera renders lit
discs for the vision verbs to find.

Reports from a simulated run carry `<simulated>true</simulated>` so they can
never be mistaken for a real one.

## Verbs

```bash
py run.py verbs                        # all
py run.py verbs --module Flow --long
```

| Module | Verbs | |
|---|---|---|
| `FlowManager` | 42 | jumps, arithmetic, strings, files, limit evaluation |
| `WinSerialManager` | 48 | the `(op, payload, terminator, level)` matrix |
| `UIManager` | 24 | grids, status, log, barcodes, progress |
| `ImageProcessManager` | 15 | conversions, contours, LED checks, cropping |
| `TestData` | 10 | alive mask, data store, datecodes, saving |
| `WinShellManager` | 7 | subprocess |
| `GlobalVISAManager` | 6 | SCPI write/query/measure with limits |
| `BaluffManager` | 6 | capture, properties, white balance |
| `CargoManager` | 3 | product validators |

### The serial matrix

v1's 27 names decode as four switches, so there is one function:

- `READ` / `EXCHANGE` — read only, or write then read
- `LINE` / `BYTES` — text, or a comma-separated byte list
- `_LT_` — read to a newline rather than a fixed byte count
- `_LV0`…`_LV3`, `_LVS` — store raw / judge / judge with retries / judge, retry
  and kill the UUT / strict, raise after retries

`EXCHANGEBYTES_LT_LV3` is therefore `(exchange, bytes, line-terminated, level 3)`.

## Tests

```bash
py -m pytest tests -q      # 92 passed
```

Headless, no hardware. Covers the alive-mask semantics (including the
`-,0,1` "all of" form), error routing and the `STD_EX` fallback, teardown on
every exit path, real concurrency in parallel blocks, the full serial matrix,
`.ods` round-tripping, report generation, and Qt wiring offscreen.

`tests/test_loaders.py` loads the real `cargo.ods` and asserts every verb it
uses resolves — the compatibility guarantee, enforced.

## Findings in `cargo.ods`

Running `check` against the table in this repo reports nine findings. They are
in the table, not the engine. The blank-module rows are **warnings** -- the row
is skipped and the program still loads, which is no worse than v1, where
`globals()[""]` raised `KeyError` and the step never ran either. The undefined
jump label is an **error**, because the run aborts the moment it is reached:

| Row | Problem |
|---|---|
| 117 | `LOG_FLAG OFF` — blank module cell |
| 124 | `VALIDATE_DET` — blank module cell |
| 249–251 | three `EVALLEDS` colour checks — blank module cell |
| 309 | `VALIDATE` — blank module cell |
| 338 | `J TOP` — blank module cell |
| 360 | `J Remove_DUT` — the label is `REMOVE` |

In v1 a blank module made `globals()[""]` raise `KeyError`, which diverted to the
row's handler — so those steps never ran and nothing said so. Row 360 was worse:
`jump()` silently did nothing when a label was missing, so the scanner handler
fell through into the next one.

`cargo.ods` looks like work in progress (a LibreOffice lock file was still in the
repo, and `VALIDATE_DET` is full of `CHECKPOINT` prints), so this is probably
expected — but it is exactly the class of defect the validator exists to catch.
