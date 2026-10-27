#!/usr/bin/env python3
"""Is a change real, and could one person see an intervention's effect at all?

Uses the within-person biological variation table (data/biological_variation.json)
and the trial-average effects table (data/effects.jsonl) of longevity-skills.
The reference change value matches longevity-analyst's `twin compare`.

  noise.py change  --marker 收缩压 --before 138 141 135 --after 131 129 128 [--gap-days 30]
  noise.py trend   --marker 空腹血糖 --series 2023-09-01:4.6 2024-09-03:5.0 2025-09-02:5.3 2026-09-01:5.6
  noise.py plan    --marker 收缩压 [--intervention 减盐] [--baseline 138 --unit mmHg] [--repeats 14]
  noise.py predict --marker 收缩压 --intervention 减盐 --baseline 138 --unit mmHg --repeats 14 [--personal 138:131:14]
  noise.py markers

trend and predict follow PLAN appendix B and share their test cases with longevity-analyst
(tests/fixtures/trend_cases.json, prediction_cases.json). Clock readouts are judged by `change` only when the
library has data/readout_noise.json (technical-replicate noise).

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
from datetime import date, datetime
from pathlib import Path
from statistics import NormalDist
from typing import Any, Dict, List, Optional, Tuple

Z80 = 0.8416  # added to the two-sided 95 % z for roughly 80 % power
Z_TREND = 2.576  # default slope test threshold (PLAN B.4); the table may set its own z_trend
Z_INTERVAL80 = 1.2816
TREND_MIN_POINTS, TREND_MIN_SPAN_DAYS, DEFAULT_WINDOW_DAYS = 3, 180, 28
NORMAL = NormalDist()

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


def convert(key: str, value: float, frm: str, to: str, table: Optional[Dict[str, float]] = None) -> Optional[float]:
    """table: the marker's own `convert` map ({unit: factor}); pass it only when `to` is the marker's unit."""
    a, b = norm_unit(frm), norm_unit(to)
    if a == b:
        return value
    for u, f in (table or {}).items():
        if norm_unit(u) == a:
            return value * f
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
    ro = None if m else match_readout(a.readouts, a.marker)
    if ro:
        return readout_change(out, ro, a.before, a.after)
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


def load_readouts(lib: Path) -> Optional[Dict[str, Any]]:
    """Technical-replicate noise of clock readouts (longevity-readout-noise/1); None when the library has none."""
    p = lib / "data" / "readout_noise.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def match_readout(table: Optional[Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    if not table:
        return None
    want = set(variants(name))
    for r in table.get("readouts", []):
        if want & {v for n in [r.get("key", ""), r.get("label_zh", ""), *r.get("match", [])] for v in variants(n)}:
            return {**r, "_z": table.get("z", 1.96)}
    return None


def readout_change(out: Dict[str, Any], ro: Dict[str, Any], before: List[float], after: List[float]) -> Dict[str, Any]:
    """PLAN WS-B.3: |Δ| > z × sqrt(1/k1 + 1/k2) × sd_abs (√2 × sd_abs for one value each side) is beyond measurement error."""
    try:
        sd = float(ro.get("sd_abs"))
    except (TypeError, ValueError):
        return {**out, "verdict": "no_noise_model",
                "why": "读数噪声表里这个读数没有可用的重复测量标准差，两次结果只能并排看"}
    b, c = sum(before) / len(before), sum(after) / len(after)
    band = ro["_z"] * math.sqrt(1 / len(before) + 1 / len(after)) * sd
    d = c - b
    out.update(before=round(b, 3), after=round(c, 3), change_abs=round(d, 2), band_abs=[round(-band, 2), round(band, 2)],
               unit=ro.get("unit", ""), noise_kind=ro.get("noise_kind"), basis="readout_noise",
               source=(ro.get("source") or {}).get("doi") or (ro.get("source") or {}).get("url"),
               verdict="up_beyond_noise" if d > band else "down_beyond_noise" if d < -band else "within_noise")
    out["wording_zh"] = ("超出测量误差。这只说明差别比同一份样本重复测量的误差大，不等于身体真的变了"
                         if out["verdict"] != "within_noise" else "在测量误差之内，现在还看不出变化")
    return out


# ---- trend (PLAN appendix B.2–B.5; shared cases: trend-cases/1) ----

CAVEAT_ZH = {
    "censored_or_non_numeric": "有的值是“<”“>”这类删失值、不是数字或为 0，没有计入",
    "unconfirmed_source": "有的值来源没确认，没有计入",
    "unit_not_convertible": "有的值单位换算不了，没有计入",
    "same_day_duplicate_first_kept": "同一天有多个值，只取了第一个",
    "returned_within_noise": "中间有一次超出波动，之后又回到波动范围内",
}
TREND_WHY_ZH = {"fewer_than_3_points": "不到 3 个时间点，不做趋势检验",
                "span_under_180_days": "首末相隔不到 180 天，不做趋势检验"}


def parse_series(tokens: List[str]) -> List[Dict[str, Any]]:
    """日期:值[:单位], a trailing ? marks a value whose source is not confirmed."""
    out = []
    for tok in tokens:
        uncertain = tok.endswith("?")
        parts = tok.rstrip("?").split(":", 2)
        try:
            d = date.fromisoformat(parts[0].strip().replace("/", "-"))
        except ValueError:
            sys.exit(f"--series: '{tok}' should be 日期:值[:单位], e.g. 2024-09-03:5.0")
        if len(parts) < 2:
            sys.exit(f"--series: '{tok}' has no value")
        out.append({"t": d, "raw": parts[1].strip(), "unit": parts[2].strip() if len(parts) > 2 else None,
                    "uncertain": uncertain})
    return out


def prepare(m: Dict[str, Any], obs: List[Dict[str, Any]]) -> Tuple[List[Tuple[date, float, int]], List[str]]:
    """Drop what cannot be used, convert units, keep the first value of a day, cluster into min_retest_days windows."""
    caveats: List[str] = []
    note = lambda c: caveats.append(c) if c not in caveats else None  # noqa: E731
    kept, days = [], set()
    for o in obs:
        if o["uncertain"]:
            note("unconfirmed_source")
            continue
        try:
            v = float(o["raw"])
        except ValueError:
            v = None
        if v is None or v <= 0 or not math.isfinite(v):
            note("censored_or_non_numeric")
            continue
        if o["unit"]:
            v = convert(m["key"], v, o["unit"], m["unit"], m.get("convert"))
            if v is None:
                note("unit_not_convertible")
                continue
        if o["t"] in days:
            note("same_day_duplicate_first_kept")
            continue
        days.add(o["t"])
        kept.append((o["t"], v))
    kept.sort(key=lambda x: x[0])
    window = m.get("min_retest_days") or DEFAULT_WINDOW_DAYS
    groups: Dict[int, List[Tuple[date, float]]] = {}
    for d, v in kept:
        groups.setdefault((d - kept[0][0]).days // window, []).append((d, v))
    points = []
    for w in sorted(groups):
        g = groups[w]
        ds, vals, k = sorted(d for d, _ in g), [v for _, v in g], len(g)
        mid = ds[(k - 1) // 2] if k % 2 else ds[k // 2 - 1] + (ds[k // 2] - ds[k // 2 - 1]) / 2
        points.append((mid, center(vals, bool(m.get("log_normal"))), k))
    return points, caveats


def compare_points(m: Dict[str, Any], z: float, p: Tuple[date, float, int], q: Tuple[date, float, int],
                   check_gap: bool = True) -> Dict[str, Any]:
    up, dn = rcv(m, z, p[2], q[2])
    ch = 100 * (q[1] - p[1]) / p[1]
    r: Dict[str, Any] = {"from": p[0].isoformat(), "to": q[0].isoformat(), "change_pct": round(ch, 1),
                         "band_pct": [round(dn, 1), round(up, 1)]}
    window = m.get("min_retest_days") or DEFAULT_WINDOW_DAYS
    if check_gap and (q[0] - p[0]).days < window:
        r.update(verdict="too_close", why=f"两次只隔 {(q[0] - p[0]).days} 天，这个指标至少要隔 {window} 天")
    else:
        r["verdict"] = "up_beyond_noise" if ch > up else "down_beyond_noise" if ch < dn else "within_noise"
    return r


def slope_test(m: Dict[str, Any], points: List[Tuple[date, float, int]], z_trend: float) -> Dict[str, Any]:
    """Weighted least-squares slope with the published within-person variation as known noise (PLAN B.4)."""
    n = len(points)
    if n < TREND_MIN_POINTS:
        return {"n": n, "verdict": "not_judged", "reason": "fewer_than_3_points", "why": TREND_WHY_ZH["fewer_than_3_points"]}
    span = (points[-1][0] - points[0][0]).days
    if span < TREND_MIN_SPAN_DAYS:
        return {"n": n, "span_days": span, "verdict": "not_judged", "reason": "span_under_180_days",
                "why": TREND_WHY_ZH["span_under_180_days"]}
    cvi, cva = cvs(m)
    if m.get("long_term_cvi_pct") is not None:
        cvi = m["long_term_cvi_pct"] / 100
    t = [(p[0] - points[0][0]).days / 365.25 for p in points]
    ybar = sum(p[1] for p in points) / n
    if m.get("log_normal"):
        sl = math.sqrt(math.log(cvi ** 2 + 1) + math.log(cva ** 2 + 1))
        y, s = [math.log(p[1]) for p in points], [sl / math.sqrt(p[2]) for p in points]
    else:
        y, s = [p[1] for p in points], [math.sqrt(cvi ** 2 + cva ** 2) * ybar / math.sqrt(p[2]) for p in points]
    w = [1 / x ** 2 for x in s]
    tw, yw = sum(a * b for a, b in zip(w, t)) / sum(w), sum(a * b for a, b in zip(w, y)) / sum(w)
    sxx = sum(wi * (ti - tw) ** 2 for wi, ti in zip(w, t))
    b = sum(wi * (ti - tw) * (yi - yw) for wi, ti, yi in zip(w, t, y)) / sxx
    zb = b * math.sqrt(sxx)
    annual = 100 * (math.exp(b) - 1) if m.get("log_normal") else 100 * b / ybar
    verdict = ("rising_trend" if zb > 0 else "falling_trend") if abs(zb) > z_trend else "no_trend_detected"
    return {"n": n, "span_days": span, "slope_per_year": round(b, 4), "slope_scale": "ln" if m.get("log_normal") else m["unit"],
            "annual_change_pct": round(annual, 1), "z": round(zb, 2), "z_crit": z_trend, "verdict": verdict,
            "noise_cvi": "long_term_cvi_pct" if m.get("long_term_cvi_pct") is not None else "cvi_pct"}


def cmd_trend(a: argparse.Namespace, z: float, idx: Dict[str, Any], _: List[Any]) -> Dict[str, Any]:
    m = match(idx, a.marker)
    if not m:
        return {"marker": a.marker, "summary_verdict": "not_judged", "verdict": "no_noise_model",
                "why": "没有这个指标的个体内变异数据，几次结果只能按时间并排看，不判断趋势"}
    z_trend = a.z_trend if a.z_trend is not None else a.table_z_trend or Z_TREND
    points, caveats = prepare(m, parse_series(a.series))
    out: Dict[str, Any] = {"marker": m["label_zh"], "unit": m["unit"],
                           "points": [{"t": p[0].isoformat(), "value": round(p[1], 4), "k": p[2]} for p in points],
                           "band_single_pct": [round(x, 1) for x in reversed(rcv(m, z))]}
    if len(points) < 2:
        out.update(pairs=[], baseline_vs_latest=None, trend=slope_test(m, points, z_trend), summary_verdict="not_judged")
    else:
        pairs = [compare_points(m, z, p, q) for p, q in zip(points, points[1:])]
        bl = compare_points(m, z, points[0], points[-1], check_gap=False)
        bl.pop("from"), bl.pop("to")
        tr = slope_test(m, points, z_trend)
        beyond = lambda v: v in ("up_beyond_noise", "down_beyond_noise")  # noqa: E731
        if tr["verdict"] in ("rising_trend", "falling_trend"):
            summary = "trend_beyond_noise"
        elif beyond(bl["verdict"]):
            summary = "change_beyond_noise"
        elif any(beyond(p["verdict"]) for p in pairs):
            summary = "change_beyond_noise"
            caveats.append("returned_within_noise")
        elif all(p["verdict"] == "too_close" for p in pairs) and tr["verdict"] == "not_judged":
            summary = "not_judged"
        else:
            summary = "within_noise"
        out.update(pairs=pairs, baseline_vs_latest=bl, trend=tr, summary_verdict=summary)
    out.update(bv_source=m["cvi_source"]["doi"], caveats=caveats, caveats_zh=[CAVEAT_ZH[c] for c in caveats])
    return out


# ---- personal response prediction (PLAN appendix B.7; shared cases: prediction-cases/1) ----

def matching_effects(idx: Dict[str, Any], m: Dict[str, Any], effects: List[Dict[str, Any]],
                     intervention: Optional[str]) -> List[Dict[str, Any]]:
    q = fold(intervention) if intervention else ""
    rows = []
    for e in effects:
        em = match(idx, e.get("marker_key", "")) or match(idx, e.get("marker_zh", "")) or match(idx, e.get("marker", ""))
        if not em or em["key"] != m["key"]:
            continue
        names = [fold(n) for n in [e.get("intervention_zh", ""), *e.get("keywords", [])] if fold(n)]
        if q and not any(n in q or q in n for n in names):
            continue
        rows.append(e)
    return rows


def effect_pct(m: Dict[str, Any], eff: Dict[str, Any], x: float, baseline: Optional[float], unit: Optional[str],
               per_units: Optional[float]) -> Tuple[Optional[float], str]:
    """One effect number (the mean or a CI bound) as % of the person's baseline, or (None, reason)."""
    if eff["kind"] == "percent_change":
        return x, ""
    if eff["kind"] == "per_unit" and not per_units:
        return None, "needs_per_units"
    if eff["kind"] not in ("mean_difference", "per_unit"):
        return None, "not_comparable"
    if not baseline:
        return None, "needs_baseline"
    to = unit or m["unit"]
    conv = convert(m["key"], x * (per_units if eff["kind"] == "per_unit" else 1.0), eff["unit"], to,
                   m.get("convert") if norm_unit(to) == norm_unit(m["unit"]) else None)
    return (None, "unit_mismatch") if conv is None else (100 * conv / baseline, "")


def parse_personal(tokens: List[str]) -> List[Tuple[float, int, int]]:
    out = []
    for tok in tokens or []:
        try:
            f = tok.split(":")
            b, c, k1 = float(f[0]), float(f[1]), int(f[2])
            k2 = int(f[3]) if len(f) > 3 else k1
        except (ValueError, IndexError):
            sys.exit(f"--personal: '{tok}' should be 前均值:后均值:每边次数, e.g. 138:131:14")
        out.append((100 * (c - b) / b, k1, k2))
    return out


def predict_one(m: Dict[str, Any], e: Dict[str, Any], a: argparse.Namespace, z: float) -> Dict[str, Any]:
    eff = e["effect"]
    mean, why = effect_pct(m, eff, eff["value"], a.baseline, a.unit, a.per_units)
    if mean is None:
        return {"effects_id": e["id"], "verdict": why}
    ci = eff.get("ci") or []
    lo, _ = effect_pct(m, eff, ci[0], a.baseline, a.unit, a.per_units) if len(ci) == 2 else (None, "")
    hi, _ = effect_pct(m, eff, ci[1], a.baseline, a.unit, a.per_units) if len(ci) == 2 else (None, "")
    if lo is None or hi is None:
        return {"effects_id": e["id"], "verdict": "no_ci", "why": "效应表没有给出置信区间，算不出试验均值本身的不确定性"}
    started = a.adherence is not None
    adh = min(1.0, a.adherence) if started else 1.0
    a_next = a.adherence_next
    mu0 = mean * adh
    se = abs(hi - lo) / (2 * 1.96)
    tau = e.get("tau_pct")
    tau_default = tau is None
    tau = abs(mu0) if tau_default else float(tau)
    s0sq = se ** 2 + tau ** 2
    cvi, cva = cvs(m)
    var = 1e4 * (cvi ** 2 + cva ** 2)  # in %²
    personal = parse_personal(a.personal)
    prec, num = 1 / s0sq, mu0 / s0sq
    for d, k1, k2 in personal:
        vi = var * (1 / k1 + 1 / k2)
        prec, num = prec + 1 / vi, num + d / vi
    ssq = 1 / prec
    mu = ssq * num
    vn = var * 2 / a.repeats
    band = z * math.sqrt(vn)
    sd = math.sqrt(ssq + vn)
    expect = mu * a_next
    better = m.get("better")
    lower = better == "lower" or (better not in ("lower", "higher") and mean < 0)
    p_detect = NORMAL.cdf((-band - expect) / sd) if lower else 1 - NORMAL.cdf((band - expect) / sd)
    p_true = NORMAL.cdf(-mu / math.sqrt(ssq)) if lower else 1 - NORMAL.cdf(-mu / math.sqrt(ssq))
    interval = [round(expect - Z_INTERVAL80 * sd, 1), round(expect + Z_INTERVAL80 * sd, 1)]
    assumptions = [f"依从比例按打卡次数线性缩放（做到计划的 {round(100 * adh)}%）" if started else "还没开始做，按完全做到计算",
                   "个人差异默认与平均效应同量级（效应表未给出）" if tau_default else f"个人差异取效应表给出的值（{tau:g}%）",
                   "试验效应和测量误差都按正态分布近似",
                   "下次实验按完全做到计算" if a_next >= 1 else f"下次实验按做到计划的 {round(100 * a_next)}% 计算"]
    if personal:
        assumptions.append("本人各次实验相互独立")
    if better not in ("lower", "higher"):
        assumptions.append("这个指标没有固定的好坏方向，按试验平均效应的方向算“有利”")
    sources = [{"type": "effects", "ref": e["id"]}, {"type": "biovar", "ref": m["key"]}]
    sources += [{"type": "personal_experiment", "ref": f"本人实验{i + 1}"} for i in range(len(personal))]
    label = {"schema": "la-label/1", "basis_kind": "statistical_model", "label_zh": "统计模型估计", "sources": sources,
             "assumptions": assumptions, "confidence": {"interval_80": interval, "unit": "%"},
             "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"), "physician_review": "none"}
    pred = {"schema": "la-prediction/1", "id": a.id, "plan_item": a.plan_item,
            "intervention_zh": e.get("intervention_zh") or a.intervention or "", "marker": m["label_zh"],
            "design": {"repeats_each_side": a.repeats, "weeks": a.weeks, "adherence": round(adh, 3)},
            "p_detect_favorable": round(p_detect, 3), "p_true_favorable": round(p_true, 3),
            "expected_change_pct": round(expect, 1), "interval_80_pct": interval, "label": label}
    pt = "超过 99%" if p_true > 0.99 else f"约 {round(100 * p_true)}%"
    return {"effects_id": e["id"], "verdict": "ok", "prediction": pred,
            "model": {"mu0_pct": round(mu0, 3), "se_pct": round(se, 3), "tau_pct": round(tau, 3), "s0_pct": round(math.sqrt(s0sq), 3),
                      "band_pct": round(band, 3), "posterior_mu_pct": round(mu, 3), "posterior_s_pct": round(math.sqrt(ssq), 3),
                      "favorable": "lower" if lower else "higher"},
            "say_zh": f"按你的情况，下次这样做实验能测出效果的概率约 {round(100 * p_detect)}%，"
                      f"这个改变对你真实有利的概率{pt}（统计模型估计，依据：{e.get('doi') or e['id']}）。"}


def cmd_predict(a: argparse.Namespace, z: float, idx: Dict[str, Any], effects: List[Dict[str, Any]]) -> Dict[str, Any]:
    m = match(idx, a.marker)
    if not m:
        return {"marker": a.marker, "verdict": "no_noise_model",
                "why": "没有这个指标的个体内变异数据，算不出单人实验能不能看出效果"}
    rows = matching_effects(idx, m, effects, a.intervention)
    if not rows:
        return {"marker": m["label_zh"], "verdict": "no_effect_row",
                "why": "效应表里没有这个干预对这个指标的试验均值；要说有没有用的概率，只能给 AI 判断，并明确标出"}
    return {"marker": m["label_zh"], "label_zh": "统计模型估计", "predictions": [predict_one(m, e, a, z) for e in rows]}


def cmd_plan(a: argparse.Namespace, z: float, idx: Dict[str, Any], effects: List[Dict[str, Any]]) -> Dict[str, Any]:
    m = match(idx, a.marker)
    if not m:
        return {"marker": a.marker, "verdict": "no_noise_model",
                "why": "没有这个指标的个体内变异数据（衰老时钟、器官年龄等都属于这类），单人前后对比判断不了"}
    rows = matching_effects(idx, m, effects, a.intervention)
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
    s = sub.add_parser("trend", help="slow drift over several dated values (PLAN appendix B)")
    s.add_argument("--marker", required=True)
    s.add_argument("--series", nargs="+", required=True,
                   help="日期:值[:单位], e.g. 2024-09-03:5.0 or 2023-09-01:83:mg/dL; '<0.5' is censored; a trailing ? marks an unconfirmed source")
    s.add_argument("--z-trend", type=float, help="slope test threshold (default: the table's z_trend, else 2.576)")
    s.set_defaults(fn=cmd_trend)
    s = sub.add_parser("predict", help="probability that a change works for this person (statistical model, PLAN B.7)")
    s.add_argument("--marker", required=True)
    s.add_argument("--intervention", required=True)
    s.add_argument("--baseline", type=float, help="the person's current value, needed for absolute effects")
    s.add_argument("--unit")
    s.add_argument("--repeats", type=int, default=1, help="separate-day measurements planned on each side next time")
    s.add_argument("--personal", nargs="+", help="earlier own experiments of the same kind: 前均值:后均值:每边次数")
    s.add_argument("--adherence", type=float, help="check-ins done / planned so far (capped at 1); omit before starting")
    s.add_argument("--adherence-next", type=float, default=1.0, help="share of the plan expected next time (default 1)")
    s.add_argument("--per-units", type=float, help="planned amount for per-unit effects, e.g. kg lost")
    s.add_argument("--weeks", type=int, help="planned weeks, recorded in the design")
    s.add_argument("--id", default="P1")
    s.add_argument("--plan-item")
    s.set_defaults(fn=cmd_predict)
    sub.add_parser("markers", help="markers that have a noise model").set_defaults(fn=cmd_markers)
    a = p.parse_args(argv)
    lib = find_library(a.library)
    z, idx, effects = load(lib)
    a.readouts = load_readouts(lib)
    a.table_z_trend = json.loads((lib / "data" / "biological_variation.json").read_text(encoding="utf-8")).get("z_trend")
    print(json.dumps(a.fn(a, z, idx, effects), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
