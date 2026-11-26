# 短问答（对话里答，不出完整报告）

适用：消息里已经带了这个人的测量值（化验单、甲基化、血浆蛋白、基因表达），只问一个结论：像多少岁、在哪个年龄段、两个人谁更年长、十年后还在不在、大概还能活多久。

不适用：交来一个检测文件夹、要整套报告、数字孪生或复测对比，那是深度分析（01–06）。问「能不能做 CR / 间歇禁食 / HIIT / 补剂或雷帕」等干预建议 → [intervention-advice.md](intervention-advice.md)。问「生物年龄降了吗 / 时钟变化算不算延寿」→ [retest-response.md](retest-response.md)。以上都不走本文的年龄/存活工具。

## 怎么做

1. 先门控再取证（顺序固定）：
   - 会错接的方法先拒：无实足年龄不调 PhenoAge；轮换位点不调固定甲基化时钟；掩蔽基因名不查 OpenGenes/SynergyAge（`la.py method-gate`）。
   - 贴了测量值：调用分析师 `la.py age-evidence`（`--modality labs|methylation|proteome|expression`）。消息很长时用 `--from-transcript`。
   - 掩蔽基因考题散文：`la.py prompt-evidence --kind opengenes-masked`（只解析题面，不查库）。
   - SynergyAge 题面已打印 `% lifespan`：`la.py prompt-evidence --kind synergyage-pairwise`。
   - 死亡两两/二分类/多分类考题：`la.py mortality-evidence --format pairwise|binary|multiclass`（Cox 是证据；有重病史关键词时低置信）。
2. 看结果里读到了多少项（`values_read`、`features_used`、`gsea_pathways_used`），以及是否 `low_confidence` / `confidence: low`。
3. 用工具 JSON 作主要依据，再结合消息里的其他信息：病史、用药、吸烟、体能这些不在模型里，问存活时要自己加进来。Cox 生存曲线是证据，不是最终答案。
4. 工具给出 `looks_older` / `suggested_letter` 且不是低置信：优先采纳。
5. 低置信、证据空、或份额接近 0.5：对人说清「证据不够 / 把握低」；考场单字段可用 `uncertain`。若对方强制只要一个选项，给最可能的那个，并用一句话说把握大小。
6. 不开 `la.py init`，不跑 01–06，不写 `report.html` / `twin.json`。考场答还要过 `la.py protocol-check`。
