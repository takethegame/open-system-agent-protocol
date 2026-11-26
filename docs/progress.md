# OSAP 进展记录

> 更新时间：2026-11-19
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
| PCS 公钥登记（M4 前置） | ✅ 完成 | 按 `kid` 登记/轮换/撤销/过期；`KeyRegistry` + `pcs.keys` 持久化；`ConsentFlow` 可选注册表验签；私钥可独立 `key_store`；516 tests | 2026-11-18 |
| 私钥存储后端（M4 前置） | ✅ 完成 | `KeyStore` 契约；JSON / 内存 / OS 密钥环（macOS `security`、Linux `secret-tool`）三种后端；统一记录校验；563 tests | 2026-11-18 |
| 上下文事件持久化（M4 前置） | ✅ 完成 | `ContextFabric(store=...)` 把 `context.resolve` 写入 `context.events`；重开逐条校验；`limit` 保留最新 N 条；582 tests | 2026-11-18 |
| 审计保留与归档（M4 前置） | ✅ 完成 | `AuditLedger(max_events=...)` 把最旧事件移入 `audit.archive.<trace_id>`；live 与归档原子双写；锚点校验与 `history()`；602 tests | 2026-11-18 |
| 任务与副作用恢复（M4 前置） | ✅ 完成 | `TaskBoard.effects` 持久化 intent/outcome；`recover()` 原子失败/重调度非终态任务并把 intent-only effect 标为 unknown；重放闸门与对账；639 tests | 2026-11-19 |
| 上下文对象持久化（M4 前置） | ✅ 完成 | `ContextFabric` 增加 `context.handles` / `context.blackboards` / `context.objects`；句柄按标识解析、黑板关闭清空、对象引用计数与墓碑跨重启；685 tests | 2026-11-19 |
| 审计按用户分区与跨 trace 顺序（M4 前置） | ✅ 完成 | `AuditJournal` 写 `audit.user.<user>.*` 与 `audit.order.<user>`；链、归档与连续序号一次 `put_many`；重开拒绝缺口/重复/时间戳不符/孤儿条目；706 tests | 2026-11-19 |
| Windows 密钥环与迁移工具（M4 前置） | ✅ 完成 | `KeyringKeyStore` 增加 Windows `PasswordVault`（PowerShell，密钥走 stdin）；后端失败细分 `KeyringError.reason`；`migrate_key_store` + `tools/migrate_pcs_key.py` 验证后迁移并在确认目标后删源；720 tests | 2026-11-19 |
| 并发服务事件循环（M4 前置） | ✅ 完成 | `serve_forever(mode="selector")` 单线程多路复用监听与全部会话；断开/出错 peer 摘除不影响循环；配额共享 `AdmissionController`；726 tests | 2026-11-19 |
| 跨进程撤销分发（M4 前置） | ✅ 完成 | `revoke` 写 `capability.revocations` 日志并与撤销集原子落盘；副本 `apply_revocations(entries, source=...)` 按来源游标幂等应用、缺口报 `REVOCATION_GAP`、写失败回滚；743 tests | 2026-11-19 |
| 恢复事务与 effect 归档（M4 前置） | ✅ 完成 | `TaskBoard(ledger=...)` 共享 store，`recover()` 把任务树、effect 日志与审计链一次 `put_many`；`AuditLedger.append_many` 批量同事务；`max_effects` 归档已决 effect 且 pending/unknown 永不归档；760 tests | 2026-11-19 |
| 审计归档压缩与按用户导出（M4 前置） | ✅ 完成 | `AuditLedger(max_archive=...)` 压缩归档并记录 `base` 锚点，kept 前缀仍可端到端验证；`AuditJournal.export()` 输出整用户分区快照；774 tests | 2026-11-19 |
| 撤销订阅与跨进程测量（M4 前置） | ✅ 完成 | `RevocationWatcher` 轮询源 store 自动应用撤销批次；`benchmark_revocation.py --cross-process` 量化 revoke → 副本 `is_revoked()` 端到端传播；778 tests | 2026-11-19 |
| asyncio 绑定（M4 前置） | ✅ 完成 | `serve_forever(mode="asyncio")` 缓冲分帧协议，半帧停滞 peer 不再阻塞他人；`close()` 经 `call_soon_threadsafe` 通知 loop（kqueue fd 跨线程关闭会挂死）；782 tests | 2026-11-19 |
| 撤销推送通道（M4 前置） | ✅ 完成 | `RevocationFeedServer/Client` 专用 AF_UNIX sidecar socket 推送撤销批次（catch-up + 增量，非 Bus 流量）；`--cross-process --tree` 支持整树 cascade 跨进程测量；790 tests | 2026-11-19 |
| M4 标准打包 | ✅ 完成(已提交) | 2 个 IETF individual draft + Linux binding + 14 ADR + `check_drafts.py`;**已提交 Datatracker(2026-11-21)**,URL 见 §17 | 2026-11-21 |
| M5 生态与采用 | 🟢 进行中 | 一致性登记表已建立(`conformance/registry.md` + `reports/`),参考实现自证登记;剩余:外部实现互操作、安全评审、发布 | 2026-11-20 |

仓库规模：

| 项目 | 数量 |
|---|---|
| 规范正文 | 131 节 |
| JSON Schema | 12（协议）+ 3（一致性：case / suite / report）= 15 |
| 示例 | 17 |
| 一致性用例 | 68 / 68 |
| 校验与基准工具 | 6 |
| Markdown 文件 | 42 |
| 参考实现 | 23 个模块 + 适配器（9233 行）+ 801 个单元测试 |
| 形式化模型 | 4 个 TLA+ 模块 + 6 个配置 + `check.sh`（479 行） |
| 端到端演示 | `demo/run_demo.py`（672 行，含崩溃恢复第 7 节）+ 演示说明 |
| 中英平行文档 | 9 对 |
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
| `73cd639` | 2026-11-18 | **PCS 公钥登记**：`KeyRegistry` 按 `kid` 登记/轮换/撤销/过期；`pcs.keys` 持久化与损坏拒绝；验签失败原因细分；39 条新测试，累计 496 |
| `c035be5` | 2026-11-18 | **同意流程接入注册表**：`ConsentFlow(registry=...)` 按 `proof.kid` 验签；`publish_pcs_key()` 幂等登记；跨 signer 激活；13 条新测试，累计 509 |
| `5419b00` | 2026-11-18 | **私钥与回执分库**：`key_store=` 把 `consent.pcs_key` 移出回执 store；`ConsentFlow.verifier()` 用临时 signer 验证；7 条新测试，累计 516 |
| `b0068ab` | 2026-11-18 | **私钥存储后端**：`keystore.py` 的 `KeyStore` 契约；JSON / 内存 / OS 密钥环后端；`as_key_store` 兼容裸 `JsonStore`；47 条新测试，累计 563 |
| `7274a27` | 2026-11-18 | **上下文事件持久化**：`ContextFabric(store=...)` 写 `context.events`；重开逐条校验；`limit` 保留最新 N 条；19 条新测试，累计 582 |
| `1a8394d` | 2026-11-18 | **审计保留与归档**：`AuditLedger(max_events=...)` 移入 `audit.archive.<trace_id>`；live 首条锚定归档尾；`history()` 导出完整链；20 条新测试，累计 602 |
| `c7e990c` | 2026-11-19 | **任务与副作用恢复**：`TaskBoard` 持久化 `task.effects`；`recover()` 失败非终态任务并标记 intent-only effect 为 unknown；重放闸门与对账；37 条新测试，累计 639 |
| `126956e` | 2026-11-21 | **进度上报接线**：`TaskBoard.report_progress` 合账 consumed（单调、仅 assignee、终态拒绝）+ `Bus(progress_board=...)` 路由单向 status（无回复帧）；demo 第 4 节演示；11 条新测试，累计 801 |
| `f98a6b3` | 2026-11-19 | **M4 本地打包**：两个 xml2rfc v3 individual draft、来源映射、`check_drafts.py`、Linux binding、14 条 ADR；CI 新增 `drafts` job |
| `fca8fe4` | 2026-11-19 | M4 输出接入 README / roadmap / progress，记录 CI run 44462099197 |
| `3d251a6` | 2026-11-19 | **上下文对象持久化**：`context.handles` / `context.blackboards` / `context.objects` 分节落盘；句柄按标识解析、黑板关闭清空、对象引用计数与墓碑跨重启；46 条新测试，累计 685 |
| `a2c6853` | 2026-11-19 | **审计按用户分区与跨 trace 顺序**：`AuditJournal` 写入 `audit.user.<user>.*` 与 `audit.order.<user>`；链、归档与序号一次 `put_many`；重开交叉校验；21 条新测试，累计 706 |
| `adba047` | 2026-11-19 | **Windows 密钥环与迁移工具**：`PasswordVault` 后端（密钥走 stdin）；`KeyringError` 细分 `backend_missing`/`lookup_failed`/`store_failed`；`migrate_key_store` 与 `tools/migrate_pcs_key.py`；14 条新测试，累计 720 |
| `6656195` | 2026-11-19 | **并发服务事件循环**：`serve_forever(mode="selector")` 单线程多路复用；断开/出错 peer 摘除；配额仍走共享控制器；6 条新测试，累计 726 |
| `893b357` | 2026-11-19 | **跨进程撤销分发**：`capability.revocations` 日志 + `apply_revocations(entries, source=...)` 来源游标；`REVOCATION_GAP` 领域扩展码；17 条新测试，累计 743 |
| `2609ef1` | 2026-11-19 | **恢复事务与 effect 归档**：`TaskBoard(ledger=...)` + `AuditLedger.append_many` 一次落盘树/日志/审计链；`max_effects` 归档已决 effect；写失败全量回滚；17 条新测试，累计 760 |
| `da17a2b` | 2026-11-19 | **审计归档压缩与按用户导出**：`max_archive` 锚点压缩；`AuditJournal.export()` 快照；10 条新测试，累计 770 |
| `1b477f6` | 2026-11-19 | **撤销订阅与跨进程测量**：`RevocationWatcher` 轮询订阅；`--cross-process` 基准；8 条新测试，累计 778 |
| `c32fc97` | 2026-11-19 | **asyncio 绑定**：缓冲分帧协议，半帧停滞不阻塞他人；跨线程 fd 关闭挂死的修复；8 条新测试，累计 782 |
| `c2b3f39` | 2026-11-19 | **撤销推送通道**：`RevocationFeedServer/Client` AF_UNIX sidecar（catch-up + 增量）；`--cross-process --tree` 整树 cascade 测量；8 条新测试，累计 790 |
| `d04c907` | 2026-11-20 | **demo 崩溃恢复**：第 7 节持久化运行时（任务树/审计链/幂等索引/黑板共库）；重放闸门拒绝 → 对账 → 显式重试；幂等重放；链条改由 `AuditLedger` 生成（单一编码） |
| `fcf0485` | 2026-11-20 | **README 限制清单**：根 README（中英）更新当前状态并列出六条采用决策相关的限制 |

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
| automated | 64 | 其中 8 条为 `observe`；C4-08/C4-09 已转为自动断言 |
| manual | 4 | C2-05、C4-01、C6-08、C7-01 |
| `observe` | 12 | 8 条 automated + 4 条 manual |

手动用例集中在三类：TTL 与原生注册表生命周期（C2-05、C6-08）、任务取消传播（C4-01）与跨 App 全链路（C7-01）。`observe` 用例不产生自动判定，报告只记录实现的实际行为。

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
7. 任务树在 M2 时只在内存；M4 前置已把整棵树接入 `JsonStore`，并在第 16 节补上 `task.effects` 与重启恢复。`audit.recover_effects` 仍只读已有事件，恢复事件需要调用方写入 `AuditLedger`。
8. 上下文审计与黑板状态只在内存，没有真正撤销句柄；§9.7 的“谁在何时解析了哪个句柄”只能读进程内列表。
9. 没有真实对象存储：`delete_object` 只返回判定，不触碰文件系统；`storage_declaration` 只核对声明，不实现配额、GC 或加密。
10. 联邦只做投影：没有监听原生注册表变化，也没有按 TTL 自动刷新，C6-08 仍是 manual；MCP/A2A/OpenAPI 的签名未验证。
11. `verify_chain` 对夹具链仍只验证 schema、trace、`audit_id` 与 `prev_hash` 链接；新增的 `AuditLedger` 对自己的事件重算正文哈希，因此损坏的持久链会在重启时 fail closed。
12. 上下文只在内存；任务树、effect 日志与审计账本已持久化（见第 10、11、16 节），但跨进程回放与 C7-01 仍未实现。
13. 64 个 pass 覆盖全部 automated 用例；4 条 manual 仍依赖跨 App 集成、原生注册表 TTL 与跨进程撤销。
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
2. PCS 公钥的登记、轮换与撤销已由第 12 节的 `KeyRegistry` 覆盖，但规范仍未定义跨 Bus 的分发消息；验证方需要通过共享 `JsonStore` 或带外获得公钥；
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
3. **过程状态只部分落盘**：`TaskBoard.effects` 与任务树已持久化，`TaskBoard.audit` 仍是内存列表；恢复事件要由调用方写入 `AuditLedger`，两个写入不在同一事务内。
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

## 12. PCS 公钥登记（M4 前置，已完成）

### 12.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/pcs.py` | `KeyRegistry`：按 `kid` 保存公钥；`register` / `rotate` / `revoke` / `state_of` / `usable` / `verify_receipt` / `require_receipt`；生命周期 `active` / `retired` / `revoked`；`pcs.keys` 分节持久化 |
| `impl/osap/consent_flow.py` | `ConsentFlow(registry=...)` 可选注册表验签；`publish_pcs_key()` 幂等登记本流程公钥；`key_store=` 把私钥移出回执 store；`ConsentFlow.verifier()` 用临时 signer 验证；`verify_receipt()` 优先查表，未配置时回退到本地 signer |
| `impl/osap/crypto.py` | `valid_public_key`：确认 base64url 能解出 32 字节 Ed25519 公钥 |
| `impl/tests/test_pcs.py` | 39 条新测试：登记、重复/畸形键、有效期窗口、轮换与宽限、撤销幂等、验签失败原因、返回副本、重开与损坏分节 |
| `impl/tests/test_consent_flow.py` | 20 条新测试：发布与幂等、不同键/已撤销键拒绝、跨 signer 激活、无注册表回退、撤销与宽限、篡改拒绝、重开、私钥分库与验证方构造 |

### 12.2 语义

- **只存公钥**：注册表按 `kid` 保存 `public_key`、生命周期状态与时间戳；私钥仍只由 `ConsentSigner` / `consent.pcs_key` 持有，注册表不接触私钥。
- **状态与可用性分开**：`state_of` 返回存储的 `active` / `retired` / `revoked`；`usable(kid, at=...)` 额外检查 `not_before`、`not_after` 与退役宽限 `grace_until`。撤销是终态，未知键永远不可用。
- **登记不覆盖**：`register` 拒绝空 `kid`、重复 `kid`、非法 Ed25519 公钥与倒置窗口；要换键必须走 `rotate`，避免同一 `kid` 被静默改绑。
- **轮换带宽限**：`rotate(kid, new_public_key, new_kid=..., grace_seconds=...)` 把旧键标为 `retired` 并记录 `retired_at` / `grace_until`，新键从 `active` 开始。宽限期内旧回执仍能验签，宽限期后旧键 `usable` 为假；已撤销或已退役的键不能再轮换。
- **撤销幂等**：`revoke` 首次返回 `True`，重复调用返回 `False` 且不重复写入；撤销未知 `kid` 抛 `ValueError`。
- **按 `kid` 验签**：`verify_receipt` 从 `proof.kid` 查表，先检查可用性再验 Ed25519，缺失或畸形的 proof 一律返回 `False`。`require_receipt` 在失败时返回 `AUTH_DENIED`，`details.reason` 区分 `receipt_key_unknown`、`receipt_key_revoked`、`receipt_key_not_yet_valid`、`receipt_key_expired` 与 `receipt_signature_invalid`。
- **重启一致**：接入 `JsonStore` 时每次变更原子重写 `pcs.keys`；重开逐条校验 `kid` 一致、公钥可解析为 32 字节、状态合法、时间戳可解析、窗口不倒置，任何损坏抛 `ValueError`，不会得到半个注册表。
- **同意流程按需接入**：`ConsentFlow(registry=...)` 后，`activate` 与 `verify_receipt` 会按 `proof.kid` 查表，先检查撤销、过期与退役宽限再验签；未配置注册表时仍只用本地 signer 的公钥，单进程行为不变。
- **登记是显式动作**：`publish_pcs_key()` 幂等登记本流程公钥；注册表不自动登记，避免验证方进程把自己生成的无关密钥写进共享注册表。同 `kid` 不同公钥或已撤销键会被拒绝。
- **跨 signer 验证**：验证方可以用自己的 `ConsentSigner` 启动，只要注册表里有签发方的 `kid` 与公钥，`activate` 就能通过；因此验证方不需要持有 PCS 私钥。
- **私钥与回执分库**：`key_store=` 把生成的 `consent.pcs_key` 写入独立 store，回执 store 只保留请求、回执与预约；验证方只打开回执 store 时看不到私钥。不传 `key_store` 时仍沿用原来的单 store 布局。
- **验证方工厂**：`ConsentFlow.verifier()` 要求一个注册表，并注入与签发方无关的临时 signer，因此构造验证方不会向回执 store 写任何密钥。

### 12.3 验证证据

2026-11-18，提交 `5419b00`（登记层 `73cd639`，注册表验签 `c035be5`）：

```
python3 -m unittest discover -s impl/tests -t impl
→ Ran 516 tests ... OK

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

新增的 39 条注册表测试覆盖：登记后的初始状态与公开字段；未知键；重复 `kid`、空/畸形/非字符串公钥、倒置窗口与非 `datetime` 窗口；`not_before` 延迟可用与 `not_after` 结束可用；撤销的终态与幂等；带/不带宽限的轮换；轮换的未知键、同 `kid`、已存在 `kid`、非法公钥与负宽限拒绝；已撤销/已退役键不能再次轮换；返回记录与内部状态隔离；按 `kid` 排序；按 `kid` 验签成功、正文篡改、未知 `kid`、畸形 proof、已撤销、已过期与尚未生效；宽限期内旧键仍可验签；重开后键、轮换、撤销与窗口一致；单节写入不影响其他 section；空注册表不写盘；非对象分节、非对象记录、`kid` 不一致、非法公钥、未知状态、缺失/畸形时间戳与倒置存储窗口的拒绝。

新增的 20 条同意流程测试覆盖：`publish_pcs_key` 登记与幂等、无注册表时拒绝发布、同 `kid` 不同公钥与已撤销键拒绝、发布后仍由本流程私钥签名；另一 signer 通过共享注册表激活、无注册表时因签名不匹配拒绝、注册表撤销键阻断激活、退役键仅在宽限内通过、篡改回执拒绝、未配置注册表时回退到本地 signer、注册表重开后仍能解析 `kid`；`key_store` 只写私钥且重开后复用、回执 store 不含 `consent.pcs_key`、验证方构造不写密钥、缺注册表时拒绝构造、注入 signer、以及只开回执 store 时无法解析未发布 `kid`。

### 12.4 已知边界

1. **不是协议消息**：规范 §4.5 只要求“通过 hello 或注册表分发”，没有定义 `pcs.key.register` 之类的信封；注册表是参考实现的本地 API，跨 Bus 分发仍靠共享 `JsonStore` 或带外。
2. **注册表与密钥存储都是可选的**：不传 `registry` 时 `activate` 仍信任本地 signer；不传 `key_store` 时私钥仍落在回执 store。使用 `key_store` + `verifier()` 可以隔离私钥，但两者都是调用方约定，不是强制布局。
3. **无撤销传播**：撤销只改本地 `pcs.keys`，不会通知已经持有旧公钥的验证方；跨进程/跨设备失效仍是 0.2 的撤销分发问题。
4. **整节重写**：每次登记/轮换/撤销都序列化全部键；没有增量写、归档或 TTL。
5. **单写者**：同一 `JsonStore` 仍要求一个进程写入；并发注册表需要外部协调。
6. **宽限依赖本地时钟**：`grace_until` 用调用方时钟比较，没有时钟偏差容忍或单调时钟保护。
7. **发布是显式动作**：`publish_pcs_key()` 不会自动调用；漏登记时 `activate` 以 `receipt_key_unknown` 拒绝，调用方需要把发布纳入启动流程。

---

## 13. 私钥存储后端（M4 前置，已完成）

### 13.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/keystore.py` | `KeyStore` 契约（`load` / `save` / 可选 `delete`）；`JsonKeyStore`、`MemoryKeyStore`、`KeyringKeyStore`；`record_of` / `signer_of` 统一记录校验；`as_key_store` 兼容裸 `JsonStore` |
| `impl/osap/consent_flow.py` | `key_store=` 接受任意 `KeyStore` 或 `JsonStore`；重开从 `load()` 恢复，缺失时生成并 `save()` |
| `impl/osap/__init__.py` | 导出 `KeyStore`、`JsonKeyStore`、`MemoryKeyStore`、`KeyringKeyStore` 与 `keystore` 子模块 |
| `impl/tests/test_keystore.py` | 47 条新测试：记录校验、三个后端、类型适配、平台选择、密钥环命令构造与错误路径、流程级密钥复用 |

### 13.2 语义

- **单一契约**：`load()` 返回记录或 `None`，`save()` 写入一条记录；后端不参与回执、预约或审计逻辑，`ConsentFlow` 只调用这两个方法。
- **统一校验**：`signer_of` 检查对象形状、非空 `kid`、可由 `private_key` 构造 Ed25519，以及 `public_key` 与私钥推导值一致；所有后端对同类损坏输入给出一致的 `ValueError`。
- **JSON 后端保持旧布局**：传入裸 `JsonStore` 时由 `as_key_store` 包成 `JsonKeyStore`，仍写 `consent.pcs_key` 分节，0600 权限与原子写入不变。
- **内存后端不落盘**：`MemoryKeyStore` 只在进程内保存深拷贝，重启即丢失；用于不需要签发的验证方与测试。
- **密钥环后端可注入**：`KeyringKeyStore(platform=..., runner=...)` 按平台选择 `security`（macOS）或 `secret-tool`（Linux）；测试注入假 runner，不触碰真实密钥环。缺少 CLI 时构造即 `RuntimeError`，不会静默退回文件。
- **不新增路径约定**：密钥只经后端读写；`service` / `account` 只是密钥环内的索引，没有引入新的环境变量或默认路径。

### 13.3 验证证据

2026-11-18，提交 `b0068ab`（分库 `5419b00`）：

```
python3 -m unittest discover -s impl/tests -t impl
→ Ran 563 tests ... OK

python3 tools/check_schemas.py
→ OK: 45 checks passed across 15 schemas
python3 tools/validate_examples.py
→ OK: 24 checks passed
python3 tools/check_docs.py
→ OK: 116 checks passed across 23 Markdown files
python3 tools/conformance_run.py --impl impl/adapter.py
→ 68 cases: 62 pass, 0 fail, 6 skip
python3 demo/run_demo.py
→ registered=3 discovery=1 consent=1 receipt=verified delegated=2 context=1 audit=verified
```

新增的 47 条测试覆盖：`record_of` 字段集合与往返；缺失字段、非字符串字段、空 `kid`、非法私钥、错配公钥的拒绝；`JsonKeyStore` 读写、缺失分节、删除与重复删除、非对象拒绝；`MemoryKeyStore` 深拷贝隔离、构造播种、删除与非对象拒绝；`as_key_store` 的 `None` / 透传 / 包装 / 拒绝；平台到后端映射与不支持平台；密钥环缺失条目、空条目、失败、非法 JSON、非对象条目的处理；macOS 命令行传密与 Linux stdin 传密的差异；保存失败与删除幂等；以及 `ConsentFlow` 复用密钥环 signer、损坏条目拒绝构造、内存 / 显式 JSON / 裸 `JsonStore` 三种 `key_store` 下回执 store 不含私钥、注入 signer 时不写后端。

### 13.4 已知边界

1. **默认仍是明文 JSON**：不传 `key_store` 或传 `JsonStore` 时，私钥与回执同处一个 0600 文件，文件权限是唯一保护。
2. **macOS 参数泄露**：`security add-generic-password` 没有 stdin 形式，密钥会作为命令行参数出现；生产应改用原生密钥环绑定。
3. **平台覆盖不全**：没有 Windows Credential Manager 后端，其他平台构造即失败并提示缺少后端。
4. **无迁移工具**：从既有 `consent.pcs_key` 迁到密钥环需要调用方先 `load()` 再 `save()`，没有一次性命令或迁移报告。
5. **单条记录**：一个后端只存一个 signer，没有多 PCS 账号、多用户或按 App 的隔离；切换密钥环条目就等于换 PCS。
6. **密钥环错误不分类**：后端失败统一抛 `RuntimeError`，调用方无法区分“未解锁”“被拒绝”与“CLI 版本不支持”。

---

## 14. 上下文解析事件持久化（M4 前置，已完成）

### 14.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/context.py` | `ContextFabric(store=..., section=..., limit=...)`；每次 `resolve` 原子重写 `context.events`；重开逐条校验；`limit` 保留最新 N 条；无标识句柄在写入前拒绝 |
| `impl/tests/test_context.py` | 19 条新测试：事件往返、允许/拒绝顺序、损坏分节与事件、保留上限、自定义分节、纯内存默认 |

### 14.2 语义

- **只记决策**：事件仍是 §9.2 的 `context.resolve`，包含 `handle`、`agent`、`label`、`decision` 与 `reason`；句柄本体由调用方传入，fabric 不持有句柄注册表。
- **每次解析一次写入**：`allow` 与 `deny` 走同一条 `_event` 路径，追加后一次性重写整个分节；写入失败会抛错，不会出现“内存成功、磁盘失败”的静默分叉。
- **重开校验**：分节必须是数组；每条事件必须是对象、`action` 为 `context.resolve`、`decision` 为 `allow`/`deny`、`handle` 与 `reason` 为非空字符串、`agent`/`label` 为字符串或 `null`；未知字段被丢弃，任何损坏抛 `ValueError`。
- **保留上限**：`limit` 在追加与重开时都保留最新 N 条；`limit=0` 写出空数组，负数、布尔与非整数在构造时拒绝。
- **写入前拒绝畸形句柄**：没有 `handle` 标识的解析请求在写盘前抛 `ValueError`，避免产生无法通过重开校验的事件。
- **默认不变**：不传 `store` 时完全保持原来的内存行为，适配器与演示无需改动。

### 14.3 验证证据

2026-11-18，提交 `7274a27`（私钥后端 `b0068ab`）：

```
python3 -m unittest discover -s impl/tests -t impl
→ Ran 582 tests ... OK

python3 tools/check_schemas.py
→ OK: 45 checks passed across 15 schemas
python3 tools/validate_examples.py
→ OK: 24 checks passed
python3 tools/check_docs.py
→ OK: 116 checks passed across 23 Markdown files
python3 tools/conformance_run.py --impl impl/adapter.py
→ 68 cases: 62 pass, 0 fail, 6 skip
python3 demo/run_demo.py
→ registered=3 discovery=1 consent=1 receipt=verified delegated=2 context=1 audit=verified
```

新增的 19 条测试覆盖：一次解析写一条事件、允许与拒绝事件按顺序恢复且与内存列表一致、空 store 无事件、非数组分节、非对象事件、未知 `action`、未知 `decision`、缺失或空 `handle`、缺失 `reason`、非字符串 `agent`/`label`、`null` 的 `agent`/`label`、未知字段被丢弃、`limit` 追加时保留最新、`limit=0`、重开时按 `limit` 截断、非法 `limit`、自定义分节、写入前拒绝无标识句柄，以及不传 store 时仍为纯内存。

### 14.4 已知边界

1. **只持久化事件**：句柄、黑板、对象元数据与缓存窗口不落盘，仍由调用方或上层存储负责。
2. **整节重写**：每次解析都序列化全部保留事件，长日志会线性变慢；`limit` 只是截断，不是归档。
3. **单写者**：同一 `JsonStore` 仍要求一个进程写入；多进程解析需要外部协调或按用户分区。
4. **没有时间戳**：事件保持 §9.2 的字段集，没有 `ts`；跨重启只能依赖顺序，不能按时间检索。
5. **没有按用户分区**：需要隔离时由调用方传不同的 `section`，例如 `ctx.user.<id>`。
6. **拒绝事件也写盘**：失败的解析同样持久化，因此反复重试的调用方会持续增长日志，直到 `limit` 生效。

---

## 15. 审计保留与归档（M4 前置，已完成）

### 15.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/audit.py` | `AuditLedger(max_events=..., archive_section=...)`；超限时把最旧事件移入 `audit.archive.<trace_id>`，live 与归档一次 `put_many` 原子写入；`verify()` 校验锚点并重验归档；`history()` / `archived_events` / `archive_section` |
| `impl/tests/test_audit.py` | 20 条新测试：裁剪、跨段链接、带/不带上限重开、内存裁剪、重复 `audit_id`、篡改与畸形归档、自定义分节、非法上限 |

### 15.2 语义

- **只裁剪不丢链**：每次 `append` 后若超过 `max_events`，把最旧的 `len - max_events` 条移入归档；live 首条事件的 `prev_hash` 仍指向上一条归档事件的 `hash`，因此从 `GENESIS_HASH` 到最新一条仍是一条可验证的链。
- **原子双写**：发生裁剪时用 `put_many` 同时写 live 与 archive，避免“live 已截断、archive 未写入”的崩溃窗口；不裁剪时仍只写 live 一节。
- **锚点校验**：`verify()` 检查 live 首条 `prev_hash` 是否等于归档尾 `hash`（无归档时为 `GENESIS_HASH`），并重新校验归档的 schema、链接、正文哈希与“归档必须从 genesis 开始”。
- **跨段唯一**：`append` 同时检查 live 与归档中的 `audit_id`，归档过的 id 不能再次写入。
- **导出**：`history()` 返回归档 + live 的时间顺序单链，可直接交给 `redact_chain`；`archived_events` 返回分离副本。
- **重开 fail closed**：先校验归档再校验 live；非对象、异 trace、非 genesis、篡改正文、`chain_id` 不一致、只有归档没有 live、被重新生根的 live 都会拒绝，不会返回缩短的历史。
- **上限语义**：`max_events` 必须是正整数；`max_events=1` 时 live 只留最新一条；不传时行为与之前完全一致。重开时是否继续裁剪由新实例的 `max_events` 决定，已有归档不会被丢弃。

### 15.3 验证证据

2026-11-18，提交 `1a8394d`（上下文事件 `7274a27`）：

```
python3 -m unittest discover -s impl/tests -t impl
→ Ran 602 tests ... OK

python3 tools/check_schemas.py
→ OK: 45 checks passed across 15 schemas
python3 tools/validate_examples.py
→ OK: 24 checks passed
python3 tools/check_docs.py
→ OK: 116 checks passed across 23 Markdown files
python3 tools/conformance_run.py --impl impl/adapter.py
→ 68 cases: 62 pass, 0 fail, 6 skip
python3 demo/run_demo.py
→ registered=3 discovery=1 consent=1 receipt=verified delegated=2 context=1 audit=verified
```

新增的 20 条测试覆盖：超限后最旧事件进入归档且顺序不变、恰好在上限时不写归档、live 首条锚定归档尾、`history()` 时间顺序与分离副本、带/不带 `max_events` 的重开、`max_events=1` 只留最新、纯内存账本裁剪、返回事件分离、已归档 `audit_id` 重复拒绝、归档正文篡改、归档未从 genesis 开始、归档被删除后的 live 重生根、只有归档没有 live、非对象归档、异 trace 归档、非数组 `events`、`chain_id` 不一致、自定义归档分节与非法上限。

### 15.4 已知边界

1. **归档只增不减**：`max_events` 限制的是 live 链，归档仍会无限增长，没有二级分层、压缩或删除策略。
2. **整节重写**：每次追加仍重写 live 整节；裁剪时额外重写整个归档，长归档会线性变慢。
3. **校验成本随归档增长**：`verify()` 每次都会重验归档，适合恢复或导出前使用，不适合每条事件都调用。
4. **没有按用户分区**：分区仍靠 `trace_id` 或自定义 `section`；§3.7 的多实例 leader election 未实现。
5. **不自动采集**：`Bus`、`TaskBoard` 与 `ContextFabric` 仍不会自动向账本追加事件。

---

## 16. 任务与副作用恢复（M4 前置，已完成）

### 16.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/task.py` | `TaskBoard.effects` 与 `task.effects` 分节；`record_effect_intent` / `record_effect_outcome` / `reconcile_effect` / `require_replay_allowed`；`recover(policy="fail"\|"reschedule")` 一次原子写入任务树与 effect 日志并返回审计事件 |
| `impl/adapter.py` | C4-08 `restart` 与 C4-09 `replay`：持久化 board → 丢弃内存实例 → 重开恢复 → 重开审计链验证 |
| `conformance/cases/C4-collaboration.json` | C4-08/C4-09 从 manual 改为 automated，断言任务失败、effect unknown、重放被拒与审计可验证 |
| `impl/tests/test_task.py` | 37 条新测试：恢复策略、detached/嵌套任务、幂等恢复、原子写、effect 持久化、损坏拒绝、重放闸门、对账与审计事件形状 |

### 16.2 语义

- **先 intent，后副作用**：`record_effect_intent` 在副作用前写 `task.effects`，状态 `pending`；`record_effect_outcome` 写 `executed`；同一 intent 的重复 outcome 幂等。
- **恢复不静默 running**：`recover()` 把非终态任务改为 `failed`，或 `policy="reschedule"` 时改回 `created`。这是重启策略覆盖，不是 §8.10 的普通转换：普通 `transition("created"→"failed")` 仍被拒绝。
- **只有 intent 就是 unknown**：所有 `pending` effect 在恢复时改为 `unknown`，报告 `effect_state=unknown`、`pending_intents` 与 `requires_reconciliation`；第二次恢复仍报告这些 unknown，但不会重复写审计。任务状态没有 `unknown` 枚举，所以任务按 §3.7 转为 `failed`，`unknown` 只描述副作用结果。
- **原子快照**：任务树与 effect 日志通过一次 `put_many` 写入；没有变化时不写。
- **重放闸门**：`require_replay_allowed` 对 `pending`/`unknown` 抛 `POLICY_DENIED` 且 `details.reason=reconciliation_required`；对已确认 `executed` 的对账结果抛 `already_executed`；只有 `executed`（幂等路径）与 `reconciled: not_executed`（确认未执行）允许继续。
- **对账写回**：`reconcile_effect(intent_ref, outcome=...)` 只接受 `unknown`，`outcome` 只能是 `executed` 或 `not_executed`；写入 `reconciled_outcome` 并持久化，对账不是自动重放。
- **审计**：`recover()` 返回可直接追加到 `AuditLedger` 的完整事件（`task.failed`/`task.created` 与 `error` 告警）；`TaskBoard.audit` 仍是内存列表，调用方负责把事件写入持久账本。

### 16.3 验证证据

2026-11-19，提交 `c7e990c`：

```
python3 -m unittest discover -s impl/tests -t impl
→ Ran 639 tests ... OK

python3 tools/check_schemas.py
→ OK: 45 checks passed across 15 schemas
python3 tools/validate_examples.py
→ OK: 24 checks passed
python3 tools/check_docs.py
→ OK: 116 checks passed across 23 Markdown files
python3 tools/conformance_run.py --impl impl/adapter.py
→ 68 cases: 64 pass, 0 fail, 4 skip
python3 demo/run_demo.py
→ registered=3 discovery=1 consent=1 receipt=verified delegated=2 context=1 audit=verified
```

`C4-08` 与 `C4-09` 现在都是 automated；剩余 4 条 manual 是 C2-05、C4-01、C6-08、C7-01。

### 16.4 已知边界

1. **审计不在同一原子写内**：任务树与 effect 日志一次 `put_many`，但恢复事件写入 `AuditLedger` 是另一次写；崩溃仍可能留下“已恢复但未审计”的窗口。
2. **重放闸门不是强制隔离**：只有调用 `require_replay_allowed()` 的路径会被拒绝；实现仍可能绕过该 API 直接执行副作用。
3. **没有自动重调度器**：`policy="reschedule"` 只把状态改回 `created`，不会重新排队、分配 owner 或重发 `delegate`。
4. **对账不自动改任务**：`reconcile_effect()` 只写 effect 状态；任务是否转 `succeeded` 或重新执行仍由调用方决定。
5. **effect 日志只增不减**：没有 TTL、归档或按任务清理，长期运行需要 compaction。

---

## 17. M4 标准打包（本地完成）

### 17.1 交付物

| 文件/目录 | 作用 |
|---|---|
| `drafts/draft-osap-capability-tokens-00.xml` | Draft A：能力 token、衰减、绑定、撤销、同意前置；xml2rfc v3 |
| `drafts/draft-osap-consent-receipts-00.xml` | Draft B：同意请求、回执、预约顺序、审计、ISO/IEC 27560 信息性映射；xml2rfc v3 |
| `drafts/submission/checklist.md` 等 | IETF 提交前置的**准备材料包**：闸门检查单、§10.4 贡献者同意书模板、BCP 79 披露草稿模板、agentproto / OAuth 联络 信草稿；全部待人工填写,不构成本仓库的提交动作 |
| `drafts/README.md` | 两个 draft 的逐节来源映射、构建命令、发布前置条件与边界 |
| `tools/check_drafts.py` | XML 良构、v3 根元素、front matter、anchor/xref、引用、JSON 代码块、占位符与本地引用检查；`--compile` 调用 `xml2rfc` |
| `requirements-drafts.txt` | 独立的 `xml2rfc` 工具链，避免所有 CI job 都安装文档依赖 |
| `bindings/linux/profile.md` / `profile.en.md` | Linux binding：D-Bus 名称/对象路径/方法签名、对端认证、错误映射、portal 映射、`systemd --user`、3 个序列图 |
| `bindings/linux/units/` | `osap-bus.socket` 与 6 个 `Type=dbus` 用户服务示例，含 hardening 与激活选择说明 |
| `bindings/linux/dbus/` | 6 个 `[D-BUS Service]` 激活文件，和 socket activation 二选一 |
| `decisions/0001-*.md` … `0014-*.md` | `standard.md` §15 的 14 条 ADR，每条含暂定结论、后果、备选方案与重审触发条件 |
| `decisions/README.md` | ADR 索引、状态约定与“ADR 不覆盖规范”的边界 |
| `GOVERNANCE.md` §9.1 / `.en.md` | 记录真实联络状态：均未正式联络；individual draft ≠ IETF 采用 |
| `.github/workflows/ci.yml` | 新增 `drafts` job：安装 `requirements-drafts.txt` 并执行 `check_drafts.py --compile` |

### 17.2 语义与边界

- **两个 draft 是 individual submission 骨架**，不是 WG 采用稿，也没有提交到 Datatracker。文档内不引用 `standard.md`、仓库路径或未发布文档；外部读者只看单个 draft 即可理解其范围。
- **Draft A** 只写 token 格式、衰减、绑定、撤销与同意前置，不写总线、发现、任务状态机或传输。它与 §5 的 10 条衰减规则、AI1–AI10、§5.7 风险等级与 §5.8 回执覆盖一一对应。
- **Draft B** 只写同意请求、回执、`cap_id` 预约顺序、审计与 27560 映射，不写 UI 或传输。27560 映射是**信息性**的，不声称 ISO 一致性；回执校验顺序写成实现建议，不新增协议 MUST。
- **Linux binding** 不改变协议语义：D-Bus 是传输与服务生命周期绑定，portal 结果是受 TTL/标签约束的句柄，不是环境权限；所有 OSAP 能力、同意、撤销与审计规则仍然适用。
- **14 条 ADR** 都是 `Provisional`；它们解释取舍并给出重审触发条件，不覆盖 `standard.md`。任何语义变更仍须走 `GOVERNANCE.md` §3。
- **不新增一致性编号**：draft 与 Linux profile 都不新增 C 用例；`docs/conformance.md` 仍是唯一来源。Linux profile 第 8 节给出的是实现检查清单。

### 17.3 验证证据

2026-11-19，本地与 CI：

```
python3 tools/check_drafts.py
→ OK: 36 checks passed across 2 drafts

python3 tools/check_drafts.py --compile
→ OK: 36 checks passed across 2 drafts and compiled
→ build/drafts/draft-osap-capability-tokens-00.{txt,html}
→ build/drafts/draft-osap-consent-receipts-00.{txt,html}

python3 tools/check_docs.py
→ OK: 195 checks passed across 42 Markdown files
```

完整的 schema / examples / 一致性 / 单元测试 / 演示结果见 §32 的对应提交记录。CI 的 `drafts` job 会在 Python 3.12 上安装 `xml2rfc` 并重新编译两个 draft；`validate` job 仍覆盖 Python 3.11/3.12 的 schema、文档、一致性与参考实现。

打包提交 `f98a6b3` 已推送，CI run [44461943418](https://github.com/takethegame/open-system-agent-protocol/actions/runs/44461943418) 的三个 job 全部通过：

```
validate (3.11)  success
validate (3.12)  success
drafts           success   # xml2rfc 安装 + check_drafts.py --compile
```

这证明的是“文档可编译、仓库检查通过”，不是 IETF 采用或外部评审通过。

### 17.4 已知边界

1. ~~**未提交 IETF**~~ **已提交（2026-11-21）**：文档名按第一作者姓氏改为 `draft-zeng-osap-*`（[capability tokens](https://datatracker.ietf.org/doc/draft-zeng-osap-capability-tokens-00/)、[consent receipts](https://datatracker.ietf.org/doc/draft-zeng-osap-consent-receipts-00/)）；§10.4 贡献者同意（`submission/consent-record.md`）与 BCP 79 IPR 自查（`submission/ipr-landscape.md`）已完成；WG 采用意向仍待两封署名联络 信发出。
2. **`ipr="trust200902"` 只是模板值**：实际的 IPR 义务经 `submission/ipr-landscape.md` 的三问自查结论为"无披露义务"；该属性不影响披露语义。
3. **没有外部评审**：两个 draft 未经 WG 或独立安全评审；Linux binding 也未在真实 GNOME/KDE/Flatpak 环境中跑过端到端测试。
4. **D-Bus 集成测试不在 CI**：本环境是 macOS；`units/` 与 `dbus/` 是示例，CI 只做静态/编译检查。Linux 集成测试应在 `dbus-run-session` 下单独运行。
5. **27560 映射未做符合性测试**：它只是概念映射，不是 ISO 认证，也没有覆盖 notice/controller/jurisdiction 等完整记录字段。
6. **ADR 是暂定的**：第 3、6、11、14 条尤其依赖 0.2 或平台进展；在外部实现出现前不应视为冻结。
7. **来源映射是人工维护的**：`drafts/README.md` 的逐节表格不会被 CI 自动比对；`check_drafts.py` 只保证 draft 自包含、引用可解析与可编译。
8. **-00 版本 2027-05-25 过期**：需要延续时发 `-01`（上传前更新 `<date>`）；未被引用或讨论也会自然过期，这属于 IETF 流程常态而非撤稿。

---

## 18. 上下文句柄、黑板与对象持久化（M4 前置，已完成）

### 18.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/context.py` | `ContextFabric` 新增 `context.handles` / `context.blackboards` / `context.objects`；`resolve` 接受句柄对象或已登记标识；句柄登记/删除、黑板打开/写入/关闭、对象登记/引用/释放/删除；每个变更一次原子分节写入；重开逐字段校验 |
| `impl/tests/test_context.py` | 46 条新测试：句柄往返/幂等/冲突/过期/未知标识、黑板往返/关闭清空/幂等/损坏、对象引用计数/墓碑/硬删拒绝/损坏、纯内存默认 |

### 18.2 语义

- **句柄注册表**：`register_handle` 校验 `handle`、`scheme`/`scope`/`audience`、时间戳、`label`、`ttl`、`derived_from` 与 `constraints`；同体重复登记幂等，异体登记拒绝，避免静默改变可解析范围。`resolve` 传字符串时先查注册表，未知标识写一条 `deny/not_found` 审计并抛 `CONTEXT_NOT_FOUND`；传字典保持原有行为。登记后的句柄仍经过 audience、`allowed_agents`、OS 权限、必需授权、过期与出口检查。
- **任务黑板**：`open_blackboard(task_id, board=...)` 保留夹具中的 `version`、`ttl`、`created_at`、`updated_at`、`expires_at`；`write_blackboard` 只改条目；`close_blackboard` 清空条目、记录 `entries_archived` 并固定 `promoted_to_memory=false`，重复关闭幂等。已关闭黑板不能再打开或写入；重开时“已关闭但仍有条目”或“已关闭却晋升记忆”都直接拒绝。
- **对象元数据**：`register_object` 记录 `uri`、可选 `label`/`metadata` 与引用计数；`retain_object`/`release_object` 维护计数且不会自动删除；`delete_object` 在计数为零时硬删除，否则墓碑化；`hard_delete=True` 遇到仍被引用的对象返回 `conforming=false` 且不改状态。`deleted` 与 `tombstoned` 互斥，`deleted` 要求计数为零。
- **写入边界**：每次公开变更只重写自己那一节；四节共享同一个 `JsonStore`，不引入跨节事务。恢复按 `context.events` → `context.handles` → `context.blackboards` → `context.objects` 顺序逐条校验，任何损坏抛 `ValueError`，不会恢复半个注册表。
- **默认不变**：不传 `store` 时所有新方法仍是纯内存行为，适配器与演示无需改动。

### 18.3 验证证据

2026-11-19，提交 `3d251a6`：

```
python3 -m unittest discover -s impl/tests -t impl -p 'test_context.py'
→ Ran 107 tests ... OK

python3 -m unittest discover -s impl/tests -t impl
→ Ran 685 tests ... OK

python3 tools/check_schemas.py
→ OK: 45 checks passed across 15 schemas
python3 tools/validate_examples.py
→ OK: 24 checks passed
python3 tools/check_docs.py
→ OK: 195 checks passed across 42 Markdown files
python3 tools/conformance_run.py --impl impl/adapter.py
→ 68 cases: 64 pass, 0 fail, 4 skip
python3 demo/run_demo.py
→ registered=3 discovery=1 consent=1 receipt=verified delegated=2 context=1 audit=verified
```

新增的 46 条测试覆盖：句柄登记往返与分节写入、同体幂等与异体冲突、返回值深拷贝、按标识解析、过期与 audience 仍生效、未知标识审计并以 `CONTEXT_NOT_FOUND` 失败、空标识、删除持久化、非法字段、非对象分节、键与记录不匹配、损坏记录、跨节共存、纯内存；黑板夹具字段往返、打开幂等与冲突、`task_id` 不匹配、`board` 与 `entries` 互斥、写入持久化、未知/已关闭黑板、关闭清空与不晋升、重复关闭幂等、非法字段与损坏记录、纯内存；对象元数据往返、登记幂等与冲突、引用计数增减、计数下限、零引用硬删、有引用墓碑化、硬删拒绝、已删除对象不可再操作、未知对象、非法字段、深拷贝、非法与损坏记录、纯内存。

### 18.4 已知边界

1. **不是对象存储**：`context.objects` 只保存元数据、引用计数与墓碑，不保存对象字节；`delete_object` 不触碰文件系统。
2. **黑板不保留条目内容**：关闭后只留下 `entries_archived` 计数与 `promoted_to_memory=false`，条目本身不归档到磁盘；需要取证时应在关闭前导出。
3. **缓存窗口仍是纯函数**：`cache_window` 不持久化具体缓存条目，重启后只能按句柄 TTL 重新判断。
4. **没有句柄撤销**：注册表支持登记与删除，但没有 §9.3 的撤销广播；删除只影响后续按标识解析，已交给调用方的句柄副本不受影响。
5. **单写者与整节重写**：每次变更序列化整节；同一 `JsonStore` 仍要求一个进程写入，多用户需要不同 `section` 或不同 store。
6. **跨节写入不原子**：一次 `resolve` 只写事件节，一次登记只写句柄节；如果调用方在同一逻辑操作里先登记再解析，两次写入之间崩溃会留下“已登记但未解析”的状态。

---

## 19. 审计按用户分区与跨 trace 顺序（M4 前置，已完成）

### 19.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/audit.py` | `AuditJournal(user_id=..., store=..., clock=..., max_events=...)`；每 trace 链写入 `audit.user.<user>.chain.<trace>`、归档写入 `audit.user.<user>.archive.<trace>`；跨 trace 序号写入 `audit.order.<user>`；链、归档与序号一次 `put_many`；重开交叉校验；`AuditLedger.append(..., companion=...)` 内部钩子与写失败回滚 |
| `impl/tests/test_audit.py` | 21 条新测试：跨 trace 序号、分区隔离、重开、保留归档、重复/外部 trace/非法事件、写入失败回滚、缺口/重复/时间戳/孤儿/无序链、构造参数、纯内存 |

### 19.2 语义

- **按用户分区**：每个 `user://` 一个 `AuditJournal`，链与归档落在 `audit.user.<user>.chain.<trace>` / `.archive.<trace>`，不会和另一个用户的分区混读。分区只是存储边界，不替代授权：跨用户读取仍由 `authorize_cross_user` 决定，journal 也不检查事件 `actor` 是否等于 `user_id`。
- **跨 trace 顺序**：`audit.order.<user>` 保存 `{seq, trace_id, audit_id, ts}` 列表；序号从 1 开始连续递增，每次 `append` 追加一条。顺序反映写入顺序，不声称因果顺序或墙钟排序。
- **一次原子写入**：`append` 把 trace 链、可能发生的归档迁移与下一条 order 条目合并进一次 `put_many`。`companion` 在持久化前构造；失败时 `AuditLedger` 恢复追加前的 `events`/`_archived`，`AuditJournal` 不推进 `_order` 与 `_next_seq`，因此不会出现“链写了、序号没写”或反之。
- **重开交叉校验**：先校验 order 的形状、`user_id`、连续序号、`audit_id` 唯一与 RFC 3339 时间戳，再加载该用户的全部 trace 链，最后要求 order 条目与各链 `history()`（含归档）逐条对应且 `ts` 一致。缺口、重复、时间戳不符、孤儿条目、链事件无对应条目都以 `AUDIT_CHAIN_INVALID` 拒绝。
- **trace 内规则不变**：每条链仍独立校验 schema、trace 一致与 `prev_hash`；trace 内重复 `audit_id` 仍拒绝。journal 额外拒绝跨 trace 的重复 `audit_id`。
- **默认不变**：不传 `store` 时 journal 只在内存中维护链与序号；`Bus`、`TaskBoard`、`ContextFabric` 不会自动追加事件。
- **单写者**：不同用户的 journal 必须共享同一个 `JsonStore` 实例；同一路径打开两个 store 会重新引入文档化的多写者覆盖问题。

### 19.3 验证证据

2026-11-19，提交 `a2c6853`：

```
python3 -m unittest discover -s impl/tests -t impl -p 'test_audit.py'
→ Ran 88 tests ... OK

python3 -m unittest discover -s impl/tests -t impl
→ Ran 706 tests ... OK

python3 tools/check_schemas.py
→ OK: 45 checks passed across 15 schemas
python3 tools/validate_examples.py
→ OK: 24 checks passed
python3 tools/check_docs.py
→ OK: 195 checks passed across 42 Markdown files
python3 tools/conformance_run.py --impl impl/adapter.py
→ 68 cases: 64 pass, 0 fail, 4 skip
python3 demo/run_demo.py
→ registered=3 discovery=1 consent=1 receipt=verified delegated=2 context=1 audit=verified
```

新增的 21 条测试覆盖：跨 trace 连续序号与内容、每 trace 独立链、重开恢复链与顺序、按用户分区互不干扰、保留归档后顺序仍完整、跨 trace 重复 `audit_id` 拒绝、外部 trace 拒绝、非法事件不推进序号、写入失败同时回滚链与序号、order 无链/链无 order/序号缺口/重复条目/时间戳不符/孤儿条目、order 的 `user_id` 不符与条目字段损坏、构造参数、显式 `audit_id`/`ts`、返回值深拷贝、纯内存 journal。

### 19.4 已知边界

1. **顺序是写入顺序**：`seq` 只表示同一用户分区内的追加次序，不携带因果信息；不同用户或不同设备之间没有总序。
2. **按用户分区的代价**：同一用户的 order 每次追加都重写整节，长历史下成本线性增长；归档虽可保留全部事件，仍只增不减，没有压缩。
3. **不是授权**：`AuditJournal` 只按 `user_id` 分节，不验证调用者身份，也不检查事件 `actor`；越权读取仍须经 `authorize_cross_user`。
4. **单写者**：一个 `JsonStore` 仍要求一个进程写入；多进程并发追加需要在外部串行化，或按用户/实例拆分 store。
5. **不自动接线**：`Bus`、`TaskBoard` 与 `ContextFabric` 仍只返回事件，是否写入 journal 由调用方决定。
6. **崩溃原子性范围**：`put_many` 只保证链、归档与 order 三节同一次落盘；调用方在 `append` 之外另行执行的业务副作用不在该事务内。

---

## 20. Windows 密钥环与迁移工具（M4 前置，已完成）

### 20.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/keystore.py` | `KeyringKeyStore` 新增 Windows 后端：PowerShell 调用 `PasswordVault`（Windows Credential Manager），保存时密钥经 stdin 传入；`MISSING_CODES` 统一“条目不存在”的退出码；`KeyringError(reason, backend, returncode, stderr, platform)`；`migrate_key_store(source, target, *, delete_source=True)` |
| `tools/migrate_pcs_key.py` | 一次性 CLI：`--json <store>` → `--to keyring` 或 `--to json:<path>`；输出 JSON 报告；`backend_missing`/迁移失败退出码 1 |
| `impl/tests/test_keystore.py` | 14 条新测试：Windows 平台映射与三条命令构造、stdin 传密、缺失条目、失败原因细分、缺失 CLI、迁移的七种结果 |

### 20.2 语义

- **Windows 后端**：`backend_for("win32") = "powershell"`。命令是 `powershell -NoProfile -NonInteractive -Command <script>`，脚本用 WinRT 投影 `[Windows.Security.Credentials.PasswordVault,...]` 完成 `Retrieve`/`Add`/`Remove`；`service`/`account` 映射为 vault 的 resource/user。保存前先尝试移除旧条目，等价于 macOS `-U` 的“更新语义”。密钥通过 stdin 进入脚本（`[Console]::In`），不在命令行参数里。
- **条目不存在统一判定**：`MISSING_CODES = {security: 44, secret-tool: 1, powershell: 44}`；Windows 脚本在 catch 里 `exit 44`，所以 `load()` 返回 `None`、`delete()` 返回 `False` 的行为与既有后端一致。
- **错误细分**：后端失败抛 `KeyringError`（`RuntimeError` 子类），`reason` 为 `backend_missing`（构造时 CLI 缺失）、`lookup_failed`、`store_failed`；`returncode`/`stderr` 保留原始输出。旧的 `except RuntimeError` 代码不受影响。记录损坏仍抛 `ValueError`。
- **迁移安全序**：`migrate_key_store` 先用 `signer_of` 校验源记录（损坏即拒绝且目标不动）；目标已被不同 `kid`/公钥占用时返回 `target_occupied` 不写不删；目标为同一记录时幂等返回 `already_migrated`；写入后回读比对，不一致返回 `target_verify_failed`；只有目标确认后才 `delete_source`（后端不支持 `delete` 时报告 `deleted_from_source=false` 并保留源）。
- **报告可序列化**：迁移结果是纯 JSON（`migrated`、`reason`、`kid`、`source`、`target`、`deleted_from_source`、`target_kid`），CLI 直接打印。
- **默认不变**：不传 `key_store` 的 `ConsentFlow` 仍用 0600 JSON；`--keep-source` 保留原分节；`JsonKeyStore`/`MemoryKeyStore` 行为不变。

### 20.3 验证证据

2026-11-19，提交 `adba047`：

```
python3 -m unittest discover -s impl/tests -t impl -p 'test_keystore.py'
→ Ran 61 tests ... OK

python3 -m unittest discover -s impl/tests -t impl
→ Ran 720 tests ... OK

python3 tools/check_schemas.py
→ OK: 45 checks passed across 15 schemas
python3 tools/validate_examples.py
→ OK: 24 checks passed
python3 tools/check_docs.py
→ OK: 195 checks passed across 42 Markdown files
python3 tools/conformance_run.py --impl impl/adapter.py
→ 68 cases: 64 pass, 0 fail, 4 skip
python3 demo/run_demo.py
→ registered=3 discovery=1 consent=1 receipt=verified delegated=2 context=1 audit=verified
```

CLI 冒烟（本机，`--to json:` 模式，不触碰真实密钥环）：先有密钥 → 报告 `migrated=true, reason=copied, deleted_from_source=true`；再次运行 → `no_key_in_source`，退出码 0；目标文件中的 `kid` 与源一致。

新增的 14 条测试覆盖：`win32 → powershell` 映射与不支持平台；构造时 CLI 缺失报 `backend_missing`（含 `platform` 字段且仍是 `RuntimeError`）；Windows load 的命令形状、脚本含 `PasswordVault`/引号化的 service/account/`RetrievePassword`/`exit 44`；缺失条目返回 `None`；save 经 stdin 传密且脚本含 `PasswordCredential`、先 `Remove` 再 `Add`、`exit 1`；delete 成功/缺失两种返回；`lookup_failed` 与 `store_failed` 携带 `returncode`/`stderr`；迁移的缺失源、成功复制、保留源、损坏源拒绝、不同目标密钥中止、损坏目标记录中止、同记录幂等、不可删除源保留记录与报告可序列化。

### 20.4 已知边界

1. **Windows 路径未在真实 Windows 上验证**：脚本依赖 Windows PowerShell 5.1 的 WinRT 投影；PowerShell 7（pwsh）默认不可用，且 `PasswordVault` 的行为因应用容器而异。CI 只有静态命令构造测试。
2. **单条记录迁移**：`migrate_key_store` 只迁移一个 signer；多 PCS 账号、多用户或批量迁移不在范围内，迁移后也不会自动重建 `ConsentFlow`。
3. **迁移不是原子事务**：目标写入与源删除是两步；进程在两步之间中断会留下两边都有记录的状态，下次迁移会因目标相同而幂等收敛。
4. **错误分类仍以 CLI 为界**：`KeyringError` 区分“CLI 缺失/失败”，但无法区分密钥环锁定的具体原因（如 macOS 钥匙串授权弹窗被拒），这需要原生绑定。
5. **macOS argv 泄露仍在**：`security add-generic-password` 没有 stdin 形式，macOS 路径依旧是文档化的开发便利；Windows/Linux 路径走 stdin。
6. **`--to json:` 复制而非轮换**：该模式只是搬记录，不生成新 `kid`；密钥轮换仍须走 `KeyRegistry` 的新 `kid` 流程。

---

## 21. 并发服务事件循环（M4 前置，已完成）

### 21.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/transport.py` | `UnixStreamServer.serve_forever(*, max_messages, concurrency=1, mode="threads")`；`mode="selector"` 用 `selectors.DefaultSelector` 在单线程内多路复用监听与全部 session；`_drop_session` 摘除断开/出错 peer |
| `impl/tests/test_transport.py` | 6 条新测试：参数校验、空闲连接不阻塞、断连 peer 摘除后继续服务、`max_messages` 停止、监听关闭停止、连接配额在 selector 模式下生效 |

### 21.2 语义

- **三种服务模式**：`concurrency=1` 串行（不变）；`concurrency=N` 线程池（不变）；`mode="selector"` 事件循环，要求 `concurrency=1`，两者互斥，`mode` 非法值直接 `ValueError`。默认仍是 `threads`，现有调用不迁移。
- **单线程多路复用**：监听 socket（`data=None` 标记）与每个已接受 session 注册到同一个 `DefaultSelector`；可读的监听 socket 走 `accept()`（含连接配额），可读的 session 服务一条消息。循环每 0.05 s 醒一次检查 `self.closed` 与 `max_messages`。
- **peer 摘除**：断开（`ConnectionError`）、写垃圾/协议错（`OsapError`、`ValueError`）、未实现操作（`NotImplementedError`）或 socket 错误的 session 被注销并关闭，循环继续服务其他连接；一条都没送出的回复不计入 `max_messages`（与线程池的归还语义一致）。
- **配额不变**：连接与消息配额仍由服务器共享的 `AdmissionController` 执行；被拒绝的连接在 `accept()` 内收到 `RATE_LIMIT` 错误信封后被关闭，循环只 `continue`。
- **关闭语义**：`close()` 置位后循环在下一次 `select` 超时返回时退出并关闭全部 session；线程池的 `shutdown(SHUT_RDWR)` 收尾只属于 threads 模式。
- **默认不变**：不传 `mode` 时行为与此前完全一致。

### 21.3 验证证据

2026-11-19，提交 `6656195`：

```
python3 -m unittest discover -s impl/tests -t impl -p 'test_transport.py'
→ Ran 29 tests ... OK

python3 -m unittest discover -s impl/tests -t impl
→ Ran 726 tests ... OK

python3 tools/check_schemas.py
→ OK: 45 checks passed across 15 schemas
python3 tools/validate_examples.py
→ OK: 24 checks passed
python3 tools/check_docs.py
→ OK: 195 checks passed across 42 Markdown files
python3 tools/conformance_run.py --impl impl/adapter.py
→ 68 cases: 64 pass, 0 fail, 4 skip
python3 demo/run_demo.py
→ registered=3 discovery=1 consent=1 receipt=verified delegated=2 context=1 audit=verified
```

新增的 6 条测试覆盖：`selector` + `concurrency>1`、非法 `mode`、非字符串 `mode` 的拒绝；空闲连接不再阻塞另一连接的握手与请求；先连接再裸断开的 peer 被摘除后循环仍服务完剩余回复；`max_messages=1` 在送出 welcome 后停止循环、后续连接无法获得服务；从外部 `close()` 监听后线程退出；`max_connections=1` 下第二个连接收到 `RATE_LIMIT`（`reason=connection_limit`）且第一个连接继续被服务。

### 21.4 已知边界

1. **半帧仍可阻塞**：selector 模式没有双工读缓冲；peer 发出半个长度前缀后停滞会让循环停在该 session 上，直到对端完成或断开。彻底解决需要原生异步绑定（asyncio / 平台事件循环）。
2. **每条消息一个往返**：循环仍按“可读 → 服务一条 → 回到 select”推进，不做批处理或写聚合；高吞吐场景需要 pipelining 或平台绑定。
3. **错误信封不算回复失败**：session 内 `bus.receive` 抛出的 `OsapError` 在 `serve()` 内转为错误信封并正常返回，计入 `served`；只有让 session 无法继续的错误才摘除连接。
4. **没有加权调度**：所有就绪 session 轮流服务，不按 Agent 或消息优先级排序（§7.11 的 `priority` 仍未接线）。
5. **平台原生异步绑定未实现**：asyncio、XPC、Binder、named pipe 仍在路线图上；selector 是 Python 标准库方案，不是平台传输。

---

## 22. 跨进程撤销分发（M4 前置，已完成）

### 22.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/capability.py` | `revoke` 为每个新撤销 token 追加 `{seq, cap_id, ts}` 日志条目，与撤销集一次 `put_many` 原子落盘且写失败回滚；`apply_revocations(entries, source=...)` 按来源游标应用远端批次并级联；`REVOCATION_GAP` 领域扩展码；`last_seq` / `applied_sources()` |
| `impl/tests/test_capability.py` | 17 条新测试：日志连续性/持久化/幂等/损坏拒绝、批次的级联/幂等/缺口/部分拉取/多来源/混合来源/已撤销不重级联、两次写失败回滚 |

### 22.2 语义

- **生产端**：`revoke(cap_id)` 沿父→子索引级联，只为新撤销的 token 追加日志条目（重复撤销不写）；本地日志序号从 1 连续。日志与 `capability.revoked` 在一次 `put_many` 中落盘，写失败时内存的撤销集、审计与日志全部回滚。
- **消费端**：`apply_revocations(entries, source=...)` 以 `source` 命名远端流，条目里的 `seq` 是**来源流**的序号；副本维护每来源游标 `applied_sources()[source]`。序号 ≤ 游标的条目跳过（重复投递幂等），批内序号必须连续，第一条新条目必须等于游标 +1——首个批次必须从来源日志的第 1 条开始，否则报 `REVOCATION_GAP`。
- **落库形状**：应用的条目在副本日志里记为 `{seq(本地), cap_id, ts, origin=source, source_seq}`；本地撤销条目不带 `origin`。恢复时校验：本地序号连续、`origin` 与 `source_seq` 成对且按来源连续、条目的 `cap_id` 必须在撤销集内、`cap_id` 不重复；任何损坏拒绝重开。
- **级联与重试**：每个新条目走与本地 `revoke` 相同的级联（副本未持有的 token 也记撤销，`is_revoked` 沿祖先链生效）；副本已独立撤销的条目只记日志不重复级联。写失败回滚内存（撤销集、审计、日志、游标），调用方原样重试同一批次。
- **fail closed**：来源批次有缺口时什么都不应用——静默跳过撤销会让副本继续执行已撤销的能力，比拒绝服务更危险。
- **默认不变**：不传 `store` 时日志只在内存；`revoke` 签名与返回值不变，`consent_flow` 与适配器无需改动。

### 22.3 验证证据

2026-11-19，提交 `893b357`：

```
python3 -m unittest discover -s impl/tests -t impl -p 'test_capability.py'
→ Ran 69 tests ... OK

python3 -m unittest discover -s impl/tests -t impl
→ Ran 743 tests ... OK

python3 tools/check_schemas.py
→ OK: 45 checks passed across 15 schemas
python3 tools/validate_examples.py
→ OK: 24 checks passed
python3 tools/check_docs.py
→ OK: 195 checks passed across 42 Markdown files
python3 tools/conformance_run.py --impl impl/adapter.py
→ 68 cases: 64 pass, 0 fail, 4 skip
python3 demo/run_demo.py
→ registered=3 discovery=1 consent=1 receipt=verified delegated=2 context=1 audit=verified
```

新增的 17 条测试覆盖：级联撤销的日志连续性、同批时间戳、本地序号与 `last_seq`；日志与撤销集同文件原子持久化、重开一致；重复撤销不写条目；纯内存不带盘；`put_many` 失败回滚撤销集/审计/日志并可重试成功；损坏日志（缺 `seq`、`seq=0`、布尔 `seq`、空 `cap_id`、坏 `ts`、`origin` 与 `source_seq` 缺一/非法）与重复 `cap_id` 拒绝重开；日志条目引用撤销集之外的重开拒绝；本地日志序号缺口重开报 `REVOCATION_GAP`；副本批次级联（含未持有 token）、幂等重投、部分拉取后缺口 fail closed 且补齐后原样重试成功、首批必须从来源第 1 条开始、双来源独立游标、混合 `origin` 拒绝、损坏批次无副作用、副本写失败回滚。

### 22.4 已知边界

1. **拉模式，不自动通知**：本实现只提供日志与校验；谁去读来源日志、何时读、失败重试几次都由调用方决定，§5.5 的“通知受影响 Agent”仍需自建传输（Bus 消息、文件轮询或 IPC）。
2. **撤销 P95 仍是进程内口径**：`apply_revocations` 是另一个进程内的级联成本，与 `benchmark_revocation.py` 测的不是同一个数字；跨进程端到端传播时间没有测量。
3. **日志只增不减**：`capability.revocations` 没有压缩或 TTL；来源侧长期运行后首批拉取会线性变长（副本靠游标跳过，但传输量不小）。
4. **单一来源命名空间**：`source` 是调用方给的字符串标签，没有签名或来源认证；被攻破的对端可以喂假撤销（fail closed 方向）或重放旧批次（幂等无副作用），但不能让副本跳过撤销。
5. **不处理时钟**：条目 `ts` 只做 RFC 3339 校验与展示，分发顺序完全由序号决定，不比较时间戳。
6. **与同意撤销未打通**：`ConsentFlow` 撤销回执时级联签发能力（已有），但该撤销不写 `capability.revocations` 日志，跨进程只覆盖 `CapabilityAuthority.revoke` 的直接路径。

---

## 23. 恢复事务与 effect 归档（M4 前置，已完成）

### 23.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/audit.py` | `AuditLedger.append_many(events, companion=None)`：整批校验、哈希并暂存，最后一次原子落盘（含归档裁剪与 companion 附加分节）；批内末尾出现重复 `audit_id` 或写失败时全量回滚；新增 `store` 属性 |
| `impl/osap/task.py` | `TaskBoard(store, ledger=..., max_effects=...)`；`recover()` 在挂共享 store 的 ledger 时把任务树、effect 日志与审计链放进同一 `put_many`，写失败回滚状态/日志/暂存事件；`task.effects.archive` 归档最旧已决 effect；pending/unknown 永不归档；effect 变更写失败回滚内存 |
| `impl/tests/test_task.py` | 12 条新测试：同事务落盘与重开验证、无事可做不写审计、恢复写失败回滚、ledger 共享校验、reschedule 审计、归档移动/永不归档 pending、归档重开与重放闸门、写失败回滚、损坏归档、limit 校验 |
| `impl/tests/test_audit.py` | 6 条新测试：`append_many` 单次落盘、companion 分节、批内重复全量回滚、写失败回滚、空批次、类型校验 |

### 23.2 语义

- **同事务恢复**：`TaskBoard(ledger=...)` 要求 `AuditLedger` 与 board 共享同一个 `JsonStore` 实例（构造时校验，独立文件直接 `ValueError`）。`recover()` 先把任务/effect 变更应用到内存，再用 `append_many` 暂存恢复事件，最后由 ledger 的一次 `put_many` 同时写入 `task.tasks`、`task.effects` 与 `audit.chain.<trace>`。
- **失败回滚**：任务状态快照（仅 status 会被恢复变更）、effect 日志深拷贝与审计长度在变更前捕获；ledger 内部自带整批回滚。任何一层失败，内存全部还原，重启恢复可以原样重试。
- **`append_many` 契约**：整批共享一次落盘；`companion` 用最后一条事件调用并返回附加分节（`AuditJournal` 与本事务都靠它）；空批次不落盘；批内重复 `audit_id` 与写失败一样全量回滚。
- **effect 归档**：`max_effects=N` 在 journal 超限时把最旧的**已决** effect（executed/reconciled）移入 `task.effects.archive`，与 live 日志同一次原子写入；pending/unknown 即使超限也留在 live，保证 `require_replay_allowed()` 的重放闸门不被裁剪抬起。归档条目与 live 用同一套校验恢复；已归档 intent 再请求重放得到 `ROUTING_NOT_FOUND`（历史结果，重放需重新记录 intent）。
- **effect 变更回滚**：`record_effect_intent` / `record_effect_outcome` / `reconcile_effect` 现在在变更前快照，写失败时还原 journal 与归档（此前失败会留下内存与磁盘分叉）。
- **默认不变**：不传 `ledger` 时恢复仍是两节 `put_many`；不传 `max_effects` 时 journal 无上限；`recover()` 返回新增 `ledger_trace_id`（无 ledger 为 `null`），其余字段不变，适配器与演示无需改动。

### 23.3 验证证据

2026-11-19，提交 `2609ef1`：

```
python3 -m unittest discover -s impl/tests -t impl
→ Ran 760 tests ... OK

python3 tools/check_schemas.py
→ OK: 45 checks passed across 15 schemas
python3 tools/validate_examples.py
→ OK: 24 checks passed
python3 tools/check_docs.py
→ OK: 195 checks passed across 42 Markdown files
python3 tools/conformance_run.py --impl impl/adapter.py
→ 68 cases: 64 pass, 0 fail, 4 skip
python3 demo/run_demo.py
→ registered=3 discovery=1 consent=1 receipt=verified delegated=2 context=1 audit=verified
```

新增的 18 条测试覆盖：恢复后 store 只含任务树/effect 日志/审计链三节且 ledger 可验证、重开一致；无事可做时不写审计也不产生分节；恢复写失败回滚状态/pending/审计长度且 ledger 为空、去掉故障后重试成功；ledger 必须为 `AuditLedger`、必须共享 store、board 必须有 store、类型错误拒绝；reschedule 恢复写入 `task.created` 事件；`append_many` 的单次落盘、prev_hash 链接、companion 分节、批内重复 `audit_id` 全量回滚且不落盘、写失败回滚、空批次、非列表与空列表；`max_effects` 移动最旧已决 effect 且 pending 永不归档、归档跨重开、已归档 intent 重放报 `ROUTING_NOT_FOUND`、写失败回滚、损坏归档（非对象/键不符/非法状态/未知任务）拒绝、limit 参数校验。

### 23.4 已知边界

1. **同事务要求同库**：ledger 与 board 各持一个 store 文件时无法原子，构造即拒绝；跨文件一致性留给调用方。
2. **没有 TTL 清理**：`task.effects` 与归档都只增不减，与其他持久化子系统一致；TTL/过期清理仍在全局边界里。
3. **归档后 intent 不可重放**：已归档 effect 的重放闸门是“找不到”而不是“允许”，重放需要重新 `record_effect_intent`；这是保守方向，但意味着归档改变语义（intent 必须重新登记）。
4. **审计只覆盖恢复事件**：挂 ledger 后只有 `recover()` 的产物进链；日常 `record_effect_intent`/`reconcile_effect` 的 `TaskBoard.audit` 仍是内存列表，需调用方自行写入 ledger。
5. **快照粒度**：任务回滚只还原 `status` 字段——恢复路径也只改 status，其他字段不在事务内。
6. **`append_many` 无优先级**：整批按给定顺序落盘，没有按风险或用户排序；顺序由调用方决定。

---

## 24. 审计归档压缩与按用户导出（M4 前置，已完成）

### 24.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/audit.py` | `AuditLedger(max_archive=N)`：归档超限时丢弃最旧归档事件并把它们链接的 `base` 哈希写进归档分节，kept 前缀仍可端到端验证（锚在 `base` 而非创世）；重开校验 `base`，不符报 `AUDIT_CHAIN_INVALID`；`AuditJournal.export()` 输出整用户分区快照 |
| `impl/tests/test_audit.py` | 10 条新测试：归档上限/锚点验证/重开/base 不符拒绝/无上限保持创世/limit 校验，export 的内容/含归档历史/深拷贝/空分区 |

### 24.2 语义

- **归档压缩**：每次 `_trim` 之后检查归档长度；超过 `max_archive` 就丢弃最旧的溢出事件，`base` 取**最后一个被丢弃事件**的 `hash`（kept 前缀正是从它链接）。`base` 为创世哈希时语义与之前完全一致。
- **验证边界**：`_verify_archive` 改为锚在 `base`；`verify()` 的 live 锚（归档尾哈希）不变。被丢弃的 `audit_id` 不再参与重复检查、也无法从创世重放——这是用最旧历史的证明力换有界存储，文档明示。
- **持久化**：归档分节新增 `base` 字段；重开时读取并校验，`base` 与 kept 首条 `prev_hash` 不符直接 `AUDIT_CHAIN_INVALID`。
- **按用户导出**：`AuditJournal.export()` 返回 `{user_id, generated_at, last_seq, order, traces}`；每 trace 携带 `chain_id`、`created_at` 与 `history()` 全事件（含归档）。深拷贝返回，消费方应固定 `last_seq` 并把后续追加当新批次。
- **默认不变**：不传 `max_archive` 时归档仍只增不减，行为与历史一致。

### 24.3 验证证据

2026-11-19，提交 `da17a2b`：`test_audit.py` 104 条全过，全量 770 tests OK；`check_docs` 195/42、`check_schemas` 45/15、`validate_examples` 24、一致性 64 pass / 0 fail / 4 skip、demo 完整。

### 24.4 已知边界

1. **压缩丢历史**：被丢弃事件退出重复 `audit_id` 检查，也不能再从创世验证；`max_archive` 是权衡不是免费午餐。
2. **`history()` 语义随压缩变化**：压缩后 `history()` 只覆盖 `base` 之后；需要全历史时不要设 `max_archive`。
3. **export 是快照**：不冻结来源，消费方无法阻止导出后继续追加。
4. **跨用户仍无总序**：export 按用户分区导出，跨用户/跨设备顺序仍不在 0.1。

---

## 25. 撤销订阅与跨进程传播测量（M4 前置，已完成）

### 25.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/capability.py` | `RevocationWatcher(source_path, replica, *, source, interval)`：按间隔重读源 store 的撤销日志并交给 `apply_revocations` 自动应用；失败下一轮重试；`poll_once` / `start` / `stop`；源文件只读 |
| `impl/tests/test_capability.py` | 4 条新测试：自动应用与游标推进、重复启动拒绝、参数校验、失败后下一轮重试成功 |
| `tools/benchmark_revocation.py` | `--cross-process`：spawn 副本进程，量化 `revoke()` → 副本 `is_revoked()` 端到端（含轮询等待、文件读取、校验与副本级联），输出 p50/p95/p99 并按 `--cross-threshold-ms` 判定 |

### 25.2 语义

- **拉模式订阅**：watcher 每轮用新的 `JsonStore` 实例读源文件（单写者规则不破——watcher 永不写源），整批交给副本的 `apply_revocations`，靠来源游标保证重复投递幂等。缺口（`REVOCATION_GAP`）等失败被线程循环吞掉、下一轮重试；直接调用 `poll_once` 时错误照常抛出。
- **无推送通道**：文件是唯一传输；没有协议消息、没有平台通知。低延迟场景应自建推送并直接调 `apply_revocations`。
- **跨进程测量**：父进程持有签发方与源 store，子进程持有副本 store 并按 `--interval` 轮询；每个样本撤销一条独立链（`--chain-length` 个 token），父进程记录 `revoke()` 返回时刻，子进程把“应用到该序号”的时刻经队列回报，差值即端到端传播时延。实测（5 链、间隔 5 ms）：p50 ≈ 8 ms，p95 ≈ 236 ms——主要来自轮询等待与进程调度，与进程内 P95（1.23 ms）不可比。
- **基准不进 CI**：与既有 in-process 基准一致，阈值依赖机器。

### 25.3 验证证据

2026-11-19，提交 `1b477f6`：`test_capability.py` 73 条全过，全量 778 tests OK；本机跑通 `--cross-process --samples 5` 与 in-process `--samples 20` 两种模式。

### 25.4 已知边界

1. **延迟下限是轮询间隔**：watcher 的通知延迟 ≥ interval + 调度抖动；推送通道仍需自建。
2. **轮询开销**：每轮新建 `JsonStore` 读整个文件；日志只增不减时读取成本随历史线性增长（配合 `max_archive`/日志压缩可缓解）。
3. **源标签无认证**：watcher 不验证来源身份；被攻破对端只能造成 fail closed 或无害重放（与 §22 相同）。
4. **测量口径**：`--cross-process` 的样本是独立短链，不含 1,555 节点的大树；跨进程大 cascade 的数字需要单独测量。

---

## 26. asyncio 绑定（M4 前置，已完成）

### 26.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/transport.py` | `serve_forever(mode="asyncio")`：`_AsyncioStreamProtocol` 按连接缓冲字节、剥完整帧后分发；连接建立时走 `UnixSession` + 配额（拒绝先发 `RATE_LIMIT` 信封）；`close()` 在 asyncio 模式改为 `call_soon_threadsafe` 通知 loop，由服务线程关 socket |
| `impl/tests/test_transport.py` | 8 条新测试：参数校验、往返、空闲连接不阻塞、**半帧停滞不阻塞他人**、断连摘除、连接配额、`max_messages` 停止、监听关闭停止 |

### 26.2 语义

- **缓冲分帧**：`data_received` 把字节追加进每连接缓冲，逐帧剥出长度前缀与 payload；超长帧立即以错误信封关闭，半帧等待不再占用 loop。
- **分发复用 Bus**：payload 解析后交给该连接的 `Bus.receive`；`OsapError` 以 `error_envelope` 应答，连接级错误关闭连接。分发是同步的，慢处理会串行化 loop——并行化要靠平台原生绑定。
- **关闭规则（关键修复）**：macOS 上从其他线程关闭 kqueue 正在监听的 fd 会让 `kevent()` 永久阻塞（已用最小复现验证）。asyncio 模式下 `close()` 只设置 `closed` 并 `call_soon_threadsafe(finish)`，loop 关闭 server 与全部 transport，服务线程在 `finally` 里关 socket；`UnixSession.close` 对 asyncio 持有的 socket 容忍关闭失败。
- **语义对齐**：连接与消息配额、`max_messages`（只计已写出的回复）与 selector/线程池模式一致；默认 `mode="threads"`，现有调用不变。

### 26.3 验证证据

2026-11-19，提交 `c32fc97`：`test_transport.py` 37 条全过，全量 782 tests OK；一致性 64 pass / 0 fail / 4 skip；demo 完整。`test_a_stalled_half_frame_does_not_block_another_peer` 在 asyncio 模式下发送半个长度头后静默，另一连接仍完成握手与请求——该场景在 selector/线程池模式下会阻塞。

### 26.4 已知边界

1. **分发串行**：慢的 Bus 处理会阻塞整个 loop；需要并行要等平台原生绑定（XPC/Binder/named pipe，仍不在本阶段）。
2. **`close()` 与启动竞态**：loop 尚未注册 `finish` 前调用 `close()` 会退回“直接关 socket”路径；此时 loop 还没起来，无 kqueue 挂死风险，但 `create_server` 可能失败（`_serve_asyncio` 吞掉并返回 0）。
3. **macOS 倾向**：kqueue 挂死问题在 Linux epoll 上未必复现，但统一走 loop 内关闭更安全，代价是文档化的实现约定。
4. **写缓冲无背压**：`transport.write` 直接入 asyncio 写缓冲，慢消费者可膨胀内存；0.1 不做流控窗口。

---

## 27. 撤销推送通道（M4 前置，已完成）

### 27.1 交付物

| 文件 | 作用 |
|---|---|
| `impl/osap/transport.py` | `RevocationFeedServer(path, journal, *, source, peer_policy)`：专用 `AF_UNIX` sidecar socket，长度分帧承载纯 JSON 批次（`{"source", "cursor", "entries"}`）；连接即发 catch-up（从序号 0 起），之后每次 `notify()`（或 0.05 s 轮询兜底）只推新条目；`journal` 是零参调用方回调，模块不反向依赖 `capability`；`RevocationFeedClient/Session` 复用既有流分帧，把批次交给 `apply_revocations` |
| `impl/tests/test_transport.py` | 8 条新测试：批次应用、迟到订阅 catch-up、双订阅者、增量推送、断连不影响服务、被拒 peer 无批次、参数校验、close 删除 socket 文件 |
| `tools/benchmark_revocation.py` | `--cross-process --tree`：每个样本撤销一棵完整 width/depth 树，量化跨进程整树 cascade |

### 27.2 语义

- **sidecar 而非 Bus 流量**：推送通道承载纯 JSON 帧、无 `osap.*` 信封、不路由、不进幂等索引——§5.5 的“通知受影响 Agent”不扩大 Bus 的消息面；接收方仍是副本上的 `apply_revocations`，游标、`REVOCATION_GAP` 与回滚语义与拉模式完全一致。
- **catch-up + 增量**：订阅者连上后先收到从序号 0 起的全部批次（迟到订阅自动补齐），此后只在 journal 增长后收到新条目。`notify()` 由签发方在 `revoke` 后显式调用；0.05 s 轮询是兜底，不是唯一触发。
- **journal 解耦**：服务器只持有一个零参回调读取完整日志（如 `lambda: JsonStore(p).get("capability.revocations")`），每次调用重新读文件，因此跨进程写永远可见，且服务器绝不写日志。
- **对端认证**：可选 `PeerPolicy`，被拒连接直接关闭、不推任何批次（测试断言客户端读到 EOF）。
- **测量扩展**：`--cross-process --tree --width --depth` 每样本撤销整棵树；实测（3 样本、43 token/树、5 ms 轮询）p50 ≈ 22 ms、p95 ≈ 215 ms，量级与短链一致，主项是轮询等待与调度。

### 27.3 验证证据

2026-11-19，提交 `c2b3f39`：`test_transport.py` 45 条全过，全量 790 tests OK；`check_docs` 195/42、`check_schemas` 45/15、`validate_examples` 24、一致性 64 pass / 0 fail / 4 skip、demo 完整；本机跑通 `--cross-process --tree --samples 3 --width 6 --depth 2` 与短链两种基准。

### 27.4 已知边界

1. **`notify()` 是显式钩子**：签发方忘记调用时推送退化为 0.05 s 轮询兜底；`CapabilityAuthority` 与 feed 服务器之间没有自动接线（保持两者解耦）。
2. **每订阅者一个线程**：推送线程按连接划分，无共享写缓冲；订阅者很多时成本线性（与线程池服务同一边界）。
3. **sidecar 无身份认证默认关闭**：不传 `PeerPolicy` 时任何本机进程都能订阅撤销流；生产部署必须传策略。
4. **帧内无签名**：推送批次是明文 JSON；被攻破的对端只能力 fail closed 或无害重放（与 §22 相同），但通道本身不是防篡改边界。
5. **测量仍含轮询兜底延迟**：`--cross-process` 的数字包含 ≤ 0.05 s 的轮询兜底与调度，不代表纯推送延迟。

---

## 28. M5 一致性登记表(进行中)

### 28.1 交付物

| 文件 | 作用 |
|---|---|
| `conformance/registry.md` | 登记表本体:目的与原则(可复现闸门、登记非认证、自证标注、报告卫生)、条目格式、登记流程(提交 → 复核 → 收录/除名)、登记表、边界 |
| `conformance/reports/osap-reference-2026-11-20.json` | 参考实现的首条报告:68 用例,64 pass / 0 fail / 4 manual skip,已通过 `report.schema.json` 校验 |
| `conformance/README.md` §8 | 目录结构新增 `registry.md` 与 `reports/`;登记流程入口 |
| `docs/conformance.md` §6 / `.en.md` | 指向登记表与复核闸门(中英同步) |
| `docs/roadmap.md` M5 | "建立一致性登记表"标记完成 |

### 28.2 语义

- **可复现闸门**:登记 = 报告 JSON(通过 `report.schema.json`)+ 表格行 + 一条维护者可原样重跑的命令;复核时 `pass`/`fail`/`skip` 集合必须与报告一致,失败用例的 `id` 必须一致。不可复现的声称不收录;已收录但无法复现的移入 ❌ 除名并保留原报告。
- **登记不是认证**:✅ 只表示"复核者按给定命令重跑出过一次相同结果",不担保实现正确性、安全性或持续一致性,也不授予任何品牌/商标权利。
- **自证标注**:`self-attested`(实现方自跑)与 `verified`(维护者/第三方独立重跑)是登记表内的两种状态;参考实现首条为 `self-attested`。
- **manual 用例如实列出**:C2-05、C4-01、C6-08、C7-01 是 manual,不计入 pass/fail,登记行必须写明。
- **边界**:本表不改变 `docs/conformance.md` 的等级、编号或判定;除名记录与原因永久保留,不做静默改写。

### 28.3 验证证据

2026-11-20:

```
python3 tools/conformance_run.py --impl impl/adapter.py --format json \
  --out conformance/reports/osap-reference-2026-11-20.json
→ report written;68 cases,64 pass / 0 fail / 4 skip
报告经 report.schema.json(Draft 2020-12 + FormatChecker)校验通过
python3 tools/check_docs.py
→ OK: 199 checks passed across 43 Markdown files(含 registry.md 与新增链接)
```

### 28.4 已知边界

1. **只有一条登记,且是自证**:参考实现的 ✅ 是维护者自跑;没有外部实现的 `verified` 条目,M5 的互操作目标仍依赖外部参与。
2. **复核闸门已机械化**:`tools/check_registry.py` 校验每行登记(报告 schema、摘要与 `cases` 数组一致、行内声称的 pass 数与 manual id、文件名以实现名开头、日期一致、✅ 必须带复现命令),`--rerun` 额外重跑命令并逐条比对失败/skip 的用例 id;复核器只执行以 `python3 tools/conformance_run.py` 开头的命令。CI 在非 rerun 模式运行该检查。
3. **报告日期是快照**:`generated_at` 含具体时刻,重跑会因时间不同而不逐字节相等;比对口径是 pass/fail/skip 集合与失败 `id`,不是文件哈希。
4. **登记表不担保持续一致**:实现后续版本不再复现时依赖维护者主动复核或实现方更新登记。

---

## 29. IETF 提交前置准备材料包(闸门 0/3/4 已完成)

### 29.1 交付物

| 文件 | 作用 |
|---|---|
| `drafts/submission/checklist.md` | 七项闸门的检查单:同意/IPR/占位作者/文档名/WG 归属/外部引用/复核;逐项标注状态、机械检查命令与负责人;明确"不构成提交、不会被自动发送" |
| `drafts/submission/consent-template.md` | §10.4 贡献者同意书模板:BCP 78(RFC 5378)+ Simplified BSD License 四条确认,签署件存仓库外,仓库内只登记表格 |
| `drafts/submission/ipr-disclosure-template.md` | BCP 79 披露草稿模板:Datatracker 表单逐字段对应;据实披露原则;Apache-2.0 与 IETF Trust 版权的关系说明 |
| `drafts/submission/liaison-agentproto.md` / `liaison-oauth.md` | 两封信草稿(英文,发送对象为 chairs):范围询问 + 审阅请求,不含任何自动发送机制 |
| `tools/check_drafts.py --submission` | 机械闸门:✅ 已转绿(2026-11-20)——作者替换与文档名改名完成后,占位作者检查与作者联系方式检查通过,并接入 CI `drafts` job(`--submission --compile`) |

### 29.2 语义

- **材料包不是提交**:`drafts/submission/` 的全部文件只供人工填写与审阅;仓库与 Datatracker 之间没有任何管道,`git push` 不会触发任何对外动作。
- **闸门进度(2026-11-20)**:0(贡献者名单=署名者本人)✅、3(作者替换)✅、4(文档名 `draft-zeng-*`)✅;1(同意邮件确认)🟡、2(IPR 专利自查)🟡、5(chairs 联络)⬜。`--submission` 已转绿并接入 CI `drafts` job(`--submission --compile`)。
- **作者落点**:两份 draft 的 front `<author>` 块改为 Zeng Zhiyong(`ZZHY`,Independent,272577337@qq.com);`docName`/文件名/`seriesInfo` 改为 `draft-zeng-osap-*`;`drafts/README.md` 的映射表与占位说明同步;邮箱会随 draft 公开发布,是署名者本人确认的选择。
- **联络信只问三件事**:是否在 charter 范围内、是否愿意接收 individual submission 评审、还是应归属其他组;明确声明"不请求采用",署名已填,发送前按 wgchairs 页核对收件人。
- **Apache-2.0 与 IETF Trust 的边界**:实现许可不变;draft 文本提交后版权按 IETF Trust 政策处理——这是提交的前提,不是新增授权;Apache-2.0 的专利授权不替代 BCP 79 披露。

### 29.3 验证证据

2026-11-20:

```
python3 tools/check_drafts.py
→ OK: 36 checks passed across 2 drafts
python3 tools/check_drafts.py --submission
→ FAIL:placeholder author 'OSAP Editors' / 'editors@osap.example' 逐文件列出(如预期)
python3 tools/check_drafts.py --compile(在 drafts venv 内)
→ OK: 36 checks passed across 2 drafts and compiled
python3 tools/check_docs.py
→ OK: 219 checks passed across 48 Markdown files
```

### 29.4 已知边界

1. **需要真人**:同意邮件确认、IPR 自查决策、Datatracker 上传、chairs 信件发送都必须由署名者本人完成;维护者不能代签。
2. **`--submission` 已入 CI**:作者替换后常绿,`drafts` job 改用 `--submission --compile`;若再出现占位作者会直接红。
3. **联络对象以发送时为准**:`agentproto`/OAuth 的 chairs 列表会变;发送前以 wgchairs 页核对。
4. **模板不是法律意见**:IPR 披露的许可类型选择(RAND/RF)是贡献者的事实决定,必要时咨询法律意见。
5. **initials 渲染**:xml2rfc 把 `initials="ZY"` 渲染为 "ZY. Zeng"(自动加点),是署名者确认的选择。

---

## 30. 待确认的规范问题

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

## 31. 下一步（按顺序）

1. **IETF**:两份 draft 已提交（§29,闸门 0–7 全部完成）；剩余——两封 WG 联络 信（agentproto / OAuth,已署名,可选项）、观察 Datatracker 反馈、如需延续发 `-01`；
2. **发布**:打 tag `v0.1.0`（规范 + 参考实现 + 演示 + 一致性登记）;
3. 加入 XPC/Binder/named pipe 平台原生传输（asyncio 绑定与撤销推送通道已完成，§26、§27）；
4. **M5**：一致性登记表已建立并机械化（§28）；剩余——找 1–2 个外部实现做 C1–C2 互操作、独立安全评审、学术投稿（材料定位:本地绑定层的系统性整合,参考 §29 的在先技术分析），并在 freedesktop/GNOME/KDE 就 Linux binding 开 issue。

---

## 32. 变更记录

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
| 2026-11-18 | **PCS 公钥登记**（`73cd639`）：`KeyRegistry` 按 `kid` 登记/轮换/撤销/过期；`pcs.keys` 持久化与损坏拒绝；`AUTH_DENIED` 细分验签失败原因；新增 39 条测试，累计 496 |
| 2026-11-18 | **同意流程接入注册表**（`c035be5`）：`ConsentFlow(registry=...)` 按 `proof.kid` 验签；`publish_pcs_key()` 幂等登记；跨 signer 激活与无注册表回退；新增 13 条测试，累计 509 |
| 2026-11-18 | **私钥与回执分库**（`5419b00`）：`key_store=` 移出 `consent.pcs_key`；`ConsentFlow.verifier()` 临时 signer 不落盘；新增 7 条测试，累计 516 |
| 2026-11-18 | **私钥存储后端**（`b0068ab`）：`KeyStore` 契约与 JSON / 内存 / OS 密钥环后端；统一 `signer_of` 校验；新增 47 条测试，累计 563 |
| 2026-11-18 | **上下文事件持久化**（`7274a27`）：`ContextFabric(store=...)` 写 `context.events`；重开校验与 `limit` 保留；新增 19 条测试，累计 582 |
| 2026-11-18 | **审计保留与归档**（`1a8394d`）：`AuditLedger(max_events=...)` 移入 `audit.archive.<trace_id>`；锚点校验与 `history()`；新增 20 条测试，累计 602 |
| 2026-11-19 | **任务与副作用恢复**（`c7e990c`）：`TaskBoard` 持久化 `task.effects`；`recover()` 失败/重调度非终态任务并标记 intent-only effect 为 unknown；重放闸门与对账；新增 37 条测试，累计 639 |
| 2026-11-19 | **M4 本地打包**（`f98a6b3`）：两个 xml2rfc v3 individual draft（能力 token、同意回执）、逐节来源映射、`tools/check_drafts.py` + `requirements-drafts.txt`、Linux binding（D-Bus/portal/systemd/3 序列图）、14 条 ADR、`GOVERNANCE.md` §9.1 联络状态；CI 新增 `drafts` job 并通过（run 44461943418）；未提交 IETF |
| 2026-11-19 | **上下文对象持久化**（`3d251a6`）：`ContextFabric` 新增 `context.handles` / `context.blackboards` / `context.objects`；句柄按标识解析且未知即 `CONTEXT_NOT_FOUND`、黑板关闭清空且不晋升记忆、对象引用计数与墓碑跨重启；新增 46 条测试，累计 685 |
| 2026-11-19 | **审计按用户分区与跨 trace 顺序**（`a2c6853`）：`AuditJournal` 写 `audit.user.<user>.chain/archive.<trace>` 与 `audit.order.<user>`；链、归档与连续序号一次 `put_many`；重开交叉校验并拒绝缺口/重复/时间戳不符/孤儿条目；新增 21 条测试，累计 706 |
| 2026-11-19 | **Windows 密钥环与迁移工具**（`adba047`）：`PasswordVault` 后端（密钥走 stdin）；`KeyringError` 细分失败原因；`migrate_key_store` + `tools/migrate_pcs_key.py`；新增 14 条测试，累计 720 |
| 2026-11-19 | **并发服务事件循环**（`6656195`）：`serve_forever(mode="selector")` 单线程 `DefaultSelector` 多路复用监听与会话；断开/出错 peer 摘除后循环继续；配额仍走共享 `AdmissionController`；新增 6 条测试，累计 726 |
| 2026-11-19 | **跨进程撤销分发**（`893b357`）：`capability.revocations` 日志与撤销集原子落盘；副本 `apply_revocations(entries, source=...)` 按来源游标幂等应用；`REVOCATION_GAP` 领域扩展码；新增 17 条测试，累计 743 |
| 2026-11-19 | **恢复事务与 effect 归档**（`2609ef1`）：`TaskBoard(ledger=...)` 共享 store，`recover()` 把树/日志/审计链一次 `put_many`；`AuditLedger.append_many` 批量同事务；`max_effects` 归档已决 effect；新增 18 条测试，累计 760 |
| 2026-11-19 | **审计归档压缩与按用户导出**（`da17a2b`）：`max_archive` 锚点压缩，kept 前缀仍可端到端验证；`AuditJournal.export()` 整用户分区快照；新增 10 条测试，累计 770 |
| 2026-11-19 | **撤销订阅与跨进程测量**（`1b477f6`）：`RevocationWatcher` 轮询订阅自动应用；`benchmark_revocation.py --cross-process` 端到端传播测量；新增 4 条测试，累计 778 |
| 2026-11-19 | **asyncio 绑定**（`c32fc97`）：`serve_forever(mode="asyncio")` 缓冲分帧，半帧停滞 peer 不阻塞他人；跨线程 kqueue fd 关闭挂死修复；新增 8 条测试，累计 782 |
| 2026-11-19 | **撤销推送通道**（`c2b3f39`）：`RevocationFeedServer/Client` AF_UNIX sidecar（catch-up + 增量，非 Bus 流量）；`--cross-process --tree` 整树 cascade 测量；新增 8 条测试，累计 790 |
| 2026-11-20 | **M5 一致性登记表**:新建 `conformance/registry.md`(可复现闸门、条目格式、登记流程)与 `conformance/reports/osap-reference-2026-11-20.json`;`docs/conformance.md` §6 与 roadmap M5 同步;参考实现自证登记(64 pass / 4 manual skip) |
| 2026-11-20 | **IETF 提交前置材料包**：`drafts/submission/`（闸门检查单、§10.4 同意书模板、BCP 79 披露模板、agentproto/OAuth 联络 信草稿）；`check_drafts.py --submission` 机械闸门（占位作者强制，未入 CI） |
| 2026-11-20 | **闸门 0/3/4 完成**：贡献者名单确认为署名者本人；两份 draft 的作者替换为 Zeng Zhiyong（ZZHY, Independent, 272577337@qq.com），文档名改名为 `draft-zeng-osap-*`；`--submission` 转绿并接入 CI `drafts` job；剩余闸门 1（同意邮件确认）、2（IPR 自查）、5（chairs 联络）为真人动作 |
| 2026-11-20 | **demo 崩溃恢复与单一审计编码**（`d04c907`）：demo 第 7 节持久化运行时 + 重放闸门/对账/幂等重放/黑板不晋升；第 6 节 16 事件改由 `AuditLedger` 生成 |
| 2026-11-20 | **README 限制清单**（`fcf0485`）：根 README 中英同步更新当前状态并列出六条采用相关限制 |
| 2026-11-20 | **闸门 1/2 辅助材料**：`consent-record.md`（四条声明待署名者确认）与 `ipr-landscape.md`（领域态势：agentproto 已获章程并有 PACE 等委派 draft；第三方专利家族梳理；Macaroons 等公开在先技术）；agentproto 联络信按已获批章程的现实重写 |
| 2026-11-21 | **闸门 1、2、6 完成,两份 draft 提交 IETF**:署名者确认 §10.4 四条声明;IPR 三问自查无披露义务;作者署名与 `draft-zeng-*` 文档名就绪;两份 individual draft 上传 Datatracker——[capability tokens](https://datatracker.ietf.org/doc/draft-zeng-osap-capability-tokens-00/)、[consent receipts](https://datatracker.ietf.org/doc/draft-zeng-osap-consent-receipts-00/)（2027-05-25 过期）;剩余:两封 WG 联络 信（署名待发,可选项） |
| 2026-11-21 | **v0.1.0 发布**:打 tag `v0.1.0`(M0–M4 + M5 登记表;两份 draft 已在 IETF Datatracker);CHANGELOG 转 `[0.1.0] - 2026-11-21`,README 版本行更新 |
| 2026-11-24 | **第二次规范↔实现审计**：发现四个信封合法但零路径的机制——§7.2 `describe`、§7.5 `stream.*`、§7.4 事件订阅、§7.1 `refs` 发送方校验（MUST）——全部列入 roadmap §4 的 0.2 冻结表并写入两侧 README 限制清单；缓解：接收方句柄解析仍过 CF 授权。修复后的 `status` 进度路径经复核无同类缺口 |
| 2026-11-24 | **0.2 第 1 批实现**:`describe`(Registry.describe + Bus(describe_service/clock) 路由,21 条测试)与 §7.1 `refs` 发送方校验(ContextFabric.authorize_refs 复用 §9.2 检查序列 + Bus(refs_authorizer) fail closed,8 条测试);`obj://` 归属模型仍缺(limitation #25);累计 822 tests |
| 2026-11-20 | **闸门 1 完成**:署名者确认 §10.4 四条声明(BCP 78 授权、Simplified BSD、IETF Trust 处分、IPR 义务知悉);记录于 `drafts/submission/consent-record.md`,DCO 签名提交固化 |
| 2026-11-20 | **闸门 2 完成**:IPR 三问自查——个人无相关专利/申请、雇主组合与本领域无关、无已知未授权使用;**无披露义务**,结论与检索记录见 `drafts/submission/ipr-landscape.md` §1/§3 |
| 2026-11-21 | **闸门 6 就绪**:两份 draft `<date>` 更新为实际上传日 2026-11-21;`--submission --compile` 38 checks 与全量复核通过,待署名者在 Datatracker 上传 |
| 2026-11-21 | **进度上报接线**(`126956e`):`TaskBoard.report_progress` 合账 `consumed`(单调、仅 assignee、终态拒绝)+ `Bus(progress_board=...)` 路由单向 `status`(无回复帧);demo 第 4 节演示;11 条新测试,累计 801 |
