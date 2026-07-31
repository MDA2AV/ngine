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

py run.py ui programs/demo/demo.yaml --simulate    # operator station
py run.py run programs/demo/demo.yaml --simulate   # headless
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
| Testability | none — module-level globals, no hardware seam | 296 tests, simulated backends for every instrument |

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
  calibration.py    coordinate sites, click resolution, the values file
tools/calibration/  capture programs offered under Tools -> Calibrate
programs/<product>/ one folder per product: the table and the values
                    it loads, kept together
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

### Variables with a value

A variable may also name a **JSON key it takes its value from**:

```yaml
values: programs/cargo/cargo-coords.json

vars:
  led.u0.a.cont:  ['0,0,30', 'led.u0.a.cont']    # cell, and the key that fills it
  led.u0.a.leds:  ['0,1,30', 'led.u0.a.leds']
```

```json
{ "led.u0.a.cont": "895,659,10,50,1",
  "led.u0.a.leds": "895,659,10,50" }
```

The file is flat and keyed by variable name. `INITDATA` writes each value into
its cell — **every time**, so the value is there before the first step runs and
is back after the per-board re-init a fixture program does at the top of its
loop. These are program constants: static for the whole session, with nothing in
`<Config>` to set them up and nothing to forget.

The mapping is written out rather than implied. It normally repeats the variable
name, which looks redundant until a key is renamed and you want the link to be
something the linter can check:

```
ERROR program: variable 'led.u2.d.cont' takes its value from key
               'led.u2.d.cont', which is not in cargo-coords.json
```

That is `check`, with the fixture cold. A key the file has and no variable claims
is a warning, not an error — usually a renamed variable that left its value
behind.

### Keeping data across a re-init

`INITDATA` takes an optional fourth argument: the first page of a region it
never clears.

```yaml
- [TestData, INITDATA, '40', '3', '32', '30']    # pages 30+ survive
```

Pages, because that is how real tables already organise the store — a page is a
category (detection, paths, per-UUT results), not an index within one. Omit it
and the behaviour is exactly v1's: everything is cleared.

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
py run.py convert TestTables/cargo.ods programs/cargo/cargo.yaml   # optional
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

## Web mode

```bash
py run.py web                                  # read-only, localhost:8080
py run.py web programs/demo/demo.yaml --simulate --allow-control
```

Open `http://localhost:8080`. The page shows the program, per-unit result
tables, the log, progress and the verdict, all updating as the run happens.

Two protocols, because they answer different questions:

| | |
|---|---|
| **REST** | commands — `GET /api/state`, `/api/programs`, `/api/verbs`, `/api/report?format=xml\|json\|csv`, `POST /api/load`, `/api/start`, `/api/stop` |
| **WebSocket** at `/ws` | the live stream — every engine event, pushed |

Polling REST for a log that emits hundreds of lines a second is the wrong
shape; pushing commands down a socket means reinventing status codes. So both.

**Control is off by default.** An endpoint that can start a test is a
remote-control surface on powered hardware, so the server binds to localhost,
refuses `/api/start` and `/api/stop` unless `--allow-control` was passed, and
prints a warning naming the risk if you bind it to the network *with* control
enabled. `--token` adds a shared secret on the control routes.

The first WebSocket frame carries the whole station state, then the last 500
events replay, so a browser opened mid-run is never blind.

## Live telemetry

The station serves a port for the whole session, publishing everything the run
is doing. Clients come and go; the test never waits for one.

```bash
py run.py ui  TestTables/cargo.ods --telemetry        # default port 8765
py run.py run TestTables/cargo.ods --telemetry 9000
```

Three kinds of client on the same port, told apart by what they send first:

| Client | Gets |
|---|---|
| Browser at `http://localhost:8765` | a live dashboard — log, results, progress, no tooling needed |
| WebSocket to `ws://localhost:8765` | every event as JSON, one per frame |
| Raw TCP | the same JSON, newline-delimited — for tooling that does not speak WebSocket |

`tools/telemetry_client.py` is a stdlib-only WebSocket client to build on:

```bash
py tools/telemetry_client.py localhost 8765
```

Every engine event is published, tagged with `type`: `log`, `step`, `status`,
`progress`, `timer`, `grid`, `field`, `alive`, `runstate`, `result`.

Three properties it is built around:

- **The test is never blocked.** Each client has its own thread and a bounded
  queue. A client that cannot keep up overflows its own queue and is dropped;
  nothing applies backpressure to the sequencer.
- **Late joiners are not lost.** A snapshot plus the last 500 events are
  replayed on connect, so a dashboard opened mid-run shows the whole picture.
- **Telemetry failures are never test failures.** Every socket path swallows
  its own exceptions.

## Statistics

Every finished run is written to `ngwart-history.db` (SQLite, alongside the
app; `--history PATH` to move it, `--history ""` to disable). The **Stats** tab
then answers the questions a single run cannot.

- **First-pass yield**, counted in *units*, not points. Counting points flatters
  the figure: a board failing one test of twenty would read as 95% good rather
  than as a reject.
- **A Pareto of failures by test**, with the vital few marked. Click a bar to
  drill into that test's history.
- **Search** across every run by test id or barcode, filtered by result and
  program.
- **Scope** toggles between this session and all time.

Simulated runs are excluded by default — folding dry runs into a yield figure
would quietly corrupt the number that matters most.

### About the Pareto

The textbook Pareto puts counts on a left axis and cumulative percent on a
right one. Two y-scales let the author place the crossover anywhere by choosing
the scales, so the reader cannot trust the geometry. Here both share one
0–100% axis: each bar is that test's *share of all failures*, the line is the
running total, and the raw count sits on the bar. Bars therefore look shorter
than in the classic form — that is the honest height, and nothing is lost.

## Debugging a failed test

```bash
py run.py run TestTables/cargo.ods --debug          # writes ./debug/<name>_<stamp>/
py run.py ui  TestTables/cargo.ods                  # or tick "Debug bundle"
```

Written for the question *"why did INTENSITY_A fail?"*, which a log cannot
answer and images can:

| File | |
|---|---|
| `SUMMARY.txt` | verdict, plus every failed point with its measured value and limits |
| `images/` | the capture, the thresholded binary, and contours drawn with the search window marked |
| `evalcont_row<N>_<TEST>.json` | the window searched, what was found, and every contour near it |
| `contours_row<N>.json` | centroid and area of every contour |
| `datastore.json` | every populated cell, with its variable name |
| `log.txt`, `run.json` | the full log; every step with timing and outcome |
| `validation.json`, `program.tsv`, `environment.txt` | diagnostics, the program as loaded, versions and SDK presence |

Send the whole folder. Off by default -- it writes images, so it costs disk and
a little time per vision step.

## Calibrating LED coordinates

Every optical test carries a nominal `cx,cy` in its arguments — `EVALCONT` and
`EVALCONTN` as `cx,cy,tol,minarea,cal`, `EVALLEDS` as `cx,cy,crop,threshold`,
`MEASCONT` as `cx,cy,tol`. In `cargo.ods` the tolerance is 10 px and the LEDs
sit 17 px apart. Nudge the camera, re-seat the fixture or change a lens and
every one of those windows misses at once:

```
INTENSITY_A: no contour within 10px of (895, 659)
INTENSITY_B: no contour within 10px of (878, 659)
...
```

which reads like a board full of dead LEDs rather than one moved camera.

There are two ways in.

**From the station, on the run that just failed** — the usual one. Run the
program; if the optical tests come back NOT_FOUND, **Tools -> Teach
coordinates** (`Ctrl+E`) opens the frame that run captured, with its contours
drawn. The board has already produced the evidence; taking a second picture to
look at it is a step nobody needs. The action is armed only once a run has left
a frame behind.

**Standalone**, when you would rather not run the whole product program:

```bash
```

That runs a **capture program** -- a small table that powers the fixture, takes
one picture and thresholds it -- then opens the same window.
`programs/cargo_capture.yaml` is one: its `<Config>` and power-up rows are
copied from `cargo.yaml` verbatim, and it thresholds at the same 180, because
teaching against a fixture powered or thresholded differently teaches the wrong
geometry.

Either way the fixture is energised only for the capture. Teardown runs before
the window opens, so nobody clicks with the supply up.

**A click stores the contour's centroid, not the pixel under the mouse.** It is
computed with the same integer truncation and the same 50-pixel noise floor the
runtime uses, so the taught value is exactly the number `EVALCONT` will compare
against, and a site can never be taught to a speck the test would refuse to see.

**Sites are grouped by location, not by test.** One LED is one place on the
board even though an intensity check, a colour check and an off-check all point
at it. On `cargo.yaml` that turns ~100 coordinate cells into **28 clicks**:

```
UUT0  INTENSITY_A / COLOR_A     895,659  +/-10px  rows 259, 266, 314, 374
UUT0  INTENSITY_B / COLOR_B     878,659  +/-10px  rows 260, 267, 315, 375
```

The window shows the drift as you go — the old search window dashed, the taught
point marked, and a line between them. A field of parallel arrows is a camera
that shifted; one odd arrow is a site that was mis-taught.

The fixture is energised only for the capture. Teardown runs before the window
opens, so nobody is clicking with the supply on.

### The file

A calibration rewrites the values file the program already loads. **The table is never
touched.**

```json
{ "led.u0.a.cont": "898,662,10,50,1",
  "led.u0.a.leds": "898,662,10,50" }
```

Each key keeps its own tail — `EVALCONT` wants `cx,cy,tol,minarea,cal` and
`EVALLEDS` wants `cx,cy,crop,threshold`; they are the same point in two shapes
and only the point moves. Tolerances and areas were qualified against real
boards and are not the teacher's to change.

Every key the table declares is written, including sites nobody re-taught, whose
value is carried across unchanged. A partial file would abort the next run on
the first missing key — loud, but useless.

A teach record is written alongside it, carrying the deltas, the rows that read
each site, and what was left untaught. Nothing reads it at run time; it is what
someone looks at to decide whether a re-teach was sane.

### Rehearsing a re-teach

`--sim-shift DX,DY` moves the simulated camera, so the whole loop can be
exercised without touching the bench. Without it every click lands on a
coordinate that was already correct and nothing is proven.

```bash
py run.py run   programs/demo/demo.yaml --simulate                    # 8 points, 0 failed
py run.py run   programs/demo/demo.yaml --simulate --sim-shift 45,30  # 4 failed, both units
                --simulate --sim-shift 45,30
```

The middle command produces exactly the failure this tool exists for:

```
 *   80  LED_A: no contour within 40.0px of (128.0, 240.0)
XX   80  UUT 0 killed: LED_A
```

Four dead LEDs, apparently. In the teach window the same drift reads
unambiguously: four search windows sitting empty, four LEDs off to one side,
and four *parallel* drift lines. Boards do not fail in formation — that is a
camera that moved.

A camera shift is a bench condition, not something a program declares, so it is
a simulation knob rather than a `SETPROPS` argument. Only `SimCamera` reads it;
it cannot affect a real run.

### Without a target table

Omit `--target` and each click simply appends a named site. Useful for reading
coordinates off a new fixture before any table exists.

### What it will not teach

Stated rather than skipped, because a site missing from the list is a test that
quietly keeps its old coordinate:

| | |
|---|---|
| `EVALCONTS` | keeps coordinates as parallel lists across columns 3 and 4 |
| `*ref` in column 3 | the coordinate is computed at run time, so there is nothing static to replace |

Both are reported by `--list` and printed when the window opens.

There is no phase 2 to build: the file *is* what the program reads.

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
py -m pytest tests -q      # 296 passed
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
