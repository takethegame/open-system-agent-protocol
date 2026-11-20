# IETF 提交前置检查单

> 性质:**内部工作文档,非规范、非公开承诺**。本目录的模板只是准备材料——在 §10.4 的闸门通过之前,任何内容都不会实际提交或发出。
> 关联:`GOVERNANCE.md` §10.4(贡献者同意与 IPR 披露)、[`../README.md`](../README.md) §6(发布前检查)。
> 更新时间:2026-11-20

---

## 1. 闸门总览

| # | 事项 | 状态 | 机械检查 | 负责人 |
|---|---|---|---|---|
| 0 | 贡献者名单确认 | ✅ 完成(2026-11-20):初始模板提交与全部 104 条 commit 均为本人 | `git log --all --format='%an <%ae>'` | Zeng Zhiyong |
| 1 | 贡献者同意(§10.4) | ✅ 完成(2026-11-20):署名者确认四条声明;记录见 [consent-record.md](consent-record.md) 登记表,DCO 签名提交固化 | `consent-record.md` 登记表填毕 | Zeng Zhiyong |
| 2 | BCP 79 IPR 披露 | ✅ 完成(2026-11-20):三问自查均为"否/无已知情况",**无披露义务**;结论见 [ipr-landscape.md](ipr-landscape.md) §3 | `ipr-landscape.md` §1/§3 填毕 | Zeng Zhiyong |
| 3 | 替换占位作者 | ✅ 完成(2026-11-20):Author/Editor = Zeng Zhiyong(ZZHY),email 已公开可见 | `python3 tools/check_drafts.py --submission` ✅ | Zeng Zhiyong |
| 4 | 文档名(draft-\<author\>-…) | ✅ 完成(2026-11-20):`draft-zeng-osap-capability-tokens-00` / `draft-zeng-osap-consent-receipts-00` | `DOCNAME_RE` + `--submission` ✅ | Zeng Zhiyong |
| 5 | WG 归属意向 | ⬜ 未启动:联络信已署名,待发送并归档回复 | 人工:chairs 回复存档 | Zeng Zhiyong |
| 6 | 外部引用改 bibxml | ⬜ 未启动(当前内联引用可编译) | `tools/check_drafts.py --compile` ✅ | Zeng Zhiyong |
| 7 | 复核(compile + docs + tests) | ✅ 本地常绿 | CI | 任何维护者 |

**剩余阻断项只有 1(邮件确认)与 2(专利自查决策),均为署名者本人动作。**

---

## 2. 贡献者同意(§10.4)

- 闸门:MUST 取得**所有**贡献者对 IETF Trust 版权条款(RFC 5378 / BCP 78)与 Simplified BSD License(RFC 8179 / BCP 79 涉及的部分)的同意,并在新版本中说明。
- ✅ 名单已确认(2026-11-20):全部 104 条 commit 均为 Zeng Zhiyong 本人(含初始模板提交 `Your Name <you@example.com>`),因此**唯一贡献者 = 署名者本人**;[consent-template.md](consent-template.md) 已填好本人信息,待其邮件回复确认四条声明。
- 归档:确认邮件放**仓库外**(邮箱存档);仓库内只登记"谁、何时、以何种方式同意"。
- 完成后:在 `drafts/README.md` §6 把第 1 项改为已完成并注明日期。

---

## 3. BCP 79 IPR 披露

- 模板:[ipr-disclosure-template.md](ipr-disclosure-template.md);检索记录:[ipr-landscape.md](ipr-landscape.md)。Datatracker 表单地址:https://datatracker.ietf.org/ipr/about/
- **检索结论(2026-11-20,非法律意见)**:领域态势已梳理——agentproto 已获章程并有 PACE/权限转移回执等 draft;第三方专利家族(consent receipt 信任根、macaroon-caveats 委派、WO2026154461A2)与 OSAP 概念相邻但机制不同;衰减式委派有充分的公开在先技术(Macaroons 2014 等)。**RFC 8179 的披露义务只针对署名者自己持有的权利**——待署名者按 [ipr-landscape.md](ipr-landscape.md) §1 的三问逐条确认;全部为"否"则无需提交披露。
- 原则:据实披露。若披露,类型(RAND/RF)是署名者的事实决定。
- 完成标志:确认结论写入本表第 2 行;披露(如有)页 URL 写入 `drafts/README.md` §6 第 2 项。

---

## 4. 占位作者与文档名

✅ 两项均已完成(2026-11-20),落点如下:

```xml
<author fullname="Zeng Zhiyong" initials="ZY" surname="Zeng">
  <organization>Independent</organization>
  <address><email>272577337@qq.com</email></address>
</author>
```

1. 两份 draft 的 front `<author>` 块已替换为真实姓名/缩写/邮箱;`editors@osap.example` 与 `drafts/README.md` 的占位说明同步移除。
2. `docName` 与文件名:按第一作者姓氏命名为 `draft-zeng-osap-capability-tokens-00` 与 `draft-zeng-osap-consent-receipts-00`,同步 `seriesInfo`、文件名与 `drafts/README.md` 的映射表;被 WG 采用后由 WG 重命名。
3. 机械闸门:`python3 tools/check_drafts.py --submission` ✅ 转绿(38 checks);注意 `272577337@qq.com` 会随 draft 公开发布,这是署名者本人确认的选择。
4. `<date year month day>` 仍是模板日期,在实际上传当日更新(闸门 6 的提交动作里执行)。

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
2. ~~未经闸门 1–5,不把 `--submission` 接入 CI~~ 已接入(2026-11-20):闸门 3/4 完成后 `--submission` 常绿,CI `drafts` job 改用 `--submission --compile`;闸门 1(邮件确认)与 2(IPR 决策)仍是上传前的真人动作。
3. 不代替任何真实作者签署同意书或提交披露——这些动作只能由署名者本人完成。
