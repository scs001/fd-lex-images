"""计量内部端点（/internal/metering）。

（端点风格照 fd-wire /internal/metering；鉴权收敛到 INTERNAL_API_TOKEN。）

- ``POST /internal/metering/events``：HTTP 推送摄取（数组批量），bearer
  校验；令牌未配置时 fail-closed（403）。
- ``POST /internal/metering/consume``：触发一轮 registry Mongo audit 流
  消费（配置了 REGISTRY_MONGO_URI/DB 时可用），同样受令牌保护。
- ``GET /internal/metering/usage``：按（身份×单位）与合计聚合调用数/数量，
  可按凭据轨道与时间窗过滤。
- ``GET /internal/metering/anomalies`` / ``/anomalies/count``：计量异常
  留痕查询与计数（缺用量戳不静默）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..billing.deps import get_db_session, require_internal_token
from .audit_consumer import ConsumeResult, MongoAuditSource, consume_once
from .db import to_utc
from .ingest import ingest_events
from .models import MeteringAnomaly, MeteringRecord

router = APIRouter(prefix="/internal/metering", tags=["metering"],
                   dependencies=[Depends(require_internal_token)])


# ---------------------------------------------------------------------------
# 摄取（写入面）
# ---------------------------------------------------------------------------


class EventsEnvelope(BaseModel):
    """推送体：对象数组，或 ``{"events": [...]}`` 包装。"""

    events: list[dict[str, Any]] = Field(default_factory=list)


@router.post("/events")
async def ingest_push(request: Request, db: Session = Depends(get_db_session)) -> dict[str, int]:
    """批量摄取 registry 审计事件（MCPServerAccessRecord 数组）。

    请求体不锁 Pydantic 模型（audit schema 允许演进，未知字段放行），
    直接取原始 JSON 数组交给规范化层。
    """
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=422, detail="body must be JSON") from exc
    events = _coerce_events(payload)
    result = ingest_events(db, events)
    return result.as_dict()


@router.post("/consume")
def ingest_consume(db: Session = Depends(get_db_session)) -> dict[str, Any]:
    """触发一轮 registry Mongo audit 流消费（手动/定时触发口）。"""
    try:
        source = MongoAuditSource()  # 未配置/未安装时抛 RuntimeError
        result: ConsumeResult = consume_once(db, source)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return result.as_dict()


def _coerce_events(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict) and "events" in payload:
        envelope = EventsEnvelope.model_validate(payload)
        return envelope.events
    raise HTTPException(status_code=422, detail="body must be a JSON array of audit events")


# ---------------------------------------------------------------------------
# 聚合查询（读取面）
# ---------------------------------------------------------------------------


class UsageRow(BaseModel):
    caller: str
    unit: str
    calls: int
    quantity: int


class UsageTotals(BaseModel):
    calls: int
    by_unit: dict[str, int]


class UsageResponse(BaseModel):
    credential_track: str | None
    start: str | None
    end: str | None
    breakdown: list[UsageRow]
    totals: UsageTotals


@router.get("/usage", response_model=UsageResponse)
def usage(
    credential_track: str | None = Query(default=None),
    start: str | None = Query(default=None),
    end: str | None = Query(default=None),
    db: Session = Depends(get_db_session),
) -> UsageResponse:
    """按（调用者×单位）聚合调用数与数量，附合计；可按轨道与时间窗过滤。"""
    if credential_track is not None and credential_track not in ("platform", "customer"):
        raise HTTPException(
            status_code=422, detail="credential_track must be platform|customer"
        )
    start_dt = _parse_window("start", start)
    end_dt = _parse_window("end", end)

    conditions = []
    if credential_track:
        conditions.append(MeteringRecord.credential_track == credential_track)
    if start_dt:
        conditions.append(MeteringRecord.event_timestamp >= start_dt)
    if end_dt:
        conditions.append(MeteringRecord.event_timestamp <= end_dt)

    breakdown_q = (
        select(
            MeteringRecord.caller,
            MeteringRecord.unit,
            func.count(MeteringRecord.id).label("calls"),
            func.sum(MeteringRecord.quantity).label("quantity"),
        )
        .group_by(MeteringRecord.caller, MeteringRecord.unit)
        .order_by(MeteringRecord.caller, MeteringRecord.unit)
    )
    for condition in conditions:
        breakdown_q = breakdown_q.where(condition)
    rows = db.execute(breakdown_q).all()

    totals_q = select(
        func.count(MeteringRecord.id),
        MeteringRecord.unit,
        func.coalesce(func.sum(MeteringRecord.quantity), 0),
    ).group_by(MeteringRecord.unit)
    for condition in conditions:
        totals_q = totals_q.where(condition)
    total_rows = db.execute(totals_q).all()
    total_calls = sum(int(c) for c, _, _ in total_rows)
    by_unit = {unit: int(q) for _, unit, q in total_rows}

    return UsageResponse(
        credential_track=credential_track,
        start=start,
        end=end,
        breakdown=[
            UsageRow(caller=caller, unit=unit, calls=int(calls), quantity=int(qty or 0))
            for caller, unit, calls, qty in rows
        ],
        totals=UsageTotals(calls=total_calls, by_unit=by_unit),
    )


def _parse_window(name: str, value: str | None) -> Any:
    if value is None:
        return None
    try:
        return to_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{name} must be ISO-8601 datetime") from exc


# ---------------------------------------------------------------------------
# 计量异常（读取面）
# ---------------------------------------------------------------------------


class AnomalyCountResponse(BaseModel):
    total: int
    by_reason: dict[str, int]


@router.get("/anomalies/count", response_model=AnomalyCountResponse)
def anomaly_count(
    reason: str | None = Query(default=None), db: Session = Depends(get_db_session)
) -> AnomalyCountResponse:
    """计量异常计数（可按 reason 过滤）——缺用量戳告警的消费口。"""
    total_q = select(func.count(MeteringAnomaly.id))
    group_q = select(MeteringAnomaly.reason, func.count(MeteringAnomaly.id)).group_by(
        MeteringAnomaly.reason
    )
    if reason:
        total_q = total_q.where(MeteringAnomaly.reason == reason)
        group_q = group_q.where(MeteringAnomaly.reason == reason)
    total = db.execute(total_q).scalar_one()
    by_reason = {r: int(c) for r, c in db.execute(group_q).all()}
    return AnomalyCountResponse(total=int(total), by_reason=by_reason)


@router.get("/anomalies")
def list_anomalies(
    reason: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """最近的计量异常留痕（新→旧），detail 为 JSON 文本。"""
    q = select(MeteringAnomaly).order_by(MeteringAnomaly.id.desc()).limit(limit)
    if reason:
        q = q.where(MeteringAnomaly.reason == reason)
    items = [row.as_dict() for row in db.execute(q).scalars().all()]
    return {"anomalies": items, "count": len(items)}
