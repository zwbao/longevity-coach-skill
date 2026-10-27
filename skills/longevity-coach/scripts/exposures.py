#!/usr/bin/env python3
"""What the member has been doing, for the analyst's twin: member file -> la-exposures/1.

  exposures.py --member ~/.longevity-coach/老王.md --out exposures.json [--export <la-export.json>] [--now 2026-09-20T10:00:00+08:00]

Reads only the fixed structures of the member file (templates/member.md): the 小承诺 table, the 复盘记录 lines
("- 2026-08-23 限盐勺：4 / 5，……") and the analyst member id in 后台. Rows without a 方案项 are not plan items and are
left out. The cumulative count is the table's value; weekly counts come from review records, and a record that does
not fall inside one Monday-to-Sunday week (or whose commitment is unclear) is left out, never estimated or split.
With --export (the analyst's la-export.json) each plan item gets its category, short title and target markers.
A table row that cannot be read stops the script with exit code 2 and names the line.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

STATUS = {"进行中": "adopted", "在做": "adopted", "采纳": "adopted", "已采纳": "adopted",
          "暂停": "paused", "毕业": "graduated", "已毕业": "graduated",
          "不做了": "dropped", "放弃": "dropped", "停止": "dropped", "已停止": "dropped",
          "未开始": "proposed", "计划": "proposed", "待定": "proposed"}
STATUS.update({v: v for v in set(STATUS.values())})
NEEDED = ("承诺", "开始", "累计次数", "状态", "方案项")
DATE = r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})"
RECORD = re.compile(r"^-\s*" + DATE + r"\s*(.*?)\s*[：:]\s*(\d+)\s*(?:/|／)\s*(\d+)")
LABEL_MAX = 40


class FileError(Exception):
    pass


def fold(s: str) -> str:
    return re.sub(r"[\s，,。.、：:（）()\"“”]+", "", unicodedata.normalize("NFKC", s)).casefold()


def to_date(s: str, where: str) -> Optional[date]:
    s = s.strip()
    if not s:
        return None
    m = re.fullmatch(DATE, s)
    if not m:
        raise FileError(f"{where}：日期“{s}”看不懂，请写成 2026-08-15")
    return date(*map(int, m.groups()))


def section(lines: List[str], title: str) -> Tuple[int, int]:
    start = next((i for i, l in enumerate(lines) if l.strip() == f"## {title}"), None)
    if start is None:
        raise FileError(f"档案里没有「{title}」一节")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return start + 1, end


def cells(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def commitments(lines: List[str]) -> List[Dict[str, Any]]:
    a, b = section(lines, "小承诺")
    head = next((i for i in range(a, b) if lines[i].lstrip().startswith("|")), None)
    if head is None:
        raise FileError("「小承诺」一节没有表格")
    cols = cells(lines[head])
    missing = [c for c in NEEDED if c not in cols]
    if missing:
        raise FileError(f"第 {head + 1} 行：小承诺表缺少列 {'、'.join(missing)}（模板见 templates/member.md）")
    rows = []
    for i in range(head + 1, b):
        line = lines[i]
        if not line.lstrip().startswith("|"):
            break
        c = cells(line)
        if all(re.fullmatch(r":?-+:?", x) for x in c if x):
            continue
        where = f"第 {i + 1} 行"
        if len(c) != len(cols):
            raise FileError(f"{where}：有 {len(c)} 格，表头有 {len(cols)} 列")
        r = dict(zip(cols, c))
        if not r["方案项"]:
            continue
        st = STATUS.get(r["状态"])
        if not st:
            raise FileError(f"{where}：状态“{r['状态']}”看不懂，请写 进行中、暂停、毕业、不做了 或 未开始")
        n = r["累计次数"].replace("次", "").strip()
        if not n:
            n = "0" if st == "proposed" else ""
        if not n.isdigit():
            raise FileError(f"{where}：累计次数“{r['累计次数']}”应该是一个整数")
        rows.append({"line": i + 1, "text": r["承诺"], "plan_item": r["方案项"], "status": st,
                     "start": to_date(r["开始"], where), "cumulative": int(n)})
    return rows


def records(lines: List[str], rows: List[Dict[str, Any]]) -> Tuple[Dict[int, List[Tuple[date, int]]], List[str]]:
    """Review records per commitment row; lines that name no single commitment are reported, not guessed."""
    a, b = section(lines, "小承诺")
    out: Dict[int, List[Tuple[date, int]]] = {}
    skipped = []
    for i in range(a, b):
        m = RECORD.match(lines[i].strip())
        if not m:
            continue
        d, name, done = date(*map(int, m.groups()[:3])), m.group(4), int(m.group(5))
        if name:
            hit = [r for r in rows if fold(name) and (fold(name) in fold(r["text"]) or fold(r["text"]) in fold(name)
                                                      or fold(name) == fold(r["plan_item"]))]
        else:
            hit = rows if len(rows) == 1 else []
        if len(hit) != 1:
            skipped.append(f"第 {i + 1} 行：对不上唯一一个承诺")
            continue
        out.setdefault(hit[0]["line"], []).append((d, done))
    return out, skipped


def weekly(row: Dict[str, Any], recs: List[Tuple[date, int]], skipped: List[str]) -> List[Dict[str, Any]]:
    """Each record covers the days since the previous one (the first: since 开始); it counts only inside one week."""
    weeks: Dict[date, int] = {}
    prev: Optional[date] = None
    for d, n in sorted(recs):
        first = prev + timedelta(days=1) if prev else row["start"]
        prev = d
        if first is None or first > d:
            skipped.append(f"{d.isoformat()} {row['text']}：不知道这条记录从哪天算起")
            continue
        monday = first - timedelta(days=first.weekday())
        if (d - monday).days >= 7:
            skipped.append(f"{d.isoformat()} {row['text']}：记录跨了不止一周，这几周不写")
            continue
        weeks[monday] = weeks.get(monday, 0) + n
    return [{"week_start": w.isoformat(), "count": c} for w, c in sorted(weeks.items())]


def member_id(lines: List[str]) -> Optional[str]:
    for l in lines:
        m = re.match(r"^-\s*分析师会员编号\s*[：:]\s*(\S+)", l.strip())
        if m:
            return m.group(1)
    return None


def plan_info(export: Optional[Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Optional[str]]:
    if not export:
        return {}, None
    items = {}
    for i in (export.get("plan") or {}).get("items", []):
        for k in (i.get("source_item"), i.get("id")):
            if k:
                items[k] = i
    return items, (export.get("member") or {}).get("sample_date")


PRECEDENCE = ["adopted", "paused", "graduated", "proposed", "dropped"]


def build(text: str, export: Optional[Dict[str, Any]], member: Optional[str], now: str) -> Tuple[Dict[str, Any], List[str]]:
    lines = text.splitlines()
    member = member or member_id(lines)
    if not member:
        raise FileError("档案「后台」里没有分析师会员编号，请用 --member-id 给出")
    rows = commitments(lines)
    recs, skipped = records(lines, rows)
    plan, origin = plan_info(export)
    if export is None and rows:
        skipped.append("没有给 --export：类别记为 other，目标指标留空")
    items: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        p = plan.get(r["plan_item"]) or plan.get(f"la-{r['plan_item'].lower()}") or {}
        it = items.setdefault(r["plan_item"], {
            "plan_item": r["plan_item"], "origin_snapshot": origin,
            "label_zh": (p.get("title") or r["text"])[:LABEL_MAX], "category": p.get("kind") or "other",
            "targets": list(p.get("markers") or []), "status": r["status"], "adopted_at": None, "status_since": None,
            "weekly_checkins": {}, "cumulative": 0})
        # several rows for one plan item (a commitment shrunk or rewritten): add up, keep the most active status
        if PRECEDENCE.index(r["status"]) < PRECEDENCE.index(it["status"]):
            it["status"] = r["status"]
        if r["start"] and r["status"] != "proposed":
            it["adopted_at"] = min(filter(None, [it["adopted_at"], r["start"].isoformat()]))
        it["cumulative"] += r["cumulative"]
        for w in weekly(r, recs.get(r["line"], []), skipped):
            it["weekly_checkins"][w["week_start"]] = it["weekly_checkins"].get(w["week_start"], 0) + w["count"]
    out = []
    for it in items.values():
        it["status_since"] = it["adopted_at"]  # the member file keeps no date of the last status change
        it["weekly_checkins"] = [{"week_start": k, "count": v} for k, v in sorted(it["weekly_checkins"].items())]
        out.append(it)
    return {"schema": "la-exposures/1", "member": member, "source": "coach_member_file", "generated_at": now,
            "items": out}, skipped


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--member", required=True, help="the member file (markdown)")
    p.add_argument("--out", required=True)
    p.add_argument("--export", help="the analyst's deliver/la-export.json, for category, title and targets")
    p.add_argument("--member-id", help="analyst member id, when 后台 does not have it")
    p.add_argument("--now", help="generated_at, ISO time with time zone (default: now)")
    a = p.parse_args(argv)
    try:
        text = Path(a.member).expanduser().read_text(encoding="utf-8")
        export = json.loads(Path(a.export).expanduser().read_text(encoding="utf-8")) if a.export else None
        doc, skipped = build(text, export, a.member_id, a.now or datetime.now().astimezone().isoformat(timespec="seconds"))
    except (FileError, OSError, json.JSONDecodeError) as e:
        print(f"exposures.py: {e}", file=sys.stderr)
        return 2
    Path(a.out).expanduser().write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"out": a.out, "items": len(doc["items"]), "left_out": skipped}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
