# OSAP — Open System Agent Protocol

[![ci](https://github.com/takethegame/open-system-agent-protocol/actions/workflows/ci.yml/badge.svg)](https://github.com/takethegame/open-system-agent-protocol/actions/workflows/ci.yml)

> English version: [README.en.md](README.en.md)

> **本地优先的开放标准：跨应用 Agent 点对点协作、能力注册表联邦、任务级授权。**
>
> 版本：**0.1.0**（tag 于 2026-11-21）· 0.1 Draft 已提交 IETF（两份 individual draft）· M0–M4 完成，M5 进行中

---

## 这是什么

OSAP 定义一套运行在操作系统本地会话中的 Agent 互操作协议。它让不同 App 所承载的 Agent 能够：

- **点对点协作**：发现彼此、建立会话、委派任务、交换结果；
- **联邦能力注册表**：把 Apple App Intents、Android AppFunctions、Windows App Actions，以及 MCP、A2A、D-Bus、OpenAPI 的能力投影为统一能力图；
- **任务级授权**：用可验证、可衰减、可撤销的能力凭证，替代粗粒度 App 权限。

OSAP 不替代 MCP、A2A、D-Bus 或厂商原生能力框架。它补的是这些机制之间的**本地互操作与治理层**：统一身份、统一发现、统一授权、统一上下文引用、统一审计。

---

## 三个支柱

### 1. 跨应用 Agent 点对点协作

- 本地 Agent Bus 路由请求、结果、事件、流与取消。
- 支持 **Supervisor/Worker** 层级委派，也支持 **Peer** 平级会话。
- 任务树、预算、截止时间、取消级联、结果聚合。

### 2. 厂商能力注册表联邦

- App 清单声明能力；Registry Federation Service 建立统一能力记录。
- Bridge 适配 App Intents / AppFunctions / App Actions / MCP / A2A / D-Bus / OpenAPI。
- 保留 `source`、`native_id`、`trust`、`provenance`；原生注册表仍是权威。

### 3. 任务级授权

- 能力凭证绑定 `subject`、`audience`、`task_id`、资源、动作、时间与预算。
- 权限只能沿委派链收窄；禁止凭证转发；撤销级联。
- L3/L4 动作要求用户同意回执；全链路审计与 trace。

---

## 为什么需要它

2026 年的现状是：

- OS 厂商已经做了“系统 Agent → App 能力”的星型注册表（App Intents / AppFunctions / App Actions），但第三方 App 的 Agent 不能平等参与。
- MCP / A2A 解决了工具调用与跨网络 Agent 协作，但不是 OS 本地、也没有 OS 对端身份与任务级授权。
- 研究界已经提出 OS 级 Agent 安全架构，但尚未形成跨厂商、可实现的本地互操作标准。

OSAP 的目标不是“再发明一个 Agent 协议”，而是定义 **本地绑定 / profile**：把上述能力接起来，并补上跨应用场景缺失的身份、授权、上下文与审计。

更详细的定位与先行工作见 [`docs/prior-art.md`](docs/prior-art.md)。

---

## 文档

| 文档 | 内容 |
|---|---|
| [`docs/standard.md`](docs/standard.md) | **规范性草案**：架构、身份、能力、联邦、消息、任务、上下文、同意、审计、一致性 |
| [`docs/conformance.md`](docs/conformance.md) | 一致性等级、测试用例、互操作矩阵、报告格式 |
| [`docs/prior-art.md`](docs/prior-art.md) | 先行工作、对比矩阵、可能的新颖点与可证伪主张 |
| [`docs/design-draft.md`](docs/design-draft.md) | 早期设计说明（非规范性，保留背景与取舍） |
| [`GOVERNANCE.md`](GOVERNANCE.md) | 版本、变更、角色、安全披露、外部标准联络 |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | 贡献流程、DCO、内容规范 |
| [`docs/roadmap.md`](docs/roadmap.md) | 0.1 → 0.2 里程碑、退出标准、风险登记与决策闸门（工作文档） |
| [`docs/progress.md`](docs/progress.md) | 已完成里程碑、验证证据、剩余用例逐条拆分（工作记录） |
| [`drafts/README.md`](drafts/README.md) | 两个 IETF individual draft 的来源映射、构建与发布前置条件（工作文档） |
| [`bindings/linux/profile.md`](bindings/linux/profile.md) | Linux D-Bus/portal/`systemd --user` 绑定 profile（0.1 Draft） |
| [`decisions/README.md`](decisions/README.md) | §15 开放问题的 ADR 索引（非规范性，暂定结论） |
| [`spec/formal/README.md`](spec/formal/README.md) | TLA+ 不变量模型、TLC 结果、模型边界（M3 工作记录） |
| [`SECURITY.md`](SECURITY.md) | 漏洞披露渠道、时限、安全评审触发条件 |
| [`CHANGELOG.md`](CHANGELOG.md) | 版本变更记录 |

---

## 仓库结构

```
docs/                 规范、一致性、先行工作、设计说明、路线图
drafts/               IETF xml2rfc v3 individual drafts 与来源映射
bindings/             平台绑定 profile（Linux D-Bus/portal/systemd）
decisions/            §15 开放问题的 ADR
schemas/              JSON Schema（信封、能力、任务、清单、能力记录、回执、审计、payload）
conformance/          机器可读一致性用例、用例 schema、运行报告 schema、登记表(registry.md)
examples/             示例消息与对象
tools/                校验脚本（示例、schema、文档、draft、一致性）
.github/workflows/    CI
GOVERNANCE.md         治理草案
CONTRIBUTING.md       贡献流程与 DCO
SECURITY.md           安全披露
CHANGELOG.md          版本变更记录
requirements.txt      Python 依赖
requirements-drafts.txt  IETF draft 工具链（xml2rfc）
LICENSE               Apache-2.0
NOTICE                版权与商标说明
README.md             本文件
```

英文平行版本使用同名 `*.en.md` 文件，与中文原文并列存放。

---

## 快速校验

```bash
python3 -m pip install -r requirements.txt
python3 tools/check_schemas.py     # schema 元校验与 $id 唯一性
python3 tools/validate_examples.py # 示例与跨文档校验
python3 tools/check_docs.py        # JSON 块、断链、中英结构一致性
python3 tools/conformance_run.py --stub  # 一致性用例格式
python3 demo/run_demo.py           # 三 Agent 端到端演示
python3 tools/benchmark_revocation.py  # 撤销传播 P95（本地基准，不在 CI）
```

以上命令除基准外都在 CI 中运行；依赖见 `requirements.txt`（Python 3.9+）。

---

## 当前状态

- **规范**：0.1 讨论稿，核心机制已定义，开放问题见规范第 15 节。
- **信任边界**：Bus Core 是最小 TCB；RFS/CA/PCS/CF/AL 为独立服务。0.1 的 Bus 可读取 payload，这是显式信任假设；不信任 Bus 的 P1 加密 profile 列入 0.2。
- **状态语义**：任务树、幂等索引、撤销列表、审计链头必须持久化并支持崩溃恢复。Bus 状态不是记忆：长期语义记忆由 Agent 或独立 memory 服务持有，必须单独授权（见 `docs/standard.md` §3.7、§9.3）。
- **实现**：Python 参考实现位于 `impl/`（M0–M4 完成，790 个单元测试，撤销 P95 1.23 ms）；`demo/` 提供三 Agent 演示，含崩溃恢复（第 7 节）。
- **一致性**：C0–C7 等级与 68 条用例全部可执行；`conformance/registry.md` 登记已复核的报告，参考实现自证 64 pass / 4 manual skip。
- **标准归属**：未定；建议作为本地 profile 与 IETF `agentproto` 相关讨论、OAuth WIMSE、AAIF/LF 生态对齐（是否成立工作组以 IETF 官方为准）。
- **许可**：Apache-2.0（规范、schema、示例、工具统一）；贡献使用 DCO 1.1。

## 当前限制(发布前须知)

完整的 22 条限制清单见 [`impl/README.md`](impl/README.md) 第 6 节；直接影响采用决策的有：

1. **能力凭证 `proof` 未验签**：token 做结构校验与签名占位，CA 密钥分发未定——凭证的密码学完整性仍待补(PCS 回执已验签，不受影响)。
2. **`max_uses` 未计数**：衰减时比较上限，但使用次数不落账，同一凭证可重复使用。
3. **持久层是单写者 JSON**：一个 store 文件一个进程写；无多写者协调、TTL 清理或压缩。
4. **撤销分发需显式接线**：日志/拉订阅/推送通道已实现，但签发方必须显式 `notify()`,跨设备传播不在 0.1。
5. **C2-05、C4-01、C6-08、C7-01 仍是 manual**:跨 App 同意 UI、原生注册表 TTL、跨进程恢复的真实集成未自动化。
6. **两份 IETF draft 已提交（2026-11-21）**：`draft-zeng-osap-capability-tokens-00` 与 `draft-zeng-osap-consent-receipts-00` 在 [Datatracker](https://datatracker.ietf.org/drafts/current/) 公开（2027-05-25 过期）；剩余动作是两封 WG 联络 信（agentproto / OAuth，已署名待发），归属以 chairs 回复为准。
7. **四个规范机制中三个已实现,事件订阅仍缺（列入 0.2）**：§7.2 `describe`、§7.1 "`refs` 句柄由发送方有权传递" 校验与 §7.5 `stream.*` 流式传输已于 2026-11-24 实现（`Registry.describe`、`ContextFabric.authorize_refs`、`StreamRegistry`,见 roadmap §4);§7.4 事件订阅仍零路径。缓解：接收方用句柄时仍过 CF 授权解析;`obj://` 归属模型未建。

---

## 参与方式

欢迎针对以下方向提交 issue / 提案 / 实现报告：

1. 两个示例 App + 一个 Bus 的最小原型；
2. App Intents / AppFunctions / App Actions 的 Bridge 适配；
3. 能力衰减、撤销、审计链的形式化与测试；
4. 提示注入与数据出口的对抗性测试；
5. 与 MCP / A2A / IETF 草案的互操作映射。

治理与提案流程见 [`GOVERNANCE.md`](GOVERNANCE.md)。

---

## 许可

本仓库统一使用 [Apache License 2.0](LICENSE)：规范文本、JSON Schema、示例与工具均以同一许可发布。

- 允许商业使用、修改、再分发与私有部署；
- 包含专利授权（Apache-2.0 §3）与商标条款（Apache-2.0 §6）；
- 与 GPLv3 兼容，不与 GPLv2 兼容；
- 贡献使用 [DCO 1.1](https://developercertificate.org/)，提交需带 `Signed-off-by`。

“OSAP” 名称与一致性标记的使用规则见 [`GOVERNANCE.md`](GOVERNANCE.md) §10。

---

## 非目标

- 不规定 Agent 的内部推理、模型或提示词。
- 不替代 MCP / A2A / D-Bus / 厂商原生能力框架。
- 不定义跨设备、跨组织、跨用户的联邦信任根（后续版本）。
- 不提供内核级隔离；OSAP 运行在现有 OS 沙箱与 IPC 之上。
