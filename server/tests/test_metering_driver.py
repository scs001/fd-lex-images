"""计量入账驱动：poll→settle 一轮全链、未配置跳过、降级重放不双扣、段间隔离、开关。

真实表 + 内存假 audit source + FakeSub2Api（含幂等缓存）——不打真库不打真计费面；
事件形状对齐审计流（log_type=mcp_server_access，无用量戳 → 计次口径）。
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from fd_lex_api.billing import Customer, LedgerEntry, SettlementService, SqlMeteringSource
from fd_lex_api.config import reset_settings
from fd_lex_api.metering import driver as driver_mod
from fd_lex_api.metering.audit_consumer import InMemoryAuditSource
from fd_lex_api.metering.db import reset_metering_runtime
from fd_lex_api.metering.driver import _closed_period, start_metering_driver, tick_once

from test_billing_common import FakeSub2Api, add_customer, make_engine, make_plan

USER = "cust-1@customer.com"
OPENING = 10_000_000  # 预存 ¥10
OCT = datetime(2026, 10, 2, tzinfo=timezone.utc)  # 闭月聚合域 = 2026-09
SEPT = "2026-09"


def _audit_event(rid: str, *, ts: str, username: str = USER, method: str = "tools/call",
                 status: str = "success", server: str = "fd-legal-search-mcp") -> dict:
    """审计流形状事件（无 rows/calls 戳 → 消费路径计次口径）。"""
    return {
        "log_type": "mcp_server_access",
        "timestamp": ts,
        "request_id": rid,
        "identity": {"username": username},
        "mcp_server": {"name": server},
        "mcp_request": {"method": method, "tool_name": "wenshu_search"},
        "mcp_response": {"status": status},
    }


@contextmanager
def driver_env(monkeypatch, **overrides: str | None):
    """驱动环境：模块级 engine 指到测试文件库 + 套餐 + 客户（=事件 username）。

    driver 以 ``from .db import get_engine, get_session`` 导入——建表后把
    driver 模块的同名符号打点到该库（reset_metering_runtime 只清缓存，
    不换单例绑定的 URL）。
    """
    import tempfile
    from pathlib import Path

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from fd_lex_api.billing import Base as BillingBase
    from fd_lex_api.console_api.models import ConsoleBase
    from fd_lex_api.metering.db import MeteringBase

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "lex_driver_test.db"
        monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
        monkeypatch.setenv("SUB2API_ADMIN_KEY", "")
        for key, value in overrides.items():
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        reset_metering_runtime()
        reset_settings()

        driver_engine = create_engine(
            f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
        )
        BillingBase.metadata.create_all(driver_engine)
        MeteringBase.metadata.create_all(driver_engine)
        ConsoleBase.metadata.create_all(driver_engine)
        factory = sessionmaker(bind=driver_engine, autoflush=False, expire_on_commit=False)
        monkeypatch.setattr(driver_mod, "get_engine", lambda: driver_engine)
        monkeypatch.setattr(driver_mod, "get_session", lambda: factory())

        try:
            fake = FakeSub2Api()
            session = Session(driver_engine)
            plan = make_plan(
                session,
                code="standard",
                name="标准版",
                quotas=[
                    {"unit": "call", "included_quantity": 2,
                     "overage_unit_price_micro": 10_000},  # ¥0.01/次
                ],
            )
            session.commit()
            add_customer(session, name="客户A", plan_id=plan.id, sub2api_user_id=USER)
            fake.add_user(USER, balance_micro=OPENING)
            session.commit()
            session.close()
            yield fake, driver_engine
        finally:
            reset_metering_runtime()
            reset_settings()


def ledger_entries(engine, kind: str) -> list[LedgerEntry]:
    with Session(engine) as session:
        return list(
            session.execute(select(LedgerEntry).where(LedgerEntry.kind == kind)).scalars()
        )


def _events(n: int = 4, month: str = SEPT) -> list[dict[str, Any]]:
    """n 条成功 tools/call（计次口径每次 1），默认落闭月 2026-09。"""
    return [
        _audit_event(f"r-{i}", ts=f"{month}-01T10:0{i}:00+00:00")
        for i in range(n)
    ]


def test_tick_full_pipe_polls_ingests_and_settles(monkeypatch) -> None:
    """一轮：事件经假 source 摄取落表 → 闭月聚合 → 超额入账 sub2api 恰一次。"""
    with driver_env(monkeypatch) as (fake, engine):
        outcome = tick_once(
            source=InMemoryAuditSource(_events(4)),
            sub2api=fake.client(),
            now=OCT,
        )
        assert outcome["polled"]["accepted"] == 4
        assert outcome["settled"]["ok"] is True
        assert outcome["settled"]["failures"] == 0
        overages = ledger_entries(engine, "overage")
        assert len(overages) == 1 and overages[0].sub2api_applied is True
        # 4 次 − 含额 2 = 超额 2 × ¥0.01 = 20000 微元
        assert overages[0].quantity == 2
        assert overages[0].amount_micro == 20_000
        assert len(fake.adjust_calls) == 1
        assert fake.balance(USER) == OPENING - 20_000


def test_tick_replay_same_domain_does_not_double_charge(monkeypatch) -> None:
    """同批重放（重叠窗兜底重拉）：幂等键短路——sub2api 零新增调用、账本零新增。"""
    with driver_env(monkeypatch) as (fake, engine):
        tick_once(source=InMemoryAuditSource(_events(4)), sub2api=fake.client(), now=OCT)
        calls_after_first = len(fake.adjust_calls)
        balance_after_first = fake.balance(USER)

        outcome = tick_once(
            source=InMemoryAuditSource(_events(4)), sub2api=fake.client(), now=OCT
        )
        assert outcome["polled"]["duplicates"] == 4  # 幂等键兜住
        assert outcome["settled"]["ok"] is True
        assert len(fake.adjust_calls) == calls_after_first  # 无新增扣减
        assert fake.balance(USER) == balance_after_first
        assert len(ledger_entries(engine, "overage")) == 1


def test_tick_degraded_sub2api_then_replay_same_key(monkeypatch) -> None:
    """sub2api 故障：首轮失败不落账；恢复后同键重放 → 净一次扣减。"""
    with driver_env(monkeypatch) as (fake, engine):
        fake.fail_adjust_left = 1
        first = tick_once(
            source=InMemoryAuditSource(_events(4)), sub2api=fake.client(), now=OCT
        )
        assert first["settled"]["ok"] is False
        assert ledger_entries(engine, "overage") == []

        second = tick_once(
            source=InMemoryAuditSource(_events(4)), sub2api=fake.client(), now=OCT
        )
        assert second["settled"]["ok"] is True
        overages = ledger_entries(engine, "overage")
        assert len(overages) == 1
        assert fake.balance(USER) == OPENING - 20_000  # 净一次


def test_tick_poll_crash_does_not_block_settle(monkeypatch) -> None:
    """段间隔离：poll 崩（假 source 抛错）不阻断 settle 段。"""

    class ExplodingSource:
        def fetch(self, since, limit):  # noqa: ANN001
            raise RuntimeError("mongo down")

    with driver_env(monkeypatch) as (fake, engine):
        # 先灌一批（正常轮），再让 poll 崩——settle 段应照常
        tick_once(source=InMemoryAuditSource(_events(4)), sub2api=fake.client(), now=OCT)
        calls = len(fake.adjust_calls)
        outcome = tick_once(source=ExplodingSource(), sub2api=fake.client(), now=OCT)
        assert outcome["polled"] is None
        assert outcome["settled"] is not None  # settle 段独立跑完
        assert len(fake.adjust_calls) == calls  # 重放幂等，无新增


def test_tick_skips_when_unconfigured(monkeypatch) -> None:
    """Mongo 与 sub2api 皆未配置：两段各自跳过（None），不抛错。"""
    with driver_env(monkeypatch) as (_fake, _engine):
        monkeypatch.delenv("REGISTRY_MONGO_URI", raising=False)
        monkeypatch.setenv("SUB2API_ADMIN_KEY", "")
        reset_settings()
        outcome = tick_once()
        assert outcome["polled"] is None
        assert outcome["settled"] is None


def test_closed_period_previous_month() -> None:
    assert _closed_period(datetime(2026, 10, 2, tzinfo=timezone.utc)) == "2026-09"
    assert _closed_period(datetime(2026, 1, 5, tzinfo=timezone.utc)) == "2025-12"


def test_current_month_deferred_not_settled(monkeypatch) -> None:
    """当月事件不结（只结闭月）：settle 段对 9 月域跑，10 月用量零扣。"""
    with driver_env(monkeypatch) as (fake, engine):
        outcome = tick_once(
            source=InMemoryAuditSource(_events(4, month="2026-10")),
            sub2api=fake.client(),
            now=OCT,
        )
        assert outcome["polled"]["accepted"] == 4  # 摄取照常
        assert outcome["settled"]["ok"] is True
        assert ledger_entries(engine, "overage") == []  # 闭月（9月）无用量
        assert fake.adjust_calls == []


def test_start_disabled_is_noop(monkeypatch) -> None:
    """默认关：start 直接返回（无事件循环下也不报错）。"""
    with driver_env(monkeypatch) as (_fake, _engine):
        monkeypatch.setenv("METERING_DRIVER_ENABLED", "false")
        reset_settings()
        start_metering_driver()
        assert driver_mod._task is None
