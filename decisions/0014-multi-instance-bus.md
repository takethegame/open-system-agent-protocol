# ADR-0014: 多实例 Bus 与审计链分区

- 状态：Provisional
- 日期：2026-11-19
- 关联：`docs/standard.md` §15.14、§3.6、§10.6；`docs/roadmap.md` §M4

## 背景

0.1 假设每用户一个 Bus。真实部署可能出现多个 Bus 实例：每个桌面会话一个、每个容器一个、或为了高可用而并行运行。多实例会带来 leader election、任务归属、撤销传播与审计链分区问题。如果处理不当，会出现 split-brain：两个 Bus 都认为自己是权威，用户看到两条不一致的链。

## 暂定结论

1. **0.1 每用户一个 Bus**。多实例不是 0.1 的支持范围；实现 MUST NOT 声称支持多实例高可用。
2. **按用户/会话分区**：如果部署多个 Bus，分区键 MUST 是 `user` 或 `session`，不是 `trace_id` 或 `task_id`；一个任务的全部事件 MUST 落在同一个 Bus/审计分区，避免跨链拼接。
3. **不做自定义 leader election**：需要单写者时，SHOULD 使用 OS 服务管理器（`systemd --user`、launchd、Windows Service）或平台已有的租约机制；不得在 OSAP 内新造 Raft/Paxos。选主失败时 MUST 拒绝写入，而不是双写。
4. **审计链分区**：`AuditLedger` 仍是每 trace 一条链；跨 trace 的全局顺序列入 0.2。多实例导出的链 MUST 带 `bus_id`/`partition` 元数据，验证方不得把两条链当作一条。
5. **撤销传播**：多实例之间 MUST 通过共享状态、显式通知或 CA 查询传播撤销；不得假设“同一用户的所有 Bus 自动同步”。无法确认撤销状态时，L3/L4 MUST 拒绝。
6. **故障关闭**：检测到 split-brain、分区不可达、审计链冲突时，实例 MUST 停止写入并报告，而不是继续服务。

## 后果

- 0.1 没有高可用；Bus 崩溃会中断会话，需要恢复流程。
- 多实例部署需要外部协调；OSAP 不提供内置共识。
- 审计导出与验证需要额外元数据；现有单链工具不能直接合并多实例链。
- 跨 trace 排序、跨实例撤销与任务迁移都留到 0.2。

## 备选方案

- **内置 leader election**：协议自包含，但复杂度高，且与 OS 服务管理器重复。
- **多写者、冲突合并**：可用性高，但审计链与任务状态难以一致，安全风险大。
- **完全禁止多实例**：简单，但容器/多会话场景可能自然产生多个 Bus。
- **按 trace 分区**：负载均衡方便，但同一任务跨分区会破坏因果与撤销。

## 重审触发条件

1. 出现多实例部署或高可用需求；
2. 需要跨 trace 的全局审计顺序；
3. OS 服务管理器提供可移植的租约/选主接口；
4. 发生 split-brain、重复执行或撤销未传播事件。

## 参考

- [`docs/standard.md`](../docs/standard.md) §3.6（每用户 Bus）、§10.6（trace）、§15.14
- [`impl/osap/audit.py`](../impl/osap/audit.py)（单 trace 账本与归档）
- [`impl/osap/capability.py`](../impl/osap/capability.py)（撤销索引与级联）
