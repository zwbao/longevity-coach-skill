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
   - `deliver/la-export.json`（格式 `la-export/1`）：标准结果。`readouts` 是每个读数；`organs` 是器官体检表，AI 估计带区间；`board` 是问题看板和每个问题的结论；`plan.items` 是方案，每项有 `executor`（member、nutritionist、physician）和 `kind`（diet、supplement、test、referral 等）；`retests` 是复测计划。
   - `deliver/report.md`：给人看的完整报告，用户想看原文时给他位置。
   - `deliver/twin.json`：这次的快照，路径记进档案，下次复测对比用。
4. 方案按 SKILL.md「深度分析」分：本人和营养师的项给他挑；医生的项和补剂、检查、转诊进问医生的单子。每项的复测写进档案。
5. 复测后又做了一次：`python3 <分析师目录>/scripts/la.py twin compare --prev <上次 twin.json> --cur <这次 twin.json>`。只有 `verdict` 是 `increase_beyond_noise` 或 `decrease_beyond_noise` 的才说是变化；`within_noise` 说"还看不出来"；`not_judged` 两次并排看。`alerts` 先说（比如基因型变了，可能拿错了样本）。
6. 把要点、报告位置、快照路径和复测时间记进档案的「检测和报告」。器官的 AI 估计要说成"AI 估计"，带上区间。

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

## 问医生的单子

写进档案，或者单独存一份 markdown 给他打印：为什么去、相关结果（日期和来源）、在用的药和补剂、想问的问题；深度分析里交给医生的项也列进去。

## 翻译成 Pi 的话

- 先讲和他的画面最相关的一件事，其余按需展开。
- 数字带上不确定性和它是什么："这是用美国人群拟合的模型估计，不是你个人的风险。"
- 技能名、脚本名、文件路径不出现在对话里，除非用户想看。
