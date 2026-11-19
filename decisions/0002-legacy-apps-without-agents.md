# ADR-0002: 无 Agent 的旧应用

- 状态：Provisional
- 日期：2026-11-19
- 关联：`docs/standard.md` §15.2、§6.7；`docs/roadmap.md` §M4

## 背景

大量桌面应用不会很快内置 Agent。用户仍希望这些应用参与跨应用任务：读取当前文档、插入一段文字、创建日历事件。可选路径有两条：

1. 应用提供一个轻量适配器/SDK，把有限动作暴露为 OSAP 能力；
2. 由外部桥接器通过 UI 自动化（Accessibility、屏幕读取、合成输入）操作应用。

UI 自动化能力强大，但它绕过应用自身的权限模型，容易读取屏幕上的一切，也容易被提示注入利用。它不应成为默认路径。

## 暂定结论

1. **优先适配器**：应用或发行版 SHOULD 提供一个轻量适配器，声明明确的能力描述（动作、资源、schema、风险、同意模式），并由 OSAP Registry 索引。
2. **UI 自动化只作兜底**：桥接器 MUST 作为独立的高风险组件注册，至少满足：
   - 只能暴露显式声明的动作，不得提供通用“执行任意脚本/点击任意坐标”的能力；
   - 读取屏幕或控件树 MUST 需要单独的 `screen.read`/`ui.inspect` 能力，并按 `sensitive` 标签处理；
   - 合成输入 MUST 经过 L3/L4 同意，不得因为“用户已授权应用”而获得环境权限；
   - 桥接器 MUST NOT 绕过 OS 的 Accessibility、Screen Recording、Input Monitoring 权限；
   - 桥接器产生的事件 MUST 标记 `origin.kind=app`、`trust=unverified` 或更严格，不得冒充原生 Agent。
3. **无适配器时默认拒绝**：如果应用既没有适配器，也没有用户显式启用的 UI 自动化桥接，OSAP MUST 返回 `ROUTING_NOT_FOUND` 或 `POLICY_DENIED`，不得静默降级到屏幕自动化。
4. **可迁移性**：适配器与 UI 自动化桥接共享同一能力 URI 与 schema；当应用后来提供原生适配器时，注册表 SHOULD 优先选择原生适配器，并在审计中记录切换。

## 后果

- 旧应用的接入需要额外工作，但攻击面可控。
- UI 自动化桥接会成为安全评审重点；它不能被当作“兼容层”而跳过同意与审计。
- 需要定义“适配器能力”与“原生 Agent 能力”的优先级、去重与迁移规则。
- 无障碍场景可能确实只能依赖 UI 自动化；此时必须把它当作高风险能力，而不是普通读操作。

## 备选方案

- **只支持原生 Agent**：最安全，但生态采用最慢，旧应用完全掉队。
- **UI 自动化作为默认**：接入最快，但把屏幕内容与输入注入变成通用权限，违背 no ambient authority。
- **每个应用单独写私有桥接**：可行，但无法形成可发现、可审计的能力记录。
- **要求应用重写**：不现实，尤其对闭源与系统应用。

## 重审触发条件

1. 主流平台把 App Intents、AppFunctions 或 App Actions 作为标准适配层，旧应用可通过系统桥接获得结构化能力；
2. 无障碍社区或监管要求把 UI 自动化列为必要路径；
3. 出现针对 UI 自动化桥接的提示注入或屏幕窃取事件；
4. 适配器生态达到足够覆盖率，可以默认关闭 UI 自动化。

## 参考

- [`docs/standard.md`](../docs/standard.md) §6.7（桥接）、§9.4（信息流标签）、§15.2
- [`impl/osap/federation.py`](../impl/osap/federation.py)（外部描述投影与信任归一）
- [`docs/prior-art.md`](../docs/prior-art.md)（App Intents / AppFunctions / App Actions）
