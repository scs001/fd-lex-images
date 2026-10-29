"""签署服务商 adapter 边界（D1/D2/D4）：编排底座与厂商之间的唯一接口面。

底座只经本模块与厂商往来。跨出客户侧的仅限**文件哈希**、签署人身份与
意愿记录、签名值与时间戳——合同全文 MUST NOT 出现在任何 adapter payload 中
（spec「合同全文不出客户侧」；D2 选型硬筛子也按此执行）。

``ESIGN_PROVIDER`` 取值：

- 未配置（空）→ ``ProviderNotConfigured``：发起返回 503 并如实报「签署腿未配置」，
  任务留在 draft，MUST NOT 静默降级为无证明力的假签（spec 第 7 条）。
- ``stub`` → 进程内确定性假件，仅供开发/测试；其出证无司法效力。
- 其它值 → 暂不支持（厂商 adapter 随选型 spike 接入，change tasks 组 1/3.2）。
"""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timezone
from typing import Any

from ..config import get_settings


class AdapterError(Exception):
    """adapter 层错误（含厂商侧拒签）；routes 折算 HTTP 状态。"""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class ProviderNotConfigured(AdapterError):
    def __init__(self) -> None:
        super().__init__(
            503,
            "签署腿未配置：请配置 ESIGN_PROVIDER（持牌服务商 adapter）；"
            "合同与签署任务可保存为草稿，但无法对外发起签署",
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


class StubSignProvider:
    """进程内确定性假件（ESIGN_PROVIDER=stub，仅开发/测试）。

    记录厂商侧收到的全部 payload（测试据此断言「全文不出侧」——任何
    envelope 数据不得含合同字节），并校验实名/签名串格式。
    """

    name = "stub"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._envelopes: dict[str, dict[str, Any]] = {}
        self._signatures: dict[str, dict[str, Any]] = {}

    # --- 厂商侧收到的数据（测试钩子：断言不含全文） --------------------------
    @property
    def received_envelopes(self) -> dict[str, dict[str, Any]]:
        return dict(self._envelopes)

    def create_envelope(
        self,
        *,
        task_id: str,
        title: str,
        category: str,
        anchor_sha256: str,
        signers: list[dict[str, Any]],
    ) -> str:
        payload = {
            "task_id": task_id,
            "title": title,
            "category": category,
            "anchor_sha256": anchor_sha256,
            "signers": [
                {"seq": s["seq"], "name": s["name"], "role_label": s.get("role_label")}
                for s in signers
            ],
        }
        ref = f"stub-env-{task_id}"
        with self._lock:
            self._envelopes[ref] = payload
        return ref

    def verify_identity(
        self,
        *,
        envelope_ref: str,
        signer: dict[str, Any],
        claimed_name: str,
        credential: dict[str, Any],
    ) -> dict[str, Any]:
        """实名认证（stub：姓名与登记签署人精确一致；真实厂商走三要素/人脸/微信支付实名）。"""
        if not credential.get("serial") or not credential.get("method"):
            raise AdapterError(
                400, "实名材料不足：需要 method 与凭证号（真实通道为三要素/人脸核身/微信支付实名）"
            )
        if claimed_name.strip() != str(signer.get("name", "")).strip():
            raise AdapterError(
                403, "实名比对不符：签署仅能由被指定的本人完成"
            )
        record = {
            "method": str(credential["method"]),
            "serial_hash": hashlib.sha256(str(credential["serial"]).encode()).hexdigest()[:16],
            "matched_name": claimed_name.strip(),
            "verified_at": _now().isoformat(),
        }
        return record

    def sign(
        self,
        *,
        envelope_ref: str,
        signer: dict[str, Any],
        anchor_sha256: str,
        intent_method: str,
    ) -> dict[str, Any]:
        """落签（stub 出确定性签名串；真实厂商侧私钥在签名人控制面内运算）。"""
        sig = f"STUB-SIG:{anchor_sha256[:16]}:{signer['seq']}:{signer['name']}"
        rec = {
            "envelope_ref": envelope_ref,
            "seq": signer["seq"],
            "name": signer["name"],
            "signature_value": sig,
            "intent_method": intent_method,
            "signed_at": _now().isoformat(),
        }
        with self._lock:
            self._signatures[f"{envelope_ref}:{signer['seq']}"] = rec
        return rec

    def fetch_report(self, envelope_ref: str) -> dict[str, Any]:
        env = self._envelopes.get(envelope_ref)
        if env is None:
            raise AdapterError(404, "服务商侧无该签署任务记录")
        sigs = [
            rec
            for key, rec in self._signatures.items()
            if key.startswith(f"{envelope_ref}:")
        ]
        return {
            "provider": self.name,
            "envelope": env,
            "signatures": sorted(sigs, key=lambda r: r["seq"]),
            "generated_at": _now().isoformat(),
        }

    def verify_signature(self, anchor_sha256: str, signature_value: str) -> bool:
        if not signature_value.startswith("STUB-SIG:"):
            return False
        try:
            _, sha16, _seq = signature_value.split(":", 2)
        except ValueError:
            return False
        return anchor_sha256.startswith(sha16)


_STUB = StubSignProvider()


def get_adapter() -> StubSignProvider:
    provider = (get_settings().esign_provider or "").strip().lower()
    if not provider:
        raise ProviderNotConfigured()
    if provider == "stub":
        return _STUB
    raise AdapterError(
        503,
        f"未支持签署服务商 {provider!r}：厂商 adapter 随选型 spike 接入"
        "（change lex-contract-esignature tasks 组 1/3.2）",
    )


__all__ = [
    "AdapterError",
    "ProviderNotConfigured",
    "StubSignProvider",
    "get_adapter",
]
