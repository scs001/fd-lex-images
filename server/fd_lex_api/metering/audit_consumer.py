"""audit 流消费器抽象 + registry Mongo 实现骨架。

（照 fd-wire metering/registry_poller.py 移植；lex 适配=消费器以
``AuditEventSource`` 协议抽象，便于测试注入内存假实现。）

协议：``fetch(since, limit) -> list[dict]``——按事件时间升序拉取
``log_type == "mcp_server_access"`` 的原始事件。实现：

- ``MongoAuditSource``：registry Mongo audit_events 直读（生产路径骨架；
  pymongo 惰性导入，未配置/未安装时不可用）
- ``InMemoryAuditSource``：测试/演练用内存假实现

水位取库内已知最大事件时间（records ∪ anomalies），消费带可配置重叠窗，
幂等键（request_id + server_name）保证重叠不双记。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from .db import to_utc
from .ingest import IngestResult, ingest_events
from .models import MeteringAnomaly, MeteringRecord

#: 重叠窗：水位回看的余量，容忍 registry 侧乱序写入
DEFAULT_OVERLAP = timedelta(minutes=5)

#: 只消费 MCP 工具调用审计流
AUDIT_LOG_TYPE = "mcp_server_access"


class AuditEventSource(Protocol):
    """audit 流消费抽象：按 (水位, 批量上限) 拉取原始事件。"""

    def fetch(self, since: datetime | None, limit: int) -> list[dict[str, Any]]:
        ...  # pragma: no cover - 协议声明


class InMemoryAuditSource:
    """测试/演练用：内存事件列表，模拟服务端按时间升序过滤。"""

    def __init__(self, events: list[dict[str, Any]] | None = None) -> None:
        self.events: list[dict[str, Any]] = list(events or [])
        self.fetch_calls: list[tuple[datetime | None, int]] = []

    def fetch(self, since: datetime | None, limit: int) -> list[dict[str, Any]]:
        self.fetch_calls.append((since, limit))
        selected: list[dict[str, Any]] = []
        for event in self.events:
            if since is not None:
                ts = self._event_time(event)
                if ts is None or ts <= since:
                    continue
            selected.append(event)
        selected.sort(key=self._event_time)
        return selected[: max(0, limit)]

    @staticmethod
    def _event_time(event: dict[str, Any]) -> datetime | None:
        raw = event.get("timestamp")
        if isinstance(raw, datetime):
            return to_utc(raw)
        try:
            return to_utc(datetime.fromisoformat(str(raw).replace("Z", "+00:00")))
        except (TypeError, ValueError):
            return None


class MongoAuditSource:
    """registry Mongo audit_events 直读（生产骨架；惰性连接）。"""

    def __init__(self, collection: Any | None = None) -> None:
        self._collection = collection  # None = 惰性按 env 连接
        self._own_connection = collection is None

    def _ensure_collection(self) -> Any:
        if self._collection is None:
            self._collection = connect_collection()
        return self._collection

    def fetch(self, since: datetime | None, limit: int) -> list[dict[str, Any]]:
        collection = self._ensure_collection()
        query: dict[str, Any] = {"log_type": AUDIT_LOG_TYPE}
        allowlist = get_settings().metering_server_allowlist_set()
        if allowlist:
            # lex 计费域白名单：审计流是全舰队共享的（wire/facet/… 也在流里），
            # 不过滤会把别线流量吸进 lex 计量表。服务端侧过滤（$in）省流量。
            query["mcp_server.name"] = {"$in": sorted(allowlist)}
        if since is not None:
            # 实测（2026-10-06 首客开户演练）：audit_events_default.timestamp 为
            # BSON date（naive UTC）。曾因 json 序列化引号误判为字符串并改成
            # strftime 过滤——实测字符串 $gt 命中 0 条（BSON 类型序里 date 排
            # 字符串之前），此处必须用 datetime 过滤。
            query["timestamp"] = {"$gt": since}
        cursor = collection.find(query, sort=[("timestamp", 1)], limit=limit)
        return list(cursor)

    def close(self) -> None:
        # 惰性连接由 MongoClient 自管；骨架期无长连接要显式释放。
        return None


def connect_collection() -> Any:
    """按 env 建立 Mongo 连接并返回审计集合；未配置/未安装时抛错。"""
    settings = get_settings()
    if not settings.registry_mongo_uri or not settings.registry_mongo_db:
        raise RuntimeError(
            "registry Mongo 直读未配置（需要 REGISTRY_MONGO_URI 与 REGISTRY_MONGO_DB）"
        )
    try:
        from pymongo import MongoClient
    except ImportError as exc:  # pragma: no cover - 依赖缺失路径
        raise RuntimeError("pymongo 未安装（可选依赖）") from exc
    client: Any = MongoClient(settings.registry_mongo_uri)
    return client[settings.registry_mongo_db][settings.registry_mongo_collection]


def _watermark(db: Session) -> datetime | None:
    """库内已知最大事件时间（计量记录与异常留痕取大者）。

    sqlite 的 ``func.max`` 可能按存储串返回，这里统一折算为 aware UTC
    datetime，供 Mongo ``$gt`` 查询使用。
    """

    def _coerce(value: Any) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            return to_utc(value)
        try:
            return to_utc(
                datetime.fromisoformat(str(value).replace(" ", "T").replace("Z", "+00:00"))
            )
        except ValueError:
            return None

    record_max = _coerce(db.execute(select(func.max(MeteringRecord.event_timestamp))).scalar())
    anomaly_max = _coerce(db.execute(select(func.max(MeteringAnomaly.event_timestamp))).scalar())
    values = [v for v in (record_max, anomaly_max) if v is not None]
    return max(values) if values else None


@dataclass(slots=True)
class ConsumeResult:
    """一轮消费的结果：拉取条数 + 摄取计数。"""

    fetched: int
    ingest: IngestResult

    def as_dict(self) -> dict[str, Any]:
        payload = self.ingest.as_dict()
        payload["fetched"] = self.fetched
        return payload


def consume_once(
    db: Session,
    source: AuditEventSource,
    *,
    overlap: timedelta = DEFAULT_OVERLAP,
    limit: int | None = None,
) -> ConsumeResult:
    """执行一轮「拉取 → 规范化 → 幂等落库」；调用方负责 commit。

    水位 = 库内最大事件时间，回看 overlap 窗；批量上限缺省取
    ``METERING_POLL_LIMIT``。
    """
    settings = get_settings()
    batch_limit = limit if limit is not None else settings.metering_poll_limit

    watermark = _watermark(db)
    since: datetime | None = None
    if watermark is not None and overlap.total_seconds() > 0:
        since = to_utc(watermark) - overlap

    batch = source.fetch(since, batch_limit)
    # audit 流不含用量戳：以「成功 tools/call 每次计 1」口径入账（行/次戳
    # 若未来入流仍优先，见 normalize_event 文档串）。
    ingest = ingest_events(db, batch, assume_tool_call=True)
    return ConsumeResult(fetched=len(batch), ingest=ingest)
