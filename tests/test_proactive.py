"""Tests for scripts/proactive.py: the shared proactive-cases/1 fixture, schemas, lint, member-file mode, OpenAPI.
Run: python3 -m pytest tests/test_proactive.py"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "longevity-coach"
sys.path.insert(0, str(SKILL / "scripts"))
import proactive as P  # noqa: E402

CASES = json.loads((ROOT / "tests" / "fixtures" / "proactive_cases.json").read_text(encoding="utf-8"))
SCHEMA = SKILL / "schema"

try:
    import jsonschema
    from referencing import Registry, Resource
except ImportError:  # pragma: no cover
    jsonschema = None


def get_path(obj, path):
    for part in path.split("."):
        if part == "length":
            return len(obj)
        obj = obj[int(part)] if isinstance(obj, list) else obj[part]
    return obj


def resolve(value, last_scan):
    if isinstance(value, str):
        return re.sub(r"\$messages\[(\d+)\]\.id", lambda m: last_scan["messages"][int(m.group(1))]["id"], value)
    if isinstance(value, dict):
        return {k: resolve(v, last_scan) for k, v in value.items()}
    return value


def run_case(case):
    """Yield (step index, step, output) after running each step; the state is threaded through the steps."""
    state = copy.deepcopy(case["state"])
    tz = P.tzinfo(state.get("timezone"))
    last = None
    for i, step in enumerate(case["steps"]):
        now = P.parse_time(step["now"], tz)
        if step["op"] == "scan":
            out = P.scan(state, None, now, opening=step.get("opening", False))
            state = P.apply_commit(state, out["commit"], now)
            last = out
            yield i, step, out, state
        else:
            action = resolve(step["action"], last)
            try:
                state, result = P.ack(state, action, now)
                yield i, step, {"result": result, "action": action}, state
            except ValueError as e:
                yield i, step, {"error": str(e), "action": action}, state


class SharedCasesTest(unittest.TestCase):
    def test_every_trigger_has_a_firing_and_a_quiet_case(self) -> None:
        fires, quiet = set(), set()
        for case in CASES["cases"]:
            for step in case["steps"]:
                ex = step.get("expect", {})
                if step["op"] != "scan":
                    continue
                for t in ex.get("events_triggers", []):
                    fires.add(t)
                for k in ex.get("events", []):
                    fires.add(k.split(":")[0])
                if ex.get("events") == [] and ex.get("messages") == [] and case["id"].endswith("-no"):
                    quiet.add(case["id"])
        self.assertEqual(fires, set(P.TRIGGERS))
        prefixes = {"critical", "concordance", "diagnosis", "medication", "retest", "new-data", "change", "trend", "prediction",
                    "wearable", "experiment", "return", "checkin-gap", "review", "milestone", "life-event", "question"}
        self.assertEqual({p for p in prefixes if any(q.startswith(p) for q in quiet)}, prefixes)

    def test_policy_cases_present(self) -> None:
        ids = {c["id"] for c in CASES["cases"]}
        for need in ("policy-cap-day", "policy-cap-week", "policy-quiet-night", "policy-merge", "policy-cooldown",
                     "policy-mute", "policy-downshift", "policy-no-consent", "case-C", "ack-checkin", "ack-snooze"):
            self.assertIn(need, ids)

    def test_cases(self) -> None:
        for case in CASES["cases"]:
            for i, step, out, state in run_case(case):
                ex = step.get("expect", {})
                where = f"{case['id']} step {i}"
                with self.subTest(where):
                    if step["op"] == "scan":
                        self.check_scan(out, ex, where)
                    else:
                        self.check_ack(out, state, ex, where)

    def check_scan(self, out, ex, where) -> None:
        if "events" in ex:
            self.assertEqual([e["dedup_key"] for e in out["events"]], ex["events"], where)
        if "events_triggers" in ex:
            self.assertEqual([e["trigger"] for e in out["events"]], ex["events_triggers"], where)
        if "messages" in ex:
            self.assertEqual(len(out["messages"]), len(ex["messages"]), f"{where}: {[m['trigger'] for m in out['messages']]}")
            for got, want in zip(out["messages"], ex["messages"]):
                self.assertEqual({k: got.get(k) for k in want}, want, where)
        if "agenda" in ex:
            self.assertEqual([e["trigger"] for e in out["agenda"]], ex["agenda"], where)
        if "suppressed" in ex:
            self.assertEqual([{"trigger": s["trigger"], "reason": s["reason"]} for s in out["suppressed"]], ex["suppressed"], where)
        for k, v in ex.get("policy", {}).items():
            self.assertEqual(out["policy"][k], v, f"{where}: policy.{k}")
        # every draft the evaluator writes must pass its own lint
        events = {e["id"]: e for e in out["events"]}
        for m in out["messages"]:
            self.assertEqual(P.lint(m, events[m["event"]]), [], f"{where}: {m['trigger']} draft fails lint")

    def check_ack(self, out, state, ex, where) -> None:
        if ex.get("error"):
            self.assertIn("error", out, where)
            return
        self.assertNotIn("error", out, where)
        for k, v in ex.get("result", {}).items():
            self.assertEqual(out["result"].get(k), v, f"{where}: result.{k}")
        for path, v in ex.get("state", {}).items():
            self.assertEqual(get_path(state, path), v, f"{where}: state.{path}")

    def test_scan_is_deterministic(self) -> None:
        for case in CASES["cases"]:
            a = [o for _, _, o, _ in run_case(case)]
            b = [o for _, _, o, _ in run_case(case)]
            self.assertEqual(a, b, case["id"])

    def test_lint_cases(self) -> None:
        for c in CASES["lint_cases"]:
            errs = P.lint(c["message"], c["event"])
            self.assertEqual(not errs, c["expect"]["ok"], c["id"])
            self.assertEqual(sorted(e["code"] for e in errs), sorted(c["expect"]["codes"]), c["id"])

    def test_all_drafts_fit_the_limits(self) -> None:
        """Render every draft variant with long-ish placeholder values: titles ≤20, bodies ≤120, ≤3 buttons."""
        sample = {"marker": "低密度脂蛋白胆固醇", "metric": "静息心率", "drug_zh": "辛伐他汀", "commitment_zh": "工作日晚饭用限盐勺",
                  "event_zh": "女儿的婚礼", "intervention_zh": "减盐", "kind_zh": "化验结果", "reason_zh": "确认之前看到的缓慢变化是不是真的",
                  "label_zh": "统计模型估计", "picture_zh": "带孙子爬泰山", "conclusion_zh": "空腹血糖 5.6 mmol/L，符合空腹血糖受损",
                  "source_zh": "ADA 指南", "direction_zh": "上升", "value_text": "185/100 mmHg", "source_short_zh": "中国高血压防治指南（2018 年修订版）",
                  "n": 100, "cumulative": 100, "total_cumulative": 1000, "weeks_done": 12, "repeats_needed": 14, "post_done": 14,
                  "p_pct": 49, "p_low_pct": 30, "p_high_pct": 60, "change_pct_abs": 12.5, "window_days": 7, "days_outside": 7,
                  "kind_zh_": "", "experiment": "X1", "retest": "R1"}
        for t in P.RULES["triggers"]:
            for d in t["drafts"]:
                self.assertLessEqual(len(P.render(d["title_zh"], sample)), 20, (t["id"], d["title_zh"]))
                self.assertLessEqual(len(P.render(d["body_zh"], sample)), 120, (t["id"], d["body_zh"]))
                self.assertLessEqual(len(d["actions"]), 3, t["id"])
                for w in P.POLICY["forbidden_zh"]:
                    self.assertNotIn(w, d["body_zh"], t["id"])
        urgent = next(t for t in P.RULES["triggers"] if t["id"] == "critical_value")
        for d in urgent["drafts"]:
            self.assertTrue(d["body_zh"].startswith("建议你现在就拨打 120 或尽快就医"))


class RulesTest(unittest.TestCase):
    def test_seventeen_triggers_with_plan_categories(self) -> None:
        want = {"retest_due": "retest", "experiment_checkpoint": "coaching", "commitment_review": "coaching", "milestone": "coaching",
                "checkin_gap": "coaching", "return_welcome": "coaching", "life_event_followup": "care", "new_data_ready": "data",
                "change_beyond_noise": "data", "trend_beyond_noise": "data", "prediction_ready": "data", "wearable_shift": "data",
                "concordance_transition": "clinical", "diagnosis_hit": "clinical", "medication_gene_conflict": "clinical",
                "critical_value": "urgent", "question_due": "question"}
        self.assertEqual({t: v["category"] for t, v in P.TRIGGERS.items()}, want)
        self.assertFalse(P.TRIGGERS["wearable_shift"]["enabled_by_default"])
        self.assertFalse(P.TRIGGERS["question_due"]["enabled_by_default"])
        self.assertFalse(P.TRIGGERS["critical_value"]["user_can_disable"])
        for t in ("milestone", "checkin_gap", "experiment_checkpoint", "commitment_review"):
            self.assertEqual(P.TRIGGERS[t]["hosts"], ["standalone"], t)

    def test_critical_thresholds_carry_a_quoted_source(self) -> None:
        for r in P.RULES["critical_rules"]:
            src = r["source"]
            self.assertTrue(src["doi"] and src["pmcid"] and src["locator"], r["id"])
            for c in r["any"]:
                # the threshold number appears in the quoted guideline sentence
                self.assertIn(f"{c['value']:g}", src["quote"].replace("3.0", "3"), (r["id"], c))


@unittest.skipUnless(jsonschema, "jsonschema not installed")
class SchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.schemas = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in SCHEMA.glob("*.json")}
        reg = Registry()
        for name, s in cls.schemas.items():
            res = Resource.from_contents(s)
            reg = reg.with_resource(s["$id"], res).with_resource(name, res)
        cls.registry = reg

    def validate(self, name, obj) -> None:
        cls = jsonschema.validators.validator_for(self.schemas[name])
        cls.check_schema(self.schemas[name])
        cls(self.schemas[name], registry=self.registry, format_checker=cls.FORMAT_CHECKER).validate(obj)

    def test_rules_file(self) -> None:
        self.validate("pi-proactive.schema.json", P.RULES)

    def test_fixture_states_and_outputs(self) -> None:
        for case in CASES["cases"]:
            self.validate("pi-state.schema.json", case["state"])
            for _, step, out, state in run_case(case):
                self.validate("pi-state.schema.json", state)
                if step["op"] == "scan":
                    for e in out["events"] + out["agenda"]:
                        self.validate("pi-event.schema.json", e)
                    for m in out["messages"]:
                        self.validate("pi-message.schema.json", m)
                elif not step["expect"].get("error"):
                    self.validate("pi-action.schema.json", out["action"])

    def test_card_example(self) -> None:
        card = {"schema": "pi-card/1", "id": "C-trend-glucose", "kind": "trend", "title_zh": "空腹血糖：缓慢上升",
                "summary_zh": "过去三年，空腹血糖出现超出你个人正常波动的缓慢上升，下一次复查可以确认。",
                "numbers": [{"ref": "series.glucose.trend.annual_change_pct", "value": 6.4, "unit": "%/年", "label": "测量"}],
                "label": {"schema": "la-label/1", "basis_kind": "measurement", "label_zh": "测量"},
                "actions": [{"id": "a1", "label_zh": "去聊聊", "type": "open_chat"}], "deep_link": "longpi://cards/C-trend-glucose",
                "updated_at": "2026-09-30T10:00:00+08:00", "source": {"export": "la-export/2", "sha256": "0" * 64}}
        self.validate("pi-card.schema.json", card)
        bad = dict(card, kind="diagnosis")
        bad.pop("label")
        with self.assertRaises(jsonschema.ValidationError):
            self.validate("pi-card.schema.json", bad)

    def test_message_schema_rejects_long_and_unlabelled(self) -> None:
        case = next(c for c in CASES["lint_cases"] if c["id"] == "lint-draft-ok")
        self.validate("pi-message.schema.json", case["message"])
        with self.assertRaises(jsonschema.ValidationError):
            self.validate("pi-message.schema.json", dict(case["message"], status="suppressed"))
        with self.assertRaises(jsonschema.ValidationError):
            self.validate("pi-message.schema.json", dict(case["message"], body_zh="很" * 121))


class OpenApiTest(unittest.TestCase):
    def test_openapi_is_valid_3_1(self) -> None:
        try:
            import yaml
            from openapi_spec_validator import validate
        except ImportError:  # pragma: no cover
            self.skipTest("pyyaml / openapi-spec-validator not installed")
        spec = yaml.safe_load((SKILL / "api" / "openapi.yaml").read_text(encoding="utf-8"))
        self.assertEqual(spec["openapi"], "3.1.0")
        validate(spec, base_uri=(SKILL / "api" / "openapi.yaml").as_uri())
        paths = {(p, m) for p, ops in spec["paths"].items() for m in ops if m in ("get", "put", "post")}
        self.assertEqual(paths, {("/me/agenda", "get"), ("/me/inbox", "get"), ("/me/messages/{id}/actions", "post"),
                                 ("/me/cards", "get"), ("/me/timeline", "get"), ("/me/checkins", "post"),
                                 ("/me/measurements", "post"), ("/me/chat", "post"), ("/me/proactive-preferences", "get"),
                                 ("/me/proactive-preferences", "put"), ("/me/devices", "post")})


MEMBER = """# 老王

## 基本

- 年龄 / 出生年月：52
- 聊天节奏：大约每 7 天
- 主动提醒：教练 开　复测 开　数据 开　临床 开　关怀 关
- 免打扰：22:00–08:00　时区：Asia/Shanghai

## 为什么 & 想要的画面

- 七八十岁时想还能做的事：带孙子爬泰山

## 近期大事

- 2026-10-10 女儿的婚礼

## 小承诺

| 承诺 | 当…时 | 频率 | 开始 | 累计次数 | 状态 |
|---|---|---|---|---|---|
| 工作日晚饭用限盐勺 | 在家做晚饭时 | 每周 5 次 | 2026-07-20 | 19 | 进行中 |

复盘记录：

- 2026-10-09：4/5，在外吃饭一次

## 测量

| 日期 | 指标 | 数值 | 单位 | 来源 |
|---|---|---|---|---|
| 2026-10-12 | 血压 | 186/104 | mmHg | 家里血压计 |

## 个人实验

- 减盐看收缩压（X1，开始 2026-08-31，最短 6 周，后测 14 次，已测 0 次，方案项 I3）

## 上次对话

- 日期：2026-10-09
"""


class MemberFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.md = self.dir / "老王.md"
        self.md.write_text(MEMBER, encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.dir)

    def cli(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = P.main(list(argv))
        return code, json.loads(out.getvalue())

    def test_member_file_parses(self) -> None:
        st = P.member_state(self.md)
        self.assertEqual(st["chat_cadence_days"], 7)
        self.assertEqual(st["preferences"]["consent"], {"coaching": True, "retest": True, "data": True, "clinical": True, "care": False})
        self.assertEqual(st["preferences"]["quiet_hours"], {"start": "22:00", "end": "08:00"})
        self.assertEqual(st["picture_zh"], "带孙子爬泰山")
        self.assertEqual(st["commitments"][0]["cumulative"], 19)
        self.assertEqual(st["commitments"][0]["last_checkin_at"], "2026-10-09")
        self.assertEqual(st["measurements"][0]["values"], {"sbp": 186.0, "dbp": 104.0})
        self.assertEqual(st["experiments"][0]["min_weeks"], 6)
        self.assertEqual(st["experiments"][0]["marker"], "收缩压")
        self.assertEqual(st["life_events"][0]["label_zh"], "女儿的婚礼")

    def test_member_file_questions(self) -> None:
        md = self.dir / "小李.md"
        md.write_text("# 小李\n\n## 基本\n\n- 主动提醒：提问 开　数据 开\n- 免打扰：22:00–08:00　时区：Asia/Shanghai\n\n"
                      "## 为什么 & 想要的画面\n\n- 七八十岁时想还能做的事：自己开车去旅行\n\n"
                      "## 生活和偏好\n\n- 吸烟：从不\n- 家族病史：没有\n\n"
                      "## 测量\n\n| 日期 | 指标 | 数值 | 单位 | 来源 |\n|---|---|---|---|---|\n| 2026-10-01 | 腰围 | 84 | cm | 自测 |\n",
                      encoding="utf-8")
        st = P.member_state(md)
        self.assertEqual(st["preferences"]["enabled_triggers"], {"question_due": True})
        self.assertEqual(st["profile"], {"smoking": "never", "family_history_known": True})
        self.assertEqual(st["measurements"][0]["kind"], "waist")
        now = P.parse_time("2026-10-12T10:00:00+08:00", P.tzinfo("Asia/Shanghai"))
        out = P.scan(st, None, now)
        self.assertEqual([e["subject"]["question"] for e in out["events"]], ["q_alcohol"])  # known facts are not asked
        st = P.apply_commit(st, out["commit"], now)
        # answered in chat, without a message: recorded, and the next scan asks something else
        st, res = P.ack(st, {"type": "answer", "params": {"question": "q_alcohol", "answer": "none"}, "at": "2026-10-12T10:30:00+08:00",
                             "idempotency_key": "chat:q_alcohol:1"}, now)
        self.assertEqual((res["answer"], res["record"]), ("none", {"profile.alcohol": "none"}))
        later = P.parse_time("2026-10-13T10:00:00+08:00", P.tzinfo("Asia/Shanghai"))
        self.assertEqual([e["subject"]["question"] for e in P.scan(st, None, later)["events"]], ["q_sleep"])
        with self.assertRaises(ValueError):
            P.ack(st, {"type": "answer", "params": {"question": "q_alcohol", "answer": "daily"}, "idempotency_key": "x"}, later)

    def test_scan_and_ack_round_trip(self) -> None:
        code, out = self.cli("scan", "--member", str(self.md), "--now", "2026-10-12T10:00:00+08:00", "--write",
                             "--inbox", str(self.dir / "老王.inbox.json"))
        self.assertEqual(code, 0)
        trig = [m["trigger"] for m in out["messages"]]
        self.assertEqual(trig[0], "critical_value")  # urgent first, always sent
        self.assertIn("experiment_checkpoint", [e["trigger"] for e in out["agenda"]])
        care = [m for m in out["messages"] if m["trigger"] == "life_event_followup"]
        self.assertEqual([(m["status"], m["suppressed_reason"]) for m in care], [("suppressed", "no_consent")])  # care is off
        self.assertTrue((self.dir / "老王.proactive.json").is_file())
        box = json.loads((self.dir / "老王.inbox.json").read_text(encoding="utf-8"))
        self.assertTrue(all(m["status"] == "scheduled" for m in box["messages"]))
        # a second scan is silent: everything was recorded in the sidecar
        _, again = self.cli("scan", "--member", str(self.md), "--now", "2026-10-12T11:00:00+08:00")
        self.assertEqual(again["events"], [])
        # a check-in updates the count in the member file itself
        act = self.dir / "a.json"
        act.write_text(json.dumps({"schema": "pi-action/1", "message": out["messages"][0]["id"], "action": "x", "type": "checkin",
                                   "at": "2026-10-12T20:00:00+08:00", "params": {"commitment": "C1"}, "idempotency_key": "k1"}),
                       encoding="utf-8")
        code, res = self.cli("ack", "--member", str(self.md), "--action", str(act), "--write")
        self.assertEqual((code, res["cumulative"]), (0, 20))
        self.assertEqual(res["celebration_zh"], "第 20 次！离带孙子爬泰山又近了一步。")
        self.assertIn("| 20 |", self.md.read_text(encoding="utf-8"))
        code, res = self.cli("ack", "--member", str(self.md), "--action", str(act), "--write")
        self.assertTrue(res["duplicate"])
        self.assertEqual(res["cumulative"], 20)
        self.assertIn("| 20 |", self.md.read_text(encoding="utf-8"))

    def test_lint_cli(self) -> None:
        c = next(c for c in CASES["lint_cases"] if c["id"] == "lint-urgent-rewritten")
        (self.dir / "m.json").write_text(json.dumps(c["message"], ensure_ascii=False), encoding="utf-8")
        (self.dir / "e.json").write_text(json.dumps(c["event"], ensure_ascii=False), encoding="utf-8")
        code, out = self.cli("lint", "--message", str(self.dir / "m.json"), "--event", str(self.dir / "e.json"))
        self.assertEqual(code, 1)
        self.assertFalse(out["ok"])


class QuestionTextLintTest(unittest.TestCase):
    """Every question's own wording passes the text checks a drafted message must pass (a digit with no source
    once kept q_waist from ever being shown)."""

    def test_question_wording_passes_text_lint(self) -> None:
        bank = P.QUESTIONS.get("questions", P.QUESTIONS) if isinstance(P.QUESTIONS, dict) else P.QUESTIONS
        for q in bank:
            event = {"id": "e1", "category": "question", "trigger": "question_due", "subject": {}, "payload": {"question": q["id"]}}
            message = dict(P.draft_question(event), event="e1", category="question")
            codes = {e["code"] for e in P.lint(message, event)} - {"bad_answer"}
            self.assertEqual(codes, set(), q["id"])


if __name__ == "__main__":
    unittest.main()
