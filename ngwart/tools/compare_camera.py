#!/usr/bin/env python3
"""Capture through both camera paths and compare the results.

    py tools/compare_camera.py [serial] [--legacy ../cargobay/src]

Runs the same SETPROPS / CALIBRATEWB / CAPTURE sequence twice -- once through
the native mvIMPACT backend, once through the site's BaluffManager -- and
reports whether the frames agree.

This exists because every camera defect in this project showed up only on
hardware. A rewrite of vendor code cannot be trusted on the strength of reading
it, so trusting it is made a one-command check rather than a judgement call.

Only the camera is touched: no supply is energised and no relay is switched.
"""

from __future__ import annotations

import argparse
import os
import sys

# Run as `py tools/compare_camera.py`, so sys.path[0] is tools/, not the repo.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_SERIAL = "UB101256"

#: The sequence cargo.ods actually uses at config time.
BUFFER_WH = "4,1296,972"
EXPOSURE = "0,120"
IMAGE = "0,100,0,0"
CALIB_EXPOSURE = "50000"


def _context(simulate: bool):
    from ngwart.engine import Context
    from ngwart.engine.loaders.native import from_dict
    from ngwart.engine.runrecord import RunRecord

    program = from_dict({"modules": {"Camera": "BaluffManager"},
                         "exec": [["Flow", "LABEL", "A"]]}).finalize()
    ctx = Context(program, simulate=simulate)
    ctx.init_data(8, 3, 30)
    ctx.init_alive(4)
    ctx.record = RunRecord()
    return ctx


def _row(*cells):
    from ngwart.engine.program import Row

    padded = list(cells) + [""] * (10 - len(cells))
    return Row(index=0, cells=padded[:10])


def capture_once(serial: str, label: str, simulate: bool = False,
                 exposure_us: int | None = None, calibrate: bool = True):
    """Run OPEN -> SETPROPS -> CALIBRATEWB -> [SETEXPOSURE] -> CAPTURE."""
    from ngwart.engine import REGISTRY

    ctx = _context(simulate)
    log: list[str] = []
    ctx.listener = type("L", (), {"emit": lambda _s, e: log.append(
        getattr(e, "message", ""))})()

    def call(verb, *cells):
        REGISTRY.require("BaluffManager", verb).fn(ctx, _row(*cells))

    print(f"\n--- {label} ---")
    call("OPEN", "Camera", "OPEN", serial)
    call("SETPROPS", "Camera", "SETPROPS", serial, BUFFER_WH, "0,0",
         EXPOSURE, IMAGE)
    if calibrate:
        call("CALIBRATEWB", "Camera", "CALIBRATEWB", serial, CALIB_EXPOSURE)
    if exposure_us:
        call("SETEXPOSURE", "Camera", "SETEXPOSURE", serial, str(exposure_us))
    call("CAPTURE", "Camera", "CAPTURE", serial, "", "0,0,1")

    for line in log:
        if line:
            print(f"    {line}")
    return ctx.content("*0,0,1")


def compare(a, b) -> bool:
    import numpy as np

    print("\n=== comparison ===")
    ok = True

    print(f"  shape     native={getattr(a, 'shape', None)}  "
          f"site={getattr(b, 'shape', None)}")
    if getattr(a, "shape", None) != getattr(b, "shape", None):
        print("  !! frame geometry differs -- every coordinate in the program "
              "would land somewhere else")
        return False

    print(f"  dtype     native={a.dtype}  site={b.dtype}")
    ok &= a.dtype == b.dtype

    a32, b32 = a.astype(np.int32), b.astype(np.int32)
    diff = np.abs(a32 - b32)
    mean_a, mean_b = a32.mean(axis=(0, 1)), b32.mean(axis=(0, 1))

    print(f"  mean BGR  native={np.round(mean_a, 1)}  site={np.round(mean_b, 1)}")

    # Two black frames compare equal and prove nothing. Say so rather than
    # reporting a match that carries no information.
    if float(max(mean_a.max(), mean_b.max())) < 3.0:
        print("  !! both frames are essentially black -- this comparison is "
              "meaningless. Raise --exposure, or light the scene.")
        return False
    print(f"  max |diff|  {int(diff.max())}      mean |diff|  {diff.mean():.2f}")

    # Two live captures are never bit-identical -- sensor noise, and the scene
    # may drift between them. Judge on whether they describe the same image.
    channel_shift = float(np.abs(mean_a - mean_b).max())
    print(f"  channel mean shift  {channel_shift:.2f}")
    if channel_shift > 6.0:
        print("  !! channel means differ materially -- white balance or gain "
              "is not being applied the same way")
        ok = False
    if diff.mean() > 12.0:
        print("  !! frames differ more than sensor noise explains")
        ok = False
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial", nargs="?", default=DEFAULT_SERIAL)
    parser.add_argument("--legacy", default="../cargobay/src",
                        help="directory holding the site's BaluffManager")
    parser.add_argument("--simulate", action="store_true",
                        help="exercise the harness without a camera")
    parser.add_argument("--exposure", type=int, default=50000,
                        help="capture exposure in us. The config-time value "
                             "(120) yields a black frame with the LEDs off, "
                             "and two black frames compare equal while proving "
                             "nothing. Default is bright enough to see the "
                             "scene.")
    args = parser.parse_args()

    import ngwart.drivers  # noqa: F401 - registers verbs

    # Calibrate once, then compare captures with the gains already locked.
    # Letting each path recalibrate confounds the test: the scene drifts between
    # runs, so gains differ for reasons unrelated to which code took the frame.
    native_a = capture_once(args.serial, "native (calibrating)", args.simulate,
                            args.exposure, calibrate=True)
    if native_a is None:
        print("native capture produced nothing")
        return 1

    if args.simulate:
        print("\n--simulate exercises the harness only; nothing to compare.")
        return 0

    # Same code twice: how much do two consecutive captures differ anyway?
    # Without this number, a cross-path difference cannot be interpreted.
    native_b = capture_once(args.serial, "native again (baseline)",
                            exposure_us=args.exposure, calibrate=False)

    from ngwart.drivers.legacy import adopt_directory

    adopt_directory(args.legacy, override=True, only={"BaluffManager"})
    site = capture_once(args.serial, f"site driver ({args.legacy})",
                        exposure_us=args.exposure, calibrate=False)
    if site is None:
        print("site capture produced nothing")
        return 1

    print("\n=== BASELINE: native vs native, same settings ===")
    baseline = compare(native_a, native_b)
    print("\n=== CROSS-PATH: native vs site driver ===")
    same = compare(native_b, site)

    print("\n  A cross-path difference no larger than the baseline means the")
    print("  two implementations are indistinguishable from run-to-run noise.")

    verdict = ("MATCH -- the native path can replace --legacy for the camera"
               if same and baseline else
               "INCONCLUSIVE or DIFFERENT -- keep --legacy for the camera")
    print(f"\n{verdict}")
    return 0 if (same and baseline) else 1


if __name__ == "__main__":
    sys.exit(main())
