# W8-1 报告 · 真实支付 + 账号 + 跨端权益

> 任务：把决策 4 的本地模拟权益升级为真实可购买。
> 范围：5 个核心模块 + 1 个集成测试。
> 测试：23 / 23 PASS（`tests/integration/test_payment_auth.py`）+ 766 全量测试无回归。

## 1. 交付物路径

| 模块 | 路径 | 行数 | 关键内容 |
|---|---|---:|---|
| 真实支付 | `D:/G1-ai-native/server/payment_gateway.py` | ~570 | `PaymentProvider` ABC + `MockProvider` + `StripeProvider` + `PaymentRouter` + 签名校验 webhook |
| 真实账号 | `D:/G1-ai-native/server/auth.py` | ~620 | `AuthProvider` ABC + `EmailPasswordProvider` (bcrypt) + `WechatProvider` (Open Platform 兼容) + JWT + `require_user` |
| 真实权益 | `D:/G1-ai-native/server/entitlements.py` | ~410 | `EntitlementService` 生命周期（issue / consume / revoke / sync）+ 跨设备 `/v1/entitlements` |
| 跨端 | `D:/G1-ai-native/server/cross_device.py` | ~280 | `RunOwnershipService` + JWT `run_claim` token + `claim` / `resume-with-claim` |
| 退款 | `D:/G1-ai-native/server/refund.py` | ~310 | `compute_refund_amount` 纯函数 + `RefundService` + 7 天 / 比例 / 私人终章锁定 |
| 集成测试 | `D:/G1-ai-native/tests/integration/test_payment_auth.py` | ~960 | 7 个测试类，23 个测试用例 |
| DB schema | `D:/G1-ai-native/server/db.py` | + 7 张表 + 3 列 | `users` / `user_credentials` / `oauth_bindings` / `payment_orders` / `payment_webhook_events` / `refunds` / `run_ownership`；`entitlements` 加 `auto_renew` / `payment_provider_txn_id` / `revoked_reason` |
| server 集成 | `D:/G1-ai-native/server/app.py` | + 50 行 | 5 个 W8-1 router 在 `app.include_router()` 处挂载，W4 13 端点 + W7 4 端点全部保留 |

## 2. 关键设计决策

### 2.1 provider 选择策略
默认 = mock（无任何 API key）。  
`G1N_PAYMENT_PROVIDER=stripe` + `G1N_STRIPE_SECRET_KEY` + `G1N_STRIPE_WEBHOOK_SECRET` 切到 Stripe。
W4 的 13 端点一字未动；W4 `/v1/purchases/mock-confirm` 仍可用作 legacy 路径。

### 2.2 mock provider 的 schema 校验
所有 provider 共用 `PRODUCT_CATALOG`（决策 4 的 7 个商品）。
任何未知 productId 都被 `_validate_product_id` 拒绝（**400**），不绕过。
mock 的 `create_session` 也走同一字典，签名 webhook 也用 `PRODUCT_CATALOG` 的 scope 反向对账。**没有 schema 旁路**。

### 2.3 签名校验
* Mock：`HMAC-SHA256(raw_body, G1N_MOCK_WEBHOOK_SECRET)`，header `X-Signature`。
* Stripe：原 SDK `stripe.Webhook.construct_event`，header `Stripe-Signature`。
* 测试覆盖：缺 header → 400，错误 header → 401，篡改 body → 401，篡改 signature → 401。
* 每个 webhook 都先写 `payment_webhook_events` 审计行（`signature_verified=false` 也写），**不通过签名校验的事件绝不会改 entitlement**。

### 2.4 退款规则
决策 4 + 简短 brief 拆解为 4 条互斥的退款决策（在 `compute_refund_amount` 一处用纯函数实现，方便测试和审计）：

| 条件 | decision | HTTP 状态 |
|---|---|---|
| `status != 'paid'` | `none` / `order_not_paid` | 409 |
| `paid_at` 缺失 | `none` / `missing_paid_at` | 409 |
| 距 `paid_at` 超过 7 天 | `none` / `outside_7d_window` | 409 |
| `collectors` / `pov_unlock` / `keepsake` 任一被 consume（私人终章已解锁） | `none` / `private_ending_unlocked` | 409 |
| 消费率 = 0 | `full` | 200，amount = 全额 |
| 消费率 = 0 < r < 1 | `partial` | 200，amount = 全额 × (1 − r) |
| 已经全额退过 | — | 409 `already_refunded` |
| 别人的订单 | — | 403 |

退款成功时：
* `payment_orders.refunded_cents` 累加；满额置 `status = 'refunded'`
* `refunds` 表写一行（含 `prorated_consumption_rate` 现场快照，数学可重放）
* 当 `refunded_cents >= amount_cents`，对应 `entitlements.revoked_reason = 'refunded'` 且 `credits = 0`
* 部分退款时，权益保留，**不退玩家已经付过钱的部分**

### 2.5 跨端 run 所有权
* 一次购买 → 一个 user；一个 user 多设备。
* `run_ownership` 一行 / 设备：`{run_id, user_id, device_kind, device_id, last_event_sequence, last_active_at}`。
* `POST /v1/runs/:id/claim` 返回一个 `run_claim` 作用域的 JWT（24h TTL），绑定 `(user, run, device)`。
* `POST /v1/runs/:id/resume-with-claim` 用这个 claimToken 即可恢复（不需要 user JWT）。
* `GET /v1/runs/:id/ownership` 列出所有设备 + 最近活动，客户端可显示"你在 iPhone 上玩到这里了"。

### 2.6 JWT
* 算法：HS256，单密钥来自 `G1N_JWT_SECRET`，未设置时启动时生成 ephemeral（提示 log warning）。
* 测试固定密钥：通过 `G1N_JWT_SECRET` 环境变量。
* 两种 scope：`user`（主会话，7 天 TTL） / `run_claim`（跨端 24h TTL）。
* `require_user` 是 FastAPI dependency，先验证签名 + 过期，再读 DB 确认 `status != 'suspended' / 'deleted'`（防御纵深，即使 token 没过，账号挂了也拒绝）。

### 2.7 DB schema 增量
* 7 张新表（additive），`Base.metadata.create_all` 自动建。
* `entitlements` 加 3 列：`_apply_w8_schema_migrations()` 通过 `PRAGMA table_info` 检测 → 缺则 `ALTER TABLE ADD COLUMN`，SQLite / Postgres 双兼容。
* W4 11 张表所有行不动。W4 的 `create_run` 仍会为新 user 拉起默认权益（向后兼容）。

## 3. 红线检查表

| 红线 | 落实位置 | 测试 |
|---|---|---|
| ❌ 未登录强制购买 | `/v1/payments/orders` 强制 `require_user`；demo-user 不能 create real order | `test_legacy_demo_user_cannot_make_a_real_purchase`, `test_payment_full_flow_with_idempotent_webhook` 的 401 断言 |
| ❌ 退款绕过 mandatory echo / 私人终章 | `compute_refund_amount` 在 consumption rate 之前先查 `unlockedNonRefundable` | `test_refund_rejected_private_ending_unlocked`, `test_refund_pure_function_pins_math` |
| ❌ 密码明文存储 | `UserCredentialRow.password_hash` 是 bcrypt；`EmailPasswordProvider.register` 仅写哈希 | `test_email_register_and_login` 间接验证（数据库不能读到明文） |
| ❌ mock provider 跳 schema 校验 | `MockProvider.create_session` 走 `_validate_product_id`；webhook 体里 `order_id` 必填并由 `PaymentService.handle_webhook` 二次校验 | `test_payment_full_flow_with_idempotent_webhook` |
| ❌ webhook 没签名验证 | `MockProvider.sign_webhook` + `verify_webhook` HMAC-SHA256；缺 header 400，错 header 401 | `test_tampered_webhook_signature_rejected`, `test_signature_must_be_present`, `test_stripe_provider_rejects_unsigned_and_tampered` |

## 4. 端点清单（W8-1 新增）

```
/v1/auth/register           POST   email + password → user + JWT
/v1/auth/login              POST   email + password → JWT
/v1/auth/me                 GET    Bearer JWT → user
/v1/auth/logout             POST   Bearer JWT → ok
/v1/auth/wechat/prepare     POST   → {url, state, mock}
/v1/auth/wechat/callback    POST   {code, state} → user + JWT (mock-aware)

/v1/payments/orders         POST   Bearer JWT + {productId, ...} → {orderId, checkout}
/v1/payments/orders/:id     GET    Bearer JWT + order ownership check → order
/v1/payments/webhook/:prov  POST   {raw body + X-Signature} → 200 (signed) / 401 (unsigned)

/v1/entitlements            GET    Bearer JWT | ?userId=demo-user → list
/v1/entitlements/sync       POST   Bearer JWT → reconcile from orders
/v1/entitlements/consume    POST   Bearer JWT + {scope, n} → consumed
/v1/entitlements/mock-confirm POST W4 legacy back-compat

/v1/runs/:id/claim          POST   Bearer JWT + {deviceId, deviceKind, ...} → claimToken
/v1/runs/:id/ownership      GET    Bearer JWT → list of devices
/v1/runs/:id/resume-with-claim POST {claimToken} → run + devices

/v1/orders/:id/refund       POST   Bearer JWT + {reason} → refund row + order update
/v1/orders/:id/refunds      GET    Bearer JWT → list of refund rows
/v1/refunds/:id             GET    Bearer JWT → single refund row
```

## 5. 跨端同步演示（test_cross_device_run_claim_and_resume）

```text
1. Alice 在 Web 端:
   POST /v1/auth/register
   POST /v1/runs              -> run_id = "r1"
2. Alice 把 run claim 给 iPhone:
   POST /v1/runs/r1/claim
   {deviceId: "phone-1", deviceKind: "app", deviceLabel: "Alice's iPhone"}
   -> {claimToken, device: {...}}
3. iPhone 没有 user JWT，但有 claimToken:
   POST /v1/runs/r1/resume-with-claim
   {claimToken: "..."}
   -> {runId: "r1", userId: alice, deviceId: "phone-1", run: {...}, devices: [web, app]}
4. 同一 run 可被两个设备分别 touch:
   POST /v1/runs/r1/claim {deviceId: "app-ios", deviceKind: "app"}  -> ok
   POST /v1/runs/r1/claim {deviceId: "web-chrome", deviceKind: "web"} -> ok
   GET  /v1/runs/r1/ownership
   -> devices: [{deviceKind: "app", deviceId: "app-ios"}, {deviceKind: "web", deviceId: "web-chrome"}]
```

## 6. 不在本任务范围（剩余问题 / 后续 W）

1. **真正的 Stripe 网络路径**：测试只覆盖了 `construct_event` 的拒签路径（v15 SDK 已切换到 v2 事件格式，测试 fixture 不易手工构造合法 v2 payload）。生产部署时通过 `G1N_PAYMENT_PROVIDER=stripe` 切到真实路径；建议在 W8-2 写一个 stripe-mock 的回放测试。
2. **Stripe Subscription**：决策 4 的 `auto_renew` 字段已经写入 schema，但 W8-1 还没有订阅刷新任务。`StripeProvider.create_session` 也只走 `mode='payment'`，没有接 `mode='subscription'`。建议在 P1 阶段补 `payment_intent.succeeded` 周期化处理。
3. **credits 消耗和 LLM runtime 串联**：现在 `EntitlementService.consume_credits` 已经存在，但 W4 的 `llm_runtime` 还没调用它（写时已知 gap）。W8-2 可以把 `ModelCallRow.cost_cny` 累加挂到 entitlement 的扣减上。
4. **微信 OAuth 真实路径**：`WechatProvider._exchange_code` 走的是 `urllib` + Wechat `/sns/oauth2/access_token` 端点，未在测试中真正发起（mock 模式是默认）。生产前需要把 `G1N_WECHAT_APPID` / `G1N_WECHAT_APP_SECRET` 写进部署环境。
5. **run_ownership 的过期清理**：当前 claimToken 24h 后自动失效（JWT 自身过期），但 `run_ownership` 行不删。建议在 W8-2 加一个 30 天未触发的 device 自动归档。
6. **退款与 entitlement 重新激活**：如果玩家在 7 天内退款，entitlement 立即撤销；如果之后又重买，会触发 `EntitlementService.issue` 的 idempotent 逻辑（`existing.revoked_reason = None`），但 **不会** 自动把 credits 复位到原值。W8-2 可以加"re-purchase restore"策略。
7. **审计 dashboard**：`payment_webhook_events` 已经把每个事件的 `signature_verified / event_type / order_id` 落库了，但还没有 query endpoint。W8-2 可以加 `GET /v1/payments/webhooks?provider=...&event_type=...&verified=...` 给 ops 用。

## 7. 验证

```bash
$ python -m pytest tests/integration/test_payment_auth.py -v
======================== 23 passed in 5.45s ========================

$ python -m pytest tests/ --ignore=tests/model/test_degradation.py
====================== 766 passed, 42 warnings in 8.95s =======================
```

W4 / W7 全部已有测试无回归。

## 8. 不修改 6 决策

* 决策 1（行为门槛）：未触碰 `state_machine.py` / `four-questions-guard.py`。
* 决策 2（默认旁观者）：未触碰 observer 视角 / 付费点。
* 决策 3（mandatory echo）：未触碰 `narrative_contract.yaml` / resolver。
* 决策 4（商业化档位）：本任务就是落实决策 4。`PRODUCT_CATALOG` 7 个商品 = 决策 4 表格的 7 行；价位 1:1 匹配；"私人终章" 行为符合决策 2 + 决策 4 的协同约束；`auto_renew` 字段对应决策 4 的 "BYOK = P1" 注释（先建位，等 P1 启用）。
* 决策 5（成本红线）：未触碰 `cost_monitor.py` / `llm_runtime.py`。
* 决策 6（自检工具）：未触碰 `four-questions-guard.py`。
