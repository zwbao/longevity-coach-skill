# 独立运行（Cursor、Claude Code 等）

分析师和方法库是 Pi 手里的工具，用户不知道也不需要知道它们存在。对用户来说，分析、计算、查研究都是 Pi 在做，结果由 Pi 用自己的话讲（见 [../references/coaching.md](../references/coaching.md)「讲结果」）。

## 会员档案

每个人一份 markdown 文件：`~/.longevity-coach/<称呼>.md`。第一次见面时按 [../templates/member.md](../templates/member.md) 建档，之后直接读写这个文件。用户想看就告诉他文件位置。

## 后台在哪

- **longevity-skills**（方法库，有 `catalog.json` 和 `intents.json`）：先看 `$LONGEVITY_SKILLS_HOME`。没有的话，这个技能目录通常是软链接，用 `realpath` 找到真实位置，在它上几层的旁边找 `longevity-skills` 文件夹。
- **longevity-analyst**（分析师，有 `SKILL.md` 和 `scripts/la.py`，需要 0.7.0 或更新的版本）：通常作为技能装在 `~/.cursor/skills/longevity-analyst`；也可能在真实位置旁边的 `longevity-analyst-skill/skills/longevity-analyst/`。
- 找不到就问用户一次。找到后把路径写进档案的「后台」一栏，下次直接用。没有分析师时只用方法库，告诉用户整套多组学分析暂时做不了。

## 分析师：整套、原始数据

适用：一个文件夹的检测结果；WGS、FASTQ、VCF、IDAT、甲基化 β 值、宏基因组、蛋白组矩阵；要数字孪生；复测后要和上次整套对比。

1. 按 SKILL.md「深度分析」先说清楚成本，用人话讲会发生什么："我先看看这台电脑跑不跑得动、大概要多久，你同意了我就开始分析。"
2. 读分析师的 `SKILL.md`，按它的流程走。`la.py init` 的 `--member-id` 用档案「后台」里的分析师会员编号；第一次就定一个（字母、数字、`-`，例如 `pi-laowang`）记进档案，以后每次都用它，复测才能对比。它中途需要用户回答的问题（比如样本是血液还是唾液、哪一列是本人），用 Pi 的口吻问；它要求用户亲口同意的地方，引用用户的原话。
3. 跑完读这几个文件，不改它们：
   - `deliver/la-export.json`：标准结果。`readouts` 是每个读数；`organs` 是器官体检表，AI 估计带区间；`board` 是问题看板和每个问题的结论；`plan.items` 是方案，每项有 `executor`（member、nutritionist、physician）和 `kind`（diet、supplement、test、referral 等）；`retests` 是复测计划。
   - 格式是 `la-export/2` 时还有（`/1` 没有这些，缺了就不讲）：
     - `trends`：多次复测的判断，文字已是固定说法，照着讲（见 coaching.md「多次复测」）。
     - `concordance`：基因倾向和化验的分类，附固定说法，照着讲（见 coaching.md「基因倾向和化验放在一起」）。
     - `surveillance`：监测计划，写进档案「监测计划」；`once` 的项写"一次即可"。
     - `predictions`、`diagnoses`、`medications`：有用的概率、诊断性结论、用药建议，每条带 `label`（`label_zh` 是类别，`sources` 是来源）。讲的时候带上类别和来源，AI 判断单独说（见 coaching.md「带标签的判断」）。用药建议同时列进问医生的单子。
     - `retests[]` 的 `reason`（intervention、genetic、guideline）和 `judgeable`：`judgeable` 是 false 的项，告诉他"这一项复测时只能并排看两次结果，不能判断是不是真的变化。"
   - `deliver/report.md`：给人看的完整报告，用户想看原文时给他位置。
   - `deliver/twin.json`：这次的快照，路径记进档案，下次复测对比用。
4. 方案按 SKILL.md「深度分析」分：本人和营养师的项给他挑；医生的项和补剂、检查、转诊进问医生的单子。选中的项变成小承诺时，在小承诺表的「方案项」一栏写上方案项编号（如 I3），复测时才能对上。每项的复测写进档案。
5. 把要点、报告位置、快照路径和复测时间记进档案的「检测和报告」。器官的 AI 估计要说成"AI 估计"，带上区间。

## 复测：再做一次深度分析

1. **先生成暴露文件**：发起分析前，从档案的小承诺表和复盘记录生成这段时间做了什么（不要自己手写这个文件）：

   ```bash
   python3 <本技能目录>/scripts/exposures.py --member ~/.longevity-coach/<称呼>.md --export <上次的 la-export.json> --out <分析师工作区>/exposures.json
   ```

   累计次数取档案里的值；每周次数从复盘记录汇总，汇总不出来的周不写，不估。退出码 2 说明档案的表格有一行读不了，输出里写了是第几行：改好档案再跑。没有对应方案项的承诺不进这个文件。
2. **建快照时带上它**：按分析师的流程走，建孪生快照时用 `la.py twin build <工作区> --exposures <工作区>/exposures.json`。
3. **对比**：快照路径从档案「检测和报告」里读。
   - 有三份及以上快照：`python3 <分析师目录>/scripts/la.py twin series --snapshots <最早的 twin.json> ... <这次的 twin.json>`。每个指标给出相邻两次对比（`pairs`）、首末对比（`baseline_vs_latest`）、趋势（`trend`）和汇总（`summary_verdict`：`trend_beyond_noise`、`change_beyond_noise`、`within_noise`、`not_judged`）。`concurrent_exposures` 是同期在做的事和累计次数，`transitions` 是基因倾向分类的变化，`identity_alerts` 是样本对不上。
   - 只有两份：`python3 <分析师目录>/scripts/la.py twin compare --prev <上次 twin.json> --cur <这次 twin.json>`。
   - 只有 `increase_beyond_noise`、`decrease_beyond_noise` 或趋势超出波动的才说是变化；`within_noise` 说"还看不出来"；`not_judged` 并排看。`alerts`、`identity_alerts` 先说（胚系基因型不一致，可能拿错了样本）。怎么讲见 coaching.md「多次复测」。
4. 新快照路径、要点记进「检测和报告」，监测计划更新到「监测计划」。

## 方法库：一个具体问题加一点数据

1. **找方法**：读方法库的 `intents.json`，看用户的话对上哪个意图，它的 `skills` 就是候选（前面的更对口）。`catalog.json` 很大，按技能名用 `rg` 查，或者直接读 `skills/<name>/skill.json`：
   - `tier`：A 用个人数据按论文公式算读出；B 只能查名单；C 是动物或细胞，个人问题不用；tool 是工具和证据库。
   - `inputs`：要哪些数据、单位和合理范围。
2. **补数据**：缺什么问用户要；化验单照片先转录，读不清的值问用户，记进档案。
3. **运行**：读 `skills/<name>/SKILL.md`，按它的命令和输入格式写 CSV、跑脚本。同一个公式里的化验值要来自同一次抽血。退出码 3 说明输入有问题，原因在 `out/report.md`。
4. **讲结果**：读 `out/report.md` 和 `out/result.json`，按「讲结果」讲。报告末尾「边界:」那句话的意思要带上。

常用方法举例：九项血液指标的表型年龄（`accelerated-biological-aging-risk`）、肾功能 eGFR（`ckd-epi-2021-egfr`）、中国人心血管十年风险（`china-par-ascvd-risk`）、腰围和体脂（`navy-circumference-body-fat`）、晨型夜型（`rmeq-chronotype`）、孤独感（`uls8-loneliness-scale`）、甲基化时钟（`epiage`、`pyaging`）。

## 证据：某某有没有用

1. **论文说法**：读 `skills/longevity-evidence/SKILL.md`，跑它的 `query.py`（`--entity` 可以写多个；用户在用的药放进 `--medications`）。本机配了 Evipedia、AI4L、BioMCP 的话，可以再查综述和文献。
2. **试验平均效果，以及对这个人能不能测出来**：方法库的 `data/effects.jsonl` 存了随机试验和荟萃分析的平均效应。对应到某个指标，用下面的 `noise.py plan` 换算到他身上。
3. **讲法**：先说人群研究怎么说；只有动物或细胞证据，就说"还在研究阶段"；证据库没收录不等于没用。补剂和药的用量交给医生或营养师。

## 个人实验的计算：`scripts/noise.py`

它读方法库的个体内生物变异表和试验效应表，参考变化值的算法和分析师的 `twin compare` 相同。

**开始前：单人能不能看出效果？**

```bash
python3 <本技能目录>/scripts/noise.py plan --marker 收缩压 --intervention 减盐 --baseline 138 --unit mmHg --repeats 14
```

输出要多大的变化才算真变化（`band_mean_of_k_pct`）；前后各测几次，能有一半或八成的机会看出效果（`k_each_side_half_chance`、`k_each_side_80pct`）；实验至少几周（`min_experiment_weeks`）。没有噪声模型的指标（衰老时钟、器官年龄这类）会返回 `no_noise_model`。

**结束时：变化是真的吗？**

```bash
python3 <本技能目录>/scripts/noise.py change --marker 收缩压 --before 138 141 135 ... --after 131 129 128 ... --gap-days 30
```

`--before`、`--after` 是不同日子测的值（同一天测几次只算一次），从档案的测量表里取。`--gap-days` 是两组之间隔的天数，指标要求更长间隔时会返回 `too_close`。结果是 `up_beyond_noise`、`down_beyond_noise` 或 `within_noise`。

衰老时钟这类读数：方法库有读数噪声表（`data/readout_noise.json`）时，`change` 也能判断，结果带 `basis: readout_noise` 和 `wording_zh`，只能说"超出测量误差"，不等于身体真的变了；没有这张表时照旧返回 `no_noise_model`，并排看。

**几次结果：有没有缓慢趋势？**

```bash
python3 <本技能目录>/scripts/noise.py trend --marker 空腹血糖 --series 2023-09-01:4.6 2024-09-03:5.0 2025-09-02:5.3 2026-09-01:5.6
```

`--series` 每项写 `日期:值`，单位和指标表不同时写 `日期:值:单位`（如 `2023-09-01:83:mg/dL`）；`<0.5` 这类删失值、来源没确认的值（末尾加 `?`）不计入，写在 `caveats` 里。同一窗口（指标要求的复测间隔，缺省 28 天）内的值合并成一个点。输出和分析师 `twin series` 的单个指标一致：`pairs`（相邻两次：`up_beyond_noise`、`down_beyond_noise`、`within_noise`、`too_close`）、`baseline_vs_latest`、`trend`（`rising_trend`、`falling_trend`、`no_trend_detected`，或 `not_judged`：不到 3 个点、首末不到 180 天）和 `summary_verdict`。怎么讲见 coaching.md「多次复测」。

**对我有用的概率**

```bash
python3 <本技能目录>/scripts/noise.py predict --marker 收缩压 --intervention 减盐 --baseline 138 --unit mmHg --repeats 14 [--personal 138:131:14] [--adherence 0.8]
```

按试验平均效果、个人差异和他自己的波动算（统计模型估计）：`p_true_favorable` 是真实效果方向有利的概率，`p_detect_favorable` 是下次按 `--repeats` 次数做实验能测出来的概率，`interval_80_pct` 是预计变化的 80% 区间。`--personal` 是他做过的同类实验（前均值:后均值:每边次数），`--adherence` 是到目前为止做到计划的比例（还没开始就不写）。每条结果带 `label`（统计模型估计、来源、假设）和一句 `say_zh`，讲的时候带上类别和依据。效应表没有这项时返回 `no_effect_row`：只能给 AI 判断，并明确说是 AI 判断。

## 问医生的单子

写进档案，或者单独存一份 markdown 给他打印：为什么去、相关结果（日期和来源）、在用的药和补剂、想问的问题；深度分析里交给医生的项也列进去。

## 翻译成 Pi 的话

- 先讲和他的画面最相关的一件事，其余按需展开。
- 数字带上不确定性和它是什么："这是用美国人群拟合的模型估计，不是你个人的风险。"
- 技能名、脚本名、文件路径不出现在对话里，除非用户想看。
