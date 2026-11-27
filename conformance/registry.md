# OSAP 一致性登记表(Conformance Registry)

> 性质:**非规范性工作文档**。等级定义、测试编号与报告格式的唯一来源是 [`docs/conformance.md`](../docs/conformance.md);本登记表不改变任何一致性等级、编号或语义。
> 更新时间:2026-11-20

---

## 1. 目的与原则

本表记录"声称通过某些 C 等级"的实现,并让每一条声称都**可独立复核**:

1. **可复现闸门**:一条登记必须附带(a)提交时生成的机器可读报告,与(b)一条维护者可在本地重跑并得到相同结果的命令。无法复现的声称不收录;已收录但后来无法复现的,移入 ❌ 除名并在表中留下原因。
2. **登记不是认证**:收录不构成 OSAP 项目的认证、担保或商标/品牌授权,也不代表维护者对实现质量负责。它只声明"该报告在复核时被复现过一次"。
3. **自证要标注**:实现方自己运行并提交的登记标为 `self-attested`;由维护者或第三方独立重跑过的标为 `verified`。两者都是登记表内的记录,不改变用例判定。
4. **报告卫生**:报告 MUST 不包含用户数据、密钥或未脱敏的对象内容(`docs/conformance.md` §6);含敏感内容的报告直接拒绝。

---

## 2. 条目格式

每条登记 = 一份提交到 `conformance/reports/<implementation>-<date>.json` 的报告 + 下表的行。报告必须通过 [`report.schema.json`](report.schema.json) 校验。表中"复现命令"一栏是**闸门本体**:维护者按原样重跑,结果应与报告一致。

| 字段 | 必填 | 说明 |
|---|---|---|
| 实现 | ✅ | 实现名称,建议与仓库名一致 |
| 版本/提交 | ✅ | 可取回的版本标识(commit、tag 或发行版);私有实现至少给出报告日期与联系渠道 |
| 联系 | ✅ | 负责人/Issue 渠道 |
| 等级 | ✅ | 报告覆盖的 C 等级,如 `C0–C7` |
| `bus_visibility` / `state_recovery` / `cf_mode` | | 报告里的三件套,与 `docs/conformance.md` §1 的声明一致 |
| 报告 | ✅ | `reports/` 下的 JSON 路径 |
| 复现命令 | ✅ | 逐字可执行的命令(含依赖来源) |
| 日期 | ✅ | 报告生成日期 |
| 状态 | ✅ | ✅ 已复核 / 🟡 待复核 / ❌ 除名 |

新增登记的 JSON 模板(直接从报告文件摘取,无新增字段):

```json
{
  "implementation": "example-osap-bus",
  "osap": "0.1",
  "generated_at": "2026-11-20T00:00:00+00:00",
  "cases": [],
  "summary": { "total": 68, "pass": 64, "fail": 0, "skip": 4 }
}
```

---

## 3. 登记流程

1. **提交**:PR 附上三样东西——`reports/<implementation>-<date>.json`、本表的表格行、逐字可复现的命令与依赖说明(例如 "Python 3.11+、`pip install -r requirements.txt`、仓库根目录执行")。
2. **复核**(维护者执行,前两项可用 `python3 tools/check_registry.py` 机械化,`--rerun` 额外执行第 3 项):
   - 报告通过 `report.schema.json` 校验;
   - 行/报告一致性:报告摘要与自身 `cases` 数组一致、行内声称的 `N/M pass` 与 manual 用例 id 与报告相符、报告文件名以实现名开头、行日期与 `generated_at` 一致;
   - 用同一套用例重跑复现命令,`pass` / `fail` / `skip` 集合与报告一致(失败用例的 `id` 必须一致);复核器只执行以 `python3 tools/conformance_run.py` 开头的命令,登记条目无法让它运行其他程序;
   - 报告无敏感内容;
   - 版本/提交指向可取回的代码(公开仓库、归档或发行版)。
3. **收录**:全部通过后状态置 ✅;任何一项不通过则 PR 说明原因,不改判定。
4. **除名**:实现方请求移除,或复核重跑与报告不一致时,状态置 ❌ 并写明原因与日期;原报告文件保留,便于审计。
5. **更新**:实现发布新版本后应重新登记;旧条目保留不动,按日期区分。

---

## 4. 登记表

| 实现 | 版本/提交 | 联系 | 等级 | 声明三件套 | 报告 | 复现命令 | 日期 | 状态 |
|---|---|---|---|---|---|---|---|---|
| `osap-reference`(本仓库 `impl/`) | 0.1 Draft(commit `9325514`;0.2 批次 + P1 用例后重登记) | [repo issue](https://github.com/takethegame/open-system-agent-protocol/issues) | C0–C7 automated(70/74 pass,4 manual skip:C2-05、C4-01、C6-08、C7-01) | `bus_visibility=payload`、`state_recovery=durable`、`cf_mode=os_handles` | [`reports/osap-reference-2026-11-27.json`](reports/osap-reference-2026-11-27.json) | `python3 tools/conformance_run.py --impl impl/adapter.py`(仓库根目录,Python 3.11+) | 2026-11-27 | ✅ 已复核(`self-attested`,维护者自证) |

**manual 用例说明**:参考实现的报告覆盖全部 64 条 automated 用例;C2-05(密钥 TTL 上限)、C4-01(跨 App 同意 UI)、C6-08(原生注册表 TTL)、C7-01(跨进程恢复)是 manual,不计入 pass/fail,登记时须如实列出。

---

## 5. 边界

1. 本表不改变 `docs/conformance.md` 的等级、编号或判定;两者冲突时以文档为准。
2. ✅ 只表示"复核者按给定命令重跑出过一次相同结果",不担保实现正确性、安全性或持续一致性。
3. 除名记录与原因永久保留;登记表的历史不做静默改写。
