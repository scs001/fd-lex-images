"""与 metering 模块的共享读取契约（耦合点，5.1 ↔ 5.2 接口）。

`metering_records` 表归 metering 模块所有（ORM：
``fd_lex_api.metering.models.MeteringRecord``），billing 只读——本侧用
独立 MetaData 的只读 Table 定义，billing 的 create_all/迁移不碰它。

真实表的关键列与计费口径：

- ``caller``：调用者身份（identity.username）——结算聚合的「客户身份映射」
  键，billing 侧由 resolver 映射到 Customer（v1 暂用 sub2api_user_id 承载
  该映射，正式的 Logto username ↔ Customer 映射落地前可注入自定义 resolver）
- ``event_timestamp``：period（YYYY-MM）由其派生。**方言适配（2026-10-12
  接客 PG 迁移）**：SQLite 用 ``strftime('%Y-%m')``、PostgreSQL 用
  ``to_char(..., 'YYYY-MM')``——按 engine.dialect.name 分支，测试（sqlite）
  与生产（PG）同源同语义。
- ``credential_track``：'customer' 才计费（platform=平台服务凭据归集，
  不进客户账单）
- ``quantity`` × ``unit``：双单位计费唯一依据（line=行、call=次、token 预留）

真实表没有批次（batch_ref）列：SqlMeteringSource 只支持整月聚合域
（batch_ref=None）。MeteringSource 协议保留 batch_ref 供增量/水位线实现
（StaticMeteringSource 等），批次切分收敛前勿对真实表按批结算。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    func,
    select,
)
from sqlalchemy.engine import Engine

#: metering_records 的只读表定义（列类型与 metering.models.MeteringRecord
#: 对齐——那侧改表须同步这里）
metering_records = Table(
    "metering_records",
    MetaData(),
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("event_timestamp", DateTime(timezone=True), nullable=False),
    Column("request_id", String(200), nullable=False),
    Column("caller", String(255), nullable=False, default="anonymous"),
    Column("credential_track", String(16), nullable=False),
    Column("server_name", String(255), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit", String(16), nullable=False),
    Column("source", String(32), nullable=False),
)

#: 测试/临时环境建同构表用的 DDL（列与 metering 侧模型对齐）
METERING_RECORDS_DDL = """
CREATE TABLE IF NOT EXISTS metering_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_timestamp TIMESTAMP NOT NULL,
    request_id VARCHAR(200) NOT NULL,
    caller VARCHAR(255) NOT NULL DEFAULT 'anonymous',
    caller_principal VARCHAR(255),
    credential_track VARCHAR(16) NOT NULL,
    server_name VARCHAR(255) NOT NULL,
    server_path VARCHAR(512),
    tool_name VARCHAR(255),
    quantity INTEGER NOT NULL,
    unit VARCHAR(16) NOT NULL,
    source VARCHAR(32) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_metering_request_server UNIQUE (request_id, server_name)
)
"""

CUSTOMER_TRACK = "customer"
PLATFORM_TRACK = "platform"


@dataclass(frozen=True)
class MeteringUsage:
    """单客户单单位在一个聚合域内的计费数量（customer_ref=caller 身份键）。"""

    customer_ref: str
    unit: str
    quantity: int


class MeteringSource(Protocol):
    """结算的计量读取接口：按 (客户身份, unit, period[, batch_ref]) 聚合。"""

    def aggregates(self, period: str, batch_ref: str | None = None) -> list[MeteringUsage]:
        ...  # pragma: no cover - 协议声明


class StaticMeteringSource:
    """测试/演练用：直接给定聚合结果（batch_ref 语义由调用方自证）。"""

    def __init__(self, usages: list[MeteringUsage]) -> None:
        self._usages = usages

    def aggregates(self, period: str, batch_ref: str | None = None) -> list[MeteringUsage]:
        return list(self._usages)


class SqlMeteringSource:
    """从真实 metering_records 表读聚合：只客户凭据轨、period 派生自时间戳、
    按 (caller, unit) 分组求和。"""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def aggregates(self, period: str, batch_ref: str | None = None) -> list[MeteringUsage]:
        if batch_ref is not None:
            raise ValueError(
                "真实 metering_records 无批次列：请按整月聚合域结算（batch_ref=None）；"
                "增量批次需水位线机制，由主代理收敛"
            )
        stmt = (
            select(
                metering_records.c.caller.label("customer_ref"),
                metering_records.c.unit.label("unit"),
                func.sum(metering_records.c.quantity).label("quantity"),
            )
            .where(
                metering_records.c.credential_track == CUSTOMER_TRACK,
                _period_expr(self._engine) == period,
            )
            .group_by(metering_records.c.caller, metering_records.c.unit)
        )
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).all()
        return [
            MeteringUsage(customer_ref=r.customer_ref, unit=r.unit, quantity=int(r.quantity))
            for r in rows
        ]


def _period_expr(engine: Engine):
    """period（YYYY-MM）提取表达式，按方言分支（sqlite 测试 / PG 生产）。

    PG 的 ``to_char`` 需显式时区——event_timestamp 为 timestamptz，直接
    to_char 会按会话 TimeZone 渲染，跨时区边界月错位；先 AT TIME ZONE 'UTC'
    固定为 UTC 月（与 sqlite strftime 的 naive-UTC 语义对齐）。
    """
    column = metering_records.c.event_timestamp
    if engine.dialect.name == "postgresql":
        return func.to_char(func.timezone("UTC", column), "YYYY-MM")
    return func.strftime("%Y-%m", column)
