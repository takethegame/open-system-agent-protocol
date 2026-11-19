# 参考实现（M2.1 – M2.7 + 持久化 / PCS / 流控 / 恢复）

本目录是 OSAP 0.1 的最小参考实现。已完成路线图的 **M2.1a（信封 + 分帧 + 错误模型）**、**M2.1b（UDS stream 与消息型绑定 + 对端认证）**、**M2.2（身份 + 签名 + 注册表）**、**M2.3（能力模型）**、**M2.4a（同意回执）**、**M2.4b（同意消息流）**、**M2.5a（任务模型）**、**M2.5b（上下文织构）**、**M2.5c（联邦适配器）**、**M2.6（审计链）** 与 **M2.7（三 Agent 演示）**，并补上跨重启的幂等/能力状态、同意流程、任务树与审计账本持久化、PCS 回执签名、公钥登记/轮换/撤销、私钥与回执分库、可插拔私钥存储（JSON / 内存 / macOS・Linux・Windows 密钥环）与 JSON→密钥环迁移工具、上下文解析事件持久化、审计保留与归档、按用户分区的跨 trace 审计顺序、撤销日志与跨进程副本应用、轮询订阅与跨进程撤销测量、恢复同事务审计与 effect 归档、任务与副作用重启恢复、同意流程可选注册表验签与离线验签、逐 Agent 的 admission control 与速率限制（均为 M4 前置）；端到端串接见 [`../demo/`](../demo/README.md)。

规范性内容以 [`../docs/standard.md`](../docs/standard.md) 为准；本目录只回答“这段文字如何落成代码”。

## 1. 范围

| 已实现 | 章节 | 说明 |
|---|---|---|
| 信封模型与校验 | §7.1、§7.9 | 版本、消息类型、JSON Schema、路由键、`task`/`auth`/`deadline` 约束 |
| 错误模型 | §7.7 | 27 个标准错误码、`retryable` 默认值、`osap.error/v1` body |
| 流式分帧 | §7.9 | 4 字节大端长度前缀 + UTF-8 JSON，增量解码 |
| 消息型分帧 | §7.9、§7.10 | 保留原生消息边界，不强制长度前缀 |
| UDS stream 绑定 | §7.9、§7.10 | `AF_UNIX` 监听/连接、长度前缀、每连接独立 `Bus`、`chmod 0600`、串行/线程池/selector/asyncio 四种服务模式 |
| 消息型本地绑定 | §7.9、§7.10 | `AF_UNIX` 数据报 socketpair，一报一消息，无长度前缀 |
| 对端认证 | §7.10 | Linux `SO_PEERCRED`、macOS `getpeereid`+`LOCAL_PEERPID`；可校验 uid/gid/pid/可执行文件，缺字段即拒绝 |
| 8 MiB 上限 | §7.9 | 两种绑定都按 UTF-8 JSON 字节数校验 |
| 握手 | §7.1、§7.9 | `hello` → `welcome`，未握手时拒绝其他消息 |
| 幂等索引 | §7.8 | 同一 `id` 只执行一次副作用；可注入 `JsonStore` 跨重启回放 |
| 持久化状态 | §7.8、§5.5、§10.3、§8、§10.5 | 分节 JSON、原子替换、`fsync`、0600；幂等、能力签发/撤销、同意流程、任务树、effect 日志与审计账本跨重启 |
| 流控与背压 | §7.11、§11.7 | 每身份连接/在途/队列上限与令牌桶；FIFO 等待；`RATE_LIMIT` 带 `reason`、`retry_after_ms` 与队列深度；线程池并发服务；`mode="selector"` 单线程事件循环 |
| 单调时钟 deadline | §7.8 | 墙钟回拨或挂起恢复不得延长超时 |
| Ed25519 签名 | §4.5 | 清单签名、验证、基钥轮换宽限期 |
| Agent 注册 | §4.1–§4.3 | `hello` 校验、App 绑定、公钥绑定、`welcome` 签发 |
| 保留命名空间 | §4.4 | `agent://system/`、`cap://os/`、`ctx://os/`、`event://os/` |
| 注册表索引 | §6.1、§6.2、§6.10 | 清单验签后才索引；能力记录校验、TTL、过期即失效 |
| 发现响应 | §6.5、§6.6 | 只带静态 `consent_hint`，不返回 `policy_verdict`，不泄漏 payload |
| 能力凭证 | §5.2 | schema 校验、签发登记、`cap_id` 索引 |
| 衰减 | §5.3 | 10 条规则逐项检查，返回全部违例维度 |
| 绑定 | §5.4 | `audience` / `task_id` / `subject` 三项无状态校验 |
| 撤销 | §5.5 | 父能力撤销级联到全部后代，撤销可跨“仅持有子凭证”的场景生效；每个新撤销 token 写入 `capability.revocations` 日志（`{seq, cap_id, ts}`）并与撤销集一次 `put_many` 落盘 |
| 撤销分发 | §5.5 | 副本用 `apply_revocations(entries, source=...)` 按来源游标应用批次：重复投递幂等、缺口报领域扩展码 `REVOCATION_GAP`、批内必须连续、写失败回滚后可原样重试；`RevocationWatcher` 按间隔轮询源 store 并自动应用（拉模式，无推送通道、无协议消息） |
| 风险分级 | §5.7 | L3/L4 必须有 `consent_receipt_id`，否则 `POLICY_CONSENT_REQUIRED` |
| 同意回执 | §5.8 | 决策 → 过期 → `cap_id`/`task_id`/`audience` → `actions`/`resources` 的顺序校验 |
| 同意请求 | §10.2 | `consent.request` payload 校验、TTL（`intent_preview.ttl`，缺省 10 分钟）、重复 `request_id` 拒绝 |
| `cap_id` 预约 | §10.3 | 用户决定前先预约；预约态不可用、不可签发，拒绝或撤销后永久不可激活 |
| 授权与拒绝 | §10.2、§10.3 | 只接受请求提供的选项；`allow_once` 强制 `max_uses=1`；拒绝返回原因码与替代方案 |
| 同意激活 | §10.3 | 回执范围校验通过后才 `issue`；重复激活报 `DUPLICATE`；过期回执不可激活 |
| 同意撤销 | §5.5、§10.3 | 回执撤销级联到已签发能力；未激活的预约直接作废 |
| 回执签名 | §10.4 | Ed25519 覆盖去掉 `proof` 的规范化 JSON；`activate` 先验签再查预约，Agent 不能自签 |
| 离线验签 | §10.4 | `pcs.verify_receipt` / `ConsentSigner.verify` 只依赖声明的 PCS 公钥 |
| PCS 公钥登记 | §4.5、§10.4 | 按 `kid` 登记、轮换（带退役宽限）、撤销与有效期；`pcs.keys` 跨重启；`ConsentFlow` 可选按 `proof.kid` 验签；`key_store` 分离私钥；验签失败细分 `AUTH_DENIED` 原因 |
| 私钥存储 | §10.4 | `KeyStore` 契约：`JsonKeyStore` 分节写入、`MemoryKeyStore` 仅内存、`KeyringKeyStore` 走 macOS `security` / Linux `secret-tool` / Windows `PasswordVault`（PowerShell）；后端失败细分 `KeyringError.reason`；记录校验统一在 `signer_of`；`migrate_key_store` 在验证后迁移并在目标确认后删源 |
| 密钥迁移 | §10.4 | `keystore.migrate_key_store(source, target)` 与 `tools/migrate_pcs_key.py`：损坏记录拒绝迁移、目标已占用不同密钥即中止、同记录幂等、删除源之前先验证目标 |
| 任务树 | §8.2、§8.10 | 父/子索引、状态机与非法转换拒绝；可注入 `JsonStore` 持久化整棵树 |
| 委派 | §8.3、§8.5 | 子任务预算 ≤ 父剩余、深度 = 父 + 1、重复 `task_id` 拒绝 |
| 预算 | §8.6 | 逐维比较；运行期超支报 `TASK_BUDGET_EXCEEDED` |
| 取消 | §8.7 | 沿任务树向下传播，`detached` 子任务继续运行 |
| 结果 | §8.8 | 只接受 assignee 的 `result`，`body.schema` 必须等于 `result_schema` |
| 所有权转移 | §8.9 | `handoff` 一次性转移、拒绝即不变、L3/L4 需新回执 |
| 句柄解析 | §9.2 | `resolve` 授权、`audience`/`allowed_agents`、每次解析写 `context.resolve` 审计 |
| 句柄 TTL | §9.3 | `expires_at` 或 `created_at + ttl`；过期即拒绝，不自动续期 |
| 解析审计持久化 | §9.2 | `ContextFabric(store=...)` 把 `context.resolve` 事件写入 `context.events`；重开逐条校验；`limit` 只保留最新 N 条 |
| 上下文对象持久化 | §9.2、§9.5、§9.6 | `context.handles` / `context.blackboards` / `context.objects` 分节落盘；句柄可按标识解析，黑板关闭即清空且不晋升记忆，对象引用计数与墓碑跨重启；每次变更一次原子写入 |
| 长期记忆 | §9.3 | 记忆句柄必须单独持有 `memory.read`，任务能力不隐含 |
| 信息流标签 | §9.4 | `public < personal < sensitive < secret`；派生对象不得降低标签 |
| 任务黑板 | §9.5 | 任务结束即清理/归档，不自动晋升为长期记忆 |
| 对象删除 | §9.6、§9.7 | 先查引用；被引用对象墓碑化，不硬删；写审计事件 |
| 缓存窗口 | §9.7 | 缓存 TTL 钳制到句柄 TTL，被撤销的句柄不会命中 |
| 数据出口 | §9.8 | `sensitive`/`secret` 离开设备需要用户显式放行 |
| OS 权限 | §9.9 | OS 拒绝是外层边界，句柄不能绕过沙箱 |
| 存储声明 | §9.10 | `managed_store` 必须覆盖配额、GC、崩溃恢复、加密、路径安全、删除 |
| 联邦投影 | §6.7 | 原生描述符投影为能力记录；保留 `source`、`native_id`、`version`、`provenance` |
| 原生身份 | §6.7 | MCP server/tool、A2A card/skill、D-Bus bus/path/interface/method、OpenAPI operationId |
| 命名空间映射 | §6.8 | 由 `registry + native_id` 生成确定性的 `cap://federation/...` 名称 |
| 外部信任 | §6.4 | 外部协议内容标 `origin=external`；未验签时不得保持 `system`，归一为 `unverified` |
| 审计链验证 | §10.5、§10.6 | 事件 schema、phase 规则、trace 一致、`audit_id` 唯一、`prev_hash` 链接；`AuditLedger` 追加时生成哈希并在重启时重算 |
| 审计保留与归档 | §10.5 | `AuditLedger(max_events=...)` 把最旧事件移入 `audit.archive.<trace_id>`；live 首条 `prev_hash` 指向归档尾；`history()` 导出完整链；`max_archive=...` 压缩归档并记录 `base` 锚点，kept 前缀仍可端到端验证 |
| 按用户分区与全局顺序 | §10.5 | `AuditJournal` 把每个用户的链写入 `audit.user.<user>.*`，并在 `audit.order.<user>` 记录跨 trace 的连续序号；链、归档与序号一次 `put_many` 原子写入；重开拒绝缺口、重复、时间戳不符与无对应事件；`export()` 输出整用户分区快照（order + 各 trace 全历史） |
| 脱敏导出 | §10.6 | 目标、策略、回执、上下文引用替换为每次导出唯一的盐值承诺；链仍可验证 |
| 回放 | §10.6 | 同一幂等键重复请求只执行一次副作用 |
| 重启任务恢复 | §3.7、§8.10 | `TaskBoard.recover()` 把非终态任务转为 `failed`，或按策略改回 `created`；任务树与 effect 日志一次 `put_many` 原子写入 |
| 恢复审计同事务 | §3.7、§10.5 | `TaskBoard(ledger=...)` 挂共享同一 `JsonStore` 的 `AuditLedger`；`recover()` 用 `AuditLedger.append_many` 一次落盘任务树、effect 日志与审计链；写失败回滚状态、日志与暂存事件，可原样重试 |
| effect 归档 | §8.11 | `TaskBoard(max_effects=...)` 把最旧的已决 effect 移入 `task.effects.archive`（与 live 同一原子写入）；pending/unknown 永不归档，重放闸门不受裁剪影响；effect 变更写失败时回滚内存 |
| 恢复对账 | §8.11、§10.5 | `task.effects` 先写 `effect.intent` 再写 outcome；只有 intent 时标记 `unknown`；`require_replay_allowed()` 在 unknown 时拒绝重放 |
| 对账写回 | §8.11 | `reconcile_effect(intent_ref, outcome=...)` 只接受 `unknown`；确认未执行后才允许显式重试，确认已执行则拒绝重放 |
| 跨用户 | §11.2 | 默认拒绝；显式开启且双方同意才放行 |
| 被攻破的 Bus | §3.6、§11.1 | 0.1 不声称 P0 防护；声明了即判不合约 |

**不在本阶段**：跨进程撤销的推送通道（拉模式日志与轮询订阅已实现）、Windows named pipe / Android Binder / macOS XPC 平台绑定，以及 localhost mTLS。未实现的传输类型会抛 `NotImplementedError`，一致性运行器据此记为 `skip`。

## 2. 目录

```
impl/
  adapter.py            一致性适配器（tools/conformance_run.py --impl 的入口）
  osap/
    __init__.py         公共导出
    bus.py              握手、校验、路由、幂等、错误回执
    audit.py            §8.11、§10.5、§10.6 审计链、持久账本、保留归档与压缩、按用户分区与导出、脱敏导出、回放、恢复
    capability.py       §5.2–§5.6 能力凭证、衰减、绑定、撤销、撤销日志/副本应用与轮询订阅
    clock.py            单调时钟 deadline
    consent.py          §5.8 同意回执与能力范围校验
    consent_flow.py     §10.2、§10.3 同意请求、预约、授权/拒绝、激活、撤销、可选注册表验签
    context.py          §9 句柄、标签、黑板、对象、缓存、存储声明、解析事件与上下文对象持久化
    crypto.py           Ed25519 签名与规范化 JSON
    envelope.py         §7.1 校验（版本 → 类型 → schema）
    errors.py           §7.7 错误码与 OsapError
    federation.py       §6.7、§6.8 原生描述符投影与命名空间映射
    flowcontrol.py      §7.11、§11.7 admission control、令牌桶与背压
    framing.py          §7.9 两种分帧绑定
    identity.py         注册、保留命名空间、App/公钥绑定
    idempotency.py      §7.8 幂等索引
    keystore.py         §10.4 PCS 私钥存储契约与 JSON / 内存 / 三平台密钥环后端、迁移
    pcs.py              §4.5、§10.4 PCS 回执签名、离线验签、公钥登记/轮换/撤销
    registry.py         §6 清单、能力记录、发现
    schema.py           JSON Schema 加载与错误映射
    store.py            原子分节 JSON 持久化（幂等、能力、同意流程、任务树、审计账本与顺序）
    task.py             §8 任务树、预算、取消、结果、handoff、整树持久化、恢复同事务审计与 effect 归档
    transport.py        §7.9、§7.10 UDS stream、消息型 socketpair、对端认证、线程池/selector/asyncio 三种并发模式
  tests/                单元测试（unittest）
```

## 3. 运行

```bash
# 单元测试
python3 -m unittest discover -s impl/tests -t impl

# 只跑已实现的范围
python3 tools/conformance_run.py --impl impl/adapter.py --level C0,C1,C2,C3,C4,C5,C6,C7

# 全量：已实现的出 pass，其余按里程碑 skip
python3 tools/conformance_run.py --impl impl/adapter.py --format md --out report.md

# 三 Agent 端到端演示（注册 → 发现 → 同意 → 委派 → 上下文 → 审计）
python3 demo/run_demo.py
```

## 4. 当前一致性结果

```
python3 tools/conformance_run.py --impl impl/adapter.py
→ 68 cases [C0..C7]: 64 pass, 0 fail, 4 skip
```

| 等级 | 结果 | 说明 |
|---|---|---|
| C0 | 7 pass | 真实 UDS 握手、信封、两种分帧、幂等、单调时钟 |
| C1 | 6 pass | 注册、保留命名空间、验签、App/公钥绑定、轮换 |
| C2 | 5 pass / 1 manual skip | 清单索引、发现响应、TTL |
| C3 | 12 pass | 绑定、衰减、撤销、风险与回执 |
| C4 | 10 pass / 1 manual skip | 委派预算、结果契约、peer 会话、所有权、handoff、重启任务恢复、intent-only 对账 |
| C5 | 11 pass | 解析授权、过期、标签继承、出口、黑板、删除、缓存、存储声明、记忆边界 |
| C6 | 7 pass / 1 manual skip | 三家原生注册表、MCP、A2A、D-Bus 投影与外部信任归一 |
| C7 | 6 pass / 1 manual skip | 审计链篡改、脱敏导出、跨用户、回放、恢复、被攻破 Bus 声明 |

64 条 automated 用例全部通过；剩余 4 条 skip 都是 manual 用例（C2-05、C4-01、C6-08、C7-01）。

C3 的 12 条都命中预期错误码，且实现被断言为“只在目标维度上失败”：C3-04…C3-07 的 `details.violations` 分别只有 `actions`、`resources`、`exp`、`depth`+`constraints.max_depth`。

C4 的 10 条 automated 逐条核对：C4-02 是 `wall_ms` 超出父剩余 8000、C4-03 是 `result_schema` 不符、C4-04 是缺 `session_id`、C4-05 是 `subject` 不是发送方、C4-06 是 L3 handoff 无新回执、C4-07 是 `wall_ms` 已用 6000 > 预算 5000、C4-08 重启后任务变 `failed` 且恢复事件写入可验证链、C4-09 只有 intent 时 effect 标 `unknown` 且重放被 `reconciliation_required` 拒绝、C4-10 是 owner 已变为 calendar。

C5 的 5 条拒绝/接受和 6 条观察也都核对过实际原因：C5-01 只给了 `read` 缺 `resolve`、C5-02 过期早于夹具“现在”、C5-04 `secret` 出口无放行、C5-05 黑板归档且不晋升、C5-07 缓存 900 s 被钳到 600 s、C5-09 OS 权限先于任何授权、C5-10 只有 `task.read` 缺 `memory.read`；C5-03/06/08/11 的 `observe` 报告分别给出标签继承、引用检查与审计、缺失的存储职责、被禁止晋升的来源。

C6 的 7 条 automated 全部命中投影字段：C6-01/02/03 保留三家的 `native_id` 与 `system` 信任；C6-04 把 `calendar-server:create_event` 拆成 server/tool 并保留 `osap.calendar.event/v1`；C6-05 从 `#` 恢复 Agent Card 与 skill；C6-06 从四段式 D-Bus 名称恢复 bus/path/interface/method；C6-07 把外部 MCP 的 `system` 声明归一为 `unverified`，并标 `origin=external`。

C7 的 6 条 automated 同样逐条核对：C7-02 在 `events[1].prev_hash` 被改后于索引 1 断开并报 `AUDIT_CHAIN_INVALID`；C7-03 保留 hash/prev_hash、替换敏感字段后仍验证通过；C7-04 跨用户默认拒绝；C7-05 两次回放只有 1 次副作用；C7-06 只有 intent 时标 `unknown` 并告警；C7-07 声明 P0 防护被判不合约。

`python3 demo/run_demo.py` 把上述模块串成一条可复核路径：三个 Agent 注册、一次发现、一次完整同意流程（request → reserve → grant → activate）、两次委派（supervisor → notes、supervisor → calendar）、一次上下文解析与 16 条审计事件。它用断言固定 C7-01 中可自动化的部分（单 trace、每跳 `causation_id`、链验证、脱敏后仍可验证、恢复不执行副作用），细节见 [`../demo/README.md`](../demo/README.md)。

### 4.1 撤销传播基准（M2 退出标准）

退出标准是“单机 P95 < 100 ms（自测口径）”。参考实现没有跨进程通知，因此口径限定为**进程内可观察传播**：从 `revoke(根)` 返回，到树中每个后代 `is_revoked()` 都为真。

```
python3 tools/benchmark_revocation.py
→ tree: width=6 depth=4 tokens=1555 samples=100
  p50=0.921 ms  p95=1.225 ms  p99=1.830 ms  max=5.969 ms  mean=1.020 ms
  PASS: p95 is below 100.000 ms
```

测量环境为 macOS + Python 3.11，单次 `revoke` 走父→子索引，不再每层扫描全部已签发凭证。`tools/benchmark_revocation.py` 不进入 CI：阈值依赖机器，CI 只验证级联结果与审计条数（`impl/tests/test_capability.py`）。跨进程扇出、持久账本读取和通知通道重试都不在这个数字里。

## 5. 设计决定

### 5.1 校验顺序

`envelope.validate` 的次序是 **版本 → 消息类型 → JSON Schema**。

如果把 schema 放在最前，`{"type": "bogus"}` 会先被 `enum` 拒绝并报 `SCHEMA_INVALID`；但 §7.9 明确要求未知类型返回 `SCHEMA_UNSUPPORTED`。

“缺 `type`”仍按 `SCHEMA_INVALID` 处理：缺失字段是结构问题，不是未知类型。

### 5.2 消息型传输不加前缀

`encode_message` 原样返回对象，只做体积检查。给消息型绑定再套 4 字节长度前缀会让 C0-06 的观察结果变成“不一致”。

### 5.3 deadline 用单调时钟

`Deadline.from_envelope` 只从信封里取**预算**（`deadline - ts`），之后一律用 `time.monotonic()` 计算剩余时间。墙钟只用于解析，不参与判定。

### 5.4 签名覆盖规范化 JSON

`crypto.canonical_bytes` 对去掉 `signature` 字段的文档做 key 排序、最小分隔符的 UTF-8 JSON 编码，再签这段字节。它不是完整的 RFC 8785，但对 OSAP 会签的文档是确定性的，并已写进代码注释供其他实现复现。

### 5.5 注册的判定顺序

`Registrar.register` 依次检查：`from` 与自报 agent 一致 → 非保留命名空间 → agent 归属的 App 与自报 App 一致 → 清单存在 → 清单验签 → 公钥在清单中绑定 → 轮换宽限期。任何一步失败都返回 `AUTH_DENIED`，不泄漏具体是哪一步之外的信息。

### 5.6 注册表只索引“可验证且新鲜”的记录

- 清单：先过 schema，再验签，最后才写入索引（§6.1）。
- 能力记录：schema 通过后检查 `freshness.expires_at`，过期记录返回 `indexed=false`，不进入发现结果（§6.10）。
- 发现结果：`consent_hint` 直接取自记录里的静态策略，任何 `policy_verdict` 都视为不一致（§6.6、§6.9）。

### 5.7 衰减从“原始夹具”派生父凭证

C3-04…C3-07 用 `context` 指向未变异的 `examples/capability.json`，适配器据此合成父凭证：`cap_id = parent_cap_id`、`depth = depth - 1`。父凭证因此与子凭证只在被测维度上不同，不会因为共享变异而把违例“抵消”掉。

### 5.8 接收方从信封解析，而不是从凭证读取

`_receiver` 优先读 `to.agent`；若是 `to.capability`，则通过注册表解析声明该能力清单的 Agent。C3-01 把 `audience` 改成 notes 的 Agent，接收方仍解析为 calendar 的 Agent，所以报 `CAPABILITY_AUDIENCE_MISMATCH`——如果拿凭证自己的 `audience` 当接收方，这条用例会假通过。

### 5.9 “现在”用信封的 `ts`

能力有效性与回执过期都以信封 `ts` 为基准，而不是墙钟。夹具固定在 2026-11-10，这样用例不会随时间流逝而失效，也符合“判定同一条消息时要使用同一个时间基准”。

### 5.10 衰减的预算维度缺失视为放宽

§5.3 要求 `max_budget` 每个维度 ≤ 父预算。若父凭证限定了 `wall_ms`，子凭证却不写这一维，等于把它变成无界，实现判为 `max_budget.wall_ms` 违例；`max_uses` 与 `rate` 同理。

### 5.11 委派超预算与运行期超预算用不同错误码

§8.6 只说“超预算 MUST 返回 `TASK_BUDGET_EXCEEDED`”，但委派时“子预算 > 父剩余”是**拒绝签发**，不是执行中超支；规范也没有委派专用错误码。实现因此按 C4-02 的约定：委派超额报 `POLICY_DENIED`，执行期消耗超额报 `TASK_BUDGET_EXCEEDED`。

### 5.12 任务 `budget.depth` 是绝对深度

`examples/task.json` 的 `budget.depth = 1`，`delegate.json` 的子预算 `depth = 2`。实现把 `depth` 当作绝对委派深度：子任务必须等于父任务 + 1，与能力衰减里的 `depth` 规则一致，这样两条路径不会给出互相矛盾的判定。

### 5.13 handoff 不引入新状态

§8.9 明确“任务状态机不新增 `handoff_pending`”。`TaskBoard.handoff` 要么改了 `owner`/`assignee`/`authority`，要么原样返回 `rejected`；C4-11 的三项 `*_unchanged` 就是对这一点的断言。

### 5.14 取消跳过 detached 子树

`detached=true` 的子任务按 §8.7 可以继续运行，但必须失去父任务能力。实现直接跳过整棵 detached 子树（连它的后代也不取消），因为失去父能力的后代不应再被父链上的取消影响。这一条目前只有单元测试覆盖，C4-01 仍是 manual。

### 5.15 夹具的“现在”取句柄的 `created_at`

C5 没有信封，也没有统一的 `ts`。适配器用 `context-handle.json` 的 `created_at`（2026-11-10T10:14:45Z）作为判定基准，这样 C5-02 把 `expires_at` 改到 09:00:00Z 时必然已过期，而 C5-01/03/04/09/10 的 600 s TTL 仍然有效。用墙钟会让整组夹具随时间失效。

### 5.16 记忆句柄按命名空间识别

§9.3 只规定“长期记忆必须单独授权”，没有定义 wire format。实现把 `ctx://user/memory` 前缀（或 `scope=user` 且句柄含该前缀）视为记忆句柄，要求 `memory.read`；普通 `ctx://` 即使 `scope=user` 仍只需 `resolve`，避免把用户级上下文误判成记忆。

### 5.17 标签违规返回 `observe`，不硬拒绝

§9.4 说派生对象“MUST 继承不低于其来源的标签”，但没说违规时是拒绝解析还是只记录。实现选择“解析成功后报告 `lowered=true` / `effective_label`”，因为 C5-03 的预期就是 `observe`：拒绝派生与抬高标签都被视为合规。真正需要阻止的是出口，由 §9.8 的 `POLICY_CONSENT_REQUIRED` 负责。

### 5.18 身份与 OS 校验先于过期判定

`ContextFabric.resolve` 的顺序是 audience → `allowed_agents` → OS 权限 → 所需授权 → 过期 → 出口。若先看过期，一个无权使用该句柄的 Agent 就能通过 `CONTEXT_EXPIRED` 推断出句柄存在且曾有 TTL。C5-02 的 audience 与句柄一致，所以仍然报 `CONTEXT_EXPIRED`。

### 5.19 被引用对象的删除只墓碑化

§9.6 说被引用对象“SHOULD 延迟删除或标记墓碑”，§9.7 要求删除触发引用清理与审计。实现把“引用数 > 0 且 `hard_delete=true`”判为不合约（`deleted=false`、`tombstoned=false`），软删除则返回 `tombstoned=true`；两种情况都写 `audit_written=true`，因为 C5-06 断言的是“有引用检查与审计事件”，不是“真的删掉了”。

### 5.20 原生身份按内容解析，不按固定位置

D-Bus 的 `native_id` 同时含 bus、interface、path 与 interface.method，冒号又可能出现在各段里。实现先取首段为 bus、取以 `/` 开头的段为 path，再取剩余段中的 interface，最后从尾段剥离 `interface.` 得到 method。这样 C6-06 的 `session:org.example.Calendar:/org/example/Calendar:org.example.Calendar.CreateEvent` 能稳定还原为 bus=`session`、path=`/org/example/Calendar`、interface=`org.example.Calendar`、method=`CreateEvent`。

### 5.21 外部协议的信任只能降不能升

§6.4 要求外部内容默认最低信任，RFS 不得把未验证来源提升为 `system`。实现把 MCP、A2A、OpenAPI、`bridge` 视为外部：即使记录自称 `system`，投影也只报 `unverified`。这一层没有验签器，`verified` 同样降到 `unverified`，宁可保守也不伪造信任。

### 5.22 投影是只读的

`federation.project` 只读取并校验能力记录，不写入原生注册表，也不改写传入的字典；C6-08 的“原生变化后更新或失效”由 `refresh()` 提供新的 freshness 窗口，真正的监听与调度留给 Bus 的注册表缓存（§6.10）。

### 5.23 审计链只验证链接，不重算哈希

夹具里的 `hash` 是短占位串（如 `sha256:1f0c9a7e2b`），不是事件正文的真实摘要；§10.5 也没有规定审计事件的正则化编码。`verify_chain` 因此校验事件 schema、`phase` 规则、`trace_id` 一致性、`audit_id` 唯一性，以及 `prev_hash == previous.hash`，不重新计算正文哈希。乱改正文却保留原 hash 的情况只有真正的内容寻址实现才能发现，已在限制中登记。

### 5.24 脱敏用每次导出唯一的盐值承诺

§10.6 允许脱敏导出证明“链未被篡改 + 字段承诺一致”，但不能恢复明文。`redact_chain` 先验证原链，再把 `target`、`policy`、`consent_receipt_id`、`context_refs` 替换为 `sha256:<salt>:<value>` 的承诺；`hash`/`prev_hash` 原样保留，所以导出后仍能过 `verify_chain`。验证方只能比对承诺，不能反推明文。

### 5.25 `AUDIT_CHAIN_INVALID` 是领域扩展码

§10.5 要求审计校验失败时拒绝，但没有定义审计专用标准码。实现使用 `AUDIT_CHAIN_INVALID`：它不在 §7.7 的 27 个标准码内，也不在保留前缀（`AUTH_`…`TRANSPORT_`）内，因此 `is_standard()` 与 `is_extension()` 都为 false；报告据此把它标为领域扩展，而不是标准错误。

### 5.26 回放与恢复不执行副作用

`replay_effect` 用 `IdempotencyIndex` 把同一幂等键的多次调用折叠成一次副作用；`recover_effects` 只读审计事件，找出没有对应 `effect.executed.intent_ref` 的 `effect.intent`，把状态标为 `unknown` 并要求对账。两者都不调用真实工具，也不把“重放”当成对账。

### 5.27 同意流程先预约、再决定、最后激活

§10.3 要求能力签发与用户决定分离。`reserve_cap_id` 在任何授权前占住 `cap_id`，但预约只登记状态，不写入 `CapabilityAuthority.issued`，所以路由、有效性检查与 `usable()` 都看不到它。`grant` 只生成回执；`activate` 才先跑 `consent.validate`，再调用 `issue`。拒绝把预约标成 `cancelled`，撤销标成 `revoked`，两者都不能再被激活。

### 5.28 回执有效期不得长于请求有效期

`grant` 接受调用方给出的 `expires_at`，但最终值取 `min(请求到期, 回执到期)`：用户同意的是这次请求的范围与时限，回执不能把窗口延长到请求之外。`allow_once` 不依赖调用方参数，直接写 `max_uses=1`。

### 5.29 回执签名与范围校验分离

`consent.validate` 只回答“回执范围是否覆盖能力”；签名验证由 `pcs.require_verified_receipt` 独立完成，`ConsentFlow.activate` 在检查预约状态与范围前先验签。离线审计方可以只验签而不持有能力，也可以只做范围比对；`examples/consent-receipt.json` 仍是范围校验夹具，其 `proof` 不参与验签路径。

### 5.30 流式绑定用真实的 UDS 监听/连接

`UnixStreamServer` 在文件系统路径上 `bind` 后 `chmod 0600`，每个 `accept` 都新建一个 `Bus`，因此握手状态属于连接而不是进程。客户端连接后先做对端认证，再允许任何 `hello`。写路径复用 `framing.encode_stream`，读路径先读 4 字节头、检查 8 MiB 上限，再读正文；超限头会变成 `TRANSPORT_FRAME_TOO_LARGE` 错误帧，而不是让接收方分配超大缓冲区。

### 5.31 消息型绑定用数据报 socketpair

`AF_UNIX` 的 `SOCK_DGRAM` 对保留“一次发送 = 一条消息”的边界，等价于参考实现范围内的 XPC/Binder 语义。`UnixSession.send` 直接序列化 JSON 后调用 `send`，不写长度前缀；接收方一次 `recv` 得到完整消息。`SOCK_SEQPACKET` 在 macOS 不可用，因此没有采用。

### 5.32 对端认证失败即关闭，且缺字段不放过

Linux 用 `SO_PEERCRED` 取 pid/uid/gid，并从 `/proc/<pid>/exe` 解析可执行文件；macOS 用 `getpeereid` + `LOCAL_PEERPID`，再用 `proc_pidinfo` 补 uid/gid、用 `proc_pidpath` 取可执行文件。`PeerPolicy` 只检查显式设置的字段；但字段被设置而平台给不出值时返回 `AUTH_DENIED`，避免“无法验证”被当成“验证通过”。监听端在 `accept` 后立即检查，失败就关闭连接；拒绝的对端不会拿到任何协议消息。

### 5.33 撤销按父→子索引传播

`CapabilityAuthority.issue` 同时维护 `parent_cap_id → {child cap_id}`；`revoke` 从目标出发做一次广度优先遍历，每个凭证只访问一次。旧实现的“反复扫描全部已签发凭证直到不再变化”在深链上是 O(n²)，无法支撑 P95 基准。重复撤销返回 0 且不重复写审计，避免重试制造重复事件。

### 5.34 持久化用分节 JSON 与原子替换

`JsonStore` 把状态放在一个 JSON 对象的多个 section 里（`idempotency`、`capability.issued`、`capability.revoked`、`consent.requests`、`consent.receipts`、`consent.reservations`、`consent.pcs_key`），每次变更整节重写，用临时文件 + `fsync` + `os.replace` 保证读到的要么是旧版本、要么是新版本。文件与临时文件都以 0600 创建；`put` 先序列化候选文档再更新内存，序列化失败时旧状态仍然可用。`put_many` 把多节变更合并为一次替换，同意流程因此不会出现“请求已记下、预约还没落盘”的中间态。

推荐同一个路径只开一个 `JsonStore` 并让 Bus、`CapabilityAuthority` 与 `ConsentFlow` 共享：两个实例各自持有整份快照，后写者会覆盖前者的 section。`CapabilityAuthority` 加载时从 `issued` 重建父→子索引，因此重启后 `revoke(parent)` 仍能级联；`Bus` 命中已落盘的 `id` 时只回放结果，不再执行副作用。

### 5.35 回执签名覆盖去掉 `proof` 的规范化 JSON

`pcs.sign_receipt` 与清单签名共用 `crypto.canonical_bytes`：key 排序、最小分隔符的 UTF-8 JSON，但 `drop=("proof",)`。`proof` 本身是签名元数据（算法、`kid`、签名值），不参与被签正文；这与 JWS 把 `kid` 放在头部、不放进 payload 的做法一致。

`ConsentFlow` 默认生成一个进程内 `ConsentSigner`，`grant` 用私钥签回执，`activate` 在检查预约状态前先验签。验签失败返回 `AUTH_DENIED`，`details.reason` 区分 `receipt_signature_invalid` 与 `receipt_key_unknown`；§7.7 的 `AUTH_DENIED` 明确包含“签名校验失败”，因此不新增错误码。固定顺序保证伪造回执无法通过错误差异探测预约是否已激活。

### 5.36 同意流程与签名密钥一起持久化

`ConsentFlow(store=...)` 把三类状态放在 `consent.requests` / `consent.receipts` / `consent.reservations`：请求记录里的 `requested_at`、`expires_at` 以 UTC ISO 字符串保存，加载时解析回 `datetime`；拒绝、撤销、激活都是单向终态，重启后 `usable()` 与再次 `activate()` 保持原判定。

未注入 `signer` 时，生成的 PCS 私钥写入 `consent.pcs_key`（同一 0600 文件），重启后回执仍能验签；注入的 signer 不落盘，适合外部密钥管理。加载时会用私钥重新导出公钥并与存储值比对，不一致就拒绝启动，避免“密钥换了但回执还在”的静默失败。私钥与回执同处一个文件只是单用户参考实现的选择，生产应改用 OS 密钥环或独立 PCS 服务。

### 5.37 流控以身份为键，等待是显式选择

`AdmissionController` 的每个身份拥有独立的令牌桶、在途计数与 FIFO 等待队列。令牌桶用 `time.monotonic()` 连续补充，上限是 `rate`；`retry_after_ms` 只在 `rate > 0` 时给出。连接配额在握手前按内核可证属性（可执行文件 → pid → uid）计数，消息配额在握手后按 `from` 计数，两者不互相冒充。

`Bus` 默认不等待（`admission_wait=0`），超限直接返回 `RATE_LIMIT`；需要排队的调用方显式传 `timeout`。等待超时只移除自己的 waiter、保留别人的在途槽位，并归还本次预扣的令牌。队列是 FIFO，`priority` 未接入；这满足“不得饥饿”的 MUST，加权公平队列仍是 SHOULD。

`UnixStreamServer` 的默认 Bus 工厂把同一个控制器传给每个连接，因此消息速率跨连接生效；拒绝连接时先回一个 `RATE_LIMIT` 错误帧再关闭，避免静默断开诱发重试风暴。

### 5.38 并发服务用线程池，连接与消息配额共享控制器

`UnixStreamServer.serve_forever(concurrency=N)` 把 accept 与 worker 分开：监听循环只负责接受连接，已接受的连接提交给大小为 N 的线程池，每个 worker 在自己的 session 上 `select` 后调用 `serve()`。`concurrency=1` 保持原来的串行路径，因此现有调用不需要迁移。

默认 Bus 工厂同时传入服务器的 `AdmissionController` 和 `admission_wait`。同一 Agent 的多个连接因此共享在途与排队配额：一个连接里的慢请求会占住该 Agent 的在途槽位，同 Agent 的新连接按 FIFO 等待或被 `RATE_LIMIT` 拒绝；不同 Agent 仍有自己的令牌桶和队列，不会被对方的慢请求拖住。

`close()` 与并发循环的收尾会对所有会话 socket 执行 `shutdown(SHUT_RDWR)`，让阻塞在 `receive` 的 worker 退出。`max_messages` 在并发模式下是 best-effort 停止条件：已受理但尚未完成的回复也占用上限，失败时会归还；它用于有界测试与优雅停止，不是协议级配额。

`serve_forever(mode="selector")` 改用单线程事件循环：监听 socket 与所有已接受的 session 注册到同一个 `selectors.DefaultSelector`，可读即服务一条消息。断开、发垃圾或被错误信封终止的 peer 会被摘除并关闭，不影响循环继续服务其他连接。连接与消息配额仍由同一个 `AdmissionController` 执行，`max_messages` 同样只统计已送出的回复。半帧停滞的 peer 仍可能让循环阻塞到该帧处理完（没有双工读缓冲），这是与线程池的关键差距。

`serve_forever(mode="asyncio")` 用 asyncio 事件循环加缓冲分帧协议（`_AsyncioStreamProtocol`）：字节按连接缓冲，半帧停滞的 peer 只占住自己的连接，不再阻塞他人——这是 selector 模式给不了的保证。消息分发复用每连接 `Bus`，`OsapError` 以标准错误信封应答，连接配额拒绝仍先发 `RATE_LIMIT` 信封再关闭。**关闭规则**：macOS 上从其他线程关闭 kqueue 正在监听的 fd 会让 `kevent()` 永久阻塞（已用最小复现验证），因此 asyncio 模式下 `close()` 只通过 `call_soon_threadsafe` 通知 loop，由服务线程在自己的收尾里关闭 socket；`UnixSession.close` 对 asyncio 持有的 socket 容忍关闭失败。三种模式共享同一配额与 `max_messages` 语义；分发仍是同步的，慢处理会串行化 loop——并行化要靠平台原生绑定（XPC/Binder/named pipe，仍不在本阶段）。

### 5.39 任务树用无损快照持久化

`Task.snapshot()` 是给调用方的摘要，只有 `task_id`、`owner`、`assignee`、`status`、`budget` 与 `authority`，不足以恢复状态机。持久化改用 `Task.to_state()`：它额外保存 `root_task_id`、`parent_task_id`、`session_id`、`result_schema`、`consumed` 与 `detached`，因此重启后预算消耗、父子链和 detached 子树判定都不会丢失。

`TaskBoard(store=...)` 把整棵树写进 `task.tasks`，每个变更方法在内存修改完成后写一次：`add`、`transition`、`cancel`、`delegate`、`handoff` 各自最多一次整节写入，`cancel` 遍历整棵子树也只写一次。`delegate` 直接调用内部插入，避免再经 `add()` 写第二遍；`transition` 传入相同状态或 `handoff` 被拒绝时不写盘。`Task.from_state()` 在加载时检查对象形状、键与 `task_id` 一致、状态合法、预算/`authority`/`consumed` 为对象、`detached` 为布尔，损坏的 section 直接抛 `ValueError`，不会得到半棵树。`TaskBoard.audit` 与其他子系统的审计一样只在内存。

### 5.40 审计账本自己生成并重算规范哈希

`verify_chain` 只验证夹具已有的 schema、trace、`audit_id` 与 `prev_hash` 链接，因为夹具 hash 是占位串，规范也没有固定审计编码。`AuditLedger` 负责写入侧：`append` 补齐 `trace_id`、`audit_id`、`ts`，把 `prev_hash` 设为当前链头，再用 `crypto.canonical_bytes`（key 排序、最小分隔符、去掉 `hash` 的 UTF-8 JSON）计算 `sha256:` 哈希。它因此可以承诺“正文改了、hash 没改”会被发现。

每条事件原子写入自己的 `audit.chain.<trace_id>` section，多个 trace 可以共享同一个 store。重开时先校验 section 形状与 trace_id，再调用 `verify()`：先跑 `verify_chain`，再逐条重算正文哈希。断链、重复 `audit_id`、正文不匹配与 trace 不一致都返回 `AUDIT_CHAIN_INVALID`；形状错误返回 `ValueError`。加载失败不会留下半个账本，调用方应据此让 L3/L4 保持关闭（§3.7）。`chain()` 返回深拷贝，可直接交给 `redact_chain`。

### 5.41 PCS 公钥登记只存公钥，状态与可用性分开

`KeyRegistry` 是 `ConsentSigner` 的分发侧：按 `kid` 保存 `public_key`、生命周期状态与时间戳，永远不接触私钥。`state_of` 只返回存储的 `active` / `retired` / `revoked`；`usable(kid, at=...)` 再叠加 `not_before`、`not_after` 与退役后的 `grace_until`。这样“键已退役”与“宽限期内仍可验旧回执”是两个可分别检查的事实，撤销则是终态。

`register` 拒绝重复 `kid`，换键必须走 `rotate`；`rotate(kid, new_public_key, new_kid=..., grace_seconds=...)` 把旧键标为 `retired`、写入 `retired_at` 与 `grace_until`，新键从 `active` 开始。`revoke` 首次返回 `True`、重复返回 `False`，不会重复写盘。`verify_receipt` 从 `proof.kid` 查表，先判可用性再验 Ed25519；`require_receipt` 把失败原因写进 `AUTH_DENIED.details.reason`（`receipt_key_unknown`、`receipt_key_revoked`、`receipt_key_not_yet_valid`、`receipt_key_expired`、`receipt_signature_invalid`）。

接入 `JsonStore` 时每次变更原子重写 `pcs.keys`；重开逐条校验 `kid` 一致、公钥是有效 32 字节 Ed25519、状态合法、时间戳可解析、窗口不倒置，损坏就抛 `ValueError`。

### 5.42 同意流程按需用注册表验签

`ConsentFlow(registry=...)` 是可选路径。配置后，`activate` 调用的 `verify_receipt` 会按回执的 `proof.kid` 查表，先检查撤销、`not_before`/`not_after` 与退役宽限，再用登记的公钥验 Ed25519；因此验证方可以持有自己的 `ConsentSigner`，只共享签发方的公钥，不需要 PCS 私钥。未配置注册表时仍回退到本地 signer，单进程行为与之前一致。

`publish_pcs_key()` 把本流程的公钥幂等登记进注册表：同 `kid` 同公钥返回已有记录，同 `kid` 不同公钥或已撤销键抛 `ValueError`。注册表不会自动登记，避免验证方进程把自己生成的无关密钥写进共享 store；漏登记会让 `activate` 以 `receipt_key_unknown` 拒绝。

### 5.43 私钥与回执状态分库

`ConsentFlow(key_store=...)` 把生成的 `consent.pcs_key` 写入独立 store；回执 store 只保留 `consent.requests`、`consent.receipts` 与 `consent.reservations`。不传 `key_store` 时仍回退到原来的单 store 布局，因此现有调用不变。签发方重开时从 `key_store` 恢复同一个 signer，回执仍可验签。

`ConsentFlow.verifier(registry=..., store=...)` 是验证方工厂：它要求一个注册表，并注入与签发方无关的临时 `ConsentSigner`，因此构造验证方不会向回执 store 写入任何密钥。验证方只打开回执 store 与公钥注册表即可 `activate` 或 `verify_receipt`；若签发方没有把公钥发布到注册表，验证仍然以 `receipt_key_unknown` 失败。

### 5.44 私钥存储是可替换的后端，不是一种文件格式

`keystore.py` 把“私钥存在哪里”收敛成一个三方法契约：`load()` 返回记录或 `None`，`save(record)` 写入，`delete()` 可选。`ConsentFlow(key_store=...)` 接受任意 `KeyStore`；直接传 `JsonStore` 时由 `as_key_store` 包成 `JsonKeyStore`，因此旧调用与 0600 分节布局都不变。

三个后端各有明确边界：

- `JsonKeyStore` 复用 `JsonStore` 的原子写入，仍是文件系统权限保护，不是加密存储；
- `MemoryKeyStore` 只活在进程内，适合不需要签发的验证方与测试，重启后密钥消失；
- `KeyringKeyStore` 调用 macOS `security`、Linux `secret-tool` 或 Windows `PasswordVault`（经 PowerShell），`platform` 与 `runner` 可注入，所以测试不碰真实密钥环；缺少对应 CLI 时构造即 `KeyringError(backend_missing)`，不会悄悄退回文件。查找/写入失败也细分 `lookup_failed` / `store_failed`，并保留 `returncode` 与 `stderr`。

记录校验集中在 `signer_of`：必须是对象、`kid` 非空、`private_key` 能构造 Ed25519、`public_key` 若存在必须与私钥推导出的公钥一致。三个后端因此对同一种损坏输入给出一致的 `ValueError`，不会出现“JSON 后端拒绝、密钥环后端接受”的差异。

macOS 的 `security add-generic-password` 没有 stdin 形式，密钥只能作为命令行参数传入，同用户的其他进程在参数列表里可能看到；Linux 的 `secret-tool store` 走 stdin。前者只作为开发便利，生产应使用原生密钥环绑定。

### 5.45 上下文只持久化解析事件

`ContextFabric(store=...)` 把每次 `resolve` 的允许/拒绝事件写入 `context.events`，重开时逐条校验 `action`、`decision`、`handle`、`reason` 与 `agent`/`label` 的类型，任何损坏直接 `ValueError`，不会恢复半个日志。事件里的 `handle` 仍由调用方传入，因此持久化的是“谁在何时解析了哪个句柄”，不是句柄注册表。

`limit` 提供最小的保留策略：超过上限时丢掉最旧的事件，追加与重开都套用同一规则，内存列表与文件不会出现长度漂移。`limit=0` 表示只保留进程内可见性，等于关闭持久化内容，但仍会创建一个空数组分节。

写入前会拒绝没有 `handle` 标识的解析请求，因为这种事件无法通过重开校验；这是一处刻意的 fail closed，避免一次畸形调用把整个分节写成不可恢复状态。

### 5.46 审计保留通过归档段保持可验证

`AuditLedger(max_events=N)` 不直接截断链。超过上限时，最旧的 `len - N` 条事件被移入 `audit.archive.<trace_id>`，live 与归档通过一次 `put_many` 原子写入；live 首条事件的 `prev_hash` 仍指向上一条归档事件的 `hash`，所以从 `GENESIS_HASH` 到最新一条仍是一条完整可验证的链。

`verify()` 因此多了一步锚点检查：live 首条 `prev_hash` 必须等于归档尾 `hash`，没有归档时等于 `GENESIS_HASH`；归档自身还要满足从 genesis 开始、schema 合法、链接正确与正文哈希可重算。被“重新生根”的 live 链（例如归档被删除或替换）会立刻失败，而不是被当成一条更短的新链。

`history()` 返回归档 + live 的时间顺序单链，可直接交给 `redact_chain`；`archived_events` 返回分离副本。`append` 的重复 `audit_id` 检查同时覆盖 live 与归档，避免已归档的 id 被重新写入。重开时是否继续裁剪由新实例的 `max_events` 决定，已有归档不会被丢弃。

### 5.47 重启恢复先落 intent，再把未知副作用挡在重放之外

`TaskBoard` 把 §8.11 的副作用过程写进 `task.effects`：`record_effect_intent()` 在副作用前落 `pending`，`record_effect_outcome()` 落 `executed`，同一 intent 的重复 outcome 幂等。`recover(policy=...)` 把所有非终态任务改为 `failed`（或 `reschedule` 时改回 `created`），把所有 `pending` effect 改为 `unknown`，并用一次 `put_many` 同时写 `task.tasks` 与 `task.effects`；没有变化时不写。任务状态没有 `unknown` 枚举，因此按 §3.7 转为 `failed`；`unknown` 描述的是副作用结果，不是任务状态。

恢复是策略覆盖，不是 §8.10 的普通转换：普通 `transition("created" → "failed")` 仍被拒绝，只有重启恢复可以把非终态任务直接推进到 `failed`。第一次恢复后，`fail` 策略下所有任务已终态（`reschedule` 策略下留在 `created`）；再次恢复不会重复写审计，但仍会报告尚未对账的 `unknown` effect。

`recover()` 返回的 `audit` 是完整审计事件：任务恢复写 `task.failed`（重调度写 `task.created`），intent-only effect 写 `error` 且 `extensions.reason=effect_outcome_unknown`。`TaskBoard` 不持有 `AuditLedger`，调用方显式追加，因此两个存储的写入仍不是同一事务。

重放不靠约定：`require_replay_allowed()` 对 `pending`/`unknown` 抛 `POLICY_DENIED` 且 `details.reason=reconciliation_required`；对“对账确认已执行”的 effect 抛 `already_executed`。只有正常记录的 `executed`（幂等路径）或确认 `not_executed` 的 `reconciled` 记录可以继续。`reconcile_effect(intent_ref, outcome=...)` 只接受 `unknown`，把结果写回 effect 日志，不用重放代替对账。

C4-08 与 C4-09 因此从 manual 变成 automated：适配器先在临时 `JsonStore` 上建 board，丢弃内存实例后重开，恢复并重开 `AuditLedger` 验证链；C4-09 还写入 `effect.intent`，在 outcome 前“崩溃”，恢复后断言重放被拒。

## 6. 已知限制

1. **部分内存态**：幂等索引、能力签发/撤销、同意流程、任务树、effect 日志、审计账本与 PCS 公钥可通过 `JsonStore` 跨重启，但清单/能力注册表、注册表轮换状态与缓存窗口仍在进程内；持久化也没有 TTL 清理、压缩或多写者协调。
2. **开发密钥环**：一致性适配器在导入时生成一次性 Ed25519 密钥并为示例 App 签清单。示例里的 `base64url-example-*` 是占位字符串，不是真实密钥。
3. **OS 认证只覆盖 Linux/macOS 本地 socket**：已实现 `SO_PEERCRED` / `getpeereid` / `LOCAL_PEERPID` 与可执行文件解析；audit token、package identity、代码签名和 Windows SID 都未实现。
4. **不是平台原生绑定**：只有 `AF_UNIX` stream 与数据报 socketpair，没有 XPC、Binder、named pipe 或 localhost mTLS；对端认证是 uid/gid/pid/可执行文件，不是平台代码签名。
5. **恢复审计事务要求同库**：`TaskBoard(ledger=...)` 可以把任务树、effect 日志与审计链放进同一次 `put_many`，但前提是 `AuditLedger` 与 board 共享同一个 `JsonStore` 实例（构造时校验）；ledger 用独立文件时事务无从谈起。`require_replay_allowed()` 仍只是闸门，绕过该 API 的直接副作用不受保护。
6. **能力凭证只做结构校验**：能力 `proof.sig` 仍未验签，`cap_id` 也未由 CA 密钥覆盖；PCS 回执的签名、登记、轮换与撤销已由 `pcs.py` 覆盖，能力凭证本身仍待补。
7. **`max_uses` 未计数**：衰减时比较上限，但使用次数没有落账，重放同一凭证不会被扣减。
8. **撤销分发是拉模式**：`revoke` 把新撤销写入 `capability.revocations` 日志并原子落盘；另一进程可用 `apply_revocations(entries, source=...)` 拉取，或用 `RevocationWatcher` 按间隔轮询源 store 自动应用（失败下一轮重试，源文件永不写入）。没有推送通道、订阅协议或平台通知，§5.5 的“通知受影响 Agent”延迟受轮询间隔支配；`tools/benchmark_revocation.py --cross-process` 给出 revoke → 副本 `is_revoked()` 的端到端数字（含一个轮询间隔），与进程内 P95 不可比。
9. **委派未校验能力链**：`delegate` 只检查任务预算与深度，没有把 `delegated_capability` 与父能力凭证做完整衰减比对（夹具里没有父凭证）。
10. **上下文持久化仍不是完整存储层**：`ContextFabric(store=...)` 可跨重启保留解析事件、句柄注册表、任务黑板与对象元数据/墓碑，但缓存窗口仍是纯计算，没有句柄撤销，也没有按用户分区；黑板关闭后只保留条目数与 `promoted_to_memory=false`，不保留条目内容。
11. **没有真实对象存储**：`delete_object` 只返回判定结果，不触碰文件系统；`storage_declaration` 只核对声明，不实现配额、GC 或加密。
12. **联邦只做投影**：没有监听原生注册表变化，也没有按 TTL 自动刷新；C6-08 仍是 manual。MCP/A2A/OpenAPI 的外部签名未验证，因此统一降为 `unverified`。
13. **`verify_chain` 不重算正文哈希**：对夹具链只验证事件 schema、trace、`audit_id` 与 `prev_hash` 链接；夹具的 hash 是占位串，规范也未固定编码。`AuditLedger` 对自己写入的事件使用统一的规范编码并在重启时重算正文哈希，但它不是完整 RFC 8785。
14. **缓存窗口未持久化**：`cache_window` 只按句柄 TTL 与已用时间计算窗口，不记录具体缓存条目；重启后无法判断某个缓存值是否仍可命中，只能重新解析句柄。
15. **64 个 pass 覆盖全部 automated 用例**，但不覆盖 4 条 manual 的跨 App、原生注册表 TTL 与跨进程撤销语义。
16. **同意流程可持久化但不分发**：接入 `JsonStore` 后请求/回执/预约跨重启，但审计仍在内存，也不会把同一请求广播给多个 Bus；两个 flow 实例共享同一 store 时仍是单写者。
17. **回执签名有本地密钥，注册表验签与分库都是可选的**：`ConsentFlow` 用 Ed25519 签回执；不传 `registry` 时 `activate` 仍用自己的 PCS 公钥验签。传 `registry` 后按 `proof.kid` 查表，验证方不需要 PCS 私钥，但必须显式 `publish_pcs_key()`。传 `key_store` 后私钥移出回执 store；不传时私钥与回执仍同处一个 0600 JSON 文件。默认后端仍是明文 JSON，密钥环只是可选后端。
18. **单用户**：一个 `ConsentFlow` 只绑定一个 `user://`，没有多用户会话、代理同意或组织策略。
19. **三种服务模式，平台异步绑定仍缺**：`concurrency=N` 线程池高连接数时成本线性增长；`mode="selector"` 消掉了每连接线程但半帧停滞可阻塞循环；`mode="asyncio"` 有双工读缓冲但分发仍是同步的，慢处理串行化 loop，也没有按 Agent 的加权调度。XPC/Binder/named pipe 平台传输不在本阶段。`max_messages` 在后两种模式下是 best-effort 停止条件，不是严格的协议配额。
20. **同 uid 不等于同一 App**：未设置 `PeerPolicy.executable` 时，同一用户的其他进程也能通过；生产绑定应同时固定可执行文件或平台代码签名。
21. **撤销传播 P95 只覆盖进程内**：基准测量 `revoke` 标记与 `is_revoked` 观察，不含跨进程通知、持久账本写入或重试；跨设备传播需要 0.2 的撤销分发机制。
22. **审计顺序只在单个用户分区内**：`AuditJournal` 为每个 `user://` 维护一条跨 trace 的连续序号，但没有跨用户或跨设备的总序，序号也不携带因果信息（只反映写入顺序）；`max_archive` 压缩归档后，被丢弃的最旧事件不再参与重复 `audit_id` 检查，也不再能从创世验证。`Bus`、`TaskBoard` 与 `ContextFabric` 也不会自动追加事件，需调用方显式写入。live 与归档每次仍整节重写，`verify()` 的成本随保留的归档增长。
23. **公钥注册表是本地 API**：`KeyRegistry` 没有对应的规范信封，跨 Bus/跨设备分发仍靠共享 `JsonStore` 或带外；`ConsentFlow` 的可选注册表验签也依赖同一份键存储；撤销不会推送给已持有旧公钥的验证方，同一 store 仍是单写者，宽限比较也依赖本地时钟。
24. **密钥环绑定仍是 CLI 包装**：Windows 路径经 PowerShell 的 `PasswordVault`（需 Windows PowerShell 5.1 的 WinRT 投影），未在真实 Windows 上端到端验证；macOS 路径仍把密钥放在 `security` 的命令行参数里。`migrate_key_store` 与 `tools/migrate_pcs_key.py` 覆盖单条记录迁移，但没有跨密钥环条目/多账号迁移，也不会自动在迁移后重建 `ConsentFlow`。

## 7. 与规范的偏差登记

| 位置 | 偏差 | 处理 |
|---|---|---|
| `welcome` 的 `body.schema` | 规范未定义 `osap.welcome/v1` 的字段 | 返回 `osap`、`session_id`、`app`、`features`、`limits`，等 M2.4 定稿后回写规范 |
| 未知但已定义的消息类型 | 规范未规定“已知类型尚未实现”的错误码 | 抛 `NotImplementedError`，由适配器记为 `skip` |
| 注册表索引失败的错误码 | 规范未为 RFS 定义专用错误码 | 沿用 C2-01/C2-06 的 `SCHEMA_INVALID`，与用例保持一致 |
| 签名规范化 | 未采用完整 RFC 8785 | 采用 key 排序的 UTF-8 JSON，并在 `crypto.py` 里写明；M4 打包时再对齐 |
| 能力凭证 `proof` | 规范要求“MUST 是签名对象”，实现未验签 | 只校验结构；密钥分发与验签待补 |
| 回执验签失败的错误码 | §7.7 没有回执专用码 | 用标准码 `AUTH_DENIED`，`details.reason` 区分 `receipt_signature_invalid` 与 `receipt_key_unknown` |
| 示例回执的 `proof` | 夹具签名是占位串，未绑定任何 PCS 公钥 | 只用于范围校验用例；真实回执由 `ConsentSigner` 生成并可离线验签 |
| PCS 私钥存储 | 规范未定义密钥存储方式 | 参考实现把生成的私钥写入 0600 `JsonStore`；生产应使用 OS 密钥环或独立 PCS 服务 |
| 流控的 `priority` | §7.11 把 `priority` 定为提示，SHOULD 使用加权公平队列 | 参考实现使用 FIFO 且不读取 `priority`；满足 MUST 的“不得饥饿”要求 |
| 流控等待的默认值 | §7.11 允许返回 `RATE_LIMIT` 或让发送方等待 | `Bus.admission_wait` 默认 0，直接拒绝；需要背压等待的调用方显式设置 |
| 回执中的 `agent` | §5.8 未明确要求回执绑定能力 `subject` | 实现额外校验 `receipt.agent == capability.subject`，不改变任何用例结果 |
| `audience` 与 `actions` 的检查顺序 | 规范未规定 | 固定为 `cap_id` → `task_id` → `audience` → `actions` → `resources`，保证同一输入总是同一错误码 |
| 委派超预算的错误码 | §8.6 只定义了执行期超支 | 委派阶段用 `POLICY_DENIED`，执行期用 `TASK_BUDGET_EXCEEDED` |
| 撤销批次的缺口错误码 | §7.7 未为撤销分发定义专用码 | 领域扩展码 `REVOCATION_GAP`（与 `AUDIT_CHAIN_INVALID` 同类，不在 27 个标准码内），副本对缺失批次 fail closed |
| 记忆句柄的识别 | §9.3 未定义记忆 wire format | 按 `ctx://user/memory` 前缀识别，要求 `memory.read` |
| 标签违规的处理 | §9.4 未规定拒绝还是记录 | 解析成功后报告 `lowered`/`effective_label`，对应 C5-03 的 `observe` |
| 被引用对象的删除 | §9.6 用 SHOULD 描述墓碑 | 软删除墓碑化；硬删被引用对象判为不合约 |
| 原生 `native_id` 的格式 | §6.7 给的是建议映射，schema 只要求非空字符串 | 解析失败报 `SCHEMA_INVALID`，不静默投影成空字段 |
| 外部协议信任 | §6.4 要求最低信任，但未规定验签失败时的具体等级 | 一律降为 `unverified`；只有本实现能验证的本地来源才保留 `system` |
| 审计错误码 | §10.5 未定义审计专用标准码 | 使用领域扩展码 `AUDIT_CHAIN_INVALID`，并标明它既非标准码也不在保留前缀内 |
| 审计 hash | 规范未固定规范化编码，夹具 hash 是占位串 | 只验证链接与 schema，不重算正文摘要 |
| 任务状态机的非法转换 | 规范未规定错误码 | 用 `POLICY_DENIED` 并附带 `from`/`to` |
| 结果状态转换 | §8.8 未规定“结果消息自带 `task.status` 时如何校验” | 先校验结果契约，再走 §8.10 状态机；因此对从未启动的任务返回结果会被拒绝 |
| 委派的能力链 | §8.5 要求子能力满足全部衰减条件 | 任务侧只校验预算与深度；能力侧需要父凭证，未在夹具中提供 |
| 消息型本地绑定 | macOS 推荐 XPC、Android 推荐 Binder | 用 `AF_UNIX` 数据报 socketpair 保留消息边界；平台原生绑定留给适配层 |
| 对端可执行文件校验 | §7.10 要求“可执行文件校验” | Linux/macOS 解析可执行路径；其他平台或字段缺失时 `AUTH_DENIED`，不降级为只看 uid |
| 对端认证失败的错误码 | §7.7 没有专用码 | 用标准码 `AUTH_DENIED`，`details.reason` 区分 `peer_mismatch` 与 `peer_field_unavailable` |
