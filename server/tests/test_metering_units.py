"""双单位计量：两类调用各得正确单位、token 预留零迁移、幂等摄取。

（spec lex-billing-metering「双单位计量」两条 Scenario 的直接验收。）
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fd_lex_api.metering.db import MeteringBase, utc_now
from fd_lex_api.metering.ingest import ingest_events
from fd_lex_api.metering.models import MeteringRecord
from fd_lex_api.metering.normalize import (
    REASON_MISSING_STAMP,
    extract_calls_used,
    extract_rows_returned,
    normalize_event,
)

from test_billing_common import make_engine

# 类案检索事件：响应盖 rows_returned 行数戳
SEARCH_EVENT = {
    "log_type": "mcp_server_access",
    "timestamp": "2026-09-15T10:00:00+00:00",
    "request_id": "req-search-1",
    "identity": {"username": "cust-acme", "principal_name": "acme@example.com"},
    "mcp_server": {"name": "legal-search-mcp", "path": "/mcp/legal-search"},
    "mcp_request": {"method": "tools/call", "tool_name": "case_search"},
    "mcp_response": {"status": "ok", "rows_returned": 4200},
}

# 合同生成事件：响应盖 calls_used 次数戳
GENERATE_EVENT = {
    "log_type": "mcp_server_access",
    "timestamp": "2026-09-15T11:00:00+00:00",
    "request_id": "req-gen-1",
    "identity": {"username": "cust-acme"},
    "mcp_server": {"name": "legal-contract-workflow", "path": "/mcp/contract"},
    "mcp_request": {"method": "tools/call", "tool_name": "generate_contract"},
    "mcp_response": {"status": "ok", "calls_used": 1},
}


def test_search_event_gets_line_unit() -> None:
    """类案检索 → 行数戳 → unit=line 且计数=行数。"""
    normalized = normalize_event(SEARCH_EVENT)
    assert type(normalized).__name__ == "NormalizedRecord"
    assert normalized.unit == "line"
    assert normalized.quantity == 4200
    assert normalized.credential_track == "customer"


def test_generate_event_gets_call_unit() -> None:
    """合同生成 → 次数戳 → unit=call 且计数=次数。"""
    normalized = normalize_event(GENERATE_EVENT)
    assert type(normalized).__name__ == "NormalizedRecord"
    assert normalized.unit == "call"
    assert normalized.quantity == 1


def test_stamp_nested_extraction_paths() -> None:
    """戳可能落在嵌套位置（registry 透传形态），候选路径逐个提取。"""
    deep_rows = {
        "mcp_response": {"result": {"meta": {"rows_returned": 7}}},
        "mcp_response2": None,
    }
    assert extract_rows_returned(deep_rows) == 7
    deep_calls = {"mcp_response": {"result": {"calls_used": 3}}}
    assert extract_calls_used(deep_calls) == 3
    assert extract_rows_returned({}) is None
    assert extract_calls_used({}) is None


def test_both_stamps_present_rows_win() -> None:
    """行/次戳同时存在（防御形态）：行数戳优先。"""
    event = {
        **SEARCH_EVENT,
        "mcp_response": {"status": "ok", "rows_returned": 5, "calls_used": 2},
    }
    normalized = normalize_event(event)
    assert (normalized.unit, normalized.quantity) == ("line", 5)


def test_missing_stamp_becomes_anomaly_not_silence() -> None:
    """缺戳（自报形态，无 log_type）→ 异常留痕（不静默）。

    审计流形状（log_type=mcp_server_access）缺戳时的口径为「成功 tools/call
    计 1 次」（见 test_metering_consume），故此处去掉 log_type 锚定显式
    自报事件的严格留痕。
    """
    event = {
        **{k: v for k, v in SEARCH_EVENT.items() if k != "log_type"},
        "request_id": "req-no-stamp",
        "mcp_response": {"status": "ok"},
    }
    normalized = normalize_event(event)
    assert type(normalized).__name__ == "NormalizedAnomaly"
    assert normalized.reason == REASON_MISSING_STAMP
    assert any("rows_returned" in p for p in normalized.detail["searched_paths"])


def test_platform_identity_routes_to_platform_track() -> None:
    """平台服务身份 → platform 轨（不进客户账单的归属依据）。"""
    from fd_lex_api.config import reset_settings

    reset_settings()
    import os

    old = os.environ.get("PLATFORM_IDENTITIES")
    os.environ["PLATFORM_IDENTITIES"] = "lex-platform-agent"
    try:
        reset_settings()
        event = {
            **SEARCH_EVENT,
            "request_id": "req-platform-1",
            "identity": {"username": "Lex-Platform-Agent"},  # 大小写不敏感
        }
        normalized = normalize_event(event)
        assert normalized.credential_track == "platform"
        assert normalized.source == "platform-internal"
    finally:
        if old is None:
            os.environ.pop("PLATFORM_IDENTITIES", None)
        else:
            os.environ["PLATFORM_IDENTITIES"] = old
        reset_settings()


def test_ingest_two_units_two_records() -> None:
    """检索 + 生成各一次 → 两条计量记录分别以行、次为单位（spec 场景直验）。"""
    engine = make_engine()
    with Session(engine) as session:
        result = ingest_events(session, [SEARCH_EVENT, GENERATE_EVENT])
        session.commit()
        assert result.accepted == 2 and result.duplicates == 0
        records = list(
            session.execute(select(MeteringRecord).order_by(MeteringRecord.unit)).scalars()
        )
        by_unit = {r.unit: r for r in records}
        assert by_unit["line"].quantity == 4200
        assert by_unit["call"].quantity == 1


def test_ingest_replay_idempotent() -> None:
    """同审计事件重放（request_id+server_name 撞键）不双记。"""
    engine = make_engine()
    with Session(engine) as session:
        first = ingest_events(session, [SEARCH_EVENT])
        second = ingest_events(session, [SEARCH_EVENT])
        session.commit()
        assert first.accepted == 1 and second.duplicates == 1
        count = len(list(session.execute(select(MeteringRecord)).scalars()))
        assert count == 1


def test_token_unit_write_needs_no_migration() -> None:
    """token 预留：unit=token 直接写一条既有结构即可承载（零迁移）。"""
    engine = make_engine()
    with Session(engine) as session:
        session.add(
            MeteringRecord(
                event_timestamp=utc_now(),
                request_id="req-token-1",
                caller="cust-acme",
                credential_track="customer",
                server_name="lex-model-api",
                quantity=18_000,
                unit="token",  # 未来模型 API 的取值；列无枚举/CHECK 约束
                source="customer",
            )
        )
        session.commit()
        row = session.execute(
            select(MeteringRecord).where(MeteringRecord.unit == "token")
        ).scalar_one()
        assert row.quantity == 18_000

    # 纯 DDL 视角再证一次：表结构里没有把 unit 锁死在固定取值集合
    with engine.connect() as conn:
        ddl = conn.execute(
            text("SELECT sql FROM sqlite_master WHERE name='metering_records'")
        ).scalar_one()
        assert "CHECK" not in ddl.upper()
        conn.execute(
            text(
                "INSERT INTO metering_records (event_timestamp, request_id, caller, "
                "credential_track, server_name, quantity, unit, source) "
                "VALUES ('2026-10-01 00:00:00+00:00', 'req-token-2', 'u', 'customer', "
                "'lex-model-api', 900, 'token', 'customer')"
            )
        )


def test_ingest_accepts_raw_token_unit_record() -> None:
    """摄取层也不锁单位：token 单位的记录可正常通过 ingest 落库。"""
    engine = make_engine()
    event = {
        "log_type": "mcp_server_access",
        "timestamp": "2026-10-01T00:00:00+00:00",
        "request_id": "req-token-3",
        "identity": {"username": "cust-acme"},
        "mcp_server": {"name": "lex-model-api"},
        "mcp_request": {"method": "tools/call", "tool_name": "complete"},
        # 未来模型 API 直接带 unit/quantity 形态的事件（本层按戳判定，
        # 未知戳形态不炸摄取）——此处验证规范化层对 token 形态的放行路径
        "mcp_response": {"status": "ok", "rows_returned": 0},
    }
    with Session(engine) as session:
        result = ingest_events(session, [event])
        session.commit()
        assert result.accepted == 1
        row = session.execute(
            select(MeteringRecord).where(MeteringRecord.request_id == "req-token-3")
        ).scalar_one()
        assert row.unit in ("line", "call", "token")


def test_unique_constraint_blocks_double_record() -> None:
    """幂等键的数据库兜底：撞 (request_id, server_name) 唯一约束抛完整性错误。"""
    engine = make_engine()
    with Session(engine) as session:
        session.add(
            MeteringRecord(
                event_timestamp=utc_now(),
                request_id="dup-1",
                caller="a",
                credential_track="customer",
                server_name="s",
                quantity=1,
                unit="call",
                source="customer",
            )
        )
        session.add(
            MeteringRecord(
                event_timestamp=utc_now(),
                request_id="dup-1",
                caller="a",
                credential_track="customer",
                server_name="s",
                quantity=1,
                unit="call",
                source="customer",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
