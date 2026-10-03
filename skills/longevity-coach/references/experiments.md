# 个人实验：你的生活就是实验室

把一个改变设计成有基线、有时长、有事先写好的判定规则的实验，并且在开始前就算清楚：单人做这个实验，有没有机会看出效果。

## 两个数字

- **试验均值**：方法库 `data/effects.jsonl` 里随机试验和荟萃分析给出的平均效应，每条带原文引文和人群描述。这是人群平均，不是这个人的效应。
- **噪声带**：方法库 `data/biological_variation.json` 里每个指标的个体内生物变异（CVI）和分析变异（CVA），算出参考变化值（RCV）。两次测量的差落在噪声带内，就不能说变好或变坏。

单次测量的噪声带：$\mathrm{RCV} = z\sqrt{2}\sqrt{\mathrm{CVI}^2+\mathrm{CVA}^2}$（$z=1.96$；对数正态的指标用不对称形式）。基线和复测各取 $k_1$、$k_2$ 次不同日子的测量平均后，$\sqrt{2}$ 换成 $\sqrt{1/k_1+1/k_2}$，噪声带随之变窄。分析师的 `twin compare` 用的是同一个公式（$k_1=k_2=1$）。

## 设计

```bash
coach experiment design --member <m> --intervention 减盐 --marker 收缩压 --repeats 14
```

每条试验均值都会给出：

- `expected_change_pct`：试验均值换算到这个人基线上的百分比变化（需要基线：先 `measure add`，或用 `--baseline/--unit`）。
- `noise.band_with_repeats_pct`：按计划测量次数算出的噪声带。
- `k_each_side_half_chance`：基线和复测各测几次，真实效应等于试验均值时，大约一半机会越过噪声带。
- `k_each_side_80pct`：各测几次，大约八成机会越过噪声带。
- `verdict`：`likely_detectable` / `coin_flip` / `unlikely_detectable`；`no_noise_model`（没有个体变异数据）；`not_comparable`（标准化效应或速率，换算不到这个人的单位）；`needs_baseline`；`needs_amount`（按每单位给的效应，用 `--per-units` 写计划的量）。
- `requires_professional`：药物或补剂。开始与否和剂量由医生或营养师决定，教练只设计测量。

只给 `--marker` 不给干预时，列出证据库里所有作用于这个指标的试验均值。

## 讲给用户

- `likely_detectable`："按这个测法，如果减盐对你的效果和试验平均差不多，大概率能看出来。"
- `coin_flip`："即使真有效，也只有一半机会看出来。想更稳，就每边多测几次。"
- `unlikely_detectable`，尤其 `advice` 里说试验均值远小于日间波动时："这个改变的平均效果比你身体每天的自然波动还小，自己前后对比看不出来。这种时候信大型试验的平均结果，比信自己的前后对比更靠谱。"做不做这件事，按试验证据和他的偏好决定，不靠单人实验。
- `no_noise_model`（衰老时钟、器官年龄、DunedinPACE 等）："这个读数没有公开的个体内波动数据，两次结果只能并排看，不能说变好变坏。"

## 开始：事先写下判定规则

```bash
coach experiment start <m> --title "减盐六周看晨起收缩压" --intervention 减盐 --marker 收缩压 \
  --weeks 6 --repeats 14 --commitment C1 \
  --rule "复测均值低于基线并超出噪声带就保留；在噪声带内就当作没看出来，继续按试验证据减盐"
```

- 判定规则在看到任何结果之前写下，结束时照规则判断，不临时改规则。
- 基线取开始日期之前最近 `repeats` 次测量；复测窗口是实验最后 `max(14, repeats)` 天，`due` 会提醒补测。
- 关联一个承诺（`--commitment`），复盘时一起看执行率：执行率低于 70% 的实验不能当作这个干预的检验。
- 时长用 `design` 输出的 `suggested_min_weeks`：取试验时长、4 周、「指标最短复测间隔（`min_retest_days`）+ 复测窗口」三者中最长的。短于它的实验，结束时复测离基线太近，`review` 只会给出 `not_judged`；`start` 会警告。
- 测量要来自不同的日子，同一天量三次只算一次（日间波动才是噪声的大头）。

## 复盘和结束

```bash
coach experiment review <m> E1
coach experiment close <m> E1 --outcome keep|drop|inconclusive|extend --note "..."
```

- `too_early`：复测窗口还没开始，不下结论。
- 结果超出噪声带、方向和预期一致：可以说"这次看到了真变化"，但别说"证明了减盐对你有效"，因为同期其他改变也可能起作用。
- 在噪声带内：说"没看出来"，不说"没用"。然后回到事先写的规则。
- 每次结束都问他的感受和代价（"限盐这六周，吃饭还开心吗？"）。坚持得住，比数字漂亮更重要。

## 边界

- 不设计药物或补剂的剂量；这类实验只在医生或营养师同意后做测量设计。
- 孕期、未成年、进食障碍风险（体重过低还想断食）不做饮食限制类实验，见 [safety.md](safety.md)。
- 实验不替代治疗。血压、血糖等已经到了需要医生处理的程度，先就诊。
