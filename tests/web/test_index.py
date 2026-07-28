from notionmemory.core.config import Config
from notionmemory.core.integrations import build_integrations
from notionmemory.core.registry import Registry
from notionmemory.web.server import create_app


def test_root_serves_dashboard_html():
    reg = Registry([], build_integrations(Config({})), Config({}))
    resp = create_app(reg).test_client().get("/")
    assert resp.status_code == 200
    assert b"notionmemory" in resp.data.lower()
    assert b"app.js" in resp.data
    assert b"design.css" in resp.data
    assert b"styles.css" in resp.data


def test_app_js_wires_integration_panel():
    reg = Registry([], build_integrations(Config({})), Config({}))
    resp = create_app(reg).test_client().get("/assets/app.js")
    assert resp.status_code == 200
    body = resp.data.decode()
    assert "openIntegration" in body
    assert "/test" in body and "/connect" in body and "/disconnect" in body
