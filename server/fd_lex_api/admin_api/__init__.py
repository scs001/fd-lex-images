"""运营后台面（/api/admin/*）的服务端（lex-platform-v1 任务 4.4）。

鉴权（两条路径，如实标注）：
1. ``X-Admin-Token: <INTERNAL_API_TOKEN>``——与 /internal/* 同一枚内部令牌
   （wire admin 的 X-Admin-Token 模式；未配置即 fail-closed 403）。
2. ``Authorization: Bearer <Logto ID token>``——token 校验通过且 roles 命中
   ``ADMIN_ROLES``（默认 lex-admin；该角色需在 Logto Admin Console 建好并
   分配给运营账号，属外部配置）。

端点族（读/写都在既有 billing/metering 模块上做，不重写其内部逻辑）：
- 客户：列表 / 开户（ensure_customer，sub2api 代建账户）/ 改档位与状态
- 身份绑定：Logto username ↔ billing Customer（控制台解析用）
- 额度：单客户周期额度状态（用量按绑定身份聚合）
- 套餐：列表 / upsert（调价不发版）
- 账本：跨客户/单客户流水（周期过滤）
- 用量：metering_records 按（轨道×调用者×单位）聚合
- 凭据留痕：经 lex 控制台发生的铸造/吊销事件（明文/哈希均不在库）
"""

from __future__ import annotations

from .auth import AdminActor, require_admin
from .routes import router

__all__ = ["AdminActor", "require_admin", "router"]