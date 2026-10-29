"""audit 流消费器：接口抽象 + 内存假实现驱动 + 水位重叠窗 + Mongo 骨架。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from fd_lex_api.metering.audit_consumer import (
    InMemoryAuditSource,
    MongoAuditSource,
    consume_once,
)
from fd_lex_api.metering.models import MeteringAnomaly, MeteringRecord

from test_billing_common import make_engine

TS0 = "2026-09-15T10:00:00+00:00"
TS1 = "2026-09-15T11:00:00+00:00"
TS2 = "2026-09-16T09:00:00+00:00"


def _event(rid: str, ts: str, stamp: dict) -> dict:
    return {
        "log_type": "mcp_server_access",
        "timestamp": ts,
        "request_id": rid,
        "identity": {"username": "cust-acme"},
        "mcp_server": {"name": "legal-search-mcp"},
        "mcp_request": {"method": "tools/call", "tool_name": "case_search"},
        "mcp_response": {"status": "ok", **stamp},
    }


def _non_metering_event(rid: str, ts: str) -> dict:
    return {
        "log_type": "registry_api_access",
        "timestamp": ts,
        "request_id": rid,
    }


def test_consume_ingests_and_is_idempotent() -> None:
    engine = make_engine()
    source = InMemoryAuditSource(
        [
            _event("req-1", TS0, {"rows_returned": 100}),
            _event("req-2", TS1, {"calls_used": 2}),
            _non_metering_event("req-skip", TS1),
        ]
    )
    with Session(engine) as db:
        first = consume_once(db, source)
        assert first.fetched == 3
        assert first.ingest.accepted == 2
        assert first.ingest.skipped == 1

        # 重放同一批（无回看窗 → 全量重拉）：幂等键兜住，不双记
        second = consume_once(db, source, overlap=timedelta(minutes=0))
        assert second.fetched == 3
        assert second.ingest.accepted == 0
        assert second.ingest.duplicates == 2
        records = list(db.execute(select(MeteringRecord)).scalars())
        assert {(r.unit, r.quantity) for r in records} == {("line", 100), ("call", 2)}


def test_consume_watermark_lookback_window() -> None:
    """水位 = 库内最大事件时间；下一轮回看重叠窗（容忍乱序），重叠由幂等键兜住。"""
    engine = make_engine()
    source = InMemoryAuditSource(
        [
            _event("req-1", TS0, {"rows_returned": 10}),
            _event("req-2", TS2, {"rows_returned": 20}),
        ]
    )
    with Session(engine) as db:
        consume_once(db, source, overlap=timedelta(minutes=5))
        assert source.fetch_calls[0][0] is None  # 首轮无水位

        # 第二轮：水位=TS2，回看 5 分钟；req-1 在窗前被挡，req-2 回看拉到后幂等去重
        result = consume_once(db, source, overlap=timedelta(minutes=5))
        ts2 = datetime(2026, 9, 16, 9, 0, 0, tzinfo=timezone.utc)
        since = source.fetch_calls[1][0]
        assert since is not None and (ts2 - since) == timedelta(minutes=5)
        assert result.fetched == 1
        assert result.ingest.accepted == 0 and result.ingest.duplicates == 1

        # 新事件（晚于水位）照常入账
        source.events.append(
            _event("req-3", "2026-09-16T12:00:00+00:00", {"rows_returned": 30})
        )
        result = consume_once(db, source, overlap=timedelta(minutes=5))
        assert result.ingest.accepted == 1 and result.ingest.duplicates == 1


def test_anomaly_carries_watermark() -> None:
    """异常留痕也推进水位（anomalies 的 event_timestamp 参与取大）。

    注：无 method 的事件在审计流口径下无法归类调用（协议流量/失败调用会被
    计入 skipped），故取「缺 method + 缺戳」作为异常样本。
    """
    engine = make_engine()
    bad = {
        "log_type": "mcp_server_access",
        "timestamp": TS1,
        "request_id": "req-bad",
        "identity": {"username": "cust-acme"},
        "mcp_server": {"name": "legal-search-mcp"},
        "mcp_request": {},  # 缺 method
        "mcp_response": {"status": "success"},  # 缺戳 → anomaly
    }
    source = InMemoryAuditSource([_event("req-1", TS0, {"rows_returned": 1}), bad])
    with Session(engine) as db:
        consume_once(db, source, overlap=timedelta(minutes=5))
        anomalies = list(db.execute(select(MeteringAnomaly)).scalars())
        assert len(anomalies) == 1
        consume_once(db, source, overlap=timedelta(minutes=5))
        (since, _) = source.fetch_calls[1]
        ts1 = datetime(2026, 9, 15, 11, 0, 0, tzinfo=timezone.utc)
        assert since is not None
        assert since == ts1 - timedelta(minutes=5)  # 水位=异常时间，回看 5 分钟


def test_mongo_source_unconfigured_raises_runtime_error() -> None:
    """未配置 REGISTRY_MONGO_URI/DB → 生产骨架路径显式不可用（409 源头）。"""
    from fd_lex_api.config import reset_settings

    reset_settings()
    source = MongoAuditSource()
    try:
        import os

        old = (os.environ.get("REGISTRY_MONGO_URI"), os.environ.get("REGISTRY_MONGO_DB"))
        os.environ.pop("REGISTRY_MONGO_URI", None)
        os.environ.pop("REGISTRY_MONGO_DB", None)
        reset_settings()
        try:
            source.fetch(None, 10)
            raised = None
        except RuntimeError as exc:
            raised = exc
        assert raised is not None and "REGISTRY_MONGO_URI" in str(raised)
    finally:
        import os

        if old[0] is not None:
            os.environ["REGISTRY_MONGO_URI"] = old[0]
        if old[1] is not None:
            os.environ["REGISTRY_MONGO_DB"] = old[1]
        reset_settings()


def test_mongo_source_with_injected_collection() -> None:
    """MongoAuditSource 骨架的查询形状（注入假 collection 验证 filter/sort/limit）。"""
    captured: dict = {}

    class FakeCollection:
        def find(self, filter, sort, limit):  # noqa: A002
            captured["filter"] = filter
            captured["sort"] = sort
            captured["limit"] = limit
            return [{"log_type": "mcp_server_access", "timestamp": TS0, "request_id": "m1"}]

    since = datetime(2026, 9, 15, 10, 0, 0, tzinfo=timezone.utc)
    source = MongoAuditSource(collection=FakeCollection())
    batch = source.fetch(since, 500)
    # 审计流 timestamp 实为 BSON date（naive UTC，2026-10-06 实采），按 datetime 过滤
    assert captured["filter"] == {
        "log_type": "mcp_server_access",
        "timestamp": {"$gt": since},
    }
    assert captured["sort"] == [("timestamp", 1)] and captured["limit"] == 500
    assert len(batch) == 1


def _audit_call(rid: str, ts: str, *, method: str = "tools/call",
                status: str = "success", tool_name: str = "wenshu_search") -> dict:
    """审计流实采形状：无 rows/calls 用度戳，只有 status/duration。"""
    return {
        "log_type": "mcp_server_access",
        "timestamp": ts,
        "request_id": rid,
        "identity": {"username": "lexdemocustomer", "auth_method": "patch-key"},
        "mcp_server": {"name": "virtual/lex-legal"},
        "mcp_request": {"method": method, "tool_name": tool_name},
        "mcp_response": {"status": status, "duration_ms": 12.0, "error_code": None},
    }


def test_audit_stream_counts_successful_tool_calls_when_no_stamps() -> None:
    """审计流口径：成功 tools/call 每次计 1（unit=call）；协议流量与失败调用不计费。"""
    engine = make_engine()
    source = InMemoryAuditSource(
        [
            _audit_call("req-call", TS0),
            _audit_call("req-init", TS0, method="initialize", tool_name=""),
            _audit_call("req-list", TS0, method="tools/list", tool_name=""),
            _audit_call("req-fail", TS1, status="error"),
        ]
    )
    with Session(engine) as db:
        result = consume_once(db, source)
        assert result.ingest.accepted == 1
        assert result.ingest.skipped == 3
        assert result.ingest.anomalies == 0  # 审计流不因缺戳刷异常
        records = list(db.execute(select(MeteringRecord)).scalars())
        assert [(r.request_id, r.unit, r.quantity) for r in records] == [
            ("req-call", "call", 1)
        ]


def test_push_path_audit_shaped_events_use_audit_caliber() -> None:
    """推送入口的审计流形状事件（log_type=mcp_server_access）同用审计流口径。"""
    from fd_lex_api.metering.ingest import ingest_events

    engine = make_engine()
    with Session(engine) as db:
        result = ingest_events(db, [_audit_call("req-push-audit", TS0)])
        assert result.accepted == 1
        assert result.anomalies == 0


def test_self_reported_events_keep_strict_missing_stamp() -> None:
    """显式自报事件（无 log_type，服务端盖章形态）保持「缺戳不静默」。"""
    from fd_lex_api.metering.ingest import ingest_events

    engine = make_engine()
    event = _audit_call("req-self-report", TS0)
    event.pop("log_type")
    with Session(engine) as db:
        result = ingest_events(db, [event])
        assert result.accepted == 0
        assert result.anomalies == 1
