---
title: MCP 接入手册
description: 通过 MCP Streamable HTTP 接入识律法律检索服务：凭据获取、连接配置、工具清单、数据溯源契约、计量额度与故障排查。
---

## 一、适用对象与前置条件

本手册面向需要在自有应用、Agent 工作流或 MCP 客户端中接入识律法律检索服务的开发者与法务技术人员。

开始之前，请确认：

- 你使用一个支持 MCP Streamable HTTP 传输的 MCP 客户端（桌面 MCP 宿主、Agent 框架或自研客户端均可）；
- 你能访问公网入口 `https://lex.finddatatech.cloud`；
- 你了解所用客户端如何为 MCP 服务配置入口 URL 与自定义请求头。

当前入口提供 10 个法律检索工具 [N7]，覆盖法律法规、裁判文书（类案）、指导案例与五源法律语料四类数据域；每个结果条目都携带数据溯源三件套（见「六、数据溯源（provenance）契约」）。

## 二、获取凭据

识律平台采用客户自持长命 API key 的凭据模型，key 以 `wgk-` 为前缀。铸造与保管步骤如下：

1. 浏览器打开控制台：`https://lex.finddatatech.cloud/console`。
2. 首次使用先注册账号（注册与登录由 Logto 身份服务承载）；已注册则直接登录。
3. 登录后进入控制台，打开凭据管理页，铸造一枚新的长命 key。
4. 铸造完成后，立即把 key 复制保存到你的密码管理器或部署密钥库。
5. 凭据列表会为每枚 key 记录最近使用时间，可随时回来核对使用痕迹。

安全约定：

- 本手册所有示例一律使用 `wgk-你的密钥` 占位，请替换为你自己的 key；
- 不要把真实 key 写进代码仓库、聊天记录或公开文档，推荐经环境变量注入；
- 如怀疑泄露，立即重新铸造一枚新 key、替换客户端配置，并核对旧 key 的最近使用记录有无异常。

## 三、连接配置

入口为 MCP Streamable HTTP 端点：

- 入口 URL：`https://lex.finddatatech.cloud/mcp`
- 认证头：`Authorization: Bearer wgk-你的密钥`
- Accept 头：`application/json, text/event-stream`（Streamable HTTP 要求同时接受两种响应类型）

通用 MCP 客户端 JSON 配置示例（字段名以你的客户端文档为准）：

```json
{
  "mcpServers": {
    "lex-legal": {
      "type": "streamable-http",
      "url": "https://lex.finddatatech.cloud/mcp",
      "headers": {
        "Authorization": "Bearer wgk-你的密钥"
      }
    }
  }
}
```

## 四、协议要点

入口遵循 MCP Streamable HTTP 语义，握手顺序为：

1. 客户端向入口 POST `initialize` 请求；
2. 服务端返回能力与服务信息（`serverInfo` 中为服务名 `fd-legal-search-mcp` 及版本号），并可能下发 `Mcp-Session-Id` 响应头；
3. 客户端发送 `notifications/initialized` 通知，完成握手；
4. 之后即可 `tools/list` 枚举工具、`tools/call` 调用工具；后续每个请求都应回带 `Mcp-Session-Id` 会话头与 `Authorization` 认证头。

`initialize` 请求体示例（`protocolVersion` 使用你的客户端 SDK 所协商的 MCP 协议版本，标准 SDK 会自动填写，无需手工维护）：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "<你的客户端所支持的 MCP 协议版本>",
    "capabilities": {},
    "clientInfo": { "name": "my-client", "version": "1.0.0" }
  }
}
```

对应的 curl 写法：

```sh
curl -sS -X POST https://lex.finddatatech.cloud/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer wgk-你的密钥" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"<协议版本>","capabilities":{},"clientInfo":{"name":"my-client","version":"1.0.0"}}}'
```

## 五、工具清单

入口背后是法律检索服务 fd-legal-search-mcp（现网版本 4.0.11），`tools/list` 实测恰为 10 个工具 [N7]。四类数据域的库侧规模如下：

| 数据域 | 工具 | 库侧规模 |
|---|---|---|
| 法律法规 | `law_search` / `law_read` / `law_semantic_search` / `law_reference` | 32,296 部 [N1]；法条切片 364,916 条 [N2] |
| 裁判文书（类案） | `wenshu_search` / `wenshu_read` | 37,001,012 篇 [N3][N4]，截至 2026-10-07 库侧实测，随增量持续增长 <!-- audit-exempt: 口径日期 --> |
| 指导案例 | `guide_cases_search` / `guide_cases_read` | 278 篇案例 + 15 条批次通知 [N5] |
| 五源语料 | `legal_docs_search` / `legal_docs_read` | 47,256 篇 [N6] |

通用约定（适用于全部工具）：

- 检索排序统一为「精确命中 > 前缀命中 > 包含命中」；
- `limit` 等参数的默认值与取值上限由服务端约束，以 `tools/list` 返回的 inputSchema 为准 <!-- audit-exempt: 接口参数默认值与上限 -->；
- 过滤参数多为封闭词表，词表外的取值会被明确拒绝并附可读原因，服务不会猜测近似值；
- 未命中一律如实返回空结果，绝不编造数据；
- 每个结果条目都携带 provenance 三件套（见下一章）；
- 读取类工具的标识参数请替换为对应检索结果返回的真实标识（JSON 类型以 inputSchema 为准）。

下面逐个给出 10 个工具的用途、关键参数与调用示例。示例为 `tools/call` 的 `params`。

### law_search

- 用途：法规目录全库标题检索（含别名治理），返回法规条目元数据，配合 `law_read` 取正文。
- 关键参数：`title_query`（必填，标题关键词）；`category`（可选，法规类别过滤，接受同义拼写，如「法律」「行政法规」「司法解释」「地方性法规」）；`limit`（可选，返回条数上限）。
- 调用示例：

```json
{
  "name": "law_search",
  "arguments": { "title_query": "民法典", "category": "法律", "limit": 5 }
}
```

### law_read

- 用途：按 `law_id` 读取一部法规的详情与条级正文切片，供正文阅读与条级引用。
- 关键参数：`law_id`（必填，来自 `law_search` 结果的稳定标识）。
- 调用示例：

```json
{ "name": "law_read", "arguments": { "law_id": "<law_search 返回的 law_id>" } }
```

### law_semantic_search

- 用途：法条语义检索——把自然语言查询向量化，在法条切片向量库中按语义相似度返回条级片段，适合没有精确条文出处的开放问题。
- 关键参数：`query`（必填，自然语言查询）；`top_k`（可选，返回条数）。
- 调用示例：

```json
{ "name": "law_semantic_search", "arguments": { "query": "合同被认定无效后财产如何返还", "top_k": 5 } }
```

### law_reference

- 用途：条级引用解析——把「《民法典》第一百四十三条」式引用解析为法规目录中的条级定位；无法解析时如实返回未命中原因，绝不猜测。
- 关键参数：`citation`（必填，中文法规引用串）。
- 调用示例：

```json
{ "name": "law_reference", "arguments": { "citation": "《民法典》第一百四十三条" } }
```

### wenshu_search

- 用途：裁判文书标题检索（类案检索入口）。案号内嵌于标题（如「（2024）京01民初1号」），无需单独的案号参数。
- 关键参数：`title_query`（必填，标题关键词，案号可直接作为关键词）；`doc_type`（可选，文书类型，如「判决书」「裁定书」「调解书」）；`province`（可选，省份）；`start_year` / `end_year`（可选，按判决年份闭区间收窄）；`limit`（可选）。
- 调用示例：

```json
{
  "name": "wenshu_search",
  "arguments": { "title_query": "买卖合同", "doc_type": "判决书", "start_year": 2023, "end_year": 2024, "limit": 5 }
}
```

### wenshu_read

- 用途：按 `doc_id` 读取一篇裁判文书正文（按块解压）；条目存在而正文缺失时如实标注，绝不编造正文。
- 关键参数：`doc_id`（必填，来自 `wenshu_search` 结果）。
- 调用示例：

```json
{ "name": "wenshu_read", "arguments": { "doc_id": "<wenshu_search 返回的 doc_id>" } }
```

### guide_cases_search

- 用途：指导性案例标题检索。
- 关键参数：`title_query`（必填）；`doc_type`（可选，封闭词表：`case` 案例 / `notice` 批次通知）；`reference_status`（可选，封闭词表：`有效` / `不再参照`）；`limit`（可选）。
- 调用示例：

```json
{
  "name": "guide_cases_search",
  "arguments": { "title_query": "不正当竞争", "reference_status": "有效", "limit": 5 }
}
```

### guide_cases_read

- 用途：按 `case_id` 读取一篇指导案例（或批次通知）的完整内容。
- 关键参数：`case_id`（必填，来自 `guide_cases_search` 结果）。
- 调用示例：

```json
{ "name": "guide_cases_read", "arguments": { "case_id": "<guide_cases_search 返回的 case_id>" } }
```

### legal_docs_search

- 用途：五源权威法律语料跨库标题检索。`source` 为五源代码封闭词表：`gov-rules-library` 政府规章库、`mfa-treaty-library` 外交部条约库、`ccdi-supervisory-regulations` 纪检监察法规库、`party-regulation-library` 党内法规库、`rmfyalk-case-library` 人民法院案例库。
- 关键参数：`title_query`（必填）；`source`（可选，五源代码之一）；`doc_type`（可选）；`limit`（可选）。
- 调用示例：

```json
{
  "name": "legal_docs_search",
  "arguments": { "title_query": "安全生产", "source": "gov-rules-library", "limit": 5 }
}
```

### legal_docs_read

- 用途：按 `doc_id` 读取一篇五源语料文档的元数据与正文（正文未入库时如实标注）。
- 关键参数：`doc_id`（必填，来自 `legal_docs_search` 结果）。
- 调用示例：

```json
{ "name": "legal_docs_read", "arguments": { "doc_id": "<legal_docs_search 返回的 doc_id>" } }
```

## 六、数据溯源（provenance）契约

每一次工具返回的结果条目都携带 `provenance` 三件套，用于把返回内容锚定回来源库：

| 字段 | 含义 |
|---|---|
| `source` | 来源库表（如 `law_db.laws`） |
| `stable_id` | 该条数据在来源库中的稳定标识 |
| `as_of` | 数据口径时间（快照/导出时间） |

各数据域的取值：

| 数据域 | source | stable_id |
|---|---|---|
| 法律法规 | `law_db.laws` | `law_id` |
| 法条切片 | `law_db.law_chunks_v2` | 向量点 id |
| 裁判文书 | `wenshu_db.judgments` | `doc_id` |
| 指导案例 | `law_db.guide_cases` | `case_id` |
| 五源语料 | `law_db.legal_documents` | `source_id` |

使用建议：

- 对外引用或落库时，把三件套与内容一起保存，保证下游可回查核验；
- 读取类工具都以 stable_id 定位，「先检索、后读取」即可串成完整链路；
- 三件套缺失即视为服务缺陷（服务端有契约测试守护），不会降级为无溯源返回。

## 七、计量与额度

- 双单位计量：读取/检索类工具按返回行数计量，生成/评测类工具按调用次数计量。当前入口提供的 10 个工具均属读取/检索类 [N7]。
- 每次调用的计量记录以平台结算账本为准，可在控制台用量页查看。
- 额度保护采用 fail-closed 语义：每次调用前服务端做额度预检，额度耗尽时直接拒绝请求（HTTP 402 <!-- audit-exempt: HTTP 状态码 -->），不会先服务后结算；充值/入金到账后自动恢复。
- 平台设两档余额预警，接近阈值时会在控制台提示；账单与流水可在控制台账单页查看。
- 套餐与额度数值以控制台实际展示为准。

## 八、故障排查

先做两项基础检查：确认请求带了 `Authorization: Bearer` 头且 key 完整、无多余空格；确认 `Accept` 头同时包含 `application/json` 与 `text/event-stream`。

| 现象 | 含义 | 处理 |
|---|---|---|
| HTTP 401 | 入口未收到有效凭据（未带头、key 失效或已被替换） | 核对认证头与 key；无凭据探测到 401 也说明入口在役 <!-- audit-exempt: HTTP 状态码 --> |
| HTTP 403 | key 有效但越界：访问了未授权的服务面 | 确认所用 key 的授权范围仅覆盖识律法律检索服务，勿将其用于其他平台入口 <!-- audit-exempt: HTTP 状态码 --> |
| HTTP 402 | 额度预检未通过：余额为零或额度耗尽（fail-closed） | 到控制台额度状态页确认余额并完成充值/入金，到账后重试 <!-- audit-exempt: HTTP 状态码 --> |
| HTTP 502 | 网关瞬态异常（如网关侧发布或重建窗口） | 稍候重试；持续出现请联系支持 <!-- audit-exempt: HTTP 状态码 --> |

工具层错误与 HTTP 层不同：参数非法（如封闭词表外的取值）、目标条目不存在等会以结构化错误在工具结果中如实返回并附可读原因，按原因修正参数即可。

## 九、常见问题

### 返回空结果是没查到吗？

是。服务以「如实回报」为契约：未命中如实返回空结果，不会用猜测数据填充；过滤词表取值非法时返回明确的校验错误。可尝试放宽关键词、去掉过滤参数后重试。

### 如何核验一条结果的出处？

查看该条目的 provenance 三件套（`source` / `stable_id` / `as_of`）：`source` 给出来源库表，`stable_id` 是可在库内定位的稳定标识，`as_of` 标明口径时间。对外引用时请一并保留三件套。

### 对 MCP 客户端有什么要求？

任意支持 Streamable HTTP 传输、可自定义请求头的 MCP 客户端均可接入。主流 MCP SDK 大多原生支持该传输，按第三章配置入口 URL 与认证头即可。

### 怀疑 key 泄露怎么办？

立即铸造一枚新 key 并替换客户端配置；随后在控制台凭据列表核对旧 key 的最近使用记录有无异常时间段的调用。文档与示例中永远只用 `wgk-你的密钥` 占位。

### 支持私有化部署吗？

支持。私有化部署是识律平台的线级能力，部署形态与交付包详见官网 `/deploy` 页。
