"""sub2api admin 客户端：客户代建 / 读取 / 幂等余额调整 / 余额探针。

（照 fd-wire billing/sub2api.py 移植后按生产实测契约修正——2026-10-06 首次
客户开户演练时发现移植版路径/鉴权/envelope 全错，在此一处改正并留实证。）

对外部服务只走显式 HTTP 契约（借用契约纪律）：
- base 可被 SUB2API_BASE 覆盖（config.settings.sub2api_base 同名映射）
- admin key 读 SUB2API_ADMIN_KEY，走 **x-api-key** 头（非 Bearer）
- 写操作带 Idempotency-Key 头（服务端对 balance 更新有幂等缓存；
  create 面忽略该头，重复建户由 find_user_by_email 前置消解）

生产实测契约（2026-10-06 直连 router.finddatatech.cloud 探针实证）：
- POST {base}/api/v1/admin/users                              # createUser
  体 {email*, password*(≥6), username?, notes?, balance?, ...}；email 必填唯一
- GET  {base}/api/v1/admin/users/{id}                         # readUser
- GET  {base}/api/v1/admin/users?search=&page=&page_size=     # listUsers（data.items）
- POST {base}/api/v1/admin/users/{id}/balance                 # updateBalance
  体 {balance*>0, operation: set|add|subtract, notes?}；响应/读取的 balance 数值
  与写入**同一单位、无换算**（实测：写 15 读 15）——lex 侧约定该数值即微元。
- DELETE {base}/api/v1/admin/users/{id}                       # deleteUser（演练清理）

响应一律枚举成功 envelope ``{code:0, message, data}``；``code != 0`` 即失败
（HTTP 状态可能与业务码不同，两者都要看）。所有外部 HTTP 依赖在测试中经
httpx.MockTransport mock（生产共享设施，测试绝不真实调用）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from ..config import get_settings

#: 新建账户的初始密码长度下限由服务端约束（min=6）；面板登录走 Logto SSO，
#: 密码仅为满足建户契约、不在此留存。
MIN_PASSWORD_LENGTH = 6


class Sub2ApiError(Exception):
    """sub2api 返回非 2xx 或响应不合契约。"""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class Sub2ApiUnavailable(Sub2ApiError):
    """计费面不可达（网络/5xx）——预检 fail-closed 语义由此表达。"""


@dataclass(frozen=True)
class Sub2User:
    id: str
    name: str
    balance_micro: int
    email: str = ""
    status: str = ""


@dataclass(frozen=True)
class ProbeResult:
    """余额探针结果：不可达时 sufficient 恒为 False（fail-closed）。"""

    user_id: str
    reachable: bool
    balance_micro: int | None = None
    min_balance_micro: int = 0
    error: str | None = None

    @property
    def sufficient(self) -> bool:
        if not self.reachable or self.balance_micro is None:
            return False
        return self.balance_micro >= self.min_balance_micro


def _balance_to_micro(raw: Any) -> int:
    """余额字段 → 整数微元：数值单位与写入一致、无换算（实测契约）。

    兼容 float/字符串形态（服务端 float64 可能带小数），仍按微元取整。
    """
    if raw is None:
        raise Sub2ApiError("sub2api 响应缺余额字段")
    if isinstance(raw, bool):
        raise Sub2ApiError(f"余额字段类型非法: {raw!r}")
    try:
        return int(round(float(raw)))
    except (TypeError, ValueError) as exc:
        raise Sub2ApiError(f"余额字段解析失败: {raw!r}") from exc


def parse_user(payload: dict[str, Any]) -> Sub2User:
    """容错解析用户对象：接受平铺或 {"user": {...}} 包裹。"""
    body = payload.get("user", payload) if isinstance(payload, dict) else None
    if not isinstance(body, dict) or "id" not in body:
        raise Sub2ApiError(f"sub2api 用户响应不合契约: {payload!r}")
    raw_balance = body.get("balance_micro", body.get("balance", 0))
    return Sub2User(
        id=str(body["id"]),
        name=str(body.get("username") or body.get("name") or ""),
        balance_micro=_balance_to_micro(raw_balance),
        email=str(body.get("email") or ""),
        status=str(body.get("status") or ""),
    )


class Sub2ApiClient:
    """sub2api 计费面 admin 客户端（线程不共享实例；用完 close 或 with）。"""

    def __init__(
        self,
        base_url: str | None = None,
        admin_key: str | None = None,
        *,
        http_client: httpx.Client | None = None,
        timeout: float = 10.0,
    ) -> None:
        self._base = (
            base_url or get_settings().sub2api_base
        ).rstrip("/")
        self._admin_key = (
            admin_key if admin_key is not None else get_settings().sub2api_admin_key
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout)

    # -- 基础设施 -----------------------------------------------------------

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {"x-api-key": self._admin_key}
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _request(self, method: str, url: str, *, json_body: dict | None = None,
                 params: dict | None = None,
                 idempotency_key: str | None = None) -> Any:
        try:
            resp = self._http.request(
                method, url, json=json_body, params=params,
                headers=self._headers(idempotency_key),
            )
        except httpx.HTTPError as exc:
            raise Sub2ApiUnavailable(f"sub2api 不可达: {exc}") from exc
        if resp.status_code >= 500:
            raise Sub2ApiUnavailable(f"sub2api 5xx: {resp.status_code}", resp.status_code)
        try:
            doc = resp.json()
        except ValueError as exc:
            if resp.status_code >= 400:
                raise Sub2ApiError(
                    f"sub2api {resp.status_code}: {resp.text[:200]}", resp.status_code
                ) from exc
            raise Sub2ApiError(f"sub2api 响应非 JSON: {resp.text[:200]!r}") from exc
        # 业务码：envelope {code:0,message,data}；code != 0 即失败。
        if isinstance(doc, dict) and "code" in doc and doc.get("code") not in (0, None):
            message = str(doc.get("message") or doc.get("code"))
            status = resp.status_code if resp.status_code >= 400 else None
            raise Sub2ApiError(f"sub2api 业务错误: {message}", status)
        if resp.status_code >= 400:
            raise Sub2ApiError(f"sub2api {resp.status_code}: {resp.text[:200]}", resp.status_code)
        if isinstance(doc, dict) and "data" in doc:
            return doc["data"]
        return doc

    def close(self) -> None:
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> "Sub2ApiClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- 方法面 --------------------------------------------------------------

    def create_user(
        self,
        *,
        email: str,
        password: str,
        username: str | None = None,
        notes: str | None = None,
        initial_balance_micro: int | None = None,
        idempotency_key: str | None = None,
    ) -> Sub2User:
        """createUser：email 必填唯一、password ≥6；服务端 create 面无幂等头，
        重复建户由调用方（ensure_customer 的 email 前置查询）消解。"""
        if len(password) < MIN_PASSWORD_LENGTH:
            raise ValueError(f"password 至少 {MIN_PASSWORD_LENGTH} 位（sub2api 约束）")
        body: dict[str, Any] = {"email": email, "password": password}
        if username:
            body["username"] = username
        if notes:
            body["notes"] = notes
        if initial_balance_micro is not None:
            body["balance"] = initial_balance_micro
        return parse_user(
            self._request(
                "POST",
                f"{self._base}/api/v1/admin/users",
                json_body=body,
                idempotency_key=idempotency_key,
            )
        )

    def list_users(self, search: str, *, page: int = 1, page_size: int = 50) -> list[dict[str, Any]]:
        """listUsers（search 命中 email/username/notes 及 key 值子串）。"""
        data = self._request(
            "GET",
            f"{self._base}/api/v1/admin/users",
            params={"search": search, "page": page, "page_size": page_size},
        )
        items = data.get("items") if isinstance(data, dict) else None
        return list(items or [])

    def find_user_by_email(self, email: str) -> Sub2User | None:
        """按 email 精确命中：命中即返回，否则 None（开户幂等的前置消解）。"""
        for item in self.list_users(email):
            if str(item.get("email") or "").lower() == email.lower():
                return parse_user(item)
        return None

    def read_user(self, user_id: str) -> Sub2User:
        """readUser：余额快照（对账消费）。"""
        payload = self._request("GET", f"{self._base}/api/v1/admin/users/{user_id}")
        return parse_user(payload)

    def adjust_balance(self, *, user_id: str, amount_micro: int,
                       idempotency_key: str) -> Sub2User:
        """updateBalance：微元带符号（负=扣减→operation subtract）。

        契约要求 balance>0 + operation∈{set,add,subtract}；符号折进 operation，
        数值发绝对值；Idempotency-Key 幂等（服务端缓存）。
        """
        if not idempotency_key:
            raise ValueError("adjust_balance 必须显式传 idempotency_key")
        amount = int(amount_micro)
        if amount == 0:
            raise ValueError("adjust_balance 金额不能为 0（契约 balance>0）")
        body = {
            "balance": abs(amount),
            "operation": "add" if amount > 0 else "subtract",
        }
        return parse_user(
            self._request(
                "POST",
                f"{self._base}/api/v1/admin/users/{user_id}/balance",
                json_body=body,
                idempotency_key=idempotency_key,
            )
        )

    def probe(self, user_id: str, *, min_balance_micro: int = 0) -> ProbeResult:
        """余额探针：不可达/报错→reachable=False 且 sufficient=False（fail-closed）。"""
        try:
            user = self.read_user(user_id)
        except Sub2ApiError as exc:
            return ProbeResult(
                user_id=user_id,
                reachable=False,
                min_balance_micro=min_balance_micro,
                error=str(exc),
            )
        return ProbeResult(
            user_id=user_id,
            reachable=True,
            balance_micro=user.balance_micro,
            min_balance_micro=min_balance_micro,
        )