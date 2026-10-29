"""计费/计量测试共享设施（非 conftest，避免与并行代理争 tests/conftest.py——
沿用 fd-wire 同款纪律）。

FakeSub2Api 用 httpx.MockTransport 承载，并模拟服务端 Idempotency-Key
幂等缓存——「同键重放只扣一次」的净效果直接在其余额上可断言。
绝不真实调用 sub2api（生产共享设施，测试期不许产生脏数据）。
"""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from fd_lex_api.billing import METERING_RECORDS_DDL, Base, Customer, Plan
from fd_lex_api.billing.models import PlanQuota
from fd_lex_api.metering.db import MeteringBase
from fd_lex_api.billing.sub2api import Sub2ApiClient

BASE = "http://sub2api.test"


def make_engine():
    """内存库：billing_* + metering_* + console_* 全部建表（静态池共享连接）。

    console_* 表随结算 resolver（绑定表优先）一起成为共用依赖——
    与生产 main.py 的 create_all 范围一致。
    """
    from fd_lex_api.console_api.models import ConsoleBase

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    MeteringBase.metadata.create_all(engine)
    ConsoleBase.metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text(METERING_RECORDS_DDL))
    return engine


def make_plan(
    session: Session,
    *,
    code: str = "standard",
    name: str = "标准版",
    monthly_price_micro: int = 0,
    quotas: list[dict] | None = None,
) -> Plan:
    """建套餐 + 按单位配额（测试夹具；生产走后台配置）。"""
    plan = Plan(code=code, name=name, monthly_price_micro=monthly_price_micro)
    session.add(plan)
    session.flush()
    for q in quotas or []:
        session.add(
            PlanQuota(
                plan_id=plan.id,
                unit=q["unit"],
                included_quantity=q.get("included_quantity", 0),
                overage_unit_price_micro=q.get("overage_unit_price_micro", 0),
            )
        )
    session.flush()
    return plan


def add_customer(
    session: Session,
    *,
    name: str,
    plan_id: int,
    sub2api_user_id: str,
    status: str = "active",
) -> Customer:
    customer = Customer(
        name=name, plan_id=plan_id, sub2api_user_id=sub2api_user_id, status=status
    )
    session.add(customer)
    session.flush()
    return customer


def insert_metering(
    engine,
    *,
    customer_ref: str,
    ts: str,
    quantity: int,
    unit: str = "line",
    track: str = "customer",
    request_id: str | None = None,
    server_name: str = "legal-search-mcp",
) -> None:
    """往 metering_records 表塞一行（列结构与 metering 侧模型对齐）。"""
    stmt = (
        "INSERT INTO metering_records "
        "(event_timestamp, request_id, caller, credential_track, server_name, "
        " quantity, unit, source) "
        "VALUES (:ts, :rid, :caller, :track, :server, :qty, :unit, :source)"
    )
    params = {
        "ts": ts,
        "rid": request_id or f"req-{customer_ref}-{ts}-{unit}-{quantity}-{track}",
        "caller": customer_ref,
        "track": track,
        "server": server_name,
        "qty": quantity,
        "unit": unit,
        "source": "customer" if track == "customer" else "platform-internal",
    }
    with engine.begin() as c:
        c.execute(text(stmt), params)


class FakeSub2Api:
    """sub2api admin 面的内存假件（契约照 2026-10-06 生产实测重写）：
    x-api-key 鉴权、envelope {code,message,data}、/api/v1/admin/* 路径、
    balance 更新 {balance>0, operation: set|add|subtract} + Idempotency-Key 去重。"""

    AUTH_KEY = "test-admin-key"

    def __init__(self) -> None:
        self.users: dict[str, dict] = {}
        self.calls: list[dict] = []
        self.idem_cache: dict[str, dict] = {}
        self.fail_adjust_left = 0   # 接下来 N 次 adjust 返回 503
        self.fail_reads_left = 0    # 接下来 N 次 GET 返回 503

    # -- 数据准备 -----------------------------------------------------------

    def add_user(self, user_id: str, *, name: str = "user",
                 balance_micro: int = 0, email: str = "",
                 status: str = "active") -> str:
        self.users[user_id] = {
            "name": name,
            "username": name,
            "email": email or f"{user_id}@test.invalid",
            "balance_micro": balance_micro,
            "status": status,
        }
        return user_id

    @property
    def adjust_calls(self) -> list[dict]:
        return [c for c in self.calls if c["op"] == "POST" and c["url"].endswith("/balance")]

    def balance(self, user_id: str) -> int:
        return self.users[user_id]["balance_micro"]

    def _payload(self, user_id: str) -> dict:
        u = self.users[user_id]
        return {
            "id": int(user_id) if user_id.isdigit() else user_id,
            "email": u.get("email", ""),
            "username": u.get("username") or u.get("name", ""),
            "balance": u["balance_micro"],  # 数值与写入同单位（无换算）
            "status": u.get("status", "active"),
        }

    @staticmethod
    def _ok(data) -> httpx.Response:  # noqa: ANN001
        return httpx.Response(200, json={"code": 0, "message": "success", "data": data})

    @staticmethod
    def _err(status: int, message: str) -> httpx.Response:
        return httpx.Response(status, json={"code": status, "message": message})

    # -- HTTP 面 ------------------------------------------------------------

    def handler(self, request: httpx.Request) -> httpx.Response:
        op, url, path = request.method, str(request.url), request.url.path
        idem = request.headers.get("Idempotency-Key")
        self.calls.append({"op": op, "url": url, "idem": idem,
                           "auth": request.headers.get("x-api-key"),
                           "body": request.content.decode() if request.content else None})
        if request.headers.get("x-api-key") != self.AUTH_KEY:
            return self._err(401, "Invalid admin API key")

        if op == "GET" and path == "/api/v1/admin/users":  # listUsers(search)
            if self.fail_reads_left > 0:
                self.fail_reads_left -= 1
                return httpx.Response(503, text="billing plane down")
            search = request.url.params.get("search", "").lower()
            items = [
                self._payload(uid) for uid, u in self.users.items()
                if not search
                or search in f"{u.get('email','')} {u.get('username') or u.get('name','')}".lower()
            ]
            return self._ok({"items": items, "total": len(items)})

        if op == "GET" and path.startswith("/api/v1/admin/users/"):  # readUser
            if self.fail_reads_left > 0:
                self.fail_reads_left -= 1
                return httpx.Response(503, text="billing plane down")
            user_id = path.rsplit("/", 1)[-1]
            if user_id not in self.users:
                return self._err(404, "user not found")
            return self._ok(self._payload(user_id))

        if op == "POST" and path == "/api/v1/admin/users":  # createUser
            body = json.loads(request.content or b"{}")
            email = str(body.get("email", ""))
            if any(u.get("email", "").lower() == email.lower() for u in self.users.values()):
                return self._err(400, "email already exists")
            digest = hashlib.sha1(email.encode()).hexdigest()[:8]
            user_id = f"su-{digest}"
            self.users[user_id] = {
                "name": body.get("username") or email,
                "username": body.get("username") or "",
                "email": email,
                "balance_micro": int(body.get("balance", 0) or 0),
                "status": "active",
            }
            return self._ok(self._payload(user_id))

        if op == "POST" and path.endswith("/balance"):  # updateBalance
            if self.fail_adjust_left > 0:
                self.fail_adjust_left -= 1
                return httpx.Response(503, text="adjust boom")
            if idem and idem in self.idem_cache:
                return self._ok(self.idem_cache[idem])
            user_id = path.split("/")[5]
            if user_id not in self.users:
                return self._err(404, "user not found")
            body = json.loads(request.content or b"{}")
            amount = float(body.get("balance", 0))
            operation = body.get("operation")
            if amount <= 0 or operation not in ("set", "add", "subtract"):
                return self._err(400, "Invalid request: balance gt=0, operation oneof set add subtract")
            user = self.users[user_id]
            if operation == "set":
                user["balance_micro"] = int(amount)
            elif operation == "add":
                user["balance_micro"] += int(amount)
            else:
                user["balance_micro"] -= int(amount)
            payload = self._payload(user_id)
            if idem:
                self.idem_cache[idem] = payload
            return self._ok(payload)

        if op == "DELETE" and path.startswith("/api/v1/admin/users/"):  # deleteUser
            user_id = path.rsplit("/", 1)[-1]
            if user_id not in self.users:
                return self._err(404, "user not found")
            self.users.pop(user_id)
            return self._ok({"message": "User deleted successfully"})

        return self._err(404, f"unmatched {op} {url}")

    def client(self) -> Sub2ApiClient:
        return Sub2ApiClient(
            base_url=BASE,
            admin_key="test-admin-key",
            http_client=httpx.Client(transport=httpx.MockTransport(self.handler)),
        )


@pytest.fixture()
def engine():
    return make_engine()


@pytest.fixture()
def fake_sub2api() -> FakeSub2Api:
    return FakeSub2Api()
