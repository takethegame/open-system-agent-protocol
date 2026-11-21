# OSAP IETF 草案打包

> 状态：本地 individual draft 骨架（0.1 Draft）· 2026-11-19
> 规范性来源：[`docs/standard.md`](../docs/standard.md)
> 规划：[`docs/roadmap.md`](../docs/roadmap.md) §M4
> 治理：[`GOVERNANCE.md`](../GOVERNANCE.md) §9、§10.4

本目录把 OSAP 0.1 中**可以独立成文**的两部分拆成 IETF individual draft，并用一个独立的 Linux binding profile 与一组 ADR 补齐 M4 的打包产出。

**当前状态不是 IETF 提交。** 两个 XML 文件是 `xml2rfc` v3 骨架，文档名为 `-00`，用于内部评审与外部预读；在完成 WG 归属确认与实际上传之前，不得提交到 IETF Datatracker（§10.4 同意与 IPR 自查已于 2026-11-20 完成，记录见 `submission/consent-record.md` 与 `submission/ipr-landscape.md`）。

---

## 1. 文件

| 文件 | 内容 | IETF 状态 |
|---|---|---|
| `draft-zeng-osap-capability-tokens-00.xml` | Draft A：`Capability Tokens for Local Agent Delegation` | individual draft，上传日 2026-11-21；作者 Zeng Zhiyong |
| `draft-zeng-osap-consent-receipts-00.xml` | Draft B：`Consent Receipt Binding for Task-Scoped Authorization` | individual draft，上传日 2026-11-21；作者 Zeng Zhiyong |
| `README.md` | 本文件：来源映射、构建、边界与发布检查 | 非规范性 |

两个 draft 都是英文，正文不引用 `standard.md`、本仓库路径或未发布文档；外部读者只看单个 draft 即可理解其范围。中文原文仍是规范性的最终来源；draft 与 `standard.md` 冲突时以 `standard.md` 为准。

---

## 2. 构建与检查

```bash
python3 -m pip install -r requirements-drafts.txt
python3 tools/check_drafts.py --compile
```

`tools/check_drafts.py` 的静态检查不依赖 `xml2rfc`，会验证：

- XML 可解析、根元素为 `rfc` 且 `version="3"`；
- `docName` 与文件名一致，front matter 完整；
- `anchor` 唯一，内部 `xref` 全部可解析；
- 每个 `reference` 都被引用，`seriesInfo` 不在 `<front>` 内；
- 每个 `sourcecode type="json"` 块可解析；
- 没有占位符、个人标识、本地路径、`docs/` 等未发布引用；
- 文件为 ASCII（IETF 正文可读性）。

`--compile` 额外调用 `xml2rfc` 生成 `build/drafts/*.txt` 与 `*.html`，用于满足 M4 的退出标准。`build/` 已加入 `.gitignore`，不提交生成物。

---

## 3. Draft A 来源映射

Draft A 只写 token 格式、衰减、绑定、撤销与同意前置，不写总线、发现或任务状态机。

| Draft A 小节 | `standard.md` 来源 | 说明 |
|---|---|---|
| 1 Introduction / 1.1 Scope | §1、§5 | 把能力模型从 umbrella 文档中抽出 |
| 1.2 Relation to Other Work | §1.3、§13 | 与 OAuth / WIMSE 的边界 |
| 2 Capability Model Overview | §5.1、§5.2 | descriptor 不等于授权 |
| 3.1 Top-Level Members | §5.2 | 字段表逐项对应 |
| 3.2 Constraints | §5.2、§5.3、§5.4 | `max_depth` 取绝对深度，与实现一致 |
| 3.3 Example Token | §5.2 | 示例改为独立、可读的 token |
| 3.4 Serialization and Canonicalization | §5.2、§11.2 | 显式化“签名对象”的规范化细节 |
| 3.5 Proof | §4.5、§5.2 | Ed25519 与 `kid` |
| 4 Attenuation | §5.3 | 10 条规则逐条对应 |
| 4.2 Stateless and Stateful Checks | §5.3、§5.4 | Bus 只做无状态绑定校验 |
| 5 Binding | §5.4 | audience / task / sender / session / nonce |
| 5.5 Delegation and Handoff | §5.4、§8.5、§8.9 | 两类 task 绑定例外 |
| 6 Revocation | §5.5、§10.7 | 级联、缓存、执行前检查、审计 |
| 7 Authority Invariants | §5.6 | AI1–AI10 原样保留 |
| 8 Risk Classes and Consent Linkage | §5.7、§5.8、§10.4 | L0–L4 与回执覆盖 |
| 9 Error Codes | §7.7 | 只列 token 相关子集 |
| 10 Security Considerations | §11 | 补充 canonicalization、密钥轮换、本地传输假设 |
| 11 Privacy Considerations | §11.5、§8 | 标识符最小化与审计保留 |

**编辑性澄清（不改变协议语义）**：

- `rate` 的 `<count>/<unit>` 语法来自 §5.2 的示例 `"5/min"`；draft 明确单位集合，但不规定具体限流算法。
- `max_depth` 明确为“绝对深度”而非“还能再委派几层”，与 §5.3 的 `depth = parent + 1` 及参考实现一致。
- canonicalization 明确为“去 `proof`、键排序、最小分隔符、整数 only”，与参考实现的签名口径一致；它不是完整的 RFC 8785 实现，draft 已注明。
- `time_window` 与 `nbf`/`exp` 同时存在时取交集；这是对 §5.2 两个字段的唯一安全解释。

---

## 4. Draft B 来源映射

Draft B 只写同意请求、回执、签发顺序、审计与 27560 映射，不写 UI 或传输。

| Draft B 小节 | `standard.md` 来源 | 说明 |
|---|---|---|
| 1 Introduction / 1.1 Scope | §10.1–§10.5 | 从同意与审计章节抽取 |
| 2 Consent Model | §5.7、§10.1、§10.3 | 风险等级、任务范围、同意疲劳 |
| 3 Consent Request | §10.2 | 字段、intent preview、options |
| 3.3 Options | §10.3 | `allow_once` / `allow_task` / `deny` |
| 4.1 Grant / 4.2 Deny | §10.3 | 回执与拒绝的返回结构 |
| 4.3 Reservation Protocol | §10.3 | 5 步签发顺序，`cap_id` 预约不可用 |
| 4.4 Revocation | §10.7 | 回执撤销级联到能力 |
| 5 Consent Receipt | §10.4 | 字段表与签名 |
| 5.3 Canonicalization and Proof | §10.4、§11.2 | 去 `proof` 的规范化签名 |
| 5.4 Validation Order | §10.4、§5.8 | 先验签，再判 decision / expiry / scope |
| 5.6 Offline Verification | §10.4、§10.6 | 离线可验证与其限制 |
| 6 Binding to Capability Tokens | §5.8、§10.3 | task / audience / actions / resources 覆盖 |
| 7 Audit and Trace | §10.5、§10.6、§8.11 | 事件字段、两段审计、哈希链、脱敏 |
| 8 ISO/IEC 27560 Mapping | §10.4、§14 | 信息性映射，不声称 ISO 一致性 |
| 9 Security Considerations | §11.1、§10.7 | 伪造、钓鱼、重放、预约竞争、审计完整性 |
| 10 Privacy Considerations | §11.5、§8 | 数据最小化与保留 |

**编辑性澄清（不改变协议语义）**：

- 回执校验顺序写成“语法 → 签名 → decision → expiry → scope → uses”，与参考实现“`activate` 先验签再查预约”一致；`standard.md` 未规定顺序，因此这是实现建议而非新增 MUST。
- `policy_hash` 在 §10.4 示例中已存在；draft 只说明它是对用户所见策略/通知的承诺，不要求嵌入全文。
- 27560 映射是信息性的；`standard.md` §14 只要求与外部标准对齐，没有声称 ISO 一致性。

---

## 5. 不在 draft 中的内容

以下内容留在 `standard.md` 或后续文档，避免 draft 变成新的 umbrella：

- 消息信封、传输绑定、分帧、握手、幂等、deadline；
- 发现、注册表联邦、App manifest 与 capability record；
- 任务对象、任务树、预算、取消、handoff 状态机；
- Context Fabric 句柄、标签、黑板、对象存储；
- 平台原生绑定（Linux D-Bus、macOS XPC、Windows named pipe、Android Binder）；
- 一致性与测试编号（仍以 [`docs/conformance.md`](../docs/conformance.md) 为唯一来源）。

Linux 绑定单独写在 [`bindings/linux/profile.md`](../bindings/linux/profile.md)；ADR 写在 [`decisions/`](../decisions/README.md)。

---

## 6. 发布前检查

在把任一 draft 提交到 IETF 之前，必须完成：

> 逐项的操作指引、同意书 / IPR 披露 / 联络信模板见 [`submission/checklist.md`](submission/checklist.md)——那是准备材料包，不构成本仓库的任何提交动作。

1. **贡献者同意**：✅ 已完成（2026-11-20）——唯一贡献者（即署名者本人）确认四条声明，记录见 [`submission/consent-record.md`](submission/consent-record.md)；
2. **IPR 披露**：✅ 无披露义务（2026-11-20）——三问自查均为"否/无已知情况"，检索记录与结论见 [`submission/ipr-landscape.md`](submission/ipr-landscape.md)；
3. **提交人**：✅ 已完成(2026-11-20)——Author/Editor 为 Zeng Zhiyong(ZZHY Zeng)，`tools/check_drafts.py --submission` 已转绿；
4. **文档名**：✅ 已完成(2026-11-20)——individual submission 按第一作者姓氏命名为 `draft-zeng-osap-capability-tokens-00` / `draft-zeng-osap-consent-receipts-00`；被 WG 采用后由 WG 重命名；
5. **WG 归属**：确认 `agentproto` 或 OAuth WG 的采用意向；未被采用时保持 individual draft；
6. **外部引用**：把当前内联的 RFC 引用替换为 `xml2rfc` 的 bibxml 或确认内联引用仍可编译；
7. **一致性**：重新跑 `tools/check_drafts.py --compile`、`tools/check_docs.py` 与全量测试。

其中第 3、4 项有机械闸门：`python3 tools/check_drafts.py --submission`（占位作者、作者联系方式检查）。它已在作者替换与改名后转绿，并接入 CI 的 `drafts` job；后续若再出现占位作者会直接红。

`ipr="trust200902"` 仍是 IETF 文档模板的默认值；BCP 79 披露义务取决于署名者的专利事实（见 `submission/ipr-disclosure-template.md`），与该属性无关。

---

## 7. 已知边界

- 两个 draft 是 **individual** 文档，不是 WG 采用稿，也不代表 IETF 背书。
- 作者信息是真实的（Zeng Zhiyong / 272577337@qq.com）；邮箱会随 draft 公开发布。
- Draft A 不定义 token 的传输编码；它假设调用方已经有一个经过认证的本地通道。
- Draft B 不定义同意 UI；它只定义请求、回执与审计的数据形状。
- 27560 映射是信息性的，未做逐字段的 ISO 符合性测试。
- 没有 IANA media type 或注册表动作；如果后续需要 `application/osap-*+json`，必须另开提案。
- 两个 draft 不覆盖跨设备、跨组织或多用户共享会话；这些在 `docs/standard.md` §15 与 ADR 中讨论。
