"""控制台身份校验：Logto ID token 本地校验（JWKS/iss/aud/exp）+ 组织门禁。

设计取舍（跨域凭据方案的 lex 侧半场）：
- 浏览器（lex 域）用 Logto SPA authorization code + PKCE 换得 ID token 与
  access token，只把 token 发给同源的本服务；本服务不持有 Logto 客户端密钥、
  不落任何 token、不设 cookie——无跨域 cookie 依赖。
- 身份取自**本地校验过的 ID token claims**（username/email/roles/
  organizations），不依赖 Logto userinfo 的额外往返。
- 组织门禁：``LOGTO_REQUIRED_ORG_IDS`` 非空时，要求 ID token 的
  ``organizations`` claim（需请求 scope ``urn:logto:scope:organizations``）
  命中其一；claim 缺失或未命中一律 403（fail-closed，不猜身份）。
  未配置门禁时放行一切合法 Logto 用户（部署默认值见 deploy/README）。

未配置 LOGTO_ISSUER/LOGTO_CLIENT_ID 时全部控制台端点 503 并给出精确缺项
（绝不假登录放行）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from fastapi import HTTPException, Request, status

from ..config import get_settings

ALGORITHMS = ["ES384", "RS256", "ES256"]


@dataclass(frozen=True)
class ConsoleUser:
    """已校验的控制台用户（身份键 = Logto username/email/sub 优先序）。"""

    identity: str
    username: str | None
    email: str | None
    sub: str | None
    roles: list[str] = field(default_factory=list)
    organizations: list[str] = field(default_factory=list)
    claims: dict[str, Any] = field(default_factory=dict)

    def has_admin_role(self, allowed: frozenset[str]) -> bool:
        return bool(allowed and (set(self.roles) & set(allowed)))


def _bearer(request: Request) -> str:
    authorization = request.headers.get("authorization") or ""
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token.strip()


@lru_cache(maxsize=8)
def _jwks_client(jwks_url: str):
    """JWKS 客户端缓存（PyJWT 内置 key 缓存；URL 作键）。"""
    from jwt import PyJWKClient

    return PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)


def _decode_id_token(token: str) -> dict[str, Any]:
    """校验 Logto ID token：签名（JWKS）+ issuer + audience + exp/iat。"""
    settings = get_settings()
    issuer = settings.logto_oidc_base()
    client_id = settings.logto_client_id.strip()
    if not issuer or not client_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "console login not configured: set LOGTO_ISSUER and LOGTO_CLIENT_ID "
                "(see deploy/README.md, external Logto SPA app required)"
            ),
        )
    try:
        import jwt as pyjwt
    except ImportError as exc:  # pragma: no cover - 依赖缺失属部署错误
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PyJWT not installed on server (required for console token verification)",
        ) from exc

    try:
        signing_key = _jwks_client(f"{issuer}/oidc/jwks").get_signing_key_from_jwt(token)
        return pyjwt.decode(
            token,
            signing_key.key,
            algorithms=ALGORITHMS,
            issuer=f"{issuer}/oidc",
            audience=client_id,
            options={"verify_exp": True, "verify_iat": True, "verify_aud": True},
        )
    except HTTPException:
        raise
    except Exception as exc:  # 各类 JWT 失败统一 401，细节只回显摘要
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid console token: {type(exc).__name__}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def _claim_list(claims: dict[str, Any], name: str) -> list[str]:
    value = claims.get(name)
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    return []


def user_from_claims(claims: dict[str, Any]) -> ConsoleUser:
    """claims → ConsoleUser（identity 取 username→email→sub 首个非空）。"""
    username = claims.get("username")
    email = claims.get("email")
    sub = claims.get("sub")
    identity = next(
        (str(v) for v in (username, email, sub) if isinstance(v, str) and v.strip()),
        "",
    )
    return ConsoleUser(
        identity=identity,
        username=str(username) if isinstance(username, str) else None,
        email=str(email) if isinstance(email, str) else None,
        sub=str(sub) if isinstance(sub, str) else None,
        roles=_claim_list(claims, "roles"),
        organizations=_claim_list(claims, "organizations"),
        claims=claims,
    )


def verify_id_token(token: str, *, enforce_organization: bool = True) -> ConsoleUser:
    """校验并解析 ID token；默认含组织门禁（控制台客户面）。

    ``enforce_organization=False`` 供运营后台角色路径使用——运营是内部身份，
    不属 lex-customers 组织；隔离由 registry 侧 scope/组映射保证。
    任何不满足即抛 HTTPException。
    """
    claims = _decode_id_token(token)
    user = user_from_claims(claims)
    if not user.identity:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="console token carries no usable identity claim (username/email/sub)",
        )
    required = get_settings().required_org_id_set()
    if enforce_organization and required:
        if not user.organizations:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "token carries no organizations claim; request scope "
                    "'urn:logto:scope:organizations' and ensure the user belongs to "
                    "the lex customer organization"
                ),
            )
        if not (set(user.organizations) & set(required)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="not a lex customer: organization membership required",
            )
    return user


async def require_console_user(request: Request) -> ConsoleUser:
    """FastAPI 依赖：控制台端点必须携带有效 Logto ID token。"""
    return verify_id_token(_bearer(request))


__all__ = [
    "ConsoleUser",
    "require_console_user",
    "user_from_claims",
    "verify_id_token",
]