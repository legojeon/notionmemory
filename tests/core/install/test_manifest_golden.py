import pytest
from notionmemory.core.install import manifest


@pytest.fixture
def fixed_home(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr("notionmemory.core.paths.home", lambda: tmp_path)
    return tmp_path


def _by_id(specs):
    return {s.id: s for s in specs}


def test_build_claude_codex_shape(fixed_home):
    specs = _by_id(manifest.build(["claude", "codex"], "notionmemory"))

    claude_hooks = specs["claude.hooks"]
    assert claude_hooks.handler == "json_hook_block"
    assert claude_hooks.path == fixed_home / ".claude" / "settings.json"
    assert claude_hooks.payload == {"events": manifest.HOOK_EVENTS("notionmemory", "claude")}
    assert claude_hooks.markers == manifest.HOOK_MARKERS

    codex_hooks = specs["codex.hooks"]
    assert codex_hooks.handler == "json_hook_block"
    assert codex_hooks.path == fixed_home / ".codex" / "hooks.json"
    assert codex_hooks.payload == {"events": manifest.HOOK_EVENTS("notionmemory", "codex")}

    assert "codex.trust" in specs
    # skill mirrors present for both targets
    assert any(i.startswith("claude.skills.") for i in specs)
    assert any(i.startswith("codex.skills.") for i in specs)
