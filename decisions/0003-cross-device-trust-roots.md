# ADR-0003: 跨设备/跨组织信任根

- 状态：Provisional
- 日期：2026-11-19
- 关联：`docs/standard.md` §15.3、§4.7、§6.5；`docs/roadmap.md` §M4

## 背景

0.1 只承诺单设备、单用户会话。用户一旦把任务扩展到手机、另一台电脑、企业服务或另一个组织的 Agent，就需要回答：本地 `agent://` 身份如何映射到远端身份？用户密钥、设备密钥、工作负载身份之间是什么关系？A2A、WIMSE、SPIFFE 已经覆盖一部分问题，OSAP 不应自建一套平行 PKI。

## 暂定结论

1. **0.1 不外推本地信任根**。本地能力 token 的 `issuer`/`subject`/`audience` 只在同一设备、同一用户会话内有意义；跨设备 MUST 显式声明并经过桥接。
2. **映射而非替代**：
   - 本地 Agent 身份映射到 WIMSE/SPIFFE 工作负载身份时，保留 `agent://` 作为显示与审计标识，另存远端身份引用；
   - 远程任务交换使用 A2A 的任务/消息语义，OSAP 只提供本地能力与同意证据；
   - 需要 OAuth 时，用 Token Exchange（RFC 8693）把本地能力换成远端 access token，并保持 audience/task 收窄。
3. **不自建跨域 PKI**：0.1/0.2 不定义新的证书层级、根 CA 或跨组织信任列表。跨域信任根 MUST 由现有 OS、企业 MDM、SPIFFE/WIMSE 或明确的双边协议提供。
4. **显式信任声明**：跨设备消息 MUST 带来源、信任级别与设备绑定；`origin.kind=external` 的默认 `trust=unverified`。本地策略可以把外部身份提升到 `verified`，但 MUST 记录依据。
5. **失败关闭**：无法验证远端身份、设备绑定或撤销状态时，L3/L4 动作 MUST 拒绝；不得用“本地曾授权”代替远端校验。

## 后果

- 0.1 的跨设备能力有限；需要桥接器或网关。
- 本地审计与远端审计需要关联 ID（`trace_id`、`task_id`），但不能假设两边链可直接拼接。
- 企业部署可以复用 MDM/SPIFFE，而不是学习一套 OSAP 专属 PKI。
- 需要定义“本地能力 → 远端凭证”的衰减规则，避免换汇时扩大权限。

## 备选方案

- **OSAP 自建跨域 PKI**：控制力最强，但与 WIMSE/SPIFFE 重复，采用成本高，且容易形成单点信任。
- **只支持单设备**：最简单，但无法满足多设备用户的真实任务。
- **完全依赖 A2A**：远程语义够用，但本地能力、同意回执与审计证据没有对应物。
- **完全依赖 OAuth**：适合 HTTP 服务，不适合本地 IPC 与任务树。

## 重审触发条件

1. WIMSE 或 SPIFFE 发布稳定的 Agent/工作负载身份 profile，可直接承载 `agent://` 映射；
2. A2A 增加本地能力或同意证据的扩展；
3. 出现首个真实的跨设备 OSAP 实现或企业部署；
4. 监管要求跨组织同意回执可移植，现有映射无法满足。

## 参考

- [`docs/standard.md`](../docs/standard.md) §4.7（命名权威）、§6.5（外部信任）、§15.3
- [`docs/prior-art.md`](../docs/prior-art.md)（WIMSE、SPIFFE、A2A）
- [`impl/osap/federation.py`](../impl/osap/federation.py)（外部信任归一）
