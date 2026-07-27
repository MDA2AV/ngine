"""HTTP + WebSocket server for the web front end.

Two protocols on one port, because they answer different questions:

* **REST** for commands -- load, start, stop, fetch a report. These are
  request/response, they can fail in ways a client must distinguish, and they
  want status codes. Pushing them down a socket would mean reinventing all of
  that.
* **WebSocket** for the live stream. Every engine event, pushed. Polling a REST
  endpoint for a log that emits hundreds of lines a second is the wrong shape.

Safety comes first in the defaults. An endpoint that can start a test is a
remote-control surface on powered hardware, so:

* the server binds to localhost unless told otherwise;
* control is refused unless ``--allow-control`` was passed;
* binding to a public interface *with* control prints a warning naming the risk;
* an optional shared token guards every control route.

Read-only remote monitoring -- the common case -- needs none of that and is the
default.
"""

from __future__ import annotations

import json
import mimetypes
import os
import socket
import threading
import traceback
import urllib.parse

from ..engine.telemetry import (BACKLOG, TelemetryServer, _parse_headers,
                                _read_headers, _ws_frame, event_to_dict)

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PORT = 8080


class WebServer:
    """Serves the front end, the REST API, and the event stream."""

    def __init__(self, station, host: str = "127.0.0.1",
                 port: int = DEFAULT_PORT, token: str | None = None,
                 program_dir: str = ".") -> None:
        self.station = station
        self.host = host
        self.port = port
        self.token = token
        self.program_dir = program_dir

        # The event fan-out is the telemetry server's job; it already handles
        # client queues and dropping clients that fall behind. Its raw-event
        # backlog is switched off here: a new client gets the accumulated model
        # instead, which is complete rather than merely recent.
        self.events = TelemetryServer(port=0, host=host, backlog=0)

        from .live import LiveModel

        self.live = LiveModel()

        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # -- lifecycle --------------------------------------------------------

    def start(self) -> "WebServer":
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            server.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind((self.host, self.port))
            server.listen(16)
        except OSError as exc:
            server.close()
            raise OSError(f"cannot serve on {self.host}:{self.port}: {exc}") from exc
        server.settimeout(0.5)
        self._server = server
        self._thread = threading.Thread(target=self._accept_loop,
                                        name="ngwart-web", daemon=True)
        self._thread.start()
        return self

    @property
    def bound_port(self) -> int:
        if self._server is None:
            return self.port
        try:
            return self._server.getsockname()[1]
        except OSError:
            return self.port

    def stop(self) -> None:
        self._stop.set()
        if self._server is not None:
            try:
                self._server.close()
            except OSError:
                pass
        self.events.stop()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def emit(self, event) -> None:
        """Listener protocol -- fold into the model, then forward."""
        self.live.observe(event)
        self.events.emit(event)

    # -- accept -----------------------------------------------------------

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _addr = self._server.accept()  # type: ignore[union-attr]
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn,),
                             daemon=True).start()

    def _handle(self, conn: socket.socket) -> None:
        # An upgraded socket outlives this function -- the telemetry fan-out
        # owns it from then on. Closing it in the finally below would hang up on
        # the client immediately after a successful handshake, which looks like
        # a server that accepts WebSockets and then never sends anything.
        upgraded = False
        try:
            conn.settimeout(10)
            head = _read_headers(conn)
            if not head:
                conn.close()
                return
            request = head.split(b"\r\n")[0].decode("latin-1", "replace")
            method, _, rest = request.partition(" ")
            target = rest.rsplit(" ", 1)[0].strip() or "/"
            headers = _parse_headers(head)

            if headers.get("upgrade", "").lower() == "websocket":
                upgraded = self._upgrade(conn, headers)
                return

            body = b""
            length = int(headers.get("content-length", 0) or 0)
            if length:
                already = head.split(b"\r\n\r\n", 1)
                body = already[1] if len(already) > 1 else b""
                while len(body) < length:
                    chunk = conn.recv(min(65536, length - len(body)))
                    if not chunk:
                        break
                    body += chunk

            conn.settimeout(None)
            self._route(conn, method.upper(), target, headers, body)
        except Exception:  # noqa: BLE001 - a bad request must not kill the server
            try:
                self._send(conn, 500, {"error": "internal error"})
            except OSError:
                pass
        finally:
            if not upgraded:
                try:
                    conn.close()
                except OSError:
                    pass

    def _upgrade(self, conn: socket.socket, headers: dict) -> bool:
        """Hand the connection to the telemetry fan-out.

        Returns True when the socket has been adopted, so the caller knows not
        to close it.
        """
        import base64
        import hashlib

        from ..engine.telemetry import _WS_GUID, _Client

        key = headers.get("sec-websocket-key")
        if not key:
            conn.close()
            return False
        accept = base64.b64encode(
            hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
        conn.sendall(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            b"Connection: Upgrade\r\nSec-WebSocket-Accept: "
            + accept.encode() + b"\r\n\r\n")
        conn.settimeout(None)

        client = _Client(conn, websocket=True)
        with self.events._lock:                      # noqa: SLF001
            self.events._clients.append(client)      # noqa: SLF001
        client.start()

        # One frame with the whole picture: station state plus everything the
        # run has accumulated. The client renders that, then follows the live
        # stream. Replaying raw events instead meant a browser opened partway
        # through a long program saw only its most recent results.
        client.send(json.dumps({"type": "snapshot",
                                "state": self.station.state(),
                                "live": self.live.snapshot()}, default=str))
        return True

    # -- routing ----------------------------------------------------------

    def _route(self, conn, method: str, target: str, headers: dict,
               body: bytes) -> None:
        path, _, query = target.partition("?")
        params = urllib.parse.parse_qs(query)

        if path.startswith("/api/"):
            self._api(conn, method, path, params, headers, body)
            return
        if method != "GET":
            self._send(conn, 405, {"error": "method not allowed"})
            return
        self._static(conn, path)

    def _api(self, conn, method: str, path: str, params: dict,
             headers: dict, body: bytes) -> None:
        control_routes = {"/api/load", "/api/start", "/api/stop"}
        if path in control_routes:
            if not self._authorised(headers, params):
                self._send(conn, 401, {"error": "unauthorised"})
                return
            if not self.station.allow_control:
                self._send(conn, 403, {
                    "error": "this server is read-only",
                    "detail": "start it with --allow-control to run tests "
                              "remotely"})
                return

        try:
            if path == "/api/state" and method == "GET":
                self.station.collect()
                self._send(conn, 200, self.station.state())

            elif path == "/api/programs" and method == "GET":
                directory = (params.get("dir", [self.program_dir])[0]
                             or self.program_dir)
                self._send(conn, 200, {"dir": os.path.abspath(directory),
                                       "programs": self.station.programs(directory)})

            elif path == "/api/verbs" and method == "GET":
                from ..engine import REGISTRY

                self._send(conn, 200, {"verbs": [
                    {"module": v.module, "name": v.name, "legacy": v.legacy,
                     "args": [{"name": p.name, "required": p.required,
                               "doc": p.doc} for p in v.params]}
                    for v in sorted(REGISTRY.all(),
                                    key=lambda v: (v.module, v.name))]})

            elif path == "/api/load" and method == "POST":
                payload = json.loads(body or b"{}")
                target = payload.get("path")
                if not target:
                    self._send(conn, 400, {"error": "no path given"})
                    return
                self._send(conn, 200, self.station.load(target))

            elif path == "/api/start" and method == "POST":
                self._send(conn, 200, self.station.start())

            elif path == "/api/stop" and method == "POST":
                self._send(conn, 200, self.station.stop())

            elif path == "/api/report" and method == "GET":
                self.station.collect()
                if self.station.record is None:
                    self._send(conn, 404, {"error": "no run yet"})
                    return
                fmt = params.get("format", ["json"])[0].lower()
                from ..reports import FORMATS, to_csv, to_json, to_xml

                if fmt not in FORMATS:
                    self._send(conn, 400, {"error": f"unknown format '{fmt}'"})
                    return
                text = {"json": to_json, "xml": to_xml,
                        "csv": to_csv}[fmt](self.station.record)
                mime = {"json": "application/json", "xml": "application/xml",
                        "csv": "text/csv"}[fmt]
                self._raw(conn, 200, text.encode("utf-8"), mime)

            else:
                self._send(conn, 404, {"error": f"no route {method} {path}"})

        except PermissionError as exc:
            self._send(conn, 403, {"error": str(exc)})
        except FileNotFoundError as exc:
            self._send(conn, 404, {"error": str(exc)})
        except (RuntimeError, ValueError) as exc:
            self._send(conn, 409, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001
            self._send(conn, 500, {"error": f"{type(exc).__name__}: {exc}",
                                   "trace": traceback.format_exc(limit=3)})

    def _authorised(self, headers: dict, params: dict) -> bool:
        if not self.token:
            return True
        supplied = headers.get("x-ngwart-token") or params.get("token", [""])[0]
        return supplied == self.token

    # -- responses --------------------------------------------------------

    def _static(self, conn, path: str) -> None:
        name = "app.html" if path in ("/", "/index.html") else path.lstrip("/")
        # Refuse anything that climbs out of the package directory.
        full = os.path.normpath(os.path.join(HERE, name))
        if not full.startswith(HERE) or not os.path.isfile(full):
            self._raw(conn, 404, b"not found", "text/plain")
            return
        mime = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as fh:
            self._raw(conn, 200, fh.read(), mime)

    def _send(self, conn, status: int, payload) -> None:
        self._raw(conn, status, json.dumps(payload, default=str).encode(),
                  "application/json")

    def _raw(self, conn, status: int, body: bytes, mime: str) -> None:
        reason = {200: "OK", 400: "Bad Request", 401: "Unauthorized",
                  403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed",
                  409: "Conflict", 500: "Internal Server Error"}.get(status, "OK")
        conn.sendall(
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: {mime}\r\n"
            f"Content-Length: {len(body)}\r\nCache-Control: no-store\r\n"
            f"Connection: close\r\n\r\n".encode() + body)
