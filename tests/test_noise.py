"""Tests for scripts/noise.py. Run: python3 tests/test_noise.py"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
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


def shared(name: str, env: str):
    """A shared fixture of longevity-analyst-skill (tests/fixtures/<name>), or the file the env variable names."""
    c = [Path(os.environ[env])] if os.environ.get(env) else []
    if ANALYST:
        c.append(ANALYST.parents[1] / "tests" / "fixtures" / name)
    return next((p for p in c if p.is_file()), None)


TREND_CASES = shared("trend_cases.json", "LONGEVITY_TREND_CASES")
PREDICTION_CASES = shared("prediction_cases.json", "LONGEVITY_PREDICTION_CASES")


def run(*argv: str, lib: Path = None) -> dict:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        noise.main(["--library", str(lib or LIB), *argv])
    return json.loads(out.getvalue())


def temp_library(tmp: str, effects_patch: dict = None, readout_noise: dict = None) -> Path:
    """A copy of the library's two tables, optionally with extra effect fields or a readout noise table."""
    lib = Path(tmp)
    (lib / "data").mkdir()
    (lib / "data" / "biological_variation.json").write_text((LIB / "data" / "biological_variation.json").read_text(encoding="utf-8"), encoding="utf-8")
    rows = [json.loads(l) for l in (LIB / "data" / "effects.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    for r in rows:
        r.update((effects_patch or {}).get(r["id"], {}))
    (lib / "data" / "effects.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    if readout_noise:
        (lib / "data" / "readout_noise.json").write_text(json.dumps(readout_noise, ensure_ascii=False), encoding="utf-8")
    return lib


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


    # ---- trend (PLAN WS-A.3) ----

    @unittest.skipUnless(TREND_CASES, "trend_cases.json not found (set LONGEVITY_TREND_CASES)")
    def test_shared_trend_cases(self) -> None:
        cases = json.loads(TREND_CASES.read_text(encoding="utf-8"))
        self.assertEqual(cases["schema"], "trend-cases/1")
        for case in cases["cases"]:
            series = [f"{o['t']}:{o['value']}" + (f":{o['unit']}" if o.get("unit") else "") + ("?" if o.get("provenance_uncertain") else "")
                      for o in case["series"]]
            d = run("trend", "--marker", case["marker"], "--series", *series, "--z-trend", str(cases["z_trend"]))
            exp, num = case["expect"]["coach"], case["numbers"]
            self.assertEqual(d["pairs"][-1]["verdict"], exp["pairs_last"], case["id"])
            self.assertEqual(d["trend"]["verdict"], exp["trend"], case["id"])
            self.assertEqual(d["summary_verdict"], case["expect"]["analyst"]["summary_verdict"], case["id"])
            self.assertEqual(len(d["points"]), num["points"], case["id"])
            self.assertAlmostEqual(d["band_single_pct"][1], num["single_rcv_up_pct"], delta=0.1, msg=case["id"])
            self.assertAlmostEqual(d["baseline_vs_latest"]["change_pct"], num["first_vs_latest_pct"], delta=0.1, msg=case["id"])
            if "z_slope" in num:
                self.assertAlmostEqual(d["trend"]["z"], num["z_slope"], delta=0.1, msg=case["id"])
                self.assertAlmostEqual(d["trend"]["slope_per_year"], num["slope_per_year"], delta=0.01, msg=case["id"])
                self.assertAlmostEqual(d["trend"]["annual_change_pct"], num["annual_change_pct"], delta=0.1, msg=case["id"])
            if "trend_not_judged_reason" in case["expect"]:
                self.assertEqual(d["trend"]["reason"], case["expect"]["trend_not_judged_reason"], case["id"])
            for c in case["expect"].get("caveats", []):
                self.assertIn(c, d["caveats"], case["id"])
            # pair verdicts line up with the analyst's, in the coach's words
            words = {"increase_beyond_noise": "up_beyond_noise", "decrease_beyond_noise": "down_beyond_noise",
                     "within_noise": "within_noise", "not_judged": "too_close"}
            self.assertEqual([p["verdict"] for p in d["pairs"]], [words[v] for v in case["expect"]["analyst"]["pairs"]], case["id"])

    def test_trend_edge_cases(self) -> None:
        self.assertEqual(run("trend", "--marker", "握力", "--series", "2024-01-01:38", "2025-01-01:40")["verdict"], "no_noise_model")
        one = run("trend", "--marker", "空腹血糖", "--series", "2024-01-01:5.0")
        self.assertEqual((one["summary_verdict"], one["trend"]["reason"]), ("not_judged", "fewer_than_3_points"))
        back = run("trend", "--marker", "空腹血糖", "--series", "2024-01-01:5.0", "2024-07-01:6.0", "2025-01-01:5.1",
                   "--z-trend", "2.576")
        self.assertEqual(back["summary_verdict"], "change_beyond_noise")
        self.assertIn("returned_within_noise", back["caveats"])
        with self.assertRaises(SystemExit):
            run("trend", "--marker", "空腹血糖", "--series", "去年:5.0")

    # ---- clock readouts with a readout noise table (PLAN WS-B.3, format A.7) ----

    def test_change_on_a_clock_uses_the_readout_noise_table_when_present(self) -> None:
        argv = ["change", "--marker", "Horvath", "--before", "50.0", "--after", "55.0"]
        with tempfile.TemporaryDirectory() as tmp:  # without a readout table clocks stay unjudged
            self.assertEqual(run(*argv, lib=temp_library(tmp))["verdict"], "no_noise_model")
        table = {"schema": "longevity-readout-noise/1", "z": 1.96, "readouts": [
            {"key": "horvath", "match": ["epiage.horvath", "Horvath"], "unit": "岁", "noise_kind": "technical_replicate",
             "sd_abs": 1.5, "tissue": "whole_blood", "platform": ["450k", "EPIC"],
             "source": {"title": "synthetic test entry", "doi": "10.0000/test", "quote": "SD 1.5 years", "quote_location": "test"}},
            {"key": "hannum", "match": ["Hannum"], "unit": "岁", "noise_kind": "test_retest", "icc": 0.9,
             "source": {"title": "synthetic test entry", "doi": "10.0000/test", "quote": "ICC 0.9", "quote_location": "test"}}]}
        with tempfile.TemporaryDirectory() as tmp:
            lib = temp_library(tmp, readout_noise=table)
            d = run(*argv, lib=lib)  # band = 1.96 × √2 × 1.5 ≈ 4.16 years
            self.assertEqual((d["verdict"], d["basis"], d["band_abs"]), ("up_beyond_noise", "readout_noise", [-4.16, 4.16]))
            self.assertIn("超出测量误差", d["wording_zh"])
            self.assertEqual(run("change", "--marker", "epiage.horvath", "--before", "50", "--after", "53", lib=lib)["verdict"], "within_noise")
            self.assertEqual(run("change", "--marker", "Hannum", "--before", "50", "--after", "60", lib=lib)["verdict"], "no_noise_model")
            self.assertEqual(run("change", "--marker", "收缩压", "--before", "138", "--after", "131", lib=lib)["verdict"], "within_noise")

    # ---- personal response prediction (PLAN WS-L.2, appendix B.7) ----

    @unittest.skipUnless(PREDICTION_CASES, "prediction_cases.json not found (set LONGEVITY_PREDICTION_CASES)")
    def test_shared_prediction_cases(self) -> None:
        cases = json.loads(PREDICTION_CASES.read_text(encoding="utf-8"))
        self.assertEqual(cases["schema"], "prediction-cases/1")
        rows = {e["id"]: e for e in (json.loads(l) for l in (LIB / "data" / "effects.jsonl").read_text(encoding="utf-8").splitlines() if l.strip())}
        for case in cases["cases"]:
            row = rows[case["effects_id"]]
            self.assertEqual((row["effect"]["value"], row["effect"]["ci"]), (case["effect"]["value"], case["effect"]["ci"]), case["id"])
            m = noise.match(self.idx, case["marker"])
            self.assertEqual(m["better"] == "lower", case["lower_is_better"], case["id"])
            argv = ["predict", "--marker", case["marker"], "--intervention", row["intervention_zh"], "--baseline", str(case["baseline"]),
                    "--unit", row["effect"]["unit"], "--repeats", str(case["repeats_each_side"])]
            if case["adherence"] != 1.0:
                argv += ["--adherence", str(case["adherence"])]
            if case["personal"]:
                # before/after means that give the case's change_pct
                argv += ["--personal", *[f"100:{100 + p['change_pct']}:{p['repeats_each_side']}" for p in case["personal"]]]
            with tempfile.TemporaryDirectory() as tmp:
                lib = temp_library(tmp, {case["effects_id"]: {"tau_pct": case["tau_pct"]}} if case["tau_pct"] is not None else None)
                d = run(*argv, lib=lib)
            r = next(p for p in d["predictions"] if p["effects_id"] == case["effects_id"])
            exp, mod, pred = case["expect"], r["model"], r["prediction"]
            for k in ("mu0_pct", "s0_pct", "band_pct", "posterior_mu_pct", "posterior_s_pct"):
                self.assertAlmostEqual(mod[k], exp[k], delta=0.1, msg=f"{case['id']} {k}")
            for k in ("p_detect_favorable", "p_true_favorable"):
                self.assertAlmostEqual(pred[k], exp[k], delta=0.01, msg=f"{case['id']} {k}")
            for got, want in zip(pred["interval_80_pct"], exp["interval_80_pct"]):
                self.assertAlmostEqual(got, want, delta=0.1, msg=case["id"])
            self.assertEqual(pred["label"]["label_zh"], "统计模型估计")
            self.assertEqual(any("个人差异默认" in x for x in pred["label"]["assumptions"]), case["tau_pct"] is None, case["id"])

    def test_prediction_matches_the_analyst_schema(self) -> None:
        d = run("predict", "--marker", "收缩压", "--intervention", "减盐", "--baseline", "138", "--unit", "mmHg",
                "--repeats", "14", "--adherence", "0.5", "--weeks", "6", "--plan-item", "I3")
        pred = d["predictions"][0]["prediction"]
        self.assertEqual(pred["label"]["basis_kind"], "statistical_model")
        self.assertIn("依从比例按打卡次数线性缩放（做到计划的 50%）", pred["label"]["assumptions"])
        self.assertIn("统计模型估计", d["predictions"][0]["say_zh"])
        schema_dir = ANALYST / "schema" if ANALYST else None
        if not (schema_dir and (schema_dir / "la-prediction-1.schema.json").is_file()):
            self.skipTest("analyst schemas not found")
        try:
            import jsonschema
            from referencing import Registry, Resource
        except ImportError:
            self.skipTest("jsonschema not installed")
        schemas = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in schema_dir.glob("la-*.schema.json")}
        from urllib.parse import urljoin  # $ref is relative to each schema's $id, e.g. la-prediction/1
        reg = Registry().with_resources((urljoin(b["$id"], n), Resource.from_contents(s))
                                        for n, s in schemas.items() for b in schemas.values())
        jsonschema.Draft202012Validator(schemas["la-prediction-1.schema.json"], registry=reg).validate(pred)

    def test_predict_edge_cases(self) -> None:
        self.assertEqual(run("predict", "--marker", "收缩压", "--intervention", "减盐")["predictions"][0]["verdict"], "needs_baseline")
        self.assertEqual(run("predict", "--marker", "收缩压", "--intervention", "倒着走路", "--baseline", "138")["verdict"], "no_effect_row")
        self.assertEqual(run("predict", "--marker", "DunedinPACE", "--intervention", "热量限制")["verdict"], "no_noise_model")
        hdl = run("predict", "--marker", "HDL-C", "--intervention", "戒烟", "--baseline", "1.2", "--unit", "mmol/L", "--repeats", "4")
        self.assertEqual(hdl["predictions"][0]["model"]["favorable"], "higher")


if __name__ == "__main__":
    unittest.main()
