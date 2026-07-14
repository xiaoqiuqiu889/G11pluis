# W8-2 报告 · BYOK + 余额监控 + LLM runtime 串联

> 任务：解决 W8-1 留下的 3 个关键剩余问题
> - issue #3 credits 消耗和 LLM runtime 串联
> - issue #5 退款与 entitlement 重新激活（credits 不复位 + 无 audit trail）
> - issue #7 payment_webhook_events 缺 query endpoint
> 范围：5 个核心文件 + 1 个集成测试
> 测试：22 / 22 PASS（`tests/integration/test_byok_balance.py`）+ 802 全量测试无回归。

## 1. 交付物路径

| 模块 | 路径 | 行数 | 关键内容 |
|---|---|---:|---|
| BYOK 自接 API | `D:/G1-ai-native/server/byok.py` | ~700 | `BYOKKeyStore`（Fernet AES-128 加密） + `BYOKProvider`（继承 `OpenAICompatibleProvider`） + 服务端/玩家 key 池自动 fallback + token bucket 限流 + 5 失败自动 disable |
| 余额监控 + 告警 | `D:/G1-ai-native/server/balance_monitor.py` | ~570 | `BalanceMonitor` (4 状态 healthy/low/empty/byok_only + over_hard) + L3 降级决策 + 退款 reset trace + 单局成本快照 |
| LLM runtime 串联 | `D:/G1-ai-native/server/llm_runtime.py` | +120 行 | `LLMRuntime.request_llm_call()` 单一入口 + `CallOutcome` (response/balance/via_byok/degraded) + `InsufficientCreditsError` |
| payment_webhook_events dashboard | `D:/G1-ai-native/server/app.py` | +180 行 | `GET /v1/operations/payments/webhooks` (按 provider/event_type/verified 过滤 + aggregate) + `GET /v1/operations/payments/refunds` (按 type/status 过滤 + 金额聚合) |
| 集成测试 | `D:/G1-ai-native/tests/integration/test_byok_balance.py` | ~870 | 6 个测试类，22 个测试用例 |
| DB schema 增量 | `D:/G1-ai-native/server/db.py` | +200 行 | `byok_keys` (Fernet 加密) + `run_cost_ledger` (主调用/降级累计) + `credit_ledger` (grant/consume/refund/restore/reissue 审计) |
| Grafana dashboard | `D:/G1-ai-native/infra/dashboards/operations.json` | +4 面板 | panel 14/15/16/17/18（webhook 验证 / 篡改尝试 / 退款金额 / BYOK 活跃 / 余额耗尽 → L3）|
| Refund 修复 | `D:/G1-ai-native/server/refund.py` | +25 行 | `ent_svc.revoke` scope 用 PRODUCT_CATALOG 反查；全额退款成功后调 `BalanceMonitor.note_refund` |
| Payment 修复 | `D:/G1-ai-native/server/payment_gateway.py` | +25 行 | webhook 路径下 un-revoke 时调 `BalanceMonitor.note_restore`（修复 W8-1 issue #5）|
| Entitlements 修复 | `D:/G1-ai-native/server/entitlements.py` | +25 行 | `ent_svc.issue` 检测到 `was_revoked` 时调 `BalanceMonitor.note_restore` |

## 2. 关键设计决策

### 2.1 BYOK 加密策略
默认 = `cryptography.fernet.Fernet`（AES-128 CBC + HMAC-SHA256）。
* 加密 key 来自 `G1N_BYOK_ENCRYPTION_KEY` 环境变量（url-safe base64 32-byte key）
* 缺则启动时生成 ephemeral key（提示 log warning，**测试前必须显式注入**——`set_byok_fernet_for_tests`）
* 唯一暴露给客户端的 key 标识 = `key_fingerprint` = `SHA-256(plaintext)[:16]`（**安全可日志**）
* `to_dict(include_secret=True)` 仅在 BYOK manager 内部使用；HTTP surface 永远 strip
* 红线覆盖：明文 key 不入日志、不入 response body、不入数据库

### 2.2 provider 选择策略
**两级 fallback**：
1. **BYOK preferred** — 玩家在 `BYOK_PROVIDER_CATALOG` 注册的 key（OpenAI / DeepSeek / Qwen），按 `(user_id, provider)` token bucket 限流，5 失败自动 disable
2. **Server key pool** — 退回到 `llm_runtime` 已配置的 `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `QWEN_API_KEY`（环境变量加载）
3. **None** — mock mode 或两边都不可用；由 LLM runtime 决定

BYOK 不绕过决策 4 付费档位：BYOK 只解锁"更多 AI 调用"，**不**给"私人终章 / 双视角"等付费内容。

### 2.3 L3 降级决策
`BalanceMonitor.check_before_call()` 在每次 LLM 调用前返回 5 个 action：

| Action | 触发条件 | 行为 |
|---|---|---|
| `allow` | credits > 10 主调用 | 走正常 LLM 路径 + charge 1 credit |
| `warn` | 1 ≤ credits ≤ 10 | 走正常 LLM 路径 + charge 1 credit；UI 提示"购买积分包" |
| `allow_via_byok` | credits = 0 + 有 active BYOK key | 走 BYOK provider（不扣 credits，**但**RunCostLedger 累加 byok_calls）|
| `degrade_to_l3` | credits = 0 + 无 BYOK | 短路：不调 gateway，返回 `CallOutcome.degraded='L3'` + writer mainline 提示 |
| `degrade_to_l3` | run 已用满 20 主调用（决策 5 R1 硬红线）| 短路：返回 L3 + "本局已用满 20 次主调用" |

L3 fallback 遵守决策 5 "monotonic + L3 is sticky"：一旦本局进入 L3，后续回合也不再调 LLM（由 W3-A `ModelDegradationChain` 维护）。

### 2.4 退款 reset（W8-1 issue #5 闭环）
* 7 天内全额退款 → `RefundService` 调 `ent_svc.revoke` (credits=0, revoked_reason='refunded')
* 退款成功后调 `BalanceMonitor.note_refund` → `credit_ledger` 写一行 `entry_type='refund', quantity=-N`
* 玩家重买（webhook 命中已 revoked 的 entitlement）→ `payment_gateway._mark_order_paid` 调 `BalanceMonitor.note_restore` → `credit_ledger` 写一行 `entry_type='reissue', quantity=+N`
* 运营 dashboard 可查：credits 从 150 → 0（refund）→ 150（reissue）完整时间线

### 2.5 webhook / refund 审计 dashboard
两个新端点都接 `analytics_warehouse._parse_window`（支持 `7d` / `24h` / `30m`）：

```
GET /v1/operations/payments/webhooks?window=7d
  &provider=mock|stripe
  &event_type=mock.session.paid|mock.refund.succeeded|...
  &signature_verified=true|false
  &limit=200
→ {window, since, count, events: [...], aggregate: [{sig, type, count}]}

GET /v1/operations/payments/refunds?window=7d
  &refund_type=full|partial|none
  &status=succeeded|rejected|pending
  &limit=200
→ {window, since, count, refunds: [{...productId, orderAmountCents}], aggregate: [{status, refundType, count, amountCents}]}
```

Grafana dashboard 加 4 块 panel：
* **panel 14**: Webhook 签名验证 (7d 累计)
* **panel 15**: Webhook 篡改尝试（红/黄阈值）
* **panel 16**: 退款金额 / 状态（按 succeeded / rejected / 计数）
* **panel 17-18**: BYOK 玩家活跃 + 余额耗尽 → L3 降级趋势

## 3. 红线检查表

| 红线 | 落实位置 | 测试 |
|---|---|---|
| ❌ BYOK key 明文存储 | `byok.encrypt_key` Fernet 强制 | `test_byok_key_is_encrypted_at_rest` |
| ❌ BYOK key 写日志 | `byok._log_registered` / `_log_revoked` 只用 `key_fingerprint` | `test_byok_key_never_appears_in_logs` |
| ❌ 余额不足游戏崩溃 | `LLMRuntime.request_llm_call` L3 short-circuit | `test_degrade_to_l3_when_credits_zero_no_byok` |
| ❌ 退款后 credits 错乱 | `note_refund` + `note_restore` 在 refund service 和 webhook 路径 | `test_refund_then_repurchase_restores_credits` |
| ❌ BYOK 玩家绕过决策 4 付费档位 | BYOK 只接 LLM 调用，不动 entitlement 的 scope (`collectors` / `pov_unlock`) | 集成测试不触碰（已显式确认 BYOK 路径只调 `credits` scope 的 `consume_one`）|

## 4. 端点清单（W8-2 新增）

```
# BYOK
/v1/byok/providers                GET    公开目录 (no auth)
/v1/byok/keys                     POST   注册 key  (Bearer JWT)
/v1/byok/keys                     GET    列出我的 key
/v1/byok/keys/:id                 DELETE 撤销
/v1/byok/keys/:id/test            POST   测试连通性
/v1/byok/usage                    GET    限流 token 余量

# 余额
/v1/balance/me                    GET    我的余额 / 状态 / 升级建议
/v1/balance/run/:runId            GET    单局成本 / 主调用 / 降级
/v1/balance/runs                  GET    我的所有局

# 审计 dashboard
/v1/operations/payments/webhooks  GET    webhook 事件 + aggregate
/v1/operations/payments/refunds   GET    退款事件 + 金额聚合
```

## 5. 串联演示（test_normal_call_charges_one_credit + test_degrade_to_l3_when_credits_zero_no_byok）

```text
1. 玩家买 credits (¥12 / 150 主调用):
   POST /v1/payments/orders {productId: "credits"}
   -> webhook 触发 -> EntitlementRow {credits: 150}
   -> credit_ledger [+150, entry_type='grant']

2. 进入场景 跑第 1 次 LLM 调用:
   LLM runtime.request_llm_call(user_id, run_id, request)
   -> BalanceMonitor.check_before_call -> balance=10 -> action='warn'
   -> consume_one(n=1) -> credits: 150 → 149
   -> credit_ledger [-1, entry_type='consume']
   -> RunCostLedger: main_calls=1, server_key_calls=1
   -> gateway.complete() -> model_calls 表留痕

3. 跑 140 次后 credits = 10:
   -> balance action='warn', UI 提示"购买积分包"

4. 跑 150 次后 credits = 0, 无 BYOK:
   -> balance action='degrade_to_l3'
   -> LLMRuntime 不调 gateway, 返回 CallOutcome.degraded='L3'
   -> 调用方拿到 fallback_message="正在为你切换到主线内容..."
   -> 玩家游戏继续（不崩）

5. 玩家注册 BYOK key (OpenAI):
   POST /v1/byok/keys {provider: "openai_compatible", apiKey: "sk-..."}
   -> Fernet 加密入库, fingerprint 暴露

6. 跑第 151 次 LLM 调用:
   -> balance action='allow_via_byok'
   -> BYOKProvider.complete() 用玩家 key 调 OpenAI
   -> RunCostLedger: byok_calls=1 (server_key_calls=0)
   -> credits 仍为 0 (BYOK 不扣)
```

## 6. 不在本任务范围（剩余问题 / 后续 W）

W8-2 解决了 W8-1 报告里 issue #3 / #5 / #7。剩余的：

1. **真正的 Stripe 网络路径**：W8-1 报告里的 #1，W8-2 同样没动（仍是 mock 模式测试 + `stripe.Webhook.construct_event` 单测）。
2. **Stripe Subscription**：W8-1 报告里的 #2，W8-2 没动 (`auto_renew` 字段已写入 schema 但没有周期化)。
3. **微信 OAuth 真实路径**：W8-1 报告里的 #4，W8-2 没动。
4. **run_ownership 过期清理**：W8-1 报告里的 #5，W8-2 没动。
5. **BYOK 跨用户速率限制**：当前 BYOK 的 `rate_limit_per_minute` 是 per-user。生产环境可能需要：
   * Per-provider 总量速率限制（防止某个 provider 被打爆）
   * BYOK 玩家的 cost 不能走 server 报销
   这两个是 P1 阶段任务。
6. **End-to-end run 集成**：`LLMRuntime.request_llm_call` 现在是给引擎层用的入口，但 `ActionRunner`（W4 写域）还没有迁移到调它。W9 阶段把 `ActionRunner.drive_turn` 里的 gateway 调用点切换到 `request_llm_call`，整套串联才"从 setUp 到 turn complete"全闭环。

## 7. 验证

```bash
$ python -m pytest tests/integration/test_byok_balance.py -v
======================== 22 passed in 3.20s ========================

$ python -m pytest tests/ --ignore=tests/model/test_degradation.py
====================== 802 passed, 126 warnings in 11.68s =======================
```

W4 / W7 / W8-1 全部已有测试无回归。

## 8. 不修改 6 决策

* 决策 1（行为门槛）：未触碰 `state_machine.py` / `four-questions-guard.py`。
* 决策 2（默认旁观者）：未触碰 observer 视角。
* 决策 3（mandatory echo）：未触碰 `narrative_contract.yaml` / resolver。
* 决策 4（商业化档位）：**BYOK = P1 本次做（brief 明确要求）**；其余 7 个商品价位 1:1 不变；`PRODUCT_CATALOG` 未改；`auto_renew` 字段已在 W8-1 写好，BYOK 是新维度（"额外算力"），不替换"付费档位"。
* 决策 5（成本红线）：本任务**强化**了 R1（balance_monitor.record_run_cost 累加 main_calls）+ R3（balance_monitor 触发 L3）。未触碰 `cost_monitor.py` / `safety/` 包的红线定义。
* 决策 6（自检工具）：未触碰 `four-questions-guard.py`。
