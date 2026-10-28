# 主动关怀

Pi 不只在用户来了才开口。到了该复查的时候、做到第 20 次的时候、两周没听到消息的时候，Pi 主动说一句。原则和 [coaching.md](coaching.md) 一样：主动但有分寸，用意义和正反馈推动，不靠愧疚，不轰炸。

这份文件有三部分：消息怎么写（给 Pi）；独立运行时怎么用；判定算法和数据格式（给宿主实现者，网站按这里用 JavaScript 实现同一套逻辑，并通过同一组共享用例）。

## 一、消息怎么写

一条主动消息（`pi-message/1`）有标题、正文、最多 3 个按钮。

**长度**：标题不超过 20 个字，正文不超过 120 个字。

**写法**（沿用 coaching.md）：

- 先说他做到的事，或一句真心关心的话。
- 一条消息只讲一件事。同一天有好几件事，只发最要紧的一条，其余留到下次对话的开场议程。
- 连回他想要的画面（"离带孙子爬泰山又近了一步"）。
- 涉及数字时带标签：统计模型估计、AI 判断、指南标准、CPIC 等。数字只能来自事件负载。
- 不用愧疚和恐吓。禁用的说法见 `data/proactive_policy.json` 的 `forbidden_zh`，例如"你又没做到""失败""再不……就晚了"。

**按类别**：

| 类别 | 触发器 | 怎么写 |
|---|---|---|
| 教练 | `experiment_checkpoint`、`commitment_review`、`milestone`、`checkin_gap`、`return_welcome` | Pi 自由写，草稿只是起点 |
| 关怀 | `life_event_followup` | Pi 自由写，只问候，不顺带布置任务 |
| 提问 | `question_due` | 标题和按钮取自提问库，正文可以改写，但要保留"为什么问"；见下文「提问」 |
| 复测 | `retest_due` | 说这次复查能帮我们确认什么 |
| 数据 | `new_data_ready`、`change_beyond_noise`、`trend_beyond_noise`、`prediction_ready`、`wearable_shift` | 讲变化时，第一句说是不是超出个人正常波动；概率带标签 |
| 临床 | `concordance_transition`、`diagnosis_hit`、`medication_gene_conflict` | 第一句说结论和来源（带标签），提供"整理问医生的单子"按钮；不说"你会得"，不劝停药 |
| 紧急 | `critical_value` | 第一句固定为"建议你现在就拨打 120 或尽快就医"，其余由模板填写，模型不改写 |

### 提问

Pi 偶尔问一个短问题，用来补上计算缺的数据、给正在做的个人实验计数，或者了解他想要的画面。这是为了不像有些手环那样每天问一样的问题、问完没有下文。规则：

- **每个问题都要有用**：答案会补上一项计算要用的数据、推进一个实验，或者是 Pi 之后会用到的事。已经知道的不问（档案里写了吸烟、家族病史，量过腰围，手表有睡眠数据，就跳过）。
- **一次只问一个，并占用当天和本周的提醒名额**：有更要紧的消息（复测、数据、临床）时，问题让路，只进开场议程，第二天再问。
- **说清为什么问**：正文第一句讲这个答案能帮上什么。
- **一点就能答**：最多 3 个按钮；问过的周期性问题，第一个按钮是"和上次一样：…"。
- **越问越少**：答案没变，下次间隔翻倍（30 → 60 → 120 天，最多 180 天）；连续 3 次看到却没回答，这个问题就不再问，除非他在对话里主动答了。
- **答了马上有回音**：回音由 `ack` 生成，数字只来自他自己的数据。例如："记上了，第 4 次。再测 10 次，就能看出减盐对你有没有用。""和上次一样，记上了。下次隔 120 天再问你。"宿主算得出补上这一项能让结果准多少时（例如 LongPi Age 的区间从 ±6.3 缩到 ±5.9 岁），放进 `gaps` 里，回音就说这个。
- **默认关闭**：问过他"我偶尔问你一个小问题，好让结果更准，可以吗？"，他同意后才打开（档案「主动提醒」写"提问 开"；网站写 `consent.question` 并打开 `enabled_triggers.question_due`）。

提问库在 `data/questions.json`，每题写明目的（`experiment` 实验 / `data_gap` 补数据 / `profile` 了解他 / `follow_up` 跟进）、适用宿主、什么情况下跳过、间隔、回答按钮、每个回答记下什么（`sets`）以及回音。加新题时，先回答"这个答案会改变什么"；答不上来就不加。

**推送文字**：锁屏上只显示"Pi 有一件事想和你说"（紧急类为"Pi 有一件要紧的事，请尽快打开看看"），不含任何健康数据和数字。完整内容在打开后显示。

**示例**：

| 触发器 | 标题 | 正文 | 按钮 |
|---|---|---|---|
| `milestone` | 第 20 次！ | 工作日晚饭用限盐勺，你已经做到第 20 次了。离带孙子爬泰山又近了一步。 | 今天也做到了 / 去聊聊 |
| `experiment_checkpoint` | 可以开始后测了 | 减盐已经坚持 6 周了。接下来 14 天每天早上量一次血压，就能看出这次改变对你有没有用。按你的情况，能测出效果的概率约 49%（统计模型估计）。 | 开始后测 / 晚点提醒我 |
| `retest_due` | 下周复查空腹血糖 | 这次复查能帮我们确认之前看到的缓慢上升是不是真的。 | 已预约 / 下周再提醒 / 去聊聊 |
| `checkin_gap` | 最近怎么样？ | 有两周没听你说限盐勺的事了，最近是不是特别忙？要不要把它缩小一点，换成只在周三做？ | 缩小一点 / 去聊聊 / 先不了 |
| `trend_beyond_noise` | 空腹血糖：缓慢上升 | 空腹血糖出现了超出你个人正常波动的缓慢上升。下一次复查可以确认，我们先聊聊可以做点什么。 | 去聊聊 / 看详情 |
| `diagnosis_hit` | 有一项结论值得给医生看 | 空腹血糖 5.6 mmol/L，符合空腹血糖受损（ADA 指南，指南标准）。这需要医生来确认，我可以帮你把要问的整理好。 | 整理问医生的单子 / 去聊聊 |
| `critical_value` | 请马上处理 | 建议你现在就拨打 120 或尽快就医。你刚记录的血压是 185/100 mmHg，已经达到中国高血压防治指南（2018 年修订版）里的危急水平。 | 拨打 120 / 去聊聊 |

改写草稿后，用 `proactive.py lint` 检查一遍（见下）。

## 二、独立运行时怎么用

**每次对话开始**：

```bash
python3 <本技能目录>/scripts/proactive.py scan --member ~/.longevity-coach/<称呼>.md [--export <最近的 la-export.json>] --opening --write
```

输出里的 `agenda` 就是这次的开场议程，按优先级排好，取代"从档案里找该跟进的事"。开场先说一件他做到的事，再从议程里挑最上面的一件跟进。`policy.ask_consent` 为真时，找个合适的时机问一次要不要主动提醒（按类别）；`policy.ask_about_frequency` 为真时，轻轻问一句提醒是不是太多了。`messages` 里 `critical_value` 的消息要最先说。

**可选：定时扫描**。用 cron 或 launchd 每天跑一次，结果写进本地收件箱（独立运行不做推送）：

```bash
python3 <本技能目录>/scripts/proactive.py scan --member ~/.longevity-coach/<称呼>.md --write --inbox ~/.longevity-coach/<称呼>.inbox.json
```

**用户在对话里对某条消息做了操作**（打卡、稍后提醒、这类不再提醒、已预约……），写一个 `pi-action/1` 文件，再：

```bash
python3 <本技能目录>/scripts/proactive.py ack --member ~/.longevity-coach/<称呼>.md --action <action.json> --write
```

打卡会更新档案「小承诺」表里的累计次数，并返回新的次数和一句庆祝语。同一个操作重复回传，结果不变。

**他回答了问题**：点按钮就是一个 `type: answer` 的操作；在对话里口头回答的，同样写一个 `pi-action/1`，不带 `message`，在 `params` 里写 `question` 和 `answer`（答案 id，"和上次一样"写 `same`）。`ack` 返回 `feedback_zh`，照它说；返回的 `record`（如吸烟情况）同时记进档案对应的位置，下次就不会再问。

**改写后检查**：

```bash
python3 <本技能目录>/scripts/proactive.py lint --message <message.json> --event <event.json>
```

**档案里要写成什么样才能被读到**：

- 「基本」：`聊天节奏：大约每 7 天`；`主动提醒：教练 开　复测 开　数据 开　临床 开　关怀 开`（还没问过就留空）；`免打扰：22:00–08:00　时区：Asia/Shanghai`。
- 「近期大事」：`- 2026-10-18 女儿的婚礼`（日期开头）。
- 「小承诺」表：按表头读"承诺""开始""累计次数""状态"（进行中 / 暂停 / 毕业 / 放弃）；复盘记录每行以日期开头，最近一行的日期当作最近一次打卡。
- 「测量」表：`血压` 写成 `185/100`，或者分开写 `收缩压`、`舒张压`；血糖类指标写数值和单位。
- 「个人实验」：一行一个，括号里带编号和数字，例如 `- 减盐看收缩压（X1，开始 2026-07-20，最短 6 周，后测 14 次，已测 0 次，方案项 I3，预测 P1）`。
- 「上次对话」的"日期"。

档案里放不下的东西（已经发过哪些、稍后提醒、这类不再提醒、打卡流水）存在档案旁边的 `<称呼>.proactive.json`，由脚本读写，用户想看也可以看。

## 三、判定算法（宿主实现者读）

### 3.1 会员状态 `pi-state/1`

宿主不需要会员档案，提供同样结构的 JSON 即可。正式 schema：[../schema/pi-state.schema.json](../schema/pi-state.schema.json)。

```json
{
  "schema": "pi-state/1",
  "member": "pi-laowang",
  "host": "standalone | longpi_site",
  "timezone": "Asia/Shanghai",
  "picture_zh": "带孙子爬泰山",
  "last_interaction_at": "2026-10-09T21:00:00+08:00",
  "chat_cadence_days": 7,
  "preferences": {
    "consent": {"coaching": true, "retest": true, "data": true, "clinical": true, "care": true},
    "quiet_hours": {"start": "22:00", "end": "08:00"},
    "caps": {"per_day": 1, "per_week": 3},
    "muted_triggers": [],
    "enabled_triggers": {"wearable_shift": false}
  },
  "commitments": [{"id": "C1", "label_zh": "工作日晚饭用限盐勺", "plan_item": "I3", "status": "active",
                   "started_at": "2026-07-20", "cumulative": 20, "last_checkin_at": "2026-10-11T20:00:00+08:00"}],
  "experiments": [{"id": "X1", "plan_item": "I3", "intervention_zh": "减盐", "marker": "收缩压", "started_at": "2026-07-20",
                   "min_weeks": 6, "repeats_needed": 14, "post_started_at": null, "post_done": 0, "prediction_ref": "P1"}],
  "life_events": [{"id": "L1", "date": "2026-10-18", "label_zh": "女儿的婚礼"}],
  "measurements": [{"id": "m1", "at": "2026-10-12T07:30:00+08:00", "kind": "blood_pressure", "unit": "mmHg",
                    "values": {"sbp": 138, "dbp": 86}}],
  "medications_in_use": [{"name": "simvastatin", "recorded_at": "2026-10-01"}],
  "plan_targets": [{"marker": "收缩压", "plan_item": "I3", "desired": "decrease"}],
  "data_batches": [{"id": "B7", "arrived_at": "2026-10-12T08:00:00+08:00", "kind": "labs"}],
  "wearable": {"resting_hr": {"metric_zh": "静息心率", "baseline": 60, "band_pct": 8, "days": [{"date": "2026-10-12", "value": 63}]}},
  "retests_scheduled": [],
  "export": {"schema": "la-export/2", "generated_at": "...", "retests": [], "trends": [], "concordance": [],
             "predictions": [], "diagnoses": [], "medications": [], "plan": {"items": []}},
  "history": {"fired": [], "messages": [], "actions": []},
  "snoozes": []
}
```

- 时间：带时区的 ISO 时间；只写日期的，按会员时区当天 0 点。
- 网站（`host: longpi_site`）：`commitments` 为 `null`，没有 `experiments`；只运行 `hosts` 含 `longpi_site` 的触发器（数据、复测、临床、紧急类）。
- `export` 可以省略，改用 `scan --export` 传入。读取的 `la-export/2` 字段：`generated_at`；`retests[]` 的 `id`、`marker`、`due_at`、`reason`；`trends[]`（`twin series` 单指标结果）的 `marker`、`pairs[-1]`、`trend.verdict`、`points[-1].t` 或 `observed_at`；`concordance[]` 的 `analyte`、`marker_zh`、`transition {from, to, observed_at}`、`label`；`predictions[]`（`la-prediction/1`）；`diagnoses[]` 的 `id`、`rule`、`hit`、`conclusion_zh`、`source_zh`、`label`；`medications[]` 的 `id`、`drug`、`drug_zh`、`source_type`（`cpic`）或 `label.basis_kind`、`routine`（CPIC 结论是"按常规"时为 `true`）、`label`；`plan.items[].targets`。缺失的字段视为没有。
- `history` 由 `scan` 和 `ack` 的提交写入，宿主保存。宿主把消息实际送达后，把 `history.messages[].status` 改为 `sent`（并写 `sent_at`），打开后为 `read`（`opened_at`）。

### 3.2 `scan` 的步骤

记 `now` 为扫描时间，`today` 为 `now` 在会员时区的日期，日期差都按会员时区的日历日计算。

1. **求值**：对 17 个触发器逐个求值（条件见下表；`question_due` 见 3.7），每个成立的条件生成一个 `pi-event/1`：`priority` 按类别（紧急 100、临床 80、复测 60、数据 50、教练 40、提问 35、关怀 30）；`id = "E-" + occurred_at 的本地日期(YYYYMMDD) + "-" + sha1(dedup_key) 的前 8 位十六进制`；`occurred_at` 为 `now`，`critical_value` 为测量时间。
2. **宿主和开关**：丢掉 `hosts` 不含当前宿主的；丢掉被关闭的（`enabled_triggers[trigger]`，缺省取 `enabled_by_default`；`user_can_disable: false` 的不能关）。
3. **取代**：如果有 `return_welcome`，丢掉 `checkin_gap` 和 `commitment_review`（规则里的 `supersedes`）。
4. **去重**：`dedup_key` 已在 `history.fired` 中的，静默丢弃。
5. **冷却**：同一触发器、同一主体（`subject_key = trigger + ":" + 主体各键按字母序 k=v 用逗号连接`）在 `history.fired` 里最近一次的本地日期距 `today` 少于 `cooldown_days` 天的，记为 `suppressed: cooldown`，不提交（冷却过后会再次出现）。`cooldown_days` 为 `"cadence"` 时取 `chat_cadence_days`；为 `null` 或 0 时不冷却（只靠去重）。
6. **稍后提醒**：`snoozes` 中 `until <= now` 的事件原样重新加入（不经过去重和冷却），提交时从 `snoozes` 移除。
7. **排序**：按 `priority` 降序、`occurred_at` 升序、触发器在规则文件中的顺序、`dedup_key` 升序。
8. **逐个决定**（按上面的顺序）：
   - 紧急类：立刻生成消息，`status: scheduled`，`send_after = now`；不看同意、频控、免打扰、不再提醒。
   - 在 `muted_triggers` 中：`suppressed: muted`，不生成消息，不进议程，不提交。
   - 该类别没有同意（`consent` 为 `null` 视为都没同意；缺某个类别时取 `consent_default`，默认都为 `false`）：生成 `status: suppressed, suppressed_reason: no_consent` 的消息，进议程。
   - 本次扫描已经选过一条非紧急消息：只进议程（合并）。
   - 否则这是本次的那一条：
     - 发送时间：`now` 在免打扰时段内（可以跨午夜）则为时段结束的本地时间，记 `deferred_reason: quiet_hours`；否则为 `now`。
     - 频控：在 `history.messages` 中数非紧急、状态为 `scheduled / sent / read / acted` 的消息：发送时间（`sent_at`，没有则 `send_after`）与本次发送时间同一本地日期的条数 `day`，以及落在（本次发送时间 − 7 天，本次发送时间］内的条数 `week`。`day >= caps.per_day` 或 `week >= caps.per_week`（自动降频时 `per_week` 取 1）则 `suppressed: cap`，进议程。
     - 否则 `status: scheduled`。如果 `expires_at <= send_after`，改为 `suppressed: quiet_hours`。
   - `expires_at = send_after + 类别的 expires_days`（紧急 1、临床 14、复测 7、数据 7、教练 3、提问 1、关怀 2 天）。消息 `id = "M-" + send_after 的本地日期 + "-" + sha1(dedup_key) 前 8 位`。
9. **自动降频**：取 `history.messages` 中非紧急、状态为 `sent / read / acted / expired` 的消息，按发送时间排序，最后 3 条都没打开（状态 `sent` 或 `expired` 且无 `opened_at`）即为降频：每周上限取 1，输出 `policy.ask_about_frequency: true`。有一条被打开后自动恢复。
10. **议程**：本次进议程的事件 + 本次发出的消息对应的事件 + `history.fired` 中 14 天内、未标记 `seen_at`、对应消息没被处理（`acted`）、不在 `muted_triggers` 的事件；按第 7 步的顺序排。`scan --opening` 表示议程已在开场展示，提交时给这些事件写 `seen_at`。
11. **提交**（`commit`）：本次生成消息或进议程的事件写入 `history.fired`（含 `via: message | agenda` 和完整事件）；消息写入 `history.messages`；移除到期的 `snoozes`。

### 3.3 触发条件

| 触发器 | 条件 | `dedup_key` |
|---|---|---|
| `critical_value` | 测量在 24 小时内（只有日期的：今天或昨天），按 `critical_rules`：血压收缩压 > 180 或舒张压 > 120 mmHg；血糖 < 3.0 mmol/L 或 < 54 mg/dL（单位须与规则一致） | `critical_value:<测量 id>:<规则 id>` |
| `concordance_transition` | `transition` 为 `latent → concordant_adverse` | `…:<analyte>:<observed_at>` |
| `diagnosis_hit` | `diagnoses[]` 中 `hit` 不为 `false` | `…:<rule>` |
| `medication_gene_conflict` | 药名（不分大小写）在 `medications_in_use` 中，且该药的 CPIC 条目 `routine` 为 `false` | `…:<药名小写>` |
| `retest_due` | 未在 `retests_scheduled` 中；距 `due_at` 的本地日期 1–7 天为 `pre`，0 到 −6 天为 `due` | `…:<id>:<due_at>:<pre/due>` |
| `new_data_ready` | `data_batches[]` 中 `arrived_at <= now` 的批次；`export.generated_at` 也算一批 | `…:<批次 id>` |
| `change_beyond_noise` | 指标在 `plan_targets` 或 `plan.items[].targets` 中，且 `pairs` 最后一对为 `increase/decrease_beyond_noise`；方向与 `desired` 一致时 `favorable` | `…:<marker>:<from>:<to>` |
| `trend_beyond_noise` | `trend.verdict` 为 `rising/falling_beyond_noise` | `…:<marker>:<最后一个观测日期>` |
| `prediction_ready` | `predictions[]` 有 `p_detect_favorable` | `…:<id>:<label.generated_at>` |
| `wearable_shift`（默认关） | 最近 7 天每天都有数据，7 天均值在 `baseline × (1 ± band_pct%)` 之外，且从今天往回连续 ≥ 3 天在同一侧之外 | `…:<metric>:<最后一天>` |
| `experiment_checkpoint` | 未开始后测且 `(today − started_at) 整除 7 >= min_weeks` → `post_start`；`post_done >= repeats_needed` → `results` | `…:<id>:post_start / results` |
| `return_welcome` | 距 `last_interaction_at` ≥ 30 天 | `…:<上次互动日期>` |
| `commitment_review` | 有进行中的承诺，距上次互动 ≥ `chat_cadence_days` | `…:<上次互动日期>` |
| `checkin_gap` | 进行中的承诺，距 `last_checkin_at`（没有则 `started_at`）≥ 14 天 | `…:<承诺 id>:<那天的日期>` |
| `milestone` | 累计次数达到的最大里程碑 m（1、5、10、20、50、100），且累计次数 − m ≤ 2 | `…:<承诺 id>:<m>` |
| `life_event_followup` | 事件日期后第 1–3 天 | `…:<事件 id>` |
| `question_due`（默认关） | 见 3.7：最多一个，适用且到期的最有用的问题 | `…:<题目 id>:<本地日期>` |

危急阈值的来源（原文摘录见 `data/proactive_rules.json`）：血压取自《中国高血压防治指南（2018 年修订版）》英文版 6.12.1 节对高血压急症的定义（"generally over 180/120 mmHg"，J Geriatr Cardiol 2019，doi:10.11909/j.issn.1671-5411.2019.03.014）；血糖取自美国糖尿病学会《2025 年糖尿病诊疗标准》第 6 章的 2 级低血糖（"<54 mg/dL [<3.0 mmol/L] … requires immediate action"，doi:10.2337/dc25-S006）。家里测得的数值无法区分急症和亚急症，所以消息写"拨打 120 或尽快就医"。

### 3.4 草稿

每个触发器在规则文件里有一组 `drafts`，取第一个 `when` 列出的负载字段都有值的那个；`{名字}` 用"主体 + 负载"的值填入（数字为整数时不带小数点）。按钮 id 依次为 `a1`、`a2`、`a3`。有"打卡"按钮或为 `milestone` 的消息，预先生成 `celebration_zh`（下一次打卡后的累计次数）。`deep_link` 也按模板填。

### 3.5 `lint` 的检查

错误码：`title_length`（1–20 字）、`body_length`（1–120 字）、`too_many_actions`（≤3）、`bad_action`、`bad_snooze`（1/3/7 天）、`number_without_source`（标题和正文里的每个数字，都要等于事件负载或主体里某个数字，允许 ×100 和取绝对值、保留 0–2 位小数；负载字符串里出现的数字也算；紧急类的固定首句不检查）、`number_without_label` 和 `label_not_in_body`（`numbers[]` 每项要有标签，且标签文字出现在正文里）、`missing_label`（临床类、`prediction_ready`、负载里有概率的消息，正文要含一个标签词，负载有 `label_zh` 时要含它）、`missing_doctor_brief`（临床类要有 `prepare_doctor_brief` 按钮）、`noise_first`（`change_beyond_noise`、`trend_beyond_noise`、`wearable_shift` 第一句要含"正常波动"）、`urgent_first_sentence` 和 `urgent_rewritten`（紧急类以固定句开头，且与模板渲染结果完全一致）、`forbidden_word`（每命中一个词一条）、`push_text`（推送文字非空、≤20 字、无数字）、`push_has_health_data`（推送文字里不能出现指标、药名、承诺、事件等）、`event_mismatch`、`category_mismatch`。

### 3.6 `ack`

- 幂等：`idempotency_key`（缺省为 `消息 id:按钮 id`）已在 `history.actions` 中，直接返回第一次的结果并加 `duplicate: true`，状态不变。
- 所有操作：消息 `opened_at` 记为操作时间（已有则不变），`status` 为 `acted`（`read` 为 `read`），写入 `history.actions`（暴露记录和产品指标都从这里取）。
- `checkin`：承诺取 `params.commitment` 或消息主体；累计次数加 `params.count`（默认 1），`last_checkin_at = at`，追加 `checkins` 流水；返回新的 `cumulative` 和 `celebration_zh`（到达里程碑时"第 N 次！离<画面>又近了一步。"，否则"记上了，累计第 N 次！"）；到达里程碑时同时写入 `history.fired`（`via: ack`），之后的扫描不再重复庆祝。
- `snooze`：`params.days` 只能是 1、3、7；把原事件和 `until = at + days` 放进 `snoozes`。
- `mute_trigger`：加入 `muted_triggers`，立即生效；`critical_value` 不能关，报错。
- `schedule_retest`：加入 `retests_scheduled`，之后不再提醒这次复查。
- `start_experiment_phase`：写 `post_started_at`。
- `open_chat`（返回 `context_message`，宿主用这条消息作为开场上下文）、`open_card`、`prepare_doctor_brief`、`call_emergency`：只记录，返回 `next`。
- `read`（不是按钮，宿主报告消息被打开）：只更新状态，用于自动降频。

### 3.7 提问（`question_due`）

- **求值**：每次扫描最多产生一个 `question_due` 事件，主体 `{question}`，`dedup_key = question_due:<题目 id>:<本地日期>`。按提问库顺序逐题判断，留下"适用且到期"的，按（目的顺序 `experiment → data_gap → profile → follow_up`，`weight` 降序（`state.gaps[题目].weight` 可覆盖），最近一次被问的日期升序，库中顺序）取第一个。
- **适用**：宿主在题目 `hosts` 里；`known_if` 指向的状态字段为空；`requires` 成立：`experiment_post_active`（有实验后测已开始且未测够，负载带上 `experiment`、`marker`、`intervention_zh`、`post_done`、`repeats_needed`）、`no_measurement`（`within_days` 天内没有这种测量）、`no_wearable`（`wearable` 里没有这个指标）、`state_equals`（这些状态字段等于给定值，例如问卷只说了"现在不吸烟"时 `profile.smoking` 为 `not_current`，只追问以前吸没吸过）。
- **"问过"**：`history.fired` 里这道题的记录，`via` 为 `message`，或者是已经 `seen_at` 的议程项。只在议程里、没被看到的不算问过。
- **到期**：不重复的题目答过就不再问。看到后没回答的，`min(interval_days, unanswered_retry_days)` 天后可再问。答过的周期题，距最后一次回答满 `interval_days × backoff_factor^(连续相同回答数 − 1)` 天（上限 `max_interval_days`；`backoff: false` 的题目不加倍）。最后一次回答之后、今天之前看到却没回答满 `retire_after_ignored` 次的，不再问（退休）。
- **议程**：同一道题只保留最新的一次；已回答、已退休的不留；本次扫描又问了的，旧的去掉。
- **草稿**：标题、正文按题目模板用负载填写；`same_as_last` 的题目且有上次回答时，第一个按钮是"和上次一样：<上次的答案>"，其余按钮为其他答案；按钮类型都是 `answer`，`params` 为 `{question, answer}`，最多 3 个。
- **`ack` 的 `answer`**：`params.question`（或消息主体）和 `params.answer`（`same` 取上一次的答案）必须是题库里的；写入 `history.answers`（`question`、`answer`、`at`、`message`）；按 `sets` 写状态字段；`effect.experiment_post_done` 给实验后测计数加一；返回 `question`、`answer`、`record`（`sets`）、`feedback_zh`，有 `then` 时返回 `next`。回音：`experiment_progress` 说已测几次、还差几次（测够时说可以看结果了）；`data_gap` 说 `gaps[题目].effect_zh`，没有就说"以后不会再问"；`recurring` 说和上次一样还是不一样，以及下次隔几天；其他就是题目里写好的那句。
- **`lint`**：提问消息至少有一个 `answer` 按钮（`question_no_answer`），每个按钮的 `params` 必须是这道题的答案（`bad_answer`）。

### 3.8 共享用例

`tests/fixtures/proactive_cases.json`（`proactive-cases/1`）。每个用例有初始 `state` 和若干步骤，状态在步骤之间传递（`scan` 之后应用提交，`ack` 之后用返回的新状态）。比较规则：

- `events`：输出事件的 `dedup_key` 列表，顺序一致；`events_triggers`：触发器列表，顺序一致。
- `messages`：条数一致，按顺序逐条比较列出的字段。
- `agenda`：议程的触发器列表，顺序一致。
- `suppressed`：`{trigger, reason}` 列表，顺序一致（冷却、不再提醒、未同意、频控、免打扰过期，按决定的先后）。
- `policy`：列出的字段相等。
- `ack` 步骤：动作里的 `$messages[i].id` 换成上一次扫描输出的第 i 条消息的 id；`expect.error` 为真表示应当拒绝；`expect.result` 比较列出的字段；`expect.state` 用点路径取值（数字为数组下标，`length` 为长度）。
- `lint_cases`：错误码排序后完全一致。
- 另外，每次扫描生成的消息都必须通过 `lint`。
