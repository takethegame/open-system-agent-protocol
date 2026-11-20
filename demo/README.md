# 三 Agent 演示（M2.7，第 7 节为 M4 加固演示）

`demo/run_demo.py` 把参考实现串成一条可复核的端到端路径：`notes-agent` 与 `calendar-agent` 在同一个 `supervisor` 下完成一次“查笔记 → 找空档 → 准备 tentative 事件”的任务，然后**模拟一次崩溃并演示重启恢复**。它不引入新的协议语义，只调用 `impl/osap/` 中已经通过一致性用例的模块。

规范性内容以 [`../docs/standard.md`](../docs/standard.md) 为准；本目录只回答“这些模块如何协同”。

## 1. 运行

```bash
python3 -m pip install -r requirements.txt
python3 demo/run_demo.py
```

脚本只使用标准库与 `cryptography`，在任意工作目录运行都可以；不需要网络、不需要真实 App，也不读取墙钟。

预期结尾：

```text
== demo complete ==
registered=3 discovery=1 consent=1 receipt=verified delegated=2 context=1 audit=verified
trace=complete redaction=verified recovery=complete
crash=recovered replay=blocked reconcile=not_executed idempotent=across_restart blackboard=dies_with_task
```

任何一步不符合断言都会以非零状态退出，并打印 `demo assertion failed: ...`。CI 在单元测试之后执行同一条命令。

## 2. 演示了什么

| 步骤 | 调用 | 章节 | 对应用例 |
|---|---|---|---|
| 1. 清单与注册 | `crypto.sign_document`、`identity.Registrar` | §4.1–§4.5、§7.1 | C1-01…C1-06 |
| 2. 能力发现 | `registry.Registry.index_record` / `discover` | §6.5、§6.6 | C2-02、C2-03 |
| 3. 同意流程与能力 | `consent_flow.ConsentFlow.request` / `reserve_cap_id` / `grant` / `activate`、`pcs.verify_receipt` | §5.2–§5.8、§10.2–§10.4 | C3-02、C3-03 |
| 4. 两次委派与结果 | `task.TaskBoard.delegate` / `transition` / `accept_result` | §8.3–§8.8 | C4-02、C4-03、C4-07 |
| 5. 上下文解析 | `context.ContextFabric.resolve` | §9.2–§9.4 | C5-01、C5-10 |
| 6. 审计链与导出 | `audit.AuditLedger.append` / `verify` / `redact_chain` / `recover_effects` / `trace_complete` | §8.11、§10.5–§10.6 | C7-02、C7-03、C7-06 |
| 7. 崩溃与重启 | `JsonStore` + `TaskBoard.recover` / `reconcile_effect` / `require_replay_allowed`、`IdempotencyIndex.execute_once`、`ContextFabric.open/close_blackboard` | §3.7、§8.11、§9.5 | C4-04–C4-06 语义(重启部分) |

第 3 节不是手工拼回执：`ConsentFlow` 依次完成 `request` → `reserve_cap_id` → `grant` → `activate`。预约的 `cap_id` 在激活前对 `usable()` 为假，用户授权也不会自动签发能力；`grant` 用 PCS 私钥签回执，`activate` 先验签、再通过回执范围校验，最后才调用 `CapabilityAuthority.issue`。演示还用 `pcs.verify_receipt` 仅凭 PCS 公钥独立核对签名。

任务树有两条并列支路：`supervisor → notes` 与 `supervisor → calendar`，因此跨过两个委派边界；三条 `trace_id` 相同的消息链（discover → notes delegate/result → calendar delegate/result）证明 trace 完整性。

第 6 节的 16 个事件全部经 `AuditLedger.append` 写入（ledger 自动生成 `audit_id`/`ts`/`prev_hash`/`hash`），demo 只提供语义字段——链条就是实现产出的链，没有第二套编码。`effect.executed` 的 `intent_ref` 指向 intent 事件的 ledger `audit_id`，这正是 §8.11 的配对规则。

第 7 节是崩溃恢复演示：任务树、effect 日志、审计链、上下文织构与幂等索引共享同一个 0600 JSON store。模拟崩溃后重开 store：审计链重验通过；intent-only effect 的重放被 `require_replay_allowed` 拒绝（`reconciliation_required`），`recover()` 把任务转为 `failed` 并把 effect 标为 `unknown`；同一条消息重投时幂等索引命中——重放结果而不是重放副作用；`reconcile_effect("not_executed")` 之后重试才成为显式的操作者决定。对照组：黑板条目在任务结束后被 `close_blackboard` 清空并保持 `promoted_to_memory=false`，跨重启也不晋升(§9.5)。

## 3. C7-01 的手工复核

C7-01 仍是 manual 用例，因为它要求“真实三 App 集成 + 崩溃恢复”（跨进程）。本演示把可自动化的部分固定下来，便于逐条核对：

| C7-01 步骤 | 演示中的落点 |
|---|---|
| 运行三 App 的端到端任务 | 第 1–4 节，三个 Agent 各自注册并有任务或消息 |
| 检查每条消息的 `trace_id` 与 `causation_id` | `trace_messages`，由 `audit.trace_complete` 断言 |
| 按 `trace_id` 导出审计链 | 第 6 节由 `AuditLedger` 生成的链与消息共享 `TRACE` |
| 验证链完整性 | `audit.verify_chain` + `ledger.verify()` |
| 回放 trace 且不执行副作用 | `audit.recover_effects` 只读事件，不调用工具 |
| **崩溃后恢复且不重放副作用** | **第 7 节：`recover()` + 重放闸门 + 幂等索引重放** |

真实的跨进程传输仍不在本演示范围内，因此 C7-01 不改为 automated；但崩溃恢复的进程内语义（§3.7、§8.11）已由第 7 节覆盖。

## 4. 确定性

- “现在”固定为 `2026-11-10T10:14:45Z`；能力有效期、句柄 TTL 与审计时间戳都以它为准，不使用墙钟。
- 每次运行生成新的 Ed25519 开发密钥，所以 `session_id` 与清单签名会变化；判定结果不变。
- 脱敏导出使用固定盐 `demo-export-salt`，便于对比；承诺值因此可复现，但真实导出必须每次生成新盐（`audit.redact_chain` 的默认行为）。

## 5. 不在演示范围内

1. **没有跨进程传输**：消息是内存字典，没有 UDS/XPC/D-Bus 绑定（M2.1b）。
2. **没有跨进程崩溃**：第 7 节的"崩溃"是丢弃进程内对象并重开 store，不是 kill 进程；跨进程恢复需要真实传输（C7-01 仍为 manual 的原因）。
3. **没有真实 OS 句柄**：`ctx://` 解析只做授权与标签判定，不触碰系统联系人、文件或日历。
4. **外部协议未验签**：演示只用本地清单；MCP/A2A/OpenAPI 的信任归一由 C6 覆盖。
5. **`effect.*` 不真正写日历**：审计记录"意图 + 结果"的记账顺序与重放闸门，但不产生外部副作用。
6. **签名声明而非验证**：清单与能力凭证的 `proof` 做结构校验，未验签（impl/README 限制 #6）；PCS 回执例外，已离线验签。
