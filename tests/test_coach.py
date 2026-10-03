"""Tests for the longevity-coach harness. Run: python3 -m unittest discover -s tests"""
from __future__ import annotations

import contextlib
import datetime as dt
import io
import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "longevity-coach" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import coach  # noqa: E402

LIB = coach._discover("library")
ANALYST = coach._discover("analyst")


def run(*argv: str) -> dict:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = coach.main(list(argv))
    if code:
        raise coach.CoachError(json.loads(err.getvalue())["error"], code)
    return json.loads(out.getvalue())


def days_ago(n: int) -> str:
    return (dt.date.today() - dt.timedelta(days=n)).isoformat()


@unittest.skipUnless(LIB, "longevity-skills library not found")
class CoachTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["LONGEVITY_COACH_HOME"] = self.tmp.name
        coach._CACHE.clear()
        run("setup", "--library", str(LIB))
        run("init", "m1", "--name", "测试", "--age", "52", "--sex", "男")

    def tearDown(self) -> None:
        self.tmp.cleanup()
        os.environ.pop("LONGEVITY_COACH_HOME", None)

    def measure(self, marker: str, value: float, unit: str, date: str) -> dict:
        return run("measure", "add", "m1", "--marker", marker, "--value", str(value), "--unit", unit,
                   "--date", date, "--source", "test")

    # ---- noise band

    @unittest.skipUnless(ANALYST, "longevity-analyst not found")
    def test_rcv_matches_analyst_twin(self) -> None:
        sys.path.insert(0, str(ANALYST / "scripts"))
        from lalib.twin import rcv  # type: ignore
        z, idx = coach.biovar(LIB)
        for m in {id(v): v for v in idx.values()}.values():
            up, down = coach.rcv_pct(m, z)
            ref = rcv(m, z)
            self.assertAlmostEqual(up, ref["up_pct"], places=9, msg=m["key"])
            self.assertAlmostEqual(down, ref["down_pct"], places=9, msg=m["key"])

    def test_k_needed_is_the_smallest_k_that_crosses_the_band(self) -> None:
        z, idx = coach.biovar(LIB)
        for key, eff in (("收缩压", -3.0), ("超敏C反应蛋白", -30.0), ("甘油三酯", -20.0), ("低密度脂蛋白胆固醇", -9.0)):
            m = coach.match_bv(idx, key)
            k = coach.k_needed(m, z, eff)
            self.assertLessEqual(eff, coach.rcv_pct(m, z, k, k)[1] + 1e-9, key)
            if k > 1:
                self.assertGreater(eff, coach.rcv_pct(m, z, k - 1, k - 1)[1], key)

    def test_compare_single_vs_averaged(self) -> None:
        base = [138, 141, 135, 139, 137, 140, 136, 138, 142, 134, 139, 137, 138, 140]
        cur = [131, 129, 132, 128, 130, 133, 127, 131, 129, 130, 132, 128, 131, 129]
        for i, v in enumerate(base):
            self.measure("收缩压", v, "mmHg", days_ago(70 - i))
        for i, v in enumerate(cur):
            self.measure("收缩压", v, "mmHg", days_ago(20 - i))
        avg = run("compare", "m1", "--marker", "收缩压", "--k", "14")
        self.assertEqual(avg["verdict"], "decrease_beyond_noise")
        one = run("compare", "m1", "--marker", "SBP")
        self.assertEqual(one["verdict"], "within_noise")

    def test_compare_without_noise_model_is_not_judged(self) -> None:
        self.measure("握力", 38, "kg", days_ago(40))
        self.measure("握力", 44, "kg", days_ago(1))
        self.assertEqual(run("compare", "m1", "--marker", "握力")["verdict"], "not_judged")

    # ---- experiments

    def test_design_salt_sbp(self) -> None:
        d = run("experiment", "design", "--intervention", "减盐", "--marker", "收缩压", "--repeats", "7",
                "--baseline", "138", "--unit", "mmHg")
        r = d["effects"][0]
        self.assertEqual(r["id"], "salt-reduction-sbp")
        self.assertAlmostEqual(r["expected_change_pct"], round(100 * -4.18 / 138, 1))
        self.assertEqual(r["verdict"], "unlikely_detectable")
        self.assertGreater(r["k_each_side_80pct"], r["k_each_side_half_chance"])

    def test_design_converts_trial_units(self) -> None:
        self.measure("甘油三酯", 1.8, "mmol/L", days_ago(3))
        d = run("experiment", "design", "--member", "m1", "--intervention", "鱼油", "--marker", "甘油三酯")
        r = [x for x in d["effects"] if x["id"] == "omega3-2g-tg"][0]
        self.assertAlmostEqual(r["expected_change_pct"], round(100 * -42.61 * 0.01129 / 1.8, 1))
        self.assertIn("requires_professional", r)

    def test_design_marker_without_noise_model(self) -> None:
        self.assertEqual(run("experiment", "design", "--marker", "DunedinPACE")["verdict"], "no_noise_model")

    def test_experiment_review_waits_for_follow_up_window(self) -> None:
        self.measure("收缩压", 138, "mmHg", days_ago(3))
        out = run("experiment", "start", "m1", "--title", "t", "--intervention", "减盐", "--marker", "收缩压",
                  "--weeks", "6", "--rule", "r", "--start", days_ago(1))
        self.assertEqual(out["warnings"], [])
        self.assertEqual(run("experiment", "review", "m1", "E1")["verdict"], "too_early")
        short = run("experiment", "start", "m1", "--title", "t", "--intervention", "减盐", "--marker", "收缩压",
                    "--weeks", "4", "--rule", "r")
        self.assertTrue(any("至少要 6 周" in w for w in short["warnings"]))

    # ---- commitments

    def test_commitments(self) -> None:
        out = run("commit", "add", "m1", "--area", "diet", "--action", "限盐勺", "--when", "做晚饭时",
                  "--cadence", "daily", "--confidence", "5")
        self.assertTrue(out["warnings"])
        chk = run("commit", "check", "m1", "C1", "--times", "5", "--period", "7")
        self.assertEqual(chk["adherence_28d"]["rate"], round(5 / 7, 2))
        run("commit", "add", "m1", "--area", "exercise", "--action", "游泳", "--when", "周二周四下班后",
            "--cadence", "2x/week")
        with self.assertRaises(coach.CoachError):
            run("commit", "check", "m1", "C2", "--done", "yes")
        chk = run("commit", "check", "m1", "C2", "--times", "1", "--period", "7")
        self.assertEqual(chk["adherence_28d"]["rate"], 0.5)

    def test_celebrations_and_wins(self) -> None:
        run("commit", "add", "m1", "--area", "exercise", "--action", "游泳", "--when", "周二周四下班后",
            "--cadence", "2x/week", "--start", days_ago(40))
        first = run("commit", "check", "m1", "C1", "--times", "1", "--period", "7", "--date", days_ago(35))["celebrate"]
        self.assertTrue(any("第 1 次" in c for c in first))
        self.assertTrue(any("部分做到" in c for c in first))
        run("commit", "check", "m1", "C1", "--times", "0", "--period", "7", "--date", days_ago(28))
        back = run("commit", "check", "m1", "C1", "--times", "2", "--period", "7", "--date", days_ago(21))["celebrate"]
        self.assertTrue(any("第 3 次" in c for c in back))
        self.assertTrue(any("重新开始" in c for c in back))
        self.assertTrue(any("执行率最高" in c for c in back))
        self.assertTrue(any("完全做到" in c for c in back))
        run("session-close", "m1", "--summary", "s", "--next", "n")
        st = coach.load_state(Path(self.tmp.name), "m1")
        st["last_session"]["t"] = days_ago(15)
        coach.save_state(Path(self.tmp.name), "m1", st)
        run("commit", "check", "m1", "C1", "--times", "2", "--period", "7", "--date", days_ago(7))
        self.measure("收缩压", 130, "mmHg", days_ago(2))
        wins = run("brief", "m1")["wins"]
        self.assertEqual(wins["commitments"][0]["done_since"], 2)
        self.assertEqual(wins["commitments"][0]["milestones_crossed"], [5])
        self.assertEqual(wins["measurements_logged"], {"收缩压": 1})

    # ---- measurement guards

    def test_measure_guards(self) -> None:
        with self.assertRaises(coach.CoachError):
            self.measure("收缩压", 130, "mmHg", (dt.date.today() + dt.timedelta(days=3)).isoformat())
        with self.assertRaises(coach.CoachError):
            run("measure", "add", "m1", "--marker", "CRP", "--value", "<0.5", "--unit", "mg/L", "--source", "x")
        self.assertEqual(self.measure("hs-CRP", 1.2, "mg/L", days_ago(1))["measurement"]["key"], "crp")
        self.assertIn("skipped", self.measure("hs-CRP", 1.2, "mg/L", days_ago(1)))

    # ---- routing and the method library

    def test_route(self) -> None:
        self.assertEqual(run("route", "最近胸口痛")["next"][:12], "safety_first")
        r = run("route", "NMN 有用吗")
        self.assertEqual(r["intents"][0]["id"], "intervention_evidence")
        self.assertIn("nmn", r["intents"][0]["entities"])
        r = run("route", "我的 INR 偏高")
        self.assertFalse(any("nr" in i["entities"] for i in r["intents"]))
        self.assertTrue(run("route", "这是我的 WGS 和甲基化文件夹")["next"].startswith("analyst"))

    def test_prepare_phenoage(self) -> None:
        rows = [("白蛋白", 44.1, "g/L"), ("肌酐", 68, "umol/L"), ("空腹血糖", 5.4, "mmol/L"), ("超敏C反应蛋白", 1.2, "mg/L"),
                ("淋巴细胞百分比", 31.5, "%"), ("平均红细胞体积", 91.2, "fL"), ("红细胞分布宽度", 13.1, "%"),
                ("碱性磷酸酶", 78, "U/L"), ("白细胞", 5.8, "10^9/L")]
        for name, v, u in rows:
            self.measure(name, v, u, days_ago(5))
        p = run("prepare", "m1", "--skill", "accelerated-biological-aging-risk")
        self.assertEqual(p["missing_required"], [])
        self.assertIn("--age 52", p["command"])
        self.assertIn("--sex male", p["command"])
        csv = (Path(p["run_dir"]) / "measurements.csv").read_text(encoding="utf-8")
        self.assertIn("C反应蛋白,1.2,mg/L", csv)
        r = run("route", "我的生物年龄", "--member", "m1")
        first = r["intents"][0]["skills"][0]
        self.assertEqual((first["name"], first["readiness"]["status"]), ("accelerated-biological-aging-risk", "ready"))

    # ---- analyst import

    def test_import_analyst(self) -> None:
        ws = Path(self.tmp.name) / "ws"
        (ws / "deliver").mkdir(parents=True)
        t = days_ago(10)
        twin = {
            "schema": "la-twin/1", "member": {"id": "m1"}, "identity": {"answer": "consistent"},
            "snapshot": {"t": t},
            "observations": [{"t": t, "marker": "甘油三酯", "value": "2.1", "unit": "mmol/L", "source_file": "F001"},
                             {"t": t, "marker": "糖化血红蛋白", "value": "<4", "unit": "%", "source_file": "F001"},
                             {"t": t, "marker": "肌酐", "value": "70", "unit": "umol/L", "source_file": "F009",
                              "provenance_uncertain": True}],
            "readouts": [{"id": "epiage.dunedinpace", "label_zh": "DunedinPACE", "value": 1.08, "unit": ""}],
            "organ_estimates": [{"id": "organ.liver.age", "label_zh": "肝脏年龄", "value": 55, "low": 50, "high": 61,
                                 "unit": "岁", "kind": "llm_estimate"}],
            "data_files": [{"id": "F002", "kind": "methylation_beta"}, {"id": "F003", "kind": "variants_vcf", "excluded": True}],
            "interventions": [{"id": "I1", "category": "exercise", "action_zh": "抗阻训练", "targets": [], "executor": "member"},
                              {"id": "I2", "category": "referral", "action_zh": "请医生评估", "targets": [], "executor": "physician"}],
            "retest_plan": [{"intervention": "I1", "what": "甘油三酯", "after_weeks": 12}],
        }
        (ws / "deliver" / "twin.json").write_text(json.dumps(twin, ensure_ascii=False), encoding="utf-8")
        out = run("import-analyst", "m1", str(ws))
        self.assertEqual(out["added"], {"measurements": 1, "readouts": 2, "proposals": 2, "retests": 1})
        self.assertEqual(out["visit"]["data_types"], ["methylation"])
        self.assertEqual(run("import-analyst", "m1", str(ws))["added"],
                         {"measurements": 0, "readouts": 0, "proposals": 0, "retests": 0})
        st = coach.load_state(Path(self.tmp.name), "m1")
        self.assertTrue([r for r in st["readouts"] if r["ref"] == "organ.liver.age"][0]["ai_estimate"])
        self.assertEqual(st["retests"][0]["due"], (dt.date.fromisoformat(t) + dt.timedelta(weeks=12)).isoformat())
        with self.assertRaises(coach.CoachError):
            run("commit", "add", "m1", "--area", "medical", "--action", "x", "--when", "y", "--cadence", "weekly",
                "--from-proposal", "P2")
        run("proposal", "set", "m1", "P2", "--status", "asked_professional")
        due = {d["kind"] for d in run("due", "m1")["due"]}
        self.assertIn("proposal", due)  # P1 is still waiting for the member's choice

    # ---- sessions, memory, deletion

    def test_brief_modes_and_life_events(self) -> None:
        self.assertEqual(run("brief", "m1")["mode"], "onboarding")
        run("goal", "add", "m1", "--picture", "爬泰山", "--why", "父亲")
        run("remember", "m1", "--kind", "life_event", "--text", "女儿婚礼",
            "--date", (dt.date.today() + dt.timedelta(days=10)).isoformat())
        run("session-close", "m1", "--summary", "s", "--next", "n")
        b = run("brief", "m1")
        self.assertEqual(b["mode"], "open")
        self.assertEqual(b["due"][0]["kind"], "life_event")

    def test_forget(self) -> None:
        j = run("remember", "m1", "--kind", "story", "--text", "秘密")["remembered"]["id"]
        run("forget", "m1", "--id", j)
        run("dossier", "m1")
        text = (Path(self.tmp.name) / "members" / "m1" / "dossier.md").read_text(encoding="utf-8")
        self.assertNotIn("秘密", text)
        with self.assertRaises(coach.CoachError):
            run("forget", "m1", "--everything", "--confirm", "wrong")
        run("forget", "m1", "--everything", "--confirm", "m1")
        self.assertFalse((Path(self.tmp.name) / "members" / "m1").exists())


if __name__ == "__main__":
    unittest.main()
