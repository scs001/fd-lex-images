"""计量域（lex 双单位计量）：模型/规范化/摄取/audit 流消费/内部端点。

入口一览：
- 建表：``init_metering(engine)``（create_all；与 billing 同库分域）
- 摄取：``ingest_events(session, events)``（HTTP 推送与消费器共用）
- 消费：``consume_once(session, source)``（``AuditEventSource`` 协议）
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from .audit_consumer import (
    AuditEventSource,
    ConsumeResult,
    InMemoryAuditSource,
    MongoAuditSource,
    consume_once,
)
from .db import MeteringBase, ensure_schema, get_db, get_engine, get_session
from .ingest import IngestResult, ingest_events
from .models import (
    TRACK_CUSTOMER,
    TRACK_PLATFORM,
    UNITS,
    UNIT_CALL,
    UNIT_LINE,
    UNIT_TOKEN,
    MeteringAnomaly,
    MeteringRecord,
)
from .normalize import (
    REASON_MISSING_STAMP,
    REASON_UNPARSABLE,
    extract_calls_used,
    extract_rows_returned,
    normalize_event,
    resolve_credential_track,
)

__all__ = [
    "AUDIT_LOG_TYPE",
    "ConsumeResult",
    "IngestResult",
    "InMemoryAuditSource",
    "MeteringAnomaly",
    "MeteringBase",
    "MeteringRecord",
    "MongoAuditSource",
    "REASON_MISSING_STAMP",
    "REASON_UNPARSABLE",
    "TRACK_CUSTOMER",
    "TRACK_PLATFORM",
    "AuditEventSource",
    "UNITS",
    "UNIT_CALL",
    "UNIT_LINE",
    "UNIT_TOKEN",
    "consume_once",
    "ensure_schema",
    "extract_calls_used",
    "extract_rows_returned",
    "get_db",
    "get_engine",
    "get_session",
    "ingest_events",
    "init_metering",
    "normalize_event",
    "resolve_credential_track",
]


def init_metering(engine: Engine | None = None) -> Engine:
    """幂等建 metering_* 表。不碰 billing_* 表（归 billing 域所有）。"""
    if engine is None:
        engine = get_engine()
    MeteringBase.metadata.create_all(engine)
    return engine


# audit_consumer 的模块常量再导出（保持 __all__ 完整性）
from .audit_consumer import AUDIT_LOG_TYPE  # noqa: E402
