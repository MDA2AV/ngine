"""Telemetry server tests.

Every test binds port 0 so the OS picks a free one -- a fixed port would make
the suite fail whenever a station happens to be running.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import time

import pytest

from ngwart.engine.events import (GridEvent, LogEvent, ResultEvent,
                                  RunStateEvent)
from ngwart.engine.telemetry import TelemetryServer, event_to_dict


@pytest.fixture
def server():
    srv = TelemetryServer(port=0, host="127.0.0.1").start()
    yield srv
    srv.stop()


# --- websocket client ---------------------------------------------------

def ws_connect(port: int, timeout: float = 5.0) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall(
        f"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n"
        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
        f"Sec-WebSocket-Version: 13\r\n\r\n".encode())
    head = b""
    while b"\r\n\r\n" not in head:
        head += sock.recv(4096)
    assert b"101" in head.split(b"\r\n")[0], head[:80]
    return sock


def ws_read(sock, count: int, timeout: float = 5.0) -> list[dict]:
    """Read `count` text frames, tolerating fragmentation across recv()."""
    sock.settimeout(timeout)
    buf, out = b"", []
    while len(out) < count:
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
        while len(buf) >= 2 and len(out) < count:
            length = buf[1] & 0x7F
            offset = 2
            if length == 126:
                if len(buf) < 4:
                    break
                length = struct.unpack("!H", buf[2:4])[0]
                offset = 4
            elif length == 127:
                if len(buf) < 10:
                    break
                length = struct.unpack("!Q", buf[2:10])[0]
                offset = 10
            if len(buf) < offset + length:
                break
            payload, buf = buf[offset:offset + length], buf[offset + length:]
            out.append(json.loads(payload.decode()))
    return out


# --- tests --------------------------------------------------------------

def test_serialisation_tags_the_event_type():
    payload = event_to_dict(LogEvent("hello", "warn", 7))
    assert payload["type"] == "log"
    assert payload["message"] == "hello"
    assert payload["row"] == 7
    assert "t" in payload


def test_websocket_client_receives_events(server):
    sock = ws_connect(server.bound_port)
    time.sleep(0.2)
    server.emit(LogEvent("first", "info", 1))
    server.emit(RunStateEvent("running"))
    server.emit(GridEvent(grid=1, op="add", values=["VBAT", "1"], tag="PASS"))

    events = ws_read(sock, 4)
    kinds = [e["type"] for e in events]
    assert kinds[0] == "snapshot"
    assert "log" in kinds and "runstate" in kinds and "grid" in kinds
    sock.close()


def test_a_late_client_is_sent_the_backlog(server):
    """A dashboard opened mid-run must not start blind."""
    for i in range(5):
        server.emit(LogEvent(f"before-{i}", "info", i))

    sock = ws_connect(server.bound_port)
    events = ws_read(sock, 6)
    messages = [e.get("message") for e in events if e["type"] == "log"]
    assert messages == [f"before-{i}" for i in range(5)]
    sock.close()


def test_snapshot_precedes_the_backlog(server):
    server.set_snapshot(program="cargo", station="ST1")
    server.emit(LogEvent("after", "info", 0))
    sock = ws_connect(server.bound_port)
    events = ws_read(sock, 2)
    assert events[0]["type"] == "snapshot"
    assert events[0]["program"] == "cargo"
    sock.close()


def test_raw_tcp_client_gets_json_lines(server):
    """Not everything on a shop floor speaks WebSocket."""
    sock = socket.create_connection(("127.0.0.1", server.bound_port), timeout=5)
    sock.sendall(b"\n")                     # anything that is not an HTTP GET
    time.sleep(0.2)
    server.emit(LogEvent("plain", "info", 3))

    sock.settimeout(5)
    data = b""
    while b"\n" not in data or b"plain" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    payloads = [json.loads(l) for l in data.decode().splitlines() if l.strip()]
    assert any(p.get("message") == "plain" for p in payloads)
    sock.close()


def test_browser_get_serves_the_dashboard(server):
    sock = socket.create_connection(("127.0.0.1", server.bound_port), timeout=5)
    sock.sendall(b"GET / HTTP/1.1\r\nHost: x\r\n\r\n")
    sock.settimeout(5)
    data = b""
    while b"</html>" not in data:
        chunk = sock.recv(65536)
        if not chunk:
            break
        data += chunk
    assert b"200 OK" in data
    assert b"NGWART live" in data
    sock.close()


def test_emitting_with_no_clients_is_harmless(server):
    for i in range(100):
        server.emit(LogEvent(f"nobody-{i}", "info", i))
    assert server.client_count == 0


def test_a_dead_client_does_not_break_the_stream(server):
    sock = ws_connect(server.bound_port)
    time.sleep(0.2)
    sock.close()                            # vanish without a close frame
    for i in range(50):
        server.emit(LogEvent(f"after-{i}", "info", i))
    time.sleep(0.3)
    # A second client still works, which is what "never blocks the test" means.
    sock2 = ws_connect(server.bound_port)
    server.emit(LogEvent("still-alive", "info", 0))
    # snapshot + the 50-event backlog replay before the new one arrives
    events = ws_read(sock2, 60, timeout=3)
    assert any(e.get("message") == "still-alive" for e in events)
    sock2.close()


def test_a_run_streams_to_a_connected_client():
    """End to end: a real program, a real socket."""
    import ngwart.drivers  # noqa: F401
    from ngwart.engine import REGISTRY, RunOptions, Sequencer
    from ngwart.engine.loaders.native import from_dict

    srv = TelemetryServer(port=0, host="127.0.0.1").start()
    try:
        sock = ws_connect(srv.bound_port)
        time.sleep(0.2)

        program = from_dict({
            "modules": {"Flow": "FlowManager"},
            "config": [["TestData", "initAlive", "1"]],
            "exec": [["TestData", "INITDATA", "4", "3", "2"],
                     ["Flow", "EVAFLOAT", "1.0,2.0", "1.5",
                      "0,0,0;0,1,0;0,2,0", "min", "0,VTEST"]],
        }).finalize()
        Sequencer(REGISTRY, None,
                  RunOptions(simulate=True, telemetry=srv)).run(program)

        events = ws_read(sock, 40, timeout=3)
        kinds = {e["type"] for e in events}
        assert "runstate" in kinds
        assert "grid" in kinds          # the VTEST result reached the client
        assert "result" in kinds
        assert any(e.get("tag") == "PASS" for e in events if e["type"] == "grid")
        sock.close()
    finally:
        srv.stop()


def test_port_in_use_is_reported_not_swallowed():
    first = TelemetryServer(port=0, host="127.0.0.1").start()
    try:
        with pytest.raises(OSError, match="cannot serve telemetry"):
            TelemetryServer(port=first.bound_port, host="127.0.0.1").start()
    finally:
        first.stop()
