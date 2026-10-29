"""控制台面（/api/console/*）与运营后台面（/api/admin/*）的服务端。

（lex-platform-v1 任务 4.3/4.4 的服务端部分。）

面一：控制台客户自助
- 登录：Logto SPA（authorization code + PKCE）在浏览器完成；本服务只校验
  ID token（JWKS + iss + aud），不持有 Logto 客户端密钥、不落 token。
- 凭据管理：经本服务代理 registry ``/api/patch-keys``（Bearer 透传客户
  access token）——lex 域页面拿不到 mcp 域会话 cookie 的跨域难题由此绕开，
  无需共享 registry SECRET_KEY、无需改 Caddy 剥前缀。
- 用量/账单/额度：读本服务的 metering/billing 域（同一事实源），身份经
  ``console_identity_bindings`` 绑定 Logto username ↔ billing Customer。

面二：运营后台
- 客户/身份绑定/套餐（调价不发版）/账本/用量/凭据操作留痕。
- 鉴权：``X-Admin-Token``（= INTERNAL_API_TOKEN，fail-closed）或携带
  ``admin_roles`` 命中角色的 Logto ID token。

模块边界：不 import registry 源码、不 import sub2api 之外的私有实现；
对 registry 只经显式 HTTP 契约（README「借用契约」纪律）。
"""

from .identity import (
    customer_identities,
    resolve_console_customer,
    usage_by_unit,
    usage_rows,
)
from .models import (
    CREDENTIAL_ACTION_MINT,
    CREDENTIAL_ACTION_REVOKE,
    ConsoleBase,
    ConsoleCredentialEvent,
    ConsoleIdentityBinding,
    ensure_console_schema,
)

__all__ = [
    "CREDENTIAL_ACTION_MINT",
    "CREDENTIAL_ACTION_REVOKE",
    "ConsoleBase",
    "ConsoleCredentialEvent",
    "ConsoleIdentityBinding",
    "customer_identities",
    "ensure_console_schema",
    "resolve_console_customer",
    "usage_by_unit",
    "usage_rows",
]