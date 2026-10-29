"""电子签路由：客户控制台面（/api/console/esignature）+ 签署人 H5 面（/api/esignature/s）。

两面鉴权彻底分离（spec「任何自动化入口不代签」）：

- 控制台面：Logto ID token（require_console_user）——只能建档/发起/撤销/换发/
  出证/验证，**没有任何落签入口**。
- 签署人面：仅认「链接 token + 短会话 token」，不读 Authorization 头；
  internal bearer、控制台 token 在此面一律不可达（无路径+无依赖）。
"""

from __future__ import annotations

import base64
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..console_api.auth import ConsoleUser, require_console_user
from ..metering.db import get_db
from . import adapter as adapter_mod
from . import service
from .models import EsignTask


def _decode_b64(raw: str) -> bytes:
    try:
        return base64.b64decode(raw.encode("ascii", "ignore"), validate=True)
    except Exception:
        raise HTTPException(400, "file_b64 不是合法 base64")


class SignerIn(BaseModel):
    name: str
    role_label: str | None = None


class TaskCreateIn(BaseModel):
    title: str
    category: str = "other"
    file_name: str
    file_b64: str
    signers: list[SignerIn] = Field(min_length=1)


class FileReplaceIn(BaseModel):
    file_name: str
    file_b64: str


class InitiateIn(BaseModel):
    acknowledged: bool = False


class RealnameIn(BaseModel):
    name: str
    credential: dict[str, Any]


class SignIn(BaseModel):
    intent_method: str


class VerifyIn(BaseModel):
    task_id: str
    file_b64: str


def _user_identity(user: ConsoleUser) -> str:
    return user.identity


console_router = APIRouter(
    prefix="/api/console/esignature",
    tags=["esignature-console"],
    dependencies=[Depends(require_console_user)],
)


def _db_task(db: Session, task_id: str, user: ConsoleUser) -> EsignTask:
    try:
        return service.get_task(db, task_id, _user_identity(user))
    except service.EsignError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@console_router.post("/tasks")
def create_task(body: TaskCreateIn, user: ConsoleUser = Depends(require_console_user), db: Session = Depends(get_db)):
    data = _decode_b64(body.file_b64)
    try:
        task = service.create_task(
            db,
            customer_identity=_user_identity(user),
            customer_principal=user.email or user.username,
            title=body.title,
            category=body.category,
            file_name=body.file_name,
            file_bytes=data,
            signers=[s.model_dump() for s in body.signers],
        )
    except service.EsignError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    return service.task_detail(db, task)


@console_router.get("/tasks")
def list_tasks(user: ConsoleUser = Depends(require_console_user), db: Session = Depends(get_db)):
    tasks = db.scalars(
        select(EsignTask)
        .where(EsignTask.customer_identity == _user_identity(user))
        .order_by(EsignTask.created_at.desc())
        .limit(200)
    ).all()
    return [t.as_dict() for t in tasks]


@console_router.get("/tasks/{task_id}")
def get_task(task_id: str, user: ConsoleUser = Depends(require_console_user), db: Session = Depends(get_db)):
    return service.task_detail(db, _db_task(db, task_id, user))


@console_router.post("/tasks/{task_id}/file")
def replace_file(task_id: str, body: FileReplaceIn, user: ConsoleUser = Depends(require_console_user), db: Session = Depends(get_db)):
    task = _db_task(db, task_id, user)
    try:
        task = service.replace_file(
            db, task, file_name=body.file_name, file_bytes=_decode_b64(body.file_b64)
        )
    except service.EsignError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    return service.task_detail(db, task)


@console_router.post("/tasks/{task_id}/initiate")
def initiate(task_id: str, body: InitiateIn, user: ConsoleUser = Depends(require_console_user), db: Session = Depends(get_db)):
    task = _db_task(db, task_id, user)
    try:
        return service.initiate(db, task, acknowledged=body.acknowledged)
    except service.EsignError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except adapter_mod.ProviderNotConfigured as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except adapter_mod.AdapterError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@console_router.post("/tasks/{task_id}/links")
def rotate_links(task_id: str, user: ConsoleUser = Depends(require_console_user), db: Session = Depends(get_db)):
    task = _db_task(db, task_id, user)
    try:
        return {"links": service.rotate_links(db, task)}
    except service.EsignError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@console_router.post("/tasks/{task_id}/revoke")
def revoke(task_id: str, user: ConsoleUser = Depends(require_console_user), db: Session = Depends(get_db)):
    task = _db_task(db, task_id, user)
    try:
        task = service.revoke(db, task)
    except service.EsignError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    return service.task_detail(db, task)


@console_router.get("/tasks/{task_id}/evidence")
def download_evidence(task_id: str, user: ConsoleUser = Depends(require_console_user), db: Session = Depends(get_db)):
    task = _db_task(db, task_id, user)
    from . import store

    payload = store.read_evidence_package(task.evidence_path or "")
    if not task.evidence_path or payload is None:
        raise HTTPException(409, "任务尚未全部完成，无出证包")
    return Response(
        content=payload,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="evidence-{task.id}.zip"'},
    )


@console_router.get("/tasks/{task_id}/evidence/cards")
def evidence_cards(task_id: str, user: ConsoleUser = Depends(require_console_user), db: Session = Depends(get_db)):
    task = _db_task(db, task_id, user)
    return {"cards": service.evidence_cards(db, task)}


@console_router.post("/verify")
def verify(body: VerifyIn, user: ConsoleUser = Depends(require_console_user), db: Session = Depends(get_db)):
    task = _db_task(db, body.task_id, user)
    try:
        return service.verify_package(db, task, _decode_b64(body.file_b64))
    except adapter_mod.AdapterError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


# ------------------------------------------------------ 签署人 H5 面 ----

signer_router = APIRouter(prefix="/api/esignature", tags=["esignature-signer"])

SESSION_HEADER = "x-esign-session"


def _session_of(x_esign_session: str | None) -> str:
    """只认签署会话头；Authorization（控制台/internal）在本面无意义。"""
    return (x_esign_session or "").strip()


@signer_router.get("/p/{link_token}", response_class=HTMLResponse)
def signer_page(link_token: str, db: Session = Depends(get_db)):
    """签署人 H5 页（人打开的就是这里）：异常状态服务端如实渲染，
    正常状态出签署应用页，页内 JS 走下面的 JSON 接口。"""
    from . import h5

    try:
        service.resolve_signer(db, link_token)
    except service.EsignError as exc:
        return HTMLResponse(h5.render_status(exc.detail), status_code=exc.status_code)
    return HTMLResponse(h5.render_page(link_token))


@signer_router.get("/s/{link_token}")
def signer_open(link_token: str, db: Session = Depends(get_db)):
    try:
        return service.open_link(db, link_token)
    except service.EsignError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


@signer_router.get("/s/{link_token}/preview")
def signer_preview(
    link_token: str,
    db: Session = Depends(get_db),
    x_esign_session: str | None = Header(default=None, alias=SESSION_HEADER),
):
    try:
        data = service.preview_document(db, link_token, _session_of(x_esign_session))
        task, _signer = service.resolve_signer(db, link_token)
    except service.EsignError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    media = "application/pdf" if task.file_name.lower().endswith(".pdf") else (
        "application/msword" if task.file_name.lower().endswith(".doc") else "text/plain; charset=utf-8"
    )
    filename = task.file_name.replace('"', "")
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@signer_router.post("/s/{link_token}/realname")
def signer_realname(
    link_token: str,
    body: RealnameIn,
    db: Session = Depends(get_db),
    x_esign_session: str | None = Header(default=None, alias=SESSION_HEADER),
):
    try:
        record = service.verify_identity(
            db, link_token, _session_of(x_esign_session),
            name=body.name, credential=body.credential,
        )
    except service.EsignError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except adapter_mod.AdapterError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    return {"verified": True, "record": record}


@signer_router.post("/s/{link_token}/sign")
def signer_sign(
    link_token: str,
    body: SignIn,
    db: Session = Depends(get_db),
    x_esign_session: str | None = Header(default=None, alias=SESSION_HEADER),
):
    try:
        return service.sign(
            db, link_token, _session_of(x_esign_session), intent_method=body.intent_method
        )
    except service.EsignError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc
    except adapter_mod.AdapterError as exc:
        raise HTTPException(exc.status_code, exc.detail) from exc


__all__ = ["console_router", "signer_router"]
