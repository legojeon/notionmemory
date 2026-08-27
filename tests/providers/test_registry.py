from notionmemory import providers


def test_names_are_claude_and_codex():
    assert providers.names() == ["claude", "codex", "kimi", "pi", "opencode"]


def test_claude_spec_fields():
    p = providers.get("claude")
    assert p.config_home_env == "CLAUDE_CONFIG_DIR"
    assert p.home_dirname == ".claude"
    assert p.hook_file_name == "settings.json"
    assert p.hook_format == "json"
    assert p.hook_file_dedicated is False
    assert p.harness_token == "claude"
    assert p.post_install_spec is None


def test_codex_spec_fields():
    p = providers.get("codex")
    assert p.config_home_env == "CODEX_HOME"
    assert p.home_dirname == ".codex"
    assert p.hook_file_name == "hooks.json"
    assert p.hook_format == "json"
    assert p.hook_file_dedicated is True
    assert p.harness_token == "codex"
    assert p.post_install_spec is not None


def test_events_are_byte_identical_to_legacy_hook_events():
    from notionmemory.core.install import manifest
    assert providers.get("claude").events("notionmemory") == \
        manifest.HOOK_EVENTS("notionmemory", "claude")
    assert providers.get("codex").events("notionmemory") == \
        manifest.HOOK_EVENTS("notionmemory", "codex")
