"""app.js esc/raw/html 헬퍼 회귀 — node 로 app.js 전체를 평가해 순수 함수만 검사.
node 미설치 환경에서는 skip (스펙상 수동 브라우저 스모크가 최종 게이트)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parents[2] / "notionmemory/web/assets/app.js"
NODE = shutil.which("node")
# tests/conftest.py's autouse `no_real_cli` fixture monkeypatches the shared
# subprocess.run (detection.subprocess is the same module object) to always
# return a stub CompletedProcess for every test, to keep CLI-detection tests
# hermetic. That collides with this test's need to actually run node, so we
# capture the genuine subprocess.run here at import time — before any
# per-test fixture has a chance to patch it — and call that reference below.
_real_run = subprocess.run

PROBE = """
console.log(JSON.stringify({
  esc: esc('<img src=x onerror="p()">\\''),
  interp: html`<b title="${'"><i>'}">${'<i>&'}</b>`,
  rawpass: html`${raw("<i>ok</i>")}`,
  nested: html`<div>${raw(html`<em>${"<x>"}</em>`)}</div>`,
  nullish: html`[${null}|${undefined}]`,
  cardWithDb: skillCard({id: "memory", name: "Memory", kinds: ["capture"],
    status: "available", missing: [], surface: "agent",
    db_url: "https://www.notion.so/abc123"}),
  dbLinkOn: dbLinkHtml("https://www.notion.so/abc123"),
  dbLinkOff: dbLinkHtml(""),
  dbLinkMissing: dbLinkHtml(undefined),
  dbLinkEscaped: dbLinkHtml('"><script>alert(1)</script>'),
}));
"""


@pytest.mark.skipif(NODE is None, reason="node 미설치 — 수동 스모크로 대체")
def test_esc_and_html_helpers(tmp_path):
    probe = tmp_path / "probe.js"
    probe.write_text(APP_JS.read_text(encoding="utf-8") + PROBE, encoding="utf-8")
    out = _real_run([NODE, str(probe)], capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    data = json.loads(out.stdout)
    assert data["esc"] == "&lt;img src=x onerror=&quot;p()&quot;&gt;&#39;"
    assert data["interp"] == '<b title="&quot;&gt;&lt;i&gt;">&lt;i&gt;&amp;</b>'
    assert data["rawpass"] == "<i>ok</i>"                      # raw 는 통과
    assert data["nested"] == "<div><em>&lt;x&gt;</em></div>"   # 이중 이스케이프 없음
    assert data["nullish"] == "[|]"                            # null/undefined → 빈 문자열
    # DB 링크는 카드가 아니라 설정 모달로 옮겼다 — 카드에는 앵커가 없어야 한다.
    assert "<a " not in data["cardWithDb"]
    # dbLinkHtml: 있으면 앵커(_blank·noopener) 렌더, 없거나(""/undefined) 안전하게 빈 문자열.
    assert "<a " in data["dbLinkOn"] and 'href="https://www.notion.so/abc123"' in data["dbLinkOn"]
    assert 'target="_blank"' in data["dbLinkOn"] and 'rel="noopener"' in data["dbLinkOn"]
    assert data["dbLinkOff"] == "" and data["dbLinkMissing"] == ""
    # html`` 이스케이프 경유(raw 아님) — href/텍스트에 삽입된 마크업이 그대로 새지 않는다
    assert "<script>" not in data["dbLinkEscaped"]
    assert "&lt;script&gt;" in data["dbLinkEscaped"]
