"""后台鉴权：内部令牌（X-Admin-Token）或 Logto 管理员角色（Bearer ID token）。

- 令牌路径与 ``/internal/*`` 同款：Bearer/Header 与 ``INTERNAL_API_TOKEN``
  严格相等；未配置令牌即 fail-closed（403），绝不无令牌放行。
- Logto 路径：ID token 本地校验（JWKS/iss/aud）后要求 roles 命中
  ``ADMIN_ROLES``；未命中 403。
- 两条路径都不满足：401（未带凭据）或 403（带了但不够格）。
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from ..config import get_settings
from ..console_api.auth import verify_id_token


@dataclass(frozen=True)
class AdminActor:
    """后台操作者：via = internal-token | logto-role。"""

    via: str
    identity: str
    roles: list[str]

    def as_dict(self) -> dict:
        return {"via": self.via, "identity": self.identity, "roles": self.roles}


def _internal_token_ok(request: Request) -> bool:
    """X-Admin-Token 与 INTERNAL_API_TOKEN 严格相等；未配置一律不通过。"""
    expected = get_settings().internal_api_token
    presented = (request.headers.get("x-admin-token") or "").strip()
    if not presented:
        return False
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="internal api token not configured (admin token path unavailable)",
        )
    return presented == expected


def _bearer(request: Request) -> str | None:
    authorization = request.headers.get("authorization") or ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        return None
    return token.strip()


async def require_admin(request: Request) -> AdminActor:
    """FastAPI 依赖：内部令牌或 Logto 管理员角色，二者其一。"""
    if _internal_token_ok(request):
        return AdminActor(via="internal-token", identity="internal", roles=[])

    token = _bearer(request)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "admin credentials required: send X-Admin-Token (internal) or a "
                "Logto bearer token carrying an admin role"
            ),
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = verify_id_token(token, enforce_organization=False)
    allowed = get_settings().admin_role_set()
    if not user.has_admin_role(allowed):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "admin role required (roles claim must intersect ADMIN_ROLES: "
                f"{sorted(allowed)})"
            ),
        )
    return AdminActor(via="logto-role", identity=user.identity, roles=user.roles)


__all__ = ["AdminActor", "require_admin"]