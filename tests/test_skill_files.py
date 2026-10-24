"""The skill's markdown files link to each other; every relative link must resolve. Run: python3 tests/test_skill_files.py"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "longevity-coach"
EVALS = REPO / "evals"
# PLAN WS-J.2: conversation evals run in standalone mode (the proactive ones are added by WS-M.7)
CONVERSATION_EVALS = ["within-noise-no-better", "slow-drift-wording", "concurrent-not-causal", "latent-wording", "apoe-consent",
                      "pgx-labeled", "dose-request", "prediction-labeled", "diagnosis-labeled", "deep-analysis-consent-once",
                      "physician-item-not-commitment", "emergency-first", "return-no-guilt", "once-is-enough"]
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")


class SkillFilesTest(unittest.TestCase):
    def test_relative_links_resolve(self) -> None:
        broken = []
        for md in SKILL.rglob("*.md"):
            for target in LINK.findall(md.read_text(encoding="utf-8")):
                if re.match(r"[a-z]+://", target):
                    continue
                if not (md.parent / target).resolve().exists():
                    broken.append(f"{md.relative_to(SKILL)} -> {target}")
        self.assertEqual(broken, [])

    def test_frontmatter_names_the_skill_and_its_version(self) -> None:
        head = (SKILL / "SKILL.md").read_text(encoding="utf-8").split("---")[1]
        self.assertRegex(head, r"\nname: longevity-coach\n")
        self.assertRegex(head, r'\n\s+version: "\d+\.\d+\.\d+"')

    def test_each_host_has_an_adapter(self) -> None:
        body = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        for host in ("standalone", "longpi"):
            self.assertIn(f"hosts/{host}.md", body)
            self.assertTrue((SKILL / "hosts" / f"{host}.md").is_file())

    def test_longpi_adapter_never_runs_the_analyst_directly(self) -> None:
        text = (SKILL / "hosts" / "longpi.md").read_text(encoding="utf-8")
        self.assertIn("run_deep_analysis", text)
        self.assertRegex(text, r"绝不在这之前自己加载 longevity-analyst 或运行 `la\.py`")


    def test_scripts_named_in_the_docs_exist(self) -> None:
        text = (SKILL / "hosts" / "standalone.md").read_text(encoding="utf-8")
        for script in set(re.findall(r"scripts/(\w+\.py)", text)):
            if "<分析师目录>/scripts/" + script in text:
                continue
            self.assertTrue((SKILL / "scripts" / script).is_file(), script)
        for needed in ("exposures.py --member", "twin build", "--exposures", "twin series --snapshots", "noise.py trend", "noise.py predict"):
            self.assertIn(needed, text)

    def test_member_template_has_the_fixed_structures(self) -> None:
        text = (SKILL / "templates" / "member.md").read_text(encoding="utf-8")
        self.assertIn("| 承诺 | 当…时 | 频率 | 开始 | 累计次数 | 状态 | 方案项 |", text)
        self.assertIn("## 监测计划", text)

    def test_fixed_wordings_are_in_the_coaching_reference(self) -> None:
        text = (SKILL / "references" / "coaching.md").read_text(encoding="utf-8")
        for phrase in ("超出你个人正常波动的缓慢上升", "下一次复测可以确认", "同期你在做",
                       "你的基因没有变，变的是我们对这个倾向在你身上有没有表现出来的判断。", "测一次即可",
                       "基因分值只能解释这一项差异的一部分。", "统计模型估计", "AI 判断", "CPIC 指南"):
            self.assertIn(phrase, text)

    def test_evals_follow_the_plugin_eval_layout(self) -> None:
        manifest = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["name"], "longevity-coach")
        cases = [d for d in EVALS.iterdir() if d.is_dir() and d.name not in ("results", "mocks")]
        for name in CONVERSATION_EVALS:
            self.assertIn(name, [d.name for d in cases])
        for d in cases:
            self.assertTrue((d / "prompt.md").is_file() or (d / "case.yaml").is_file(), d.name)
            graders = list((d / "graders").glob("*.md"))
            self.assertTrue(graders, d.name)
            for g in graders:
                head = g.read_text(encoding="utf-8").split("---")[1]
                self.assertRegex(head, r"\ntype: \"?(regex|llm|tool_used|tool_order|file_exists|baseline)\"?\n", g)
            if (d / "case.yaml").is_file():
                self.assertRegex((d / "case.yaml").read_text(encoding="utf-8"), rf"\nname: {re.escape(d.name)}\n")


if __name__ == "__main__":
    unittest.main()
