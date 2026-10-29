"""registry 凭据面客户端（借调：不改 registry 源码，只走显式 HTTP 契约）。

契约（wire-platform-v1 5.1 已上线，实测于 https://mcp.finddatatech.cloud）：
- ``GET    /api/patch-keys``        列出调用者的凭据（仅元数据，无明文/哈希）
- ``POST   /api/patch-keys``        铸造（body ``{"name": ...}``；明文仅此一次）
- ``DELETE /api/patch-keys/{id}``   吊销（不可逆，下一次调用 401）

鉴权：``Authorization: Bearer <token>``。registry 侧 nginx ``/api/`` 走
auth_request → auth-server ``/validate``；``/validate`` 接受 patch key
（wgk- 前缀，实测）与 Logto JWT（audience ∈ 该 IdP 配置的
client_id/m2m_client_id/m2m_resource）。本服务因此**只透传客户 access
token**，不共享 registry 的 SECRET_KEY、不伪造内部令牌。
无会话 cookie 的请求 CSRF 自动跳过（registry 侧 ``verify_csrf_token_flexible``
对无 cookie 请求不做校验）——跨域 cookie 难题由此绕开。
"""

from __future__ import annotations

from typing import Any

import httpx

from ..config import get_settings


class RegistryUnavailable(RuntimeError):
    """registry 面网络/超时不可达（如实上抛，由路由映射 502）。"""


class RegistryPatchKeyClient:
    """registry patch-keys 的最小客户端（可注入 transport 供测试）。"""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self._base = (base_url or settings.registry_base_url).rstrip("/")
        self._timeout = timeout if timeout is not None else settings.registry_timeout_seconds
        self._transport = transport

    def _request(
        self,
        method: str,
        path: str,
        *,
        token: str,
        json_body: dict[str, Any] | None = None,
    ) -> tuple[int, Any]:
        url = f"{self._base}{path}"
        headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.request(method, url, headers=headers, json=json_body)
        except httpx.HTTPError as exc:
            raise RegistryUnavailable(
                f"registry unreachable at {url}: {type(exc).__name__}: {exc}"
            ) from exc
        try:
            payload: Any = response.json()
        except ValueError:
            payload = {"detail": response.text[:500]}
        return response.status_code, payload

    # -- 契约面 ---------------------------------------------------------------

    def list_keys(self, token: str) -> tuple[int, Any]:
        return self._request("GET", "/api/patch-keys", token=token)

    def mint_key(self, token: str, name: str) -> tuple[int, Any]:
        return self._request("POST", "/api/patch-keys", token=token, json_body={"name": name})

    def revoke_key(self, token: str, key_id: str) -> tuple[int, Any]:
        return self._request(
            "DELETE", f"/api/patch-keys/{key_id}", token=token
        )


def get_registry_client() -> RegistryPatchKeyClient:
    """请求级客户端工厂（测试经 dependency_overrides 换假件）。"""
    return RegistryPatchKeyClient()


__all__ = [
    "RegistryPatchKeyClient",
    "RegistryUnavailable",
    "get_registry_client",
]