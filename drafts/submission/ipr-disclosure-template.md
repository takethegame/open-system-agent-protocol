# BCP 79 IPR 披露草稿模板

> 用法:仅在**存在**需披露的知识产权时填写;若全项目无已知专利声明,则无需提交披露,只需在 IETF 通讯中据实说明。**这是待人工填写的模板,不构成披露。**
> 提交表单:https://datatracker.ietf.org/ipr/about/(Datatracker 账号由披露人本人持有)
> 依据:RFC 3979(RFC 4879 修订)——参与 IETF 文档工作时对已知专利的披露义务。

---

## 披露字段(Datatracker 表单逐项对应)

| 字段 | 填写内容(模板) |
|---|---|
| Patent / Patent application | <专利号或申请号、受理局、申请日> |
| Holder(s) of patent | <姓名/公司> |
| Holder's contact | <邮箱;若不愿公开则注明"do not publish",Datatracker 仍需联系方式> |
| IETF document(s) | `draft-zeng-osap-capability-tokens`、`draft-zeng-osap-consent-receipts` |
| IETF working group | <agentproto / OAuth / independent> |
| Disclosure type | Generic(不限于特定实现)/ Specific(特定实现)——按事实选择 |
| Nature of rights | <许可类型:RAND / RF 免费许可 / 其他,据实> |
| Licensing declaration | <Datatracker 提供的声明选项,逐字核对> |
| Holder's statement | <可选说明> |
| Revision note | <披露更新原因> |

---

## 本项目当前的事实基线(供填写时对照)

1. 参考实现以 Apache-2.0 分发;draft 文本按 IETF Trust 政策提交,两者许可**互不改变**(draft 被采纳后文本版权归 IETF Trust,这是提交的前提而非新增授权)。
2. 项目迄今**未做专利检索**;本模板不用于替代检索。披露义务针对"已知"权利,请贡献者自查自己的专利与申请。
3. Apache-2.0 的专利授权只及于实现,不自动延伸到 IETF 文档内容;若贡献者的专利涉及 draft 内容,Apache-2.0 不能替代 BCP 79 披露。

---

## 提交后动作

1. 把 Datatracker 披露页 URL 记入 `drafts/README.md` §6 第 2 项;
2. 更新 `GOVERNANCE.md` §10.4 的版本说明(新版本中说明同意与披露完成);
3. 若披露类型为 RAND 等受限许可,在两个 draft 的 IANA Considerations / Security Considerations 中如实陈述(与 draft 的 `ipr="trust200902"` 无关)。
