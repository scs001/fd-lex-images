"""fd-lex 运行时配置：全部 env 可覆盖（同名环境变量优先）。

命名沿用 fd-wire 生产验证的借用契约口径（README「借用契约」纪律）：
对不归本仓的能力（registry / sub2api）只经显式 HTTP 契约访问，端点与
密钥都是占位默认值、部署时用同名环境变量覆盖。

环境变量一览：

- ``DATABASE_URL``：lex 库连接串（计量 + 账本同库），默认
  ``sqlite:///./fd_lex_dev.db``；测试指向内存库/临时库。
- ``SUB2API_BASE`` / ``SUB2API_ADMIN_KEY``：sub2api 计费面 admin API
  （与 wire 同一生产设施、同一契约端点）。
- ``INTERNAL_API_TOKEN``：全部 ``/internal/*`` 端点的 bearer 校验令牌；
  未配置时 fail-closed（403），绝不无令牌放行。接入 Logto 后由此收敛
  （骨架期简单 bearer，见 billing/deps.py）。
- ``PLATFORM_IDENTITIES``：平台服务身份名单（逗号分隔 username，大小写
  不敏感）。命中的调用 → credential_track=platform（平台自用，不进客户
  账单），否则 customer。
- ``REGISTRY_MONGO_URI`` / ``REGISTRY_MONGO_DB`` /
  ``REGISTRY_MONGO_COLLECTION``：registry Mongo 审计流直读（生产消费链，
  2026-10-12 落地）；URI 未配置时该路径禁用。
- ``METERING_SERVER_ALLOWLIST``：lex 计费域 server 白名单（逗号分隔）。
  registry 审计流含全舰队事件——不设白名单会把 wire/facet 流量吸进
  lex 计量表（结算报告刷 skipped_no_customer 噪声）。空串=不过滤（不推荐）。
- ``METERING_DRIVER_ENABLED`` / ``METERING_DRIVER_INTERVAL_SECONDS``：
  周期「审计摄取 → 闭月结算」驱动（默认关，生产部署 env 开闸）。
- ``METERING_POLL_LIMIT``：audit 流单轮消费批量上限，默认 500。
- ``METERING_AUTO_CREATE_TABLES``：启动时 create_all（默认 true，开发
  便利；生产迁移链就位后置 false——schema 唯一事实源=alembic 链）。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """lex 运行时配置（同名环境变量优先）。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./fd_lex_dev.db"
    sub2api_base: str = "https://router.finddatatech.cloud"
    sub2api_admin_key: str = ""
    internal_api_token: str | None = None
    platform_identities: str = ""
    registry_mongo_uri: str | None = None
    registry_mongo_db: str | None = None
    registry_mongo_collection: str = "audit_events"
    #: lex 计费域 server 白名单（空=不过滤，见模块 docstring）。
    #: 生产值：fd-legal-search-mcp,virtual/lex-legal（含 law-bench 对外子集时追加）。
    metering_server_allowlist: str = ""
    metering_poll_limit: int = 500
    metering_auto_create_tables: bool = True
    #: 周期计量驱动（审计摄取 + 闭月结算）；默认关，生产 env 开闸。
    metering_driver_enabled: bool = False
    metering_driver_interval_seconds: int = 300

    # --- 分发面（/api/distribution，lex-platform-v1 6.3） --------------------
    # 交付包（Distribution）目录：packer 产出的 bundle 目录树（只读扫描）。
    distribution_root: str = "./distribution_packs"
    # 分发面 bearer 令牌；未配置 fail-closed（403）。
    # v1 客户侧定时任务共用该令牌；客户级凭据（wgk-）接 Logto 后演进（如实标注为后续项）。
    distribution_api_token: str | None = None

    # --- 电子签（/api/console/esignature + /api/esignature/s，lex-contract-esignature）
    # 签署腿 provider（可插拔 adapter，见 esignature/adapter.py）。空串=未配置：
    # 发起 fail-closed（409「签署腿未配置」），绝不静默降级为无证明力的假签；
    # ``stub``=进程内确定性假件（开发/测试专用，其出证无司法效力）；真实厂商
    # adapter 待选型 spike 后接入（change tasks 组 1/3.2）。
    esign_provider: str = ""
    # 内容寻址文件仓：合同全文只落客户侧本地目录（sha256 即文件名），
    # 跨出客户侧的仅限哈希+身份记录+签名值（spec「合同全文不出客户侧」）。
    esign_file_store_dir: str = "./esign_files"
    # 签署人 H5 会话有效期（秒）：打开链接后实名/意愿/落签须在该窗口内完成。
    esign_signer_session_ttl_seconds: int = 1800

    # --- 控制台（/console）与运营后台（/admin）面 ---------------------------
    # Logto OIDC：控制台 SPA 走 authorization code + PKCE，服务端只做 ID token
    # 校验（JWKS/iss/aud）与身份读取——不落任何 Logto 客户端密钥。
    # logto_issuer 例：https://auth.finddatatech.cloud（issuer 取其 + /oidc）。
    logto_issuer: str = ""
    # 控制台 SPA 的 Logto client_id（新建 SPA 应用；redirect URI 见部署文档）。
    logto_client_id: str = ""
    # 控制台请求的 Logto API resource：须与 registry auth-server 接受的
    # audience（LOGTO_M2M_RESOURCE，默认 https://mcp.finddatatech.cloud/api）
    # 一致——凭据代理以该 access token 作 Bearer 透传给 registry patch-keys。
    logto_resource: str = "https://mcp.finddatatech.cloud/api"
    # 非空时要求 ID token 的 organizations claim 命中其一（外部客户隔离门）。
    logto_required_org_ids: str = ""
    # 控制台登录请求的 scope（Logto 第一方应用）。
    console_scopes: str = (
        "openid profile email roles offline_access urn:logto:scope:organizations"
    )
    # 运营后台角色门禁：命中 ID token roles claim 任一即放行（Logto 角色名）。
    admin_roles: str = "lex-admin"
    # registry 面（凭据代理目标；同源 Caddy 之外的显式借用契约端点）。
    registry_base_url: str = "https://mcp.finddatatech.cloud"
    # 控制台站点 origin（回跳与 CORS 提示用，不参与鉴权判定）。
    console_origin: str = "https://lex.finddatatech.cloud"
    # registry patch-keys 代理超时（秒）。
    registry_timeout_seconds: float = 10.0

    def platform_identity_set(self) -> frozenset[str]:
        """平台服务身份名单（小写精确匹配）。"""
        return frozenset(
            name.strip().lower() for name in self.platform_identities.split(",") if name.strip()
        )

    def metering_server_allowlist_set(self) -> frozenset[str]:
        """lex 计费域 server 白名单（精确匹配 server_name；空=不过滤）。"""
        return frozenset(
            name.strip() for name in self.metering_server_allowlist.split(",") if name.strip()
        )

    def logto_oidc_base(self) -> str:
        """Logto issuer（去尾斜杠）；空串=未配置。"""
        return self.logto_issuer.strip().rstrip("/")

    def required_org_id_set(self) -> frozenset[str]:
        """必须命中的 Logto organization id 集合（空=不做组织门禁）。"""
        return frozenset(
            org.strip() for org in self.logto_required_org_ids.split(",") if org.strip()
        )

    def admin_role_set(self) -> frozenset[str]:
        """后台角色名集合（精确匹配 Logto roles claim）。"""
        return frozenset(role.strip() for role in self.admin_roles.split(",") if role.strip())

    def console_scope_list(self) -> list[str]:
        return [scope for scope in self.console_scopes.split() if scope]

    def describe(self) -> dict[str, Any]:
        """当前生效配置一览（不含令牌明文，排障用）。"""
        return {
            "database_url": self.database_url,
            "sub2api_base": self.sub2api_base,
            "sub2api_admin_key_configured": bool(self.sub2api_admin_key),
            "internal_api_token_configured": bool(self.internal_api_token),
            "platform_identities": sorted(self.platform_identity_set()),
            "registry_mongo_configured": bool(self.registry_mongo_uri and self.registry_mongo_db),
            "registry_mongo_collection": self.registry_mongo_collection,
            "metering_server_allowlist": sorted(self.metering_server_allowlist_set()),
            "metering_poll_limit": self.metering_poll_limit,
            "metering_driver_enabled": self.metering_driver_enabled,
            "metering_driver_interval_seconds": self.metering_driver_interval_seconds,
            "distribution_root": self.distribution_root,
            "distribution_api_token_configured": bool(self.distribution_api_token),
            "esign_provider": self.esign_provider or None,
            "esign_file_store_dir": self.esign_file_store_dir,
            "esign_signer_session_ttl_seconds": self.esign_signer_session_ttl_seconds,
            "logto_configured": bool(self.logto_oidc_base() and self.logto_client_id),
            "logto_issuer": self.logto_oidc_base(),
            "logto_client_id_configured": bool(self.logto_client_id),
            "logto_resource": self.logto_resource,
            "logto_required_org_ids": sorted(self.required_org_id_set()),
            "admin_roles": sorted(self.admin_role_set()),
            "registry_base_url": self.registry_base_url,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """进程内单例；测试用 ``reset_settings()`` 后重设 env 再取。"""
    return Settings()


def reset_settings() -> None:
    """清空配置缓存——测试切换环境变量用。"""
    get_settings.cache_clear()
