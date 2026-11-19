# ADR-0012: 崩溃恢复与对账模型

- 状态：Provisional
- 日期：2026-11-19
- 关联：`docs/standard.md` §15.12、§8.10–§8.11；`spec/formal/Recovery.tla`

## 背景

崩溃可能发生在“已写 intent、未写 outcome”之间。此时无法仅凭本地状态判断副作用是否发生。重试可能重复执行；不重试可能永远不知道结果。OSAP 需要一个可形式化、可审计、不过度承诺的模型。

## 暂定结论

1. **三态模型**：effect 只有 `pending`（已写 intent、未写 outcome）、`executed`（outcome 已写）与 `unknown`（恢复时只有 intent）。`unknown` 是“需要人工/外部对账”，不是“未执行”。
2. **任务状态**：恢复时非终态任务 MUST 转为 `failed`，或按 `policy="reschedule"` 回到 `created`；不得静默保持 `running`。任务转 `failed` 与 effect 为 `unknown` 可以同时存在。
3. **不自动重放**：`unknown` effect MUST 先对账；`require_replay_allowed()` 对 pending/unknown 返回 `POLICY_DENIED`，对已对账为 executed 的 effect 返回 `already_executed`。只有 `executed` 与 `reconciled(not_executed)` 允许重试。
4. **对账不自动改任务**：`reconcile_effect()` 只写 effect 结果，不替调用方决定任务成功/失败；任务状态由上层策略决定。
5. **不声称 exactly-once**：对不可逆副作用，OSAP 只承诺“至少记录 intent、恢复时标记 unknown、禁止未对账重放”。at-most-once 依赖幂等键与外部系统；exactly-once 不在 0.1 承诺范围。
6. **模型先行**：`spec/formal/Recovery.tla` 是意图/结果/unknown 的权威模型；实现变更 MUST 先更新模型或解释为何模型不适用。

## 后果

- 恢复后可能需要人工对账，运维成本上升。
- 任务与 effect 的一次 `put_many` 是原子的，但审计写入是另一次写；仍存在“已恢复未审计”的窗口（见 `docs/progress.md` §16.4）。
- 重放闸门不是沙箱；绕过 API 直接执行副作用的实现仍可能重复。
- 需要为 `task.effects` 增加 TTL/归档，否则日志无限增长。

## 备选方案

- **自动重试所有 intent**：简单，但可能重复支付/发信。
- **恢复时全部标记失败、不提供对账**：安全，但无法区分“没执行”和“已执行”。
- **两阶段提交到外部系统**：最强，但要求外部系统配合，超出本地协议范围。
- **只做审计、不做状态机**：可观测，但不能阻止重放。

## 重审触发条件

1. 引入自动对账器或外部副作用查询接口；
2. 任务/effect 与审计写入纳入同一事务；
3. `task.effects` 增加 TTL/归档或压缩；
4. 形式化模型扩展到多 Bus、跨设备或外部幂等键。

## 参考

- [`docs/standard.md`](../docs/standard.md) §8.10–§8.11、§15.12
- [`spec/formal/Recovery.tla`](../spec/formal/Recovery.tla)
- [`impl/osap/task.py`](../impl/osap/task.py)（`record_effect_intent`、`recover`、`reconcile_effect`）
- [`docs/progress.md`](../docs/progress.md) §16（恢复实现与已知边界）
