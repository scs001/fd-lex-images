"""离线测试：不依赖网络与外部服务。"""

from fastapi.testclient import TestClient

from fd_lex_api.main import app

client = TestClient(app)


def test_healthz() -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_version_defaults_to_dev() -> None:
    resp = client.get("/api/version")
    assert resp.status_code == 200
    body = resp.json()
    assert body["service"] == "fd-lex-api"
    assert body["version"] == "dev"


def test_version_prefers_build_version_env(monkeypatch) -> None:
    monkeypatch.setenv("BUILD_VERSION", "sha-abc1234")
    resp = client.get("/api/version")
    assert resp.status_code == 200
    assert resp.json()["version"] == "sha-abc1234"
