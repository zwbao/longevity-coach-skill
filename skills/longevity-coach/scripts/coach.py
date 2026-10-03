#!/usr/bin/env python3
"""longevity-coach harness.

Durable memory for one or more members, commitments with check-ins, N-of-1
experiments judged against published within-person biological variation,
routing into the longevity-skills method library, and import of
longevity-analyst deliverables. Standard library only (Python 3.9+).

State lives under the coach home: --home, else LONGEVITY_COACH_HOME, else
~/.longevity-coach. The agent changes state only through these commands and
runs `brief` at the start of every session.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import re
import shutil
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SCHEMA = "coach-state/1"
SKILL_DIR = Path(__file__).resolve().parent.parent
EXIT_INPUT = 2
Z80 = 0.8416  # added to the two-sided 95 % z for roughly 80 % power

TONES = ("upbeat", "gentle", "direct", "clinical")
MILESTONES = (1, 3, 5, 10, 20, 30, 50, 75, 100, 150, 200, 300, 365, 500, 750, 1000)
NOTE_KINDS = ("story", "preference", "barrier", "win", "concern", "life_event", "value")
AREAS = ("sleep", "exercise", "diet", "stress", "social", "substance", "measurement", "medical", "other")
STAGES = ("precontemplation", "contemplation", "preparation", "action", "maintenance")
PROPOSAL_STATUS = ("proposed", "adopted", "declined", "asked_professional", "done")

DATA_LADDER = [
    ("questionnaire", "问卷（几分钟就能答）", "high"),
    ("home_measurement", "在家能量的（腰围、血压、体重）", "high"),
    ("routine_labs", "常规体检化验单", "high"),
    ("wearable", "手环或手表数据", "high"),
    ("repeated_measures", "同一指标的两次以上测量", "medium"),
    ("genotype", "基因检测原始数据", "medium"),
    ("methylation", "DNA 甲基化", "low"),
    ("proteomics", "血浆蛋白组", "low"),
    ("metabolomics", "代谢组", "low"),
    ("microbiome", "肠道菌群", "low"),
    ("imaging", "影像", "low"),
    ("telomere", "端粒", "low"),
    ("immune_profile", "免疫细胞分型", "low"),
]
LADDER_TYPES = tuple(t for t, _, _ in DATA_LADDER)
ROUTINE_LAB_KEYS = {"albumin", "creatinine", "glucose", "crp", "mcv", "rbc", "hb", "hct", "mch", "mchc", "alp", "wbc",
                    "lymph_abs", "hba1c", "tc", "ldl", "hdl", "tg", "vitd"}
HOME_KEYS = {"sbp", "dbp", "weight"}
HOME_NAMES = {"腰围", "waist", "臀围", "hip", "颈围", "neck", "身高", "height", "握力", "grip", "步速", "静息心率"}
ANALYST_KINDS = {"methylation_beta": "methylation", "methylation_idat": "methylation", "variants_vcf": "genotype",
                 "protein_matrix": "proteomics", "olink_long": "proteomics", "somascan_adat": "proteomics",
                 "ms_raw": "proteomics", "metaphlan_profile": "microbiome", "amplicon_table": "microbiome",
                 "lab_table": "routine_labs", "imaging": "imaging"}

RED_FLAGS = ["胸痛", "胸口痛", "胸口疼", "胸口压", "胸闷", "呼吸困难", "喘不上气", "喘不过气", "晕倒", "昏厥", "晕厥",
             "口角歪斜", "一侧无力", "半边身体", "说话不清", "口齿不清", "突然看不见", "剧烈头痛", "便血", "呕血", "黑便",
             "咯血", "不明原因消瘦", "体重莫名", "自杀", "不想活", "轻生", "伤害自己", "活着没意思", "结束生命",
             "chest pain", "can't breathe", "fainted", "suicide", "kill myself"]
ANALYST_HINTS = ["文件夹", "全套", "多组学", "全基因组", "wgs", "vcf", "fastq", "cram", "bam", "idat", "宏基因组",
                 "蛋白组矩阵", "数字孪生", "完整报告", "整套报告", "复测对比", "一堆报告", "所有报告", "multi-omics", "digital twin"]

# Multiply a value in the first unit by the factor to get the second unit.
UNIT_FACTORS: Dict[str, Dict[Tuple[str, str], float]] = {
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


class CoachError(Exception):
    def __init__(self, msg: str, code: int = EXIT_INPUT):
        super().__init__(msg)
        self.code = code


# ---------------------------------------------------------------- helpers

def now_iso() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def today() -> dt.date:
    return dt.date.today()


def to_date(s: Any) -> dt.date:
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        raise CoachError(f"not an ISO date (YYYY-MM-DD): {s}")


def date_arg(s: Optional[str], past: bool = False) -> str:
    d = to_date(s) if s else today()
    if past and d > today():
        raise CoachError(f"{d.isoformat()} is in the future; a measurement or check-in has already happened")
    return d.isoformat()


def load_json(p: Path) -> Any:
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(p: Path) -> List[Dict[str, Any]]:
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_json(p: Path, obj: Any) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, p)


def emit(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def fold(text: Any) -> str:
    s = unicodedata.normalize("NFKC", str(text)).casefold()
    return re.sub(r"[\s_\-·•:：,，/\\]+", "", s)


def name_variants(text: Any) -> List[str]:
    """Folded forms of a name, with and without a trailing parenthetical: 白蛋白(ALB) → 白蛋白(alb), 白蛋白, alb."""
    raw = unicodedata.normalize("NFKC", str(text)).strip()
    out: List[str] = []

    def add(v: str) -> None:
        f = fold(v)
        if f and f not in out:
            out.append(f)

    add(raw)
    m = re.match(r"^(.*?)[(（]([^()（）]*)[)）]\s*$", raw)
    if m:
        add(m.group(1))
        add(m.group(2))
    return out


def norm_unit(u: Any) -> str:
    s = unicodedata.normalize("NFKC", str(u or "")).replace("µ", "u").replace("μ", "u").lower()
    return re.sub(r"\s+", "", s)


def convert(key: Optional[str], value: float, frm: str, to: str) -> Optional[float]:
    a, b = norm_unit(frm), norm_unit(to)
    if a == b:
        return value
    table = UNIT_FACTORS.get(key or "", {})
    if (a, b) in table:
        return value * table[(a, b)]
    if (b, a) in table:
        return value / table[(b, a)]
    return None


def contains_term(q: str, term: str) -> bool:
    """Substring match; pure-ASCII terms must stand alone so that 'nr' does not match inside 'inr'."""
    t = term.casefold()
    if t.startswith("re:"):
        return re.search(term[3:], q, re.I) is not None
    if re.fullmatch(r"[a-z0-9 .+\-']+", t):
        return re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", q) is not None
    return t in q


# ---------------------------------------------------------------- home, config, library

def coach_home(args: argparse.Namespace) -> Path:
    h = getattr(args, "home", None) or os.environ.get("LONGEVITY_COACH_HOME") or "~/.longevity-coach"
    return Path(h).expanduser().resolve()


def _is_library(p: Path) -> bool:
    return (p / "catalog.json").is_file() and (p / "intents.json").is_file()


def _is_analyst(p: Path) -> bool:
    return (p / "SKILL.md").is_file() and (p / "scripts" / "la.py").is_file()


def _discover(kind: str) -> Optional[Path]:
    env = os.environ.get("LONGEVITY_SKILLS_HOME" if kind == "library" else "LONGEVITY_ANALYST_HOME")
    cands: List[Path] = [Path(env).expanduser()] if env else []
    for parent in list(SKILL_DIR.parents)[:5]:
        if kind == "library":
            cands.append(parent / "longevity-skills")
        else:
            cands += [parent / "longevity-analyst-skill" / "skills" / "longevity-analyst", parent / "longevity-analyst"]
    cands.append(Path.home() / ("longevity-skills" if kind == "library" else ".cursor/skills/longevity-analyst"))
    test = _is_library if kind == "library" else _is_analyst
    for c in cands:
        if test(c):
            return c.resolve()
    return None


def config(home: Path) -> Dict[str, Any]:
    p = home / "config.json"
    return load_json(p) if p.exists() else {}


def library_dir(home: Path, required: bool = True) -> Optional[Path]:
    c = config(home).get("library")
    if c and _is_library(Path(c)):
        return Path(c)
    d = _discover("library")
    if d or not required:
        return d
    raise CoachError("longevity-skills library not found (needs catalog.json and intents.json): "
                     "run `coach.py setup --library <clone>`")


def analyst_dir(home: Path) -> Optional[Path]:
    c = config(home).get("analyst")
    if c and _is_analyst(Path(c)):
        return Path(c)
    return _discover("analyst")


_CACHE: Dict[Tuple[str, str], Any] = {}


def lib_json(lib: Path, rel: str) -> Any:
    key = (str(lib), rel)
    if key not in _CACHE:
        _CACHE[key] = load_jsonl(lib / rel) if rel.endswith(".jsonl") else load_json(lib / rel)
    return _CACHE[key]


def biovar(lib: Optional[Path]) -> Tuple[float, Dict[str, Dict[str, Any]]]:
    if not lib:
        return 1.96, {}
    bv = lib_json(lib, "data/biological_variation.json")
    idx: Dict[str, Dict[str, Any]] = {}
    for m in bv["markers"]:
        for n in [m["key"], m.get("label_zh", ""), *m.get("aliases", [])]:
            for v in name_variants(n):
                idx.setdefault(v, m)
    return bv["z"], idx


def match_bv(idx: Dict[str, Dict[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    for v in name_variants(name):
        if v in idx:
            return idx[v]
    return None


def _cv(m: Dict[str, Any]) -> Tuple[float, float]:
    cvi = m["cvi_pct"] / 100
    cva = (m["cva_pct"] if m.get("cva_pct") is not None else 0.5 * m["cvi_pct"]) / 100
    return cvi, cva


def rcv_pct(m: Dict[str, Any], z: float, k1: int = 1, k2: int = 1) -> Tuple[float, float]:
    """Reference change value (up %, down %) between the mean of k1 and the mean of k2 separate-day measurements.

    k1 = k2 = 1 is the classic RCV, z·√2·√(CVI²+CVA²); the log-normal form is asymmetric.
    """
    cvi, cva = _cv(m)
    f = 1 / k1 + 1 / k2
    if m.get("log_normal"):
        w = z * math.sqrt(f * (math.log(cvi ** 2 + 1) + math.log(cva ** 2 + 1)))
        return 100 * (math.exp(w) - 1), 100 * (math.exp(-w) - 1)
    r = 100 * z * math.sqrt(f * (cvi ** 2 + cva ** 2))
    return r, -r


def k_needed(m: Dict[str, Any], zz: float, effect_pct: float) -> Optional[int]:
    """Separate-day measurements needed before and after so that a true change of effect_pct crosses the band."""
    cvi, cva = _cv(m)
    if effect_pct == 0 or effect_pct <= -100:
        return None
    if m.get("log_normal"):
        e, var = math.log(1 + effect_pct / 100), math.log(cvi ** 2 + 1) + math.log(cva ** 2 + 1)
    else:
        e, var = effect_pct / 100, cvi ** 2 + cva ** 2
    return max(1, math.ceil(2 * zz ** 2 * var / e ** 2))


def center(vals: List[float], log_normal: bool) -> float:
    if log_normal and all(v > 0 for v in vals):
        return math.exp(sum(math.log(v) for v in vals) / len(vals))
    return sum(vals) / len(vals)


# ---------------------------------------------------------------- member state

MEMBER_RE = re.compile(r"^[A-Za-z0-9_\-\u4e00-\u9fff]{1,40}$")


def mdir(home: Path, mid: str) -> Path:
    if not MEMBER_RE.match(mid):
        raise CoachError("member id: letters, digits, _ - or Chinese characters, at most 40")
    return home / "members" / mid


def load_state(home: Path, mid: str) -> Dict[str, Any]:
    p = mdir(home, mid) / "state.json"
    if not p.exists():
        raise CoachError(f"no member '{mid}' under {home}; run `coach.py init {mid} --name ...` first")
    return load_json(p)


def save_state(home: Path, mid: str, st: Dict[str, Any]) -> None:
    st["updated_at"] = now_iso()
    write_json(mdir(home, mid) / "state.json", st)


def new_id(items: List[Dict[str, Any]], prefix: str) -> str:
    n = 0
    for it in items:
        m = re.match(rf"^{prefix}(\d+)$", str(it.get("id", "")))
        if m:
            n = max(n, int(m.group(1)))
    return f"{prefix}{n + 1}"


def find(items: List[Dict[str, Any]], iid: str, what: str) -> Dict[str, Any]:
    for it in items:
        if it.get("id") == iid:
            return it
    raise CoachError(f"no {what} with id {iid}")


def journal_add(home: Path, mid: str, st: Dict[str, Any], entry: Dict[str, Any]) -> Dict[str, Any]:
    st["seq"] = st.get("seq", 0) + 1
    e = {"id": f"J{st['seq']}", "t": now_iso(), **entry}
    with open(mdir(home, mid) / "journal.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(e, ensure_ascii=False) + "\n")
    return e


def journal(home: Path, mid: str) -> List[Dict[str, Any]]:
    return load_jsonl(mdir(home, mid) / "journal.jsonl")


def member_age(st: Dict[str, Any]) -> Optional[int]:
    m = st["member"]
    if m.get("birth_date"):
        b, t = to_date(m["birth_date"]), today()
        return t.year - b.year - ((t.month, t.day) < (b.month, b.day))
    a = m.get("age_at")
    if a and a.get("age") is not None:
        return int(a["age"]) + int((today() - to_date(a["date"])).days // 365.25)
    return None


def norm_sex(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    v = s.strip().lower()
    if v in ("m", "male", "男", "man"):
        return "male"
    if v in ("f", "female", "女", "woman"):
        return "female"
    raise CoachError("sex: male or female (m/f/男/女)")


def series(st: Dict[str, Any], name: str, idx: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    bm = match_bv(idx, name)
    want = set(name_variants(name))
    out = [x for x in st["measurements"]
           if (bm and x.get("key") == bm["key"]) or (want & set(name_variants(x["marker"])))]
    return sorted(out, key=lambda x: x["date"])


def data_has(st: Dict[str, Any]) -> List[str]:
    has = set()
    fact = st["facts"].get("data_has")
    if fact:
        has |= {t.strip() for t in re.split(r"[,，、\s]+", str(fact["value"])) if t.strip()}
    keys = {m.get("key") for m in st["measurements"]}
    if keys & ROUTINE_LAB_KEYS:
        has.add("routine_labs")
    if keys & HOME_KEYS or any(set(name_variants(m["marker"])) & {fold(n) for n in HOME_NAMES} for m in st["measurements"]):
        has.add("home_measurement")
    dates: Dict[str, set] = {}
    for m in st["measurements"]:
        dates.setdefault(m.get("key") or fold(m["marker"]), set()).add(m["date"])
    if any(len(d) >= 2 for d in dates.values()):
        has.add("repeated_measures")
    for v in st["analyst_visits"]:
        has |= set(v.get("data_types", []))
    return [t for t in LADDER_TYPES if t in has]


# ---------------------------------------------------------------- commitments

CADENCE_RE = re.compile(r"^(daily|weekdays|weekly|([1-7])x/week)$")


def cadence_rate(c: str) -> float:
    m = CADENCE_RE.match(c)
    if not m:
        raise CoachError("cadence: daily, weekdays, weekly or Nx/week (N = 1..7)")
    return {"daily": 1.0, "weekdays": 5 / 7, "weekly": 1 / 7}.get(c) or int(m.group(2)) / 7


def adherence(cm: Dict[str, Any], window_days: int = 28) -> Optional[Dict[str, Any]]:
    cutoff = today() - dt.timedelta(days=window_days)
    checks = [c for c in cm.get("checks", []) if to_date(c["date"]) > cutoff]
    if not checks:
        return None
    times = sum(c["times"] for c in checks)
    expected = 0.0
    for c in checks:
        if c["period_days"] == 1 and cm["cadence"] in ("daily", "weekdays"):
            expected += 1
        else:
            expected += cadence_rate(cm["cadence"]) * c["period_days"]
    return {"window_days": window_days, "checkins": len(checks), "done": times, "expected": round(expected, 1),
            "rate": round(min(1.0, times / expected), 2) if expected else None}


def last_check(cm: Dict[str, Any]) -> Optional[str]:
    return max((c["date"] for c in cm.get("checks", [])), default=None)


def cumulative(cm: Dict[str, Any], until: Optional[str] = None) -> float:
    """Total times done; never resets, unlike a streak."""
    return sum(c["times"] for c in cm.get("checks", []) if until is None or c["date"] <= until)


def check_rate(cm: Dict[str, Any], c: Dict[str, Any]) -> Optional[float]:
    if c["period_days"] == 1 and cm["cadence"] in ("daily", "weekdays"):
        exp = 1.0
    else:
        exp = cadence_rate(cm["cadence"]) * c["period_days"]
    return min(1.0, c["times"] / exp) if exp else None


def celebrations(cm: Dict[str, Any], chk: Dict[str, Any], cad: int) -> List[str]:
    """True, specific things worth praising about this check-in, computed from the record."""
    prev = [c for c in cm["checks"] if c is not chk]
    before, after = cumulative({"checks": prev}), cumulative(cm)
    out = ["按约定来复盘了：愿意如实说，本身就是坚持"]
    out += [f"累计完成第 {m} 次（累计不清零）" for m in MILESTONES if before < m <= after]
    rate, rates = check_rate(cm, chk), [check_rate(cm, c) for c in prev]
    if rate and rates and all(r is not None and rate > r for r in rates):
        out.append("这是到目前为止执行率最高的一次")
    if chk["times"] > 0 and prev:
        last = max(prev, key=lambda c: c["date"])
        gap = (to_date(chk["date"]) - to_date(last["date"])).days
        if last["times"] == 0 or gap > 2 * cad:
            out.append("中断之后重新开始了：重新开始比从不中断更难")
    if rate is not None and 0 < rate < 1:
        if chk["period_days"] == 1:
            out.append("做了一部分：部分做到也算数")
        else:
            target = cadence_rate(cm["cadence"]) * chk["period_days"]
            out.append(f"这 {chk['period_days']} 天做到了 {chk['times']:g} 次（约定约 {target:.0f} 次）：部分做到也算数")
    elif rate == 1:
        out.append("这一段完全做到了约定")
    weeks = (to_date(chk["date"]) - to_date(cm["since"])).days // 7
    if weeks >= 4 and after > 0:
        out.append(f"开始这个小动作已经 {weeks} 周，你还在继续")
    return out


def wins_since(st: Dict[str, Any], jr: List[Dict[str, Any]], since: Optional[str]) -> Dict[str, Any]:
    """Material for positive feedback at the start of a session: everything good since the last session."""
    since = since or "0000-00-00"
    commits = []
    for c in st["commitments"]:
        done = sum(x["times"] for x in c.get("checks", []) if x["date"] > since)
        crossed = [m for m in MILESTONES if cumulative(c, since) < m <= cumulative(c)]
        if done or crossed or (c["status"] == "graduated"):
            commits.append({"id": c["id"], "action": c["action"], "status": c["status"], "done_since": done,
                            "cumulative": cumulative(c), "milestones_crossed": crossed})
    logged: Dict[str, int] = {}
    for m in st["measurements"]:
        if m["date"] > since and not str(m.get("source", "")).startswith("analyst:"):
            logged[m["marker"]] = logged.get(m["marker"], 0) + 1
    return {"since": None if since == "0000-00-00" else since, "commitments": commits, "measurements_logged": logged,
            "experiments_closed": [{"id": e["id"], "title": e["title"], "outcome": e.get("outcome")}
                                   for e in st["experiments"] if e.get("closed") and e["closed"] > since],
            "win_notes": [{"id": j["id"], "text": j["text"]} for j in jr if j.get("kind") == "win" and j["t"][:10] > since]}


# ---------------------------------------------------------------- commands: setup, members, profile

def cmd_setup(a: argparse.Namespace) -> None:
    home = coach_home(a)
    home.mkdir(parents=True, exist_ok=True)
    cfg = config(home)
    for kind, given, test in (("library", a.library, _is_library), ("analyst", a.analyst, _is_analyst)):
        if given:
            p = Path(given).expanduser().resolve()
            if not test(p):
                need = "catalog.json + intents.json" if kind == "library" else "SKILL.md + scripts/la.py"
                raise CoachError(f"{p} is not a {kind} directory (needs {need})")
            cfg[kind] = str(p)
        elif not (cfg.get(kind) and test(Path(cfg[kind]))):
            d = _discover(kind)
            if d:
                cfg[kind] = str(d)
    write_json(home / "config.json", cfg)

    def ver(p: Optional[str], rel: str) -> Optional[str]:
        f = Path(p) / rel if p else None
        return f.read_text(encoding="utf-8").strip() if f and f.is_file() else None

    emit({"home": str(home), "library": cfg.get("library"), "library_version": ver(cfg.get("library"), "VERSION"),
          "analyst": cfg.get("analyst"), "analyst_version": ver(cfg.get("analyst"), "../../VERSION"),
          "members": sorted(p.name for p in (home / "members").glob("*") if (p / "state.json").exists()),
          "missing": [k for k in ("library", "analyst") if not cfg.get(k)]})


def cmd_members(a: argparse.Namespace) -> None:
    home = coach_home(a)
    rows = []
    for p in sorted((home / "members").glob("*")):
        if (p / "state.json").exists():
            st = load_json(p / "state.json")
            rows.append({"id": p.name, "name": st["member"].get("name"),
                         "last_session": (st.get("last_session") or {}).get("t")})
    emit({"home": str(home), "members": rows})


def cmd_init(a: argparse.Namespace) -> None:
    home = coach_home(a)
    d = mdir(home, a.member)
    if (d / "state.json").exists():
        raise CoachError(f"member '{a.member}' exists; change it with `profile` or `persona`")
    if a.tone not in TONES:
        raise CoachError(f"tone: one of {', '.join(TONES)}")
    st: Dict[str, Any] = {
        "schema": SCHEMA,
        "member": {"id": a.member, "name": a.name, "sex": norm_sex(a.sex), "birth_date": None, "age_at": None},
        "persona": {"coach_name": a.coach_name, "tone": a.tone, "address": a.address},
        "cadence_days": a.cadence_days,
        "facts": {}, "goals": [], "commitments": [], "experiments": [], "measurements": [], "readouts": [],
        "proposals": [], "retests": [], "analyst_visits": [], "skill_results": [], "safety": [],
        "last_session": None, "seq": 0, "created_at": now_iso(),
    }
    if a.birth_date:
        st["member"]["birth_date"] = to_date(a.birth_date).isoformat()
    elif a.age is not None:
        st["member"]["age_at"] = {"age": a.age, "date": today().isoformat()}
    d.mkdir(parents=True, exist_ok=True)
    journal_add(home, a.member, st, {"kind": "system", "text": "建档"})
    save_state(home, a.member, st)
    emit({"member": a.member, "dir": str(d), "persona": st["persona"], "age": member_age(st), "sex": st["member"]["sex"]})


def cmd_profile(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    m, changed = st["member"], {}
    if a.name:
        m["name"] = changed["name"] = a.name
    if a.sex:
        m["sex"] = changed["sex"] = norm_sex(a.sex)
    if a.birth_date:
        m["birth_date"], m["age_at"] = to_date(a.birth_date).isoformat(), None
        changed["birth_date"] = m["birth_date"]
    elif a.age is not None:
        m["age_at"], m["birth_date"] = {"age": a.age, "date": today().isoformat()}, None
        changed["age"] = a.age
    if a.cadence_days:
        st["cadence_days"] = changed["cadence_days"] = a.cadence_days
    if not changed:
        raise CoachError("nothing to change")
    journal_add(home, a.member, st, {"kind": "profile", "text": json.dumps(changed, ensure_ascii=False), "source": a.source})
    save_state(home, a.member, st)
    emit({"member": a.member, "changed": changed, "age": member_age(st)})


def cmd_persona(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    if a.tone and a.tone not in TONES:
        raise CoachError(f"tone: one of {', '.join(TONES)}")
    for k in ("coach_name", "tone", "address"):
        v = getattr(a, k)
        if v:
            st["persona"][k] = v
    journal_add(home, a.member, st, {"kind": "persona", "text": json.dumps(st["persona"], ensure_ascii=False)})
    save_state(home, a.member, st)
    emit({"member": a.member, "persona": st["persona"]})


def cmd_fact(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    done = {}
    for pair in a.pairs:
        if "=" not in pair:
            raise CoachError(f"expected key=value, got {pair}")
        k, v = (s.strip() for s in pair.split("=", 1))
        if k.startswith("stage.") and v not in STAGES:
            raise CoachError(f"stage value: one of {', '.join(STAGES)}")
        if k == "data_has":
            bad = [t for t in re.split(r"[,，、\s]+", v) if t and t not in LADDER_TYPES]
            if bad:
                raise CoachError(f"data_has: unknown types {bad}; use {', '.join(LADDER_TYPES)}")
        st["facts"][k] = {"value": v, "source": a.source, "t": now_iso()}
        done[k] = v
    journal_add(home, a.member, st, {"kind": "fact", "text": json.dumps(done, ensure_ascii=False), "source": a.source})
    save_state(home, a.member, st)
    emit({"member": a.member, "facts_set": done})


def cmd_remember(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    e = {"kind": a.kind, "text": a.text}
    if a.source:
        e["source"] = a.source
    if a.date:
        e["date"] = date_arg(a.date)
    if a.tags:
        e["tags"] = [t.strip() for t in a.tags.split(",") if t.strip()]
    e = journal_add(home, a.member, st, e)
    save_state(home, a.member, st)
    emit({"member": a.member, "remembered": e})


def cmd_forget(a: argparse.Namespace) -> None:
    home = coach_home(a)
    d = mdir(home, a.member)
    if a.everything:
        if a.confirm != a.member:
            raise CoachError(f"deleting everything needs --confirm {a.member}")
        load_state(home, a.member)
        shutil.rmtree(d)
        emit({"member": a.member, "deleted": "everything", "dir": str(d)})
        return
    st = load_state(home, a.member)
    removed = None
    if a.fact:
        if st["facts"].pop(a.fact, None) is None:
            raise CoachError(f"no fact {a.fact}")
        removed = f"fact:{a.fact}"
    elif a.id and a.id.startswith("J"):
        rows = journal(home, a.member)
        keep = [r for r in rows if r["id"] != a.id]
        if len(keep) == len(rows):
            raise CoachError(f"no journal entry {a.id}")
        with open(d / "journal.jsonl", "w", encoding="utf-8") as f:
            f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in keep)
        removed = a.id
    elif a.id:
        for lst in ("measurements", "goals", "readouts"):
            n = len(st[lst])
            st[lst] = [x for x in st[lst] if x.get("id") != a.id]
            if len(st[lst]) < n:
                removed = a.id
                break
        if not removed:
            raise CoachError(f"no journal entry, measurement, goal or readout with id {a.id}")
    else:
        raise CoachError("give --id, --fact or --everything")
    journal_add(home, a.member, st, {"kind": "system", "text": f"按用户要求删除 {removed}"})
    save_state(home, a.member, st)
    emit({"member": a.member, "deleted": removed})


# ---------------------------------------------------------------- goals and commitments

def cmd_goal_add(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    g = {"id": new_id(st["goals"], "G"), "why": a.why, "picture": a.picture, "area": a.area,
         "status": "active", "t": today().isoformat()}
    st["goals"].append(g)
    journal_add(home, a.member, st, {"kind": "goal", "text": f"{g['id']} {a.picture}", "source": a.source})
    save_state(home, a.member, st)
    emit({"member": a.member, "goal": g})


def cmd_goal_set(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    g = find(st["goals"], a.id, "goal")
    g["status"] = a.status
    journal_add(home, a.member, st, {"kind": "goal", "text": f"{a.id} → {a.status}", "source": a.note})
    save_state(home, a.member, st)
    emit({"member": a.member, "goal": g})


def cmd_commit_add(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    cadence_rate(a.cadence)
    if a.from_proposal:
        p = find(st["proposals"], a.from_proposal, "proposal")
        if p["executor"] != "member":
            raise CoachError(f"{p['id']} is for the {p['executor']}; the member cannot adopt it as a habit")
        p["status"] = "adopted"
    c = {"id": new_id(st["commitments"], "C"), "area": a.area, "action": a.action, "when": a.when,
         "cadence": a.cadence, "confidence": a.confidence, "status": "active", "since": date_arg(a.start),
         "goal": a.goal, "from_proposal": a.from_proposal, "checks": []}
    st["commitments"].append(c)
    journal_add(home, a.member, st, {"kind": "commitment", "text": f"{c['id']} {a.when}，{a.action}"})
    save_state(home, a.member, st)
    warn = []
    if a.confidence is not None and a.confidence < 7:
        warn.append("把握度低于 7：先把这个动作缩小到有 7 分以上把握再开始（commit set --action ...）")
    if len([x for x in st["commitments"] if x["status"] == "active"]) > 3:
        warn.append("进行中的承诺超过 3 个：考虑暂停一个，少而能做到胜过多而做不到")
    emit({"member": a.member, "commitment": c, "warnings": warn})


def cmd_commit_check(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    c = find(st["commitments"], a.id, "commitment")
    if a.times is not None:
        times, period = a.times, a.period or 7
    elif a.done:
        frac = {"yes": 1.0, "partial": 0.5, "no": 0.0}[a.done]
        if c["cadence"] in ("daily", "weekdays"):
            times, period = frac, 1
        elif c["cadence"] == "weekly":
            times, period = frac, 7
        else:
            raise CoachError(f"{c['id']} is {c['cadence']}: report the period instead, e.g. --times 2 --period 7")
    else:
        raise CoachError("give --done yes|partial|no or --times N [--period DAYS]")
    chk = {"date": date_arg(a.date, past=True), "times": times, "period_days": period}
    if a.note:
        chk["note"] = a.note
    c["checks"].append(chk)
    journal_add(home, a.member, st, {"kind": "checkin", "text": f"{c['id']} {times}/{period}d {a.note or ''}".strip()})
    save_state(home, a.member, st)
    emit({"member": a.member, "commitment": c["id"], "check": chk, "adherence_28d": adherence(c),
          "cumulative": cumulative(c), "celebrate": celebrations(c, chk, st.get("cadence_days") or 7)})


def cmd_commit_set(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    c = find(st["commitments"], a.id, "commitment")
    before = {k: c[k] for k in ("status", "action", "when", "cadence")}
    if a.cadence:
        cadence_rate(a.cadence)
    for k in ("status", "action", "when", "cadence"):
        v = getattr(a, k)
        if v:
            c[k] = v
    if a.confidence is not None:
        c["confidence"] = a.confidence
    journal_add(home, a.member, st, {"kind": "commitment", "text": f"{c['id']} 调整：{json.dumps(before, ensure_ascii=False)} → "
                                     f"{json.dumps({k: c[k] for k in before}, ensure_ascii=False)}", "source": a.note})
    save_state(home, a.member, st)
    emit({"member": a.member, "commitment": c})


def cmd_proposal_set(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    p = find(st["proposals"], a.id, "proposal")
    p["status"] = a.status
    if a.note:
        p["note"] = a.note
    journal_add(home, a.member, st, {"kind": "proposal", "text": f"{p['id']}（{p['action']}）→ {a.status}", "source": a.note})
    save_state(home, a.member, st)
    emit({"member": a.member, "proposal": p})


def cmd_retest_add(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    r = {"id": new_id(st["retests"], "T"), "what": a.what, "due": date_arg(a.due), "origin": "coach",
         "intervention": a.experiment, "status": "open"}
    st["retests"].append(r)
    journal_add(home, a.member, st, {"kind": "retest", "text": f"{r['id']} {a.what} 约在 {r['due']}"})
    save_state(home, a.member, st)
    emit({"member": a.member, "retest": r})


def cmd_retest_set(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    r = find(st["retests"], a.id, "retest")
    r["status"] = a.status
    if a.due:
        r["due"] = date_arg(a.due)
    journal_add(home, a.member, st, {"kind": "retest", "text": f"{r['id']} {r['what']} → {r['status']}", "source": a.note})
    save_state(home, a.member, st)
    emit({"member": a.member, "retest": r})


# ---------------------------------------------------------------- measurements and change judgment

def cmd_measure_add(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    try:
        value = float(str(a.value).replace(",", ""))
    except ValueError:
        raise CoachError("value must be a plain number; a censored value such as '<0.5' goes into `remember`, not here")
    _, idx = biovar(library_dir(home, required=False))
    bm = match_bv(idx, a.marker)
    date = date_arg(a.date, past=True)
    for x in st["measurements"]:
        if fold(x["marker"]) == fold(a.marker) and x["date"] == date and x["value"] == value and norm_unit(x["unit"]) == norm_unit(a.unit):
            emit({"member": a.member, "skipped": "same marker, date, value and unit already recorded", "id": x["id"]})
            return
    m = {"id": new_id(st["measurements"], "M"), "marker": a.marker, "key": bm["key"] if bm else None, "value": value,
         "unit": a.unit, "date": date, "source": a.source}
    if a.context:
        m["context"] = a.context
    st["measurements"].append(m)
    save_state(home, a.member, st)
    out: Dict[str, Any] = {"member": a.member, "measurement": m}
    if bm and norm_unit(bm["unit"]) != norm_unit(a.unit) and convert(bm["key"], 1.0, a.unit, bm["unit"]) is None:
        out["note"] = f"单位 {a.unit} 和变异表的 {bm['unit']} 不同且没有换算；同单位的测量之间仍能比较"
    emit(out)


def cmd_measure_list(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    _, idx = biovar(library_dir(home, required=False))
    rows = series(st, a.marker, idx) if a.marker else sorted(st["measurements"], key=lambda x: (x["marker"], x["date"]))
    emit({"member": a.member, "measurements": rows})


def judge(m: Optional[Dict[str, Any]], z: float, base: List[Dict[str, Any]], cur: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compare the centre of `base` with the centre of `cur` against the reference change value."""
    unit = cur[-1]["unit"]
    key = m["key"] if m else None

    def vals(rows: List[Dict[str, Any]]) -> Tuple[List[float], List[str]]:
        out, dropped = [], []
        for r in rows:
            v = convert(key, r["value"], r["unit"], unit)
            if v is None:
                dropped.append(f"{r['id']}（{r['unit']}）")
            else:
                out.append(v)
        return out, dropped

    bv, bd = vals(base)
    cv, cd = vals(cur)
    res: Dict[str, Any] = {"unit": unit, "baseline": {"ids": [r["id"] for r in base], "dates": [r["date"] for r in base]},
                           "current": {"ids": [r["id"] for r in cur], "dates": [r["date"] for r in cur]}}
    if bd or cd:
        res["dropped_unit_mismatch"] = bd + cd
    if not bv or not cv:
        res.update(verdict="not_judged", why="没有同单位、可比较的两组数值")
        return res
    ln = bool(m and m.get("log_normal"))
    a_, b_ = center(bv, ln), center(cv, ln)
    res["baseline"]["value"], res["current"]["value"] = round(a_, 4), round(b_, 4)
    res["baseline"]["n"], res["current"]["n"] = len(bv), len(cv)
    gap = (to_date(cur[0]["date"]) - to_date(base[-1]["date"])).days
    if not m:
        res.update(verdict="not_judged", why="变异表里没有这个指标的个体内生物变异，只并排列出数值，不说变好变坏")
    elif gap < 1:
        res.update(verdict="not_judged", why="两组测量在同一天")
    elif m.get("min_retest_days") and gap < m["min_retest_days"]:
        res.update(verdict="not_judged", why=f"两组只隔 {gap} 天，这个指标至少要隔 {m['min_retest_days']} 天")
    elif a_ == 0:
        res.update(verdict="not_judged", why="基线为 0")
    else:
        up, down = rcv_pct(m, z, len(bv), len(cv))
        ch = 100 * (b_ - a_) / a_
        verdict = "increase_beyond_noise" if ch > up else "decrease_beyond_noise" if ch < down else "within_noise"
        res.update(change_pct=round(ch, 1), noise_band_pct=[round(down, 1), round(up, 1)], verdict=verdict,
                   better_direction=m.get("better"), bv_source=m["cvi_source"]["doi"],
                   assumptions="基线与复测各取均值（对数正态指标取几何均值）；每个值须来自不同的日子；CVA 未给出时取 0.5×CVI")
        if m["key"] == "vitd" and {d[5:7] for d in res["baseline"]["dates"]} != {d[5:7] for d in res["current"]["dates"]}:
            res["caveat"] = "25(OH)D 有季节性波动，不同季节的差异可能来自日照"
    return res


def cmd_compare(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    z, idx = biovar(library_dir(home, required=False))
    rows = series(st, a.marker, idx)
    if a.before:
        cut = to_date(a.before)
        base = [r for r in rows if to_date(r["date"]) < cut][-a.k:]
        cur = [r for r in rows if to_date(r["date"]) >= cut][-a.k:]
    else:
        k = min(a.k, len(rows) // 2)
        base, cur = rows[:k], rows[-k:] if k else []
    if not base or not cur:
        raise CoachError(f"need measurements on both sides; found {len(rows)} for {a.marker}")
    emit({"member": a.member, "marker": a.marker, **judge(match_bv(idx, a.marker), z, base, cur)})


# ---------------------------------------------------------------- N-of-1 experiments

def _effect_rows(lib: Path, intervention: Optional[str], idx: Dict[str, Dict[str, Any]],
                 marker: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    q = fold(intervention) if intervention else ""
    for e in lib_json(lib, "data/effects.jsonl"):
        names = [e.get("intervention_zh", ""), *e.get("keywords", [])]
        if q and not any(fold(n) and (fold(n) in q or q in fold(n)) for n in names):
            continue
        em = match_bv(idx, e.get("marker_zh", "")) or match_bv(idx, e.get("marker", ""))
        if marker and (not em or em["key"] != marker["key"]):
            continue
        out.append({**e, "_bv": em})
    return out


def follow_window(repeats: int) -> int:
    return max(14, repeats)


def min_weeks(m: Dict[str, Any], repeats: int, trial_weeks: Optional[float]) -> int:
    """Shortest experiment whose follow-up window starts at least min_retest_days after the baseline."""
    need = math.ceil(((m.get("min_retest_days") or 0) + follow_window(repeats)) / 7)
    return int(max(need, math.ceil(trial_weeks or 0), 4))


def design(lib: Path, st: Optional[Dict[str, Any]], intervention: Optional[str], marker_name: Optional[str],
           repeats: int, baseline: Optional[float], unit: Optional[str], per_units: Optional[float],
           before: Optional[dt.date] = None) -> Dict[str, Any]:
    z, idx = biovar(lib)
    marker = match_bv(idx, marker_name) if marker_name else None
    if marker_name and not marker:
        return {"marker": marker_name, "noise_model": None,
                "verdict": "no_noise_model",
                "why": "变异表里没有这个指标的个体内生物变异：单人前后对比没法判断，只能并排列出数值（衰老时钟、器官年龄都属于这一类）"}
    rows = _effect_rows(lib, intervention, idx, marker) if (intervention or marker) else []
    out: Dict[str, Any] = {"intervention": intervention, "marker": marker_name, "repeats_each_side": repeats, "z": z}

    def personal_baseline(m: Dict[str, Any]) -> Tuple[Optional[float], Optional[str], str]:
        if baseline is not None and m is marker:
            return baseline, unit or m["unit"], "given"
        if st:
            s = [r for r in series(st, m["key"], idx) if before is None or to_date(r["date"]) < before]
            if s:
                last = s[-repeats:]
                u = last[-1]["unit"]
                vals = [v for v in (convert(m["key"], r["value"], r["unit"], u) for r in last) if v is not None]
                if vals:
                    return center(vals, bool(m.get("log_normal"))), u, f"最近 {len(vals)} 次记录"
        return None, None, "none"

    def noise(m: Dict[str, Any], base: Optional[float], u: Optional[str]) -> Dict[str, Any]:
        up1, dn1 = rcv_pct(m, z)
        upk, dnk = rcv_pct(m, z, repeats, repeats)
        n = {"marker_key": m["key"], "label_zh": m["label_zh"], "cvi_pct": m["cvi_pct"], "log_normal": m["log_normal"],
             "band_single_pct": [round(dn1, 1), round(up1, 1)], "band_with_repeats_pct": [round(dnk, 1), round(upk, 1)],
             "min_retest_days": m.get("min_retest_days"), "bv_source": m["cvi_source"]["doi"]}
        if base is not None:
            n["baseline"] = {"value": round(base, 3), "unit": u}
            n["band_with_repeats_abs"] = [round(base * dnk / 100, 3), round(base * upk / 100, 3)]
        n["suggested_min_weeks"] = min_weeks(m, repeats, None)
        return n

    if marker and not rows:
        b, u, src = personal_baseline(marker)
        out["noise"] = noise(marker, b, u)
        out["effects"] = []
        out["why"] = ("证据库里没有这个干预对这个指标的试验均值；能说清的是要多大变化才算真变化。干预本身的证据去查 longevity-evidence"
                      if intervention else "只给噪声带：要多大变化才算超出这个人的正常波动")
        return out

    results = []
    for e in rows:
        m = e.pop("_bv")
        r: Dict[str, Any] = {k: e.get(k) for k in ("id", "intervention_zh", "marker_zh", "category", "effect", "design",
                                                   "trials", "participants", "population", "duration_weeks", "doi", "note_zh")}
        if e.get("category") in ("drug", "supplement"):
            r["requires_professional"] = "药物或补剂：开始与否和剂量由医生或营养师决定，教练只设计测量"
        if not m:
            r.update(verdict="no_noise_model", why="这个指标没有个体内生物变异数据，单人前后对比没法判断")
            results.append(r)
            continue
        b, u, src = personal_baseline(m)
        r["noise"] = noise(m, b, u)
        eff = e["effect"]
        kind = eff.get("kind")
        pct = cons = None
        if kind == "percent_change":
            pct = eff["value"]
            cons = min(eff["ci"], key=abs) if eff.get("ci") else None
        elif kind in ("mean_difference", "per_unit"):
            mult = 1.0
            if kind == "per_unit":
                if per_units is None:
                    r.update(verdict="needs_amount", why=f"效应按「{eff.get('per')}」给出；用 --per-units 写计划的量")
                    results.append(r)
                    continue
                mult = per_units
            if b is None:
                r.update(verdict="needs_baseline", why="没有这个人的基线值：先记录测量，或用 --baseline/--unit 给出")
                results.append(r)
                continue
            conv = convert(m["key"], eff["value"] * mult, eff["unit"], u)
            if conv is None:
                r.update(verdict="unit_mismatch", why=f"试验单位 {eff['unit']} 换算不到 {u}")
                results.append(r)
                continue
            pct = 100 * conv / b
            if eff.get("ci"):
                c0 = convert(m["key"], min(eff["ci"], key=abs) * mult, eff["unit"], u)
                cons = 100 * c0 / b if c0 is not None else None
            r["source_baseline"] = src
        else:
            r.update(verdict="not_comparable", why="标准化效应或速率换算不到这个人的单位，没法和噪声带比较")
            results.append(r)
            continue
        k50, k80 = k_needed(m, z, pct), k_needed(m, z + Z80, pct)
        r["expected_change_pct"] = round(pct, 1)
        if cons is not None:
            r["expected_change_pct_ci_edge"] = round(cons, 1)
            r["k80_at_ci_edge"] = k_needed(m, z + Z80, cons) if cons else None
        r["k_each_side_half_chance"], r["k_each_side_80pct"] = k50, k80
        if k80 is not None and repeats >= k80:
            r["verdict"] = "likely_detectable"
        elif k50 is not None and repeats >= k50:
            r["verdict"] = "coin_flip"
        else:
            r["verdict"] = "unlikely_detectable"
        if k50 is not None and k50 > 30:
            r["advice"] = "试验平均效应远小于这个人的日间波动：单人前后对比看不出来，信试验均值比信自己的前后对比更靠谱"
        r["suggested_min_weeks"] = min_weeks(m, repeats, e.get("duration_weeks"))
        r["caveat"] = "试验均值是人群平均，不是这个人的效应；试验人群见 population"
        results.append(r)
    out["effects"] = results
    if not results:
        out["why"] = "证据库没有这个干预的试验均值；去查 longevity-evidence，或只为指标设计噪声带（加 --marker）"
    return out


def cmd_exp_design(a: argparse.Namespace) -> None:
    home = coach_home(a)
    lib = library_dir(home)
    st = load_state(home, a.member) if a.member else None
    if not a.intervention and not a.marker:
        raise CoachError("give --intervention, --marker or both")
    emit(design(lib, st, a.intervention, a.marker, a.repeats, a.baseline, a.unit, a.per_units))


def cmd_exp_start(a: argparse.Namespace) -> None:
    home = coach_home(a)
    lib = library_dir(home)
    st = load_state(home, a.member)
    if a.commitment:
        find(st["commitments"], a.commitment, "commitment")
    start = date_arg(a.start)
    d = design(lib, st, a.intervention, a.marker, a.repeats, None, None, a.per_units, before=to_date(start))
    e = {"id": new_id(st["experiments"], "E"), "title": a.title, "intervention": a.intervention, "marker": a.marker,
         "start": start, "weeks": a.weeks, "repeats": a.repeats, "rule": a.rule, "commitment": a.commitment,
         "status": "active", "design": d}
    st["experiments"].append(e)
    journal_add(home, a.member, st, {"kind": "experiment", "text": f"{e['id']} 开始：{a.title}；判定规则：{a.rule}"})
    save_state(home, a.member, st)
    warn = []
    if any(r.get("requires_professional") for r in d.get("effects", [])):
        warn.append("这个干预是药物或补剂：确认医生或营养师已经同意，教练只负责测量方案")
    noises = [d.get("noise")] + [r.get("noise") for r in d.get("effects", [])]
    need = max([n["suggested_min_weeks"] for n in noises if n] or [0])
    if need and a.weeks < need:
        warn.append(f"按这个指标的最短复测间隔和 {a.repeats} 次复测，实验至少要 {need} 周，否则复测窗口离基线太近，结束时没法判断")
    emit({"member": a.member, "experiment": {k: v for k, v in e.items() if k != "design"}, "design": d, "warnings": warn})


def follow_from(e: Dict[str, Any]) -> dt.date:
    return to_date(e["start"]) + dt.timedelta(days=max(0, e["weeks"] * 7 - follow_window(e["repeats"])))


def cmd_exp_review(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    z, idx = biovar(library_dir(home, required=False))
    e = find(st["experiments"], a.id, "experiment")
    rows = series(st, e["marker"], idx)
    start = to_date(e["start"])
    ff = to_date(a.follow_from) if a.follow_from else follow_from(e)
    base = [r for r in rows if to_date(r["date"]) < start][-e["repeats"]:]
    cur = [r for r in rows if to_date(r["date"]) >= ff][-e["repeats"]:]
    out: Dict[str, Any] = {"member": a.member, "experiment": e["id"], "title": e["title"], "rule": e["rule"],
                           "start": e["start"], "end": (start + dt.timedelta(days=e["weeks"] * 7)).isoformat(),
                           "follow_up_from": ff.isoformat(), "baseline_n": len(base), "follow_up_n": len(cur),
                           "planned_each_side": e["repeats"]}
    if e.get("commitment"):
        c = find(st["commitments"], e["commitment"], "commitment")
        out["adherence"] = adherence(c, window_days=max(28, e["weeks"] * 7))
        rate = (out["adherence"] or {}).get("rate")
        if rate is not None and rate < 0.7:
            out["adherence_warning"] = "执行率低于 70%：这次结果不能当作这个干预的检验"
    if today() < ff and not a.follow_from:
        out.update(verdict="too_early", why=f"复测窗口从 {ff.isoformat()} 开始，现在下结论会把噪声当效果")
    elif not base or not cur:
        out.update(verdict="not_judged", why="基线或复测测量缺失")
    else:
        out["judgment"] = judge(match_bv(idx, e["marker"]), z, base, cur)
        if len(base) < e["repeats"] or len(cur) < e["repeats"]:
            out["note"] = "测量次数少于计划，噪声带按实际次数计算，会更宽"
    emit(out)


def cmd_exp_close(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    e = find(st["experiments"], a.id, "experiment")
    e.update(status="closed", outcome=a.outcome, closed=today().isoformat(), note=a.note)
    journal_add(home, a.member, st, {"kind": "experiment", "text": f"{e['id']} 结束：{a.outcome}；{a.note or ''}".strip()})
    save_state(home, a.member, st)
    emit({"member": a.member, "experiment": {k: v for k, v in e.items() if k != "design"}})


# ---------------------------------------------------------------- routing into the method library

def readiness(skill: Dict[str, Any], st: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if st is None:
        return {"status": "unknown_member"}
    have = {v for m in st["measurements"] for v in name_variants(m["marker"])}
    missing, args_needed = [], []
    meas = [i for i in skill.get("inputs", []) if i.get("from") == "measurements"]
    present = [i.get("label_zh", i["key"]) for i in meas
               if any(v in have for n in [i["key"], i.get("label_zh", ""), *i.get("aliases", [])] for v in name_variants(n))]
    for inp in skill.get("inputs", []):
        if not inp.get("required"):
            continue
        src, label = inp.get("from"), inp.get("label_zh", inp["key"])
        if src == "profile":
            ok = st["member"].get("sex") if inp["key"] == "sex" else member_age(st) is not None if inp["key"] == "age" \
                else inp["key"] in st["facts"]
            if not ok:
                missing.append(label)
        elif src == "measurements":
            names = [inp["key"], inp.get("label_zh", ""), *inp.get("aliases", [])]
            if not any(v in have for n in names for v in name_variants(n)):
                missing.append(label)
        else:
            args_needed.append(label)
    status = "missing" if missing else "no_data" if meas and not present else "ready"
    return {"status": status, "missing": missing, "present": present, "measurement_inputs": len(meas),
            "arguments": args_needed}


def cmd_route(a: argparse.Namespace) -> None:
    home = coach_home(a)
    lib = library_dir(home)
    st = load_state(home, a.member) if a.member else None
    q = unicodedata.normalize("NFKC", a.question).casefold()
    intents = lib_json(lib, "intents.json")["intents"]
    catalog = {s["name"]: s for s in lib_json(lib, "catalog.json")["skills"]}
    scored = []
    for it in intents:
        hits = [t for t in it.get("triggers", []) if contains_term(q, t)]
        ents = [t for t in it.get("entities", []) if contains_term(q, t)]
        if hits or ents:
            scored.append((len(hits) + len(ents), it.get("priority", 0), it, hits, ents))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    out: Dict[str, Any] = {"question": a.question,
                           "safety_hits": [t for t in RED_FLAGS if contains_term(q, t)],
                           "analyst_hint": [t for t in ANALYST_HINTS if contains_term(q, t)],
                           "intents": []}
    for score, _, it, hits, ents in scored[:3]:
        skills = []
        for name in it["skills"]:
            s = catalog.get(name)
            if not s or (s["tier"] == "C" and it["id"] != "model_organism"):
                continue
            skills.append({"name": name, "tier": s["tier"], "blurb_zh": s.get("blurb_zh"), "has_script": s.get("has_script"),
                           "skill_md": str(lib / "skills" / name / "SKILL.md"), "readiness": readiness(s, st)})
        out["intents"].append({"id": it["id"], "label_zh": it["label_zh"], "data": it.get("data", []), "matched": hits,
                               "entities": ents, "skills": skills})
    if out["safety_hits"]:
        out["next"] = "safety_first: 先按 references/safety.md 处理，暂停其他一切"
    elif out["analyst_hint"]:
        out["next"] = "analyst: 原始数据或整套检测走 longevity-analyst（先讲清耗时和磁盘，按它自己的同意流程）"
    elif out["intents"]:
        out["next"] = "method_library: 选一个 readiness=ready 的技能，用 `coach.py prepare` 准备输入"
    else:
        out["next"] = "coach_only: 没有对上方法库的意图，这是一次教练对话（动机、习惯、情绪、计划）"
    emit(out)


def cmd_prepare(a: argparse.Namespace) -> None:
    home = coach_home(a)
    lib = library_dir(home)
    st = load_state(home, a.member)
    s = {x["name"]: x for x in lib_json(lib, "catalog.json")["skills"]}.get(a.skill)
    if not s:
        raise CoachError(f"no skill {a.skill} in catalog.json")
    entry = s.get("entry") or {}
    skill_md = lib / "skills" / a.skill / "SKILL.md"
    if not s.get("has_script") or not entry.get("script"):
        emit({"skill": a.skill, "skill_md": str(skill_md), "note": "这个技能没有个人读出脚本：读它的 SKILL.md 按说明执行"})
        return
    runs = mdir(home, a.member) / "runs"
    n = len(list(runs.glob(f"{a.skill}-{today().isoformat()}*"))) if runs.exists() else 0
    run = runs / f"{a.skill}-{today().isoformat()}" if n == 0 else runs / f"{a.skill}-{today().isoformat()}-{n + 1}"
    run.mkdir(parents=True, exist_ok=True)
    rows, used, missing, args_needed, flags = [], [], [], [], []
    for inp in s.get("inputs", []):
        label = inp.get("label_zh", inp["key"])
        if inp.get("from") == "measurements":
            names = {v for nm in [inp["key"], inp.get("label_zh", ""), *inp.get("aliases", [])] for v in name_variants(nm)}
            cands = [m for m in st["measurements"] if names & set(name_variants(m["marker"]))]
            if cands:
                m = max(cands, key=lambda x: x["date"])
                rows.append([label, f"{m['value']:g}", m["unit"]])
                used.append({"input": inp["key"], "measurement": m["id"], "marker": m["marker"], "value": m["value"],
                             "unit": m["unit"], "date": m["date"]})
            elif inp.get("required"):
                missing.append(label)
        elif inp.get("from") == "profile":
            if inp.get("required") and ((inp["key"] == "age" and member_age(st) is None)
                                        or (inp["key"] == "sex" and not st["member"].get("sex"))):
                missing.append(label)
        elif inp.get("from") == "argument":
            args_needed.append({"input": inp["key"], "label_zh": label, "required": bool(inp.get("required"))})
    warnings = []
    if used:
        ds = sorted(to_date(u["date"]) for u in used)
        if (ds[-1] - ds[0]).days > 90:
            warnings.append(f"混用了相隔 {(ds[-1] - ds[0]).days} 天的测量：同一个公式里的化验值应来自同一次抽血")
    cmd = [f'python3 "{lib / "skills" / a.skill / entry["script"]}"']
    if entry.get("measurements_flag") and rows:
        csv = run / "measurements.csv"
        header = entry.get("measurements_header") or ["marker", "value", "unit"]
        with open(csv, "w", encoding="utf-8") as f:
            f.write(",".join(header) + "\n")
            f.writelines(",".join(c.replace(",", " ") for c in r) + "\n" for r in rows)
        cmd.append(f'{entry["measurements_flag"]} "{csv}"')
    age, sex = member_age(st), st["member"].get("sex")
    if entry.get("age_flag") and age is not None:
        cmd.append(f"{entry['age_flag']} {age}")
    if entry.get("sex_flag") and sex:
        cmd.append(f"{entry['sex_flag']} {sex}")
    meds = st["facts"].get("medications")
    if entry.get("medications_flag") and meds:
        mf = run / "medications.txt"
        mf.write_text("\n".join(x.strip() for x in re.split(r"[,，、;；\n]+", meds["value"]) if x.strip()) + "\n", encoding="utf-8")
        cmd.append(f'{entry["medications_flag"]} "{mf}"')
    cmd.append(f'{entry.get("out_flag", "--out")} "{run / "out"}"')
    emit({"member": a.member, "skill": a.skill, "tier": s["tier"], "skill_md": str(skill_md), "run_dir": str(run),
          "command": " ".join(cmd), "used": used, "missing_required": missing, "arguments_needed": args_needed,
          "warnings": warnings,
          "next": "先读 skill_md；补齐 missing_required 和需要的参数后执行 command，再 `coach.py import-result`"})


def cmd_ladder(a: argparse.Namespace) -> None:
    home = coach_home(a)
    lib = library_dir(home)
    st = load_state(home, a.member)
    has = data_has(st)
    intents = lib_json(lib, "intents.json")["intents"]
    catalog = {s["name"]: s for s in lib_json(lib, "catalog.json")["skills"]}
    rungs = []
    for t, label, access in DATA_LADDER:
        its = [i for i in intents if t in i.get("data", [])]
        n = len({s for i in its for s in i["skills"] if catalog.get(s, {}).get("tier") in ("A", "B", "tool")})
        rungs.append({"type": t, "label_zh": label, "accessibility": access, "has": t in has,
                      "unlocks": [i["label_zh"] for i in its], "methods": n})
    nxt = [r for r in rungs if not r["has"] and r["accessibility"] == "high"][:2] or \
        [r for r in rungs if not r["has"] and r["accessibility"] == "medium"][:1]
    emit({"member": a.member, "has": has, "ladder": rungs, "suggest_next": [r["type"] for r in nxt],
          "rule": "先用便宜、容易拿到的数据；低可及性的检测只在回答一个具体问题时才建议，不为“多知道一点”去测"})


# ---------------------------------------------------------------- imports

def cmd_import_analyst(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    ws = Path(a.workspace).expanduser().resolve()
    twin_p = next((p for p in (ws / "deliver" / "twin.json", ws / "work" / "twin" / "twin.json") if p.exists()), None)
    if not twin_p:
        raise CoachError(f"no twin.json under {ws}/deliver or {ws}/work/twin: finish longevity-analyst workflow 06 first")
    tw = load_json(twin_p)
    _, idx = biovar(library_dir(home, required=False))
    t = tw["snapshot"]["t"][:10]
    origin = f"analyst:{ws.name}:{t}"
    added = {"measurements": 0, "readouts": 0, "proposals": 0, "retests": 0}
    for o in tw.get("observations", []):
        if o.get("provenance_uncertain"):
            continue
        try:
            v = float(str(o["value"]).replace(",", ""))
        except ValueError:
            continue
        if any(x["marker"] == o["marker"] and x["date"] == t and x["value"] == v for x in st["measurements"]):
            continue
        bm = match_bv(idx, o["marker"])
        st["measurements"].append({"id": new_id(st["measurements"], "M"), "marker": o["marker"], "key": bm["key"] if bm else None,
                                   "value": v, "unit": o.get("unit", ""), "date": t,
                                   "source": f"{origin}:{o.get('source_file')}"})
        added["measurements"] += 1
    for r in tw.get("readouts", []) + tw.get("organ_estimates", []):
        if r.get("provenance_uncertain") or any(x.get("ref") == r["id"] and x["t"] == t for x in st["readouts"]):
            continue
        st["readouts"].append({"id": new_id(st["readouts"], "R"), "ref": r["id"], "label": r.get("label_zh"),
                               "value": r.get("value"), "low": r.get("low"), "high": r.get("high"), "unit": r.get("unit", ""),
                               "kind": r.get("kind"), "t": t, "source": origin,
                               "ai_estimate": r.get("kind") == "llm_estimate"})
        added["readouts"] += 1
    for i in tw.get("interventions", []):
        if any(p["origin"] == origin and p["item"] == i["id"] for p in st["proposals"]):
            continue
        st["proposals"].append({"id": new_id(st["proposals"], "P"), "origin": origin, "item": i["id"],
                                "category": i["category"], "action": i["action_zh"], "targets": i.get("targets", []),
                                "executor": i["executor"], "status": "proposed", "t": t})
        added["proposals"] += 1
    for rt in tw.get("retest_plan", []):
        if not rt.get("after_weeks"):
            continue
        due = (to_date(t) + dt.timedelta(weeks=rt["after_weeks"])).isoformat()
        if any(x["origin"] == origin and x["what"] == rt["what"] for x in st["retests"]):
            continue
        st["retests"].append({"id": new_id(st["retests"], "T"), "what": rt["what"], "due": due, "origin": origin,
                              "intervention": rt.get("intervention"), "status": "open"})
        added["retests"] += 1
    kinds = sorted({ANALYST_KINDS[f["kind"]] for f in tw.get("data_files", [])
                    if f.get("kind") in ANALYST_KINDS and not f.get("excluded")})
    files = {"report_md": ws / "deliver" / "report.md", "report_html": ws / "deliver" / "report.html",
             "summary": ws / "work" / "report" / "summary.md", "plan": ws / "work" / "intervene" / "plan.json"}
    visit = {"workspace": str(ws), "t": t, "twin": str(twin_p), "data_types": kinds,
             "identity": (tw.get("identity") or {}).get("answer"),
             **{k: str(p) for k, p in files.items() if p.exists()}}
    st["analyst_visits"] = [v for v in st["analyst_visits"] if v["workspace"] != str(ws)] + [visit]
    journal_add(home, a.member, st, {"kind": "import", "text": f"导入分析师结果 {origin}：{json.dumps(added, ensure_ascii=False)}"})
    save_state(home, a.member, st)
    warn = []
    if visit["identity"] not in ("consistent",):
        warn.append(f"分析师的身份核对结果是 {visit['identity']}：解读前先说明哪些文件不确定属于这个人")
    if tw.get("member", {}).get("id") not in (None, a.member):
        warn.append(f"分析师工作区的会员 id 是 {tw['member']['id']}，教练这边是 {a.member}：确认是同一个人")
    emit({"member": a.member, "visit": visit, "added": added, "warnings": warn,
          "next": "读 summary 和 report_md，按 references/rituals.md 的「解读报告」三层讲；proposals 里 executor=member 的项由用户挑选后再 commit add"})


def _scalars(obj: Any, prefix: str = "", out: Optional[Dict[str, Any]] = None, depth: int = 0) -> Dict[str, Any]:
    out = {} if out is None else out
    if isinstance(obj, dict) and depth < 3:
        for k, v in obj.items():
            _scalars(v, f"{prefix}{k}.", out, depth + 1)
    elif isinstance(obj, (str, int, float, bool)) and len(out) < 40:
        if not isinstance(obj, str) or len(obj) <= 120:
            out[prefix.rstrip(".")] = obj
    return out


def cmd_import_result(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    out_dir = Path(a.out).expanduser().resolve()
    rj = out_dir / "result.json"
    if not rj.exists():
        raise CoachError(f"no result.json in {out_dir}; if the script exited with code 3 read report.md for the reason")
    res = load_json(rj)
    rec = {"skill": a.skill, "t": date_arg(a.date), "out_dir": str(out_dir), "summary": _scalars(res)}
    if (out_dir / "report.md").exists():
        rec["report_md"] = str(out_dir / "report.md")
    st["skill_results"].append(rec)
    journal_add(home, a.member, st, {"kind": "import", "text": f"方法读出 {a.skill}（{out_dir.name}）"})
    save_state(home, a.member, st)
    emit({"member": a.member, "result": rec,
          "next": "读 report_md：用一句话讲最要紧的事，带上不确定性，保留报告的「边界:」原话"})


# ---------------------------------------------------------------- due, brief, sessions, safety, dossier

def due_items(st: Dict[str, Any], jr: List[Dict[str, Any]], horizon: int = 7,
              idx: Optional[Dict[str, Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    t = today()
    cad = st.get("cadence_days") or 7
    items: List[Dict[str, Any]] = []
    for s in st["safety"]:
        if s["status"] == "open":
            items.append({"kind": "safety", "id": s["id"], "what": s["flag"], "action": s["action"], "priority": 0})
    last = st.get("last_session")
    if not last:
        items.append({"kind": "onboarding", "what": "还没有完整的一次对话：走「初见」", "priority": 1})
    else:
        gap = (t - to_date(last["t"])).days
        if gap >= cad:
            items.append({"kind": "checkin", "what": f"距上次对话 {gap} 天（约定节奏 {cad} 天）", "priority": 2,
                          "re_engage": gap >= 2 * cad})
    for c in st["commitments"]:
        if c["status"] != "active":
            continue
        lc = last_check(c) or c["since"]
        gap = (t - to_date(lc)).days
        if gap >= cad:
            items.append({"kind": "commitment", "id": c["id"], "what": f"{c['when']}，{c['action']}",
                          "days_since_check": gap, "priority": 3})
        ad = adherence(c)
        if ad and ad["rate"] is not None and ad["rate"] >= 0.8 and ad["checkins"] >= 3 and (t - to_date(c["since"])).days >= 28:
            items.append({"kind": "graduate", "id": c["id"], "what": "执行率连续四周以上不低于 80%：可以问要不要「毕业」成习惯、减少跟进",
                          "priority": 6})
    for r in st["retests"]:
        if r["status"] == "open" and to_date(r["due"]) <= t + dt.timedelta(days=horizon):
            items.append({"kind": "retest", "id": r["id"], "what": r["what"], "due": r["due"],
                          "overdue": to_date(r["due"]) < t, "priority": 4})
    for e in st["experiments"]:
        if e["status"] != "active":
            continue
        end = to_date(e["start"]) + dt.timedelta(days=e["weeks"] * 7)
        ff = follow_from(e)
        got = len([r for r in series(st, e["marker"], idx or {}) if to_date(r["date"]) >= ff])
        if t >= end:
            items.append({"kind": "experiment_review", "id": e["id"], "what": e["title"], "priority": 3})
        elif t >= ff and got < e["repeats"]:
            items.append({"kind": "experiment_measure", "id": e["id"],
                          "what": f"{e['title']}：复测窗口已开始，{e['marker']} 已测 {got}/{e['repeats']} 次", "priority": 4})
    for p in st["proposals"]:
        if p["status"] == "proposed":
            items.append({"kind": "proposal", "id": p["id"], "what": p["action"], "executor": p["executor"], "priority": 5})
    for j in jr:
        if j.get("kind") == "life_event" and j.get("date"):
            d = (to_date(j["date"]) - t).days
            if -14 <= d <= 30:
                items.append({"kind": "life_event", "id": j["id"], "what": j["text"], "date": j["date"],
                              "when": "upcoming" if d >= 0 else "just_passed", "priority": 2})
    return sorted(items, key=lambda x: x["priority"])


def cmd_due(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    idx = biovar(library_dir(home, required=False))[1]
    emit({"member": a.member, "today": today().isoformat(), "due": due_items(st, journal(home, a.member), a.horizon, idx)})


def cmd_brief(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    jr = journal(home, a.member)
    lib = library_dir(home, required=False)
    due = due_items(st, jr, idx=biovar(lib)[1])
    kinds = {d["kind"] for d in due}
    if "safety" in kinds:
        mode = "safety"
    elif "onboarding" in kinds or not st["goals"]:
        mode = "onboarding"
    elif any(d.get("re_engage") for d in due):
        mode = "re_engage"
    elif kinds & {"checkin", "commitment", "experiment_review", "retest"}:
        mode = "check_in"
    else:
        mode = "open"
    notes = [j for j in jr if j.get("kind") in NOTE_KINDS]
    values = [j for j in notes if j["kind"] == "value"]
    recent = [j for j in notes if j["kind"] != "value"][-10:]
    active_c = []
    for c in st["commitments"]:
        if c["status"] == "active":
            active_c.append({"id": c["id"], "when": c["when"], "action": c["action"], "cadence": c["cadence"],
                             "since": c["since"], "last_check": last_check(c), "adherence_28d": adherence(c)})
    emit({
        "persona": st["persona"],
        "member": {"id": a.member, "name": st["member"].get("name"), "age": member_age(st), "sex": st["member"].get("sex")},
        "mode": mode,
        "today": today().isoformat(),
        "last_session": st.get("last_session"),
        "goals": [g for g in st["goals"] if g["status"] == "active"],
        "values": [{"id": j["id"], "text": j["text"]} for j in values],
        "stages": {k[6:]: v["value"] for k, v in st["facts"].items() if k.startswith("stage.")},
        "facts": {k: v["value"] for k, v in st["facts"].items() if not k.startswith("stage.")},
        "commitments": active_c,
        "experiments": [{k: e[k] for k in ("id", "title", "marker", "start", "weeks", "repeats", "rule")}
                        for e in st["experiments"] if e["status"] == "active"],
        "due": due,
        "wins": wins_since(st, jr, (st.get("last_session") or {}).get("t")),
        "recent_notes": [{"id": j["id"], "kind": j["kind"], "text": j["text"], "date": j.get("date")} for j in recent],
        "data_has": data_has(st),
        "latest_analyst_visit": st["analyst_visits"][-1] if st["analyst_visits"] else None,
        "measurements": len(st["measurements"]), "readouts": len(st["readouts"]),
        "library": str(lib) if lib else None, "analyst": str(analyst_dir(home) or "") or None,
        "open_with": "安全事项优先；否则先用 wins 里一件具体的进步开场，再跟进 due 里最靠前的一件（人生大事 > 承诺/实验 > 复测），不要以“今天想聊什么”开场",
    })


def cmd_session_close(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    st["last_session"] = {"t": today().isoformat(), "summary": a.summary, "next": a.next, "threads": a.thread or []}
    journal_add(home, a.member, st, {"kind": "session", "text": a.summary, "next": a.next, "threads": a.thread or []})
    save_state(home, a.member, st)
    emit({"member": a.member, "last_session": st["last_session"]})


def cmd_safety(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    if a.resolve:
        s = find(st["safety"], a.resolve, "safety flag")
        s.update(status="resolved", resolved=today().isoformat(), resolution=a.note)
        journal_add(home, a.member, st, {"kind": "safety", "text": f"{s['id']} 已处理：{a.note or ''}"})
    else:
        if not a.flag or not a.action:
            raise CoachError("give --flag and --action (what you told the person to do)")
        s = {"id": new_id(st["safety"], "S"), "t": now_iso(), "flag": a.flag, "action": a.action, "status": "open"}
        st["safety"].append(s)
        journal_add(home, a.member, st, {"kind": "safety", "text": f"{s['id']} {a.flag} → {a.action}"})
    save_state(home, a.member, st)
    emit({"member": a.member, "safety": s})


def cmd_dossier(a: argparse.Namespace) -> None:
    home = coach_home(a)
    st = load_state(home, a.member)
    jr = journal(home, a.member)
    p, m = st["persona"], st["member"]
    L = [f"# {p['coach_name']} 记得的关于{m.get('name') or a.member}的一切", "",
         f"这些都只存在这台电脑上（{mdir(home, a.member)}）。任何一条都可以让我删掉。", "", "## 基本信息", ""]
    sex = {"male": "男", "female": "女"}.get(m.get("sex") or "", "未记录")
    L.append(f"- 称呼：{m.get('name') or '未记录'}；年龄：{member_age(st) if member_age(st) is not None else '未记录'}；性别：{sex}")
    if st["facts"]:
        L += ["", "## 你告诉过我的事实", ""]
        L += [f"- {k}：{v['value']}（来源：{v.get('source') or '—'}）" for k, v in st["facts"].items()]
    if st["goals"]:
        L += ["", "## 目标", ""]
        L += [f"- [{g['id']}·{g['status']}] {g['picture']}。为什么：{g['why']}" for g in st["goals"]]
    if st["commitments"]:
        L += ["", "## 约定的小动作", ""]
        for c in st["commitments"]:
            ad = adherence(c)
            L.append(f"- [{c['id']}·{c['status']}] {c['when']}，{c['action']}（{c['cadence']}，自 {c['since']}）"
                     + (f"；最近四周完成 {ad['done']:g}/{ad['expected']:g}" if ad else ""))
    if st["experiments"]:
        L += ["", "## 个人实验", ""]
        L += [f"- [{e['id']}·{e['status']}] {e['title']}：{e['intervention']} → {e['marker']}，{e['weeks']} 周；规则：{e['rule']}"
              + (f"；结果：{e.get('outcome')}" if e.get("outcome") else "") for e in st["experiments"]]
    if st["measurements"]:
        L += ["", "## 测量", ""]
        L += [f"- [{x['id']}] {x['date']} {x['marker']} {x['value']:g} {x['unit']}（{x['source']}）"
              for x in sorted(st["measurements"], key=lambda x: (x["marker"], x["date"]))]
    if st["readouts"]:
        L += ["", "## 分析读出", ""]
        L += [f"- [{r['id']}] {r['t']} {r['label']}：{r['value']} {r.get('unit') or ''}" + ("（AI 估计，不是测量）" if r.get("ai_estimate") else "")
              for r in st["readouts"]]
    notes = [j for j in jr if j.get("kind") in NOTE_KINDS]
    if notes:
        L += ["", "## 我记下的你的故事和偏好", ""]
        L += [f"- [{j['id']}·{j['kind']}] {j['text']}" + (f"（{j['date']}）" if j.get("date") else "") for j in notes]
    sessions = [j for j in jr if j.get("kind") == "session"]
    if sessions:
        L += ["", "## 每次对话的小结", ""]
        L += [f"- {j['t'][:10]}：{j['text']}" + (f" → 下次：{j['next']}" if j.get("next") else "") for j in sessions]
    text = "\n".join(L) + "\n"
    path = mdir(home, a.member) / "dossier.md"
    path.write_text(text, encoding="utf-8")
    emit({"member": a.member, "path": str(path), "chars": len(text)})


# ---------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    P = argparse.ArgumentParser(prog="coach.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    P.add_argument("--home", help="coach home (default: $LONGEVITY_COACH_HOME or ~/.longevity-coach)")
    sub = P.add_subparsers(dest="cmd", required=True)

    def add(name: str, fn: Any, help_: str, member: bool = True, parent: Any = None) -> argparse.ArgumentParser:
        sp = (parent or sub).add_parser(name, help=help_)
        if member:
            sp.add_argument("member")
        sp.set_defaults(fn=fn)
        return sp

    s = add("setup", cmd_setup, "find or set the longevity-skills library and the longevity-analyst skill", member=False)
    s.add_argument("--library")
    s.add_argument("--analyst")
    add("members", cmd_members, "list members", member=False)

    s = add("init", cmd_init, "create a member")
    s.add_argument("--name", required=True, help="how the person wants to be called")
    s.add_argument("--age", type=int)
    s.add_argument("--birth-date")
    s.add_argument("--sex")
    s.add_argument("--coach-name", default="Pi")
    s.add_argument("--tone", default="upbeat", help="upbeat | gentle | direct | clinical")
    s.add_argument("--address", default="你", choices=["你", "您"])
    s.add_argument("--cadence-days", type=int, default=7)

    s = add("profile", cmd_profile, "change name, age, sex or check-in cadence")
    s.add_argument("--name")
    s.add_argument("--age", type=int)
    s.add_argument("--birth-date")
    s.add_argument("--sex")
    s.add_argument("--cadence-days", type=int)
    s.add_argument("--source", required=True, help="the person's own words")

    s = add("persona", cmd_persona, "rename the coach or change its tone")
    s.add_argument("--coach-name")
    s.add_argument("--tone")
    s.add_argument("--address", choices=["你", "您"])

    s = add("fact", cmd_fact, "record structured facts: smoker=no stage.exercise=contemplation data_has=wearable")
    s.add_argument("pairs", nargs="+")
    s.add_argument("--source", required=True, help="quote of what the person said, or the document")

    s = add("remember", cmd_remember, "remember a story, preference, barrier, win, concern, life event or value")
    s.add_argument("--kind", required=True, choices=NOTE_KINDS)
    s.add_argument("--text", required=True)
    s.add_argument("--source")
    s.add_argument("--date", help="date of a life event (YYYY-MM-DD)")
    s.add_argument("--tags")

    s = add("forget", cmd_forget, "delete a note, measurement, goal, readout or fact; or everything")
    s.add_argument("--id")
    s.add_argument("--fact")
    s.add_argument("--everything", action="store_true")
    s.add_argument("--confirm")

    g = sub.add_parser("goal", help="goals anchored in what the person wants to be able to do").add_subparsers(dest="sub", required=True)
    s = add("add", cmd_goal_add, "add a goal", parent=g)
    s.add_argument("--picture", required=True, help="the concrete picture, e.g. 75 岁还能背着孙女爬黄山")
    s.add_argument("--why", required=True)
    s.add_argument("--area", choices=AREAS)
    s.add_argument("--source")
    s = add("set", cmd_goal_set, "change a goal's status", parent=g)
    s.add_argument("id")
    s.add_argument("--status", required=True, choices=["active", "achieved", "paused", "dropped"])
    s.add_argument("--note")

    c = sub.add_parser("commit", help="small commitments and check-ins").add_subparsers(dest="sub", required=True)
    s = add("add", cmd_commit_add, "add a commitment", parent=c)
    s.add_argument("--area", required=True, choices=AREAS)
    s.add_argument("--action", required=True)
    s.add_argument("--when", required=True, help="implementation intention: 当…时 / 在…之后")
    s.add_argument("--cadence", required=True, help="daily | weekdays | weekly | Nx/week")
    s.add_argument("--confidence", type=int, choices=range(0, 11), metavar="0-10")
    s.add_argument("--goal")
    s.add_argument("--from-proposal")
    s.add_argument("--start")
    s = add("check", cmd_commit_check, "log a check-in", parent=c)
    s.add_argument("id")
    s.add_argument("--done", choices=["yes", "partial", "no"])
    s.add_argument("--times", type=float)
    s.add_argument("--period", type=int)
    s.add_argument("--date")
    s.add_argument("--note")
    s = add("set", cmd_commit_set, "change, pause, drop or graduate a commitment", parent=c)
    s.add_argument("id")
    s.add_argument("--status", choices=["active", "paused", "dropped", "graduated"])
    s.add_argument("--action")
    s.add_argument("--when")
    s.add_argument("--cadence")
    s.add_argument("--confidence", type=int, choices=range(0, 11), metavar="0-10")
    s.add_argument("--note")

    pr = sub.add_parser("proposal", help="analyst plan items imported into the coach record").add_subparsers(dest="sub", required=True)
    s = add("set", cmd_proposal_set, "mark a proposal adopted, declined, taken to a professional or done", parent=pr)
    s.add_argument("id")
    s.add_argument("--status", required=True, choices=PROPOSAL_STATUS)
    s.add_argument("--note")

    rt = sub.add_parser("retest", help="planned retests").add_subparsers(dest="sub", required=True)
    s = add("add", cmd_retest_add, "plan a retest", parent=rt)
    s.add_argument("--what", required=True)
    s.add_argument("--due", required=True)
    s.add_argument("--experiment")
    s = add("set", cmd_retest_set, "close, drop or reschedule a retest", parent=rt)
    s.add_argument("id")
    s.add_argument("--status", required=True, choices=["open", "done", "dropped"])
    s.add_argument("--due")
    s.add_argument("--note")

    m = sub.add_parser("measure", help="measurements the person gave or a document showed").add_subparsers(dest="sub", required=True)
    s = add("add", cmd_measure_add, "record one measurement", parent=m)
    s.add_argument("--marker", required=True)
    s.add_argument("--value", required=True)
    s.add_argument("--unit", required=True)
    s.add_argument("--date")
    s.add_argument("--source", required=True, help="where the number came from")
    s.add_argument("--context")
    s = add("list", cmd_measure_list, "list measurements", parent=m)
    s.add_argument("--marker")

    s = add("compare", cmd_compare, "is a change real? judge against within-person biological variation")
    s.add_argument("--marker", required=True)
    s.add_argument("--k", type=int, default=1, help="values averaged on each side")
    s.add_argument("--before", help="split date: baseline before, current on or after")

    e = sub.add_parser("experiment", help="N-of-1 experiments").add_subparsers(dest="sub", required=True)
    s = add("design", cmd_exp_design, "expected trial effect vs this person's noise band", parent=e, member=False)
    s.add_argument("--member")
    s.add_argument("--intervention")
    s.add_argument("--marker")
    s.add_argument("--repeats", type=int, default=1, help="separate-day measurements on each side")
    s.add_argument("--baseline", type=float)
    s.add_argument("--unit")
    s.add_argument("--per-units", type=float, help="planned amount for per-unit effects, e.g. kg lost")
    s = add("start", cmd_exp_start, "pre-register an experiment", parent=e)
    s.add_argument("--title", required=True)
    s.add_argument("--intervention", required=True)
    s.add_argument("--marker", required=True)
    s.add_argument("--weeks", type=int, required=True)
    s.add_argument("--repeats", type=int, default=1)
    s.add_argument("--rule", required=True, help="decision rule written before the data: what result means keep or drop")
    s.add_argument("--commitment")
    s.add_argument("--start")
    s.add_argument("--per-units", type=float)
    s = add("review", cmd_exp_review, "judge an experiment", parent=e)
    s.add_argument("id")
    s.add_argument("--follow-from")
    s = add("close", cmd_exp_close, "close an experiment", parent=e)
    s.add_argument("id")
    s.add_argument("--outcome", required=True, choices=["keep", "drop", "inconclusive", "extend"])
    s.add_argument("--note")

    s = add("route", cmd_route, "match a question to intents and skills in longevity-skills", member=False)
    s.add_argument("question")
    s.add_argument("--member")
    s = add("prepare", cmd_prepare, "write a skill's input CSV from recorded measurements and print the command")
    s.add_argument("--skill", required=True)
    add("ladder", cmd_ladder, "what data the person has and the cheapest next step")

    s = add("import-analyst", cmd_import_analyst, "pull a longevity-analyst workspace into the coach record")
    s.add_argument("workspace")
    s = add("import-result", cmd_import_result, "pull a method's out/result.json into the coach record")
    s.add_argument("--skill", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--date")

    s = add("due", cmd_due, "what to follow up")
    s.add_argument("--horizon", type=int, default=7)
    add("brief", cmd_brief, "session-start briefing: run before every conversation")
    s = add("session-close", cmd_session_close, "close a session")
    s.add_argument("--summary", required=True)
    s.add_argument("--next", required=True, help="the one thing until next time")
    s.add_argument("--thread", action="append", help="an open thread to pick up later (repeatable)")
    s = add("safety", cmd_safety, "record a red flag and what the person was told, or resolve one")
    s.add_argument("--flag")
    s.add_argument("--action")
    s.add_argument("--resolve")
    s.add_argument("--note")
    add("dossier", cmd_dossier, "write everything the coach remembers to dossier.md")
    return P


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.fn(args)
    except CoachError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return e.code
    return 0


if __name__ == "__main__":
    sys.exit(main())
