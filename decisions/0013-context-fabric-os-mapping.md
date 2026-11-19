# ADR-0013: Context Fabric 与 OS 句柄/portal 映射

- 状态：Provisional
- 日期：2026-11-19
- 关联：`docs/standard.md` §15.13、§9；`bindings/linux/profile.md` §5

## 背景

Context Fabric（CF）需要解析 `ctx://`、`obj://`、`task://`、`file://`、`contact://`、`event://` 等句柄。它可以选择自建对象存储，也可以映射到 OS 已有的文件描述符、security-scoped bookmark、content URI、portal 或等价机制。自建存储控制力强，但会重复 OS 工作并扩大数据面。

## 暂定结论

1. **CF 是授权/句柄解析层，不是文件系统**。默认实现 MUST 复用 OS 已有机制；独立对象存储是可选实现，且必须满足 §9.10 的存储责任。
2. **句柄映射**：
   - `file://` 映射到 OS 不透明句柄（fd、bookmark、content URI、portal 结果），不得暴露绝对路径；
   - `obj://` 映射到内容寻址对象或 OS 内容服务，保留标签、TTL 与引用计数；
   - `task://` 映射到任务黑板，生命周期 = 任务生命周期；
   - `ctx://` 映射到用户/会话/设备上下文，解析必须经过策略；
   - `contact://`/`event://` 映射到目录/事件服务，不默认获得长期记忆。
3. **portal 结果是句柄，不是能力**：portal 的一次性选择结果 MUST 被包装为带 `ttl`、`label`、`origin` 的 CF 句柄；后续解析仍受 OSAP 能力控制。portal 的 UI 决策记录为 `context.resolve` 审计；L3/L4 仍需回执。
4. **平台绑定独立**：Linux 的 D-Bus/portal 映射写在 [`bindings/linux/profile.md`](../bindings/linux/profile.md)；macOS/Windows/Android 的绑定各自成文，不把平台细节塞进核心规范。
5. **失败关闭**：portal/OS 句柄不可用、标签冲突、TTL 过期时 MUST 拒绝解析；不得回退到路径遍历或“管理员模式”。
6. **长期记忆边界**：任务黑板、对象元数据与 Bus 持久状态 MUST NOT 自动晋升为长期记忆；写入/读取长期记忆需要单独能力与同意。

## 后果

- CF 的行为依赖平台能力；跨平台一致性需要通过一致性测试与明确的“不支持”声明。
- portal 覆盖范围有限（联系人、日历、消息没有统一 portal），这些能力只能由应用提供。
- 自建对象存储的诱惑仍在；实现若选择自建，必须承担加密、引用计数、删除与审计责任。
- 句柄撤销需要映射到 OS 句柄撤销；无法撤销时只能靠 TTL 与拒绝解析兜底。

## 备选方案

- **CF 自建统一对象存储**：跨平台一致，但重复 OS 工作，数据面更大，迁移困难。
- **只支持 `file://`**：实现简单，但无法表达对象、联系人、事件与任务黑板。
- **把 portal 结果直接当能力**：少一层包装，但会把资源选择误当成环境权限。
- **把平台映射写进核心规范**：读者方便，但核心规范会被平台细节绑死。

## 重审触发条件

1. `xdg-desktop-portal` 或平台句柄 API 发生不兼容变化；
2. 出现新的 OS 句柄类型（如新的 content URI、bookmark、capability fd）；
3. 跨平台抽象无法用现有 scheme 表达；
4. 发生 portal 结果被误用为能力或路径泄漏事件。

## 参考

- [`docs/standard.md`](../docs/standard.md) §9（Context Fabric）、§15.13
- [`bindings/linux/profile.md`](../bindings/linux/profile.md) §5（portal 映射）
- [`impl/osap/context.py`](../impl/osap/context.py)（句柄、标签、出口、黑板）
