"""memory 스킬 테스트 공유 fakes — Notion 세션을 흉내내되 실네트워크는 절대 안 침.

FakeResp/FakeSession 은 fixture 가 아니라 평범한 클래스다(테스트가 커스텀 응답이
필요한 경우가 많아 fixture 로 감싸면 오히려 유연성이 준다) — 다른 memory 테스트
파일에서도 `from tests.skills.memory.conftest import FakeResp, FakeSession` 로
그대로 재사용할 수 있다.
"""
from __future__ import annotations


class FakeResp:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body or {}
        self.text = text

    def json(self):
        return self._body


class FakeSession:
    """모든 request 호출을 기록한다. PATCH /pages/{id} 는 `.patched` 에도 남겨
    `set_status`/`set_properties` 테스트가 바로 검증할 수 있게 한다."""

    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []
        self.patched: dict | None = None

    def request(self, method: str, path: str, **kw):
        self.calls.append((method, path, kw))
        if method == "PATCH" and path.startswith("/pages/"):
            self.patched = {"path": path, "json": kw.get("json", {})}
            return FakeResp(200, {})
        raise AssertionError(f"unexpected {method} {path}")
