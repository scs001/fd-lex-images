# fd-lex-api

识律平台服务端（FastAPI）。当前提供健康检查、版本自报、计量结算内部服务面与
控制台/运营后台服务面（lex-platform-v1 task 5.1+5.2+4.3+4.4）：

- `GET /healthz` — 存活探针，返回 `{"status": "ok"}`
- `GET /api/version` — 版本自报（`BUILD_VERSION` 环境变量优先，默认 `dev`）
- `/internal/metering` — 双单位计量（行/次，token 预留）：审计事件摄取、
  registry Mongo audit 流消费、用量聚合、异常留痕查询
- `/internal/billing` — 结算账本：结算触发（sub2api 幂等扣减）、账本×计量流×
  支付侧三方对账、账本流水、额度状态预检（fail-closed）、套餐配置（调价不发版）
- 全部 `/internal/*` 端点走 `INTERNAL_API_TOKEN` 简单 bearer（未配置时
  fail-closed 403）；接 Logto 后在 `fd_lex_api/billing/deps.py` 一处收敛
- `/api/console`（任务 4.3，客户控制台面）：
  `GET /auth/config`（公开 OIDC 配置，无密钥）、`GET /me`、`GET /usage`、
  `GET /billing`、`GET /quota`、`GET|POST /credentials`、
  `DELETE /credentials/{id}`、`GET /credentials/events`。
  鉴权 = `Authorization: Bearer <Logto ID token>`（服务端 JWKS/iss/aud 本地校验）；
  凭据写操作另带 `X-Registry-Token: <Logto access token>`，由本服务**代理**
  registry `/api/patch-keys`（跨域 cookie 难题绕行：不共享 registry 密钥、
  不改 Caddy 剥前缀；lex 域 `/api/*` 原样反代到本服务）。
  用量/账单/额度读 metering/billing 既有表；身份经
  `console_identity_bindings`（Logto username ↔ billing Customer）解析。
- `/api/admin`（任务 4.4，运营后台面）：客户开户/改档/身份绑定、套餐 upsert
  （调价不发版）、账本、用量分轨、凭据操作留痕。
  鉴权 = `X-Admin-Token`（= `INTERNAL_API_TOKEN`，未配置 fail-closed）**或**
  Logto ID token 的 roles 命中 `ADMIN_ROLES`（默认 `lex-admin`）。
- `/api/distribution`（任务 6.3，交付包分发面，`fd_lex_api/distribution/`）：
  `GET /manifests`（bundle 清单，可按 tier/form 过滤）、
  `GET /manifests/{bundle_id}`（manifest 详情）、
  `GET /packs/{bundle_id}`（pack 流式下载，支持 Range 断点续传/HEAD/If-Range）、
  `GET /packs/{bundle_id}/sha256`（每包 sha256 校验；`?verify=1` 重算比对，
  不一致 409 拒绝背书——坏包不应用）、`GET /catalog`（双宿主能力目录与如实差异）。
  数据源 = `DISTRIBUTION_ROOT` 下 packer 产出的 bundle 目录树（只读，路径白名单
  防穿越）；鉴权 = `DISTRIBUTION_API_TOKEN` bearer（未配置 fail-closed 403；
  **客户级凭据 wgk- 接 Logto 为后续项**，见 `distribution/deps.py`）。
- CORS 骨架期全开（生产同源不经 CORS；接入网关后按域名收敛）

## 控制台登录的外部配置（主代理/运维）

1. Logto Admin Console：新建**第一方 SPA 应用**（如 `lex-console`），
   redirect URI `https://lex.finddatatech.cloud/console/callback`，
   post sign-out redirect `https://lex.finddatatech.cloud/console`；
   允许 scope `openid profile email roles offline_access
   urn:logto:scope:organizations`；确保该应用可请求 API resource
   `https://mcp.finddatatech.cloud/api`（registry auth-server 的
   `LOGTO_M2M_RESOURCE` 默认值——access token 的 aud 必须是它）。
2. Secret `fd-lex-env` 增加：`LOGTO_ISSUER=https://auth.finddatatech.cloud`、
   `LOGTO_CLIENT_ID=<上一步 client_id>`、`LOGTO_REQUIRED_ORG_IDS=hnrbfpgq2717`、
   `REGISTRY_BASE_URL=https://mcp.finddatatech.cloud`（其余默认值可省）。
3. 运营后台若走 Logto 角色：在 Logto 建角色 `lex-admin` 并分配给运营账号
   （否则用 `INTERNAL_API_TOKEN` 作为 X-Admin-Token）。
4. Caddy 无需改动：`https://lex.finddatatech.cloud/api/*` 已原样反代本服务
   （`/api/version` 实测 200）；新端点自带 `/api` 前缀。

## 本地开发

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/uvicorn fd_lex_api.main:app --reload   # http://127.0.0.1:8000
```

环境变量样例见 `.env.example`。架构参照 fd-wire 结算域移植（账本权威 +
sub2api 幂等结算 + 两档预警 80%/95%）；规格见
`openspec/changes/lex-platform-v1/specs/lex-billing-metering/spec.md`。

## 测试

```sh
.venv/bin/pytest          # 118 passed（98 既有 + 20 分发面离线测试）
```

测试纪律：sub2api / registry 一律换假件（`dependency_overrides` 或内存假件），
绝不真实调用生产设施；控制台登录用本地 EC 密钥对自签 ID token 验证真校验路径；
分发面测试用 tmp 合成 pack 目录 + 仓内 packer 真实产物的跨模块契约用例
（引用包 full、结构增量、**flk 日增量 incremental** 三种形态：下载完整性 / Range /
sha256 verify=1 / 鉴权 fail-closed）。
