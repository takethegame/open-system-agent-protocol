# ADR-0011: P1 不可见 payload

- 状态：Provisional
- 日期：2026-11-19
- 关联：`docs/standard.md` §15.11、§2.4、§11.3；`docs/roadmap.md` §4

## 背景

0.1 的 P0 信任 profile 假设 Bus 与本地传输可见 payload；它依赖 OS 的进程隔离、对端认证与审计，而不是端到端加密。高价值场景（支付、密钥、企业数据）希望 Bus 也看不到 payload。P1 需要定义 HPKE wire format、密钥发现、前向保密与元数据保护。

## 暂定结论

1. **0.1 只承诺 P0**：实现 MUST NOT 声称支持 P1；P1 的 wire format 列入 0.2 范围，当前不定义字段。
2. **候选密码套件**：HPKE（RFC 9180）的 X25519/HKDF-SHA256/ChaCha20-Poly1305 是首选基线；如果后续评审要求，增加 P-256 或 AES-GCM 变体，但 MUST 由 profile 明确，不得由实现自行协商。
3. **前向保密**：每条消息或每个短流 SHOULD 使用发送方临时密钥；长期身份密钥只用于认证临时公钥。不得复用长期共享密钥加密多条消息。
4. **密钥发现**：接收方公钥通过 Registry 或 KeyRegistry 按 `kid` 发布；发布记录 MUST 有生命周期（active/retired/revoked）与所有权证明。没有可信 `kid` 时 MUST 拒绝，而不是回退到明文。
5. **元数据仍可见**：P1 只能隐藏 payload，不能隐藏 `from`/`to`/`task_id`/时间等路由元数据；需要元数据保护时另立 profile，不得声称 P1 已解决。
6. **迁移与降级**：P0/P1 之间 MUST 显式协商；不得静默降级到 P0。降级需要策略允许并记录审计。

## 后果

- 0.1 的高风险场景仍需依赖本地信任与 OS 隔离；不能把 OSAP 当作端到端加密协议。
- P1 会增加密钥管理、失败模式与性能开销；0.2 需要独立的安全评审。
- Registry 的公钥发布成为新的攻击面；需要撤销、轮换与离线缓存策略。
- 元数据泄漏仍是隐私问题，用户可见性文档必须说明。

## 备选方案

- **0.1 直接上 P1**：安全叙事更强，但密码学与密钥发现未评审，容易冻结错误设计。
- **用 TLS/mTLS 替代**：适合 localhost/跨进程，但不解决 Bus 自身可见 payload 的问题。
- **只做 payload 签名、不加密**：完整性够，机密性不足。
- **自定义加密格式**：灵活，但重复 HPKE 工作，审计成本高。

## 重审触发条件

1. HPKE 的 OSAP profile 完成安全评审与互操作测试；
2. 出现必须隐藏 payload 的部署或监管要求；
3. 元数据分析表明即使加密 payload，路由元数据仍泄漏关键信息；
4. 0.2 范围冻结时，P1 仍缺少密钥发现/撤销方案。

## 参考

- [`docs/standard.md`](../docs/standard.md) §2.4（信任 profile）、§11.3（密码学）、§15.11
- [`docs/roadmap.md`](../docs/roadmap.md) §4（0.2 范围冻结建议）
- [`impl/osap/pcs.py`](../impl/osap/pcs.py)（密钥生命周期与 `kid` 解析）
