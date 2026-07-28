from notionmemory.app import build_app


def test_build_app_with_no_skills(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text("integrations: {}\n")
    client = build_app(str(p), skills=[]).test_client()
    assert client.get("/api/skills").get_json() == []
    assert len(client.get("/api/integrations").get_json()) == 3
    assert client.get("/").status_code == 200


def test_registry_includes_memory_skill(tmp_path):
    from notionmemory.app import build_registry
    registry = build_registry(str(tmp_path / "config.yaml"))
    assert registry.get("memory") is not None
    assert registry.get("memory-capture") is None
    card = next(c for c in registry.cards() if c.id == "memory")
    assert card.requires == ["notion"]
    assert card.status == "blocked"  # conftest 가 keyring 을 비워두므로 미연결
