"""The skill's markdown files link to each other; every relative link must resolve. Run: python3 tests/test_skill_files.py"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1] / "skills" / "longevity-coach"
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


if __name__ == "__main__":
    unittest.main()
