#!/usr/bin/env python3
"""Minimal WebSocket client for NGWART telemetry -- stdlib only.

    py tools/telemetry_client.py [host] [port]

Prints every event as it arrives. Use it as a starting point for a line
dashboard, an MES bridge, or a shift logger. For something even simpler, open a
raw TCP socket to the same port and send a newline: the server falls back to
newline-delimited JSON.
"""

import base64
import json
import os
import socket
import struct
import sys


def frames(sock):
    """Yield text payloads from a server-side (unmasked) WebSocket stream."""
    buf = b""

    def need(n):
        nonlocal buf
        while len(buf) < n:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError("server closed the connection")
            buf += chunk
        out, buf = buf[:n], buf[n:]
        return out

    while True:
        b0, b1 = need(2)
        opcode = b0 & 0x0F
        masked = b1 & 0x80
        length = b1 & 0x7F
        if length == 126:
            length = struct.unpack("!H", need(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", need(8))[0]
        key = need(4) if masked else b""
        payload = need(length)
        if masked:
            payload = bytes(c ^ key[i % 4] for i, c in enumerate(payload))
        if opcode == 0x8:                      # close
            return
        if opcode == 0x1:                      # text
            yield payload.decode("utf-8", "replace")


def main() -> int:
    host = sys.argv[1] if len(sys.argv) > 1 else "localhost"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765

    sock = socket.create_connection((host, port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall(
        f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\n"
        f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        .encode())

    head = b""
    while b"\r\n\r\n" not in head:
        head += sock.recv(4096)
    if b"101" not in head.split(b"\r\n")[0]:
        print("handshake failed:", head.split(b"\r\n")[0].decode())
        return 1
    print(f"connected to {host}:{port}\n")

    for text in frames(sock):
        try:
            event = json.loads(text)
        except ValueError:
            continue
        kind = event.get("type", "?")
        if kind == "log":
            row = event.get("row")
            print(f"{'' if row is None else row:>5}  [{event.get('level')}] "
                  f"{event.get('message')}")
        elif kind == "grid" and event.get("op") == "add":
            print(f"       RESULT {event.get('values')} -> {event.get('tag')}")
        elif kind == "result":
            print(f"\n  RUN {'PASS' if event.get('passed') else 'FAIL'} "
                  f"{event.get('detail') or ''}")
        elif kind in ("runstate", "snapshot"):
            print(f"  -- {kind}: "
                  f"{event.get('state') or event.get('program') or ''}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ConnectionError, OSError, KeyboardInterrupt) as exc:
        print(f"\ndisconnected: {exc}")
        sys.exit(1)
