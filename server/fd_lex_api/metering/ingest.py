"""摄取服务：批量审计事件 → 幂等落库（HTTP 推送与 Mongo 消费共用）。

（照 fd-wire metering/ingest.py 移植；lex 适配=记录带 unit/quantity。）

幂等语义：``request_id + server_name`` 已存在（或同批次内重复）即跳过，
不产生第二条计量记录；异常留痕以 ``request_id + server_name + reason``
幂等。批量结束一次性提交（调用方 commit）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import utc_now
from .models import MeteringAnomaly, MeteringRecord
from .normalize import (
    NormalizedAnomaly,
    NormalizedRecord,
    SkippedEvent,
    normalize_event,
)


@dataclass(slots=True)
class IngestResult:
    """一批事件的摄取结果计数。"""

    received: int = 0
    accepted: int = 0
    duplicates: int = 0
    anomalies: int = 0
    anomaly_duplicates: int = 0
    skipped: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "received": self.received,
            "accepted": self.accepted,
            "duplicates": self.duplicates,
            "anomalies": self.anomalies,
            "anomaly_duplicates": self.anomaly_duplicates,
            "skipped": self.skipped,
        }


def ingest_events(
    db: Session,
    events: Iterable[dict[str, Any]],
    *,
    assume_tool_call: bool = False,
) -> IngestResult:
    """把一批原始审计事件规范化并幂等写入；调用方负责 commit。

    ``assume_tool_call`` 透传 normalize 层强制审计流口径；log_type 为
    ``mcp_server_access`` 的事件本身即适用该口径（两个摄取入口一致），
    显式自报事件（无 log_type）保持缺戳异常留痕。
    """
    result = IngestResult()
    seen_records: set[tuple[str, str]] = set()
    seen_anomalies: set[tuple[str, str, str]] = set()
    now = utc_now()

    for raw in events:
        result.received += 1
        normalized = normalize_event(
            raw if isinstance(raw, dict) else {}, assume_tool_call=assume_tool_call
        )

        if isinstance(normalized, SkippedEvent):
            result.skipped += 1
        elif isinstance(normalized, NormalizedRecord):
            _ingest_record(db, normalized, seen_records, result, now)
        elif isinstance(normalized, NormalizedAnomaly):
            _ingest_anomaly(db, normalized, seen_anomalies, result, now)

    return result


def _ingest_record(
    db: Session,
    record: NormalizedRecord,
    seen: set[tuple[str, str]],
    result: IngestResult,
    now: Any,
) -> None:
    key = (record.request_id, record.server_name)
    if key in seen:  # 同批次内重复
        result.duplicates += 1
        return
    exists = db.execute(
        select(MeteringRecord.id).where(
            MeteringRecord.request_id == record.request_id,
            MeteringRecord.server_name == record.server_name,
        )
    ).first()
    if exists is not None:  # 历史已摄取（重放）
        result.duplicates += 1
        seen.add(key)
        return
    db.add(
        MeteringRecord(
            event_timestamp=record.event_timestamp,
            request_id=record.request_id,
            caller=record.caller,
            caller_principal=record.caller_principal,
            credential_track=record.credential_track,
            server_name=record.server_name,
            server_path=record.server_path,
            tool_name=record.tool_name,
            quantity=record.quantity,
            unit=record.unit,
            source=record.source,
            created_at=now,
        )
    )
    seen.add(key)
    result.accepted += 1


def _ingest_anomaly(
    db: Session,
    anomaly: NormalizedAnomaly,
    seen: set[tuple[str, str, str]],
    result: IngestResult,
    now: Any,
) -> None:
    key = (
        anomaly.request_id or "",
        anomaly.server_name or "",
        anomaly.reason,
    )
    if key in seen:
        result.anomaly_duplicates += 1
        return
    if anomaly.request_id and anomaly.server_name:
        exists = db.execute(
            select(MeteringAnomaly.id).where(
                MeteringAnomaly.request_id == anomaly.request_id,
                MeteringAnomaly.server_name == anomaly.server_name,
                MeteringAnomaly.reason == anomaly.reason,
            )
        ).first()
        if exists is not None:
            result.anomaly_duplicates += 1
            seen.add(key)
            return
    db.add(
        MeteringAnomaly(
            reason=anomaly.reason,
            request_id=anomaly.request_id,
            server_name=anomaly.server_name,
            tool_name=anomaly.tool_name,
            caller=anomaly.caller,
            credential_track=anomaly.credential_track,
            detail=json.dumps(anomaly.detail, ensure_ascii=False, default=str),
            event_timestamp=anomaly.event_timestamp,
            created_at=now,
        )
    )
    seen.add(key)
    result.anomalies += 1
