"""规范化层：registry 审计事件（MCPServerAccessRecord 形状）→ 双单位计量字段。

（照 fd-wire metering/normalize.py 移植，lex 适配=双单位戳判定。）

registry 审计事件关键字段：``timestamp`` / ``request_id`` / ``identity`` /
``mcp_server`` / ``mcp_request`` / ``mcp_response``。

用量戳由 business-mcp / 生成类工具在响应里盖，registry 透传时可能落在
多个位置，本层按候选路径逐个提取：

- ``rows_returned``（行数戳，读取/检索类）→ unit=line
- ``calls_used``（次数戳，生成/评测类）→ unit=call
- 两者皆缺 → 分类为缺戳异常（不静默）；两者皆有 → 行数戳优先（读取类
  响应不应盖次数戳，此为防御性约定）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..config import get_settings
from .db import to_utc
from .models import TRACK_CUSTOMER, TRACK_PLATFORM

#: 缺用量戳异常分类
REASON_MISSING_STAMP = "missing_usage_stamp"
#: 结构不可解析（缺 request_id/timestamp/server 等必备件）
REASON_UNPARSABLE = "unparseable_event"

#: 行数戳候选提取路径（按优先级；registry 版本演进时在此追加）
_ROWS_PATHS: tuple[tuple[str, ...], ...] = (
    ("rows_returned",),
    ("mcp_response", "rows_returned"),
    ("mcp_response", "meta", "rows_returned"),
    ("mcp_response", "result", "rows_returned"),
    ("mcp_response", "result", "meta", "rows_returned"),
)

#: 次数戳候选提取路径（生成/评测类工具盖 calls_used）
_CALLS_PATHS: tuple[tuple[str, ...], ...] = (
    ("calls_used",),
    ("mcp_response", "calls_used"),
    ("mcp_response", "meta", "calls_used"),
    ("mcp_response", "result", "calls_used"),
    ("mcp_response", "result", "meta", "calls_used"),
)


def _extract_stamp(event: dict[str, Any], paths: tuple[tuple[str, ...], ...]) -> int | None:
    """按候选路径提取非负整数戳；不存在或非法返回 None。"""
    for path in paths:
        node: Any = event
        for key in path:
            if not isinstance(node, dict) or key not in node:
                node = None
                break
            node = node[key]
        if node is None:
            continue
        try:
            value = int(node)
        except (TypeError, ValueError):
            continue
        if value >= 0:
            return value
    return None


def extract_rows_returned(event: dict[str, Any]) -> int | None:
    """从原始事件提取 rows_returned；不存在或非负整数要求不满足返回 None。"""
    return _extract_stamp(event, _ROWS_PATHS)


def extract_calls_used(event: dict[str, Any]) -> int | None:
    """从原始事件提取 calls_used；不存在或非负整数要求不满足返回 None。"""
    return _extract_stamp(event, _CALLS_PATHS)


# ---------------------------------------------------------------------------
# 宽松输入模型：未知字段放行（audit schema 演进不炸摄取）
# ---------------------------------------------------------------------------


class _IdentityIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    username: str = "anonymous"
    principal_name: str | None = None
    auth_method: str | None = None


class _McpServerIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    path: str | None = None


class _McpRequestIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    method: str | None = None
    tool_name: str | None = None


class AuditEventIn(BaseModel):
    """MCPServerAccessRecord 的宽松投影；规范化只依赖这些字段。"""

    model_config = ConfigDict(extra="allow")

    timestamp: datetime | None = None
    request_id: str | None = None
    identity: _IdentityIn | None = None
    mcp_server: _McpServerIn | None = None
    mcp_request: _McpRequestIn | None = None
    mcp_response: dict[str, Any] | None = None
    request: dict[str, Any] | None = None
    log_type: str | None = Field(default=None)


@dataclass(slots=True)
class NormalizedRecord:
    """可入 ``metering_records`` 的一条规范化计量记录（带单位）。"""

    event_timestamp: datetime
    request_id: str
    caller: str
    caller_principal: str | None
    credential_track: str  # platform | customer
    server_name: str
    server_path: str | None
    tool_name: str | None
    quantity: int
    unit: str  # line | call（token 由未来模型 API 直接写库，零迁移）
    source: str


@dataclass(slots=True)
class SkippedEvent:
    """与计量无关的审计事件（如 registry_api_access/token_mint）：静默跳过，只计数。"""

    log_type: str | None


@dataclass(slots=True)
class NormalizedAnomaly:
    """不可计量的事件：留痕到 ``metering_anomalies``。"""

    reason: str
    request_id: str | None
    server_name: str | None
    tool_name: str | None
    caller: str | None
    credential_track: str | None
    detail: dict[str, Any] = field(default_factory=dict)
    event_timestamp: datetime | None = None


def resolve_credential_track(caller: str, platform_identities: frozenset[str]) -> str:
    """命中平台服务身份名单 → platform，否则 customer（客户/平台双轨标记）。"""
    return TRACK_PLATFORM if caller.lower() in platform_identities else TRACK_CUSTOMER


def resolve_source(credential_track: str) -> str:
    """来源标记：platform 轨=platform-internal；customer 轨=customer。

    （wire 的身份→来源映射表 lex v1 未引入；provenance 细分后续按需追加。）
    """
    return TRACK_CUSTOMER if credential_track == TRACK_CUSTOMER else "platform-internal"


def normalize_event(
    raw: dict[str, Any],
    *,
    assume_tool_call: bool = False,
) -> NormalizedRecord | NormalizedAnomaly | SkippedEvent:
    """单条审计事件 → 计量记录 / 异常留痕 / 跳过（两条摄取入口共用的唯一入口）。

    ``assume_tool_call=True`` = 审计流消费路径的计数口径（2026-10-06 首客
    开户演练实采：registry 审计记录不含 rows/calls 用量戳，只到 status/
    duration）——成功的 ``tools/call`` 以次数入账（每次计 1，unit=call），
    协议流量（initialize/tools/list 等）与失败调用不计费；行/次戳若未来
    入流仍优先（此口径为缺戳时的审计流回退）。``log_type=='mcp_server_access'``
    的事件（审计流形状，消费与推送两入口共有）同样适用该口径；显式自报
    事件（无 log_type）保持「缺戳不静默」。
    """
    settings = get_settings()
    # 仅消费 MCP 工具调用审计流；其余审计类型与逐调用计量无关，跳过不落表。
    log_type = raw.get("log_type") if isinstance(raw, dict) else None
    if log_type is not None and log_type != "mcp_server_access":
        return SkippedEvent(log_type=str(log_type))
    try:
        event = AuditEventIn.model_validate(raw)
    except Exception as exc:  # 结构彻底不合法 → 异常留痕而非丢弃
        return NormalizedAnomaly(
            reason=REASON_UNPARSABLE,
            request_id=str(raw.get("request_id")) if isinstance(raw, dict) else None,
            server_name=None,
            tool_name=None,
            caller=None,
            credential_track=None,
            detail={"error": f"schema validation failed: {exc}"},
        )

    request_id = (event.request_id or "").strip()
    server_name = (event.mcp_server.name if event.mcp_server else "") or ""
    timestamp = to_utc(event.timestamp) if event.timestamp else None

    # 必备件缺失：无法定位幂等键/时间，无法计量
    if not request_id or not server_name or timestamp is None:
        return NormalizedAnomaly(
            reason=REASON_UNPARSABLE,
            request_id=request_id or None,
            server_name=server_name or None,
            tool_name=event.mcp_request.tool_name if event.mcp_request else None,
            caller=event.identity.username if event.identity else None,
            credential_track=None,
            detail={
                "missing": [
                    name
                    for name, value in (
                        ("request_id", request_id),
                        ("mcp_server.name", server_name),
                        ("timestamp", timestamp),
                    )
                    if not value
                ]
            },
            event_timestamp=timestamp,
        )

    caller = event.identity.username if event.identity else "anonymous"
    track = resolve_credential_track(caller, settings.platform_identity_set())
    tool_name = event.mcp_request.tool_name if event.mcp_request else None

    # 双单位判定：行数戳优先（读取/检索类），其次次数戳（生成/评测类）；
    # 皆缺时按消费路径分流（详见 normalize_event 文档串）。
    rows = extract_rows_returned(raw)
    calls = extract_calls_used(raw)
    quantity: int | None = None
    unit: str | None = None
    if rows is not None:
        quantity, unit = rows, "line"
    elif calls is not None:
        quantity, unit = calls, "call"
    elif assume_tool_call or log_type == "mcp_server_access":
        # 审计流形状的事件（无论走消费还是推送入口）都用审计流口径：
        # 该流不携带用量戳（其 mcp_response 只到 status/duration），成功
        # tools/call 每次计 1；显式自报事件（无 log_type）仍走缺戳异常。
        method = event.mcp_request.method if event.mcp_request else None
        status = str((event.mcp_response or {}).get("status") or "")
        if method == "tools/call" and status == "success":
            quantity, unit = 1, "call"  # 审计流计数口径：成功调用每次计 1
        elif method:
            # 协议流量（initialize/tools/list/…）与失败调用不计费，静默跳过
            return SkippedEvent(log_type=str(log_type) if log_type is not None else None)
    if quantity is None or unit is None:
        response = event.mcp_response or {}
        return NormalizedAnomaly(
            reason=REASON_MISSING_STAMP,
            request_id=request_id,
            server_name=server_name,
            tool_name=tool_name,
            caller=caller,
            credential_track=track,
            detail={
                "mcp_response_status": response.get("status"),
                "mcp_response_error_code": response.get("error_code"),
                "method": event.mcp_request.method if event.mcp_request else None,
                "searched_paths": (
                    [".".join(p) for p in _ROWS_PATHS]
                    + [".".join(p) for p in _CALLS_PATHS]
                ),
            },
            event_timestamp=timestamp,
        )

    return NormalizedRecord(
        event_timestamp=timestamp,
        request_id=request_id,
        caller=caller,
        caller_principal=event.identity.principal_name if event.identity else None,
        credential_track=track,
        server_name=server_name,
        server_path=event.mcp_server.path if event.mcp_server else None,
        tool_name=tool_name,
        quantity=quantity,
        unit=unit,
        source=resolve_source(track),
    )
