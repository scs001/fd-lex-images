"""计量入账驱动：周期「审计摄取 → 闭月结算」双段循环（消费链生产形态）。

（照 fd-wire metering/driver.py 移植；lex 适配=server 白名单经消费器内建。）

链路此前只有手动触发（``POST /internal/metering/consume`` 与结算端点的
人工调用），生产无人开闸——本模块把它挂上 lifespan 调度。

每轮 tick 两段串行、独立幂等，前段失败不阻断后段：

1. **poll**：registry Mongo 直读一批 ``mcp_server_access`` 事件（lex 计费域
   白名单内）→ 规范化 → 幂等落库（水位 + 重叠窗；``REGISTRY_MONGO_URI``
   未配置时静默跳过，HTTP 推送路径喂同一张表）。
2. **settle**：已关闭月份（上一自然月）整月聚合域（``YYYY-MM``）→ 套餐额度
   → 超额 → sub2api adjustBalance 幂等扣减（settle 键一月一键，首笔落账后
   重放零调用零新增）。**只结闭月，不结当月**：整月聚合域的幂等键在首笔
   入账即固化，月内增量重放不再扣——当月消费由预检余额门（402）与两档
   预警兜底（后置结算+周期核对，design D8 预案），月初首个 tick 自然结算
   上月。``SUB2API_ADMIN_KEY`` 未配置时跳过并告警——部署面必须配齐才开闸。

环境变量：

- ``METERING_DRIVER_ENABLED``：默认 false（生产部署显式开闸）。
- ``METERING_DRIVER_INTERVAL_SECONDS``：tick 间隔，默认 300。
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from ..billing.metering_source import SqlMeteringSource
from ..billing.settle import SettlementService
from ..billing.sub2api import Sub2ApiClient
from ..config import get_settings
from .audit_consumer import MongoAuditSource, consume_once
from .db import get_engine, get_session

logger = logging.getLogger(__name__)

_task: asyncio.Task[None] | None = None


def _closed_period(now: datetime | None = None) -> str:
    """结算聚合域：上一个**已关闭**的自然月（``YYYY-MM``）。

    整月聚合域的 settle 键一月一键：首笔入账后同月重放被账本短路，月内
    增量不再扣——所以只结闭月。月初 rollover 后的首个 tick 结算上月，
    之后的 tick 幂等空转。
    """
    moment = now or datetime.now(timezone.utc)
    first_of_month = datetime(moment.year, moment.month, 1, tzinfo=moment.tzinfo or timezone.utc)
    return (first_of_month - timedelta(days=1)).strftime("%Y-%m")


def _poll_once(source: Any | None) -> dict[str, int] | None:
    """一段：审计摄取。返回落库计数；未配置返回 None。

    异常由 tick 捕获记日志（下轮水位重叠窗兜底重拉）。
    """
    settings = get_settings()
    configured = bool(settings.registry_mongo_uri and settings.registry_mongo_db)
    if source is None and not configured:
        return None
    session = get_session()
    try:
        result = consume_once(session, source or MongoAuditSource())
        session.commit()
        return {
            "fetched": result.fetched,
            "accepted": result.ingest.accepted,
            "duplicates": result.ingest.duplicates,
            "anomalies": result.ingest.anomalies,
            "skipped": result.ingest.skipped,
        }
    finally:
        session.close()


def _settle_once(sub2api: Sub2ApiClient | None, now: datetime | None) -> dict[str, Any] | None:
    """二段：闭月结算入账。返回摘要；sub2api 未配置返回 None。"""
    settings = get_settings()
    if sub2api is None and not settings.sub2api_admin_key:
        logger.warning("settle 段跳过：SUB2API_ADMIN_KEY 未配置（入账未开闸）")
        return None
    session = get_session()
    try:
        service = SettlementService(
            session, sub2api or Sub2ApiClient(), SqlMeteringSource(get_engine())
        )
        report = service.settle(_closed_period(now))
        return {
            "period": report.period,
            "ok": not report.failures,
            "customers": len(report.results),
            "failures": len(report.failures),
        }
    finally:
        session.close()


def tick_once(
    *,
    source: Any | None = None,
    sub2api: Sub2ApiClient | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """一轮完整入账（测试可注入假 source / 假 sub2api / 固定时刻）。

    两段各自 try：一段崩了只记日志，另一段照常——审计摄取与结算是
    两个幂等域，不存在半账状态（settle 的失败自愈靠幂等键重放）。
    """
    outcome: dict[str, Any] = {"polled": None, "settled": None}
    try:
        outcome["polled"] = _poll_once(source)
    except Exception:  # noqa: BLE001 - 摄取失败不阻断结算，下轮重叠窗重拉
        logger.exception("metering poll 段失败；下一轮重试")
    try:
        outcome["settled"] = _settle_once(sub2api, now)
    except Exception:  # noqa: BLE001 - 结算失败不动任何账（settle 内部语义）
        logger.exception("metering settle 段失败；下一轮同幂等键重放")
    return outcome


async def _loop() -> None:
    interval = get_settings().metering_driver_interval_seconds
    while True:
        await asyncio.sleep(interval)
        try:
            # tick_once 是阻塞 IO（pymongo + SQLAlchemy + httpx）——下放线程
            await asyncio.to_thread(tick_once)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - 失败只记日志，等下一轮
            logger.exception("metering driver tick crashed; will retry next interval")


def start_metering_driver() -> None:
    """启动入账驱动循环（幂等；需在事件循环内；METERING_DRIVER_ENABLED=false 关闭）。"""
    global _task
    if not get_settings().metering_driver_enabled:
        logger.info("metering driver disabled by settings")
        return
    if _task is not None and not _task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("no running event loop; metering driver not started")
        return
    _task = loop.create_task(_loop())
    logger.info(
        "metering driver started (interval=%ss)",
        get_settings().metering_driver_interval_seconds,
    )


def stop_metering_driver() -> None:
    global _task
    if _task is not None and not _task.done():
        _task.cancel()
    _task = None
