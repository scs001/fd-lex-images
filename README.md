# fd-lex

识律（lex）独立平台门面单仓：`lex.finddatatech.cloud` 四入口的 web 面（官网 / 控制台 / 管理后台）+ FastAPI 服务端（结算/分发/后台 API）。

新仓依据 `openspec/changes/lex-platform-v1`（task 4.1，骨架）。技术栈（design D12）：前端 React 19 + Vite + TS + Tailwind v4 + i18next 双语（fd 舰队配方）；服务端 Python FastAPI（萬星 bookkeeping 概念移植）；部署 cheap fd-prod + TCR + ArgoCD（mcp-service-deploy 既有模式）。

服务本体（法条/类案/语料检索 MCP）在独立仓 `fd-legal-search-mcp`，本仓不承载检索实现。

## 仓结构

| 目录 | 内容 | 镜像（hkccr.ccs.tencentyun.com/finddata-business/） |
|---|---|---|
| `web/` | React 19 + Vite 单页：`/` 官网 landing、`/console` 控制台、`/admin` 管理后台（骨架期均为真实可渲染占位页） | `fd-lex-web` |
| `server/` | FastAPI 服务端骨架：`/healthz`、`/api/version`，CORS 骨架期全开 | `fd-lex-api` |

## 四入口规划

| 入口 | 路径 | 说明 | 状态 |
|---|---|---|---|
| 官网 landing | `/` | 「识律 Lex」品牌与产品定位（法律数据·应用·模型，全栈可私有化） | 占位页 |
| 控制台 console | `/console` | 租户/用量/结算/分发入口 | 占位页 |
| 管理后台 admin | `/admin` | 平台后台，按 panel 角色门禁模式 | 占位页 |
| 平台 API | `/api`（server 侧） | 结算/分发/后台 API | 骨架（healthz/version） |

i18n：i18next 中英双语（zh/en 各一个 `translation` namespace），导航栏可切换。

## 本地开发

server（FastAPI）：

```sh
cd server
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/uvicorn fd_lex_api.main:app --reload   # http://127.0.0.1:8000
```

web（React + Vite）：

```sh
cd web
npm ci
npm run dev        # http://localhost:5173
npm run build      # 产物 dist/
```

## 发布通道

GitHub Actions -> TCR 个人版（`.github/workflows/image.yml`，一个 workflow 两个 job：web / api 各一）。

- 仓库：`hkccr.ccs.tencentyun.com/finddata-business/fd-lex-web`、`.../fd-lex-api`
- tag：`sha-<短哈希>` + `main`；provenance 关闭、gha 缓存
- cheap-3 tcr-relay 5 分钟内回灌 `ccr` 侧
- 配方：`docs/IMAGE-RELEASE.md`（硬性要求：上游源为默认，国内镜像源一律 ARG 且默认空）
