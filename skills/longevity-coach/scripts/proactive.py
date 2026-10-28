#!/usr/bin/env python3
"""Proactive care: when should Pi reach out, what may the message say, and what did the member do with it.

  proactive.py scan --member <档案.md> | --state <state.json> [--export <la-export.json>] [--now <ISO>] [--opening] [--write]
  proactive.py lint --message <message.json> --event <event.json>
  proactive.py ack  --member <档案.md> | --state <state.json> --action <action.json> [--now <ISO>] [--write]

Pure and deterministic: the same state, export and time give the same output. The host-neutral state
(`pi-state/1`) and the exact algorithm are in references/proactive.md; tests/fixtures/proactive_cases.json
holds the shared cases a second implementation (the LongPi website) must pass.
Standalone keeps proactive history in a sidecar next to the member file: <称呼>.proactive.json.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

SKILL = Path(__file__).resolve().parents[1]
RULES = json.loads((SKILL / "data" / "proactive_rules.json").read_text(encoding="utf-8"))
POLICY = json.loads((SKILL / "data" / "proactive_policy.json").read_text(encoding="utf-8"))
TRIGGERS = {t["id"]: t for t in RULES["triggers"]}
ORDER = {t["id"]: i for i, t in enumerate(RULES["triggers"])}
CATEGORIES = POLICY["categories"]
ACTION_TYPES = ["checkin", "snooze", "dismiss", "mute_trigger", "open_chat", "open_card", "schedule_retest",
                "start_experiment_phase", "prepare_doctor_brief", "call_emergency", "answer", "read"]
QUESTIONS = json.loads((SKILL / "data" / "questions.json").read_text(encoding="utf-8"))
QBANK = {q["id"]: q for q in QUESTIONS["questions"]}
QORDER = {q["id"]: i for i, q in enumerate(QUESTIONS["questions"])}
QPURPOSE = {p: i for i, p in enumerate(QUESTIONS["purposes"])}
QPOL = POLICY["questions"]
MILESTONES = TRIGGERS["milestone"]["when"]["cumulative_reaches"]
REASON_ZH = {"intervention": "确认你做的改变有没有真的起作用", "genetic": "看看基因提示的这一项有没有表现出来",
             "guideline": "按指南的时间把这一项再看一看"}
DIRECTION_ZH = {"increase": "上升", "decrease": "下降", "rising": "上升", "falling": "下降"}
KIND_ZH = {"labs": "化验结果", "wearable": "手环数据", "analysis": "分析结果"}
LIVE = ("scheduled", "sent", "read", "acted")


# ---------- time ----------

def tzinfo(name: Optional[str]):
    name = name or "Asia/Shanghai"
    m = re.fullmatch(r"([+-])(\d{2}):(\d{2})", name)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        return timezone(sign * timedelta(hours=int(m.group(2)), minutes=int(m.group(3))))
    return ZoneInfo(name)


def parse_time(value: Any, tz) -> Optional[datetime]:
    """ISO datetime with offset, or a bare date (= local midnight)."""
    if not value:
        return None
    s = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return datetime.combine(date.fromisoformat(s), time(0), tz)
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=tz)


def iso(dt: datetime, tz) -> str:
    return dt.astimezone(tz).isoformat(timespec="seconds")


def local_date(dt: datetime, tz) -> date:
    return dt.astimezone(tz).date()


def hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def quiet_end(now: datetime, tz, quiet: Dict[str, str]) -> Optional[datetime]:
    """If `now` is inside quiet hours, the local time they end; else None. Windows may cross midnight."""
    start, end = hhmm(quiet["start"]), hhmm(quiet["end"])
    loc = now.astimezone(tz)
    t = loc.time().replace(tzinfo=None)
    if start == end:
        return None
    if start > end:  # e.g. 22:00-08:00
        if t >= start:
            return datetime.combine(loc.date() + timedelta(days=1), end, tz)
        if t < end:
            return datetime.combine(loc.date(), end, tz)
        return None
    if start <= t < end:
        return datetime.combine(loc.date(), end, tz)
    return None


def short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]


# ---------- evaluation ----------

def make_event(state: dict, trig: str, subject: dict, payload: dict, dedup: str, at: datetime, tz,
               refs: Optional[list] = None) -> dict:
    cat = TRIGGERS[trig]["category"]
    return {"schema": "pi-event/1", "id": f"E-{local_date(at, tz):%Y%m%d}-{short_hash(dedup)}",
            "member": state.get("member", ""), "trigger": trig, "category": cat,
            "priority": CATEGORIES[cat]["priority"], "occurred_at": iso(at, tz), "subject": subject,
            "payload": payload, "refs": refs or [], "dedup_key": dedup}


def subject_key(event: dict) -> str:
    return event["trigger"] + ":" + ",".join(f"{k}={event['subject'][k]}" for k in sorted(event["subject"]))


def pct(x: float) -> int:
    return int(round(x * 100))


def num(x: Any) -> Any:
    return int(x) if isinstance(x, float) and x.is_integer() else x


def days_between(a: date, b: date) -> int:
    return (b - a).days


def evaluate(state: dict, export: dict, now: datetime, tz) -> List[dict]:
    """Every trigger condition that holds at `now`, as pi-event/1 (before dedup and policy)."""
    out: List[dict] = []
    today = local_date(now, tz)
    commitments = [c for c in (state.get("commitments") or []) if c.get("status", "active") == "active"]
    last_seen = parse_time(state.get("last_interaction_at"), tz)
    preds = {p.get("id"): p for p in export.get("predictions") or []}

    # critical_value
    recent = timedelta(hours=POLICY["critical_recent_hours"])
    for m in state.get("measurements") or []:
        at = parse_time(m.get("at"), tz)
        if at is None or at > now:
            continue
        date_only = re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(m.get("at")))
        if (date_only and days_between(at.date(), today) > 1) or (not date_only and now - at > recent):
            continue
        vals, unit = m.get("values") or {}, (m.get("unit") or "").replace(" ", "")
        for rule in RULES["critical_rules"]:
            if m.get("kind") != rule["kind"]:
                continue
            hit = [c for c in rule["any"] if c["field"] in vals and c["unit"].lower() == unit.lower()
                   and (vals[c["field"]] > c["value"] if c["op"] == ">" else vals[c["field"]] < c["value"])]
            if not hit:
                continue
            if rule["kind"] == "blood_pressure":
                value_text = f"{num(vals.get('sbp'))}/{num(vals.get('dbp'))} {m.get('unit')}"
            else:
                value_text = f"{num(vals[hit[0]['field']])} {m.get('unit')}"
            payload = {"rule": rule["id"], "kind": rule["kind"], "kind_zh": rule["kind_zh"], "values": vals,
                       "unit": m.get("unit"), "value_text": value_text, "source_short_zh": rule["source_short_zh"],
                       "measurement": m.get("id")}
            out.append(make_event(state, "critical_value", {"measurement": m.get("id"), "rule": rule["id"]}, payload,
                                  f"critical_value:{m.get('id')}:{rule['id']}", at, tz,
                                  [{"type": "rule", "id": rule["id"]}, {"type": "measurement", "id": m.get("id")}]))

    # concordance_transition
    for c in export.get("concordance") or []:
        tr = c.get("transition") or {}
        if [tr.get("from"), tr.get("to")] != TRIGGERS["concordance_transition"]["when"]["transition"]:
            continue
        when = tr.get("observed_at") or export.get("generated_at")
        label = (c.get("label") or {}).get("label_zh") or "测量"
        payload = {"analyte": c.get("analyte"), "marker": c.get("marker_zh") or c.get("analyte"), "from": tr["from"],
                   "to": tr["to"], "observed_at": when, "label_zh": label}
        out.append(make_event(state, "concordance_transition", {"analyte": c.get("analyte")}, payload,
                              f"concordance_transition:{c.get('analyte')}:{when}", now, tz,
                              [{"type": "concordance", "id": c.get("analyte")}]))

    # diagnosis_hit
    for d in export.get("diagnoses") or []:
        if d.get("hit") is False:
            continue
        rule = d.get("rule") or d.get("id")
        label = d.get("label") or {}
        payload = {"diagnosis": d.get("id"), "rule": rule, "conclusion_zh": d.get("conclusion_zh", ""),
                   "source_zh": d.get("source_zh", ""), "label_zh": label.get("label_zh", ""),
                   "basis_kind": label.get("basis_kind")}
        out.append(make_event(state, "diagnosis_hit", {"rule": rule}, payload, f"diagnosis_hit:{rule}", now, tz,
                              [{"type": "diagnosis", "id": d.get("id")}]))

    # medication_gene_conflict
    in_use = {str(x.get("name", "")).casefold(): x for x in state.get("medications_in_use") or []}
    for med in export.get("medications") or []:
        drug = str(med.get("drug", ""))
        label = med.get("label") or {}
        is_cpic = med.get("source_type") == "cpic" or label.get("basis_kind") == "cpic"
        if not is_cpic or med.get("routine", True) or drug.casefold() not in in_use:
            continue
        payload = {"drug": drug, "drug_zh": med.get("drug_zh") or drug, "medication": med.get("id"),
                   "label_zh": label.get("label_zh") or "CPIC"}
        out.append(make_event(state, "medication_gene_conflict", {"drug": drug.casefold()}, payload,
                              f"medication_gene_conflict:{drug.casefold()}", now, tz,
                              [{"type": "medication", "id": med.get("id")}]))

    # retest_due
    scheduled = set(state.get("retests_scheduled") or [])
    pre, _ = TRIGGERS["retest_due"]["when"]["retest_due_in_days"]
    window = TRIGGERS["retest_due"]["when"]["due_window_days"]
    trending = {t.get("marker"): DIRECTION_ZH[t["trend"]["verdict"].split("_")[0]] for t in export.get("trends") or []
                if (t.get("trend") or {}).get("verdict") in ("rising_beyond_noise", "falling_beyond_noise")}
    for r in export.get("retests") or []:
        rid = r.get("id") or r.get("marker")
        due = parse_time(r.get("due_at"), tz)
        if due is None or rid in scheduled:
            continue
        left = days_between(today, local_date(due, tz))
        if 0 < left <= pre:
            phase = "pre"
        elif -window < left <= 0:
            phase = "due"
        else:
            continue
        reason = f"确认之前看到的缓慢{trending[r.get('marker')]}是不是真的" if r.get("marker") in trending else \
            REASON_ZH.get(r.get("reason"), "把这一项再看一看")
        payload = {"retest": rid, "marker": r.get("marker"), "due_at": r.get("due_at"), "days_left": left,
                   "reason": r.get("reason"), "reason_zh": reason, "phase_pre": phase == "pre", "phase": phase}
        out.append(make_event(state, "retest_due", {"retest": rid}, payload, f"retest_due:{rid}:{r.get('due_at')}:{phase}",
                              now, tz, [{"type": "retest", "id": rid}]))

    # new_data_ready
    batches = list(state.get("data_batches") or [])
    if export.get("generated_at"):
        batches.append({"id": f"export:{export['generated_at']}", "arrived_at": export["generated_at"], "kind": "analysis"})
    for b in batches:
        at = parse_time(b.get("arrived_at"), tz)
        if at is None or at > now:
            continue
        payload = {"batch": b.get("id"), "kind": b.get("kind"), "kind_zh": b.get("kind_zh") or KIND_ZH.get(b.get("kind"), "数据")}
        out.append(make_event(state, "new_data_ready", {"batch": b.get("id")}, payload, f"new_data_ready:{b.get('id')}",
                              now, tz))

    # change_beyond_noise / trend_beyond_noise
    targets = {t.get("marker"): t for t in state.get("plan_targets") or []}
    for it in (export.get("plan") or {}).get("items") or []:
        for mk in it.get("targets") or []:
            targets.setdefault(mk, {"marker": mk, "plan_item": it.get("id")})
    for t in export.get("trends") or []:
        mk = t.get("marker")
        pairs = t.get("pairs") or []
        last = pairs[-1] if pairs else None
        if mk in targets and last and last.get("verdict") in ("increase_beyond_noise", "decrease_beyond_noise"):
            direction = last["verdict"].split("_")[0]
            want = targets[mk].get("desired")
            payload = {"marker": mk, "change_pct": last.get("change_pct"), "change_pct_abs": num(abs(last.get("change_pct", 0))),
                       "band_pct": last.get("band_pct"), "verdict": last["verdict"], "direction": direction,
                       "direction_zh": DIRECTION_ZH[direction], "favorable": bool(want) and want == direction,
                       "plan_item": targets[mk].get("plan_item"), "from": last.get("from"), "to": last.get("to"),
                       "concurrent_exposures": t.get("concurrent_exposures") or []}
            out.append(make_event(state, "change_beyond_noise", {"marker": mk}, payload,
                                  f"change_beyond_noise:{mk}:{last.get('from')}:{last.get('to')}", now, tz,
                                  [{"type": "series", "id": mk}]))
        tr = t.get("trend") or {}
        if tr.get("verdict") in ("rising_beyond_noise", "falling_beyond_noise"):
            points = t.get("points") or []
            latest = t.get("observed_at") or (points[-1].get("t") if points else "")
            direction = tr["verdict"].split("_")[0]
            payload = {"marker": mk, "verdict": tr["verdict"], "direction_zh": DIRECTION_ZH[direction],
                       "annual_change_pct": tr.get("annual_change_pct"), "n": tr.get("n"), "observed_at": latest}
            out.append(make_event(state, "trend_beyond_noise", {"marker": mk}, payload,
                                  f"trend_beyond_noise:{mk}:{latest}", now, tz, [{"type": "series", "id": mk}]))

    # prediction_ready
    for p in export.get("predictions") or []:
        label = p.get("label") or {}
        version = label.get("generated_at") or json.dumps(p.get("p_detect_favorable"))
        payload = {"prediction": p.get("id"), "plan_item": p.get("plan_item"), "intervention_zh": p.get("intervention_zh"),
                   "marker": p.get("marker"), "label_zh": label.get("label_zh", ""), "basis_kind": label.get("basis_kind")}
        pdf = p.get("p_detect_favorable")
        if isinstance(pdf, list):
            payload.update(p_low_pct=pct(pdf[0]), p_high_pct=pct(pdf[1]), p_detect_favorable=pdf)
        elif pdf is not None:
            payload.update(p_pct=pct(pdf), p_detect_favorable=pdf)
        else:
            continue
        out.append(make_event(state, "prediction_ready", {"prediction": p.get("id")}, payload,
                              f"prediction_ready:{p.get('id')}:{version}", now, tz, [{"type": "prediction", "id": p.get("id")}]))

    # wearable_shift
    w = TRIGGERS["wearable_shift"]["when"]
    for metric, d in sorted((state.get("wearable") or {}).items()):
        days = sorted(d.get("days") or [], key=lambda x: x["date"])
        days = [x for x in days if days_between(date.fromisoformat(x["date"]), today) < w["window_days"]
                and date.fromisoformat(x["date"]) <= today]
        if len(days) < w["window_days"] or not d.get("baseline") or d.get("band_pct") is None:
            continue
        lo, hi = d["baseline"] * (1 - d["band_pct"] / 100), d["baseline"] * (1 + d["band_pct"] / 100)
        mean = sum(x["value"] for x in days) / len(days)
        side = 1 if mean > hi else -1 if mean < lo else 0
        run = 0
        for x in reversed(days):
            if (side == 1 and x["value"] > hi) or (side == -1 and x["value"] < lo):
                run += 1
            else:
                break
        if side and run >= w["min_days_outside"]:
            payload = {"metric": d.get("metric_zh") or metric, "window_days": w["window_days"], "days_outside": run,
                       "mean": round(mean, 2), "baseline": d["baseline"], "band_pct": d["band_pct"],
                       "direction": "increase" if side > 0 else "decrease"}
            out.append(make_event(state, "wearable_shift", {"metric": metric}, payload,
                                  f"wearable_shift:{metric}:{days[-1]['date']}", now, tz))

    # experiment_checkpoint
    for x in state.get("experiments") or []:
        start = parse_time(x.get("started_at"), tz)
        if start is None or x.get("status") in ("done", "stopped"):
            continue
        base = {"experiment": x.get("id"), "plan_item": x.get("plan_item"), "intervention_zh": x.get("intervention_zh"),
                "marker": x.get("marker"), "repeats_needed": x.get("repeats_needed")}
        if not x.get("post_started_at"):
            weeks = days_between(local_date(start, tz), today) // 7
            if weeks < (x.get("min_weeks") or 0):
                continue
            payload = dict(base, phase="post_start", weeks_done=weeks, prediction_ref=x.get("prediction_ref"))
            p = preds.get(x.get("prediction_ref"))
            refs = []
            if p and isinstance(p.get("p_detect_favorable"), (int, float)):
                payload.update(p_pct=pct(p["p_detect_favorable"]), p_detect_favorable=p["p_detect_favorable"],
                               label_zh=(p.get("label") or {}).get("label_zh", ""))
                refs = [{"type": "prediction", "id": p.get("id")}]
            out.append(make_event(state, "experiment_checkpoint", {"experiment": x.get("id")}, payload,
                                  f"experiment_checkpoint:{x.get('id')}:post_start", now, tz, refs))
        elif (x.get("post_done") or 0) >= (x.get("repeats_needed") or 10 ** 9):
            payload = dict(base, phase="results", phase_results=True, post_done=x.get("post_done"))
            out.append(make_event(state, "experiment_checkpoint", {"experiment": x.get("id")}, payload,
                                  f"experiment_checkpoint:{x.get('id')}:results", now, tz))

    # return_welcome / checkin_gap / commitment_review
    total = sum(int(c.get("cumulative") or 0) for c in state.get("commitments") or [])
    if last_seen is not None:
        idle = days_between(local_date(last_seen, tz), today)
        seen_day = local_date(last_seen, tz).isoformat()
        if idle >= TRIGGERS["return_welcome"]["when"]["days_since_interaction"]:
            out.append(make_event(state, "return_welcome", {"member": state.get("member", "")},
                                  {"days_since_interaction": idle, "total_cumulative": total},
                                  f"return_welcome:{seen_day}", now, tz))
        cadence = state.get("chat_cadence_days")
        if cadence and commitments and idle >= cadence:
            c = commitments[0]
            out.append(make_event(state, "commitment_review", {"member": state.get("member", "")},
                                  {"days_since_interaction": idle, "cadence_days": cadence, "commitment": c.get("id"),
                                   "commitment_zh": c.get("label_zh"), "cumulative": int(c.get("cumulative") or 0)},
                                  f"commitment_review:{seen_day}", now, tz))
    gap = TRIGGERS["checkin_gap"]["when"]["days_without_checkin"]
    for c in commitments:
        last = parse_time(c.get("last_checkin_at") or c.get("started_at"), tz)
        if last is None:
            continue
        idle = days_between(local_date(last, tz), today)
        if idle >= gap:
            out.append(make_event(state, "checkin_gap", {"commitment": c.get("id")},
                                  {"commitment": c.get("id"), "commitment_zh": c.get("label_zh"), "days_without_checkin": idle,
                                   "plan_item": c.get("plan_item")},
                                  f"checkin_gap:{c.get('id')}:{local_date(last, tz).isoformat()}", now, tz))

    # milestone
    for c in state.get("commitments") or []:
        n = int(c.get("cumulative") or 0)
        reached = [m for m in MILESTONES if m <= n]
        if not reached or n - reached[-1] > TRIGGERS["milestone"]["when"]["recent_within"]:
            continue  # celebrate a milestone only while it is fresh
        payload = {"commitment": c.get("id"), "commitment_zh": c.get("label_zh"), "n": reached[-1], "cumulative": n,
                   "plan_item": c.get("plan_item")}
        if state.get("picture_zh"):
            payload["picture_zh"] = state["picture_zh"]
        out.append(make_event(state, "milestone", {"commitment": c.get("id")}, payload,
                              f"milestone:{c.get('id')}:{reached[-1]}", now, tz))

    # life_event_followup
    lo, hi = TRIGGERS["life_event_followup"]["when"]["days_after_event"]
    for ev in state.get("life_events") or []:
        when = parse_time(ev.get("date"), tz)
        if when is None:
            continue
        after = days_between(local_date(when, tz), today)
        if lo <= after <= hi:
            eid = ev.get("id") or f"{ev.get('date')}:{short_hash(ev.get('label_zh', ''))}"
            out.append(make_event(state, "life_event_followup", {"life_event": eid},
                                  {"life_event": eid, "event_zh": ev.get("label_zh"), "date": ev.get("date")},
                                  f"life_event_followup:{eid}", now, tz))

    # question_due: at most one, the most useful question that is due
    q = next_question(state, now, tz)
    if q:
        qid, payload = q
        out.append(make_event(state, "question_due", {"question": qid}, payload,
                              f"question_due:{qid}:{today.isoformat()}", now, tz))
    return out


# ---------- questions ----------

def get_path(obj: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(part)
    return obj


def set_path(obj: dict, path: str, value: Any) -> None:
    *head, last = path.split(".")
    for part in head:
        obj = obj.setdefault(part, {})
    obj[last] = value


def active_experiment(state: dict, xid: Optional[str] = None) -> Optional[dict]:
    """The experiment whose post-test is running (or the named one)."""
    for x in state.get("experiments") or []:
        if xid and x.get("id") == xid:
            return x
        if not xid and x.get("post_started_at") and int(x.get("post_done") or 0) < int(x.get("repeats_needed") or 0):
            return x
    return None


def question_fired(state: dict, qid: str) -> List[dict]:
    return [f for f in (state.get("history") or {}).get("fired", [])
            if f.get("trigger") == "question_due" and ((f.get("event") or {}).get("subject") or {}).get("question") == qid]


def question_log(state: dict, qid: str, tz) -> Tuple[List[datetime], List[dict]]:
    """When the member actually saw the question (a sent message, or the agenda shown at an opening) and the answers,
    oldest first. A question that only waited unseen in the agenda was not asked."""
    hist = state.get("history") or {}
    asks = sorted(parse_time(f["at"], tz) for f in question_fired(state, qid) if f.get("via") == "message" or f.get("seen_at"))
    answers = sorted((a for a in hist.get("answers", []) if a.get("question") == qid), key=lambda a: parse_time(a["at"], tz))
    return asks, answers


def question_retired(unanswered_days: List[date], today: date) -> bool:
    """Seen retire_after_ignored times on earlier days without an answer."""
    return len([d for d in unanswered_days if d < today]) >= QPOL["retire_after_ignored"]


def question_still_open(state: dict, fired: dict, tz, today: date) -> bool:
    """A fired question stays on the agenda only if it is the latest ask of that question, unanswered and not retired."""
    qid = ((fired.get("event") or {}).get("subject") or {}).get("question")
    if qid not in QBANK:
        return False
    at = parse_time(fired["at"], tz)
    if any(parse_time(f["at"], tz) > at for f in question_fired(state, qid)):
        return False
    asks, answers = question_log(state, qid, tz)
    if answers and parse_time(answers[-1]["at"], tz) >= at:
        return False
    last_answer = local_date(parse_time(answers[-1]["at"], tz), tz) if answers else None
    return not question_retired([local_date(a, tz) for a in asks if last_answer is None or local_date(a, tz) > last_answer], today)


def same_streak(answers: List[dict]) -> int:
    n = 0
    for a in reversed(answers):
        if a["answer"] != answers[-1]["answer"]:
            break
        n += 1
    return n


def question_interval(q: dict, answers: List[dict]) -> int:
    """Days to wait after the last answer: the base interval, doubled for each repeat of the same answer."""
    base = q.get("interval_days") or 0
    if not answers or not q.get("backoff", True):
        return base
    return min(QPOL["max_interval_days"], base * QPOL["backoff_factor"] ** (same_streak(answers) - 1))


def question_payload(state: dict, q: dict, host: str, now: datetime, tz) -> Optional[dict]:
    """The payload if the question applies to this member now, else None. Never asks what the state already knows."""
    if host not in q["hosts"]:
        return None
    if q.get("known_if") and get_path(state, q["known_if"]) not in (None, "", []):
        return None
    req = q.get("requires") or {}
    payload: Dict[str, Any] = {"question": q["id"], "purpose": q["purpose"]}
    if req.get("experiment_post_active"):
        x = active_experiment(state)
        if x is None:
            return None
        payload.update(experiment=x.get("id"), marker=x.get("marker"), intervention_zh=x.get("intervention_zh"),
                       post_done=int(x.get("post_done") or 0), repeats_needed=int(x.get("repeats_needed") or 0))
    if "no_measurement" in req:
        r = req["no_measurement"]
        cutoff = now - timedelta(days=r["within_days"])
        if any(m.get("kind") == r["kind"] and (parse_time(m.get("at"), tz) or cutoff) > cutoff
               for m in state.get("measurements") or []):
            return None
    if "no_wearable" in req and (state.get("wearable") or {}).get(req["no_wearable"]):
        return None
    if any(get_path(state, k) != v for k, v in (req.get("state_equals") or {}).items()):
        return None
    return payload


def next_question(state: dict, now: datetime, tz) -> Optional[Tuple[str, dict]]:
    """The one question to ask now, or None. Order: purpose, weight (state.gaps may override), asked longest ago, file order."""
    host = state.get("host", "standalone")
    today = local_date(now, tz)
    gaps = state.get("gaps") or {}
    due = []
    for q in QUESTIONS["questions"]:
        payload = question_payload(state, q, host, now, tz)
        if payload is None:
            continue
        asks, answers = question_log(state, q["id"], tz)
        last_answer = local_date(parse_time(answers[-1]["at"], tz), tz) if answers else None
        if answers and not q.get("recurring"):
            continue
        unanswered = [local_date(a, tz) for a in asks if last_answer is None or local_date(a, tz) > last_answer]
        if question_retired(unanswered, today):
            continue
        if unanswered:
            wait = min(q.get("interval_days") or QPOL["unanswered_retry_days"], QPOL["unanswered_retry_days"])
            if days_between(unanswered[-1], today) < wait:
                continue
        elif answers and days_between(last_answer, today) < question_interval(q, answers):
            continue
        if q.get("same_as_last") and answers:
            payload["last_answer"] = answers[-1]["answer"]
        weight = (gaps.get(q["id"]) or {}).get("weight", q.get("weight", 0))
        last_ask = local_date(asks[-1], tz) if asks else date.min
        due.append(((QPURPOSE[q["purpose"]], -weight, last_ask, QORDER[q["id"]]), q["id"], payload))
    if not due:
        return None
    _, qid, payload = min(due)
    return qid, payload


def answer_feedback(state: dict, q: dict, ans: dict, before: List[dict], after: List[dict], xid: Optional[str]) -> str:
    """What the member sees right after answering. Numbers come only from the state."""
    spec = q["feedback"].get(ans["id"], q["feedback"].get("*", "记上了。"))
    if spec == "experiment_progress":
        x = active_experiment(state, xid) or {}
        k, n = int(x.get("post_done") or 0), int(x.get("repeats_needed") or 0)
        if n and k >= n:
            return f"{n} 次都测够了！可以看看这次改变对你有没有用了。"
        return f"记上了，第 {k} 次。再测 {n - k} 次，就能看出{x.get('intervention_zh') or '这次改变'}对你有没有用。"
    if spec == "data_gap":
        effect = ((state.get("gaps") or {}).get(q["id"]) or {}).get("effect_zh")
        return "记上了。" + effect if effect else "记上了，这个以后不会再问你。"
    if spec == "recurring":
        nxt = question_interval(q, after)
        if before and before[-1]["answer"] == ans["id"]:
            return f"和上次一样，记上了。下次隔 {nxt} 天再问你。"
        if before:
            prev = next((a["label_zh"] for a in q["answers"] if a["id"] == before[-1]["answer"]), "")
            return f"记上了，和上次（{prev}）不一样，我会留意。{nxt} 天后再问你。"
        return f"记上了。{nxt} 天后再问你一次，答案没变的话就越问越少。"
    return spec


# ---------- drafting ----------

def render(template: str, payload: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: str(num(payload.get(m.group(1), ""))), template)


def draft_question(event: dict) -> dict:
    p = dict(event["subject"], **event["payload"])
    q = QBANK[p["question"]]
    answers = list(q["answers"])
    last = p.get("last_answer")
    buttons = []
    if q.get("same_as_last") and last:
        prev = next((a for a in answers if a["id"] == last), None)
        if prev:
            buttons.append({"label_zh": f"和上次一样：{prev['label_zh']}", "answer": prev["id"]})
            answers = [a for a in answers if a["id"] != last]
    buttons += [{"label_zh": a["label_zh"], "answer": a["id"]} for a in answers]
    actions = [{"id": f"a{i + 1}", "label_zh": b["label_zh"], "type": "answer",
                "params": {"question": q["id"], "answer": b["answer"]}} for i, b in enumerate(buttons[:POLICY["limits"]["max_actions"]])]
    return {"title_zh": render(q["title_zh"], p), "body_zh": render(q["body_zh"], p),
            "push_text_zh": POLICY["push_text_zh"]["default"], "numbers": [], "actions": actions,
            "deep_link": render(TRIGGERS["question_due"]["deep_link"], p)}


def draft(event: dict) -> dict:
    if event["trigger"] == "question_due":
        return draft_question(event)
    trig = TRIGGERS[event["trigger"]]
    p = dict(event["subject"], **event["payload"])
    d = next(d for d in trig["drafts"] if all(p.get(k) not in (None, False, "", 0) for k in d.get("when", [])))
    actions = [dict({"id": f"a{i + 1}", "label_zh": a["label_zh"], "type": a["type"]},
                    **({"params": a["params"]} if a.get("params") else {})) for i, a in enumerate(d["actions"])]
    numbers = []
    for key in ("p_detect_favorable",):
        if key in p and p.get("label_zh"):
            numbers.append({"ref": f"{p.get('prediction') or p.get('prediction_ref')}.{key}", "value": p[key],
                            "label": p["label_zh"]})
    msg = {"title_zh": render(d["title_zh"], p), "body_zh": render(d["body_zh"], p),
           "push_text_zh": POLICY["push_text_zh"]["urgent" if event["category"] == "urgent" else "default"],
           "numbers": numbers, "actions": actions, "deep_link": render(trig["deep_link"], p)}
    if event["trigger"] == "milestone" or any(a["type"] == "checkin" for a in actions):
        n = int(p.get("cumulative") or 0) + 1
        msg["celebration_zh"] = celebration(n, p.get("picture_zh"))
    return msg


def celebration(n: int, picture: Optional[str]) -> str:
    if n in MILESTONES:
        return f"第 {n} 次！" + (f"离{picture}又近了一步。" if picture else "每一次都算数。")
    return f"记上了，累计第 {n} 次！"


# ---------- policy ----------

def prefs_of(state: dict) -> dict:
    p = state.get("preferences") or {}
    return {"consent": p.get("consent"), "quiet_hours": p.get("quiet_hours") or POLICY["quiet_hours"],
            "caps": dict(POLICY["caps"], **(p.get("caps") or {})), "muted": set(p.get("muted_triggers") or []),
            "enabled": p.get("enabled_triggers") or {}}


def consented(prefs: dict, category: str) -> bool:
    if category == "urgent":
        return True
    c = prefs["consent"]
    if c is None:
        return False
    return bool(c.get(category, CATEGORIES[category]["consent_default"]))


def downshifted(state: dict, tz) -> bool:
    k = POLICY["downshift_after_unopened"]
    msgs = [m for m in (state.get("history") or {}).get("messages", [])
            if m.get("category") != "urgent" and m.get("status") in ("sent", "read", "acted", "expired")]
    msgs.sort(key=lambda m: parse_time(m.get("sent_at") or m.get("send_after"), tz))
    last = msgs[-k:]
    return len(last) == k and all(m.get("status") in ("sent", "expired") and not m.get("opened_at") for m in last)


def sent_counts(state: dict, when: datetime, tz) -> Tuple[int, int]:
    day, week = 0, 0
    for m in (state.get("history") or {}).get("messages", []):
        if m.get("category") == "urgent" or m.get("status") not in LIVE:
            continue
        t = parse_time(m.get("sent_at") or m.get("send_after"), tz)
        if local_date(t, tz) == local_date(when, tz):
            day += 1
        if when - timedelta(days=7) < t <= when:
            week += 1
    return day, week


def scan(state: dict, export: Optional[dict], now: datetime, opening: bool = False) -> dict:
    tz = tzinfo(state.get("timezone"))
    export = export if export is not None else (state.get("export") or {})
    host = state.get("host", "standalone")
    prefs = prefs_of(state)
    hist = state.get("history") or {}
    fired = {f["dedup_key"]: f for f in hist.get("fired", [])}
    today = local_date(now, tz)

    cands = []
    for e in evaluate(state, export, now, tz):
        trig = TRIGGERS[e["trigger"]]
        if host not in trig["hosts"]:
            continue
        if not prefs["enabled"].get(e["trigger"], trig["enabled_by_default"]) and trig["user_can_disable"]:
            continue
        cands.append(e)
    drop = {s for e in cands for s in TRIGGERS[e["trigger"]].get("supersedes", [])}
    cands = [e for e in cands if e["trigger"] not in drop]  # e.g. a welcome back replaces the gap and review nudges

    suppressed, fresh = [], []
    for e in cands:
        if e["dedup_key"] in fired:
            continue  # already handled: silent
        cd = TRIGGERS[e["trigger"]]["cooldown_days"]
        if cd == "cadence":
            cd = state.get("chat_cadence_days") or 0
        if cd:
            sk = subject_key(e)
            prior = [parse_time(f["at"], tz) for f in fired.values() if f.get("subject_key") == sk]
            if prior and days_between(local_date(max(prior), tz), today) < cd:
                suppressed.append((e, "cooldown"))
                continue
        fresh.append(e)
    snoozes_due = []
    for s in state.get("snoozes") or []:
        if parse_time(s["until"], tz) <= now:
            e = copy.deepcopy(s["event"])
            fresh = [f for f in fresh if f["dedup_key"] != e["dedup_key"]]
            fresh.append(e)
            snoozes_due.append(e["dedup_key"])

    is_down = downshifted(state, tz)
    caps = dict(prefs["caps"])
    if is_down:
        caps["per_week"] = min(caps["per_week"], POLICY["caps"]["per_week_downshifted"])

    key = lambda e: (-e["priority"], e["occurred_at"], ORDER[e["trigger"]], e["dedup_key"])
    fresh.sort(key=key)
    messages, agenda_new, commit_fired = [], [], []
    picked = False

    def message(e: dict, status: str, send_after: datetime, reason: Optional[str] = None,
                deferred: Optional[str] = None) -> dict:
        d = draft(e)
        exp = send_after + timedelta(days=CATEGORIES[e["category"]]["expires_days"])
        m = {"schema": "pi-message/1", "id": f"M-{local_date(send_after, tz):%Y%m%d}-{short_hash(e['dedup_key'])}",
             "member": e["member"], "event": e["id"], "trigger": e["trigger"], "category": e["category"],
             "priority": e["priority"], **d, "status": status, "send_after": iso(send_after, tz), "expires_at": iso(exp, tz)}
        if reason:
            m["suppressed_reason"] = reason
        if deferred:
            m["deferred_reason"] = deferred
        return m

    for e in fresh:
        cat = e["category"]
        via = "agenda"
        if cat == "urgent":
            messages.append(message(e, "scheduled", now))
            via = "message"
        elif e["trigger"] in prefs["muted"]:
            suppressed.append((e, "muted"))
            continue
        elif not consented(prefs, cat):
            suppressed.append((e, "no_consent"))
            messages.append(message(e, "suppressed", now, "no_consent"))
        elif picked:
            pass  # merged: only the highest-priority non-urgent item gets a message in one scan
        else:
            picked = True
            end = quiet_end(now, tz, prefs["quiet_hours"])
            send = end or now
            day, week = sent_counts(state, send, tz)
            if day >= caps["per_day"] or week >= caps["per_week"]:
                suppressed.append((e, "cap"))
                messages.append(message(e, "suppressed", send, "cap"))
            else:
                m = message(e, "scheduled", send, deferred="quiet_hours" if end else None)
                if parse_time(m["expires_at"], tz) <= send:
                    m.update(status="suppressed", suppressed_reason="quiet_hours")
                    suppressed.append((e, "quiet_hours"))
                else:
                    via = "message"
                messages.append(m)
        if via == "agenda":
            agenda_new.append(e)
        commit_fired.append({"dedup_key": e["dedup_key"], "trigger": e["trigger"], "subject_key": subject_key(e),
                             "event_id": e["id"], "at": iso(now, tz), "via": via, "event": e})

    keep = timedelta(days=POLICY["agenda_keep_days"])
    acted = {m.get("event") for m in hist.get("messages", []) if m.get("status") == "acted"}
    pending = [f["event"] for f in hist.get("fired", []) if f.get("via") in ("agenda", "message") and not f.get("seen_at")
               and f.get("event") and f["event_id"] not in acted and now - parse_time(f["at"], tz) <= keep
               and f["event"]["trigger"] not in prefs["muted"]
               and (f["event"]["trigger"] != "question_due" or question_still_open(state, f, tz, today))]
    sent_now = [e for e in fresh if any(m["event"] == e["id"] and m["status"] == "scheduled" for m in messages)]
    asked_now = {e["subject"].get("question") for e in sent_now + agenda_new if e["trigger"] == "question_due"}
    pending = [e for e in pending if e["trigger"] != "question_due" or e["subject"].get("question") not in asked_now]
    agenda = sorted({e["dedup_key"]: e for e in pending + sent_now + agenda_new}.values(), key=key)

    commit = {"fired": commit_fired, "messages": [m for m in messages], "remove_snoozes": snoozes_due,
              "seen": [e["dedup_key"] for e in agenda] if opening else []}
    return {"schema": "pi-scan/1", "member": state.get("member", ""), "now": iso(now, tz), "host": host,
            "events": fresh, "messages": messages, "agenda": agenda,
            "suppressed": [{"event": e["id"], "trigger": e["trigger"], "dedup_key": e["dedup_key"], "reason": r}
                           for e, r in suppressed],
            "policy": {"downshifted": is_down, "ask_about_frequency": is_down,
                       "ask_consent": prefs["consent"] is None, "caps": caps},
            "commit": commit}


def apply_commit(state: dict, commit: dict, now: datetime) -> dict:
    st = copy.deepcopy(state)
    tz = tzinfo(st.get("timezone"))
    hist = st.setdefault("history", {})
    hist.setdefault("fired", []).extend(commit["fired"])
    for m in commit["messages"]:
        f = next((f for f in commit["fired"] if f["event_id"] == m["event"]), {})
        row = {k: m[k] for k in ("id", "event", "trigger", "category", "status", "send_after", "expires_at",
                                 "suppressed_reason", "celebration_zh") if m.get(k) is not None}
        hist.setdefault("messages", []).append(dict(row, dedup_key=f.get("dedup_key"),
                                                    subject=(f.get("event") or {}).get("subject", {})))
    st["snoozes"] = [s for s in st.get("snoozes") or [] if s["event"]["dedup_key"] not in commit["remove_snoozes"]]
    for f in hist["fired"]:
        if f["dedup_key"] in commit.get("seen", []) and not f.get("seen_at"):
            f["seen_at"] = iso(now, tz)
    return st


# ---------- lint ----------

def numbers_in(text: str) -> List[str]:
    return re.findall(r"\d+(?:\.\d+)?", text)


def allowed_numbers(obj: Any, out: set) -> set:
    if isinstance(obj, bool) or obj is None:
        return out
    if isinstance(obj, (int, float)):
        for v in (obj, obj * 100, abs(obj), abs(obj) * 100):
            for nd in (0, 1, 2):
                out.add(f"{round(v, nd):.{nd}f}")
        return out
    if isinstance(obj, str):
        out.update(numbers_in(obj))
        for n in numbers_in(obj):
            out.add(f"{float(n):g}")
        return out
    for v in (obj.values() if isinstance(obj, dict) else obj):
        allowed_numbers(v, out)
    return out


def norm_number(n: str) -> str:
    return f"{float(n):g}"


def lint(message: dict, event: dict) -> List[dict]:
    errs: List[dict] = []
    err = lambda code, text: errs.append({"code": code, "message": text})
    lim = POLICY["limits"]
    title, body, push = message.get("title_zh", ""), message.get("body_zh", ""), message.get("push_text_zh", "")
    if message.get("event") != event.get("id"):
        err("event_mismatch", "message.event 和事件 id 不一致")
    if message.get("category") != event.get("category"):
        err("category_mismatch", "消息类别和事件类别不一致")
    if not title or len(title) > lim["title_chars"]:
        err("title_length", f"标题 {len(title)} 字，应为 1–{lim['title_chars']} 字")
    if not body or len(body) > lim["body_chars"]:
        err("body_length", f"正文 {len(body)} 字，应为 1–{lim['body_chars']} 字")
    acts = message.get("actions") or []
    if len(acts) > lim["max_actions"]:
        err("too_many_actions", f"{len(acts)} 个按钮，最多 {lim['max_actions']} 个")
    for a in acts:
        if a.get("type") not in ACTION_TYPES or a.get("type") == "read":
            err("bad_action", f"按钮类型 {a.get('type')!r} 不在允许的列表里")
        if a.get("type") == "snooze" and (a.get("params") or {}).get("days") not in POLICY["snooze_days"]:
            err("bad_snooze", "稍后提醒只能是 1、3 或 7 天")
    allowed = {norm_number(n) for n in allowed_numbers([event.get("payload"), event.get("subject")], set())}
    fixed = POLICY["urgent_first_sentence_zh"]
    checked = (title + "\n" + body).replace(fixed, "") if event.get("category") == "urgent" else title + "\n" + body
    for n in numbers_in(checked):
        if norm_number(n) not in allowed:
            err("number_without_source", f"数字 {n} 不在事件负载里")
    for x in message.get("numbers") or []:
        vals = x.get("value") if isinstance(x.get("value"), list) else [x.get("value")]
        if any(norm_number(str(v)) not in allowed for v in vals):
            err("number_without_source", f"numbers 里的 {x.get('value')} 不在事件负载里")
        if not x.get("label"):
            err("number_without_label", f"数字 {x.get('ref')} 没有标签")
        elif x["label"] not in body:
            err("label_not_in_body", f"正文里没有写出标签“{x['label']}”")
    label = (event.get("payload") or {}).get("label_zh")
    needs_label = event.get("category") == "clinical" or event.get("trigger") == "prediction_ready" or \
        "p_pct" in (event.get("payload") or {})
    if needs_label:
        if not any(w in body for w in POLICY["label_words_zh"]) or (label and label not in body):
            err("missing_label", "临床结论或概率必须带标签（如“统计模型估计”“AI 判断”“CPIC”）")
    if event.get("category") == "clinical" and not any(a.get("type") == "prepare_doctor_brief" for a in acts):
        err("missing_doctor_brief", "临床类消息要有“整理问医生的单子”按钮")
    if event.get("trigger") in ("change_beyond_noise", "trend_beyond_noise", "wearable_shift"):
        first = re.split(r"[。！？!?]", body, maxsplit=1)[0]
        if not any(w in first for w in POLICY["noise_words_zh"]):
            err("noise_first", "数据类消息第一句要说变化是不是超出个人正常波动")
    if event.get("category") == "urgent":
        if not body.startswith(fixed):
            err("urgent_first_sentence", f"紧急消息第一句必须是“{fixed}”")
        expected = draft(event)["body_zh"]
        if body != expected:
            err("urgent_rewritten", "紧急消息由模板填写，不能改写")
    for w in POLICY["forbidden_zh"]:
        if w in title or w in body or w in push:
            err("forbidden_word", f"出现了禁用的说法“{w}”")
    if not push or len(push) > lim["title_chars"] or re.search(r"\d", push):
        err("push_text", "推送文字不能为空、不能超过 20 字、不能含数字")
    if event.get("trigger") == "question_due":
        q = QBANK.get((event.get("subject") or {}).get("question"))
        answers = [a for a in acts if a.get("type") == "answer"]
        if not answers:
            err("question_no_answer", "提问消息至少要有一个回答按钮")
        for a in answers:
            prm = a.get("params") or {}
            if q is None or prm.get("question") != q["id"] or prm.get("answer") not in {x["id"] for x in q["answers"]}:
                err("bad_answer", f"回答按钮 {a.get('id')} 不是这个问题的答案")
    p = event.get("payload") or {}
    for k in ("marker", "metric", "drug_zh", "drug", "commitment_zh", "event_zh", "kind_zh", "intervention_zh", "conclusion_zh"):
        if isinstance(p.get(k), str) and p[k] and p[k] in push:
            err("push_has_health_data", "推送文字里不能有健康数据")
    return errs


# ---------- ack ----------

def ack(state: dict, action: dict, now: Optional[datetime] = None) -> Tuple[dict, dict]:
    st = copy.deepcopy(state)
    tz = tzinfo(st.get("timezone"))
    hist = st.setdefault("history", {})
    acts = hist.setdefault("actions", [])
    key = action.get("idempotency_key") or f"{action.get('message')}:{action.get('action')}"
    prior = next((a for a in acts if a.get("idempotency_key") == key), None)
    if prior:
        return state, dict(prior["result"], duplicate=True)
    typ = action.get("type")
    if typ not in ACTION_TYPES:
        raise ValueError(f"unknown action type {typ!r}")
    at = parse_time(action.get("at"), tz) or now
    msg = next((m for m in hist.get("messages", []) if m.get("id") == action.get("message")), None)
    if msg is None and typ not in ("checkin", "answer"):
        raise ValueError(f"message {action.get('message')!r} not found in history")
    params = action.get("params") or {}
    result: Dict[str, Any] = {"ok": True, "type": typ, "message": action.get("message")}
    if msg is not None:
        msg["opened_at"] = msg.get("opened_at") or iso(at, tz)
        msg["status"] = "read" if typ == "read" else "acted"
        result["message_status"] = msg["status"]
    subject = (msg or {}).get("subject") or {}
    event = next((f["event"] for f in hist.get("fired", []) if msg and f.get("event_id") == msg.get("event")), None)

    if typ == "checkin":
        cid = params.get("commitment") or subject.get("commitment")
        comm = next((c for c in st.get("commitments") or [] if c.get("id") == cid), None)
        if comm is None:
            raise ValueError("checkin needs a commitment (params.commitment or a message about one)")
        n = int(params.get("count") or 1)
        comm["cumulative"] = int(comm.get("cumulative") or 0) + n
        comm["last_checkin_at"] = iso(at, tz)
        comm.setdefault("checkins", []).append({"at": iso(at, tz), "count": n})
        result.update(commitment=cid, cumulative=comm["cumulative"],
                      celebration_zh=celebration(comm["cumulative"], st.get("picture_zh")))
        if comm["cumulative"] in MILESTONES:  # celebrated right here; the scan must not celebrate it again
            hist.setdefault("fired", []).append({"dedup_key": f"milestone:{cid}:{comm['cumulative']}", "trigger": "milestone",
                                                 "subject_key": f"milestone:commitment={cid}", "event_id": None,
                                                 "at": iso(at, tz), "via": "ack"})
    elif typ == "snooze":
        days = params.get("days")
        if days not in POLICY["snooze_days"]:
            raise ValueError("snooze days must be 1, 3 or 7")
        if event is None:
            raise ValueError("snoozed message has no stored event")
        until = at + timedelta(days=days)
        st["snoozes"] = [s for s in st.get("snoozes") or [] if s["event"]["dedup_key"] != event["dedup_key"]]
        st["snoozes"].append({"event": event, "until": iso(until, tz)})
        result["until"] = iso(until, tz)
    elif typ == "mute_trigger":
        trig = params.get("trigger") or (msg or {}).get("trigger")
        if not TRIGGERS.get(trig, {}).get("user_can_disable", False):
            raise ValueError(f"trigger {trig!r} cannot be muted")
        prefs = st.setdefault("preferences", {})
        prefs["muted_triggers"] = sorted(set(prefs.get("muted_triggers") or []) | {trig})
        result["muted_trigger"] = trig
    elif typ == "schedule_retest":
        rid = params.get("retest") or subject.get("retest")
        st["retests_scheduled"] = sorted(set(st.get("retests_scheduled") or []) | {rid})
        result["retest"] = rid
    elif typ == "start_experiment_phase":
        xid = params.get("experiment") or subject.get("experiment")
        x = next((x for x in st.get("experiments") or [] if x.get("id") == xid), None)
        if x is None:
            raise ValueError(f"experiment {xid!r} not found")
        x["post_started_at"] = x.get("post_started_at") or iso(at, tz)
        x["post_done"] = x.get("post_done") or 0
        result.update(experiment=xid, post_started_at=x["post_started_at"])
    elif typ == "answer":
        qid = params.get("question") or subject.get("question")
        q = QBANK.get(qid)
        if q is None:
            raise ValueError(f"answer needs a known question, got {qid!r}")
        _, before = question_log(st, qid, tz)
        aid = before[-1]["answer"] if params.get("answer") == "same" and before else params.get("answer")
        ans = next((a for a in q["answers"] if a["id"] == aid), None)
        if ans is None:
            raise ValueError(f"{aid!r} is not an answer to {qid}")
        hist.setdefault("answers", []).append({"question": qid, "answer": aid, "at": iso(at, tz), "message": action.get("message")})
        for path, value in (ans.get("sets") or {}).items():
            set_path(st, path, value)
        xid = params.get("experiment") or ((event or {}).get("payload") or {}).get("experiment")
        if (ans.get("effect") or {}).get("experiment_post_done"):
            x = active_experiment(st, xid) or active_experiment(st)
            if x is None:
                raise ValueError("no running post-test to count this answer for")
            x["post_done"] = int(x.get("post_done") or 0) + ans["effect"]["experiment_post_done"]
            xid = x.get("id")
        _, after = question_log(st, qid, tz)
        result.update(question=qid, answer=aid, record=ans.get("sets") or {},
                      feedback_zh=answer_feedback(st, q, ans, before, after, xid))
        if ans.get("then"):
            result["next"] = ans["then"]
    elif typ in ("open_chat", "open_card", "prepare_doctor_brief", "call_emergency"):
        result["next"] = typ
        if typ == "open_chat":
            result["context_message"] = action.get("message")
    acts.append({"idempotency_key": key, "message": action.get("message"), "action": action.get("action"), "type": typ,
                 "at": iso(at, tz), "params": params, "result": result})
    return st, dict(result, duplicate=False)


# ---------- standalone member file ----------

def section(md: str, name: str) -> str:
    m = re.search(rf"^## {re.escape(name)}[^\n]*\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    return m.group(1) if m else ""


def table(text: str) -> List[Dict[str, str]]:
    rows = [l.strip() for l in text.splitlines() if l.strip().startswith("|")]
    if len(rows) < 2:
        return []
    head = [c.strip() for c in rows[0].strip("|").split("|")]
    return [dict(zip(head, [c.strip() for c in r.strip("|").split("|")])) for r in rows[2:]]


DATE = r"(\d{4}-\d{1,2}-\d{1,2})"


def iso_day(s: str) -> str:
    y, m, d = s.split("-")
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def member_state(md_path: Path) -> dict:
    """Read the fixed parts of a member file into pi-state/1, then overlay the sidecar <name>.proactive.json."""
    md = re.sub(r"<!--.*?-->", "", md_path.read_text(encoding="utf-8"), flags=re.S)
    side_path = md_path.with_suffix(".proactive.json")
    side = json.loads(side_path.read_text(encoding="utf-8")) if side_path.is_file() else {}
    basic = section(md, "基本")
    st: Dict[str, Any] = {"schema": "pi-state/1", "member": md_path.stem, "host": "standalone",
                          "timezone": "Asia/Shanghai"}
    m = re.search(r"聊天节奏：[^\n\d]*(\d+)\s*天", basic)
    st["chat_cadence_days"] = int(m.group(1)) if m else None
    m = re.search(r"时区：\s*([A-Za-z_/+\-:0-9]+)", basic)
    if m:
        st["timezone"] = m.group(1)
    prefs: Dict[str, Any] = {}
    m = re.search(r"主动提醒：([^\n]*)", basic)
    if m and m.group(1).strip():
        names = {"教练": "coaching", "复测": "retest", "数据": "data", "临床": "clinical", "关怀": "care", "提问": "question"}
        found = dict(re.findall(r"(教练|复测|数据|临床|关怀|提问)\s*(开|关)", m.group(1)))
        if found:
            prefs["consent"] = {names[k]: v == "开" for k, v in found.items()}
        if "提问" in found:
            prefs["enabled_triggers"] = {"question_due": found["提问"] == "开"}
    life = section(md, "生活和偏好")
    m = re.search(r"吸烟：\s*(从不|已戒|戒了|在吸|现在吸)", life)
    profile: Dict[str, Any] = {}
    if m:
        profile["smoking"] = {"从不": "never", "已戒": "former", "戒了": "former"}.get(m.group(1), "current")
    if re.search(r"家族病史：\s*[^\s<（(]", life):
        profile["family_history_known"] = True
    if profile:
        st["profile"] = profile
    m = re.search(r"免打扰：\s*(\d{1,2}:\d{2})\s*[–\-~到至]\s*(\d{1,2}:\d{2})", basic)
    if m:
        prefs["quiet_hours"] = {"start": m.group(1).zfill(5), "end": m.group(2).zfill(5)}
    m = re.search(r"七八十岁时想还能做的事：\s*([^\n]+)", section(md, "为什么 & 想要的画面"))
    st["picture_zh"] = m.group(1).strip() if m and m.group(1).strip() else None
    status = {"进行中": "active", "暂停": "paused", "毕业": "graduated", "已毕业": "graduated", "放弃": "dropped", "停了": "dropped"}
    comms = []
    for i, r in enumerate(table(section(md, "小承诺"))):
        if not r.get("承诺"):
            continue
        cum = re.search(r"\d+", r.get("累计次数", "") or "")
        start = re.search(DATE, r.get("开始", "") or "")
        comms.append({"id": f"C{i + 1}", "label_zh": r["承诺"], "plan_item": r.get("方案项") or None,
                      "status": status.get((r.get("状态") or "进行中").strip(), "active"),
                      "started_at": iso_day(start.group(1)) if start else None,
                      "cumulative": int(cum.group(0)) if cum else 0, "last_checkin_at": None})
    review_dates = [iso_day(d) for d in re.findall(r"^- " + DATE, section(md, "小承诺"), re.M)]
    for c in comms:
        if review_dates:
            c["last_checkin_at"] = max(review_dates)
    st["commitments"] = comms
    st["life_events"] = [{"id": f"L-{iso_day(d)}-{short_hash(t.strip())}", "date": iso_day(d), "label_zh": t.strip()}
                         for d, t in re.findall(r"^- " + DATE + r"\s*[：:，, ]?\s*([^\n]+)", section(md, "近期大事"), re.M)]
    meas, pending = [], {}
    for i, r in enumerate(table(section(md, "测量"))):
        d = re.search(DATE, r.get("日期", "") or "")
        name, val, unit = (r.get("指标") or "").strip(), (r.get("数值") or "").strip(), (r.get("单位") or "").strip()
        if not d or not val:
            continue
        day = iso_day(d.group(1))
        bp = re.fullmatch(r"(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)", val)
        if name == "血压" and bp:
            meas.append({"id": f"m{i + 1}", "at": day, "kind": "blood_pressure", "unit": unit or "mmHg",
                         "values": {"sbp": float(bp.group(1)), "dbp": float(bp.group(2))}})
        elif name in ("收缩压", "舒张压") and re.fullmatch(r"\d+(?:\.\d+)?", val):
            k = (day, r.get("来源"))
            entry = pending.setdefault(k, {"id": f"m{i + 1}", "at": day, "kind": "blood_pressure",
                                           "unit": unit or "mmHg", "values": {}})
            entry["values"]["sbp" if name == "收缩压" else "dbp"] = float(val)
        elif name == "腰围" and re.fullmatch(r"\d+(?:\.\d+)?", val):
            meas.append({"id": f"m{i + 1}", "at": day, "kind": "waist", "unit": unit or "cm", "values": {"waist": float(val)}})
        elif "血糖" in name and re.fullmatch(r"\d+(?:\.\d+)?", val):
            meas.append({"id": f"m{i + 1}", "at": day, "kind": "glucose", "unit": unit, "values": {"glucose": float(val)}})
    meas += [e for e in pending.values() if len(e["values"]) == 2]
    st["measurements"] = meas
    exps = []
    for line in re.findall(r"^- ([^\n]+)", section(md, "个人实验"), re.M):
        xid = re.search(r"\b(X\d+)\b", line)
        start = re.search(r"开始\s*" + DATE, line)
        if not (xid and start):
            continue
        g = lambda pat: (lambda mm: int(mm.group(1)) if mm else None)(re.search(pat, line))
        post = re.search(r"后测开始\s*" + DATE, line)
        head = re.split(r"[（(]", line, 1)[0]
        marker = re.search(r"看(\S+?)(?:[（(]|$)", head)
        exps.append({"id": xid.group(1), "intervention_zh": re.sub(r"看\S+$", "", head).strip(),
                     "marker": marker.group(1) if marker else None,
                     "plan_item": (lambda mm: mm.group(1) if mm else None)(re.search(r"方案项\s*(I\d+)", line)),
                     "started_at": iso_day(start.group(1)), "min_weeks": g(r"最短\s*(\d+)\s*周"),
                     "repeats_needed": g(r"后测\s*(\d+)\s*次"), "post_done": g(r"已测\s*(\d+)\s*次") or 0,
                     "post_started_at": iso_day(post.group(1)) if post else None,
                     "prediction_ref": (lambda mm: mm.group(1) if mm else None)(re.search(r"预测\s*(P\d+)", line)),
                     "status": "done" if "结果：" in line else "running"})
    st["experiments"] = exps
    m = re.search(r"日期：\s*" + DATE, section(md, "上次对话"))
    st["last_interaction_at"] = iso_day(m.group(1)) if m else None
    # the sidecar holds what markdown does not: history, snoozes, mutes, overrides written by ack
    for k in ("history", "snoozes", "retests_scheduled", "data_batches", "medications_in_use", "plan_targets", "wearable",
              "member", "gaps"):
        if k in side:
            st[k] = side[k]
    p = dict(side.get("preferences") or {})
    p.update(prefs)
    st["preferences"] = p
    if side.get("profile"):
        st["profile"] = dict(side["profile"], **(st.get("profile") or {}))
    for c in st["commitments"]:
        o = (side.get("commitments") or {}).get(c["label_zh"]) or {}
        c.update({k: v for k, v in o.items() if k in ("last_checkin_at", "checkins")})
        if o.get("cumulative") and o["cumulative"] > c["cumulative"]:
            c["cumulative"] = o["cumulative"]
    for x in st["experiments"]:
        o = (side.get("experiments") or {}).get(x["id"]) or {}
        x.update({k: v for k, v in o.items() if v is not None})
    return st


def save_member(md_path: Path, before: dict, after: dict) -> None:
    """Write the sidecar, and the check-in count back into the member file's 小承诺 table."""
    side_path = md_path.with_suffix(".proactive.json")
    side = json.loads(side_path.read_text(encoding="utf-8")) if side_path.is_file() else {}
    for k in ("history", "snoozes", "retests_scheduled", "profile"):
        if after.get(k) is not None:
            side[k] = after[k]
    side["preferences"] = {k: v for k, v in (after.get("preferences") or {}).items() if k == "muted_triggers"} | \
        {k: v for k, v in (side.get("preferences") or {}).items() if k != "muted_triggers"}
    side["commitments"] = {c["label_zh"]: {"cumulative": c.get("cumulative"), "last_checkin_at": c.get("last_checkin_at"),
                                           "checkins": c.get("checkins", [])} for c in after.get("commitments") or []}
    side["experiments"] = {x["id"]: {"post_started_at": x.get("post_started_at"), "post_done": x.get("post_done")}
                           for x in after.get("experiments") or []}
    side_path.write_text(json.dumps(side, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    old = {c["id"]: c.get("cumulative") for c in before.get("commitments") or []}
    md = md_path.read_text(encoding="utf-8")
    for c in after.get("commitments") or []:
        if c.get("cumulative") == old.get(c["id"]):
            continue
        lines = md.splitlines(keepends=True)
        sec = re.search(r"^## 小承诺", md, re.M)
        if not sec:
            break
        head_idx = None
        offset = md[:sec.start()].count("\n")
        for i in range(offset, len(lines)):
            if lines[i].startswith("|") and "累计次数" in lines[i]:
                head_idx = i
                break
        if head_idx is None:
            break
        head = [h.strip() for h in lines[head_idx].strip().strip("|").split("|")]
        col = head.index("累计次数")
        for i in range(head_idx + 2, len(lines)):
            if not lines[i].startswith("|"):
                break
            cells = lines[i].rstrip("\n").strip().strip("|").split("|")
            if cells[0].strip() == c["label_zh"]:
                cells[col] = f" {c['cumulative']} "
                lines[i] = "|" + "|".join(cells) + "|\n"
        md = "".join(lines)
    md_path.write_text(md, encoding="utf-8")


# ---------- CLI ----------

def load_state(args) -> Tuple[dict, Optional[Path], Optional[Path]]:
    if args.member:
        p = Path(args.member).expanduser()
        return member_state(p), p, None
    p = Path(args.state)
    return json.loads(p.read_text(encoding="utf-8")), None, p


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "ack"):
        s = sub.add_parser(name)
        g = s.add_mutually_exclusive_group(required=True)
        g.add_argument("--member")
        g.add_argument("--state")
        s.add_argument("--now")
        s.add_argument("--write", action="store_true", help="save the updated state (sidecar, or the state file)")
        if name == "scan":
            s.add_argument("--export")
            s.add_argument("--opening", action="store_true", help="session start: the agenda is shown, mark it seen")
            s.add_argument("--inbox", help="also write the scheduled messages to this inbox file (standalone cron)")
        else:
            s.add_argument("--action", required=True)
    s = sub.add_parser("lint")
    s.add_argument("--message", required=True)
    s.add_argument("--event", required=True)
    args = ap.parse_args(argv)

    if args.cmd == "lint":
        msg = json.loads(Path(args.message).read_text(encoding="utf-8"))
        ev = json.loads(Path(args.event).read_text(encoding="utf-8"))
        errs = lint(msg, ev)
        print(json.dumps({"ok": not errs, "errors": errs}, ensure_ascii=False, indent=2))
        return 0 if not errs else 1

    state, md_path, state_path = load_state(args)
    tz = tzinfo(state.get("timezone"))
    now = parse_time(args.now, tz) if args.now else datetime.now(tz)
    if args.cmd == "scan":
        export = json.loads(Path(args.export).read_text(encoding="utf-8")) if args.export else None
        out = scan(state, export, now, opening=args.opening)
        new = apply_commit(state, out["commit"], now)
        if args.inbox:
            ip = Path(args.inbox).expanduser()
            box = json.loads(ip.read_text(encoding="utf-8")) if ip.is_file() else {"schema": "pi-inbox/1", "messages": []}
            have = {m["id"] for m in box["messages"]}
            box["messages"] += [m for m in out["messages"] if m["status"] == "scheduled" and m["id"] not in have]
            ip.write_text(json.dumps(box, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        action = json.loads(Path(args.action).read_text(encoding="utf-8"))
        try:
            new, out = ack(state, action, now)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            return 2
    if args.write:
        if md_path:
            save_member(md_path, state, new)
        else:
            state_path.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
