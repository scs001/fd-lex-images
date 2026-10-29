---
title: MCP Integration Guide
description: Connect to the LiangLü legal-search MCP over Streamable HTTP — credentials, connection settings, tool reference, provenance contract, metering, and troubleshooting.
---

## 1. Audience and prerequisites

This guide is for developers and legal-engineering practitioners who want to integrate the LiangLü legal-search service into their own applications, agent workflows, or MCP clients.

Before you start, make sure that:

- you use an MCP client with Streamable HTTP transport support (desktop MCP hosts, agent frameworks, and custom clients all work);
- you can reach the public endpoint `https://lex.finddatatech.cloud`;
- you know how your client configures a custom MCP service (endpoint URL and custom headers).

The endpoint currently exposes 10 legal-search tools [N7] covering four data domains — statutes and regulations, judgment documents (similar-case search), guiding cases, and the five-source legal corpus. Every result item carries the three-part provenance tuple (see section 6, "Data provenance contract").

## 2. Obtaining credentials

The LiangLü platform uses customer-held long-lived API keys, prefixed with `wgk-`. To mint and store one:

1. Open the console in a browser: `https://lex.finddatatech.cloud/console`.
2. Register an account on first use (registration and login are handled by the Logto identity service); existing users can sign in directly.
3. After signing in, open the credentials page in the console and mint a new long-lived key.
4. As soon as the key is minted, copy it into your password manager or deployment secret store.
5. The credentials list records the last-used time for each key, so you can audit usage at any time.

Security rules:

- All examples in this guide use the placeholder `wgk-你的密钥`; replace it with your own key;
- never put a real key into source control, chat history, or public documents — inject it via environment variables instead;
- if you suspect a leak, mint a new key immediately, update your client configuration, and check the old key's last-used record for anomalies.

## 3. Connection settings

The endpoint is an MCP Streamable HTTP server:

- Endpoint URL: `https://lex.finddatatech.cloud/mcp`
- Auth header: `Authorization: Bearer wgk-你的密钥`
- Accept header: `application/json, text/event-stream` (Streamable HTTP requires accepting both response types)

A generic MCP client JSON configuration (field names follow your client's documentation):

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

## 4. Protocol essentials

The endpoint follows MCP Streamable HTTP semantics. The handshake sequence is:

1. The client POSTs an `initialize` request to the endpoint;
2. The server replies with its capabilities and service info (`serverInfo` carries the service name `fd-legal-search-mcp` and a version), and may issue an `Mcp-Session-Id` response header;
3. The client sends the `notifications/initialized` notification to complete the handshake;
4. Then `tools/list` enumerates the tools and `tools/call` invokes them; every subsequent request should carry both the `Mcp-Session-Id` session header and the `Authorization` auth header.

Example `initialize` request body (`protocolVersion` is the MCP protocol version your client SDK negotiates — standard SDKs fill it in automatically):

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "<the MCP protocol version your client supports>",
    "capabilities": {},
    "clientInfo": { "name": "my-client", "version": "1.0.0" }
  }
}
```

The same request with curl:

```sh
curl -sS -X POST https://lex.finddatatech.cloud/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "Authorization: Bearer wgk-你的密钥" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"<protocol version>","capabilities":{},"clientInfo":{"name":"my-client","version":"1.0.0"}}}'
```

## 5. Tool reference

Behind the endpoint sits the legal-search service fd-legal-search-mcp (live version 4.0.11); a live `tools/list` returns exactly 10 tools [N7]. The four data domains and their database-side sizes:

| Data domain | Tools | Database-side size |
|---|---|---|
| Statutes and regulations | `law_search` / `law_read` / `law_semantic_search` / `law_reference` | 32,296 statutes [N1]; 364,916 article-level chunks [N2] |
| Judgment documents (similar cases) | `wenshu_search` / `wenshu_read` | 37,001,012 judgments [N3][N4], measured in the live database on 2026-10-07 and growing with increments <!-- audit-exempt: as-of date --> |
| Guiding cases | `guide_cases_search` / `guide_cases_read` | 278 cases + 15 batch notices [N5] |
| Five-source corpus | `legal_docs_search` / `legal_docs_read` | 47,256 documents [N6] |

Conventions that apply to all tools:

- Search ranking is uniformly "exact match > prefix match > substring match";
- Default values and bounds for parameters such as `limit` are enforced server-side; treat the inputSchema returned by `tools/list` as authoritative <!-- audit-exempt: parameter defaults and bounds -->;
- Most filter parameters are closed vocabularies — out-of-vocabulary values are rejected outright with a readable reason; the service never guesses near-matches;
- Misses are always returned honestly as empty results; data is never fabricated;
- Every result item carries the provenance tuple (next section);
- For read tools, replace the identifier argument with the real identifier returned by the corresponding search (the JSON type follows the inputSchema).

Below are the 10 tools one by one — purpose, key parameters, and a call example. Examples show the `params` of `tools/call`.

### law_search

- Purpose: title search across the full statute catalog (with alias governance); returns statute metadata — pair with `law_read` for full text.
- Key parameters: `title_query` (required, title keywords); `category` (optional, statute-category filter with synonym-tolerant spelling, e.g. 法律, 行政法规, 司法解释, 地方性法规); `limit` (optional, max results).
- Call example:

```json
{
  "name": "law_search",
  "arguments": { "title_query": "民法典", "category": "法律", "limit": 5 }
}
```

### law_read

- Purpose: read one statute's details and article-level text chunks by `law_id`, for full-text reading and article-level citation.
- Key parameters: `law_id` (required, the stable identifier from `law_search` results).
- Call example:

```json
{ "name": "law_read", "arguments": { "law_id": "<law_id returned by law_search>" } }
```

### law_semantic_search

- Purpose: semantic statute search — the query is embedded and matched against the article-chunk vector store by similarity, suited to open questions without a precise article citation.
- Key parameters: `query` (required, natural-language query); `top_k` (optional, number of results).
- Call example:

```json
{ "name": "law_semantic_search", "arguments": { "query": "合同被认定无效后财产如何返还", "top_k": 5 } }
```

### law_reference

- Purpose: article-level citation resolution — parses citations like 「《民法典》第一百四十三条」 into an article-level location in the statute catalog; unresolvable input is reported honestly with a reason, never guessed.
- Key parameters: `citation` (required, the Chinese statute citation string).
- Call example:

```json
{ "name": "law_reference", "arguments": { "citation": "《民法典》第一百四十三条" } }
```

### wenshu_search

- Purpose: judgment-title search (the similar-case search entry). Case numbers are embedded in titles (e.g. 「（2024）京01民初1号」), so no separate case-number argument is needed.
- Key parameters: `title_query` (required, title keywords; case numbers work as keywords directly); `doc_type` (optional, document type, e.g. 判决书, 裁定书, 调解书); `province` (optional, province); `start_year` / `end_year` (optional, closed interval on judgment year); `limit` (optional).
- Call example:

```json
{
  "name": "wenshu_search",
  "arguments": { "title_query": "买卖合同", "doc_type": "判决书", "start_year": 2023, "end_year": 2024, "limit": 5 }
}
```

### wenshu_read

- Purpose: read one judgment's full text by `doc_id` (block-by-block decompression); if the entry exists but the body is missing, that is stated honestly — the body is never fabricated.
- Key parameters: `doc_id` (required, from `wenshu_search` results).
- Call example:

```json
{ "name": "wenshu_read", "arguments": { "doc_id": "<doc_id returned by wenshu_search>" } }
```

### guide_cases_search

- Purpose: title search over guiding cases.
- Key parameters: `title_query` (required); `doc_type` (optional, closed vocabulary: `case` for cases / `notice` for batch notices); `reference_status` (optional, closed vocabulary: 有效 "in effect" / 不再参照 "no longer referenced"); `limit` (optional).
- Call example:

```json
{
  "name": "guide_cases_search",
  "arguments": { "title_query": "不正当竞争", "reference_status": "有效", "limit": 5 }
}
```

### guide_cases_read

- Purpose: read one guiding case (or batch notice) in full by `case_id`.
- Key parameters: `case_id` (required, from `guide_cases_search` results).
- Call example:

```json
{ "name": "guide_cases_read", "arguments": { "case_id": "<case_id returned by guide_cases_search>" } }
```

### legal_docs_search

- Purpose: cross-corpus title search over the five-source authoritative legal corpus. `source` is a closed vocabulary of five corpus codes: `gov-rules-library` (government rules), `mfa-treaty-library` (MFA treaties), `ccdi-supervisory-regulations` (supervisory regulations), `party-regulation-library` (party regulations), `rmfyalk-case-library` (people's court cases).
- Key parameters: `title_query` (required); `source` (optional, one of the five corpus codes); `doc_type` (optional); `limit` (optional).
- Call example:

```json
{
  "name": "legal_docs_search",
  "arguments": { "title_query": "安全生产", "source": "gov-rules-library", "limit": 5 }
}
```

### legal_docs_read

- Purpose: read one five-source corpus document's metadata and body by `doc_id` (a missing body is stated honestly).
- Key parameters: `doc_id` (required, from `legal_docs_search` results).
- Call example:

```json
{ "name": "legal_docs_read", "arguments": { "doc_id": "<doc_id returned by legal_docs_search>" } }
```

## 6. Data provenance contract

Every result item returned by any tool carries a `provenance` tuple that anchors the content back to its source database:

| Field | Meaning |
|---|---|
| `source` | Source database table (e.g. `law_db.laws`) |
| `stable_id` | The item's stable identifier within the source database |
| `as_of` | Data as-of time (snapshot/export time) |

Values per data domain:

| Data domain | source | stable_id |
|---|---|---|
| Statutes and regulations | `law_db.laws` | `law_id` |
| Article chunks | `law_db.law_chunks_v2` | vector point id |
| Judgment documents | `wenshu_db.judgments` | `doc_id` |
| Guiding cases | `law_db.guide_cases` | `case_id` |
| Five-source corpus | `law_db.legal_documents` | `source_id` |

Usage advice:

- When citing externally or persisting results, store the tuple together with the content so downstream consumers can verify it;
- Read tools locate items by stable_id, so "search first, then read" forms a complete chain;
- A missing tuple is treated as a service defect (guarded by contract tests on the server side); results are never degraded to provenance-free output.

## 7. Metering and quota

- Dual-unit metering: read/search tools are metered per row returned, while generation/evaluation tools are metered per call. All 10 tools currently exposed on this endpoint are read/search class [N7].
- Metering records for every call follow the platform settlement ledger and can be reviewed on the console usage page.
- Quota protection uses fail-closed semantics: the server runs a quota precheck before every call; when the quota is exhausted the request is rejected outright (HTTP 402 <!-- audit-exempt: HTTP status code -->) — service is never rendered before settlement. Service resumes automatically once a top-up is credited.
- Two balance-alert thresholds are provided; the console prompts as they are approached. Bills and ledger entries are available on the console billing page.
- Plan and quota figures are shown as displayed in the console.

## 8. Troubleshooting

Two basic checks first: confirm the request carries an `Authorization: Bearer` header with a complete key (no stray whitespace), and confirm the `Accept` header includes both `application/json` and `text/event-stream`.

| Symptom | Meaning | Action |
|---|---|---|
| HTTP 401 | The endpoint received no valid credential (missing header, expired key, or replaced key) | Verify the auth header and key; a 401 on an unauthenticated probe also confirms the endpoint is alive <!-- audit-exempt: HTTP status code --> |
| HTTP 403 | The key is valid but out of scope: an unauthorized service surface was addressed | Confirm the key's authorization covers only the LiangLü legal-search service; do not point it at other platform endpoints <!-- audit-exempt: HTTP status code --> |
| HTTP 402 | Quota precheck failed: zero balance or exhausted quota (fail-closed) | Check the balance on the console quota page, complete a top-up, then retry once credited <!-- audit-exempt: HTTP status code --> |
| HTTP 502 | Transient gateway error (e.g. a gateway release or rebuild window) | Retry shortly; contact support if it persists <!-- audit-exempt: HTTP status code --> |

Tool-level errors differ from HTTP-level ones: invalid parameters (e.g. out-of-vocabulary filter values) or missing target items come back as structured errors inside the tool result with a readable reason — fix the parameter per that reason.

## 9. FAQ

### Does an empty result mean nothing was found?

Yes. The service contract is honest reporting: misses are returned as empty results and are never padded with guessed data; out-of-vocabulary filter values produce an explicit validation error. Try broader keywords or drop filter parameters and search again.

### How do I verify the origin of a result?

Inspect the item's provenance tuple (`source` / `stable_id` / `as_of`): `source` names the source table, `stable_id` locates the item inside that database, and `as_of` states the data as-of time. Keep the tuple whenever you cite a result externally.

### What are the MCP client requirements?

Any MCP client that supports Streamable HTTP transport and custom headers will work. Most mainstream MCP SDKs support this transport natively — configure the endpoint URL and auth header as in section 3.

### What should I do if I suspect a key leak?

Mint a new key immediately and update your client configuration; then check the old key's last-used record in the console credentials list for calls from unusual times. Documentation and examples always use the `wgk-你的密钥` placeholder only.

### Is private deployment supported?

Yes. Private deployment is a platform-line capability of LiangLü; see the `/deploy` page on the website for deployment forms and the distribution package.
