"""签署编排底座（spec 第 1/2/3/4/6/8 条的行为真源；routes 只做参数与状态码折算）。

纪律：

- **签哈希不签全文**：给 adapter 的 create_envelope payload 仅哈希与元数据，
  合同字节只落客户侧文件仓（store.py）。
- **不代签**：「完成签署」只存在于签署人会话路由（routes 的 signer_router），
  且 MUST 先过实名（adapter.verify_identity）后过意愿（sign）；本模块不存在
  以 ConsoleUser/internal token 身份落签的任何入口。
- **fail-closed**：签署腿未配置 → ProviderNotConfigured 上抛（503），任务留草稿；
  闸门阻断 → 不建 envelope、不产生计量。
"""

from __future__ import annotations

import json
import secrets
import zipfile
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..metering.db import to_utc
from ..metering.models import (
    TRACK_CUSTOMER,
    TRACK_PLATFORM,
    UNIT_SIGNING,
    MeteringRecord,
)
from . import adapter as adapter_mod
from . import gate, store
from .models import (
    SIGNER_PENDING,
    SIGNER_SIGNED,
    TASK_COMPLETED,
    TASK_DRAFT,
    TASK_IN_PROGRESS,
    TASK_PENDING,
    TASK_REVOKED,
    EsignDocument,
    EsignEvent,
    EsignSigner,
    EsignTask,
    new_id,
    utcnow,
)


class EsignError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _hash_token(token: str) -> str:
    return store.sha256_hex(token.encode("utf-8"))


def _event(
    db: Session, task_id: str, *, actor: str, action: str,
    signer_id: str | None = None, detail: dict[str, Any] | None = None,
) -> EsignEvent:
    ev = EsignEvent(
        task_id=task_id,
        signer_id=signer_id,
        actor=actor,
        action=action,
        detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
    )
    db.add(ev)
    return ev


# ---------------------------------------------------------------- 任务面 ----

def create_task(
    db: Session, *, customer_identity: str, customer_principal: str | None,
    title: str, category: str, file_name: str, file_bytes: bytes,
    signers: list[dict[str, Any]],
) -> EsignTask:
    if not title.strip():
        raise EsignError(400, "title 不能为空")
    if category not in gate.CATEGORIES:
        raise EsignError(400, f"category 需在 {gate.CATEGORIES} 内")
    if not signers:
        raise EsignError(400, "至少一名签署人")
    if not file_bytes:
        raise EsignError(400, "合同文件为空")
    for i, s in enumerate(signers, start=1):
        if not str(s.get("name", "")).strip():
            raise EsignError(400, f"第{i}名签署人缺 name")
        s.setdefault("seq", i)

    sha, size = store.store_document(file_bytes, file_name)
    if db.get(EsignDocument, sha) is None:
        db.add(EsignDocument(sha256=sha, file_name=file_name, size=size))
    task = EsignTask(
        id=new_id(),
        customer_identity=customer_identity,
        customer_principal=customer_principal,
        title=title.strip(),
        category=category,
        status=TASK_DRAFT,
        anchor_sha256=sha,
        file_name=file_name,
        file_size=size,
    )
    db.add(task)
    db.flush()
    for s in signers:
        db.add(
            EsignSigner(
                task_id=task.id,
                seq=int(s["seq"]),
                name=str(s["name"]).strip(),
                role_label=(str(s["role_label"]).strip() if s.get("role_label") else None),
                status=SIGNER_PENDING,
            )
        )
    _event(db, task.id, actor=customer_identity, action="task_created",
           detail={"sha256": sha, "signers": len(signers), "category": category})
    return task


def get_task(db: Session, task_id: str, customer_identity: str) -> EsignTask:
    task = db.get(EsignTask, task_id)
    if task is None or task.customer_identity != customer_identity:
        raise EsignError(404, "任务不存在")
    return task


def task_detail(db: Session, task: EsignTask) -> dict[str, Any]:
    signers = db.scalars(
        select(EsignSigner).where(EsignSigner.task_id == task.id).order_by(EsignSigner.seq)
    ).all()
    return {
        **task.as_dict(),
        "signers": [
            {
                "seq": s.seq, "name": s.name, "role_label": s.role_label,
                "status": s.status, "flow_state": s.flow_state(),
                "realname_verified_at": s.realname_verified_at.isoformat() if s.realname_verified_at else None,
                "signed_at": s.signed_at.isoformat() if s.signed_at else None,
            }
            for s in signers
        ],
    }


def replace_file(
    db: Session, task: EsignTask, *, file_name: str, file_bytes: bytes
) -> EsignTask:
    """draft 可换版；pending 起锚定不可原地替换（spec 第 1 条）。"""
    if task.status != TASK_DRAFT:
        raise EsignError(
            409,
            "签署已发起，锚定文件不可原地替换；须作废旧任务并以新版本文件重新发起",
        )
    sha, size = store.store_document(file_bytes, file_name)
    if db.get(EsignDocument, sha) is None:
        db.add(EsignDocument(sha256=sha, file_name=file_name, size=size))
    old_sha = task.anchor_sha256
    task.anchor_sha256 = sha
    task.file_name = file_name
    task.file_size = size
    task.updated_at = utcnow()
    _event(db, task.id, actor=task.customer_identity, action="file_replaced",
           detail={"from": old_sha, "to": sha})
    return task


def revoke(db: Session, task: EsignTask) -> EsignTask:
    if task.status == TASK_REVOKED:
        return task
    if task.status == TASK_COMPLETED:
        raise EsignError(409, "签署已全部完成，任务不可撤销")
    task.status = TASK_REVOKED
    task.revoked_at = utcnow()
    task.updated_at = utcnow()
    _event(db, task.id, actor=task.customer_identity, action="task_revoked")
    return task


def initiate(
    db: Session, task: EsignTask, *, acknowledged: bool = False
) -> dict[str, Any]:
    """闸门 → 签署腿 → envelope → 签署链接（token 明文只回显一次）。"""
    if task.status != TASK_DRAFT:
        raise EsignError(409, f"任务状态 {task.status} 不可发起")
    verdict = gate.evaluate(task.category, task.title)
    if verdict["verdict"] == "block":
        _event(db, task.id, actor=task.customer_identity, action="gate_blocked",
               detail={k: v for k, v in verdict.items() if k != "legal_basis"})
        db.commit()  # 闸门留痕必须先落库：请求以异常收尾时 get_db 会回滚
        raise EsignError(422, json.dumps(verdict, ensure_ascii=False))
    if verdict["verdict"] == "notice" and not acknowledged:
        _event(db, task.id, actor=task.customer_identity, action="gate_notice_shown",
               detail={"category": task.category})
        db.commit()  # 同上：提示展示动作入账留痕（spec 场景）
        raise EsignError(
            400,
            json.dumps({"require_ack": True, **verdict}, ensure_ascii=False),
        )
    if verdict["verdict"] == "notice" and acknowledged:
        _event(db, task.id, actor=task.customer_identity, action="gate_notice_acknowledged",
               detail={"category": task.category})

    provider = adapter_mod.get_adapter()  # 未配置即 ProviderNotConfigured（fail-closed）
    signers = db.scalars(
        select(EsignSigner).where(EsignSigner.task_id == task.id).order_by(EsignSigner.seq)
    ).all()
    envelope_ref = provider.create_envelope(
        task_id=task.id,
        title=task.title,
        category=task.category,
        anchor_sha256=task.anchor_sha256,
        signers=[
            {"seq": s.seq, "name": s.name, "role_label": s.role_label} for s in signers
        ],
    )
    task.status = TASK_PENDING
    task.adapter_name = provider.name
    task.envelope_ref = envelope_ref
    task.initiated_at = utcnow()
    task.updated_at = utcnow()
    _event(db, task.id, actor=task.customer_identity, action="envelope_created",
           detail={"adapter": provider.name, "envelope_ref": envelope_ref})

    base = get_settings().console_origin.rstrip("/")
    links = []
    for s in signers:
        token = secrets.token_urlsafe(32)
        s.link_token_hash = _hash_token(token)
        links.append(
            {"seq": s.seq, "signer_id": s.id, "name": s.name,
             "url": f"{base}/api/esignature/p/{token}"}
        )
        _event(db, task.id, signer_id=s.id, actor=task.customer_identity,
               action="link_issued")
    return {"task": task_detail(db, task), "links": links}


def rotate_links(db: Session, task: EsignTask) -> list[dict[str, Any]]:
    if task.status not in (TASK_PENDING, TASK_IN_PROGRESS):
        raise EsignError(409, f"任务状态 {task.status} 不可换发链接")
    signers = db.scalars(
        select(EsignSigner).where(EsignSigner.task_id == task.id).order_by(EsignSigner.seq)
    ).all()
    base = get_settings().console_origin.rstrip("/")
    links = []
    for s in signers:
        token = secrets.token_urlsafe(32)
        s.link_token_hash = _hash_token(token)
        s.session_token_hash = None
        s.session_expires_at = None
        links.append(
            {"seq": s.seq, "signer_id": s.id, "name": s.name,
             "url": f"{base}/api/esignature/p/{token}"}
        )
        _event(db, task.id, signer_id=s.id, actor=task.customer_identity,
               action="link_issued", detail={"rotated": True})
    return links


# ------------------------------------------------------------- 签署人会话 ----

def resolve_signer(db: Session, link_token: str) -> tuple[EsignTask, EsignSigner]:
    signer = db.scalar(
        select(EsignSigner).where(EsignSigner.link_token_hash == _hash_token(link_token))
    )
    if signer is None:
        raise EsignError(404, "签署链接无效")
    task = db.get(EsignTask, signer.task_id)
    if task is None:  # pragma: no cover - 数据一致性兜底
        raise EsignError(404, "签署链接无效")
    if task.status == TASK_REVOKED:
        raise EsignError(410, "签署任务已撤销，链接失效")
    if task.status == TASK_DRAFT:
        raise EsignError(409, "签署任务尚未发起")
    return task, signer


def _require_session(db: Session, task: EsignTask, signer: EsignSigner, session_token: str) -> None:
    if not session_token or signer.session_token_hash != _hash_token(session_token):
        raise EsignError(401, "签署会话无效或已过期，请重新打开签署链接")
    if signer.session_expires_at is None or to_utc(signer.session_expires_at) < utcnow():
        raise EsignError(401, "签署会话已过期，请重新打开签署链接")


def open_link(db: Session, link_token: str) -> dict[str, Any]:
    task, signer = resolve_signer(db, link_token)
    if signer.status == SIGNER_SIGNED:
        return {"already_signed": True, "task": task_detail(db, task)}
    session_token = secrets.token_urlsafe(32)
    signer.session_token_hash = _hash_token(session_token)
    signer.session_expires_at = utcnow() + timedelta(
        seconds=get_settings().esign_signer_session_ttl_seconds
    )
    _event(db, task.id, signer_id=signer.id, actor=signer.name, action="link_opened")
    return {
        "already_signed": False,
        "session_token": session_token,
        "task_title": task.title,
        "signer": {"seq": signer.seq, "name": signer.name, "flow_state": signer.flow_state()},
    }


def preview_document(db: Session, link_token: str, session_token: str) -> bytes:
    task, signer = resolve_signer(db, link_token)
    _require_session(db, task, signer, session_token)
    data = store.read_document(task.anchor_sha256)
    if data is None:  # pragma: no cover - 文件仓丢失
        raise EsignError(500, "合同文件缺失，请联系发起方")
    if not db.scalar(
        select(EsignEvent).where(
            EsignEvent.task_id == task.id,
            EsignEvent.signer_id == signer.id,
            EsignEvent.action == "read_receipt",
        )
    ):
        _event(db, task.id, signer_id=signer.id, actor=signer.name, action="read_receipt")
    return data


def verify_identity(
    db: Session, link_token: str, session_token: str, *, name: str, credential: dict[str, Any]
) -> dict[str, Any]:
    task, signer = resolve_signer(db, link_token)
    _require_session(db, task, signer, session_token)
    if signer.status == SIGNER_SIGNED:
        raise EsignError(409, "该签署人已签署，链接不可复用")
    provider = adapter_mod.get_adapter()
    record = provider.verify_identity(
        envelope_ref=str(task.envelope_ref),
        signer={"seq": signer.seq, "name": signer.name, "role_label": signer.role_label},
        claimed_name=name,
        credential=credential,
    )
    signer.realname_verified_at = utcnow()
    signer.realname_record_json = json.dumps(record, ensure_ascii=False)
    _event(db, task.id, signer_id=signer.id, actor=signer.name, action="realname_verified",
           detail=record)
    return record


def sign(
    db: Session, link_token: str, session_token: str, *, intent_method: str
) -> dict[str, Any]:
    task, signer = resolve_signer(db, link_token)
    _require_session(db, task, signer, session_token)
    if signer.realname_verified_at is None:
        raise EsignError(409, "请先完成实名认证再落签")
    if signer.status == SIGNER_SIGNED:
        raise EsignError(409, "该签署人已签署，链接不可复用")
    if not intent_method.strip():
        raise EsignError(400, "缺少意愿认证方式")
    provider = adapter_mod.get_adapter()
    result = provider.sign(
        envelope_ref=str(task.envelope_ref),
        signer={"seq": signer.seq, "name": signer.name},
        anchor_sha256=task.anchor_sha256,
        intent_method=intent_method.strip(),
    )
    signer.status = SIGNER_SIGNED
    signer.signed_at = utcnow()
    signer.intent_confirmed_at = signer.signed_at
    signer.signature_value = result["signature_value"]
    _event(db, task.id, signer_id=signer.id, actor=signer.name, action="signed",
           detail={"intent_method": intent_method, "signature_ref": result["signature_value"][-16:]})
    _meter_signing(db, task, signer)

    if task.status == TASK_PENDING:
        task.status = TASK_IN_PROGRESS
    db.flush()  # autoflush=False：本会话刚写的 signed 状态必须对后续查询可见
    pending = db.scalars(
        select(EsignSigner).where(
            EsignSigner.task_id == task.id, EsignSigner.status != SIGNER_SIGNED
        )
    ).all()
    if not pending:
        task.status = TASK_COMPLETED
        task.completed_at = utcnow()
        _build_evidence_package(db, task, provider)
        _event(db, task.id, actor="system", action="task_completed")
    task.updated_at = utcnow()
    return {"task_status": task.status, "signed_at": signer.signed_at.isoformat()}


# ------------------------------------------------------- 出证 / 验证 / 计量 ----

def _build_evidence_package(db: Session, task: EsignTask, provider) -> None:
    """出证包：识律 manifest（聚合）+ 事件流 + 厂商报告原件（双轨，D6）。"""
    manifest = {
        "task": task.as_dict(),
        "anchor_sha256": task.anchor_sha256,
        "signers": [
            {
                "seq": s.seq, "name": s.name, "role_label": s.role_label,
                "signed_at": s.signed_at.isoformat() if s.signed_at else None,
                "realname": _load(s.realname_record_json),
                "signature_value": s.signature_value,
            }
            for s in db.scalars(
                select(EsignSigner)
                .where(EsignSigner.task_id == task.id)
                .order_by(EsignSigner.seq)
            ).all()
        ],
    }
    events = db.scalars(
        select(EsignEvent).where(EsignEvent.task_id == task.id).order_by(EsignEvent.id)
    ).all()
    report_raw = provider.fetch_report(str(task.envelope_ref))
    manifest["report_sha256"] = store.sha256_hex(
        json.dumps(report_raw, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    import io

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr(
            "events.ndjson",
            "\n".join(json.dumps(e.as_dict(), ensure_ascii=False) for e in events),
        )
        zf.writestr(
            "provider_report.json",
            json.dumps(report_raw, ensure_ascii=False, indent=2),
        )
    task.evidence_path = store.store_evidence_package(task.id, buf.getvalue())


def _load(raw: str | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def evidence_cards(db: Session, task: EsignTask) -> list[dict[str, Any]]:
    """出证包 → 证据卡结构（evidence-card-organizer 阶段 2 字段表）。"""
    cards: list[dict[str, Any]] = []
    n = 0
    for s in db.scalars(
        select(EsignSigner).where(EsignSigner.task_id == task.id).order_by(EsignSigner.seq)
    ).all():
        if s.status != SIGNER_SIGNED:
            continue
        n += 1
        realname = _load(s.realname_record_json) or {}
        cards.append(
            {
                "编号": f"SP{n:03d}",
                "来源文件": f"{task.file_name}（电子签署出证包 task={task.id}）",
                "原文摘要": (
                    f"签署记录：{s.name}（第{s.seq}顺位）实名认证方式"
                    f"={realname.get('method', '—')}，签署时间={s.signed_at.isoformat() if s.signed_at else '—'}，"
                    f"锚定哈希={task.anchor_sha256[:16]}…，签名串尾段={ (s.signature_value or '')[-16:] }"
                ),
                "发言者": "对方" if s.seq > 1 else "己方",
                "证明目的": "合同约定",
                "时间": s.signed_at.isoformat() if s.signed_at else None,
                "金额": None,
                "对应要件": None,
                "形式要件": f"电子签名记录（adapter={task.adapter_name}；原始报告见出证包 provider_report.json）",
                "置信度": "高",
            }
        )
    return cards


def verify_package(db: Session, task: EsignTask, file_bytes: bytes) -> dict[str, Any]:
    """对给定文件与任务出证包做完整性验证（spec「篡改文件验证失败」）。"""
    checks: list[dict[str, Any]] = []
    recomputed = store.sha256_hex(file_bytes)
    checks.append(
        {
            "name": "content_integrity",
            "passed": recomputed == task.anchor_sha256,
            "detail": f"重算哈希={recomputed[:16]}… 锚定哈希={task.anchor_sha256[:16]}…",
        }
    )
    if not task.evidence_path:
        checks.append({"name": "evidence_package", "passed": False, "detail": "任务未完成，无出证包"})
        return {"valid": False, "checks": checks}
    pkg = store.read_evidence_package(task.evidence_path)
    if pkg is None:
        checks.append({"name": "evidence_package", "passed": False, "detail": "出证包文件缺失"})
        return {"valid": False, "checks": checks}
    import io

    with zipfile.ZipFile(io.BytesIO(pkg)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        report_raw = json.loads(zf.read("provider_report.json"))
    checks.append(
        {
            "name": "package_anchor",
            "passed": manifest.get("anchor_sha256") == task.anchor_sha256,
            "detail": "出证包锚定与任务一致",
        }
    )
    provider = adapter_mod.get_adapter()
    sig_ok, sig_total = 0, 0
    for s in manifest.get("signers", []):
        if not s.get("signature_value"):
            continue
        sig_total += 1
        if provider.verify_signature(task.anchor_sha256, s["signature_value"]):
            sig_ok += 1
    checks.append(
        {
            "name": "signature_chain",
            "passed": sig_total > 0 and sig_ok == sig_total,
            "detail": f"{sig_ok}/{sig_total} 份签名验证通过；provider={report_raw.get('provider')}",
        }
    )
    valid = all(c["passed"] for c in checks)
    return {"valid": valid, "checks": checks}


def _meter_signing(db: Session, task: EsignTask, signer: EsignSigner) -> None:
    """单份签署完成入账（spec 第 8 条：未完成/撤销份数不入账——只在落签时写）。"""
    track = (
        TRACK_PLATFORM
        if task.customer_identity.lower() in get_settings().platform_identity_set()
        else TRACK_CUSTOMER
    )
    db.add(
        MeteringRecord(
            event_timestamp=utcnow(),
            request_id=f"esign:{task.id}:{signer.id}",
            caller=task.customer_identity,
            caller_principal=task.customer_principal,
            credential_track=track,
            server_name="lex-esignature",
            server_path="/api/esignature",
            tool_name="contract-signature",
            quantity=1,
            unit=UNIT_SIGNING,
            source="lex-internal",
        )
    )
    _event(db, task.id, signer_id=signer.id, actor="system", action="metered",
           detail={"unit": UNIT_SIGNING, "track": track})


__all__ = [
    "EsignError",
    "create_task",
    "evidence_cards",
    "get_task",
    "initiate",
    "open_link",
    "preview_document",
    "replace_file",
    "revoke",
    "rotate_links",
    "sign",
    "task_detail",
    "verify_identity",
    "verify_package",
]
