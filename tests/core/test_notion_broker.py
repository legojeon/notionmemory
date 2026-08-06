import os
from pathlib import Path

from notionmemory.core import notion_broker
from notionmemory.core.install.handlers import LaunchAgent
from notionmemory.core.install.spec import ArtifactSpec


def test_broker_socket_is_private_and_forwards_without_returning_pat(tmp_path, monkeypatch):
    path = Path("/private/tmp") / f"notionmemory-test-{os.getpid()}.sock"
    path.unlink(missing_ok=True)
    monkeypatch.setattr(notion_broker, "socket_path", lambda: path)
    monkeypatch.setattr(notion_broker.notion_auth, "load_pat", lambda: "ntn_secret")
    seen = {}

    class Response:
        status_code = 200
        headers = {"Content-Type": "application/json"}
        content = b'{"ok":true}'

    def fake_request(method, url, headers, timeout, **kwargs):
        seen.update(method=method, url=url, headers=headers, kwargs=kwargs)
        return Response()

    monkeypatch.setattr(notion_broker.requests, "request", fake_request)
    with notion_broker.running():
        reply = notion_broker.request("GET", "/users/me")
        assert os.stat(path).st_mode & 0o777 == 0o600

    assert reply["status_code"] == 200
    assert "ntn_secret" not in repr(reply)
    assert seen["headers"]["Authorization"] == "Bearer ntn_secret"


def test_broker_never_reflects_a_pat_in_an_error(monkeypatch):
    monkeypatch.setattr(notion_broker.notion_auth, "load_pat", lambda: "ntn_secret")
    monkeypatch.setattr(notion_broker.requests, "request",
                        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("ntn_secret leaked")))

    reply = notion_broker._handle(b'{"method":"GET","path":"/users/me"}')

    assert reply == {"error": "Broker request failed"}


def test_launch_agent_is_marked_and_removable(tmp_path, monkeypatch):
    path = tmp_path / "com.notionmemory.notion-broker.plist"
    spec = ArtifactSpec(
        id="shared.notion_broker", owner="_core", handler="launch_agent", target="shared",
        path=path, payload={"label": "com.notionmemory.notion-broker",
                            "program": "/x/notionmemory", "home": str(tmp_path)},
        markers=("notionmemory broker",))
    monkeypatch.setattr("notionmemory.core.install.handlers.subprocess.run", lambda *a, **k: None)

    handler = LaunchAgent()
    assert handler.install(spec) is True
    assert handler.detect(spec) is True
    assert "notionmemory broker" in path.read_text(encoding="utf-8")
    assert handler.remove(spec) is True
    assert not path.exists()
