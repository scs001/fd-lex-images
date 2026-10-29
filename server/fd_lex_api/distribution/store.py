"""pack 库：bundle 目录扫描、manifest 读取、路径安全与摘要。

目录约定（packer 产出，原样）：

    <DISTRIBUTION_ROOT>/lex-dist-v0.1.0-citation/
        manifest.json
        pack.tar
        pack.tar.sha256
        data/*.jsonl.gz

安全：bundle_id 严格白名单正则 + resolve 后必须落在 root 之内（防路径穿越）。
只读：本模块绝不写 pack 目录。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from ..config import get_settings

MANIFEST_SCHEMA = "lex.distribution.manifest/v1"
BUNDLE_ID_RE = re.compile(
    r"^lex-dist-v\d+\.\d+\.\d+-[a-z_]+(?:-inc-\d{4}-\d{2}-\d{2})?$"
)
PACK_FILENAME = "pack.tar"
DIGEST_SIDECAR = "pack.tar.sha256"


class PackNotFound(KeyError):
    """bundle 不存在（404）。"""


class PackUnavailable(RuntimeError):
    """bundle 存在但其 pack 制品不可用（缺文件/缺摘要）。"""


@dataclass
class PackEntry:
    """一个可分发 bundle。"""

    bundle_id: str
    dir: Path
    manifest: dict
    pack_path: Path
    declared_sha256: str | None
    pack_bytes: int | None

    @property
    def bundle(self) -> dict:
        return dict(self.manifest.get("bundle", {}))

    @property
    def components(self) -> list[dict]:
        return list(self.manifest.get("components", []))

    def summary(self) -> dict:
        bundle = self.bundle
        return {
            "bundle_id": self.bundle_id,
            "name": bundle.get("name"),
            "version": bundle.get("version"),
            "tier": bundle.get("tier"),
            "form": bundle.get("form"),
            "as_of": bundle.get("as_of"),
            "built_at": bundle.get("built_at"),
            "hosts": bundle.get("hosts", []),
            "component_count": len(self.components),
            "pack_bytes": self.pack_bytes,
            "pack_sha256": self.declared_sha256,
            "model_assets_included": bool(
                (self.manifest.get("model_assets") or {}).get("included")
            ),
            "missing_inputs": [
                item.get("component") for item in self.manifest.get("missing_inputs", [])
            ],
            "download_url": f"/api/distribution/packs/{self.bundle_id}",
            "sha256_url": f"/api/distribution/packs/{self.bundle_id}/sha256",
        }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_sidecar(path: Path) -> str | None:
    if not path.is_file():
        return None
    parts = path.read_text(encoding="utf-8").split()
    return parts[0] if parts else None


def safe_bundle_dir(root: Path, bundle_id: str) -> Path:
    """校验 bundle_id 并返回其目录；非法/越界抛 PackNotFound。"""
    if not BUNDLE_ID_RE.match(bundle_id or ""):
        raise PackNotFound(bundle_id)
    root_resolved = root.resolve()
    candidate = (root_resolved / bundle_id).resolve()
    if not candidate.is_relative_to(root_resolved):
        raise PackNotFound(bundle_id)
    return candidate


class PackStore:
    """pack 目录的只读视图（请求期构造，无缓存；目录变化即时可见）。"""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root if root is not None else get_settings().distribution_root)

    def list_entries(self, *, tier: str | None = None, form: str | None = None) -> list[PackEntry]:
        entries: list[PackEntry] = []
        if not self.root.is_dir():
            return entries
        for child in sorted(self.root.iterdir()):
            if not child.is_dir() or not BUNDLE_ID_RE.match(child.name):
                continue
            try:
                entry = self.get(child.name)
            except (PackNotFound, PackUnavailable, ValueError, json.JSONDecodeError):
                continue
            bundle = entry.bundle
            if tier and bundle.get("tier") != tier:
                continue
            if form and bundle.get("form") != form:
                continue
            entries.append(entry)
        return entries

    def get(self, bundle_id: str) -> PackEntry:
        directory = safe_bundle_dir(self.root, bundle_id)
        manifest_path = directory / "manifest.json"
        if not manifest_path.is_file():
            raise PackNotFound(bundle_id)
        manifest = _read_json(manifest_path)
        if manifest.get("schema") != MANIFEST_SCHEMA:
            raise ValueError(f"unsupported manifest schema: {manifest.get('schema')!r}")
        if str(manifest.get("bundle", {}).get("id")) != bundle_id:
            raise ValueError(
                f"manifest bundle.id={manifest.get('bundle', {}).get('id')!r}"
                f" 与目录名 {bundle_id!r} 不一致"
            )
        pack_path = directory / PACK_FILENAME
        return PackEntry(
            bundle_id=bundle_id,
            dir=directory,
            manifest=manifest,
            pack_path=pack_path,
            declared_sha256=_parse_sidecar(directory / DIGEST_SIDECAR),
            pack_bytes=(pack_path.stat().st_size if pack_path.is_file() else None),
        )

    def require_pack(self, bundle_id: str) -> PackEntry:
        """取可用于下载的 bundle；缺 pack 制品抛 PackUnavailable（409/404 语义）。"""
        entry = self.get(bundle_id)
        if entry.pack_bytes is None:
            raise PackUnavailable(f"{bundle_id} 无 {PACK_FILENAME}（构建未完成或制品缺失）")
        if not entry.declared_sha256:
            raise PackUnavailable(f"{bundle_id} 缺 {DIGEST_SIDECAR}（无法提供完整性校验）")
        return entry