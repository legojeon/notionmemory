"""User-scoped Notion request broker for sandboxes without Keychain access.

The broker is deliberately a *request* proxy, not a credential proxy.  Its
Unix socket is private to the current user and its wire format never contains
or returns a PAT.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import socket

import requests

from notionmemory.core import notion_auth, paths

API = "https://api.notion.com/v1"
MAX_MESSAGE_BYTES = 8 * 1024 * 1024


def socket_path() -> Path:
    return paths.state_dir() / "notion-broker.sock"


def available() -> bool:
    """Whether a private broker socket has been installed and is reachable."""
    path = socket_path()
    return path.is_socket() and (path.stat().st_mode & 0o777) == 0o600


def _readline(conn: socket.socket) -> bytes:
    data = bytearray()
    while len(data) <= MAX_MESSAGE_BYTES:
        chunk = conn.recv(min(65536, MAX_MESSAGE_BYTES - len(data) + 1))
        if not chunk:
            break
        data.extend(chunk)
        if b"\n" in chunk:
            return bytes(data).split(b"\n", 1)[0]
    if len(data) > MAX_MESSAGE_BYTES:
        raise ValueError("request exceeds broker limit")
    return bytes(data)


def _handle(raw: bytes) -> dict:
    try:
        data = json.loads(raw)
        method = str(data["method"]).upper()
        path = str(data["path"])
        if method not in {"GET", "POST", "PATCH", "DELETE"}:
            raise ValueError("unsupported method")
        if not path.startswith("/") or path.startswith("//") or "://" in path:
            raise ValueError("invalid path")
        token = notion_auth.load_pat()
        if not token:
            raise RuntimeError("Notion PAT unavailable in broker")
        response = requests.request(
            method, API + path,
            headers={"Authorization": f"Bearer {token}",
                     "Notion-Version": notion_auth.NOTION_VERSION,
                     "Content-Type": "application/json"},
            timeout=60, json=data.get("json"), params=data.get("params"))
        return {"status_code": response.status_code, "headers": dict(response.headers),
                "content": base64.b64encode(response.content).decode()}
    except Exception:  # Never return exception text: libraries can echo request headers.
        return {"error": "Broker request failed"}


def serve_forever(listener: socket.socket | None = None) -> None:
    """Serve requests until the process is stopped (used by the LaunchAgent)."""
    own_listener = listener is None
    path = socket_path()
    if own_listener:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        path.unlink(missing_ok=True)
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(path))
        os.chmod(path, 0o600)
        listener.listen()
    assert listener is not None
    try:
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            with conn:
                raw = _readline(conn)
                conn.sendall(json.dumps(_handle(raw)).encode() + b"\n")
    finally:
        listener.close()
        if own_listener:
            path.unlink(missing_ok=True)


def request(method: str, path: str, *, json_body=None, params=None) -> dict:
    if not available():
        raise RuntimeError("Notion broker is unavailable. Reinstall notionmemory to start it.")
    with socket.socket(socket.AF_UNIX) as client:
        client.settimeout(65)
        client.connect(str(socket_path()))
        client.sendall(json.dumps({"method": method, "path": path,
                                   "json": json_body, "params": params}).encode() + b"\n")
        reply = json.loads(_readline(client))
    if "error" in reply:
        raise RuntimeError(reply["error"])
    reply["content"] = base64.b64decode(reply["content"])
    return reply


# Test-only lifecycle helper.  Production uses ``serve_forever`` through the
# user LaunchAgent so it survives an agent session ending.
def running():
    import contextlib
    import threading

    @contextlib.contextmanager
    def _running():
        path = socket_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.unlink(missing_ok=True)
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(path))
        os.chmod(path, 0o600)
        listener.listen()
        thread = threading.Thread(target=serve_forever, args=(listener,), daemon=True)
        thread.start()
        try:
            yield path
        finally:
            listener.close()
            thread.join(timeout=1)
            path.unlink(missing_ok=True)
    return _running()
