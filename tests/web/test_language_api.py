from notionmemory.core.config import Config
from notionmemory.core.integrations import build_integrations
from notionmemory.core.registry import Registry
from notionmemory.web.server import create_app


def _client(tmp_path, cfg_dict=None):
    p = tmp_path / "config.yaml"
    cfg = Config(cfg_dict or {}, str(p))
    reg = Registry([], build_integrations(cfg), cfg)
    return create_app(reg).test_client(), p


def test_get_language_defaults_to_en(tmp_path):
    client, _ = _client(tmp_path)
    assert client.get("/api/language").get_json() == {"language": "en"}


def test_get_language_reads_config(tmp_path):
    client, _ = _client(tmp_path, {"language": "ko"})
    assert client.get("/api/language").get_json() == {"language": "ko"}


def test_get_language_invalid_config_falls_back_to_en(tmp_path):
    client, _ = _client(tmp_path, {"language": "fr"})
    assert client.get("/api/language").get_json() == {"language": "en"}


def test_post_language_saves_and_is_reflected(tmp_path):
    client, p = _client(tmp_path)
    resp = client.post("/api/language", json={"language": "ko"})
    assert resp.status_code == 200
    assert resp.get_json() == {"language": "ko"}
    assert Config.load(str(p)).get("language") == "ko"          # persisted to disk
    assert client.get("/api/language").get_json() == {"language": "ko"}  # in-memory too


def test_post_invalid_language_rejected_and_writes_nothing(tmp_path):
    client, p = _client(tmp_path)
    resp = client.post("/api/language", json={"language": "fr"})
    assert resp.status_code == 400
    assert not p.exists()
