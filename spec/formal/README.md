# 形式化不变量（M3，进行中）

本目录用 TLA+ 建模 `standard.md` 中四条跨模块不变量，并用 TLC 在有限状态空间内检查。模型是**规范层**的抽象，不复刻错误码、序列化或传输细节；实现侧由 `impl/tests/` 覆盖。

## 1. 模型

| 文件 | 建模对象 | 规范依据 |
|---|---|---|
| `Capability.tla` | 能力签发、衰减、撤销集合 | §5.3、§5.5 |
| `Task.tla` | 任务树、预算、消耗、完成、取消、分离子树 | §8.6、§8.7、§8.8 |

两个模型都使用有限集合常量，状态空间由配置文件的 `CONSTANT` 限定。`Capability.tla` 的 `AllowWidening` 只用于证明模型不是空转：正常配置把它设为 `FALSE`，`CapabilityBroken.cfg` 设为 `TRUE`，TLC 应立即给出反例。

## 2. 不变量与条文的对应

| 不变量 | 含义 | 条文 |
|---|---|---|
| `AttenuationMonotonic` | 子能力的 `actions`/`resources` 是父集合的子集，`exp` 不晚于父，`depth` 恰为父 + 1 | §5.3 |
| `RevocationCascade` | 任一已撤销能力的直接子能力也已撤销；对有限树归纳即覆盖任意深度 | §5.5 |
| `BudgetMonotonic` | 子任务预算不大于父任务预算 | §8.6 |
| `NoOverConsumption` | 任务消耗不超过自身预算 | §8.6 |
| `CancellationPropagation` | 已取消任务的非 `detached` 直接子任务也已取消；归纳覆盖整棵附加子树 | §8.7 |
| `NoResultAfterCancel` | 已取消任务不再暴露结果（取消时清零，历史结果留在审计） | §8.7、§8.8 |

`Task.tla` 把 `delegate` 限制为“子预算不超过父任务**剩余**预算”，与 `impl/osap/task.py` 的检查一致；`BudgetMonotonic` 只断言沿链不增长，不把运行期父任务消耗后的剩余量当成新的上界。

## 3. 运行

需要 Java 17+ 与 `tla2tools.jar`（不随仓库分发）：

```bash
curl -sSL -o /tmp/tla2tools.jar \
  https://github.com/tlaplus/tlaplus/releases/download/v1.7.4/tla2tools.jar
TLA2TOOLS_JAR=/tmp/tla2tools.jar spec/formal/check.sh
```

`check.sh` 依次检查两个正常配置，再运行 `CapabilityBroken.cfg` 并断言它**必须**报错。最后一条是负向对照：如果放宽 `actions`/`resources`/`exp` 后 TLC 仍然通过，说明模型没有真正约束衰减。

## 4. 结果

2026-11-15，`tla2tools` v1.7.4、TLC 2.19、单 worker：

| 配置 | 结果 | 状态数 |
|---|---|---|
| `Capability.cfg` | 无违例 | 61,267 生成 / 16,866 去重 |
| `Task.cfg` | 无违例 | 78,551 生成 / 15,972 去重 |
| `CapabilityBroken.cfg` | `AttenuationMonotonic` 反例（孙能力 `exp` 超过父） | 2,708 生成 / 347 去重 |

## 5. 模型检查发现的问题

`Capability.tla` 的第一版允许从**已撤销**的父能力继续 `Attenuate`；TLC 给出的路径是“先撤销根，再从根派生新子能力”，此时 `RevocationCascade` 被破坏。参考实现当时也有同样的缺口：`CapabilityAuthority.issue` 只校验 schema 与索引，不检查父能力是否已撤销。

修复后：

- `issue` 拒绝 `cap_id` 已在撤销集合中的凭证；
- `issue` 拒绝 `parent_cap_id` 已在撤销集合中的子凭证，返回 `CAPABILITY_REVOKED`；
- 新增两条单元测试固定这两个拒绝路径。

这也是 M3 的第一个实际收益：模型不是把已有代码翻译一遍，而是找到了实现漏掉的“撤销后不得再派生”约束。

## 6. 未建模

- `Receipt`（同意回执）与 `RevocationSet` 的持久化/分发语义；
- §8.11 的 `intent` / `outcome` / `unknown` 崩溃对账三态；
- 跨进程通知、重试与 P95 传播时延（由 `tools/benchmark_revocation.py` 单独测量）；
- 错误码、JSON 编码与传输绑定。

这些是 M3 后续任务，不在当前两个模型的证明范围内。
