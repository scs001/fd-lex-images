"""用量两档预警（80% / 95%）：同客户同周期同单位同档位只发一次。

（照 fd-wire billing/notices.py 移植；lex 适配=按单位判定与留档——行与
次的额度各自到达阈值各发各的，互不抑制。）

阈值比较全整数运算（used*100 >= pct*included），不吃浮点亏；
「只发一次」由 billing_notices 的唯一约束兜底（SAVEPOINT 吞重复）。
渠道固定 mail+inapp（spec 裁决）；实际投递由通知通道消费
NoticeRecord 行，本模块只负责判定与留档（通知发送是后续任务）。
"""

from __future__ import annotations

import json
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import NOTICE_CHANNELS, Customer, NoticeKind, NoticeRecord, validate_period

USAGE_WARNING_TIERS: tuple[int, ...] = (80, 95)


def threshold_tiers_hit(used: int, included: int) -> list[int]:
    """纯判定：已用/含额跨过的预警档位（升序）。两档阈值判定的服务函数。"""
    if included <= 0:
        return []
    return [pct for pct in USAGE_WARNING_TIERS if used * 100 >= pct * included]


def _payload(unit: str, used: int, included: int, period: str) -> str:
    ratio = (Decimal(used) / Decimal(included)).quantize(Decimal("0.0001"))
    return json.dumps(
        {
            "unit": unit,
            "used_quantity": used,
            "included_quantity": included,
            "ratio": str(ratio),
            "period": period,
        },
        ensure_ascii=False,
    )


def already_sent(
    session: Session, customer_id: int, period: str, threshold_pct: int, unit: str
) -> bool:
    return (
        session.execute(
            select(NoticeRecord).where(
                NoticeRecord.customer_id == customer_id,
                NoticeRecord.period == period,
                NoticeRecord.kind == NoticeKind.USAGE_WARNING.value,
                NoticeRecord.threshold_pct == threshold_pct,
                NoticeRecord.unit == unit,
            )
        ).scalar_one_or_none()
        is not None
    )


def evaluate_usage_warnings(
    session: Session,
    *,
    customer: Customer,
    period: str,
    unit: str,
    used_quantity: int,
    included_quantity: int,
) -> list[NoticeRecord]:
    """按已用/含额判定两档预警，新建未发过的档位（幂等），返回新建列表。

    只判定与留档，不做任何通知投递（渠道消费是后续任务）。
    """
    validate_period(period)
    created: list[NoticeRecord] = []
    for pct in threshold_tiers_hit(used_quantity, included_quantity):
        if already_sent(session, customer.id, period, pct, unit):
            continue
        notice = NoticeRecord(
            customer_id=customer.id,
            kind=NoticeKind.USAGE_WARNING.value,
            period=period,
            threshold_pct=pct,
            unit=unit,
            channels=NOTICE_CHANNELS,
            payload_json=_payload(unit, used_quantity, included_quantity, period),
        )
        try:
            with session.begin_nested():
                session.add(notice)
                session.flush()
        except IntegrityError:
            continue  # 并发对手已发——只发一次
        created.append(notice)
    return created
