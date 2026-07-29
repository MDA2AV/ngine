"""Web front end: REST for commands, WebSocket for the live stream.

Two protocols because they answer different questions. Commands are
request/response and need status codes; the event stream is a firehose that
should be pushed, not polled.

    ngwart web                       read-only, localhost, port 8080
    ngwart web --allow-control       lets a browser start and stop tests
"""

from __future__ import annotations

import os

from .server import DEFAULT_PORT, WebServer
from .station import Station

__all__ = ["WebServer", "Station", "DEFAULT_PORT", "serve"]


from ..engine.loaders import pick_program_dir as _pick_program_dir  # noqa: E402


def serve(program: str | None = None, host: str = "127.0.0.1",
          port: int = DEFAULT_PORT, simulate: bool = False,
          allow_control: bool = False, token: str | None = None,
          debug_dir: str | None = None, program_dir: str | None = None,
          station: str = "", operator: str = "") -> int:
    """Run the web station until interrupted."""
    import time

    from .. import drivers  # noqa: F401 - registers verbs

    program_dir = _pick_program_dir(program_dir, program)

    controller = Station(simulate=simulate, debug_dir=debug_dir,
                         station=station, operator=operator,
                         allow_control=allow_control)
    server = WebServer(controller, host=host, port=port, token=token,
                       program_dir=program_dir)
    controller.listener = server
    server.start()

    print(f"  programs from {os.path.abspath(program_dir)}")
    where = f"http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{server.bound_port}"
    print(f"  NGWART web station on {where}")
    print(f"  control: {'ENABLED' if allow_control else 'read-only'}"
          f"{'  token required' if token else ''}")
    if host not in ("127.0.0.1", "localhost") and allow_control and not token:
        # Naming the risk rather than refusing: it may be exactly what a
        # cell controller needs. But it should never be a surprise.
        print("  !! reachable from the network AND able to start tests, with no")
        print("     token. Anyone who can reach this port can energise the")
        print("     fixture. Use --token, or bind to localhost.")

    if program:
        try:
            controller.load(program)
            print(f"  loaded {program}")
        except Exception as exc:  # noqa: BLE001
            print(f"  could not load {program}: {exc}")

    try:
        while True:
            time.sleep(0.5)
            controller.collect()
    except KeyboardInterrupt:
        print("\n  stopping…")
    finally:
        if controller.running:
            controller.allow_control = True     # our own shutdown, not a client's
            controller.stop()
        server.stop()
    return 0
