"""电子签离线测试（change lex-contract-esignature，spec 8 条 requirements 对账）。

ESIGN_PROVIDER=stub（进程内假件，零网络）；库与文件仓全部 tmp_path。
链接 URL=人面 H5 页（/api/esignature/p/{token}），逻辑走 JSON 接口面
（/api/esignature/s/{token}）；测试命名对账 spec 场景。
组 1/3.2/5.3/6.1/8.1/9.x 为外部依赖或部署面，不在离线测试范围。
"""

from __future__ import annotations

import base64
import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from fd_lex_api.config import reset_settings
from fd_lex_api.console_api.auth import ConsoleUser, require_console_user
from fd_lex_api.esignature.adapter import _STUB
from fd_lex_api.esignature.models import EsignEvent
from fd_lex_api.main import app
from fd_lex_api.metering.db import get_session, reset_metering_runtime
from fd_lex_api.metering.models import UNIT_SIGNING, MeteringRecord

USER = ConsoleUser(
    identity="lexdemocustomer",
    username="lexdemocustomer",
    email="demo@example.com",
    sub="sub-demo",
    roles=["lex-user"],
    organizations=["lex-demo"],
)

CONTRACT = "买卖合同全文\n甲方：A公司\n乙方：B公司\n标的：设备一台\n价款：10万元\n".encode("utf-8")
OTHER_TEXT = "买卖合同全文\n甲方：A公司\n乙方：B公司\n标的：设备一台\n价款：11万元\n".encode("utf-8")

CRED = {"method": "three-element", "serial": "31010119900101001X"}


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _token_of(url: str) -> str:
    return url.rsplit("/", 1)[1]


def _page_of(url: str) -> str:
    """人面 H5 页路径。"""
    return url.split("https://lex.test", 1)[1]


def _api_of(url: str) -> str:
    """逻辑 JSON 接口面路径（由链接 URL 推导）。"""
    return "/api/esignature/s/" + _token_of(url)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'lex.db'}")
    monkeypatch.setenv("ESIGN_PROVIDER", "stub")
    monkeypatch.setenv("ESIGN_FILE_STORE_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("INTERNAL_API_TOKEN", "test-internal")
    monkeypatch.setenv("CONSOLE_ORIGIN", "https://lex.test")
    reset_metering_runtime()
    app.dependency_overrides[require_console_user] = lambda: USER
    with TestClient(app) as c:  # lifespan 幂等建表（dev 便利开关）
        yield c
    app.dependency_overrides.clear()
    reset_metering_runtime()


def _create(client, *, title="设备买卖合同", category="sale", data=CONTRACT,
            signers=(("A公司代表", "甲方"), ("B公司代表", "乙方"))):
    resp = client.post(
        "/api/console/esignature/tasks",
        json={
            "title": title, "category": category, "file_name": "contract.txt",
            "file_b64": _b64(data),
            "signers": [{"name": n, "role_label": r} for n, r in signers],
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _initiate(client, task_id, acknowledged=False):
    return client.post(
        f"/api/console/esignature/tasks/{task_id}/initiate",
        json={"acknowledged": acknowledged},
    )


def _open_session(client, url):
    opened = client.get(_api_of(url))
    assert opened.status_code == 200, opened.text
    return opened.json()["session_token"]


def _sign_one(client, url, name):
    """签署人完整流：open → preview（阅读回执）→ realname → sign。"""
    sess = _open_session(client, url)
    headers = {"x-esign-session": sess}
    api = _api_of(url)
    pv = client.get(f"{api}/preview", headers=headers)
    assert pv.status_code == 200
    assert pv.content == CONTRACT
    rn = client.post(f"{api}/realname", json={"name": name, "credential": CRED}, headers=headers)
    assert rn.status_code == 200, rn.text
    sg = client.post(f"{api}/sign", json={"intent_method": "face"}, headers=headers)
    assert sg.status_code == 200, sg.text
    return sg.json()


def _complete_two(client, *, category="sale"):
    task_id = _create(client, category=category)
    resp = _initiate(client, task_id)
    assert resp.status_code == 200, resp.text
    links = resp.json()["links"]
    _sign_one(client, links[0]["url"], links[0]["name"])
    return task_id, _sign_one(client, links[1]["url"], links[1]["name"])


# ----------------------------------------------------- spec 第 1 条 锚定/状态机 ----

def test_anchor_locked_after_initiate_replaces_rejected(client):
    """「定稿文件被锚定后篡改请求被拒」：draft 可换版，pending 起 409。"""
    task_id = _create(client)
    ok = client.post(
        f"/api/console/esignature/tasks/{task_id}/file",
        json={"file_name": "contract.txt", "file_b64": _b64(CONTRACT + "改".encode())},
    )
    assert ok.status_code == 200  # 草稿期正常换版
    assert _initiate(client, task_id).status_code == 200
    resp = client.post(
        f"/api/console/esignature/tasks/{task_id}/file",
        json={"file_name": "contract.txt", "file_b64": _b64(CONTRACT + "再改".encode())},
    )
    assert resp.status_code == 409
    assert "作废旧任务" in resp.json()["detail"]


def test_revoke_invalidates_links(client):
    """「签署中撤销使链接失效」：撤销后接口面与 H5 页都如实拒绝。"""
    task_id = _create(client)
    url = _initiate(client, task_id).json()["links"][0]["url"]
    assert client.post(f"/api/console/esignature/tasks/{task_id}/revoke").status_code == 200
    api = client.get(_api_of(url))
    assert api.status_code == 410
    assert "撤销" in api.json()["detail"]
    page = client.get(_page_of(url))
    assert page.status_code == 410
    assert "撤销" in page.text


def test_rotate_links_kills_old(client):
    task_id = _create(client)
    old = _initiate(client, task_id).json()["links"][0]["url"]
    new = client.post(f"/api/console/esignature/tasks/{task_id}/links").json()["links"][0]["url"]
    assert client.get(_api_of(old)).status_code == 404  # 旧链接令牌已被覆盖
    assert client.get(_api_of(new)).status_code == 200


# ----------------------------------------------------- spec 第 2 条 全文不出侧 ----

def test_provider_never_sees_full_text(client):
    """走完流程后检查 stub 厂商侧收到的 envelope：仅哈希与元数据，无合同全文。"""
    task_id, _ = _complete_two(client)
    task = client.get(f"/api/console/esignature/tasks/{task_id}").json()
    payload = json.dumps(_STUB.received_envelopes[task["envelope_ref"]], ensure_ascii=False)
    assert task["anchor_sha256"] in payload
    for needle in ("买卖合同全文", "10万元", "设备一台"):
        assert needle not in payload


def test_read_receipt_recorded(client):
    task_id = _create(client)
    links = _initiate(client, task_id).json()["links"]
    sess = _open_session(client, links[0]["url"])
    client.get(_api_of(links[0]["url"]) + "/preview", headers={"x-esign-session": sess})
    with get_session() as db:
        ev = db.scalars(
            select(EsignEvent).where(
                EsignEvent.task_id == task_id, EsignEvent.action == "read_receipt"
            )
        ).all()
    assert len(ev) == 1
    assert ev[0].actor == "A公司代表"


# ----------------------------------------------------- spec 第 3 条 签署链接面 ----

def test_non_designated_person_refused(client):
    """「非指定本人拒签」：实名比对不符 403，且不产生签名。"""
    task_id = _create(client)
    url = _initiate(client, task_id).json()["links"][0]["url"]
    sess = _open_session(client, url)
    resp = client.post(_api_of(url) + "/realname",
                       json={"name": "冒名者", "credential": CRED},
                       headers={"x-esign-session": sess})
    assert resp.status_code == 403
    assert "本人" in resp.json()["detail"]
    task = client.get(f"/api/console/esignature/tasks/{task_id}").json()
    assert all(s["signed_at"] is None for s in task["signers"])


def test_sign_requires_realname_first(client):
    task_id = _create(client)
    url = _initiate(client, task_id).json()["links"][0]["url"]
    sess = _open_session(client, url)
    resp = client.post(_api_of(url) + "/sign", json={"intent_method": "face"},
                       headers={"x-esign-session": sess})
    assert resp.status_code == 409
    assert "实名" in resp.json()["detail"]


def test_two_signers_complete_and_evidence(client):
    task_id, done = _complete_two(client)
    assert done["task_status"] == "completed"
    task = client.get(f"/api/console/esignature/tasks/{task_id}").json()
    assert task["status"] == "completed" and task["evidence_available"]
    resp = client.get(f"/api/console/esignature/tasks/{task_id}/evidence")
    assert resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        names = set(zf.namelist())
        assert {"manifest.json", "events.ndjson", "provider_report.json"} <= names
        manifest = json.loads(zf.read("manifest.json"))
    assert manifest["anchor_sha256"] == task["anchor_sha256"]
    cards = client.get(f"/api/console/esignature/tasks/{task_id}/evidence/cards").json()["cards"]
    assert len(cards) == 2
    assert cards[0]["编号"] == "SP001" and cards[0]["置信度"] == "高"


# ----------------------------------------------------- spec 第 4 条 不代签 ----

def test_signer_face_ignores_platform_credentials(client):
    """internal bearer 与无会话都不能驱动落签；控制台面不存在 sign 路径。"""
    task_id = _create(client)
    url = _initiate(client, task_id).json()["links"][0]["url"]
    resp = client.post(_api_of(url) + "/sign",
                       json={"intent_method": "face"},
                       headers={"Authorization": "Bearer test-internal"})
    assert resp.status_code == 401
    paths = app.openapi()["paths"]
    assert not [p for p in paths if p.startswith("/api/console/esignature") and p.endswith("/sign")]
    assert not [p for p in paths if p.startswith("/internal") and "esignature" in p]


# ----------------------------------------------------- spec 第 5 条 适用性闸门 ----

def test_gate_blocks_excluded_documents(client):
    """「人身关系合同被阻断」：类别与标题线索都阻断，展示已核验第三条原文。"""
    task_id = _create(client, title="离婚协议书", category="sale")
    resp = _initiate(client, task_id)
    assert resp.status_code == 422
    body = json.loads(resp.json()["detail"])
    assert body["verdict"] == "block"
    assert body["title_hit"]
    basis = body["legal_basis"]  # 来自 fd-legal-search-mcp 核验（legal_basis.json）
    assert basis["statute"] == "中华人民共和国电子签名法" and basis["status"] == "有效"
    assert "婚姻、收养、继承" in basis["text"]
    assert "停止供水、供热、供气" in basis["text"]
    assert basis["provenance"]["source"] == "law_db.law_chunks_v2"

    task_id2 = _create(client, title="赡养协议", category="marriage-family")
    assert _initiate(client, task_id2).status_code == 422


def test_gate_labor_notice_then_ack(client):
    """「劳动合同提示后放行」：未确认 400+require_ack；确认后入签且双事件入账。"""
    task_id = _create(client, title="劳动合同书", category="labor")
    resp = _initiate(client, task_id)
    assert resp.status_code == 400
    body = json.loads(resp.json()["detail"])
    assert body["require_ack"] is True
    notice = body["notice"]
    assert "电子劳动合同订立指引" in notice
    assert "第十三条" in notice  # 引用的是已核验条文
    assert "未经核验" in notice  # 指引未收录，如实标注、不引用其条文
    assert _initiate(client, task_id, acknowledged=True).status_code == 200
    with get_session() as db:
        actions = [e.action for e in db.scalars(
            select(EsignEvent).where(EsignEvent.task_id == task_id)
        ).all()]
    assert "gate_notice_shown" in actions and "gate_notice_acknowledged" in actions


def test_gate_loan_enhanced_notice(client):
    task_id = _create(client, title="借款协议", category="loan")
    resp = _initiate(client, task_id)
    assert resp.status_code == 400
    assert "冒名" in json.loads(resp.json()["detail"])["notice"]


# ----------------------------------------------------- spec 第 6 条 出证可验 ----

def test_verify_detects_tamper(client):
    """「篡改文件验证失败」：一字之差即不通过；原件通过。"""
    task_id, _ = _complete_two(client)
    ok = client.post("/api/console/esignature/verify",
                     json={"task_id": task_id, "file_b64": _b64(CONTRACT)}).json()
    assert ok["valid"] is True
    bad = client.post("/api/console/esignature/verify",
                      json={"task_id": task_id, "file_b64": _b64(OTHER_TEXT)}).json()
    assert bad["valid"] is False
    assert [c for c in bad["checks"] if c["name"] == "content_integrity"][0]["passed"] is False


def test_verify_before_completion(client):
    task_id = _create(client)
    _initiate(client, task_id)
    out = client.post("/api/console/esignature/verify",
                      json={"task_id": task_id, "file_b64": _b64(CONTRACT)}).json()
    assert out["valid"] is False


# ----------------------------------------------------- spec 第 7 条 fail-closed ----

def test_provider_unconfigured_honest_error(client):
    """「机房环境未配连接器如实报错」：503+签署腿未配置，任务留草稿、零计量。"""
    import os

    os.environ["ESIGN_PROVIDER"] = ""
    reset_settings()
    try:
        task_id = _create(client)
        resp = _initiate(client, task_id)
        assert resp.status_code == 503
        assert "签署腿未配置" in resp.json()["detail"]
        assert client.get(f"/api/console/esignature/tasks/{task_id}").json()["status"] == "draft"
        with get_session() as db:
            assert db.scalars(
                select(MeteringRecord).where(MeteringRecord.unit == UNIT_SIGNING)
            ).all() == []
    finally:
        os.environ["ESIGN_PROVIDER"] = "stub"
        reset_settings()


# ----------------------------------------------------- spec 第 8 条 计量 ----

def test_metering_per_completed_signer(client):
    """「三方签署按三份计量」+ 撤销份数不计：4 人中 3 签成 + 1 未签撤销 → 入账 3。"""
    task_id = _create(
        client,
        signers=(("A公司代表", "甲方"), ("B公司代表", "乙方"), ("见证人甲", "第三方"), ("见证人乙", "第三方")),
    )
    links = _initiate(client, task_id).json()["links"]
    _sign_one(client, links[0]["url"], links[0]["name"])
    _sign_one(client, links[1]["url"], links[1]["name"])
    _sign_one(client, links[2]["url"], links[2]["name"])
    assert client.post(f"/api/console/esignature/tasks/{task_id}/revoke").status_code == 200
    with get_session() as db:
        rows = db.scalars(
            select(MeteringRecord).where(MeteringRecord.unit == UNIT_SIGNING)
        ).all()
    assert len(rows) == 3
    assert {r.caller for r in rows} == {"lexdemocustomer"}
    assert {r.credential_track for r in rows} == {"customer"}


# ----------------------------------------------------- H5 面（微信内浏览器）----

def test_h5_page_render_and_server_side_denials(client):
    task_id = _create(client)
    url = _initiate(client, task_id).json()["links"][0]["url"]
    page = client.get(_page_of(url))
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "电子签署" in page.text and _token_of(url) in page.text
    # 不存在 token：页面级 404；撤销后：页面级 410 如实文案
    assert client.get("/api/esignature/p/nonexistent-token").status_code == 404
    assert client.post(f"/api/console/esignature/tasks/{task_id}/revoke").status_code == 200
    revoked = client.get(_page_of(url))
    assert revoked.status_code == 410
    assert "撤销" in revoked.text
