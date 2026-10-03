#!/usr/bin/env python3
"""Is a change real, and could one person see an intervention's effect at all?

Uses the within-person biological variation table (data/biological_variation.json)
and the trial-average effects table (data/effects.jsonl) of longevity-skills.
The reference change value matches longevity-analyst's `twin compare`.

  noise.py change --marker 收缩压 --before 138 141 135 --after 131 129 128 [--gap-days 30]
  noise.py plan   --marker 收缩压 [--intervention 减盐] [--baseline 138 --unit mmHg] [--repeats 14]
  noise.py markers

Library: --library, else $LONGEVITY_SKILLS_HOME, else a longevity-skills folder next to this skill.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

Z80 = 0.8416  # added to the two-sided 95 % z for roughly 80 % power

# Multiply a value in the first unit by the factor to get the second unit.
UNIT_FACTORS = {
    "glucose": {("mg/dl", "mmol/l"): 0.0555},
    "tc": {("mg/dl", "mmol/l"): 0.02586},
    "ldl": {("mg/dl", "mmol/l"): 0.02586},
    "hdl": {("mg/dl", "mmol/l"): 0.02586},
    "tg": {("mg/dl", "mmol/l"): 0.01129},
    "creatinine": {("mg/dl", "umol/l"): 88.4},
    "crp": {("mg/dl", "mg/l"): 10.0},
    "albumin": {("g/dl", "g/l"): 10.0},
    "hb": {("g/dl", "g/l"): 10.0},
    "vitd": {("nmol/l", "ng/ml"): 0.4006},
}


def fold(text: Any) -> str:
    return re.sub(r"[\s_\-·•:：,，/\\]+", "", unicodedata.normalize("NFKC", str(text)).casefold())


def variants(text: Any) -> List[str]:
    raw = unicodedata.normalize("NFKC", str(text)).strip()
    out = [fold(raw)]
    m = re.match(r"^(.*?)[(（]([^()（）]*)[)）]\s*$", raw)
    if m:
        out += [fold(m.group(1)), fold(m.group(2))]
    return [v for v in out if v]


def norm_unit(u: Any) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(u or "")).replace("µ", "u").replace("μ", "u").lower())


def convert(key: str, value: float, frm: str, to: str) -> Optional[float]:
    a, b = norm_unit(frm), norm_unit(to)
    if a == b:
        return value
    t = UNIT_FACTORS.get(key, {})
    if (a, b) in t:
        return value * t[(a, b)]
    if (b, a) in t:
        return value / t[(b, a)]
    return None


def find_library(given: Optional[str]) -> Path:
    cands = [Path(given)] if given else []
    if os.environ.get("LONGEVITY_SKILLS_HOME"):
        cands.append(Path(os.environ["LONGEVITY_SKILLS_HOME"]))
    cands += [p / "longevity-skills" for p in list(Path(__file__).resolve().parents)[:6]]
    for c in cands:
        if (c.expanduser() / "data" / "biological_variation.json").is_file():
            return c.expanduser()
    sys.exit("longevity-skills not found: pass --library <folder with data/biological_variation.json>")


def load(lib: Path) -> Tuple[float, Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    bv = json.loads((lib / "data" / "biological_variation.json").read_text(encoding="utf-8"))
    idx: Dict[str, Dict[str, Any]] = {}
    for m in bv["markers"]:
        for n in [m["key"], m.get("label_zh", ""), *m.get("aliases", [])]:
            for v in variants(n):
                idx.setdefault(v, m)
    p = lib / "data" / "effects.jsonl"
    effects = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []
    return bv["z"], idx, effects


def match(idx: Dict[str, Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    return next((idx[v] for v in variants(name) if v in idx), None)


def cvs(m: Dict[str, Any]) -> Tuple[float, float]:
    cvi = m["cvi_pct"] / 100
    cva = (m["cva_pct"] if m.get("cva_pct") is not None else 0.5 * m["cvi_pct"]) / 100
    return cvi, cva


def rcv(m: Dict[str, Any], z: float, k1: int = 1, k2: int = 1) -> Tuple[float, float]:
    """Reference change value (up %, down %) between the means of k1 and k2 separate-day measurements."""
    cvi, cva = cvs(m)
    f = 1 / k1 + 1 / k2
    if m.get("log_normal"):
        w = z * math.sqrt(f * (math.log(cvi ** 2 + 1) + math.log(cva ** 2 + 1)))
        return 100 * (math.exp(w) - 1), 100 * (math.exp(-w) - 1)
    r = 100 * z * math.sqrt(f * (cvi ** 2 + cva ** 2))
    return r, -r


def k_needed(m: Dict[str, Any], zz: float, pct: float) -> Optional[int]:
    """Separate-day measurements on each side so that a true change of pct crosses the band."""
    if pct == 0 or pct <= -100:
        return None
    cvi, cva = cvs(m)
    if m.get("log_normal"):
        e, var = math.log(1 + pct / 100), math.log(cvi ** 2 + 1) + math.log(cva ** 2 + 1)
    else:
        e, var = pct / 100, cvi ** 2 + cva ** 2
    return max(1, math.ceil(2 * zz ** 2 * var / e ** 2))


def center(vals: List[float], log_normal: bool) -> float:
    if log_normal and all(v > 0 for v in vals):
        return math.exp(sum(math.log(v) for v in vals) / len(vals))
    return sum(vals) / len(vals)


def noise_card(m: Dict[str, Any], z: float, k: int) -> Dict[str, Any]:
    up1, dn1 = rcv(m, z)
    upk, dnk = rcv(m, z, k, k)
    need = math.ceil(((m.get("min_retest_days") or 0) + max(14, k)) / 7)
    return {"marker": m["label_zh"], "unit": m["unit"], "log_normal": m["log_normal"],
            "band_single_pct": [round(dn1, 1), round(up1, 1)], f"band_mean_of_{k}_pct": [round(dnk, 1), round(upk, 1)],
            "min_retest_days": m.get("min_retest_days"), "min_experiment_weeks": max(4, need),
            "source": m["cvi_source"]["doi"]}


def cmd_change(a: argparse.Namespace, z: float, idx: Dict[str, Any], _: List[Any]) -> Dict[str, Any]:
    m = match(idx, a.marker)
    out: Dict[str, Any] = {"marker": a.marker, "n_before": len(a.before), "n_after": len(a.after)}
    if not m:
        return {**out, "verdict": "no_noise_model",
                "why": "没有这个指标的个体内变异数据，两次结果只能并排看，不判断变好变坏"}
    ln = bool(m.get("log_normal"))
    b, c = center(a.before, ln), center(a.after, ln)
    up, dn = rcv(m, z, len(a.before), len(a.after))
    ch = 100 * (c - b) / b
    out.update(before=round(b, 3), after=round(c, 3), change_pct=round(ch, 1), band_pct=[round(dn, 1), round(up, 1)],
               better=m.get("better"), source=m["cvi_source"]["doi"])
    if a.gap_days is not None and m.get("min_retest_days") and a.gap_days < m["min_retest_days"]:
        out.update(verdict="too_close", why=f"两组只隔 {a.gap_days} 天，这个指标至少要隔 {m['min_retest_days']} 天")
    else:
        out["verdict"] = "up_beyond_noise" if ch > up else "down_beyond_noise" if ch < dn else "within_noise"
    return out


def cmd_plan(a: argparse.Namespace, z: float, idx: Dict[str, Any], effects: List[Dict[str, Any]]) -> Dict[str, Any]:
    m = match(idx, a.marker)
    if not m:
        return {"marker": a.marker, "verdict": "no_noise_model",
                "why": "没有这个指标的个体内变异数据（衰老时钟、器官年龄等都属于这类），单人前后对比判断不了"}
    q = fold(a.intervention) if a.intervention else ""
    rows = []
    for e in effects:
        em = match(idx, e.get("marker_zh", "")) or match(idx, e.get("marker", ""))
        if not em or em["key"] != m["key"]:
            continue
        names = [fold(n) for n in [e.get("intervention_zh", ""), *e.get("keywords", [])] if fold(n)]
        if q and not any(n in q or q in n for n in names):
            continue
        rows.append(e)
    out: Dict[str, Any] = {"noise": noise_card(m, z, a.repeats), "effects": []}
    for e in rows:
        eff, r = e["effect"], {k: e.get(k) for k in ("id", "intervention_zh", "category", "effect", "design",
                                                    "participants", "population", "duration_weeks", "doi", "note_zh")}
        pct, why = None, "not_comparable"
        if eff["kind"] == "percent_change":
            pct = eff["value"]
        elif eff["kind"] == "per_unit" and not a.per_units:
            why = "needs_per_units"
        elif eff["kind"] in ("mean_difference", "per_unit"):
            why = "needs_baseline" if not a.baseline else "unit_mismatch"
            mult = a.per_units if eff["kind"] == "per_unit" else 1.0
            conv = convert(m["key"], eff["value"] * mult, eff["unit"], a.unit or m["unit"]) if a.baseline else None
            if conv is not None:
                pct = 100 * conv / a.baseline
        if pct is None:
            r["verdict"] = why
        else:
            k50, k80 = k_needed(m, z, pct), k_needed(m, z + Z80, pct)
            r.update(expected_change_pct=round(pct, 1), k_each_side_half_chance=k50, k_each_side_80pct=k80,
                     verdict="likely" if k80 and a.repeats >= k80 else "coin_flip" if k50 and a.repeats >= k50 else "unlikely")
        out["effects"].append(r)
    if not rows:
        out["why"] = "效应表里没有这个干预对这个指标的试验均值；只给噪声带"
    return out


def cmd_markers(a: argparse.Namespace, z: float, idx: Dict[str, Any], _: List[Any]) -> Dict[str, Any]:
    seen = {id(m): m for m in idx.values()}.values()
    return {"z": z, "markers": [noise_card(m, z, 1) for m in seen]}


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--library")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("change", help="is the change between two sets of measurements beyond normal variation")
    s.add_argument("--marker", required=True)
    s.add_argument("--before", type=float, nargs="+", required=True, help="values from separate days, same unit")
    s.add_argument("--after", type=float, nargs="+", required=True)
    s.add_argument("--gap-days", type=int, help="days between the last 'before' and the first 'after'")
    s.set_defaults(fn=cmd_change)
    s = sub.add_parser("plan", help="trial-average effect vs this person's noise band")
    s.add_argument("--marker", required=True)
    s.add_argument("--intervention")
    s.add_argument("--baseline", type=float, help="the person's current value, needed for absolute effects")
    s.add_argument("--unit")
    s.add_argument("--repeats", type=int, default=1, help="separate-day measurements planned on each side")
    s.add_argument("--per-units", type=float, help="planned amount for per-unit effects, e.g. kg lost")
    s.set_defaults(fn=cmd_plan)
    sub.add_parser("markers", help="markers that have a noise model").set_defaults(fn=cmd_markers)
    a = p.parse_args(argv)
    z, idx, effects = load(find_library(a.library))
    print(json.dumps(a.fn(a, z, idx, effects), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
