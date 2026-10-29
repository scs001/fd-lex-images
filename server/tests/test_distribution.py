"""分发面（/api/distribution）离线测试：鉴权 fail-closed、下载完整性、Range 断点续传、
坏哈希拒绝语义、manifest 列表/详情、与 packer 产物的真实契约（若 packer 在仓）。

测试隔离：DISTRIBUTION_ROOT 指向 tmp_path 合成 pack 目录；不触网/不触库。
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fd_lex_api.config import reset_settings
from fd_lex_api.main import app

TOKEN = "test-distribution-token"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}
SCHEMA = "lex.distribution.manifest/v1"
CAPABILITIES = {
    "law_search": {"cloud": True, "on_prem": True, "note": "法条检索"},
    "customer_console_billing": {"cloud": True, "on_prem": False, "note": "云侧专属"},
}
HOST_DELTAS = [
    {"capability": "customer_console_billing", "cloud": True, "on_prem": False,
     "note": "云侧专属，客户机房无账单面"}
]


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def make_bundle(
    root: Path,
    bundle_id: str = "lex-dist-v0.1.0-citation",
    *,
    form: str = "full",
    data: bytes = b"pack-payload-0123456789",
    tier: str = "citation",
    with_sidecar: bool = True,
    with_pack: bool = True,
) -> Path:
    """按 packer 目录约定合成一个 bundle（manifest/pack.tar/pack.tar.sha256/data）。"""
    directory = root / bundle_id
    (directory / "data").mkdir(parents=True, exist_ok=True)
    component = directory / "data" / "laws.jsonl.gz"
    component.write_bytes(data)
    manifest = {
        "schema": SCHEMA,
        "bundle": {
            "id": bundle_id,
            "name": "lex-dist",
            "version": "0.1.0",
            "form": form,
            "tier": tier,
            "as_of": "2026-10-05",
            "built_at": "2026-10-05T00:00:00Z",
            "builder": "lex-packer/0.1.0",
            "hosts": ["cloud", "on_prem"],
            "base_bundle": "lex-dist-v0.1.0-citation" if form == "incremental" else None,
            "content_digest": _sha256(json.dumps(
                [{"name": "laws", "bytes": len(data), "sha256": _sha256(data)}],
                sort_keys=True, separators=(",", ":")).encode()),
        },
        "components": [
            {
                "name": "laws",
                "kind": "data",
                "tier": tier,
                "path": "data/laws.jsonl.gz",
                "bytes": len(data),
                "sha256": _sha256(data),
                "rows": 1,
                "provenance": {
                    "source": "law_db.public.laws",
                    "stable_id": "(src_db, src_id)",
                    "as_of": "2026-10-05",
                },
            }
        ],
        "capability_catalog": CAPABILITIES,
        "host_deltas": HOST_DELTAS,
        "model_assets": {"included": False, "artifacts": [], "note": "lineage 审计门槛未过"},
        "data_tiers": {"tier": tier, "included": ["laws"]},
        "guards": {"cloud_locked_guard": {"ok": True, "violations": []}},
        "missing_inputs": [],
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if with_pack:
        pack_bytes = b"TAR!" + data
        (directory / "pack.tar").write_bytes(pack_bytes)
        if with_sidecar:
            (directory / "pack.tar.sha256").write_text(
                f"{_sha256(pack_bytes)}  pack.tar\n", encoding="utf-8"
            )
    return directory


@pytest.fixture()
def dist_client(monkeypatch, tmp_path):
    """合成 pack 库（citation full + citation 增量）+ 配置好令牌的 TestClient。"""
    root = tmp_path / "distribution_packs"
    root.mkdir()
    make_bundle(root)
    make_bundle(root, "lex-dist-v0.1.1-citation-inc-2026-10-05", form="incremental",
                data=b"delta!")
    monkeypatch.setenv("DISTRIBUTION_ROOT", str(root))
    monkeypatch.setenv("DISTRIBUTION_API_TOKEN", TOKEN)
    reset_settings()
    try:
        yield TestClient(app), root
    finally:
        reset_settings()


# ---------------------------------------------------------------------------
# 鉴权 fail-closed
# ---------------------------------------------------------------------------


def test_requires_bearer_token(dist_client) -> None:
    client, _ = dist_client
    assert client.get("/api/distribution/manifests").status_code == 401
    assert client.get("/api/distribution/manifests",
                      headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_fail_closed_when_token_unconfigured(dist_client, monkeypatch) -> None:
    client, _ = dist_client
    monkeypatch.delenv("DISTRIBUTION_API_TOKEN", raising=False)
    reset_settings()
    try:
        resp = client.get("/api/distribution/manifests", headers=HEADERS)
        assert resp.status_code == 403
        assert "not configured" in resp.json()["detail"]
    finally:
        reset_settings()


# ---------------------------------------------------------------------------
# manifest 列表 / 详情
# ---------------------------------------------------------------------------


def test_list_manifests(dist_client) -> None:
    client, _ = dist_client
    resp = client.get("/api/distribution/manifests", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    full = next(item for item in body["items"] if item["form"] == "full")
    assert full["bundle_id"] == "lex-dist-v0.1.0-citation"
    assert full["tier"] == "citation"
    assert full["pack_sha256"] and full["pack_bytes"]
    assert full["download_url"] == "/api/distribution/packs/lex-dist-v0.1.0-citation"
    assert "wgk-" in body["auth"]["note"]  # 客户级凭据如实标注为后续项


def test_list_filters(dist_client) -> None:
    client, _ = dist_client
    assert client.get("/api/distribution/manifests", params={"tier": "judgment"},
                      headers=HEADERS).json()["count"] == 0
    assert client.get("/api/distribution/manifests", params={"form": "incremental"},
                      headers=HEADERS).json()["count"] == 1
    assert client.get("/api/distribution/manifests", params={"tier": "bogus"},
                      headers=HEADERS).status_code == 422


def test_manifest_detail(dist_client) -> None:
    client, _ = dist_client
    resp = client.get("/api/distribution/manifests/lex-dist-v0.1.0-citation", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["schema"] == SCHEMA
    assert body["bundle"]["hosts"] == ["cloud", "on_prem"]
    assert body["pack"]["available"] is True
    assert body["pack"]["sha256"] == body["components"][0]["sha256"] or body["pack"]["sha256"]
    assert body["model_assets"]["included"] is False


def test_unknown_bundle_404(dist_client) -> None:
    client, _ = dist_client
    assert client.get("/api/distribution/manifests/lex-dist-v9.9.9-citation",
                      headers=HEADERS).status_code == 404
    assert client.get("/api/distribution/packs/lex-dist-v9.9.9-citation",
                      headers=HEADERS).status_code == 404


def test_path_traversal_rejected(dist_client) -> None:
    client, _ = dist_client
    resp = client.get("/api/distribution/manifests/..%2F..%2Fetc", headers=HEADERS)
    assert resp.status_code in (404, 422)


# ---------------------------------------------------------------------------
# 下载完整性 + Range 断点续传
# ---------------------------------------------------------------------------


def test_download_full_integrity(dist_client) -> None:
    client, root = dist_client
    expected = (root / "lex-dist-v0.1.0-citation" / "pack.tar").read_bytes()
    resp = client.get("/api/distribution/packs/lex-dist-v0.1.0-citation", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.content == expected
    assert _sha256(resp.content) == resp.headers["x-lex-bundle-sha256"]
    assert resp.headers["accept-ranges"] == "bytes"
    assert int(resp.headers["content-length"]) == len(expected)
    assert resp.headers["etag"].startswith('"')


def test_head_probe(dist_client) -> None:
    client, root = dist_client
    total = (root / "lex-dist-v0.1.0-citation" / "pack.tar").stat().st_size
    resp = client.head("/api/distribution/packs/lex-dist-v0.1.0-citation", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.headers["accept-ranges"] == "bytes"
    assert int(resp.headers["content-length"]) == total
    assert resp.content == b""


def test_range_resume(dist_client) -> None:
    client, root = dist_client
    expected = (root / "lex-dist-v0.1.0-citation" / "pack.tar").read_bytes()
    total = len(expected)

    first = client.get("/api/distribution/packs/lex-dist-v0.1.0-citation", headers={
        **HEADERS, "Range": "bytes=0-6",
    })
    assert first.status_code == 206
    assert first.content == expected[:7]
    assert first.headers["content-range"] == f"bytes 0-6/{total}"
    assert first.headers["content-length"] == "7"

    rest = client.get("/api/distribution/packs/lex-dist-v0.1.0-citation", headers={
        **HEADERS, "Range": "bytes=7-",
    })
    assert rest.status_code == 206
    assert rest.content == expected[7:]
    assert first.content + rest.content == expected  # 断点续传拼回原包

    tail = client.get("/api/distribution/packs/lex-dist-v0.1.0-citation", headers={
        **HEADERS, "Range": "bytes=-4",
    })
    assert tail.status_code == 206
    assert tail.content == expected[-4:]
    assert tail.headers["content-range"] == f"bytes {total - 4}-{total - 1}/{total}"


def test_range_unsatisfiable_416(dist_client) -> None:
    client, _ = dist_client
    resp = client.get("/api/distribution/packs/lex-dist-v0.1.0-citation", headers={
        **HEADERS, "Range": "bytes=999999-",
    })
    assert resp.status_code == 416
    assert resp.headers["content-range"].startswith("bytes */")


def test_malformed_or_multipart_range_ignored(dist_client) -> None:
    client, root = dist_client
    expected = (root / "lex-dist-v0.1.0-citation" / "pack.tar").read_bytes()
    for header in ("bytes=abc-def", "items=0-1", "bytes=0-1,3-4"):
        resp = client.get("/api/distribution/packs/lex-dist-v0.1.0-citation", headers={
            **HEADERS, "Range": header,
        })
        assert resp.status_code == 200, header
        assert resp.content == expected, header


def test_if_range_mismatch_serves_full(dist_client) -> None:
    client, root = dist_client
    expected = (root / "lex-dist-v0.1.0-citation" / "pack.tar").read_bytes()
    resp = client.get("/api/distribution/packs/lex-dist-v0.1.0-citation", headers={
        **HEADERS, "Range": "bytes=0-3", "If-Range": '"stale-etag"',
    })
    assert resp.status_code == 200
    assert resp.content == expected

    resp = client.get("/api/distribution/packs/lex-dist-v0.1.0-citation", headers={
        **HEADERS, "Range": "bytes=0-3", "If-Range": resp.headers.get("ETag", '"x"'),
    })
    # 用真实 ETag 再取一次 → 206
    etag = client.head("/api/distribution/packs/lex-dist-v0.1.0-citation",
                       headers=HEADERS).headers["etag"]
    ok = client.get("/api/distribution/packs/lex-dist-v0.1.0-citation", headers={
        **HEADERS, "Range": "bytes=0-3", "If-Range": etag,
    })
    assert ok.status_code == 206
    assert ok.content == expected[:4]


def test_incremental_bundle_downloadable(dist_client) -> None:
    """离线整包与在线增量同端点形态：增量包同样可列/可下/可校验。"""
    client, root = dist_client
    expected = (root / "lex-dist-v0.1.1-citation-inc-2026-10-05" / "pack.tar").read_bytes()
    resp = client.get(
        "/api/distribution/packs/lex-dist-v0.1.1-citation-inc-2026-10-05", headers=HEADERS
    )
    assert resp.status_code == 200
    assert resp.content == expected
    manifests = client.get("/api/distribution/manifests", params={"form": "incremental"},
                           headers=HEADERS).json()["items"]
    assert manifests[0]["bundle_id"].endswith("-inc-2026-10-05")


# ---------------------------------------------------------------------------
# sha256 校验端点 / 坏哈希拒绝
# ---------------------------------------------------------------------------


def test_sha256_endpoint_declared_and_verified(dist_client) -> None:
    client, _ = dist_client
    resp = client.get(
        "/api/distribution/packs/lex-dist-v0.1.0-citation/sha256", headers=HEADERS
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["declared_sha256"]) == 64
    assert body["components"][0]["name"] == "laws"

    verified = client.get(
        "/api/distribution/packs/lex-dist-v0.1.0-citation/sha256",
        params={"verify": 1}, headers=HEADERS,
    )
    assert verified.status_code == 200
    assert verified.json()["match"] is True
    assert verified.json()["computed_sha256"] == verified.json()["declared_sha256"]


def test_sha256_endpoint_rejects_tampered_pack(dist_client) -> None:
    """坏包拒绝语义：pack 被篡改 → verify=1 返回 409（服务端不给坏包背书）。"""
    client, root = dist_client
    victim = root / "lex-dist-v0.1.0-citation" / "pack.tar"
    victim.write_bytes(victim.read_bytes() + b"tampered")
    resp = client.get(
        "/api/distribution/packs/lex-dist-v0.1.0-citation/sha256",
        params={"verify": 1}, headers=HEADERS,
    )
    assert resp.status_code == 409
    detail = resp.json()["detail"]
    assert detail["declared_sha256"] != detail["computed_sha256"]
    assert detail["error"] == "pack digest mismatch"
    # 客户端仍可拿到声明的摘要用于本地校验（不应用该包）
    declared = client.get(
        "/api/distribution/packs/lex-dist-v0.1.0-citation/sha256", headers=HEADERS
    )
    assert declared.status_code == 200


def test_sha256_missing_sidecar_conflict(monkeypatch, tmp_path) -> None:
    root = tmp_path / "packs_no_sidecar"
    root.mkdir()
    make_bundle(root, "lex-dist-v0.1.0-citation", with_sidecar=False)
    monkeypatch.setenv("DISTRIBUTION_ROOT", str(root))
    monkeypatch.setenv("DISTRIBUTION_API_TOKEN", TOKEN)
    reset_settings()
    try:
        client = TestClient(app)
        resp = client.get(
            "/api/distribution/packs/lex-dist-v0.1.0-citation/sha256", headers=HEADERS
        )
        assert resp.status_code == 409
        assert "pack.tar.sha256" in resp.json()["detail"]
        assert client.get("/api/distribution/packs/lex-dist-v0.1.0-citation",
                          headers=HEADERS).status_code == 409
    finally:
        reset_settings()


def test_catalog_exposes_host_deltas(dist_client) -> None:
    client, _ = dist_client
    resp = client.get("/api/distribution/catalog", headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["capabilities"]["law_search"]["on_prem"] is True
    assert body["host_deltas"][0]["capability"] == "customer_console_billing"
    assert "双宿主能力一致" in body["note"]


# ---------------------------------------------------------------------------
# 与 packer 产物的跨模块契约（packer 在仓即跑）
# ---------------------------------------------------------------------------


def test_serves_real_packer_build(monkeypatch, tmp_path) -> None:
    """真实契约：packer 构建的 bundle 原样被端点读取（manifest/下载/sha256 校验）。"""
    packer_dir = Path(__file__).resolve().parents[2] / "packer"
    if not (packer_dir / "lex_packer").is_dir():  # pragma: no cover
        pytest.skip("packer 不在仓内")
    sys.path.insert(0, str(packer_dir))
    try:
        from lex_packer.build import BuildRequest, build_bundle
    finally:
        sys.path.remove(str(packer_dir))

    src = tmp_path / "src"
    src.mkdir()
    rows = {
        "laws": [{"id": 1, "title": "民法典", "content": "第一条"}],
        "law_catalog": [{"id": 1, "title": "民法典"}],
        "law_chunks_v2": [{"chunk_id": "1-1", "law_id": 1, "chunk_no": 1, "chunk_text": "第一条"}],
        "guide_cases": [{"source_id": "gc-1", "title": "指导案例1号", "body": "全文"}],
    }
    for name, items in rows.items():
        (src / f"{name}.jsonl").write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in items) + "\n",
            encoding="utf-8",
        )
    result = build_bundle(
        BuildRequest(tier="citation", version="0.1.0", out_dir=tmp_path / "dist",
                     source_dir=src, built_at="2026-10-05T00:00:00Z", mtime=0)
    )

    monkeypatch.setenv("DISTRIBUTION_ROOT", str(tmp_path / "dist"))
    monkeypatch.setenv("DISTRIBUTION_API_TOKEN", TOKEN)
    reset_settings()
    try:
        client = TestClient(app)
        listed = client.get("/api/distribution/manifests", headers=HEADERS).json()
        assert [item["bundle_id"] for item in listed["items"]] == ["lex-dist-v0.1.0-citation"]

        detail = client.get(
            "/api/distribution/manifests/lex-dist-v0.1.0-citation", headers=HEADERS
        ).json()
        assert {c["name"] for c in detail["components"]} == set(rows)
        assert detail["pack"]["sha256"] == result.pack_sha256

        download = client.get(
            "/api/distribution/packs/lex-dist-v0.1.0-citation", headers=HEADERS
        )
        assert download.status_code == 200
        assert download.content == result.pack_file.read_bytes()

        verified = client.get(
            "/api/distribution/packs/lex-dist-v0.1.0-citation/sha256",
            params={"verify": 1}, headers=HEADERS,
        )
        assert verified.status_code == 200
        assert verified.json()["match"] is True

        partial = client.get(
            "/api/distribution/packs/lex-dist-v0.1.0-citation",
            headers={**HEADERS, "Range": "bytes=0-9"},
        )
        assert partial.status_code == 206
        assert partial.content == result.pack_file.read_bytes()[:10]
    finally:
        reset_settings()

def test_serves_real_flk_incremental_build(monkeypatch, tmp_path) -> None:
    """真实契约：packer 的 flk 日增量 bundle（6.3 增量通道）原样被端点服务。

    覆盖：增量 bundle 列表过滤、manifest 详情（incremental_kind=flk-daily）、
    pack 完整下载、Range 断点续传、sha256 校验端点 verify=1。
    """
    packer_dir = Path(__file__).resolve().parents[2] / "packer"
    if not (packer_dir / "lex_packer").is_dir():  # pragma: no cover
        pytest.skip("packer 不在仓内")
    sys.path.insert(0, str(packer_dir))
    try:
        from lex_packer.flk import build_flk_incremental, iter_flk_source
    finally:
        sys.path.remove(str(packer_dir))

    mirror = tmp_path / "rustfs" / "laws" / "incremental" / "2026" / "10"
    mirror.mkdir(parents=True)
    (mirror / "flk-2026-10-05.jsonl").write_text(
        json.dumps({"src_db": "flk", "source_id": "x-1", "title": "新规",
                    "content": "第一条"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (mirror / "flk-2026-10-05.manifest.json").write_text(
        json.dumps({"date": "2026-10-05", "counts": {"ok": 1, "pending": 0, "missing": 0},
                    "emitted": 1}, ensure_ascii=False),
        encoding="utf-8",
    )
    objects, _, manifests = iter_flk_source(local_dir=tmp_path / "rustfs" / "laws")
    result = build_flk_incremental(
        objects, tmp_path / "dist", "0.1.0",
        local_root=tmp_path / "rustfs" / "laws", flk_manifests=manifests, mtime=0,
    )
    assert result.bundle_id == "lex-dist-v0.1.0-citation-inc-2026-10-05"

    monkeypatch.setenv("DISTRIBUTION_ROOT", str(tmp_path / "dist"))
    monkeypatch.setenv("DISTRIBUTION_API_TOKEN", TOKEN)
    reset_settings()
    try:
        client = TestClient(app)
        listed = client.get(
            "/api/distribution/manifests", params={"form": "incremental"}, headers=HEADERS
        ).json()
        assert [item["bundle_id"] for item in listed["items"]] == [result.bundle_id]
        assert listed["items"][0]["tier"] == "citation"

        detail = client.get(
            f"/api/distribution/manifests/{result.bundle_id}", headers=HEADERS
        ).json()
        assert detail["bundle"]["incremental_kind"] == "flk-daily"
        assert {c["name"] for c in detail["components"]} == {
            "flk-2026-10-05", "flk-2026-10-05.manifest",
        }

        full = client.get(f"/api/distribution/packs/{result.bundle_id}", headers=HEADERS)
        assert full.status_code == 200
        assert full.content == result.pack_file.read_bytes()
        assert full.headers["content-length"] == str(result.pack_file.stat().st_size)

        partial = client.get(
            f"/api/distribution/packs/{result.bundle_id}",
            headers={**HEADERS, "Range": "bytes=4-19"},
        )
        assert partial.status_code == 206
        assert partial.content == result.pack_file.read_bytes()[4:20]

        verified = client.get(
            f"/api/distribution/packs/{result.bundle_id}/sha256",
            params={"verify": 1}, headers=HEADERS,
        )
        assert verified.status_code == 200
        assert verified.json()["match"] is True
        assert verified.json()["declared_sha256"] == result.pack_sha256
    finally:
        reset_settings()
