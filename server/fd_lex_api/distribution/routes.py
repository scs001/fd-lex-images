"""分发端点路由（/api/distribution）。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..config import get_settings
from .deps import require_distribution_token
from .hashing import sha256_file
from .ranges import ByteRange, iter_file, parse_range
from .store import DIGEST_SIDECAR, PACK_FILENAME, PackNotFound, PackStore, PackUnavailable

router = APIRouter(
    prefix="/api/distribution",
    tags=["distribution"],
    dependencies=[Depends(require_distribution_token)],
)

PACK_MEDIA_TYPE = "application/octet-stream"
CLIENT_CREDENTIALS_NOTE = (
    "v1 凭据=配置化分发 token（fail-closed）；客户级凭据（wgk-）接 Logto 后启用（后续项）"
)


def _store() -> PackStore:
    return PackStore()


def _get_entry(bundle_id: str):
    try:
        return _store().get(bundle_id)
    except PackNotFound:
        raise HTTPException(status_code=404, detail=f"bundle not found: {bundle_id}") from None
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid bundle: {exc}") from exc


# ---------------------------------------------------------------------------
# manifest 列表 / 详情
# ---------------------------------------------------------------------------


@router.get("/manifests")
def list_manifests(
    tier: str | None = Query(default=None),
    form: str | None = Query(default=None),
) -> dict[str, Any]:
    """bundle 清单（新→旧按 built_at 排序），可按数据档/形态过滤。"""
    if tier and tier not in ("citation", "corpus", "judgment"):
        raise HTTPException(status_code=422, detail="tier must be citation|corpus|judgment")
    if form and form not in ("full", "incremental"):
        raise HTTPException(status_code=422, detail="form must be full|incremental")
    entries = _store().list_entries(tier=tier, form=form)
    entries.sort(key=lambda item: (str(item.bundle.get("built_at") or ""), item.bundle_id),
                 reverse=True)
    return {
        "count": len(entries),
        "auth": {"scheme": "bearer", "note": CLIENT_CREDENTIALS_NOTE},
        "items": [entry.summary() for entry in entries],
    }


@router.get("/manifests/{bundle_id}")
def get_manifest(bundle_id: str) -> dict[str, Any]:
    """manifest 详情：全量 manifest + pack 制品摘要 + 下载/校验 URL。"""
    entry = _get_entry(bundle_id)
    return {
        **entry.manifest,
        "pack": {
            "file": entry.pack_path.name,
            "bytes": entry.pack_bytes,
            "sha256": entry.declared_sha256,
            "available": entry.pack_bytes is not None and entry.declared_sha256 is not None,
            "download_url": f"/api/distribution/packs/{entry.bundle_id}",
            "sha256_url": f"/api/distribution/packs/{entry.bundle_id}/sha256",
        },
        "auth": {"scheme": "bearer", "note": CLIENT_CREDENTIALS_NOTE},
    }


# ---------------------------------------------------------------------------
# 包下载（Range 断点续传）/ 校验端点
# ---------------------------------------------------------------------------


@router.get("/packs/{bundle_id}/sha256")
def pack_sha256(bundle_id: str, verify: int = Query(default=0, ge=0, le=1)) -> dict[str, Any]:
    """每包 sha256 校验端点。

    ``verify=1`` 时重算 pack.tar 摘要并与声明的 sidecar 摘要比对；不一致返回 409
    （服务端拒绝给坏包背书——客户端据此不应用该包）。
    """
    entry = _get_entry(bundle_id)
    if entry.pack_bytes is None:
        raise HTTPException(
            status_code=409,
            detail=f"{bundle_id} 无可用 pack 制品 {PACK_FILENAME}（构建未完成或制品缺失）",
        )
    if not entry.declared_sha256:
        raise HTTPException(
            status_code=409,
            detail=f"{bundle_id} 缺 {DIGEST_SIDECAR}（无法提供完整性校验）",
        )
    payload: dict[str, Any] = {
        "bundle_id": entry.bundle_id,
        "file": entry.pack_path.name,
        "bytes": entry.pack_bytes,
        "declared_sha256": entry.declared_sha256,
        "source": "pack.tar.sha256",
        "components": [
            {"name": c.get("name"), "sha256": c.get("sha256"), "bytes": c.get("bytes")}
            for c in entry.components
        ],
        "note": "客户端下载后应重算 sha256 与 declared_sha256 比对；不一致即不应用（坏包不应用）",
    }
    if verify:
        computed = sha256_file(entry.pack_path)
        payload["computed_sha256"] = computed
        payload["match"] = computed == entry.declared_sha256
        if not payload["match"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "pack digest mismatch",
                    "bundle_id": entry.bundle_id,
                    "declared_sha256": entry.declared_sha256,
                    "computed_sha256": computed,
                    "note": "检测到坏包，拒绝背书；客户端不得应用",
                },
            )
    return payload


def _etag_for(entry) -> str:
    return f'"{entry.declared_sha256}"' if entry.declared_sha256 else f'"{entry.bundle_id}"'


@router.head("/packs/{bundle_id}")
def head_pack(bundle_id: str) -> StreamingResponse:
    """HEAD：断点续传前探测 Accept-Ranges/Content-Length/ETag（不发 body）。"""
    return _pack_response(bundle_id, request=None, head=True)


@router.get("/packs/{bundle_id}")
def download_pack(bundle_id: str, request: Request) -> StreamingResponse:
    """pack 流式下载；支持 Range 断点续传与 If-Range/ETag。"""
    return _pack_response(bundle_id, request=request, head=False)


def _pack_response(bundle_id: str, request: Request | None, *, head: bool) -> StreamingResponse:
    try:
        entry = _store().require_pack(bundle_id)
    except PackNotFound:
        raise HTTPException(status_code=404, detail=f"bundle not found: {bundle_id}") from None
    except PackUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid bundle: {exc}") from exc
    assert entry.pack_bytes is not None  # require_pack 已保证
    total = entry.pack_bytes
    etag = _etag_for(entry)

    range_header = request.headers.get("range") if request else None
    if_range = request.headers.get("if-range") if request else None
    parsed = parse_range(range_header, total)
    if parsed.unsatisfiable:
        raise HTTPException(
            status_code=416,
            detail="requested range not satisfiable",
            headers={"Content-Range": f"bytes */{total}", "Accept-Ranges": "bytes"},
        )
    byte_range: ByteRange | None = parsed.byte_range
    # If-Range：带 ETag 不匹配则忽略 Range（整包 200）
    if byte_range is not None and if_range and if_range.strip() not in (etag, entry.declared_sha256):
        byte_range = None

    headers = {
        "Accept-Ranges": "bytes",
        "ETag": etag,
        "Content-Disposition": f'attachment; filename="{entry.pack_path.name}"',
        "X-Lex-Bundle-Id": entry.bundle_id,
        "X-Lex-Bundle-Sha256": entry.declared_sha256 or "",
    }
    if byte_range is None:
        headers["Content-Length"] = str(total)
        if head:
            return StreamingResponse(iter(()), media_type=PACK_MEDIA_TYPE,
                                     headers=headers, status_code=200)
        return StreamingResponse(
            iter_file(entry.pack_path), media_type=PACK_MEDIA_TYPE,
            headers=headers, status_code=200,
        )

    headers["Content-Length"] = str(byte_range.length)
    headers["Content-Range"] = byte_range.content_range()
    if head:
        return StreamingResponse(iter(()), media_type=PACK_MEDIA_TYPE,
                                 headers=headers, status_code=206)
    return StreamingResponse(
        iter_file(entry.pack_path, byte_range.start, byte_range.end),
        media_type=PACK_MEDIA_TYPE,
        headers=headers,
        status_code=206,
    )


# ---------------------------------------------------------------------------
# 双宿主能力目录
# ---------------------------------------------------------------------------


@router.get("/catalog")
def catalog() -> dict[str, Any]:
    """能力目录 + 如实标注的双宿主差异（未标注差异 = 构建器已拒绝，见 packer guard）。"""
    entries = _store().list_entries()
    latest = entries[-1] if entries else None
    manifest = latest.manifest if latest else {}
    return {
        "schema": "lex.distribution.capability-catalog/v1",
        "source_bundle": latest.bundle_id if latest else None,
        "bundles": [entry.summary() for entry in entries],
        "capabilities": manifest.get("capability_catalog", {}),
        "host_deltas": manifest.get("host_deltas", []),
        "note": "两宿主差异仅限 host_deltas 标注项；未标注差异在构建器被拒绝（双宿主能力一致）",
    }