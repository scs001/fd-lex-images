"""交付包分发端点（lex-platform-v1 6.3 / spec lex-private-distribution 增量更新通道）。

面：``/api/distribution/*``（宿主 Caddy 把 lex 域 /api/* 原样反代到本服务）。

- ``GET /api/distribution/manifests``：bundle 清单（可按 tier/form 过滤）
- ``GET /api/distribution/manifests/{bundle_id}``：manifest 详情（含 pack 摘要与下载 URL）
- ``GET /api/distribution/packs/{bundle_id}``：pack 流式下载（支持 Range 断点续传、
  If-Range/ETag、HEAD）
- ``GET /api/distribution/packs/{bundle_id}/sha256``：每包 sha256 校验端点
  （``?verify=1`` 时重算并比对，不一致 409 拒绝——坏包不应用语义的服务端一侧）
- ``GET /api/distribution/catalog``：双宿主能力目录 + 如实标注的差异

鉴权：v1 用配置化 token（``DISTRIBUTION_API_TOKEN``），fail-closed（未配置 403）；
客户级凭据（wgk-）接 Logto 后在此收敛（如实标注为后续项）。
"""