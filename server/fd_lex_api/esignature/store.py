"""内容寻址文件仓（客户侧）：sha256 即键，字节只落 ``ESIGN_FILE_STORE_DIR``。

spec「合同全文不出客户侧」的存储面：合同全文永远只在本地目录，
数据库里只有哈希与元数据；跨出客户侧到签署服务商的仅限哈希+身份记录+
签名值（见 adapter.py 的 payload 契约）。目录随私有化包落在客户机房。
"""

from __future__ import annotations

import hashlib
import os

from ..config import get_settings


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _root() -> str:
    root = get_settings().esign_file_store_dir
    os.makedirs(root, exist_ok=True)
    return root


def store_document(data: bytes, file_name: str) -> tuple[str, int]:
    """幂等入库：返回 (sha256, size)。同哈希重复写入不损坏既有内容。"""
    sha = sha256_hex(data)
    path = os.path.join(_root(), sha)
    if not os.path.exists(path):
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    return sha, len(data)


def read_document(sha: str) -> bytes | None:
    path = os.path.join(_root(), sha)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()


def store_evidence_package(task_id: str, payload: bytes) -> str:
    """出证包 zip 落盘（客户侧），返回路径。"""
    ev_dir = os.path.join(_root(), "evidence")
    os.makedirs(ev_dir, exist_ok=True)
    path = os.path.join(ev_dir, f"{task_id}.zip")
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(payload)
    os.replace(tmp, path)
    return path


def read_evidence_package(path: str) -> bytes | None:
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return fh.read()


__all__ = [
    "read_document",
    "read_evidence_package",
    "sha256_hex",
    "store_document",
    "store_evidence_package",
]
