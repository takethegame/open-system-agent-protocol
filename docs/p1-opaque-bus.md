# P1 Opaque Bus — 0.2 设计提案

> 性质:**非规范性设计文档**。0.1 规范(§3.6)只允许实现声明 P0(Trusted Bus);本文是 P1(Opaque Bus)进入 0.2 前的设计提案,不是规范,不改变任何 0.1 的 MUST,也不是 IETF draft。
> 关联:`docs/standard.md` §3.6(信任 profile)、§5.4(绑定分工)、§7(消息协议)、§10(审计);RFC 9180(HPKE)。
> 状态:设计提案,未实现;实现前须经维护者评审(密码学参数与 FS 结论尤其需要外部评审)。
> 更新时间:2026-11-27

---

## 1. 目标与威胁模型

### 1.1 解决的问题

P0(Trusted Bus)下,Bus 可读取跨 App 消息的明文 `body`——这是显式信任假设,把 Bus 变成了全局内容汇聚点:

- 一次 Bus 攻陷即泄露全部跨 App 任务内容;
- 部署方必须向用户披露"Bus 可读取内容",这在多租户或不受信运行环境不可接受;
- 审计与幂等所需的**元数据**被迫与**业务载荷**同权级暴露。

P1 Opaque Bus 的目标:**Bus 只见路由与授权元数据,不见业务载荷**——payload 使用端到端加密,Bus 从"内容汇聚点"降级为"受约束的路由器"。

### 1.2 威胁模型

| 对手能力 | P1 下的结果 |
|---|---|
| 读取 Bus 内存/磁盘/线路上的消息 | 只见外层元数据;`body`/`auth`/`refs`/`consent` 全为密文 |
| 篡改外层可见字段(改 task、换 from) | 解密失败(AAD 绑定),fail closed |
| 重放整条密文消息 | Bus 的 `id` 去重仍然生效;接收方 HPKE 解密结果与 AAD 绑定同一上下文,跨任务重放被拒 |
| 伪造新消息 | 需要接收方 HPKE 静态公钥与合法元数据;HPKE auth 模式(可选启用)提供发送方身份证明 |
| 攻陷接收端点的 P1 私钥 | **见 §6 前向保密分析**——轮换窗口内的历史消息可解;这是 P1 的诚实边界 |
| 攻陷任一端点(发送方/接收方进程) | 端点本就看到明文;P1 不解决端点恶意(§1.4 非目标不变) |
| 流量分析 | 元数据明文(见 §3);P1 不解决 |

### 1.3 明确不解决

1. 端点恶意(§1.4);
2. 元数据流量分析(from/to/task 仍可见,§3 是有意决策);
3. 每条消息的完美前向保密(ratchet)——P1 提供轮换粒度的 FS(§6);
4. Bus 丢弃/延迟消息(DoS 永远可能,P1 不改变可用性边界);
5. 审计的机密性——审计事件由各服务直写 AL,路径不变(§7)。

---

## 2. 可见性决策:哪些字段保持明文

| 字段 | 明文/密文 | 理由 |
|---|---|---|
| `osap`、`id`、`type`、`trace_id`、`causation_id` | 明文 | 版本协商、幂等去重、审计关联 |
| `from`、`to` | 明文 | 路由、对端认证、§5.4 的 audience/subject **外层**核对 |
| `task`、`deadline`、`priority`、`session_id` | 明文 | 路由、背压、超时;`task.id` 参与 AAD 绑定防跨任务重放 |
| `ts` | 明文 | 时钟偏差检查(§2.5) |
| `origin` | 明文 | 提示注入防护与信任判断(§7.1) |
| `auth`(token + cap_id) | **密文** | 凭证是最高价值载荷;`cap_id` 的明文暴露会把跨 App 任务关联成图谱 |
| `body` | **密文** | 业务载荷本体 |
| `refs` | **密文** | 句柄即数据地图 |
| `consent` | **密文** | 回执 id 关联用户决定 |
| `extensions` | **密文** | 扩展与核心字段一起签名/加密 |

**语义影响(须在 0.2 规范化时写明)**:§5.4 规定路由边界 MUST 做无状态核对(audience、subject、task_id、depth)。P1 下路由器能核对的是**外层**的 audience(`to`)、subject(`from` 的传输认证身份)与 task_id;`depth`、consent 有效期等全部移交接收方。这收窄了路由器的判定面,是 P1 的语义代价,与 §5.3"有状态条件由接收方拒绝"的方向一致。

**降级保护**:路由器收到的仍是**传输认证**的身份(§7.10 对端认证),所以 `from` 不是可以随意伪造的字段——伪造 `from` 首先要通过对端认证,而 P1 接收方还会核对解密后的 `token.subject == 外层 from`。

---

## 3. 密钥发现

### 3.1 密钥类型

**密钥按套件生成与隔离**(§4.1):每个 Agent 对每个自己声明支持的套件,各持有一枚 P1 HPKE 静态密钥对(KEM:X25519):

- 私钥:仅本进程持有,存 `KeyStore`(复用 `impl/osap/keystore.py` 契约——`JsonKeyStore` / `MemoryKeyStore` / OS 密钥环,与 PCS 私钥同一治理);
- 公钥:进入发现面,绑定 `kid`。

### 3.2 发布渠道(两条,均可独立工作)

1. **welcome 扩展**:`welcome` 的 `features` 列出支持的套件(如 `["p1", "p1-hpke-x25519-256"]`),并按套件携带 `{suite, p1_kid, p1_public_key}`——点对点连接建立时直接获得对方当前公钥与套件;
2. **RFS 索引**:能力记录的 `extensions` 携带 `{suite, p1_kid, p1_public_key}` 对,经 `describe` 查询——发送方在路由前即可解析目标公钥与套件(对 `to: {capability}` 这类接收方未知的场景必需)。

### 3.3 `kid`、轮换与撤销

- `kid` 格式:`p1_<公钥指纹前 16 hex>`;**轮换必须换 kid**(与 PCS KeyRegistry §10.4 同一原则);
- **轮换间隔 R(默认建议 24h)**:接收方对**每个套件**每 R 生成新密钥对、发布新 kid、旧 kid 进入**退役宽限 G(默认建议 1h)**——G 内旧私钥仅用于解密在途消息,G 后**销毁**;
- **撤销**:kid 泄露时在 RFS 标记 revoked;消息携带 `p1_kid`,接收方/发送方遇到 revoked kid 时拒绝并提示重连获取新公钥;
- 跨 App 一致性:发送方缓存的目标公钥过期(观察到新 kid)时,重查 RFS——与能力记录 TTL 语义一致。

---

## 4. Wire format(HPKE,RFC 9180)

### 4.1 密码套件（命名套件 + 声明-选择，0.2 起）

套件**可以协商**，但机制不是交互式协商，而是**声明-选择**（declare-and-choose）：

1. 每个命名套件有一个稳定标识符，并定义完整的 (KEM, KDF, AEAD) 组合与 `info` 字符串；
2. 接收方在 welcome 与 RFS 上**公布**自己接受的 `(kid, suite)` 对——公布即全部选择面；
3. 发送方**只能**从接收方公布过的组合里选一个，并把所选 `suite` 回显在 `osap.opaque/v1` 的 `data` 中；
4. 不存在交互式协商，也不存在双方"共同决定"的回合——**降级面从结构上不存在**（Bus 无法让发送方选到接收方未公布的套件）。

| 套件名 | KEM | KDF | AEAD | `info` | 状态 |
|---|---|---|---|---|---|
| `hpke-x25519-128` | DHKEM(X25519, HKDF-SHA256) | HKDF-SHA256 | AES-128-GCM | `osap-p1-hpke-x25519-128-v0.2` | **默认、必备**（RFC 9180 A.1.1 向量验证） |
| `hpke-x25519-256` | DHKEM(X25519, HKDF-SHA256) | HKDF-SHA256 | AES-256-GCM | `osap-p1-hpke-x25519-256-v0.2` | 可选实现 |
| （未来）X448 / ChaCha20Poly1305 / PQ-KEM | — | — | — | — | 按 RFC 9180 §7.1.5 立项 |

`info` 按套件**域分隔**——两个套件永远不会从相同输入派生出相同密钥。

#### 4.1.1 降级与残留风险（诚实边界）

- **声明通道的可信度**：`welcome` 是点对点直连，声明不可被第三方剥离；RFS 索引上的声明与 RFS 同信任级——被攻陷的 RFS 可以**裁剪**高强度的 `(kid, suite)` 条目，但不能注入接收方未生成的密钥（kid 绑定接收方公钥，解密仍需私钥）。缓解：发送方本地策略可设**强度下限**（如"绝不使用低于 128 的套件"），低于下限的声明直接拒绝发送；
- **套件替换**：攻击者把 `data.suite` 从 256 改成 128？接收方以 (kid → 自己生成的密钥及其套件) 打开——密钥是**按套件生成**的，kid 与套件绑定，替换后 kid/套件不匹配即 `AUTH_DENIED`；
- **逐消息混合**：同一接收方同时运行两个套件的密钥是允许的（密钥按套件隔离，§3.3）。

### 4.2 AAD:外层元数据绑定

AAD = 可见路由字段的**规范化序列化**(与能力 token 的 §5.2 规范化 profile 同规则:键排序、最小分隔、整数),恰好包含:

```
osap, id, type, trace_id, causation_id(如有), from, to, task, deadline(如有), session_id(如有), ts
```

效果:Bus 篡改或重排任何可见字段,接收方解密即失败;密文与 (task, from, to) 绑死——跨任务重放一条截获的密文必然 AAD 不匹配。`priority` 不参与 AAD(路由器可按背压降级?——**不**,priority 也是 AAD 的一部分,防止降级改序;开放问题见 §9)。

### 4.3 信封形状

```
{
  "osap": "0.2",
  "id": "msg_01J...",
  "type": "request",
  "trace_id": "trace_01J...",
  "from": "agent://com.example.notes/assistant#7f3a",
  "to": { "agent": "agent://com.example.calendar/agent#9c" },
  "task": { "id": "task_01J...", "mode": "supervisor" },
  "deadline": "2026-11-10T10:15:00Z",
  "ts": "2026-11-10T10:14:45Z",
  "origin": { "kind": "agent", "trust": "verified" },
  "body": {
    "schema": "osap.opaque/v1",
    "data": {
      "suite": "hpke-x25519-128",
      "p1_kid": "p1_9f2c7b1a8d3e4f5b",
      "enc": "base64url(HPKE enc, 32 字节)",
      "ciphertext": "base64url(AEAD 密文)"
    }
  }
}
```

**内层明文**(解密后):

```
{
  "auth": { "cap_id": "cap_01J...", "token": { ... } },
  "body": { "schema": "osap.calendar.propose/v1", "data": { ... } },
  "refs": ["obj://sha256:9f2c..."],
  "consent": { "receipt_id": "consent_01J..." },
  "extensions": { ... }
}
```

规则:

- 每条消息**一次独立 HPKE 封装**(fresh ephemeral)——无跨消息 nonce 状态,乱序/并行安全;
- `auth`/`body`/`refs`/`consent`/`extensions` 全部进内层,结构就是 P0 信封的对应字段;
- `osap.opaque/v1` 的 `data` 只含 `suite`/`p1_kid`/`enc`/`ciphertext`,Bus 与任何中间件无需也无法解析更多;
- 解密失败 → `AUTH_DENIED`(fail closed);`p1_kid` 未知/撤销 → `AUTH_DENIED` 并提示重查 RFS。

### 4.4 各消息类型在 P1 下

| 类型 | P1 处理 |
|---|---|
| `request` | body/auth/refs/consent 加密(§4.3) |
| `delegate` / `handoff` | 同上;`task` 外层明文,内层凭证与结果 schema 加密 |
| `status` | `consumed` 属业务语义 → 整体加密;外层保留 task 路由 |
| `event` | `origin`/topic 明文,`payload` 加密;订阅匹配仍由事件服务(topic 明文)执行 |
| `stream.chunk` | `stream_id`/`seq` 明文(排序需要),`data` 加密 |
| `consent.request` | 预览文本面向用户,PCS 端点本就见明文;P1 加密与否 = **开放问题**(§9.5) |
| `hello` / `welcome` / `describe` / `error` | 协商与控制,不加密 |

---

## 5. 授权与审计在 P1 下如何继续成立

| 原机制 | P1 下的位置 |
|---|---|
| §5.4 路由器无状态核对 | audience/subject/task_id 用外层;**depth 移交接收方**(§2 的语义代价) |
| §5.4 接收方有状态核对 | 全部保留——解密后 token 的 revoked/max_uses/consent/预算检查不变 |
| §10.3 预约顺序(reserve → grant → activate) | 不变:回执与预约是 PCS 与 CA 之间的事务,不经 Bus |
| §8.11 AI8(审计先于副作用) | effect.intent 由**接收方服务直写 AL**(与 Bus 同机不同组件),不依赖 Bus 读写 payload;P1 不改变该路径 |
| §10.5 审计链 | 链事件由服务生成;P1 下审计事件**不加密**(审计是给用户/取证方的),但事件由 AL 独立持久化,Bus 无法篡改 |
| §10.6 脱敏导出 | 不变 |
| 幂等去重 | Bus 仍按明文 `id` 去重——重放密文不重复执行副作用(§8.11) |

---

## 6. 前向保密分析(诚实边界)

### 6.1 HPKE base 模式的固有性质

`hpke_seal(pkR, …)` 用**接收方静态公钥**封装:只要 `skR` 不泄露,截获的密文安全。但**一旦 `skR` 泄露**,攻击者可解密**历史上所有用该 `skR` 封装的密文**——base 模式本身**不提供**前向保密。

### 6.2 P1 的 FS 来源:轮换粒度

P1 不引入 ratchet,而是用**密钥轮换 + 销毁**逼近:

- 接收方每 R(24h)轮换 `kid`,旧 `skR` 在宽限 G(1h)后**销毁**;
- 于是"截获存档 + 日后攻陷设备"的对手最多解密**当前轮换窗口内**的消息;
- **FS 保证 = min(R, 消息存活期)**,并依赖"旧私钥确已安全销毁"这一实现承诺(§8 的 KeyStore 义务)。

### 6.3 明确不是

- **不是**每消息 FS(双 ratchet / Signal 风格)——`stream.*` 乱序与并行投递使 ratchet 复杂化,列为开放问题(§9.2);
- **不是**密钥泄露后的全程补救——窗口内泄露即窗口内暴露;R/G 参数是安全性与运维成本的权衡,须写入部署声明;
- **不依赖**发送方持有长期秘密:每消息 fresh ephemeral,发送方被攻陷不影响其**过去发出的**密文(发送方无私钥可偷)。

### 6.4 结论表述(供 0.2 规范化采用)

> P1 提供**轮换窗口内的前向保密**:在接收方按 R 轮换并销毁旧私钥的前提下,捕获并存储密文的攻击者无法解密早于当前轮换窗口的消息。P1 不提供逐条消息的前向保密,也不保护元数据。

---

## 7. 传输层正交性

P1 与传输绑定正交:UDS stream / 数据报 / 未来 XPC/Binder 均可携带 `osap.opaque/v1`。传输层对端认证(§7.10)在 P1 下**更重要**——`from` 的可信度完全依赖它。传输层已有的能力全部保留(PeerPolicy、配额、背压)。

---

## 8. 实现草图(0.2,非规范性)

- **模块**:`impl/osap/opaque.py`
  - `P1KeyPair.generate()` → `{kid, public_key, private_key}`;
  - `seal(envelope_fields, inner, pkR)` / `open(outer, skR)`——按 §4.2 AAD 规则;
  - HPKE 合成:用 `cryptography` 现有原语(X25519、HKDF-SHA256、AESGCM)按 RFC 9180 §5.1/§5.2 分层封装;**必须带 RFC 9180 附录 A.1/A.3 官方测试向量**做正确性验证;
- **Bus**:`Bus(p1_keys=..., p1_required=False)`——`p1_keys` 是 KeyRegistry 式组件(查找 kid → 公钥/私钥);welcome `features` 增加 `"p1"` + 发布自身公钥;
- **发送方路径**:目标声明 p1 且本地策略要求 opaque → `seal` 后发送 `osap.opaque/v1`;接收方遇到 `osap.opaque/v1` → `open` → 以内层字段继续现有 dispatch 流程(错误处理:解密失败 `AUTH_DENIED`);
- **协商**:welcome 对比;P0/P1 混合部署期间接收方必须同时接受两种消息;
- **依赖**:仅 `cryptography`(已安装),无新依赖;
- **测试**:RFC 9180 官方向量、AAD 篡改拒绝、kid 撤销拒绝、轮换后旧密文不可解(FS 性质测试)、P0/P1 混合收发。

---

## 9. 开放问题

1. **接收方私钥的销毁证明**:KeyStore 层能否提供"已销毁"的可验证声明(如密钥环条目删除回执)?仍是实现承诺,非密码学保证;
2. **ratchet**:是否值得为 stream 乱序设计 per-message FS?倾向 0.2 不做;
3. **群发效率**:一个发送方对 N 个接收方各需一次封装(各自的 pkR);`event` 广播场景的密钥协商成本待设计;
4. **`consent.request` 是否在 P1 下加密**:预览文本面向用户,PCS 端点本就明文;加密反而把 PCS 排除在外——倾向不加密,待 WG 讨论;
5. **priority 的 AAD 绑定**:防止降级改序 vs 允许路由器调度弹性——需要 WG 权衡;
6. **与 WIMSE 的关系**:`sadp-delegation` 等稿同样处理加密委派载荷;0.2 规范化时应与 WIMSE 对齐或明确分界。

~~7. 套件演进~~(已解决,2026-11-27):套件协商采用 §4.1 的声明-选择模型——命名套件、接收方按套件公布 `(kid, suite)`、发送方选择并回显 `suite`;降级面从结构上不存在,残留风险与缓解见 §4.1.1。

---

## 10. 前置条件与状态更新

进入 0.2 规范化之前:

1. 本文档经维护者 + 至少一次外部密码学评审(§6 的 FS 结论是核心评审对象);
2. `opaque.py` 实现并通过 RFC 9180 官方测试向量;
3. `docs/standard.md` §3.6 的"P1 方向"按本文升级为规范性文字(语义影响 §2 须一并写入);
4. 一致性用例:P1 加解密往返、AAD 篡改拒绝、kid 撤销拒绝(新增编号,先改 `docs/conformance.md`);
5. 两份 IETF draft 是否需要 -01 增补 opaque 章节:Draft A/B 均不定义传输,倾向**单独立稿**而非并入。

---

## 11. 与 0.1 的关系(重申)

- 0.1 实现 **MUST NOT** 声称支持 P1(§3.6)——本提案不改变这一点;
- 0.1 的 P0 部署义务(披露、脱敏、代码签名)全部保留;
- P1 是 0.2 的**可选** profile:P0 与 P1 长期共存,单用户设备继续用 P0。
