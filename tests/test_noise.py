"""Tests for scripts/noise.py. Run: python3 tests/test_noise.py"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
from datetime import date
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills" / "longevity-coach" / "scripts"))
import noise  # noqa: E402

LIB = next((p / "longevity-skills" for p in ROOT.parents if (p / "longevity-skills" / "data").is_dir()), None)
ANALYST = next((p / "longevity-analyst-skill" / "skills" / "longevity-analyst" for p in ROOT.parents
                if (p / "longevity-analyst-skill").is_dir()), None)
# Shared RCV cases, also run by longevity-analyst (twin compare) and LongPi (reference.ts).
_rcv = [Path(os.environ["LONGEVITY_RCV_CASES"])] if os.environ.get("LONGEVITY_RCV_CASES") else []
if ANALYST:
    _rcv.append(ANALYST.parents[1] / "tests" / "fixtures" / "rcv_cases.json")
RCV_CASES = next((p for p in _rcv if p.is_file()), None)


def run(*argv: str) -> dict:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        noise.main(["--library", str(LIB), *argv])
    return json.loads(out.getvalue())


@unittest.skipUnless(LIB, "longevity-skills not found next to this repo")
class NoiseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.z, cls.idx, _ = noise.load(LIB)

    @unittest.skipUnless(ANALYST, "longevity-analyst not found")
    def test_rcv_matches_analyst_twin_compare(self) -> None:
        sys.path.insert(0, str(ANALYST / "scripts"))
        from lalib.twin import rcv  # type: ignore
        for m in {id(v): v for v in self.idx.values()}.values():
            up, down = noise.rcv(m, self.z)
            ref = rcv(m, self.z)
            self.assertAlmostEqual(up, ref["up_pct"], places=9, msg=m["key"])
            self.assertAlmostEqual(down, ref["down_pct"], places=9, msg=m["key"])

    def test_k_needed_is_the_smallest_k_that_crosses_the_band(self) -> None:
        for name, eff in (("收缩压", -3.0), ("超敏C反应蛋白", -30.0), ("甘油三酯", -20.0), ("LDL-C", -9.0)):
            m = noise.match(self.idx, name)
            k = noise.k_needed(m, self.z, eff)
            self.assertLessEqual(eff, noise.rcv(m, self.z, k, k)[1] + 1e-9, name)
            if k > 1:
                self.assertGreater(eff, noise.rcv(m, self.z, k - 1, k - 1)[1], name)

    def test_change(self) -> None:
        before = [138, 141, 135, 139, 137, 140, 136, 138, 142, 134, 139, 137, 138, 140]
        after = [131, 129, 132, 128, 130, 133, 127, 131, 129, 130, 132, 128, 131, 129]
        args = ["change", "--marker", "收缩压", "--before", *map(str, before), "--after", *map(str, after)]
        self.assertEqual(run(*args, "--gap-days", "30")["verdict"], "down_beyond_noise")
        self.assertEqual(run(*args, "--gap-days", "10")["verdict"], "too_close")
        self.assertEqual(run("change", "--marker", "SBP", "--before", "138", "--after", "131")["verdict"], "within_noise")
        self.assertEqual(run("change", "--marker", "握力", "--before", "38", "--after", "44")["verdict"], "no_noise_model")

    @unittest.skipUnless(RCV_CASES, "rcv_cases.json not found (set LONGEVITY_RCV_CASES)")
    def test_shared_rcv_cases(self) -> None:
        for case in json.loads(RCV_CASES.read_text(encoding="utf-8"))["cases"]:
            gap = (date.fromisoformat(case["cur_date"]) - date.fromisoformat(case["prev_date"])).days
            argv = ["change", "--marker", case["marker"], "--gap-days", str(gap)]
            d = run(*argv, "--before", *map(str, case["before"]), "--after", *map(str, case["after"]))
            self.assertEqual(d["verdict"], case["expect"]["noise"], case["id"])
            if "change_pct" in case and d["verdict"] != "too_close":
                self.assertAlmostEqual(d["change_pct"], case["change_pct"], places=1, msg=case["id"])
                self.assertEqual(d["band_pct"], case["band_pct"], case["id"])
            if "noise_single" in case["expect"]:
                one = run(*argv, "--before", str(case["before"][0]), "--after", str(case["after"][0]))
                self.assertEqual(one["verdict"], case["expect"]["noise_single"], case["id"])
                self.assertEqual(one["band_pct"], case["band_single_pct"], case["id"])

    def test_plan_salt_sbp(self) -> None:
        d = run("plan", "--marker", "收缩压", "--intervention", "减盐", "--baseline", "138", "--unit", "mmHg", "--repeats", "14")
        r = d["effects"][0]
        self.assertEqual(r["id"], "salt-reduction-sbp")
        self.assertAlmostEqual(r["expected_change_pct"], round(100 * -4.18 / 138, 1))
        self.assertEqual(r["verdict"], "unlikely")
        self.assertEqual(d["noise"]["min_experiment_weeks"], 6)

    def test_plan_converts_trial_units(self) -> None:
        d = run("plan", "--marker", "甘油三酯", "--intervention", "鱼油", "--baseline", "1.8", "--unit", "mmol/L")
        r = [e for e in d["effects"] if e["id"] == "omega3-2g-tg"][0]
        self.assertAlmostEqual(r["expected_change_pct"], round(100 * -42.61 * 0.01129 / 1.8, 1))

    def test_plan_edge_cases(self) -> None:
        per = run("plan", "--marker", "收缩压", "--intervention", "减重", "--baseline", "138")["effects"][0]
        self.assertEqual(per["verdict"], "needs_per_units")
        per = run("plan", "--marker", "收缩压", "--intervention", "减重", "--baseline", "138", "--per-units", "3")["effects"][0]
        self.assertAlmostEqual(per["expected_change_pct"], round(100 * -1.05 * 3 / 138, 1))
        self.assertEqual(run("plan", "--marker", "收缩压", "--intervention", "减盐")["effects"][0]["verdict"], "needs_baseline")
        self.assertEqual(run("plan", "--marker", "DunedinPACE")["verdict"], "no_noise_model")


if __name__ == "__main__":
    unittest.main()
