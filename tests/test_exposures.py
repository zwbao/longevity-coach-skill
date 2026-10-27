"""Tests for scripts/exposures.py (member file -> la-exposures/1). Run: python3 tests/test_exposures.py"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "longevity-coach" / "scripts"))
import exposures  # noqa: E402

FIX = ROOT / "tests" / "fixtures"
SCHEMA = next((p / "longevity-analyst-skill" / "skills" / "longevity-analyst" / "schema" / "la-exposures-1.schema.json"
               for p in ROOT.parents if (p / "longevity-analyst-skill").is_dir()), None)
TEMPLATE = ROOT / "skills" / "longevity-coach" / "templates" / "member.md"
NOW = "2026-09-20T10:00:00+08:00"


def run(member_text: str, *extra: str):
    with tempfile.TemporaryDirectory() as tmp:
        m, out = Path(tmp) / "m.md", Path(tmp) / "x.json"
        m.write_text(member_text, encoding="utf-8")
        err, so = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(so):
            code = exposures.main(["--member", str(m), "--out", str(out), "--now", NOW, *extra])
        return code, (json.loads(out.read_text(encoding="utf-8")) if code == 0 else None), err.getvalue(), so.getvalue()


class ExposuresTest(unittest.TestCase):
    member = (FIX / "member_synthetic.md").read_text(encoding="utf-8")

    def test_synthetic_member_file(self) -> None:
        code, doc, _, so = run(self.member, "--export", str(FIX / "export_synthetic.json"))
        self.assertEqual(code, 0)
        self.assertEqual((doc["schema"], doc["member"], doc["source"], doc["generated_at"]),
                         ("la-exposures/1", "pi-laowang", "coach_member_file", NOW))
        items = {i["plan_item"]: i for i in doc["items"]}
        self.assertEqual(set(items), {"I3", "I5"})  # the row without 方案项 is not a plan item
        i3 = items["I3"]
        self.assertEqual((i3["label_zh"], i3["category"], i3["targets"], i3["status"], i3["adopted_at"], i3["cumulative"], i3["origin_snapshot"]),
                         ("工作日晚饭用限盐勺", "diet", ["收缩压"], "adopted", "2026-08-17", 21, "2025-09-02"))
        # 09-13 covered two weeks and the second 09-20 line names two commitments: those weeks are left out, not split
        self.assertEqual(i3["weekly_checkins"], [{"week_start": "2026-08-17", "count": 4}, {"week_start": "2026-08-24", "count": 5},
                                                 {"week_start": "2026-09-14", "count": 3}])
        self.assertEqual((items["I5"]["status"], items["I5"]["weekly_checkins"]), ("paused", [{"week_start": "2026-08-17", "count": 2}]))
        left = json.loads(so)["left_out"]
        self.assertTrue(any("跨了不止一周" in x for x in left))
        self.assertTrue(any("对不上唯一一个承诺" in x for x in left))

    @unittest.skipUnless(SCHEMA and SCHEMA.is_file(), "la-exposures-1.schema.json not found next to this repo")
    def test_output_passes_the_analyst_schema(self) -> None:
        try:
            import jsonschema
        except ImportError:
            self.skipTest("jsonschema not installed")
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        for extra in (("--export", str(FIX / "export_synthetic.json")), ()):
            code, doc, _, _ = run(self.member, *extra)
            self.assertEqual(code, 0)
            jsonschema.Draft202012Validator(schema).validate(doc)

    def test_empty_template_gives_no_items(self) -> None:
        code, doc, _, _ = run(TEMPLATE.read_text(encoding="utf-8"), "--member-id", "pi-test")
        self.assertEqual((code, doc["items"]), (0, []))

    def test_bad_lines_stop_with_the_line_number(self) -> None:
        bad_cells = self.member.replace("| 限盐勺 | 工作日做晚饭时 | 每周 5 次 |", "| 限盐勺 | 工作日做晚饭时 |")
        code, _, err, _ = run(bad_cells)
        self.assertEqual(code, 2)
        self.assertIn("第 14 行", err)
        code, _, err, _ = run(self.member.replace("| 21 | 进行中 |", "| 二十多 | 进行中 |"))
        self.assertEqual(code, 2)
        self.assertIn("累计次数", err)
        code, _, err, _ = run(self.member.replace("| 21 | 进行中 |", "| 21 | 还行 |"))
        self.assertIn("状态", err)
        code, _, err, _ = run(self.member.replace("| 方案项 |", "|"))
        self.assertIn("方案项", err)
        code, _, err, _ = run(self.member.replace("- 分析师会员编号：pi-laowang", ""))
        self.assertIn("会员编号", err)


if __name__ == "__main__":
    unittest.main()
