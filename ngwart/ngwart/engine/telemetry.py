"""Live telemetry: publish everything a run is doing, to anyone who connects.

The station serves a port for the whole session. Clients may come and go; the
test never waits for them and never fails because of them.

Three kinds of client are accepted on the same port, distinguished by what they
send first:

* ``GET`` with ``Upgrade: websocket``  -> a WebSocket, framed per RFC 6455
* ``GET /`` with no upgrade            -> a small live dashboard, so a browser
                                          is a working client with no tooling
* anything else                        -> newline-delimited JSON, for the many
                                          shop-floor tools that speak TCP but
                                          not WebSocket

WebSocket framing is implemented here rather than pulling in a dependency: the
server side of RFC 6455 is a handshake and one frame writer, and a test station
should not need a package index to boot.

Design rules, in priority order:

1. **The test is never blocked.** Each client has a bounded queue served by its
   own thread. A slow or dead client overflows its own queue and is dropped;
   ``emit`` does not wait, and no client can stall the sequencer.
2. **Late joiners are not lost.** A ring buffer of recent events is replayed on
   connect, after a snapshot of the current run, so a dashboard opened halfway
   through shows the whole picture.
3. **Failures here are never test failures.** Every socket path swallows its
   exceptions; the worst outcome is that telemetry stops.
"""

from __future__ import annotations

import base64
import hashlib
import json
import queue
import socket
import struct
import threading
import time
from dataclasses import asdict, is_dataclass

DEFAULT_PORT = 8765

#: Events replayed to a client that connects mid-run.
BACKLOG = 500

#: Per-client queue depth. Beyond this the client is too slow to keep up and is
#: dropped rather than allowed to apply backpressure to the test.
CLIENT_QUEUE = 2000

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# --- serialisation ------------------------------------------------------

def event_to_dict(event) -> dict:
    """Render an engine event as a JSON-ready dict tagged with its type."""
    if is_dataclass(event):
        payload = asdict(event)
    elif isinstance(event, dict):
        payload = dict(event)
    else:
        payload = {"repr": repr(event)}
    payload["type"] = type(event).__name__.replace("Event", "").lower()
    payload["t"] = round(time.time(), 3)
    return payload


def _dump(payload: dict) -> str:
    # default=str keeps a stray non-serialisable value (a numpy shape, a Path)
    # from taking the whole stream down.
    return json.dumps(payload, default=str, separators=(",", ":"))


# --- the server ---------------------------------------------------------

class TelemetryServer:
    """Broadcasts engine events. Implements the engine's Listener protocol."""

    def __init__(self, port: int = DEFAULT_PORT, host: str = "0.0.0.0",
                 backlog: int = BACKLOG) -> None:
        self.host = host
        self.port = port
        self._clients: list[_Client] = []
        self._lock = threading.Lock()
        self._backlog: list[dict] = []
        self._backlog_max = backlog
        self._snapshot: dict = {"type": "snapshot"}
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.dropped = 0

    # -- lifecycle --------------------------------------------------------

    def start(self) -> "TelemetryServer":
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):        # Windows
            server.setsockopt(socket.SOL_SOCKET,
                              socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            server.bind((self.host, self.port))
            server.listen(8)
        except OSError as exc:
            server.close()
            raise OSError(
                f"cannot serve telemetry on {self.host}:{self.port}: {exc}"
            ) from exc
        server.settimeout(0.5)
        self._server = server
        self._thread = threading.Thread(target=self._accept_loop,
                                        name="ngwart-telemetry", daemon=True)
        self._thread.start()
        return self

    @property
    def bound_port(self) -> int:
        """Actual port, which differs from `port` when 0 was requested."""
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
        with self._lock:
            clients = list(self._clients)
            self._clients.clear()
        for client in clients:
            client.close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def __enter__(self) -> "TelemetryServer":
        return self.start()

    def __exit__(self, *_exc) -> None:
        self.stop()

    # -- Listener ---------------------------------------------------------

    def emit(self, event) -> None:
        """Never blocks, never raises."""
        try:
            payload = event_to_dict(event)
        except Exception:  # noqa: BLE001
            return
        self._remember(payload)
        self.broadcast(payload)

    def broadcast(self, payload: dict) -> None:
        try:
            text = _dump(payload)
        except Exception:  # noqa: BLE001
            return
        with self._lock:
            clients = list(self._clients)
        for client in clients:
            if not client.send(text):
                self.dropped += 1
                self._remove(client)

    def set_snapshot(self, **fields) -> None:
        """State a late joiner needs before the replayed events make sense."""
        with self._lock:
            self._snapshot.update(fields)
            self._snapshot["type"] = "snapshot"

    def clear_backlog(self) -> None:
        """Called at the start of a run so a client is not shown the last one."""
        with self._lock:
            self._backlog.clear()

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    # -- internals --------------------------------------------------------

    def _remember(self, payload: dict) -> None:
        with self._lock:
            self._backlog.append(payload)
            if len(self._backlog) > self._backlog_max:
                del self._backlog[: len(self._backlog) - self._backlog_max]

    def _remove(self, client: "_Client") -> None:
        with self._lock:
            if client in self._clients:
                self._clients.remove(client)
        client.close()

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, addr = self._server.accept()  # type: ignore[union-attr]
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._handshake, args=(conn, addr),
                             daemon=True).start()

    def _handshake(self, conn: socket.socket, addr) -> None:
        try:
            conn.settimeout(5)
            head = _read_headers(conn)
            headers = _parse_headers(head)
            conn.settimeout(None)

            upgrade = headers.get("upgrade", "").lower()
            if upgrade == "websocket" and "sec-websocket-key" in headers:
                accept = base64.b64encode(hashlib.sha1(
                    (headers["sec-websocket-key"] + _WS_GUID).encode()
                ).digest()).decode()
                conn.sendall(
                    b"HTTP/1.1 101 Switching Protocols\r\n"
                    b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                    b"Sec-WebSocket-Accept: " + accept.encode() + b"\r\n\r\n")
                client = _Client(conn, websocket=True)
            elif head.startswith(b"GET"):
                body = DASHBOARD_HTML.encode("utf-8")
                conn.sendall(
                    b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\n"
                    b"Content-Length: " + str(len(body)).encode() +
                    b"\r\nConnection: close\r\n\r\n" + body)
                conn.close()
                return
            else:
                client = _Client(conn, websocket=False)
        except Exception:  # noqa: BLE001
            try:
                conn.close()
            except OSError:
                pass
            return

        with self._lock:
            self._clients.append(client)
            snapshot = dict(self._snapshot)
            backlog = list(self._backlog)

        client.start()
        client.send(_dump({**snapshot, "clients": self.client_count,
                           "backlog": len(backlog)}))
        for payload in backlog:
            if not client.send(_dump(payload)):
                self._remove(client)
                return


class _Client:
    """One connected consumer, served by its own thread and bounded queue."""

    def __init__(self, conn: socket.socket, websocket: bool) -> None:
        self.conn = conn
        self.websocket = websocket
        self.queue: queue.Queue = queue.Queue(maxsize=CLIENT_QUEUE)
        self.alive = True
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def send(self, text: str) -> bool:
        """Enqueue. False means the client is gone or hopelessly behind."""
        if not self.alive:
            return False
        try:
            self.queue.put_nowait(text)
            return True
        except queue.Full:
            # Too slow to keep up. Dropping it is correct: a test must not be
            # paced by a consumer.
            self.alive = False
            return False

    def _pump(self) -> None:
        while self.alive:
            try:
                text = self.queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                if self.websocket:
                    self.conn.sendall(_ws_frame(text.encode("utf-8")))
                else:
                    self.conn.sendall(text.encode("utf-8") + b"\n")
            except OSError:
                self.alive = False
                break
        self.close()

    def close(self) -> None:
        self.alive = False
        try:
            self.conn.close()
        except OSError:
            pass


# --- WebSocket framing --------------------------------------------------

def _ws_frame(payload: bytes, opcode: int = 0x1) -> bytes:
    """A single unfragmented, unmasked server frame."""
    header = bytearray([0x80 | opcode])
    length = len(payload)
    if length < 126:
        header.append(length)
    elif length < (1 << 16):
        header.append(126)
        header += struct.pack("!H", length)
    else:
        header.append(127)
        header += struct.pack("!Q", length)
    return bytes(header) + payload


def _read_headers(conn: socket.socket, limit: int = 65536) -> bytes:
    """Read an HTTP head, or return early for a client not speaking HTTP.

    A raw TCP consumer sends nothing resembling a request, so blocking until
    CRLFCRLF would stall it for the whole handshake timeout before its feed
    began. One chunk is enough to tell the two apart.
    """
    data = b""
    while len(data) < limit:
        try:
            chunk = conn.recv(4096)
        except socket.timeout:
            break
        if not chunk:
            break
        data += chunk
        if not data.lstrip().upper().startswith(b"GET"):
            break                     # not HTTP -- treat as a raw JSON consumer
        if b"\r\n\r\n" in data:
            break
    return data


def _parse_headers(raw: bytes) -> dict:
    headers = {}
    for line in raw.split(b"\r\n")[1:]:
        if b":" not in line:
            continue
        key, _, value = line.partition(b":")
        headers[key.decode("latin-1").strip().lower()] = \
            value.decode("latin-1").strip()
    return headers


# --- browser dashboard --------------------------------------------------

DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>NGWART live</title>
<style>
:root{--bg:#0d1417;--panel:#131c20;--rule:#263439;--ink:#e7eef0;--dim:#7c9098;
--accent:#3fb6ce;--pass:#4fc98a;--fail:#f0797e;--warn:#e0ac55}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 ui-sans-serif,"Segoe UI",system-ui,sans-serif}
header{padding:14px 20px;border-bottom:1px solid var(--rule);display:flex;
gap:22px;align-items:center;flex-wrap:wrap}
h1{margin:0;font-size:15px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}
.chip{font-size:12px;color:var(--dim)}
.chip b{color:var(--ink);font-variant-numeric:tabular-nums}
#state{padding:3px 10px;border-radius:4px;background:var(--rule);font-weight:600;font-size:12px}
main{display:grid;grid-template-columns:1fr 380px;gap:14px;padding:14px;
height:calc(100vh - 58px)}
@media(max-width:900px){main{grid-template-columns:1fr;height:auto}}
.panel{background:var(--panel);border:1px solid var(--rule);border-radius:8px;
display:flex;flex-direction:column;min-height:0}
.panel h2{margin:0;padding:9px 13px;font-size:11px;letter-spacing:.12em;
text-transform:uppercase;color:var(--dim);border-bottom:1px solid var(--rule)}
#log{flex:1;overflow:auto;padding:8px 13px;font:12px/1.55 ui-monospace,Consolas,monospace}
#log div{white-space:pre-wrap;word-break:break-word}
.lvl-error,.lvl-fail{color:var(--fail);font-weight:600}
.lvl-warn{color:var(--warn)}
.lvl-pass{color:var(--pass)}
.row{color:var(--dim)}
table{width:100%;border-collapse:collapse;font-size:12px}
td,th{padding:5px 13px;border-bottom:1px solid var(--rule);text-align:left}
th{color:var(--dim);font-weight:600;font-size:10px;letter-spacing:.08em;text-transform:uppercase}
.PASS{color:var(--pass);font-weight:700}.FAIL{color:var(--fail);font-weight:700}
#points{flex:1;overflow:auto}
#bar{height:4px;background:var(--rule);border-radius:2px;overflow:hidden;flex:1;min-width:120px}
#bar i{display:block;height:100%;width:0;background:var(--accent);transition:width .2s}
</style></head><body>
<header>
  <h1>NGWART live</h1>
  <span id="state">connecting</span>
  <span class="chip">program <b id="prog">--</b></span>
  <span class="chip">step <b id="step">--</b></span>
  <span class="chip">elapsed <b id="elapsed">0.0</b>s</span>
  <span class="chip">points <b id="npoints">0</b> / fails <b id="nfails">0</b></span>
  <div id="bar"><i></i></div>
</header>
<main>
  <section class="panel"><h2>Log</h2><div id="log"></div></section>
  <section class="panel"><h2>Results</h2>
    <div id="points"><table><thead><tr><th>UUT</th><th>Test</th><th>Value</th>
    <th>Result</th></tr></thead><tbody id="pbody"></tbody></table></div>
  </section>
</main>
<script>
const $=id=>document.getElementById(id);
let points=0,fails=0;
function connect(){
  const ws=new WebSocket("ws://"+location.host);
  ws.onopen=()=>{$("state").textContent="live";$("state").style.background="#1d5b3c"};
  ws.onclose=()=>{$("state").textContent="disconnected";
    $("state").style.background="#5b1d20";setTimeout(connect,2000)};
  ws.onmessage=e=>{let d;try{d=JSON.parse(e.data)}catch(_){return};handle(d)};
}
function handle(d){
  switch(d.type){
    case "snapshot": if(d.program)$("prog").textContent=d.program; break;
    case "log": addLog(d.message,d.level,d.row); break;
    case "step": $("step").textContent=d.text||"--"; break;
    case "progress": $("bar").firstElementChild.style.width=
      Math.max(0,Math.min(1,d.value))*100+"%"; break;
    case "timer": $("elapsed").textContent=(d.seconds||0).toFixed(1); break;
    case "runstate": $("state").textContent=d.state; break;
    case "grid": if(d.op==="add")addPoint(d.values,d.tag); break;
    case "result": addLog("RUN "+(d.passed?"PASS":"FAIL")+" "+(d.detail||""),
      d.passed?"pass":"fail"); break;
  }
}
function addLog(msg,level,row){
  const el=document.createElement("div");
  el.className="lvl-"+(level||"info");
  el.textContent=(row!=null?String(row).padStart(4)+"  ":"      ")+msg;
  const box=$("log");const stick=box.scrollTop+box.clientHeight>=box.scrollHeight-30;
  box.appendChild(el);
  while(box.childElementCount>3000)box.removeChild(box.firstChild);
  if(stick)box.scrollTop=box.scrollHeight;
}
function addPoint(values,tag){
  const v=values||[];const tr=document.createElement("tr");
  tr.innerHTML="<td>"+(v[1]||"")+"</td><td>"+(v[0]||"")+"</td><td>"+
    (v[4]!==undefined?v[4]:"")+"</td><td class='"+(tag||"")+"'>"+(tag||"")+"</td>";
  $("pbody").appendChild(tr);
  points++; if(tag==="FAIL")fails++;
  $("npoints").textContent=points;$("nfails").textContent=fails;
  $("points").scrollTop=$("points").scrollHeight;
}
connect();
</script></body></html>
"""
