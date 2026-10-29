"""电子签模块表（lex_esign_*，change lex-contract-esignature）。

四张表一个事实源：

- ``lex_esign_tasks``：签署任务。状态机 draft→pending→in_progress→completed，
  draft/pending/in_progress 均可→revoked。``anchor_sha256`` 锚定定稿文件——
  pending 起原地不可替换（换版=作废旧任务后重发起）；出证包路径落
  ``evidence_path``。
- ``lex_esign_signers``：签署人。H5 链接令牌**只存哈希**（明文仅在发起/换发
  响应中出现一次）；实名通过/意愿确认/落签三段时刻与记录独立入账；
  会话令牌同样只存哈希且带 TTL。
- ``lex_esign_events``：全量审计流（发起/闸门/阅读回执/实名/换发/撤销/计量
  入账……）；出证包与验证口径都以本表为准绳。
- ``lex_esign_documents``：内容寻址文档登记。sha256 即键，字节只存客户侧
  文件仓（esignature/store.py）——跨出客户侧到签署服务商的仅限哈希、
  身份记录与签名值（spec「合同全文不出客户侧」）。

与 console_* 表同库不同 Base；软引用不建 FK，迁移链互不牵扯。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: 任务状态机取值（routes/service 与迁移口径一致）
TASK_DRAFT = "draft"
TASK_PENDING = "pending"
TASK_IN_PROGRESS = "in_progress"
TASK_COMPLETED = "completed"
TASK_REVOKED = "revoked"
TASK_STATUSES = (TASK_DRAFT, TASK_PENDING, TASK_IN_PROGRESS, TASK_COMPLETED, TASK_REVOKED)

SIGNER_PENDING = "pending"
SIGNER_SIGNED = "signed"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class EsignBase(DeclarativeBase):
    """电子签面 ORM 基类（lex_esign_* 表）。"""


class EsignDocument(EsignBase):
    """内容寻址文档登记（字节只落客户侧文件仓，库内只存哈希与元数据）。"""

    __tablename__ = "lex_esign_documents"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )


class EsignTask(EsignBase):
    """签署任务（一份定稿合同 × 一组签署人 × 一台状态机）。"""

    __tablename__ = "lex_esign_tasks"
    __table_args__ = (Index("ix_esign_tasks_customer_time", "customer_identity", "created_at"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    customer_identity: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    customer_principal: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    #: 业务类别（labor|loan|nda|sale|service|other；闸门与计量提示按此走）
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=TASK_DRAFT)
    #: 锚定文件（sha256 → lex_esign_documents）
    anchor_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 签署腿（adapter 名与厂商侧任务引用；出证双轨保留用）
    adapter_name: Mapped[str | None] = mapped_column(String(64))
    envelope_ref: Mapped[str | None] = mapped_column(String(255))
    evidence_path: Mapped[str | None] = mapped_column(String(1000))
    initiated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "status": self.status,
            "anchor_sha256": self.anchor_sha256,
            "file_name": self.file_name,
            "file_size": self.file_size,
            "adapter_name": self.adapter_name,
            "envelope_ref": self.envelope_ref,
            "evidence_available": bool(self.evidence_path),
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "initiated_at": self.initiated_at.isoformat() if self.initiated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "revoked_at": self.revoked_at.isoformat() if self.revoked_at else None,
        }


class EsignSigner(EsignBase):
    """单个签署人：链接令牌（哈希）、H5 会话（哈希+TTL）、三段完成时刻。"""

    __tablename__ = "lex_esign_signers"
    __table_args__ = (
        UniqueConstraint("task_id", "seq", name="uq_esign_signer_task_seq"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role_label: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default=SIGNER_PENDING)
    #: H5 链接令牌哈希（明文只回显一次；换发即覆盖=旧链接立死）
    link_token_hash: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True
    )
    #: 当前会话令牌哈希与过期（打开链接后短窗口内完成实名/意愿/落签）
    session_token_hash: Mapped[str | None] = mapped_column(String(64))
    session_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    realname_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    realname_record_json: Mapped[str | None] = mapped_column(Text)
    intent_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    signature_value: Mapped[str | None] = mapped_column(Text)

    def flow_state(self) -> str:
        """签署人可观察的细状态（列表/出证口径用）。"""
        if self.status == SIGNER_SIGNED:
            return "signed"
        if self.realname_verified_at:
            return "verified"
        return "pending"


class EsignEvent(EsignBase):
    """签署审计流（出证包 events 即本表的逐条投影）。"""

    __tablename__ = "lex_esign_events"
    __table_args__ = (Index("ix_esign_events_task_time", "task_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    signer_id: Mapped[str | None] = mapped_column(String(32))
    #: 行为主体：客户身份 / 签署人姓名 / system
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    detail_json: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "signer_id": self.signer_id,
            "actor": self.actor,
            "action": self.action,
            "detail": _load_json(self.detail_json),
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


def _load_json(raw: str | None):
    if not raw:
        return None
    import json

    try:
        return json.loads(raw)
    except ValueError:
        return None


def ensure_esign_schema(engine=None) -> None:
    """幂等建 lex_esign_* 表（dev 便利；生产迁移链由 alembic 收敛）。"""
    if engine is None:
        from ..metering.db import get_engine

        engine = get_engine()
    EsignBase.metadata.create_all(engine)


__all__ = [
    "EsignBase",
    "EsignDocument",
    "EsignEvent",
    "EsignSigner",
    "EsignTask",
    "SIGNER_PENDING",
    "SIGNER_SIGNED",
    "TASK_COMPLETED",
    "TASK_DRAFT",
    "TASK_IN_PROGRESS",
    "TASK_PENDING",
    "TASK_REVOKED",
    "TASK_STATUSES",
    "ensure_esign_schema",
    "new_id",
    "utcnow",
]
