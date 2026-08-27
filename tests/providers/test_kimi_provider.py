from notionmemory import providers


def test_kimi_registered_last():
    assert providers.names() == ["claude", "codex", "kimi", "pi", "opencode"]


def test_kimi_spec_fields():
    p = providers.get("kimi")
    assert p.config_home_env == "KIMI_CODE_HOME"
    assert p.home_dirname == ".kimi-code"
    assert p.hook_file_name == "config.toml"
    assert p.hook_format == "toml"
    assert p.hook_file_dedicated is False
    assert p.harness_token == "kimi"
    assert p.post_install_spec is None


def test_kimi_events_are_the_three_pipeline_hooks():
    ev = providers.get("kimi").events("notionmemory")
    assert set(ev) == {"UserPromptSubmit", "Stop", "SessionEnd"}
    # recall inject + enqueue + spawn; SessionEnd timeout 3 (observation-only)
    se = ev["SessionEnd"][0]["hooks"][0]
    assert se["command"] == "notionmemory hook session-end --harness kimi"
    assert se["timeout"] == 3
