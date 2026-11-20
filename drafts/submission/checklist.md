# IETF 提交前置检查单

> 性质:**内部工作文档,非规范、非公开承诺**。本目录的模板只是准备材料——在 §10.4 的闸门通过之前,任何内容都不会实际提交或发出。
> 关联:`GOVERNANCE.md` §10.4(贡献者同意与 IPR 披露)、[`../README.md`](../README.md) §6(发布前检查)。
> 更新时间:2026-11-20

---

## 1. 闸门总览

| # | 事项 | 状态 | 机械检查 | 负责人 |
|---|---|---|---|---|
| 1 | 贡献者同意(§10.4) | ⬜ 未启动 | 人工:已签署同意书归档 | 仓库所有者 |
| 2 | BCP 79 IPR 披露 | ⬜ 未启动 | 人工:Datatracker 披露页 | 实际提交人 |
| 3 | 替换占位作者 | ⬜ 未启动 | `python3 tools/check_drafts.py --submission`(当前如预期失败,替换后转绿) | 实际提交人 |
| 4 | 文档名(draft-\<author\>-…) | ⬜ 未启动 | `check_drafts` 的 `DOCNAME_RE` 在改名后自动适配 | 实际提交人 |
| 5 | WG 归属意向 | ⬜ 未启动 | 人工:chairs 回复存档 | 联络人 |
| 6 | 外部引用改 bibxml | ⬜ 未启动 | `tools/check_drafts.py --compile` | 提交人 |
| 7 | 复核(compile + docs + tests) | ✅ 本地常绿 | CI | 任何维护者 |

**当前阻断项只有 1–5,全部需要真实身份与人工决策;模板见本目录。**

---

## 2. 贡献者同意(§10.4)

- 闸门:MUST 取得**所有**贡献者对 IETF Trust 版权条款(RFC 5378 / BCP 78)与 Simplified BSD License(RFC 8179 / BCP 79 涉及的部分)的同意,并在新版本中说明。
- 名单来源:`git log --all --format='%an <%ae>' | sort -u` 逐人确认;每个贡献者一份 [consent-template.md](consent-template.md)。
- 归档:签署件放**仓库外**(邮件存档或私有目录);仓库内只登记"谁、何时、以何种方式同意",不存放含个人邮箱的签署件。
- 完成后:在 `drafts/README.md` §6 把第 1 项从"未启动"改为已完成并注明日期。

---

## 3. BCP 79 IPR 披露

- 模板:[ipr-disclosure-template.md](ipr-disclosure-template.md)。Datatracker 表单地址:https://datatracker.ietf.org/ipr/about/
- 原则:据实披露。本项目当前**没有已知专利声明**;若贡献者持有涉及两个 draft 内容的专利/申请,MUST 在提交前披露(BCP 79 / RFC 3979 + 4879 语义)。
- 完成标志:披露页 URL 写入 `drafts/README.md` §6 第 2 项;`ipr="trust200902"` 属性届时已与披露核对一致(该值本身是模板默认,不是披露)。

---

## 4. 占位作者与文档名

当前占位(两份 draft 相同):

```xml
<author fullname="OSAP Editors" initials="O." surname="Editors">
  <organization>OSAP Project</organization>
  <address><email>editors@osap.example</email></address>
</author>
```

替换清单:

1. 每份 draft 的 front `<author>` 块改为真实姓名/缩写/邮箱;多作者时各自一块。
2. `editors@osap.example` 与 `drafts/README.md` 中的占位说明同步更新。
3. `docName` 与文件名:individual submission 必须是 `draft-<第一作者姓氏>-<标题>-<nn>`;例如改名为 `draft-<surname>-osap-capability-tokens-00`。`tools/check_drafts.py` 的 `DOCNAME_RE` 只校验格式,改名后同步 `seriesInfo`、文件名与 `drafts/README.md` 的映射表。
4. 机械闸门:`python3 tools/check_drafts.py --submission`(占位符与作者联系方式检查;在占位替换完成前如预期失败,不要把它接入 CI)。

---

## 5. WG 联络

- 模板:[liaison-agentproto.md](liaison-agentproto.md)、[liaison-oauth.md](liaison-oauth.md)。
- 动作:把信(填入真实署名与邮箱)发给 chairs;未被采用前保持 individual submission。
- 存档:chairs 回复放仓库外;仓库内只登记日期与结论。

---

## 6. 提交动作(闸门全过之后)

1. 在 Datatracker 以**真实个人账号**上传(an individual submission,不是 WG upload);
2. 上传前重跑:`python3 tools/check_drafts.py --submission --compile` + 全量测试;
3. Datatracker 会自动执行 ipr/authors 检查;任何 mismatches 按其提示处理;
4. 提交后在 `drafts/README.md` 记录 URL 与日期,并在 `GOVERNANCE.md` §10.4 的"新版本说明"要求下更新声明。

---

## 7. 明确不做的事

1. 本目录任何文件**不构成提交**,也不会被自动发送;`git push` 与 Datatracker 之间没有管道。
2. 未经闸门 1–5,不把 `--submission` 接入 CI(它会一直红,且那是预期)。
3. 不代替任何真实作者签署同意书或提交披露——这些动作只能由署名者本人完成。
