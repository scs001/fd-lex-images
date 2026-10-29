"""lex 权威账本：同 idempotency_key 重放只记一条（结算幂等的兜底约束）。"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from fd_lex_api.billing import (
    Customer,
    Ledger,
    LedgerKind,
    adjustment_key,
    grant_key,
    grant_unit_key,
    hardstop_key,
    settle_key,
)

from test_billing_common import add_customer, make_engine, make_plan

PERIOD = "2026-09"


def _customer_id(session: Session, ref: str) -> int:
    return session.execute(
        select(Customer).where(Customer.sub2api_user_id == ref)
    ).scalar_one().id


def test_same_key_records_once() -> None:
    engine = make_engine()
    with Session(engine) as session:
        plan = make_plan(session, code="p", monthly_price_micro=1_999_000)
        customer = add_customer(session, name="客户A", plan_id=plan.id,
                                sub2api_user_id="u-a")
        ledger = Ledger(session)

        first = ledger.record(
            customer_id=customer.id, kind=LedgerKind.OVERAGE, period=PERIOD,
            idempotency_key="k-1", unit="line", quantity=100, amount_micro=400_000,
        )
        replay = ledger.record(
            customer_id=_customer_id(session, "u-a"), kind=LedgerKind.OVERAGE,
            period=PERIOD, idempotency_key="k-1", unit="line", quantity=100,
            amount_micro=400_000,
        )
        assert first.created is True
        assert replay.created is False
        assert replay.entry.id == first.entry.id
        entries = ledger.entries(customer.id, PERIOD)
        assert len(entries) == 1


def test_key_conventions() -> None:
    """键规范收口在 ledger 模块（结算幂等键的唯一出处）。"""
    assert grant_key(7, "2026-09") == "grant:7:2026-09"
    assert grant_unit_key(7, "2026-09", "call") == "grant:7:2026-09:call"
    assert settle_key("2026-09", None, 7, "line") == "settle:2026-09:period:7:line"
    assert settle_key("2026-09", "batch-1", 7, "call") == "settle:2026-09:batch-1:7:call"
    assert adjustment_key("adj-1", 7, "2026-09") == "adjust:7:2026-09:adj-1"
    assert hardstop_key(7, "2026-09", "call-tool-x") == "hardstop:7:2026-09:call-tool-x"


def test_semantic_shortcuts_are_idempotent() -> None:
    engine = make_engine()
    with Session(engine) as session:
        plan = make_plan(session, code="p2", monthly_price_micro=5_000_000,
                         quotas=[{"unit": "line", "included_quantity": 1_000_000}])
        customer = add_customer(session, name="客户B", plan_id=plan.id,
                                sub2api_user_id="u-b")
        ledger = Ledger(session)

        g1 = ledger.ensure_grant(customer_id=customer.id, period=PERIOD,
                                 monthly_price_micro=plan.monthly_price_micro)
        g2 = ledger.ensure_grant(customer_id=customer.id, period=PERIOD,
                                 monthly_price_micro=plan.monthly_price_micro)
        assert g1.created and not g2.created

        ug1 = ledger.ensure_unit_grant(customer_id=customer.id, period=PERIOD,
                                       unit="line", included_quantity=1_000_000)
        ug2 = ledger.ensure_unit_grant(customer_id=customer.id, period=PERIOD,
                                       unit="line", included_quantity=1_000_000)
        assert ug1.created and not ug2.created

        adj = ledger.record_adjustment(customer_id=customer.id, period=PERIOD,
                                       amount_micro=-1_000, source_ref="csr-001")
        adj_replay = ledger.record_adjustment(customer_id=customer.id, period=PERIOD,
                                              amount_micro=-1_000, source_ref="csr-001")
        assert adj.created and not adj_replay.created
        assert ledger.applied_total(customer.id, PERIOD) == 0  # adjustment 未置 applied

        hs = ledger.record_hardstop(customer_id=customer.id, period=PERIOD, ref="ref-1")
        hs_replay = ledger.record_hardstop(customer_id=customer.id, period=PERIOD, ref="ref-1")
        assert hs.created and not hs_replay.created

        with_qty = ledger.record_overage(
            customer_id=customer.id, period=PERIOD, unit="line",
            idempotency_key=settle_key(PERIOD, None, customer.id, "line"),
            quantity=500, amount_micro=2_000, sub2api_applied=True,
        )
        assert with_qty.created
        assert ledger.overage_quantity(customer.id, PERIOD, "line") == 500
        assert ledger.granted_quantity(customer.id, PERIOD, "line") == 1_000_000
        assert ledger.applied_total(customer.id, PERIOD) == 2_000


def test_zero_adjustment_rejected() -> None:
    engine = make_engine()
    with Session(engine) as session:
        plan = make_plan(session, code="p3")
        customer = add_customer(session, name="客户C", plan_id=plan.id,
                                sub2api_user_id="u-c")
        ledger = Ledger(session)
        with pytest.raises(ValueError):
            ledger.record_adjustment(customer_id=customer.id, period=PERIOD,
                                     amount_micro=0, source_ref="x")
