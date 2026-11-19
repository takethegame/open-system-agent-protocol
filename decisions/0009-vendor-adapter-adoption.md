# ADR-0009: 厂商适配器采用

- 状态：Provisional
- 日期：2026-11-19
- 关联：`docs/standard.md` §15.9、§6.7；`docs/roadmap.md` §M5

## 背景

Apple App Intents、Android AppFunctions/App Actions、Windows 的 app actions 等原生机制已经在做“应用能力声明”。OSAP 不可能要求厂商重写这些机制，也不应让每个厂商定义一套私有 wire format。适配器的质量决定生态能否形成。

## 暂定结论

1. **开放适配器规范**：OSAP 提供适配器接口与一致性测试，任何厂商、发行版或社区都可以实现；不设“官方适配器”之外的协议特权。
2. **保留原生身份**：能力记录 MUST 保留 `source.kind`、`native_id`、`version` 与厂商域名；OSAP 能力 URI 是投影，不得覆盖或伪造原生 ID。
3. **信任归一**：原生注册表的信任级别可以映射到 OSAP 的 `verified`/`unverified`，但 MUST NOT 把“系统预装”自动提升为 L0/L1 的无限读取；风险仍按能力记录计算。
4. **官方 SDK 优先，但不强制**：厂商把适配器放进官方 SDK 是最好的采用路径；在未进入 SDK 前，发行版/社区适配器可以工作，但 MUST 明确标注维护者与支持范围。
5. **不 fork 协议**：厂商扩展 MUST 放在 `extensions` 或厂商命名空间；不得改变核心授权、衰减、绑定或撤销语义。出现不兼容扩展时，OSAP 名称不得用于该分支。
6. **一致性登记**：适配器通过哪些 C 等级、在哪个平台/版本上测试，必须可复现；不得用“厂商认证”替代测试报告。

## 后果

- 适配器可能碎片化；Registry 需要去重、优先级与迁移规则。
- 厂商可能只想支持自己的动作，不愿暴露完整能力；OSAP 只能索引已声明部分，不能假装完整。
- 官方 SDK 采用需要长期联络；短期靠社区适配器，质量参差。
- 需要定义“原生能力更新/删除”如何同步到 OSAP 记录与缓存。

## 备选方案

- **只支持 OSAP 原生 Agent**：生态最慢，重复厂商工作。
- **让厂商自定义 wire format**：采用快，但互操作与一致性崩溃。
- **由 OSAP 项目维护所有适配器**：不可持续，也无法覆盖闭源平台。
- **强制厂商认证**：提高质量，但形成准入壁垒，违背开放标准。

## 重审触发条件

1. 任一主流厂商在官方 SDK 中内置 OSAP 适配器；
2. 出现无法用 `extensions` 表达的原生能力；
3. 适配器不一致导致跨应用任务失败或安全事件；
4. 治理机构要求认证/商标许可，需与 `GOVERNANCE.md` §10.2 对齐。

## 参考

- [`docs/standard.md`](../docs/standard.md) §6.7（Bridge）、§15.9
- [`impl/osap/federation.py`](../impl/osap/federation.py)（原生描述投影）
- [`docs/prior-art.md`](../docs/prior-art.md)（App Intents / AppFunctions / App Actions）
- [`GOVERNANCE.md`](../GOVERNANCE.md) §10.2（一致性标记）
