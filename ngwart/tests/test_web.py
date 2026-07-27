"""Web mode: REST for commands, WebSocket for the live stream.

Every test binds port 0 so the OS picks a free one; a fixed port would fail
whenever a station happens to be serving.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import threading
import time
import urllib.error
import urllib.request

import pytest

import ngwart.drivers  # noqa: F401
from ngwart.web import Station, WebServer

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.join(HERE, "..", "programs", "demo.yaml")
PROGRAMS = os.path.join(HERE, "..", "programs")


@pytest.fixture
def server():
    made = []

    def factory(**kw):
        token = kw.pop("token", None)
        station = Station(simulate=True, **kw)
        srv = WebServer(station, host="127.0.0.1", port=0,
                        program_dir=PROGRAMS, token=token)
        station.listener = srv
        srv.start()
        made.append(srv)
        return srv, station

    yield factory
    for srv in made:
        srv.stop()


def get(srv, path, headers=None):
    url = "http://127.0.0.1:%d%s" % (srv.bound_port, path)
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def post(srv, path, payload=None, headers=None):
    url = "http://127.0.0.1:%d%s" % (srv.bound_port, path)
    head = {"Content-Type": "application/json"}
    head.update(headers or {})
    request = urllib.request.Request(
        url, method="POST", data=json.dumps(payload or {}).encode(),
        headers=head)
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read())


def collect_events(port, stop_after=6.0):
    """A real WebSocket client, gathering frames until the socket goes quiet."""
    events = []
    sock = socket.create_connection(("127.0.0.1", port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    handshake = (
        "GET /ws HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
        "Connection: Upgrade\r\nSec-WebSocket-Key: " + key + "\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n")
    sock.sendall(handshake.encode())

    head = b""
    while b"\r\n\r\n" not in head:
        head += sock.recv(4096)
    assert b"101" in head.split(b"\r\n")[0], head[:80]

    buf = b""
    sock.settimeout(stop_after)
    while True:
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        buf += chunk
        while len(buf) >= 2:
            length = buf[1] & 0x7F
            offset = 2
            if length == 126:
                length = struct.unpack("!H", buf[2:4])[0]
                offset = 4
            elif length == 127:
                length = struct.unpack("!Q", buf[2:10])[0]
                offset = 10
            if len(buf) < offset + length:
                break
            events.append(json.loads(buf[offset:offset + length]))
            buf = buf[offset + length:]
    sock.close()
    return events


# --- static and read-only API -------------------------------------------

def test_serves_the_app(server):
    srv, _ = server()
    status, body = get(srv, "/")
    assert status == 200
    assert b"NGWART" in body


def test_static_path_cannot_escape_the_package(server):
    srv, _ = server()
    assert get(srv, "/../../../etc/passwd")[0] == 404


def test_state_and_programs(server):
    srv, _ = server()
    status, body = get(srv, "/api/state")
    assert status == 200
    state = json.loads(body)
    assert state["program"] is None and state["simulate"] is True

    status, body = get(srv, "/api/programs")
    names = [p["name"] for p in json.loads(body)["programs"]]
    assert "demo.yaml" in names


def test_program_listing_skips_lock_files(tmp_path, server):
    _, station = server()
    (tmp_path / "real.yaml").write_text("exec: []")
    (tmp_path / "~$real.yaml").write_text("junk")
    (tmp_path / ".~lock.real.yaml#").write_text("junk")
    assert [p["name"] for p in station.programs(str(tmp_path))] == ["real.yaml"]


def test_verbs_endpoint(server):
    srv, _ = server()
    status, body = get(srv, "/api/verbs")
    assert status == 200
    assert len(json.loads(body)["verbs"]) > 100


def test_unknown_route_is_404(server):
    srv, _ = server()
    assert get(srv, "/api/nope")[0] == 404


# --- control is off by default ------------------------------------------

def test_control_is_refused_unless_enabled(server):
    """An endpoint that can energise a fixture is not on by default."""
    srv, _ = server(allow_control=False)
    status, body = post(srv, "/api/start")
    assert status == 403
    assert "read-only" in body["error"]


def test_token_guards_control_routes(server):
    srv, _ = server(allow_control=True, token="s3cret")
    assert post(srv, "/api/start")[0] == 401
    status, _ = post(srv, "/api/load", {"path": DEMO},
                     headers={"X-Ngwart-Token": "s3cret"})
    assert status == 200


def test_starting_without_a_program_is_a_conflict(server):
    srv, _ = server(allow_control=True)
    status, body = post(srv, "/api/start")
    assert status == 409
    assert "no program" in body["error"]


def test_loading_an_invalid_program_reports_diagnostics(tmp_path, server):
    import yaml

    srv, _ = server(allow_control=True)
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump({
        "modules": {"Flow": "FlowManager"},
        "exec": [["Flow", "NOSUCHVERB", "x"]]}))
    status, body = post(srv, "/api/load", {"path": str(bad)})
    assert status == 200
    errors = [d for d in body["diagnostics"] if d["severity"] == "error"]
    assert errors and not body["program"]["valid"]


# --- the live stream ----------------------------------------------------

def test_a_run_streams_to_the_browser(server):
    """The point of web mode: progress visible as it happens."""
    srv, station = server(allow_control=True)

    events = []
    thread = threading.Thread(
        target=lambda: events.extend(collect_events(srv.bound_port)),
        daemon=True)
    thread.start()
    time.sleep(0.4)

    assert post(srv, "/api/load", {"path": DEMO})[0] == 200
    assert post(srv, "/api/start")[0] == 200
    time.sleep(4)
    station.collect()
    thread.join(timeout=10)

    kinds = {e.get("type") for e in events}
    assert {"snapshot", "log", "step", "grid", "result"} <= kinds, kinds

    rows = [e for e in events if e.get("type") == "grid" and e.get("op") == "add"]
    assert len(rows) == 8, "expected 8 result rows, got %d" % len(rows)

    results = [e for e in events if e.get("type") == "result"]
    assert results and results[-1]["passed"] is True


def test_the_first_frame_carries_the_whole_state(server):
    """A browser opening mid-run must not start blind."""
    srv, _ = server(allow_control=True)
    post(srv, "/api/load", {"path": DEMO})

    events = collect_events(srv.bound_port, stop_after=1.5)
    assert events and events[0]["type"] == "snapshot"
    assert events[0]["state"]["program"]["name"] == "demo"


def test_report_is_downloadable_after_a_run(server):
    srv, station = server(allow_control=True)
    post(srv, "/api/load", {"path": DEMO})
    assert get(srv, "/api/report")[0] == 404      # nothing has run yet

    post(srv, "/api/start")
    time.sleep(4)
    station.collect()

    status, body = get(srv, "/api/report?format=xml")
    assert status == 200 and b"<LOG_XML>" in body
    assert b"<simulated>true</simulated>" in body, "a dry run must be tagged"

    status, body = get(srv, "/api/report?format=csv")
    assert status == 200 and b"uut,test,result" in body
    assert get(srv, "/api/report?format=bogus")[0] == 400


def test_program_directory_defaults_sensibly(tmp_path, monkeypatch):
    """The cwd is a poor default: a station is launched from the package root
    while its programs live a level down, so the picker came up empty and
    looked broken."""
    from ngwart.web import _pick_program_dir

    monkeypatch.chdir(tmp_path)
    (tmp_path / "programs").mkdir()
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "p.yaml").write_text("exec: []")

    # No hints at all -> the conventional folder, if it exists.
    assert _pick_program_dir(None, None) == "programs"
    # A program was opened -> list the folder it came from.
    assert _pick_program_dir(None, str(tmp_path / "elsewhere" / "p.yaml")) \
        == str(tmp_path / "elsewhere")
    # An explicit choice always wins.
    assert _pick_program_dir("chosen", str(tmp_path / "elsewhere" / "p.yaml")) \
        == "chosen"


def test_empty_listing_reports_where_it_looked(tmp_path, server):
    srv, station = server()
    srv.program_dir = str(tmp_path)
    status, body = get(srv, "/api/programs")
    payload = json.loads(body)
    assert status == 200
    assert payload["programs"] == []
    # The client shows this path, so "nothing found" is actionable.
    assert payload["dir"] == str(tmp_path)
