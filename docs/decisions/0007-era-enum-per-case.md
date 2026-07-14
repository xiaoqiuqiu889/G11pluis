# ADR 0007: Era enum + per-case era overrides (P0-7)

| 项 | 值 |
|---|---|
| 状态 | **已接受** (2026-07-15) |
| 触发 | W2 整合修补：技术评审 cron 抓到的 P0-7 阻断 |
| 决策者 | mvs_164fd83880c741be978c0c7f0a49e8e5（综合开发任务 session）|
| 上游约束 | 决策 4（商业化档位 + 多案路径）、ADR 0006（多案准备）|

---

## 1. 背景

`server/engine/types.py` 定义了一个 13 值的 `Era` enum，对齐
`server/config/schemas/world_snapshot.schema.json` 的
`canonicalState.era` enum：

```
pre_1911_qing, 1911_1927_republic, ..., 2012_present_ai_age, present, epilogue
```

这 13 个 era 字符串是为多案 / 多时代项目设计的（《崇祯》是其中
之一，使用 `pre_1911_qing` / `1644_rebellion` 类的值）。

革命街第一案（`case_01_revolution_street`）只需要 4 个 era 字
符串，团队在场景 YAML、合同、客户端侧统一使用**短年份格式**：

- `2008`（photo_lab_2008）
- `2011`（farewell_2011）
- `2024`（reunion_2024）
- `EPILOGUE`（epilogue）

如果第一案直接用 `Era` enum，团队必须从 13 个选项里挑 4 个
跟语义最接近的（`2000_2012_globalization` / `2012_present_ai_age`
/ `epilogue` 等）——这破坏**短年份**作为内部命名约定的稳定性。
如果改 `Era` enum，又破坏 schema 对齐，牵连《崇祯》和其他
未来案。

技术评审 cron 把这个冲突标为 P0-7 阻断。

## 2. 决策

**保留 13 值 `Era` enum 不动（兼容多案路径，包括《崇祯》），
新增 `CASE_ERAS` dict 作为按案追加的 era 短码覆盖。**

具体做法：

1. `server/engine/types.py` 新增 `CASE_ERAS: dict[str, dict[str, str]]`：
   ```python
   CASE_ERAS = {
       "case_01_revolution_street": {
           "2008_photo_lab": "2008",
           "2011_farewell": "2011",
           "2024_reunion": "2024",
           "epilogue": "EPILOGUE",
       },
   }
   ```

2. 新增两个 helper：
   - `is_valid_era_for_case(era, case_slug) -> bool`
   - `legal_eras_for_case(case_slug) -> set[str]`

3. `server/engine/world_snapshot.py:CanonicalState.__post_init__`
   的 era 校验改为：**接受 Era enum 的 13 值 ∪ 全部
   `CASE_ERAS` 值的并集**。

4. 三个值都通过校验时，不区分是来自 Era enum 还是 case-scoped
   覆盖——它们都是合法的 `canonicalState.era` 字符串。

5. schema `server/config/schemas/world_snapshot.schema.json`
   **本 ADR 不要求改**——它的 enum 仍是 13 值的硬约束，是静
   态检查的 source of truth。`CASE_ERAS` 是运行时扩展点。
   当某个 case 的短码需要被 schema 也承认时，**必须在同一
   个 PR 里同时改 schema 和 `CASE_ERAS`**（保持静态 / 动态
   一致）。

## 3. 备选方案

### 方案 A：把 4 个短码直接加进 Era enum
- **优点**：单点修改，schema 也只改一处。
- **缺点**：污染 enum 语义——`2008` 不是"朝代标签"而是"案件
  时间戳"；同时把 case 命名强加到 enum 上，第二个案（例如
  90 年代案）就会有 `1994` / `1996` 这种跟 `Era` 完全
  不同语义的值。
- **否决**。

### 方案 B：让 `canonicalState.era` 改用 case-scoped 字串，删 Era enum
- **优点**：最干净——case 自己声明自己的 era 集合。
- **缺点**：破坏 schema 对齐（schema 仍然是 13 enum），破坏
  《崇祯》对 enum 的依赖，破坏多案路径下的"哪些 era 是历
  史朝代"这一组语义。
- **否决**。

### 方案 C：本 ADR 提议的"CASE_ERAS 覆盖"
- **优点**：
  - Era enum 不动 → schema 不动 → 《崇祯》和多案路径不受影响
  - case 自己声明自己的 era 短码集 → 不污染 enum
  - 加新案只需在 `CASE_ERAS` 加一个 key，**不**改 enum
  - 运行时 + 静态检查可以分别演化（runtime 接受 4 短码；
    schema 仍是 13 enum；如果想 schema 也接受，必须显式同
    步加 enum 值）
- **缺点**：
  - 多了一个全局 dict——但 dict 本身就是 case → sceneId → era
    的明文映射，可读性高
  - 静态（schema）和动态（runtime）可能出现短暂不一致——
    **接受**这个风险，约束是"如要 schema 承认，必须同 PR
    同步"
- **接受**。

## 4. 影响

### 4.1 兼容性
- **向后兼容**：13 值 Era enum 全部保留，第一案以前可能用
  过的 era 字符串仍然有效。
- **前向兼容**：加新案只需在 `CASE_ERAS` 加 key，不动 enum，
  不动 schema。

### 4.2 调用点
- `WorldSnapshot.empty(runId, sceneId, era)` 现在接受
  `case_01_revolution_street` 的 4 个短码之一。
- `CanonicalState(...)` 直接构造时也接受。
- `Resolver` 和 `contract_loader` 应在 hydration 时调用
  `is_valid_era_for_case(era, case_slug)` 做 case-aware
  校验（不在本 ADR 范围，留给 W3 补；本 ADR 只保证
  `WorldSnapshot` 构造期的非法 era 被拒绝）。

### 4.3 测试
- `tests/engine/test_state_machine.py:CaseEraValidationTests`
  新增 6 个测试，覆盖：
  1. 4 个 case-scoped era 全部接受
  2. 5 个 canonical Era 全部仍接受（向后兼容）
  3. 未知 era 被拒绝
  4. 未知 case slug + 非 canonical era 拒绝
  5. `legal_eras_for_case` 返回 union
  6. 未知 case slug 只返回 canonical 13 值

- P0-3 相关 + 6 个 P0-7 测试 = +9 测试；engine 总数从 81
  升到 90。

## 5. 决策后续

- **不在本 ADR 范围**：Resolver / contract_loader 的
  case-aware era 校验、W3 接入时的 era 跨案检查。
- **未来工作**：第二案启动时，需要在 `CASE_ERAS` 加
  `case_02_xxx` 映射；如需要 schema 也承认 short codes，
  同步改 `world_snapshot.schema.json` 的 `canonicalState.era`
  enum。
- **不重做**：决策 1-6 保持不变（不允许在执行阶段改决策）；
  本 ADR 是 P0-7 修补，是工程实现层的决策，不属于产品决策。

## 6. 相关

- 触发：技术评审 cron（2026-07-15）
- 决策源：`docs/design/requirements-review-v1.md` §4 + §5
- 实施：P0-7 patch（`server/engine/types.py` 增 `CASE_ERAS` /
  `is_valid_era_for_case` / `legal_eras_for_case`；
  `server/engine/world_snapshot.py:CanonicalState.__post_init__`
  era 校验改 union）
- 测试：`tests/engine/test_state_machine.py:CaseEraValidationTests`（+6）
