# IPR 检索记录(闸门 2 辅助材料)

> 用途:`drafts/submission/ipr-disclosure-template.md` 的配套检索记录。检索日期 2026-11-20,检索人:维护者(非法律意见)。
> **义务边界(RFC 8179)**:BCP 79 的披露义务只针对**你自己(或你的雇主)持有的、你认为对规范实现可能有必要权利要求的专利/申请**。第三方专利不由贡献者披露——由 IETF 流程与其他持有人处理。因此本记录的结论是"自查清单 + 领域态势",不是自由实施(FTO)分析。

---

## 1. 自查清单(必须由署名者逐条回答)

| 问题 | 答案 |
|---|---|
| 你个人名下是否有与这两份 draft 内容相关的专利或专利申请? | 待署名者确认 |
| 你的雇主(如有)是否有此类专利/申请,且你参与起草可能触发披露义务? | 待署名者确认(个人独立开发且无相关雇主权利要求时,通常为"否") |
| 你是否在知情的情况下使用了他人的专利技术且未被许可? | 待署名者确认 |

**任一为"是" → 填写 [ipr-disclosure-template.md](ipr-disclosure-template.md) 并在 Datatracker 提交;全部为"否" → 无需披露,联络信与 WG 交流中据实说明即可。**

---

## 2. 领域态势(检索所见,按相关度)

### 2.1 直接同域的 IETF 活动

- **agentproto(AG)已于 2026-10 获 IESG 批准章程**(IETF 126 Vienna BoF,IETF 127 有正式会);组内已有委派/授权类 draft:`draft-nandakumar-agentproto-pace-authz`(PACE 授权:委派与动作批准)、`draft-watts-agent-authority-transition-receipts`(权限转移回执)、`draft-le-agent-passport`(Agent 护照与委派回执)、`draft-marques-asqav-compliance-receipts`(签名动作回执合规档)。
- **WIMSE 侧**:`draft-atakora-wimse-sadp-delegation-00`——"Capability-Bound Delegation Chains with Scoped Context Disclosure for AI Agents",明确沿用 Macaroons 的 caveat 衰减传统,并自称 authority 沿链单调递减。与 Draft A 的十条衰减规则**同域不同机制**(该稿用加密 task capsule + HMAC caveats;OSAP 用 Ed25519 签名 + 结构化约束 + 本地任务绑定)。
- **既有 IPR 披露**:datatracker #7500(11 AI Blockchain trust,US19/454392 未公开申请,"AI-governed medical data storage / audit / content-addressed persistence",许可选择 **RF(b)**)——与我们的内容寻址引用(obj://sha256)与审计持久化概念相邻,但其权利要求聚焦医疗数据硬件加速存储;Ben Le 关于 `draft-le-agent-passport` 的披露(#7669)针对他人 draft。

### 2.2 第三方专利(公开检索所见,仅供参考,非义务披露对象)

| 专利/申请 | 与 OSAP 的概念交叠 | 差异点 |
|---|---|---|
| US11595215B1(macaroons-with-caveats 委派授权,IoT) | caveat 式衰减委派 | OSAP 是 Ed25519 签名凭证 + 结构化约束 + 任务/受众绑定,非 HMAC caveat 链;场景是单机本地会话 |
| "Trust root system for verification of user consents" 家族(WO2022204143A1、US20220300645A1、US20250390871A1/72A1) | 数字签名的同意请求存为 consent receipt | OSAP 的回执绑定 `cap_id` 预约顺序(先预约后授权)、与能力签发耦合、本地单设备;该家族是跨实体中心化信任根服务 |
| WO2026154461A2(防"数据目的洗白":硬件根 pre-effectuation finality + consent receipt + capability release) | "执行前先记 intent + 凭证 + 回执"的组合 | OSAP 无硬件根要求、无 sealed TEE 状态;但这是**概念上最接近**的一篇,起草 agentproto 相关讨论时应知悉 |
| US20190012751A1 等 consent documentation 系统 | 电子同意记录 | 通用文档系统,机制不同 |

### 2.3 公开在先技术(有利证据)

- **Macaroons**(Birgisson et al. 2014,学术公开):holder attenuation + caveats 是公开在先的完整机制;
- CAPMAS(arXiv 2609.06500)、AIP(arXiv 2603.24775)等 2026 年多方公开论文均以 attenuation-only 委派为前提;
- ISO/IEC 27560 与 Kantara consent receipt 是公开标准脉络。

**含义**:衰减式委派与同意回执的核心思想有充分的公开在先技术——既降低"我们独立设计撞上他人私有权利要求"的概率,也说明 OSAP 的贡献在于**本地绑定与任务级授权的系统性整合**,而非单个原语的"新颖性"(学术投稿时按此定位)。

---

## 3. 结论模板(署名者确认后填入)

> 截至 2026-11-XX,本人(Zeng Zhiyong)确认:本人名下无与 `draft-zeng-osap-capability-tokens`、`draft-zeng-osap-consent-receipts` 内容相关的专利或专利申请;本人无雇主权利要求涉及该内容;无需按 RFC 8179 提交披露。若日后出现相关权利,将按 BCP 79 及时披露。
