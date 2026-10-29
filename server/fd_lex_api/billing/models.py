"""计费域 SQLAlchemy 模型：套餐/配额/客户/账本/预警通知。

（照 fd-wire billing/models.py 移植；lex 适配=套餐配额拆独立表按单位
配置，承载双单位计价与 token 扩展。）

金额一律用「微元」（1 元 = 1,000,000 微元）的整数存储与运算，
避免浮点误差（超额单价 ¥0.004/行 = 4,000 微元/行）。

注意：
- `metering_records` / `metering_anomalies` 表归 metering 模块所有，刻意
  不在本 Base 的 metadata 里（见 billing/metering_source.py 的共享读取
  契约）；billing 的 create_all 只建 billing_* 表。
- 套餐数字不预填（design D8）：档位/包含额度/超额单价是数据不是常量，
  由运营后台经 plans.upsert_plan 配置，调价不发版。
- 迁移链由主代理收敛：落地前先 ``Base.metadata.create_all(engine)``。
"""

from __future__ import annotations

import enum
import re
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def validate_period(period: str) -> str:
    """period 必须形如 YYYY-MM，否则抛 ValueError。"""
    if not isinstance(period, str) or not PERIOD_RE.match(period):
        raise ValueError(f"period 需为 YYYY-MM: {period!r}")
    return period


class Base(DeclarativeBase):
    """计费域 ORM 基类（billing_* 表）。"""


class LedgerKind(str, enum.Enum):
    """账本条目类型。"""

    GRANT = "grant"          # 套餐额度（月费 grant 带金额；单位 grant 带含额数量）
    OVERAGE = "overage"      # 超额按单位计费
    HARDSTOP = "hardstop"    # 额度耗尽硬停事件
    ADJUSTMENT = "adjustment"  # 人工调整（带符号）


#: 其金额变动会经由 sub2api adjustBalance 执行的账目类型。
#: grant=套餐额度分配（月费走账单，不扣 sub2api 余额）。
SUB2API_APPLIED_KINDS = frozenset({LedgerKind.OVERAGE.value, LedgerKind.ADJUSTMENT.value})


class CustomerStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"


class Plan(Base):
    """套餐档位（数字不预填：由后台配置，调价不发版）。"""

    __tablename__ = "billing_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    #: 微元金额用 BigInteger：PG int4 上限 21.47 亿微元（¥2147）——月费大档会溢出
    #: （wire cutover 2026-10-11 实证抓修同款缺陷；SQLite 动态 int8 掩盖）
    monthly_price_micro: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    quotas: Mapped[list["PlanQuota"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan"
    )
    customers: Mapped[list["Customer"]] = relationship(back_populates="plan")

    def quota(self, unit: str) -> "PlanQuota | None":
        """按单位取配额配置；未配置 = 该单位此套餐不参与计价。"""
        for q in self.quotas:
            if q.unit == unit:
                return q
        return None

    def __repr__(self) -> str:  # pragma: no cover - 调试便利
        return f"<Plan {self.code} ¥{self.monthly_price_micro / 1_000_000}/mo>"


class PlanQuota(Base):
    """套餐按单位的配额配置（双单位计价的数据载体）。

    - unit：line|call（token 预留）——普通字符串列，扩展单位零迁移；
    - included_quantity：包含额度（0=无包含额度）；
    - overage_unit_price_micro：超额单价（微元/单位，0=超额不计价）。
    套餐未配置某单位 = 该单位用量不进账单（对账侧以 unbilled 差异呈现，
    不静默）。
    """

    __tablename__ = "billing_plan_quotas"
    __table_args__ = (UniqueConstraint("plan_id", "unit", name="uq_plan_unit"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("billing_plans.id"), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    included_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 超额单价（微元/单位）同用 BigInteger：¥0.01/次 = 10000 微元尚安全，
    #: 但高单价单位（如 ¥0.5/行 = 500000 微元 × 大批量）与统一口径取 BigInteger
    overage_unit_price_micro: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    plan: Mapped[Plan] = relationship(back_populates="quotas")


class Customer(Base):
    """客户与支付侧（sub2api）账户映射。"""

    __tablename__ = "billing_customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    sub2api_user_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("billing_plans.id"), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=CustomerStatus.ACTIVE.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    plan: Mapped[Plan] = relationship(back_populates="customers")

    @property
    def status_enum(self) -> CustomerStatus:
        return CustomerStatus(self.status)


class LedgerEntry(Base):
    """lex 权威账本条目。

    - unit：条目所属计量单位（grant 月费条目 unit 为 NULL——与单位无关）；
    - quantity：数量（grant 单位条目=含额数量、overage=超额数量，其余可为 0）
    - amount_micro：微元金额，平台应收视角带符号（adjustment 可为负）
    - idempotency_key：全表唯一——同键重放只记一条（结算幂等的兜底约束）
    - sub2api_applied：该笔是否已（或应已）通过 sub2api adjustBalance 执行，
      对账口径以此为准（spec 未列此列，属工程补充，见汇报）
    """

    __tablename__ = "billing_ledger_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("billing_customers.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(16), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: 微元金额（BigInteger 同 Plan 口径——PG int4 会溢出，SQLite 无感）
    amount_micro: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(191), unique=True, nullable=False)
    source_ref: Mapped[str | None] = mapped_column(String(191))
    sub2api_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )

    customer: Mapped[Customer] = relationship()


class NoticeKind(str, enum.Enum):
    USAGE_WARNING = "usage_warning"


#: 预警渠道（spec：mail+inapp；实际投递由通知通道消费 NoticeRecord 行）
NOTICE_CHANNELS = "mail+inapp"


class NoticeRecord(Base):
    """预警/通知留档：同客户同周期同单位同档位只发一次（唯一约束兜底）。"""

    __tablename__ = "billing_notices"
    __table_args__ = (
        UniqueConstraint(
            "customer_id", "period", "kind", "threshold_pct", "unit",
            name="uq_notice_once_per_tier",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(
        ForeignKey("billing_customers.id"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(
        String(32), nullable=False, default=NoticeKind.USAGE_WARNING.value
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    threshold_pct: Mapped[int] = mapped_column(Integer, nullable=False)  # 80 / 95
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="line")
    channels: Mapped[str] = mapped_column(String(32), nullable=False, default=NOTICE_CHANNELS)
    payload_json: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
