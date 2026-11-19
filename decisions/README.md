# OSAP 架构决策记录（ADR）

> 状态：工作记录（非规范性）· 2026-11-19
> 来源：[`docs/standard.md`](../docs/standard.md) §15 的 14 个开放问题
> 规划：[`docs/roadmap.md`](../docs/roadmap.md) §M4

本目录把 0.1 草案中的开放问题逐条写成可追踪的架构决策记录。每条 ADR 给出：

1. **背景**：问题是什么，为什么现在需要暂定结论；
2. **暂定结论**：0.1 的实现与文档应采用什么立场；
3. **后果**：接受该结论后必须承担的代价与限制；
4. **备选方案**：被否决或暂缓的路径；
5. **重审触发条件**：出现什么证据时必须重新打开决策。

ADR **不是规范性文本**。它与 `docs/standard.md` 冲突时，以 `standard.md` 为准；ADR 只解释取舍、记录边界与重审条件。任何改变协议语义的结论仍须走 [`GOVERNANCE.md`](../GOVERNANCE.md) §3 的提案流程。

---

## 索引

| 编号 | 标题 | 暂定结论（摘要） | 重审触发条件 |
|---|---|---|---|
| [0001](0001-bus-ownership.md) | Bus 的所有权 | 不强制单一所有者；每用户 Bus Core，优先 OS/桌面环境，独立守护进程可作为 Linux 参考；所有权不附带策略/签发权 | 平台原生 Bus 落地、多厂商治理机构成立、出现策略俘获 |
| [0002](0002-legacy-apps-without-agents.md) | 无 Agent 的旧应用 | 优先轻量适配器/SDK；UI 自动化只作兜底，按高风险处理，不得绕过 OS 权限 | 平台提供 App Intents/AppFunctions/App Actions；无障碍场景只剩 UI 自动化 |
| [0003](0003-cross-device-trust-roots.md) | 跨设备/跨组织信任根 | 0.1 只管本地；跨设备映射到 WIMSE/SPIFFE 与 A2A，不自建 PKI | WIMSE/SPIFFE profile 稳定、A2A 扩展落地、首个跨设备实现 |
| [0004](0004-multi-user-shared-sessions.md) | 多用户共享会话 | 每用户一个 Bus；主体切换必须新会话/新能力；不做跨用户总线 | 远程桌面/多 seat、企业共享设备、OS 提供 per-app 用户上下文 |
| [0005](0005-consent-fatigue.md) | 同意疲劳 | 按风险分级：L3 每次或有界任务级，L4 强确认；批量同意必须显式范围 | 用户研究显示疲劳、L3 事故、监管指引变化 |
| [0006](0006-semantic-discovery.md) | 语义发现 | 结构化匹配优先；embedding 本地、可选、可解释，不上传原始能力文本 | 本地 embedding 模型、隐私检索方案、外部注册表要求语义搜索 |
| [0007](0007-prompt-injection-responsibility.md) | 提示注入责任 | 分层责任：协议做来源/信任/动作闸门，App 做内容防护，模型层做指令层级 | 注入基准发布、新攻击类、平台提供指令来源 |
| [0008](0008-policy-evaluation-performance.md) | 策略求值性能 | 短期缓存/租约；L3/L4 仍做撤销检查；过期即拒绝 | p95 超预算、策略引擎更换、跨设备策略 |
| [0009](0009-vendor-adapter-adoption.md) | 厂商适配器采用 | 开放适配器规范 + 一致性；不设厂商特权；保留原生 ID 与信任 | 厂商 SDK 内置适配器、出现不兼容扩展、治理变化 |
| [0010](0010-standards-home.md) | 标准归属 | 先做中立开源项目；IETF individual draft 管 wire format；不急于绑定单一基金会 | ≥2 个外部实现、IETF WG 采用、基金会正式邀请 |
| [0011](0011-p1-opaque-bus.md) | P1 不可见 payload | 0.1 只承诺 P0；P1 延到 0.2；候选 HPKE + 每消息临时密钥 | HPKE profile 稳定、元数据分析完成、0.2 范围冻结 |
| [0012](0012-recovery-formal-model.md) | 崩溃恢复与对账模型 | intent/outcome/unknown 三态；不自动重放；不声称 exactly-once | 自动对账、跨子系统事务、effect TTL/归档 |
| [0013](0013-context-fabric-os-mapping.md) | Context Fabric 与 OS 映射 | CF 是授权/句柄解析层，不是文件系统；portal 结果是句柄不是能力 | portal API 变化、新 OS 句柄类型、跨平台抽象 |
| [0014](0014-multi-instance-bus.md) | 多实例 Bus | 0.1 每用户一个 Bus；不做 leader election；按用户/会话分区 | 多实例部署、跨 trace 审计需求、OS 服务管理器支持 |

---

## 约定

- 文件名：`NNNN-kebab-case-title.md`，编号一旦分配不复用。
- 状态：`Provisional`（默认）、`Accepted`、`Superseded`、`Rejected`。
- 日期：决策记录首次落盘日期；重审时追加“重审记录”，不覆盖原文。
- 关联：每条 ADR 必须链接回 `standard.md` §15 的编号，以及相关实现/测试/文档。
- 变更：推翻一条 ADR 时新建编号并在旧条目写 `Superseded by NNNN`，不要静默改写历史。
