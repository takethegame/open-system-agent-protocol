# OSAP 进展记录

> 更新时间：2026-11-17
> 关联规划：[`roadmap.md`](roadmap.md)
> 性质：工作记录（非规范性）。规范性内容以 [`standard.md`](standard.md) 为准。

本文记录已完成的里程碑、验证证据、设计决定、已知限制，以及剩余工作的逐条拆分。每完成一个里程碑追加一节，不覆盖历史。

---

## 1. 当前快照

| 里程碑 | 状态 | 进度 | 完成日期 |
|---|---|---|---|
| M0 仓库可信化 | ✅ 完成 | 7/7 | 2026-11-12 |
| M1 可执行一致性 | ✅ 完成 | 68/68 用例（100%） | 2026-11-12 |
| M2 参考实现 MVP | 🟢 完成 | M2.1a/b + M2.2 + M2.3 + M2.4a/b + M2.5a/b/c + M2.6 + M2.7 完成；撤销传播 P95 1.23 ms（1,555 节点，100 样本） | — |
| M3 形式化不变量 | ✅ 完成 | 4/4 主不变量 + 同意/崩溃恢复模型通过 TLC；两个负向对照均报反例 | 2026-11-15 |
| 持久化基础（M4 前置） | ✅ 完成 | 幂等、能力签发/撤销、同意请求/回执/预约与 PCS 签名密钥跨重启；原子分节写入；387 tests | 2026-11-16 |
| PCS 回执签名（M4 前置） | ✅ 完成 | Ed25519 签名 + 离线验签；`activate` 先验签；375 tests | 2026-11-16 |
| 流控与背压（M4 前置） | ✅ 完成 | 每身份连接/在途/队列上限与令牌桶速率；FIFO 等待；显式 `RATE_LIMIT`；UDS 可并发服务；422 tests | 2026-11-17 |
| 任务树持久化（M4 前置） | ✅ 完成 | 整棵树跨重启：状态、预算、`consumed`、`detached`、父子链与 handoff；每次变更一次原子写入；440 tests | 2026-11-17 |
| 审计账本持久化（M4 前置） | ✅ 完成 | 单 trace 追加链：自动生成 `audit_id`/`ts`/`prev_hash`/`hash`；重启重算正文哈希；损坏 fail closed；457 tests | 2026-11-17 |
| M4 标准打包 | ⬜ 未开始 | 0/4 产出 | — |
| M5 生态与采用 | ⬜ 未开始 | — | — |

仓库规模：

| 项目 | 数量 |
|---|---|
| 规范正文 | 131 节 |
| JSON Schema | 12（协议）+ 3（一致性：case / suite / report）= 15 |
| 示例 | 17 |
| 一致性用例 | 68 / 68 |
| 校验与基准工具 | 6 |
| Markdown 文件 | 23 |
| 参考实现 | 22 个模块 + 适配器（5631 行）+ 457 个单元测试 |
| 形式化模型 | 4 个 TLA+ 模块 + 6 个配置 + `check.sh`（479 行） |
| 端到端演示 | `demo/run_demo.py`（575 行）+ 演示说明（67 行） |
| 中英平行文档 | 8 对 |
| CI 工作流 | 1（Python 3.11 / 3.12） |

---

## 2. 提交时间线

| commit | 日期 | 内容 |
|---|---|---|
| `440dde5` | 2026-11-10 | first commit：规范、schema、示例骨架 |
| `0ea4714` | 2026-11-10 | version 1：补全 12 schema、13 示例、校验脚本 |
| `aa1a1d7` | 2026-11-11 | 收紧 handoff、同意绑定、一致性表述 |
| `d932070` | 2026-11-11 | 英文平行译本（7 个 `*.en.md`） |
| `1d38d32` | 2026-11-12 | **M0**：CI、安全策略、变更记录、路线图 |
| `f8e13bd` | 2026-11-12 | **M1（部分）**：C0 + C3 共 19 条可执行用例 |
| `93f0d4e` | 2026-11-12 | 创建 `docs/progress.md`，拆分剩余用例 |
| `ba31745` | 2026-11-12 | **M1（续）**：C1 + C2 共 12 条，`examples/hello.json` |
| `043806f` | 2026-11-12 | 进展文档更新到 31/68 |
| `a34ec0f` | 2026-11-12 | **M1（续）**：C4 共 11 条；envelope 增加 peer/`session_id` 条件 |
| `b3b8ab5` | 2026-11-12 | **M1（续）**：C6 共 8 条（7 automated，1 manual） |
| `74a41ce` | 2026-11-12 | **M1（续）**：C5 共 11 条；新增上下文句柄与黑板夹具 |
| `012c9c7` | 2026-11-12 | **M1 完成**：C7 共 7 条；新增审计链夹具；报告纳入 schema 校验 |
| `e9079cc` | 2026-11-12 | M1 文档收尾（68/68）；`validate_examples.py` 扩到 24 项 |
| `add9162` | 2026-11-13 | M1 复核：`--stub` 增加编号覆盖检查与夹具/mutation 实测 |
| `eb19411` | 2026-11-13 | **M2.1a**：信封、错误模型、分帧、握手、幂等、单调时钟（32 tests；C0 5 pass） |
| `f8d37b7` | 2026-11-13 | **M2.2**：Ed25519 签名、注册、注册表（62 tests；累计 16 pass） |
| `a41ec78` | 2026-11-13 | **M2.3 + M2.4**：能力衰减、绑定、撤销、风险前置、回执（118 tests；累计 28 pass） |
| `2e05890` | 2026-11-14 | **M2.5a**：任务树、委派预算、取消、结果、handoff（160 tests；累计 36 pass） |
| `206008b` | 2026-11-14 | **M2.5b**：上下文织构、标签、出口、黑板、删除、缓存、存储声明（202 tests；累计 47 pass） |
| `c2bca7d` | 2026-11-14 | M2.5b 加固：身份/OS/授权先于过期判定，避免向无权调用者泄漏 TTL 状态 |
| `49cf486` | 2026-11-14 | **M2.5c**：联邦适配器、原生身份、命名空间、外部信任归一（228 tests；累计 54 pass） |
| `0b304db` | 2026-11-14 | **M2.6**：审计链、脱敏导出、回放、恢复、跨用户；修复 None 结果的幂等缓存（265 tests；累计 60 pass） |
| `1a4d09a` | 2026-11-14 | **M2.7**：三 Agent 演示（注册、发现、同意、两次委派、上下文、16 条审计事件），CI 增加演示步骤 |
| `f1b8453` | 2026-11-15 | **M2.4b**：同意请求、`cap_id` 预约、授权/拒绝、激活与撤销；演示第 3 节接入（309 tests） |
| `47a3f4c` | 2026-11-15 | **M2.1b**：UDS stream、消息型 socketpair、对端认证；C0-01/C0-06 自动化（325 tests；累计 62 pass） |
| `b95e2c9` | 2026-11-15 | **M2 退出标准**：撤销按父→子索引传播，P95 1.23 ms（1,555 节点、100 样本）；329 tests |
| `c3268f6` | 2026-11-15 | **M3（第一段）**：TLA+ 能力/任务模型、6 条不变量、负向对照；发现并修复撤销后仍可派生（331 tests） |
| `17c11ad` | 2026-11-15 | **M3 完成**：同意顺序与 §8.11 崩溃对账模型；四个模型、两个负向对照全部通过 |
| `48e744e` | 2026-11-16 | **持久化基础**：`JsonStore` 原子分节 JSON；幂等索引与能力签发/撤销跨重启；共享 store 隔离；27 条新测试，累计 358 |
| `092c710` | 2026-11-16 | **PCS 回执签名**：Ed25519 覆盖去 `proof` 的规范化 JSON；离线验签；`activate` 先验签；17 条新测试，累计 375 |
| `61a9994` | 2026-11-16 | **同意流程持久化**：请求/回执/预约与签名密钥跨重启；`put_many` 原子多节写入；12 条新测试，累计 387 |
| `0b13483` | 2026-11-17 | **流控与背压**：`Quota` / `AdmissionController` / `Admission`；每身份令牌桶、在途与 FIFO 等待队列；连接配额与显式 `RATE_LIMIT`；32 条新测试，累计 419 |
| `eaf8260` | 2026-11-17 | **并发 UDS 服务**：`serve_forever(concurrency=N)` 线程池接受/服务连接；空闲连接不再阻塞他人；同 Agent 跨连接共享在途与排队配额；3 条新测试，累计 422 |
| `f47abd7` | 2026-11-17 | **任务树持久化**：`TaskBoard(store=...)` 与无损 `Task.to_state`/`from_state`；整树跨重启；每次变更一次原子写入；18 条新测试，累计 440 |
| `ca808b9` | 2026-11-17 | **审计账本持久化**：`AuditLedger` 单 trace 追加链；规范哈希与重启重算；损坏 fail closed；按 trace 分区；17 条新测试，累计 457 |

---

## 3. M0 — 仓库可信化（已完成）

### 3.1 交付物

| 文件 | 行数 | 作用 |
|---|---|---|
| `.gitignore` | 20 | 忽略 `.idea/`、`__pycache__`、`.venv`、本地报告 |
| `requirements.txt` | 3 | `jsonschema` 4.18+、`referencing` 0.30+ |
| `.github/workflows/ci.yml` | 44 | 3.11/3.12 矩阵，4 个检查步骤 |
| `tools/check_schemas.py` | 108 | 元校验、`$id` 唯一性、`$ref` 目标 |
| `tools/check_docs.py` | 164 | JSON 块、围栏、断链、中英结构、敏感字符串 |
| `SECURITY.md` / `SECURITY.en.md` | 62 / 62 | 披露渠道、7/14/90 天时限、评审触发条件 |
| `CHANGELOG.md` | 82 | Keep a Changelog，回填 0.1 |
| `docs/roadmap.md` | 340 | M0–M5、决策闸门、风险登记 |
| `README.md` / `README.en.md` | 修改 | CI 徽章、文档表、仓库结构、校验命令 |

### 3.2 改名记录

| 项目 | 旧 | 新 |
|---|---|---|
| GitHub 仓库 | `takethegame/open-system-agent-protocal` | `takethegame/open-system-agent-protocol` |
| 本地目录 | `~/project/os-agent-communication-protocal` | `~/project/open-system-agent-protocol` |
| `origin` | `git@github.com:takethegame/open-system-agent-protocal.git` | `git@github.com:takethegame/open-system-agent-protocol.git` |

GitHub 侧由仓库管理员改名；本地由 `mv` + `git remote set-url` 完成，会话工作目录同步迁移。旧 URL 由 GitHub 重定向。

### 3.3 验证证据

```
python3 tools/check_schemas.py      → OK: 36 checks passed across 12 schemas
python3 tools/validate_examples.py  → OK: 20 checks passed
python3 tools/check_docs.py         → OK: 96 checks passed across 18 Markdown files
```

CI：

| commit | 运行 | 结论 |
|---|---|---|
| `1d38d32` | [43196619992](https://github.com/takethegame/open-system-agent-protocol/actions/runs/43196619992) | ✅ success（3.11 + 3.12） |
| `f8e13bd` | [43207360154](https://github.com/takethegame/open-system-agent-protocol/actions/runs/43207360154) | in progress |

### 3.4 遗留风险

- 改名不会重定向 GitHub Pages 与 package 名；目前两者都未使用，暂不处理。
- `CHANGELOG.md` 仅英文，与中文原文的双语政策不一致；理由是条目对应英文 commit message，且属于流程文档而非规范。

---

## 4. M1 — 可执行一致性（已完成）

### 4.1 交付物

| 文件 | 行数 | 作用 |
|---|---|---|
| `conformance/case.schema.json` | 161 | 单用例；`reject` 强制带 `error` |
| `conformance/suite.schema.json` | 20 | 按 level 分组的用例文件 |
| `conformance/report.schema.json` | 60 | 运行报告（standard §12.4） |
| `conformance/README.md` | 128 | 字段、mutation、适配器 API、新增流程 |
| `conformance/cases/C0-transport.json` | 125 | 7 条（5 automated，2 manual） |
| `conformance/cases/C1-identity.json` | 110 | 6 条（5 automated，1 `observe`） |
| `conformance/cases/C2-registry.json` | 109 | 6 条（4 automated，1 `observe`，1 manual） |
| `conformance/cases/C3-authorization.json` | 220 | 12 条（全 automated） |
| `conformance/cases/C4-collaboration.json` | 223 | 11 条（8 automated，3 manual） |
| `conformance/cases/C5-context.json` | 215 | 11 条（全 automated，其中 4 条 `observe`） |
| `conformance/cases/C6-federation.json` | 236 | 8 条（7 automated，1 manual） |
| `conformance/cases/C7-full.json` | 144 | 7 条（6 automated，1 manual） |
| `examples/hello.json` | 20 | 注册夹具（`osap.hello/v1`） |
| `examples/context-handle.json` | 19 | 上下文句柄夹具（标签、TTL、scope） |
| `examples/blackboard.json` | 23 | 任务黑板夹具（条目、版本、TTL） |
| `examples/audit-chain.json` | 52 | 3 条链式审计事件，止于 `effect.intent` |
| `tools/conformance_run.py` | 372 | 加载、校验、变异、执行、报告、报告 schema 校验 |

### 4.2 覆盖情况

| 等级 | 已迁移 | 总数 | 状态 |
|---|---|---|---|
| C0 Transport | 7 | 7 | ✅ |
| C1 Identity | 6 | 6 | ✅ |
| C2 Registry | 6 | 6 | ✅ |
| C3 Authorization | 12 | 12 | ✅ |
| C4 Collaboration | 11 | 11 | ✅ |
| C5 Context | 11 | 11 | ✅ |
| C6 Federation | 8 | 8 | ✅ |
| C7 Full | 7 | 7 | ✅ |
| **合计** | **68** | **68** | **100%** |

### 4.3 设计决定

| 决定 | 理由 |
|---|---|
| mutation 由 runner 统一应用（RFC 6901） | 各实现不必重复解释变异语义，减少互操作分歧 |
| `expect.outcome` 三值：`accept` / `reject` / `observe` | `observe` 覆盖“视为不一致”类检查，避免把主观判断写成断言 |
| `reject` 必须带 `error` | 用 schema 强制，防止用例写出无法判定的期望 |
| `mode: manual` | 握手状态、时钟回拨、崩溃恢复需要运行时条件，标注而非伪造自动化 |
| 适配器返回 `{"outcome":"skip"}` | 能力子集实现可以显式跳过，其余异常一律 `fail` |
| 用例 `title` 用英文 | 便于外部实现者阅读，也是报告中的直接展示字段 |
| `--stub` 取代独立 stub 脚本 | 无适配器时全部 skip，同时仍校验用例格式 |

### 4.4 验证证据

```
python3 tools/check_schemas.py              → OK: 45 checks passed across 15 schemas
python3 tools/validate_examples.py          → OK: 24 checks passed
python3 tools/check_docs.py                 → OK: 104 checks passed across 20 Markdown files
python3 tools/conformance_run.py --stub     → 68 cases [C0, C1, C2, C3, C4, C5, C6, C7]: 0 pass, 0 fail, 68 skip
python3 tools/conformance_run.py --stub --format json --out conformance-report.json
                                            → summary: 68 total, 0 pass, 0 fail, 68 skip
                                            → report 通过 report.schema.json 校验
```

M1 收尾时的负向验证（均在临时目录，不随仓库发布）：

| 场景 | 结果 |
|---|---|
| 把某条用例的 `input.ref` 指向不存在的夹具 | 该条 `fail`，其余继续执行，退出码 1 |
| 把 mutation 的 `replace` 路径改成不存在的字段 | 该条 `fail`（`fixture error`） |
| 只加载 `C7-full.json` 跑 `check_ids` | 报 61 条缺号，退出码非 0 |
| 完整用例集合跑 `check_ids` | 通过 |

临时回显适配器（不随仓库发布）验证完整链路（C0–C3 共 19 条时）：

| 场景 | 结果 |
|---|---|
| 回显用例期望值 | 19 条中 17 pass、2 条 manual skip |
| mutation 生效检查（C3-01 / C3-09 / C3-10） | 通过 |
| 报告 JSON 对照 `report.schema.json` | 0 错误 |
| 错误适配器（全部返回 accept） | 12 fail，退出码 1 |
| `--stub` | 全部 skip，退出码 0 |

### 4.5 已知限制

1. **没有真实实现**：仓库内的 `--stub` 全部为 `skip`，不产生任何 `pass`。此前出现的 `pass` 都来自临时回显适配器，只证明 runner 与用例自洽，不证明协议可实现。
2. **mutation 只作用于主夹具**：`input.mutations` 不能同时改 `context` 中的多个文档。需要多文档变异时，只能把被改文档设为主夹具（C3-10–C3-12 就是这么做的）。
3. **缺少运行时状态模型**：C4-01（取消传播）、C7-01（trace 完整性）这类断言依赖实现暴露状态，目前只能标 manual。
4. **适配器 API 未冻结**：`conformance_check(case, documents)` 可能在 M2 中调整。
5. **`observe` 用例需要人工判定**：报告只记录实际结果，不产生 pass/fail。
6. **注册表错误码是近似映射**：C2-01 / C2-06 使用 `SCHEMA_INVALID`，但规范没有为注册表索引单独定义错误码；用例真正断言的是“索引 MUST 失败”，`notes` 已注明实现可返回领域前缀错误码。
7. **部分状态通过 `params` 模拟**：C4-07（已消耗预算）、C4-10（handoff 后的 owner）、C4-11（handoff 被拒绝）用 `params` 声明运行时前置状态，适配器需自行解释。这类用例可执行，但不如真实运行时模型严格。
8. **上下文夹具没有 JSON Schema**：`context-handle.json` 与 `blackboard.json` 的字段取自 §9.3–§9.5，但规范未定义 wire format，因此不纳入 `validate_examples.py`。字段调整不会触发 schema 校验。
9. **审计链错误码是领域扩展码**：C7-02 使用 `AUDIT_CHAIN_INVALID`，规范只要求“校验失败”，没有定义审计专用标准码。该码既不在 §7.7 的 27 个标准码内，也不在保留前缀内（`is_standard` 与 `is_extension` 都为 false），已在 `notes` 注明。

### 4.6 用例分布（迁移完成）

| 维度 | 数量 | 说明 |
|---|---|---|
| 总数 | 68 | C0 7 + C1 6 + C2 6 + C3 12 + C4 11 + C5 11 + C6 8 + C7 7 |
| automated | 60 | 其中 7 条为 `observe` |
| manual | 6 | C2-05、C4-01、C4-08、C4-09、C6-08、C7-01 |
| `observe` | 14 | 7 条 automated + 7 条 manual |

手动用例集中在三类：传输/时钟运行时（C0）、TTL 与生命周期（C2、C6）、崩溃与跨 App 集成（C4、C7）。`observe` 用例不产生自动判定，报告只记录实现的实际行为。

### 4.7 夹具缺口

全部夹具已就位：

| 夹具 | 用于 | 状态 |
|---|---|---|
| `hello.json` | C1 | ✅ |
| `context-handle.json` | C5 | ✅ |
| `blackboard.json` | C5 | ✅ |
| `audit-chain.json` | C7 | ✅ |

C2/C4/C6 复用 `manifest.json`、`discovery-result.json`、`capability-record.json`、`task.json`、`delegate.json`、`handoff.json`、`result.json`。

### 4.8 M1 退出标准

- [x] 68 个用例全部可加载，case / suite schema 校验通过；
- [x] `--stub` 输出 68 条 `skip`；
- [x] JSON 报告通过 `report.schema.json` 校验；
- [x] CI 同时运行用例检查与报告校验；
- [x] 编号覆盖：用例集合与 `docs/conformance.md` 表格逐条相等（缺号/多号即失败）；
- [x] 夹具可执行：`--stub` 也解析 `input.ref`、`context` 并应用全部 mutation，路径不存在即失败。

后续工作（不属于 M1 退出标准）：

- 用真实适配器跑通 C0–C3（M2）；
- 冻结适配器 API（M2.1）。

之后进入 M2.1（信封 + 错误模型）。

---

## 5. M2 — 参考实现（已完成）

### 5.1 交付物

`impl/` 是 0.1 的最小参考实现，语言为 Python 3.11+，只新增 `cryptography` 一个依赖。

| 模块 | 行数 | 职责 | 章节 | 阶段 |
|---|---|---|---|---|
| `impl/osap/envelope.py` | 112 | 信封校验、路由键、任务 ID | §7.1 | M2.1a |
| `impl/osap/errors.py` | 105 | 27 个标准错误码、`retryable` 默认值 | §7.7 | M2.1a |
| `impl/osap/framing.py` | 92 | 流式前缀、消息型边界、8 MiB 上限 | §7.9、§7.10 | M2.1a |
| `impl/osap/clock.py` | 71 | 单调时钟 deadline | §7.8 | M2.1a |
| `impl/osap/idempotency.py` | 45 | 按 `id` 去重 | §7.8 | M2.1a |
| `impl/osap/bus.py` | 154 | 握手、校验、路由、幂等、错误回执 | §7.1、§7.9 | M2.1a |
| `impl/osap/schema.py` | 60 | schema 加载与错误映射 | — | M2.2 |
| `impl/osap/crypto.py` | 104 | Ed25519 签名与规范化 JSON | §4.5 | M2.2 |
| `impl/osap/identity.py` | 127 | 注册、保留命名空间、App/公钥绑定 | §4.1–§4.4 | M2.2 |
| `impl/osap/registry.py` | 208 | 清单、能力记录、发现、能力描述解析 | §6 | M2.2 |
| `impl/osap/capability.py` | 258 | 能力凭证、衰减、绑定、撤销、风险前置 | §5.2–§5.7 | M2.3 |
| `impl/osap/consent.py` | 120 | 同意回执与能力范围校验 | §5.8 | M2.4 |
| `impl/osap/consent_flow.py` | 381 | 同意请求、`cap_id` 预约、授权/拒绝、激活、撤销 | §10.2、§10.3 | M2.4b |
| `impl/osap/task.py` | 550 | 任务树、预算、取消、结果、handoff、整树持久化 | §8.2–§8.10 | M2.5a |
| `impl/osap/transport.py` | 508 | UDS stream、消息型 socketpair、对端认证 | §7.9、§7.10 | M2.1b |
| `impl/osap/context.py` | 289 | 句柄、标签、黑板、对象、缓存、存储声明 | §9.2–§9.10 | M2.5b |
| `impl/osap/federation.py` | 138 | 原生描述符投影、原生身份、命名空间、信任归一 | §6.4、§6.7、§6.8 | M2.5c |
| `impl/osap/audit.py` | 415 | 审计链、持久账本、脱敏导出、回放、恢复、跨用户 | §8.11、§10.5–§10.6、§11.2 | M2.6 |
| `impl/adapter.py` | 761 | 一致性适配器 | — | M2.1a–M2.7 |
| `demo/run_demo.py` | 575 | 三 Agent 端到端演示：注册、发现、同意、委派、上下文、审计 | §4–§10 | M2.7 |

`impl/tests/` 有 331 个单元测试，覆盖分帧往返与边界、校验顺序、幂等、时钟回拨、错误码默认值、签名与篡改、注册拒绝路径、注册表 TTL 与发现过滤、衰减的十项规则（逐维度）、撤销级联、绑定三项、回执的校验顺序、同意请求的 TTL 与选项、预约的惰性、拒绝/撤销后不可激活、回执有效期钳制、任务状态机、取消传播、委派预算与深度、结果契约、handoff 的五类拒绝路径，上下文句柄的授权/过期/标签/出口/黑板/删除/缓存/存储/记忆边界，联邦投影的 MCP/A2A/D-Bus/OpenAPI 身份解析、外部信任归一与命名空间映射，UDS stream 与数据报消息绑定的真实往返、连接级握手隔离、超长帧与 8 MiB 上限、uid/gid/pid/可执行文件认证与 fail-closed 策略，以及审计链链接校验、脱敏承诺、回放幂等、恢复对账与跨用户边界。

### 5.2 验证证据

```
python3 -m unittest discover -s impl/tests -t impl
    → Ran 331 tests ... OK
python3 tools/conformance_run.py --impl impl/adapter.py
    → 68 cases [C0..C7]: 62 pass, 0 fail, 6 skip
python3 demo/run_demo.py
    → registered=3 discovery=1 consent=1 delegated=2 context=1 audit=verified
      16 events verified; redaction verifiable; recovery complete; trace complete
```

| 等级 | 结果 | 覆盖点 |
|---|---|---|
| C0 | 7 pass | 真实 UDS 握手、版本、两种分帧、幂等、单调时钟 |
| C1 | 6 pass | 未注册、保留命名空间、验签失败、App 越权、轮换宽限、公钥未绑定 |
| C2 | 5 pass / 1 manual skip | 无签名清单、发现无泄漏、静态 `consent_hint`、TTL 过期、缺 `provenance` |
| C3 | 12 pass | audience/task/subject 绑定、四项衰减、撤销级联、L3 无回执、回执过期与范围不足 |
| C4 | 8 pass / 3 manual skip | 委派预算、结果契约、peer 会话、他人能力、handoff 重同意、运行期预算、所有权、拒绝 handoff |
| C5 | 11 pass | 解析授权、过期不续期、标签继承、出口同意、黑板清理、引用检查、缓存钳制、存储职责、OS 权限、记忆边界 |
| C6 | 7 pass / 1 manual skip | 三家原生注册表、MCP server/tool、A2A card/skill、D-Bus 四段、外部信任归一 |
| C7 | 6 pass / 1 manual skip | 审计链篡改、脱敏导出、跨用户、回放、恢复、被攻破 Bus 声明 |

C3 的 12 条不仅错误码匹配，`details.violations` 也被断言为只含目标维度：

| 用例 | 命中维度 |
|---|---|
| C3-04 | `["actions"]` |
| C3-05 | `["resources"]` |
| C3-06 | `["exp"]` |
| C3-07 | `["depth", "constraints.max_depth"]` |

C4 的 8 条 automated 全部通过，且每条都核对过拒绝原因：

| 用例 | 拒绝点 |
|---|---|
| C4-02 | 委派 `wall_ms=9000` > 父剩余 `8000` |
| C4-03 | 结果 `body.schema` 与 `result_schema` 不符 |
| C4-04 | `mode=peer` 但缺 `session_id`（信封 schema 的条件分支） |
| C4-05 | 凭证 `subject` 是 calendar，发送方是 orchestrator |
| C4-06 | L3 handoff 没有指向新 owner 的回执 |
| C4-07 | 已消耗 `wall_ms=6000` > 预算 `5000` |
| C4-10 | handoff 后 owner 已是 calendar，orchestrator 再发 `request` |
| C4-11 | 拒绝 handoff：`owner`/`budget`/`status` 三项均未变 |

C5 的 11 条同样逐条核对：

| 用例 | 实际判定 |
|---|---|
| C5-01 | 只有 `read`，缺 `resolve`，`details.required_action=resolve` |
| C5-02 | `expires_at=09:00Z` 早于夹具“现在”`10:14:45Z`，报 `CONTEXT_EXPIRED` |
| C5-03 | 声明 `public`、来源 `sensitive`，报告 `lowered=true`、`effective_label=sensitive` |
| C5-04 | `secret` + `egress=true` + 无用户放行，报 `POLICY_CONSENT_REQUIRED` |
| C5-05 | 黑板归档 2 条，`promoted_to_memory=false` |
| C5-06 | 引用数 2，软删除返回 `tombstoned=true` 且 `audit_written=true` |
| C5-07 | 请求 900 s 被钳到句柄 TTL 600 s，700 s 时 `cache_hit=false` |
| C5-08 | `managed_store` 缺配额、GC、崩溃恢复、加密、路径安全、删除六项职责 |
| C5-09 | `file://` 句柄在 `os_permission=denied` 时先被 OS 边界拒绝 |
| C5-10 | 记忆句柄只有 `task.read`，缺 `memory.read`，`required_action=memory.read` |
| C5-11 | 幂等索引、审计日志、任务树三项都被列为禁止晋升 |

C6 的 7 条 automated 都命中投影字段：

| 用例 | 投影结果 |
|---|---|
| C6-01 | Android AppFunction 保留 `android.appfunctions` 与 `com.example.calendar.createEvent` |
| C6-02 | Apple App Intent 保留 `apple.app_intents` 与 `CreateEventIntent` |
| C6-03 | Windows App Action 保留 `windows.app_actions` 与 `CreateEventAction` |
| C6-04 | MCP 拆出 `server=calendar-server`、`tool=create_event`，保留 `osap.calendar.event/v1` |
| C6-05 | A2A 从 `#` 恢复 Agent Card 与 `skill=create_event` |
| C6-06 | D-Bus 恢复 `bus=session`、`path=/org/example/Calendar`、`interface=org.example.Calendar`、`method=CreateEvent` |
| C6-07 | 外部 MCP 的 `system` 声明被降为 `unverified`，`origin=external` |

C7 的 6 条 automated 也逐条核对：

| 用例 | 实际判定 |
|---|---|
| C7-02 | `events[1].prev_hash` 改成 `sha256:tampered0000`，在索引 1 报 `AUDIT_CHAIN_INVALID` |
| C7-03 | 保留 `hash`/`prev_hash`，替换目标/策略/回执/上下文引用后仍通过验证；明文不可恢复 |
| C7-04 | 跨用户且 `cross_user_enabled=false`，报 `POLICY_DENIED` |
| C7-05 | 两次回放只有 1 次副作用，`idempotent_replay=true` |
| C7-06 | 只有 `effect.intent`，`effect_state=unknown` 且 `alerted=true` |
| C7-07 | 声明 P0 能防被攻破的 Bus，报告 `conforming=false`、`p1_required=true` |

### 5.2.1 同意消息流（M2.4b）的覆盖

M2.4b 不新增一致性编号：它把 §10.2–§10.3 的流程接到 `consent.py` 的回执校验与 `capability.py` 的签发之上，由 44 条单元测试覆盖。关键不变量：

| 不变量 | 断言 |
|---|---|
| 请求先落库、TTL 可解析 | `intent_preview.ttl=PT10M` → `expires_at=10:24:45Z`；缺省 10 分钟；非法 duration 报 `SCHEMA_INVALID` |
| 重复请求不覆盖 | 同一 `request_id` 第二次 `request` 报 `DUPLICATE` |
| 预约是惰性的 | `reserve_cap_id` 后 `usable(cap_id)=false`，也不在 `CapabilityAuthority.issued` 中 |
| 预约先于授权 | 未预约直接 `grant` 报 `POLICY_DENIED`，`details.reason=missing_reservation` |
| 只接受请求提供的选项 | `allow_ttl` 未在 `options` 中时报 `SCHEMA_INVALID` 并列出 `offered` |
| `allow_once` 固化一次 | 回执 `constraints.max_uses=1`，不依赖调用方参数 |
| 回执不超过请求 | 请求到期 10:24:45Z，回执请求 24 小时也取 10:24:45Z；早于请求则保留更早值 |
| 授权不等于激活 | `grant` 后 `usable=false`；`activate` 才调用 `issue` 并置 `active` |
| 范围不匹配拒绝激活 | 换 `cap_id` 或放宽 `actions` 报 `POLICY_CONSENT_SCOPE_MISMATCH` |
| 拒绝永久作废 | `deny` 把预约置 `cancelled`；之后 `grant` 报 `POLICY_DENIED`，激活被拒 |
| 撤销级联 | `revoke(receipt_id)` 把预约置 `revoked`，并让 `CapabilityAuthority.revoke` 级联到后代 |
| 审计动作 | 正常路径依次记录 `consent.requested` → `consent.granted` → `capability.issued`；拒绝与撤销各有独立事件 |

C1-05 与 C2-03 是 `observe`：前者规范允许“拒绝或宽限期接受”，实现选择拒绝；后者报告实际观察到的字段。

### 5.2.2 真实传输（M2.1b）的覆盖

C0-01 与 C0-06 已从 manual 改为 automated，因为适配器现在真的建立 `AF_UNIX` socket：

| 用例 | 传输 | 断言 |
|---|---|---|
| C0-01 | UDS stream | 连接后不发 `hello`，直接发 `examples/request.json`；服务端返回 `TRANSPORT_HANDSHAKE_REQUIRED` 错误帧 |
| C0-06 | `AF_UNIX` `SOCK_DGRAM` | `hello` 以一条无前缀数据报发送；收到 `welcome`，`binding=message`、`native_boundary=true`、`length_prefix=false` |

16 条传输集成测试另外覆盖：

- 同一 UDS 连接上的 `hello` → `request` 往返；
- 每条连接独立 `Bus`，第二条连接未握手仍被拒绝；
- 4 字节头超过 8 MiB 时返回 `TRANSPORT_FRAME_TOO_LARGE`；
- 消息型发送超过 8 MiB 时在发送侧拒绝；
- uid/gid/pid/可执行文件匹配，错误 uid 或可执行文件被 `AUTH_DENIED` 拒绝；
- 平台给不出策略要求的字段时 fail closed；
- `server.close()` 删除 socket 文件，路径上是普通文件时拒绝启动。

### 5.2.3 撤销传播基准（M2 退出标准）

规范只给了“单机 P95 < 100 ms”的自测口径，没有定义传播的观察点。参考实现没有跨进程通知，因此把口径固定为：**从 `revoke(根)` 返回，到树中每个后代 `is_revoked()` 都为真**。

```
python3 tools/benchmark_revocation.py
→ tree: width=6 depth=4 tokens=1555 samples=100
  p50=0.921 ms  p95=1.225 ms  p99=1.830 ms  max=5.969 ms  mean=1.020 ms
  PASS: p95 is below 100.000 ms
```

为了让这个数字有意义，`CapabilityAuthority` 改为在 `issue` 时维护 `parent_cap_id → 子 cap_id` 索引，`revoke` 做一次广度优先遍历；旧的“每轮扫描全部凭证”在深链上是 O(n²)。基准不计入凭证签发、持久账本读写或任何跨进程投递，这些不在 M2 的实现范围内。

### 5.3 设计决定

| 决定 | 理由 |
|---|---|
| 校验顺序：版本 → 类型 → JSON Schema | §7.9 要求未知类型返回 `SCHEMA_UNSUPPORTED`；若先跑 schema，`enum` 会先报 `SCHEMA_INVALID` |
| 消息型绑定不设统一加前缀的 `encode()` 默认路径 | 避免 C0-06 的“再套一层长度前缀” |
| UDS stream 每连接一个 `Bus`，socket 文件 `chmod 0600` | 握手状态属于连接，不跨对端泄漏；同用户其他进程也要先过文件权限 |
| 消息型本地绑定用 `AF_UNIX` 数据报 socketpair | macOS 不支持 `SOCK_SEQPACKET`；数据报天然保留“一报一消息”，无需长度前缀 |
| 对端认证 fail closed | 策略要求的 uid/gid/pid/可执行文件拿不到时拒绝，而不是降级为“无法验证即通过” |
| 撤销维护父→子索引 | 深链上把传播从 O(n²) 降到 O(n)，P95 才有可比性；重复撤销返回 0 且不重复写审计 |
| deadline 只保存预算，剩余时间一律用 `time.monotonic()` | 墙钟回拨或挂起恢复不得复活请求（C0-07） |
| `STANDARD_CODES` 单点定义 | 错误码只出现一次，测试反查 §7.7 的 `retryable` 列 |
| 签名覆盖“去掉 `signature` 后的 key 排序 JSON” | 确定性强、跨语言可复现；不是完整 RFC 8785，已在代码里写明 |
| 注册按固定顺序拒绝，不区分原因对外暴露 | 避免把“App 未注册”“公钥不匹配”变成探测信号（§4.1） |
| 清单先验签再索引，记录先验证再判 TTL | §6.1 与 §6.10 的顺序要求 |
| 已定义但未实现的消息类型抛 `NotImplementedError` | 不占用错误码命名空间，也不伪装成 `pass` |
| 衰减只从“原始夹具”派生父凭证 | C3-04…C3-07 的 `context` 指向未变异的能力夹具，适配器取 `cap_id = parent_cap_id`、`depth = depth - 1`；父与子只在被测维度不同，违例不会被共享变异抵消 |
| 接收方从信封解析，不从凭证读取 | 若拿凭证自己的 `audience` 当接收方，C3-01 会假通过；`to.capability` 经注册表解析到声明该能力的 Agent |
| 能力与回执的“现在”取信封 `ts` | 夹具固定在 2026-11-10，用例不会随时间失效，且同一条消息共享同一时间基准 |
| 回执校验顺序：决策 → 过期 → 范围 | 同一输入总是同一错误码；C3-10（同时过期且范围变窄）必须报 `POLICY_CONSENT_EXPIRED` |
| 父凭证限定的预算维度在子凭证缺失时视为放宽 | `max_budget` 省略某维等于无界，与 AI2“单调收窄”一致 |
| 委派超预算报 `POLICY_DENIED`，执行期超支报 `TASK_BUDGET_EXCEEDED` | §8.6 只定义执行期错误；委派是拒绝签发，规范无专用码，按 C4-02 的约定处理 |
| 任务 `budget.depth` 视为绝对深度 | 子任务 = 父任务 + 1，与能力衰减的 `depth` 规则一致，两条路径不会互相矛盾 |
| handoff 不引入新状态 | §8.9 明确不加 `handoff_pending`；拒绝时 `owner`/`budget`/`status` 原样返回 |
| 取消跳过整棵 detached 子树 | §8.7 允许 detached 子任务继续，且必须失去父能力，父链取消不应再影响它 |
| C5 的“现在”取句柄 `created_at` | 不应让夹具随墙钟失效；C5-02 的过期变异必须稳定能触发 |
| 身份、OS 权限与授权先于过期判定 | 无权限的调用者不应学到句柄是否过期；C5-02 的 audience 匹配，仍会正确报 `CONTEXT_EXPIRED` |
| D-Bus 原生身份按内容解析 | 冒号可能出现在各段；取首段为 bus、`/` 开头段为 path、剩余段为 interface，尾段剥离 `interface.` 得 method |
| 外部协议信任只降不升 | §6.4 要求外部内容最低信任；未验签时 `verified` 与 `system` 都降为 `unverified` |
| 联邦投影只读 | 不改写原生注册表，也不改写传入字典；TTL 刷新由 `refresh()` 提供新窗口 |
| 审计链只验证链接，不重算正文哈希 | 夹具 hash 是占位串，规范未固定规范化编码；验证 schema、trace、`audit_id` 与 `prev_hash` |
| 脱敏用每次导出唯一的盐值承诺 | §10.6 要求可验证但不可恢复明文；保留 hash/prev_hash，替换敏感字段 |
| `AUDIT_CHAIN_INVALID` 作为领域扩展码 | §10.5 未定义审计专用标准码；该码不在 27 个标准码内，也不在保留前缀内 |
| 回放与恢复不执行副作用 | C7-05/06 断言的是“不重复执行”和“标 unknown”，不是真实工具调用 |
| 演示固定模拟时间 `2026-11-10T10:14:45Z` | 能力和句柄夹具都锚定这一天；用墙钟会让整条路径随时间失效 |
| 演示用两条并列委派而不是 handoff | C7-01 只要求跨两个边界；两条委派让 notes 与 calendar 都产生真实结果，比 handoff 更容易复核 |
| 演示固定脱敏盐 | 只为输出可复现；真实导出必须每次生成新盐，默认行为已在 `redact_chain` 中 |
| 演示对关键不变量做 `require()` 断言 | 避免“打印成功但实际未验证”；任何断言失败都以非零状态退出，CI 才能发现 |
| 同意流程先预约、再决定、最后激活 | §10.3 要求签发与用户决定分离；预约不写入 `issued`，`grant` 只生成回执，`activate` 才校验并签发 |
| 回执有效期取 `min(请求, 回执)` | 用户同意的是这次请求的范围与时限；回执不能把窗口延长到请求之外 |
| 拒绝/撤销把预约标成终态 | `cancelled` 与 `revoked` 都是单向的，避免“先拒绝后授权”或“先撤销后复活” |
| 同意回执的 `proof` 用占位串 | 参考实现没有 PCS 用户密钥；结构通过 schema，但验签链路留给后续里程碑 |
| 记忆句柄按 `ctx://user/memory` 前缀识别 | §9.3 未定义记忆 wire format；普通 `ctx://` 的 `scope=user` 仍只需 `resolve` |
| 标签违规返回 `observe` 而非拒绝 | C5-03 的预期是 `observe`；拒绝派生与抬高标签都合规，真正阻止泄露的是出口策略 |
| 被引用对象的硬删判为不合约 | §9.6 用 SHOULD 描述墓碑；实现区分软删（墓碑）与硬删（拒绝），并总是写审计 |

### 5.4 登记的偏差

| 位置 | 偏差 | 处理 |
|---|---|---|
| `welcome.body.data` | 规范未定义 `osap.welcome/v1` 的字段 | 返回 `osap`、`session_id`、`app`、`features`、`limits`；M2.4 定稿后回写规范 |
| 已定义但未实现的消息类型 | 没有对应错误码 | 适配器记 `skip`，报告写明里程碑 |
| 签名规范化 | 未采用完整 RFC 8785 | 采用 key 排序 UTF-8 JSON；M4 打包时对齐 |
| 一致性适配器的开发密钥环 | 示例夹具的签名是占位串 | 适配器在导入时生成一次性 Ed25519 密钥签开发清单，真实执行验签路径 |
| 能力凭证 `proof` | §5.2 要求“MUST 是签名对象”，实现只校验结构 | 密钥分发与验签待补，尚未纳入任何里程碑 |
| 回执 `agent` 绑定 | §5.8 未明确要求 | 额外校验 `receipt.agent == capability.subject`，不改变用例结果 |
| `max_uses` 计数 | 规范要求“5 次上限”，实现只比较上限 | 未落账使用次数，重放同一凭证不会扣减 |
| 任务状态机的非法转换 | 规范未指定错误码 | 用 `POLICY_DENIED` 并附带 `from`/`to` |
| 结果消息自带 `task.status` | §8.8 未规定如何与状态机配合 | 先校验结果契约再走状态机；对从未启动的任务返回结果会被拒绝 |
| 委派的能力链 | §8.5 要求子能力满足全部衰减条件 | 任务侧只校验预算与深度，夹具没有提供父凭证 |
| 记忆句柄识别 | §9.3 未定义记忆 wire format | 按 `ctx://user/memory` 前缀识别，要求 `memory.read` |
| 标签违规处理 | §9.4 未规定拒绝还是记录 | 解析后报告 `lowered`/`effective_label`，对应 C5-03 的 `observe` |
| 对象硬删被引用对象 | §9.6 用 SHOULD 描述墓碑 | 判为不合约；软删返回墓碑并写审计 |
| 原生 `native_id` 格式 | §6.7 是建议映射，schema 只要求非空 | 解析失败报 `SCHEMA_INVALID`，不静默投影为空字段 |
| 外部协议信任等级 | §6.4 未规定验签失败时的具体等级 | 一律 `unverified`；只有可验证的本地来源保留 `system` |
| 审计链错误码 | §10.5 未定义审计专用标准码 | `AUDIT_CHAIN_INVALID` 是领域扩展码，`is_standard` 与 `is_extension` 均为 false |
| 审计链 hash | 规范未固定规范化编码，夹具 hash 是占位串 | 只验证事件 schema、trace、`audit_id` 与链接，不重算正文摘要 |
| 演示的清单密钥 | 示例夹具只有占位签名 | 每次运行生成新的 Ed25519 密钥，会话 ID 因此会变；判定结果不变 |
| 演示的传输 | 没有真实 UDS/XPC/D-Bus | 消息是内存字典，只证明协议语义，不证明传输行为 |
| 消息型本地绑定 | macOS 推荐 XPC、Android 推荐 Binder | 用 `AF_UNIX` 数据报 socketpair 保留消息边界；平台原生绑定留给适配层 |
| 对端认证失败 | §7.7 没有传输认证专用码 | 用 `AUTH_DENIED`，`details.reason` 区分 `peer_mismatch` 与 `peer_field_unavailable` |
| 对端可执行文件校验 | §7.10 要求“可执行文件校验” | Linux/macOS 解析可执行路径；字段缺失时拒绝，不降级为只看 uid |
| 同意流程的回执 `proof` | 没有 PCS 用户密钥 | 生成结构合法的占位 `kid`/`sig`；`consent.validate` 只校验范围与时间 |
| 预约被拒绝/撤销后的错误码 | §10.3 只要求“不可再激活”，未定义码 | 统一 `POLICY_DENIED`，`details` 带 `cap_id` 与预约状态 |
| 未预约先授权 | 规范只规定顺序，未规定错误码 | `POLICY_DENIED` + `details.reason=missing_reservation`，与“用户未同意”区分 |

### 5.5 已知限制

1. 幂等索引、注册表、轮换状态都在内存，重启即丢；§7.8 要求可重建的持久索引，尚未实现。
2. `auth.token` 与能力 `proof.sig` 都只做结构校验，没有验签；密钥分发链路未实现。
3. 传输绑定只有 `AF_UNIX` stream 与数据报 socketpair；没有 XPC、Binder、named pipe 或 localhost mTLS。
4. 对端认证覆盖 uid/gid/pid/可执行文件（Linux `SO_PEERCRED`，macOS `getpeereid` + `LOCAL_PEERPID`），没有 audit token、package identity 或代码签名；同 uid 的其他进程只有在设置可执行文件策略后才被排除。
5. 撤销集合只在内存，重启即丢，也没有广播；§5.5 要求写入审计账本并通知受影响 Agent，尚未实现。
6. `max_uses` 未计数，`rate` 未限流；衰减只比较声明值。
7. 任务树在 M2 时只在内存；M4 前置已把整棵树接入 `JsonStore`（见第 10 节）。`TaskBoard` 仍不产生 `effect.intent`，`audit.recover_effects` 只读已有事件，C4-08/C4-09 仍是 manual。
8. 上下文审计与黑板状态只在内存，没有真正撤销句柄；§9.7 的“谁在何时解析了哪个句柄”只能读进程内列表。
9. 没有真实对象存储：`delete_object` 只返回判定，不触碰文件系统；`storage_declaration` 只核对声明，不实现配额、GC 或加密。
10. 联邦只做投影：没有监听原生注册表变化，也没有按 TTL 自动刷新，C6-08 仍是 manual；MCP/A2A/OpenAPI 的签名未验证。
11. `verify_chain` 对夹具链仍只验证 schema、trace、`audit_id` 与 `prev_hash` 链接；新增的 `AuditLedger` 对自己的事件重算正文哈希，因此损坏的持久链会在重启时 fail closed。
12. 上下文只在内存；任务树与审计账本已持久化（见第 10、11 节），但跨进程回放与 C7-01 仍未实现。
13. 62 个 pass 覆盖全部 automated 用例；6 条 manual 仍依赖崩溃恢复与跨 App 集成。
14. 演示是进程内单进程：它证明模块能串起来，不证明真实传输、真实 OS 句柄或持久账本。
15. `ConsentFlow` 的请求、回执与预约都只在内存；重启即丢，也没有把同一请求广播给多个 Bus。
16. 同意回执的 `proof` 是占位串，没有 PCS 用户密钥的分发与验签。
17. 一个 `ConsentFlow` 只绑定一个 `user://`，没有多用户会话、代理同意或组织策略。
18. UDS 服务端在 M2 时串行处理连接，没有 §7.11 的连接并发、admission control、在途请求上限或 rate limit（后续已补，见第 9 节）。
19. 撤销传播的 P95 只覆盖进程内标记与观察；跨进程通知、持久账本写入和重试都不在这个数字里。

### 5.6 M2 剩余工作

- [x] **M2.1b**：真实传输绑定（UDS stream + 消息型 socketpair）与对端认证，C0-01/C0-06 已自动化（`impl/osap/transport.py`；16 条集成测试）；
- [x] **M2.2**：身份、签名、注册表（C1 全绿，C2 automated 全绿）；
- [x] **M2.3**：能力签发、衰减、绑定、撤销（C3-01…C3-08 全绿）；
- [x] **M2.4**：风险前置与同意回执校验（C3-09…C3-12 全绿）；
- [x] **M2.4b**：`consent.request` / `grant` / `deny` 的消息流、回执签发、`cap_id` 预约顺序（`impl/osap/consent_flow.py`；44 条单元测试，演示第 3 节接入）；
- [x] **M2.5a**：任务树、委派、预算、取消、结果、handoff（C4 automated 8/8）；
- [x] **M2.5b**：上下文织构（C5 11/11）；
- [x] **M2.5c**：联邦适配器（C6 automated 7/7）；
- [x] **M2.6**：审计链、脱敏导出、回放、恢复与跨用户边界（C7 automated 6/6）；
- [x] **M2.7**：三 Agent 演示（`demo/run_demo.py`；两个委派边界、16 条审计事件、脱敏与恢复断言）。

---

## 6. M3 — 形式化不变量（已完成）

### 6.1 交付物

| 文件 | 作用 |
|---|---|
| `spec/formal/Capability.tla` | 能力签发、衰减、撤销的 TLA+ 状态机 |
| `spec/formal/Task.tla` | 任务树、预算、消耗、完成、取消与 `detached` 子树 |
| `spec/formal/Consent.tla` | 同意请求、`cap_id` 预约、授权/拒绝、激活与撤销 |
| `spec/formal/Recovery.tla` | §8.11 的 `intent` / `outcome` / `unknown` 崩溃对账 |
| `spec/formal/Capability.cfg` / `Task.cfg` / `Consent.cfg` / `Recovery.cfg` | 正常配置，有限常量 |
| `spec/formal/CapabilityBroken.cfg` / `RecoveryBroken.cfg` | 负向对照：放宽衰减或允许盲重试后必须报反例 |
| `spec/formal/check.sh` | 依次运行四个正常配置与两个负向对照 |
| `spec/formal/README.md` | 不变量到条文、结果、模型边界 |

### 6.2 验证证据

2026-11-15，`tla2tools` v1.7.4、TLC 2.19、单 worker：

```
spec/formal/check.sh
→ Capability: 61,267 states generated, 16,866 distinct states found
→ Task:       78,551 states generated, 15,972 distinct states found
→ Consent:     6,850 states generated,  2,532 distinct states found
→ Recovery:        8 states generated,      6 distinct states found
→ CapabilityBroken: Invariant AttenuationMonotonic is violated.
→ RecoveryBroken:   Invariant AtMostOnce is violated.
→ OK: all positive models pass and both negative controls fail
```

四条主不变量分别对应 §5.3、§5.5、§8.6、§8.7；`Consent.tla` 覆盖 §10.3 的“先预约、再授权、后激活”，`Recovery.tla` 覆盖 §8.11 的三态。四个模型合计 19 条断言（含 `TypeOK`），所有常量都在 `.cfg` 中限定，状态空间可枚举。

### 6.3 模型发现的实现缺口

`Capability.tla` 初版允许从已撤销的父能力继续 `Attenuate`。TLC 的反例是“先撤销根，再从根派生新能力”，此时 `RevocationCascade` 被破坏。参考实现当时同样只校验 schema 与索引，没有检查父能力是否已撤销。

修复：

- 已撤销的 `cap_id` 不能再 `issue`；
- `parent_cap_id` 已撤销时拒绝派生，返回 `CAPABILITY_REVOKED`；
- 新增两条单元测试固定这两个路径。

### 6.4 设计决定

| 决定 | 理由 |
|---|---|
| `Revoke` / `Cancel` 在一个原子步骤里做有界闭包 | 规范承诺的是可观察结果；把异步传播拆成多步会让“未传播完”的状态破坏不变量 |
| 闭包用 `MaxDepth` 次迭代而不是无界递归 | TLC 可直接展开；模型中的树深由配置固定，超出深度的派生不会发生 |
| `Task.tla` 的委托检查基于父任务“剩余预算” | 与 `impl/osap/task.py` 一致；`BudgetMonotonic` 只断言沿链不增长，避免把运行期消耗误当新上界 |
| 取消把 `results` 清零 | 规范要求取消后子树不再产生新 `result`；已产生的结果留在审计里，不进入可用状态 |
| `Consent.tla` 用 `granted_once` 记录历史 | 单靠 `phase` 无法证明“激活前确实授权过”；历史变量让 `ActivationHadGrant` 可检查 |
| `Recovery.tla` 把 `unknown` 分成“无副作用”与“已执行”两种对账结果 | 前者回到 `idle`，后者进入 `done`；两者都不重新执行副作用 |
| `AllowWidening` / `AllowBlindRetry` 只服务负向对照 | 证明模型不是空转：放宽一条约束后 TLC 必须给出反例 |

### 6.5 未建模

1. `RevocationSet` 的跨进程分发、持久化与重放；
2. 同意回执的真实 `proof` 验签与 PCS 用户密钥；
3. 跨进程通知、重试与传播时延（由 `tools/benchmark_revocation.py` 单独测量）；
4. 错误码、JSON 编码、传输绑定与审计链。

Alloy 补充模型不采用：四条主不变量的关系约束在 TLA+ 中已经可读，两个负向对照也足以证明模型非空转。

---

## 7. 持久化基础（M4 前置，已完成）

### 7.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/store.py` | `JsonStore`：按 section 组织的 JSON 文档；整文件原子替换（`os.replace` + `fsync`），文件与临时文件均为 0600；序列化失败时保留旧内容 |
| `impl/osap/idempotency.py` | 构造时可注入 `JsonStore`；`remember` / `forget` / `clear` 同步落盘，重启后同一 `id` 直接回放 |
| `impl/osap/capability.py` | 持久化 `issued` 与 `revoked`，加载时重建 `parent_cap_id → children` 索引；撤销与级联跨重启保留 |
| `impl/osap/bus.py` | `Bus` 接受显式 `IdempotencyIndex` 或 `store` 路径/实例；两者互斥，误传直接 `ValueError` |
| `impl/osap/consent_flow.py` | 持久化 `requests` / `receipts` / `reservations` 与生成的 PCS 签名密钥；`put_many` 一次原子写入三节；加载时恢复时间戳与签名者 |
| `impl/tests/test_store.py` 等 | 39 条新测试：store 往返/重开/权限/失败回滚/多节写入，幂等回放与清理，撤销级联重建，Bus 重启回放，同意流程请求/拒绝/激活/撤销/过期状态跨重启，签名密钥复用与注入 |

### 7.2 语义

- **一个路径一个 store 实例**：Bus、`CapabilityAuthority`、`ConsentFlow` 与 `TaskBoard` 可以共享同一个 `JsonStore`，各自写不同 section（`idempotency`、`capability.*`、`consent.*`、`task.tasks`），互不覆盖。两个独立 store 实例同时指向同一文件会各自写整份快照，后写者会丢掉前者的 section；这一限制写在模块文档里。
- **重启即回放，不重复执行**：`Bus.receive` 命中已持久化的 `id` 时返回缓存结果并把 `replayed` 置真，`side_effects` 不增加。C7-05 的“只执行一次”因此不再依赖进程存活。
- **撤销跨重启**：`revoke` 在返回前写入排序后的 revoked 列表；重新打开后 `is_revoked`、`check_validity` 与“已撤销父不能派生”都保持原判定。
- **同意流程终态跨重启**：`pending` 请求仍可继续预约/授权；`denied`、`expired`、`activated`、`revoked` 保持单向；激活过的回执再次激活返回 `DUPLICATE`。
- **签名密钥随流程保存**：由 `ConsentFlow` 生成的 PCS 私钥写入 `consent.pcs_key`（文件 0600），重启后回执仍可验签；注入的 signer 不落盘，加载时会校验 `public_key` 与私钥一致。
- **审计不落盘**：`CapabilityAuthority.audit`、`ConsentFlow.audit` 与 `TaskBoard.audit` 仍是进程内列表；持久账本属于后续工作，避免把“状态持久化”误称为“审计持久化”。
- **整节重写**：每次变更重写整个 section，换取简单与原子性；`put_many` 把多节变更合并为一次 `os.replace`。参考实现不追求增量写或并发写吞吐。

### 7.3 验证证据

2026-11-16，提交 `48e744e`（幂等/能力）与 `61a9994`（同意流程）：

```
python3 -m unittest discover -s impl/tests -t impl
→ Ran 387 tests ... OK

python3 tools/check_schemas.py
→ OK: 45 checks passed across 15 schemas
python3 tools/validate_examples.py
→ OK: 24 checks passed
python3 tools/check_docs.py
→ OK: 116 checks passed across 23 Markdown files
python3 tools/conformance_run.py --stub
→ 68 cases: 0 pass, 0 fail, 68 skip（无适配器）
python3 tools/conformance_run.py --impl impl/adapter.py
→ 68 cases: 62 pass, 0 fail, 6 skip
python3 demo/run_demo.py
→ registered=3 discovery=1 consent=1 receipt=verified delegated=2 context=1 audit=verified
TLA2TOOLS_JAR=... spec/formal/check.sh
→ OK: all positive models pass and both negative controls fail
```

新增的 39 条测试中，27 条覆盖 `JsonStore`、幂等回放、能力撤销与 Bus 重启；12 条覆盖同意流程的请求/拒绝/激活/撤销/过期状态、签名密钥复用与注入、损坏 section 的拒绝。

### 7.4 同意流程与签名密钥

- **section 布局**：`consent.requests`、`consent.receipts`、`consent.reservations` 与 `consent.pcs_key`；每次变更通过 `put_many` 一次原子替换，避免请求已记下但预约尚未落盘的中间态。
- **时间戳**：`requested_at` / `expires_at` 在存储中写成 UTC ISO 字符串，加载时解析回 `datetime`；判定仍使用注入时钟。
- **终态单向**：拒绝把预约标为 `cancelled`，撤销标为 `revoked`，激活标为 `active`；重新打开后 `usable()` 与再次 `activate()` 都保持原判定。
- **签名者恢复**：未注入 `signer` 时优先复用 `consent.pcs_key`；没有则生成并保存。注入的 `signer` 不写入 store，适合外部密钥管理；加载时若 `public_key` 与私钥不匹配则拒绝启动。
- **边界**：私钥与回执同处一个 0600 JSON 文件，只适用于单用户参考实现；生产环境应使用 OS 密钥环或独立 PCS 服务。

### 7.5 已知边界

1. 单进程、单写者；没有跨进程文件锁、租约或冲突合并；
2. 外部副作用没有 write-ahead：动作执行后才落盘幂等结果，进程在两步之间崩溃仍可能重复执行；协议层只能要求实现对账；
3. 上下文仍未持久化；任务树与审计账本已在第 10、11 节接入 `JsonStore`；
4. 没有 TTL 清理、压缩或归档；长期运行会把所有已见 `id`、历史凭证与已完成同意流程留在同一文件里；
5. PCS 私钥落在同一个 JSON 文件里，没有 OS 密钥环集成或密钥轮换。

---

## 8. PCS 回执签名（M4 前置，已完成）

### 8.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/pcs.py` | `sign_receipt` / `verify_receipt` / `require_verified_receipt`；`ConsentSigner` 持有 Ed25519 私钥，只导出 `{kid, public_key}` |
| `impl/osap/consent_flow.py` | `ConsentFlow` 默认生成签名者；`grant` 签回执，`activate` 在检查预约前先验签；可注入稳定 signer |
| `impl/tests/test_pcs.py` | 签名确定性、篡改字段、错误密钥、`kid` 不匹配、畸形 proof、未知密钥 |
| `impl/tests/test_consent_flow.py` | 注入 signer、Agent 自签回执、篡改回执、缺 proof 均无法激活；`pcs_key` 只含公钥 |
| `demo/run_demo.py` | grant 后用 PCS 公钥独立验签，结尾增加 `receipt=verified` |

### 8.2 语义

- **签名范围**：与清单签名共用 `crypto.canonical_bytes`，但 `drop=("proof",)`；`proof` 是算法、`kid`、签名值等元数据，不参与被签正文。
- **验签顺序**：`activate` 取到回执后先验签，再检查预约是 `cancelled` / `revoked` / `active`。伪造或篡改的回执只能得到 `AUTH_DENIED`，不能通过错误差异探测 `cap_id` 状态。
- **错误码**：§7.7 的 `AUTH_DENIED` 已覆盖“签名校验失败”，不新增码；`details.reason` 区分 `receipt_signature_invalid` 与 `receipt_key_unknown`。
- **Agent 不能自签**：签名私钥只存在于 `ConsentSigner`；用另一把密钥重签同一正文，即使 `kid` 相同也无法通过 `ConsentSigner.require`。
- **离线验证**：验证方只需要 PCS 公钥；`examples/consent-receipt.json` 仍是范围校验夹具，其占位 `proof` 不进入验签路径。

### 8.3 验证证据

2026-11-16，提交 `092c710`：

```
python3 -m unittest discover -s impl/tests -t impl
→ Ran 375 tests ... OK

python3 tools/conformance_run.py --impl impl/adapter.py
→ 68 cases: 62 pass, 0 fail, 6 skip
python3 demo/run_demo.py
→ ... consent=1 receipt=verified delegated=2 ... audit=verified
```

### 8.4 已知边界

1. 使用 `JsonStore` 时签名密钥写入 `consent.pcs_key` 并在重启后复用；不接 store 时仍是进程内一次性生成。跨进程验签需要带外获得公钥；
2. PCS 公钥的登记、轮换与撤销没有协议；验证方需要带外获得公钥；
3. 能力凭证 `proof` 仍是结构校验，未由 CA 私钥覆盖；
4. 示例回执的 `proof` 是占位串；只有 `ConsentFlow` 产出的回执进入验签路径。

---

## 9. 流控与背压（M4 前置，已完成）

### 9.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/flowcontrol.py` | `Quota` / `AdmissionController` / `Admission`：每身份连接、在途、队列上限与令牌桶；`RATE_LIMIT` 附带 `reason`、`retry_after_ms`、队列深度与配额 |
| `impl/osap/bus.py` | `Bus(admission=..., admission_wait=...)`；每条信封先过 admission 再校验/路由；默认配额为 32 连接 / 16 在途 / 32 排队 / 200 条每秒 |
| `impl/osap/transport.py` | 监听器按内核可证身份限制连接数；拒绝时先回 `RATE_LIMIT` 再关闭；默认 Bus 工厂共享同一控制器；`serve_forever(concurrency=N)` 用线程池并行服务多个连接 |
| `impl/tests/test_flowcontrol.py` 等 | 35 条新测试：28 条 controller/Bus，4 条连接配额与传输，3 条并发服务 |

### 9.2 语义

- **每身份隔离**：令牌桶、在途计数与等待队列都以身份为键。一个 Agent 排满自己的队列不会占用另一个 Agent 的槽位，避免全局队头阻塞。
- **连接配额用内核身份**：握手前没有 Agent URI，因此按可执行文件路径 → pid → uid 回退；无法识别的对端共享 `unknown` 桶，而不是绕过配额。
- **消息配额用 `from`**：握手后按信封 `from` 的 Agent URI 计数；`from` 缺失或不是字符串时落入 `unknown`。连接配额与消息配额是两套键，互不冒充。
- **令牌桶**：初始满桶，按 `time.monotonic()` 连续补充，上限为 `rate`；`rate=0` 表示全部拒绝；`rate=None` 表示不限速。`retry_after_ms` 只在 `rate > 0` 时给出。
- **有界 FIFO 队列**：`max_in_flight` 满时可等待，等待人数由 `max_queued` 限制；先到先得，因此低优先级/晚到请求不会永久饥饿。`priority` 未接入，加权公平队列属于规范的 SHOULD，未实现。
- **等待是显式选择**：`AdmissionController.admit(timeout=...)` 才会等待；`Bus.admission_wait` 默认 0，即不排队、直接 `RATE_LIMIT`。等待超时只移除自己的 waiter，不释放别人占用的在途槽位，并归还本次预扣的令牌。
- **显式背压**：所有拒绝都用标准码 `RATE_LIMIT`，`details.reason` 为 `rate_limited`、`in_flight_limit`、`queue_full`、`queue_timeout` 或 `connection_limit`；`details.quota` 给出完整配额，`details.in_flight` / `queued` / `connections` 给出当时计数。
- **失败也释放**：`Admission` 是上下文管理器；`dispatch` 抛 `OsapError` 或 `NotImplementedError` 时槽位照常归还。被限流的消息不执行副作用，也不进入 `Bus.received`。
- **连接拒绝可诊断**：`UnixStreamServer.accept` 在配额拒绝时先发送一个 `osap.error/v1` 帧再关闭，避免客户端把“静默断开”误判为网络故障并立即重试。
- **并发服务**：`UnixStreamServer.serve_forever(concurrency=N)` 把已接受的连接提交给大小为 N 的线程池；accept 循环与 worker 分离，空闲或慢速连接只占用自己的 worker，不再阻塞其他连接被 accept。`concurrency=1` 保持原有串行语义。
- **跨连接共享配额**：默认 Bus 工厂把服务器的 `AdmissionController` 与 `admission_wait` 传给每个连接。同一 Agent 的多个连接共享在途与排队配额；不同 Agent 仍各有独立的桶和队列。
- **可停止的 worker**：`max_messages` 是 best-effort 上限；`close()` 关闭监听器并 shutdown 所有会话 socket，让阻塞在 `receive` 的 worker 退出，`serve_forever` 不会留下悬挂线程。

### 9.3 验证证据

2026-11-17，提交 `0b13483`（流控）与 `eaf8260`（并发服务）：

```
python3 -m unittest discover -s impl/tests -t impl
→ Ran 422 tests ... OK

python3 tools/check_schemas.py
→ OK: 45 checks passed across 15 schemas
python3 tools/validate_examples.py
→ OK: 24 checks passed
python3 tools/check_docs.py
→ OK: 116 checks passed across 23 Markdown files
python3 tools/conformance_run.py --stub
→ 68 cases: 0 pass, 0 fail, 68 skip（无适配器）
python3 tools/conformance_run.py --impl impl/adapter.py
→ 68 cases: 62 pass, 0 fail, 6 skip
python3 demo/run_demo.py
→ registered=3 discovery=1 consent=1 receipt=verified delegated=2 context=1 audit=verified
```

新增的 35 条测试覆盖：配额校验；满桶、补充、封顶与零速率；同身份限流与跨身份隔离；在途上限、队列满、队列超时与令牌归还；连接上限与释放；真实 UDS 连接拒绝与 `RATE_LIMIT` 帧；共享控制器；dispatch 失败后的槽位释放；空闲连接旁的活动连接；同一 Agent 跨连接等待一个在途槽位；并发参数校验。

### 9.4 已知边界

1. **并发上限由线程池决定**：`serve_forever(concurrency=N)` 每连接一个线程，连接数很高时线程与内存成本线性增长；没有事件循环或异步 I/O，也没有按 Agent 的独立调度权重。
2. **`priority` 只是规范提示**：参考实现不读取 `priority`，FIFO 满足“不得饥饿”的 MUST；加权公平队列与 credit-based 流控是 SHOULD，未实现。
3. **配额状态在内存**：令牌桶与计数器重启清零，没有跨进程共享或持久化；多进程部署需要外部限流器。
4. **等待队列的公平性限于单进程**：`max_queued` 只约束同一控制器实例的等待者；多个 Bus 只有共享同一个 `AdmissionController` 时才共享配额。
5. **`status` 消息尚未路由**：队列深度通过 `AdmissionController.snapshot()` 提供，尚未作为 `status` 消息正文返回。
6. **`max_messages` 是 best-effort**：并发模式下，已受理但尚未完成的回复也占用上限；失败时会归还，因此它适合有界测试与优雅停止，不是协议级配额。

---

## 10. 任务树持久化（M4 前置，已完成）

### 10.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/task.py` | `TaskBoard(store=...)` 把整棵树写入 `task.tasks`；`Task.to_state()` / `from_state()` 无损记录状态、预算、消耗、`detached`、父子链、会话与结果契约；加载时校验结构 |
| `impl/tests/test_task.py` | 18 条新测试：整树重开、恢复后继续转换、委派/取消/handoff 跨重启、detached 子树、审计不落盘、共享 store 隔离、损坏 section 拒绝，以及每个变更方法只写一次 |

### 10.2 语义

- **无损状态**：`snapshot()` 只用于对外摘要，缺少 `root_task_id`、`parent_task_id`、`session_id`、`result_schema`、`consumed` 与 `detached`。持久化改用 `to_state()`，因此重启后预算消耗与 detached 判定不会丢失。
- **一次变更一次写入**：`add`、`transition`、`cancel`、`delegate`、`handoff` 在完成内存修改后各写一次整节；`cancel` 遍历整棵子树也只写一次。`transition` 传入相同状态或 `handoff` 被拒绝时不写盘。
- **加载即校验**：section 必须是对象；每条记录必须是对象，`task_id` 必须与键一致，`status` 必须在 `STATUSES` 内，`budget` / `authority` / `consumed` 必须是对象，`detached` 必须是布尔，可选字符串字段必须是字符串或 null。损坏文件在构造时抛 `ValueError`，不会得到半棵树。
- **审计仍在内存**：`TaskBoard.audit` 不落盘，与其他子系统一致；它记录的是过程，不是可恢复状态。
- **共享 store**：任务树写 `task.tasks`，与 `idempotency`、`capability.*`、`consent.*` 并列；同一个 `JsonStore` 上其他 section 不受影响。

### 10.3 验证证据

2026-11-17，提交 `f47abd7`：

```
python3 -m unittest discover -s impl/tests -t impl
→ Ran 440 tests ... OK

python3 tools/check_schemas.py
→ OK: 45 checks passed across 15 schemas
python3 tools/validate_examples.py
→ OK: 24 checks passed
python3 tools/check_docs.py
→ OK: 116 checks passed across 23 Markdown files
python3 tools/conformance_run.py --stub
→ 68 cases: 0 pass, 0 fail, 68 skip（无适配器）
python3 tools/conformance_run.py --impl impl/adapter.py
→ 68 cases: 62 pass, 0 fail, 6 skip
python3 demo/run_demo.py
→ registered=3 discovery=1 consent=1 receipt=verified delegated=2 context=1 audit=verified
```

新增的 18 条测试覆盖：整树重开后的状态、预算、`consumed`、`detached`、父子链、会话与结果契约；恢复后继续状态转换；委派、取消与 handoff 跨重启；detached 子树不被父取消；审计不落盘；共享 store 的其他 section 不被覆盖；损坏 section、未知状态、键不一致与缺预算的拒绝；以及 `add` / `delegate` / `cancel` / `transition` / `handoff` 的单次写入行为。

### 10.4 已知边界

1. **整节重写**：任务数量很大时每次变更都序列化整棵树；没有增量更新或分片。
2. **单进程单写者**：没有跨进程文件锁；两个 store 实例会互相覆盖。
3. **过程状态未落盘**：`TaskBoard.audit` 与 `effect.intent` 仍未持久化，C4-08/C4-09 仍是 manual。
4. **不做引用完整性检查**：加载不要求父任务存在于同一 section（夹具允许父链在外部），也不检测父子环。
5. **不清理历史**：已终态任务永久留在文件中；长期运行需要归档或 TTL 清理。

---

## 11. 审计账本持久化（M4 前置，已完成）

### 11.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/audit.py` | `AuditLedger`：单 trace 追加链，自动填充 `audit_id`、`ts`、`prev_hash`、`hash`；`chain()` 导出可脱敏对象；`verify()` 在链接校验后重算正文哈希；按 `audit.chain.<trace_id>` 持久化 |
| `impl/tests/test_audit.py` | 17 条新测试：字段填充与链接、重复 `audit_id`/外部 trace/非法事件拒绝、返回副本、正文哈希重算、脱敏、重开、按 trace 隔离，以及损坏 section/断链/错误 trace/错误形状的 fail closed |

### 11.2 语义

- **账本拥有哈希**：`append` 在调用方给出的语义字段上补齐 `trace_id`、`audit_id`、`ts`，把 `prev_hash` 设为当前链头，再对去掉 `hash` 的事件计算规范哈希。编码与签名共用 `crypto.canonical_bytes`：key 排序、最小分隔符、UTF-8 JSON。
- **一次追加一次写入**：每条事件通过 `JsonStore.put` 原子替换该 trace 的 section；被拒绝的事件不会进入 `events`，也不会产生写入。
- **重启即校验**：`_restore` 先要求 section 是对象、`trace_id` 与构造参数一致、`events` 是数组，再调用 `verify()`。`verify()` 先跑原有的 schema/trace/链接检查，再逐条重算正文哈希，因此“改了正文却保留旧 hash”会在重启时被拒绝。
- **失败关闭**：断链、重复 `audit_id`、正文哈希不匹配、section 内 trace 不一致都抛 `AUDIT_CHAIN_INVALID`；section 形状错误抛 `ValueError`。加载失败不会留下半个账本，L3/L4 调用方应据此保持关闭（§3.7）。
- **按 trace 分区**：每个 trace 写自己的 `audit.chain.<trace_id>` section，多个 `AuditLedger` 可以共享同一个 `JsonStore` 而互不覆盖；没有跨 trace 的全局顺序。
- **与只读校验共存**：`verify_chain` 对夹具链的行为不变，仍只验证 schema、trace、`audit_id` 唯一性与 `prev_hash` 链接；重算正文哈希只发生在账本自己的事件上，因为夹具 hash 是占位串、规范也未固定编码。
- **导出可继续脱敏**：`chain()` 返回深拷贝，可直接传给 `redact_chain`；脱敏保留 hash 链，只替换敏感字段。

### 11.3 验证证据

2026-11-17，提交 `ca808b9`：

```
python3 -m unittest discover -s impl/tests -t impl
→ Ran 457 tests ... OK

python3 tools/check_schemas.py
→ OK: 45 checks passed across 15 schemas
python3 tools/validate_examples.py
→ OK: 24 checks passed
python3 tools/check_docs.py
→ OK: 116 checks passed across 23 Markdown files
python3 tools/conformance_run.py --stub
→ 68 cases: 0 pass, 0 fail, 68 skip（无适配器）
python3 tools/conformance_run.py --impl impl/adapter.py
→ 68 cases: 62 pass, 0 fail, 6 skip
python3 demo/run_demo.py
→ registered=3 discovery=1 consent=1 receipt=verified delegated=2 context=1 audit=verified
```

新增的 17 条测试覆盖：自动字段与首尾链接；显式 `audit_id`/`ts` 保留；重复 id、外部 trace、非法事件不落盘；返回值与内部状态隔离；正文哈希重算；账本链脱敏；重开后事件与链头一致；多 trace 共享 store；正文篡改、断链、错误 trace、非对象 section、非数组 events 与损坏事件形状的拒绝；空账本不写 section。

### 11.4 已知边界

1. **一个账本一个 trace**：没有跨 trace 的全局顺序、合并链头或统一的查询接口。
2. **整节重写**：长链每次追加都序列化全部事件；没有分段、日志结构或增量写。
3. **没有保留策略**：没有归档、截断、TTL 或按用户分区；§3.7 的多实例 leader election 仍未实现，单写者约束靠调用方保证。
4. **未自动接入**：`Bus`、`TaskBoard` 与 `ContextFabric` 不会自动向账本追加事件；调用方显式调用 `append`。
5. **编码仍是参考实现约定**：账本哈希与签名共用 `crypto.canonical_bytes`，不是完整 RFC 8785；其他实现若要逐字节复现需要采用同一编码。
6. **夹具链不重算**：`verify_chain` 对 `examples/audit-chain.json` 仍只验证链接，不能据此推断夹具中的短 hash 是真实摘要。

---

## 12. 待确认的规范问题

迁移过程中暴露的歧义。M1 用例已按暂定处理落盘，以下条目需在 M2 冻结适配器 API 前定稿（不改编号，只补语义）：

| 编号 | 问题 | 处理 | 状态 |
|---|---|---|---|
| C1-05 | 密钥轮换后旧签名“按策略”拒绝，缺少最低要求 | 写为 `observe`，建议 §4.5 补“过渡期 MUST 不超过 TTL” | ⬜ 待定 |
| C2-05 | “TTL 内失效”未说明失效上限 | 以 `freshness.expires_at` 为唯一判据 | ✅ 已采用 |
| C4-02 | 委派预算超过父剩余时应返回哪个错误码未定义 | 暂用 `POLICY_DENIED`，用例断言“拒绝委派”这一不变量 | ⬜ 待定 |
| C5-11 | “幂等索引/审计日志/任务树”如何判定被当记忆检索 | 依赖实现自证，标 `observe` | ⬜ 待定 |
| C6-07 | `origin=external` 在 `capability-record.schema.json` 中没有对应字段 | 用例把 `origin` 作为投影后的规范化输出断言；是否写入 schema 待定 | ⬜ 待定 |
| C7-02 | 审计链校验失败没有标准错误码 | 暂用扩展码 `AUDIT_CHAIN_INVALID`，用例断言“校验 MUST 失败” | ⬜ 待定 |
| C7-07 | “被攻破的 Bus”在 0.1 的期望不明确 | 明确为“0.1 不提供该防护”，用例只记录 | ⬜ 待定 |

---

## 13. 下一步（按顺序）

1. 把上下文接到 `JsonStore`，并为审计账本补保留/归档、按用户分区与真实回放；
2. 定义 PCS 公钥的登记、轮换与撤销，并把私钥从普通 JSON 迁移到 OS 密钥环；
3. 为并发服务补事件循环或平台原生异步绑定，并加入 XPC/Binder/named pipe 等平台传输；
4. 为撤销增加跨进程分发与重试，把 P95 口径从进程内扩展到跨进程；
5. 进入 M4 标准打包：把规范拆成可独立提交的材料，并保持每个 PR 只对应一个清晰的不变量或用例。

---

## 14. 变更记录

| 日期 | 变更 |
|---|---|
| 2026-11-12 | 创建本文；记录 M0 完成、M1 达到 19/68、剩余用例拆分 |
| 2026-11-12 | M1 扩展到 31/68（C1 6 条、C2 6 条）；补 `examples/hello.json`；登记注册表错误码近似映射 |
| 2026-11-12 | M1 扩展到 42/68（C4 11 条）；envelope 增加 peer/`session_id` 条件；登记 `params` 状态模拟与委派预算错误码问题 |
| 2026-11-12 | M1 扩展到 50/68（C6 8 条）；登记 `origin` 在能力记录 schema 中缺少字段的问题 |
| 2026-11-12 | M1 扩展到 61/68（C5 11 条）；新增 `context-handle.json` 与 `blackboard.json`；登记夹具无 schema 的限制 |
| 2026-11-12 | **M1 完成**：68/68；新增 C7 与 `audit-chain.json`；JSON 报告纳入 schema 校验 |
| 2026-11-14 | **M2.5b**（`206008b`）：上下文织构（句柄授权、TTL、标签、出口、黑板、删除、缓存、存储声明、记忆边界）；C5 11/11，累计 47 pass |
| 2026-11-14 | **M2.5c**（`49cf486`）：联邦适配器（原生身份、命名空间、外部信任归一）；C6 automated 7/7，累计 54 pass |
| 2026-11-14 | **M2.6**（`0b304db`）：审计链、脱敏导出、回放、恢复、跨用户；C7 automated 6/6，累计 60 pass（全部 automated） |
| 2026-11-14 | **M2.7**（`1a4d09a`）：三 Agent 演示（notes + calendar + supervisor）；两个委派边界、16 条审计事件、脱敏与恢复断言；CI 增加 `python3 demo/run_demo.py` |
| 2026-11-15 | **M2.4b**（`f1b8453`）：同意消息流（请求、`cap_id` 预约、授权/拒绝、激活、撤销）；44 条单元测试，累计 309；演示第 3 节改为完整流程并增加 `consent.requested` 事件（16 条） |
| 2026-11-15 | **M2.1b**（`47a3f4c`）：真实传输（UDS stream + 数据报消息绑定）与对端认证；C0-01/C0-06 自动化，C0 7/7；16 条集成测试，累计 325；剩余 6 条 manual |
| 2026-11-15 | **M2 退出标准**（`b95e2c9`）：撤销传播改为父→子索引的一次遍历，重复撤销幂等；新增 `tools/benchmark_revocation.py`，实测 P95 1.23 ms；累计 329 tests |
| 2026-11-15 | **M3（第一段）**（`c3268f6`）：`spec/formal/` 的 Capability/Task TLA+ 模型与 TLC 检查；负向对照证明模型非空转；TLC 发现“撤销后仍可派生”缺口，`issue` 改为返回 `CAPABILITY_REVOKED`；累计 331 tests |
| 2026-11-15 | **M3 完成**（`17c11ad`）：新增 `Consent.tla`（预约→授权→激活→撤销）与 `Recovery.tla`（intent/outcome/unknown）；`check.sh` 扩到四个正常模型与两个负向对照；M3 退出标准全部满足 |
| 2026-11-16 | **持久化基础**（`48e744e`）：`JsonStore` 原子分节写入；幂等索引与能力签发/撤销跨重启；`Bus` 可注入 store；新增 27 条测试，累计 358；`docs/standard.md` 语义未改 |
| 2026-11-16 | **PCS 回执签名**（`092c710`）：Ed25519 覆盖去 `proof` 的规范化 JSON；离线验签；`activate` 先验签再查预约；新增 17 条测试，累计 375；演示增加 `receipt=verified` |
| 2026-11-16 | **同意流程持久化**（`61a9994`）：请求/回执/预约与 PCS 签名密钥跨重启；`put_many` 原子多节写入；新增 12 条测试，累计 387 |
| 2026-11-17 | **流控与背压**（`0b13483`）：每身份连接/在途/队列上限与令牌桶；FIFO 等待与显式 `RATE_LIMIT`；UDS 连接配额与拒绝帧；新增 32 条测试，累计 419 |
| 2026-11-17 | **并发 UDS 服务**（`eaf8260`）：`serve_forever(concurrency=N)` 线程池；空闲连接不再阻塞他人；同 Agent 跨连接共享配额；新增 3 条测试，累计 422 |
| 2026-11-17 | **任务树持久化**（`f47abd7`）：`TaskBoard(store=...)` 无损整树跨重启；每次变更一次原子写入；新增 18 条测试，累计 440 |
| 2026-11-17 | **审计账本持久化**（`ca808b9`）：`AuditLedger` 单 trace 追加链；规范哈希与重启重算；损坏 fail closed；按 trace 分区；新增 17 条测试，累计 457 |
