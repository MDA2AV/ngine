#!/usr/bin/env bash
# Run a program with a hard time cap, then force the fixture to a safe state.
#
# A `timeout` kill is a SIGTERM, so the sequencer's teardown does not run and
# cargo.ods has no <Teardown> block of its own. Anything that energises the
# bench therefore gets de-energised here, unconditionally, whether the run
# finished, failed, or was cut off.
LIMIT="${LIMIT:-40}"
LOG="${LOG:-/tmp/hw-run.log}"
shift_args=("$@")

# -u is essential: Python block-buffers stdout when it is a pipe, and the
# SIGTERM from `timeout` discards whatever is still in the buffer. Without it a
# capped run can produce an empty log precisely when you most need to see how
# far it got.
timeout "$LIMIT" py -u run.py run "${shift_args[@]}" > "$LOG" 2>&1
code=$?
echo "EXIT: $code$( [ $code -eq 124 ] && echo '  (time cap reached)' )"

py - <<'PY'
try:
    import pyvisa
    rm = pyvisa.ResourceManager()
    for res in rm.list_resources():
        if "DP2A" not in res:
            continue
        psu = rm.open_resource(res); psu.timeout = 4000
        for ch in (1, 2, 3):
            psu.write(f"INST:NSEL {ch}"); psu.write("OUTP OFF"); psu.write("VOLT 0")
        states = []
        for ch in (1, 2, 3):
            psu.write(f"INST:NSEL {ch}")
            states.append(f"CH{ch}={psu.query('OUTP?').strip()}")
        print("  SAFE STATE:", " ".join(states), "(0 = off)")
        psu.close()
except Exception as exc:
    print("  !! could not confirm safe state:", exc)
PY
