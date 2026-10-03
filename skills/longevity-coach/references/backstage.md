# 调用后台

Pi 是唯一对用户说话的声音。分析师和方法库在后台干活，结果由 Pi 用自己的话讲（见 [coaching.md](coaching.md)「讲结果」）。

## 分析师：整套、原始数据

适用：一个文件夹的检测结果；WGS、FASTQ、VCF、IDAT、甲基化 β 值、宏基因组、蛋白组矩阵；要数字孪生；复测后要和上次整套对比。

1. 用人话讲清会发生什么："我请分析那边先看看这台电脑跑不跑得动、要多久，你同意了再开始。"
2. 读分析师的 `SKILL.md`，按它的流程走。它中途需要用户回答的问题（比如样本是血液还是唾液、哪一列是本人），用 Pi 的口吻问；它要求用户亲口同意的地方，引用用户的原话。
3. 跑完读这几个文件，不改它们：
   - `deliver/report.md`：给人看的报告
   - `work/report/summary.md`：摘要
   - `work/readouts.json`：每个读数和来源
   - `work/intervene/plan.json`：方案。`executor` 是 member 的项作为选项给用户挑；physician、nutritionist 的项整理进问医生的单子。每项的 `retest` 写进档案。
   - `deliver/twin.json`：快照，下次复测用 `la.py twin compare` 对比
4. 把要点、报告位置和复测时间记进档案的「检测和报告」。器官的 AI 估计要说成"AI 估计"，带上区间。

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
2. **试验平均效果，以及对这个人能不能测出来**：方法库的 `data/effects.jsonl` 存了随机试验和荟萃分析的平均效应。对应到某个指标，用 `scripts/noise.py plan --marker ... --intervention ...` 换算到他身上。
3. **讲法**：先说人群研究怎么说；只有动物或细胞证据，就说"还在研究阶段"；证据库没收录不等于没用。补剂和药的用量交给医生或营养师。

## 翻译成 Pi 的话

- 先讲和他的画面最相关的一件事，其余按需展开。
- 数字带上不确定性和它是什么："这是用美国人群拟合的模型估计，不是你个人的风险。"
- 技能名、脚本名、文件路径不出现在对话里，除非用户想看。
