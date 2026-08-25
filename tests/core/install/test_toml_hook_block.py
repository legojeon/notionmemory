from pathlib import Path
from notionmemory.core.install.handlers import TomlHookBlock
from notionmemory.core.install.spec import ArtifactSpec

MARKERS = ("notionmemory hook",)


def _spec(path: Path) -> ArtifactSpec:
    events = {
        "UserPromptSubmit": [{"hooks": [
            {"type": "command", "command": "notionmemory hook user-prompt --harness kimi",
             "timeout": 20}]}],
        "SessionEnd": [{"hooks": [
            {"type": "command", "command": "notionmemory hook session-end --harness kimi",
             "timeout": 3}]}],
    }
    return ArtifactSpec(id="kimi.hooks", owner="_core", handler="toml_hook_block",
                        target="kimi", path=path, payload={"events": events},
                        markers=MARKERS)


def test_install_writes_our_hook_tables(tmp_path):
    p = tmp_path / "config.toml"
    h = TomlHookBlock()
    assert h.install(_spec(p)) is True
    text = p.read_text(encoding="utf-8")
    assert '[[hooks]]' in text
    assert 'event = "UserPromptSubmit"' in text
    assert 'command = "notionmemory hook user-prompt --harness kimi"' in text
    assert 'timeout = 3' in text


def test_install_is_idempotent(tmp_path):
    p = tmp_path / "config.toml"
    h = TomlHookBlock()
    h.install(_spec(p))
    assert h.install(_spec(p)) is False          # second run: no change
    assert p.read_text(encoding="utf-8").count("[[hooks]]") == 2


def test_preserves_user_content(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('model = "k2"\n\n[[hooks]]\nevent = "Stop"\n'
                 'command = "my-own-script"\ntimeout = 10\n', encoding="utf-8")
    h = TomlHookBlock()
    h.install(_spec(p))
    text = p.read_text(encoding="utf-8")
    assert 'model = "k2"' in text                # unrelated key kept
    assert 'command = "my-own-script"' in text   # user's own hook kept
    assert h.detect(_spec(p)) is True


def test_remove_strips_only_ours(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[[hooks]]\nevent = "Stop"\ncommand = "my-own-script"\ntimeout = 10\n',
                 encoding="utf-8")
    h = TomlHookBlock()
    h.install(_spec(p))
    assert h.remove(_spec(p)) is True
    text = p.read_text(encoding="utf-8")
    assert 'command = "my-own-script"' in text    # user's hook survives
    assert 'notionmemory hook' not in text        # ours gone
    assert h.detect(_spec(p)) is False
