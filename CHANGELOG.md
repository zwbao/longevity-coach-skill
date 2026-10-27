# Changelog

## 0.4.0 (2026-10)

Pi asks one useful question at a time, and every answer gets an immediate reply.

### Added
- `question_due` trigger and a `question` category (priority 35, off by default like `wearable_shift`): at most one
  question per scan, sharing the day and week caps with every other non-urgent message. Bank in `data/questions.json`
  (`pi-questions/1`): ten questions across four purposes (running experiment, data gap, profile, follow-up), each with
  why it is asked, skip conditions (`known_if`, `requires`), interval, at most three answer buttons and what each answer
  records (`sets`).
- Repetition rules (`proactive_policy.json` `questions`): never ask what the state knows; an unchanged answer doubles the
  interval (30 → 60 → 120 days, at most 180) and offers "和上次一样" as the first button; a question seen three times
  without an answer is retired; only a question's latest ask stays on the agenda.
- `ack` type `answer` (from a button or, without a message, from chat): records `history.answers`, applies `sets` and
  experiment counts, returns `feedback_zh` (experiment progress, data-gap effect from the host's `state.gaps`, or the
  next interval) and `record` for the host to store.
- `lint`: `question_no_answer`, `bad_answer`. Schemas, OpenAPI `ActionResult` and consent carry the new fields.
- Member file: `主动提醒` accepts 提问; 「生活和偏好」 has 吸烟 and 家族病史 lines and the 测量 table reads 腰围, so those
  questions are skipped once known.
- Shared cases: nine `question-*` cases in `proactive-cases/1` (86 cases), including the hand-off from a questionnaire that only said "does not smoke now". Eval `question-answer-feedback`.

### Changed
- Persona and product thesis: Pi recommends LongPi products without pushing (evidence first, at most three, zero
  allowed, disclosed as LongPi's own); published organ age estimates can be discussed as labelled ranges on the site.

## 0.3.0 (2026-10)

Closes the retest loop on the coach side and adds labelled judgements and proactive care.

### Added
- `noise.py trend`: slow drift over several dated values (adjacent pairs, first vs latest, weighted slope test with the
  published within-person variation as known noise). Passes the shared `trend-cases/1` used by longevity-analyst and LongPi.
- `noise.py predict`: probability that a change works for this person (statistical model: trial average effect,
  between-person spread `tau_pct` or its documented default, the person's own earlier experiments, adherence). Output is
  `la-prediction/1` with a `la-label/1` label "统计模型估计" and its assumptions. Passes the shared `prediction-cases/1`.
- `noise.py change` judges clock readouts (Horvath, Hannum) against technical-replicate noise when longevity-skills has
  `data/readout_noise.json` ("超出测量误差", which is not a biological change); without it, clocks stay unjudged.
- `scripts/exposures.py`: member file → `la-exposures/1` for the analyst's `twin build --exposures` (cumulative counts from
  the file, weekly counts only from review records that fit one week, never estimated).
- Member file: `方案项` column in 小承诺, a 「监测计划」 section, a line for consent to genetic results.
- Coaching wording: slow trends, concurrent interventions ("同期你在做", never causal), the four genetic–lab concordance
  classes and their transitions, "测一次就够", labelled predictions, diagnoses and medication suggestions; fixed
  wordings collected in SKILL.md 「讲变化的固定说法」.
- Standalone retest flow: exposures → `la.py twin build --exposures` → `la.py twin series`; reading `la-export/2`
  (`trends`, `concordance`, `surveillance`, `predictions`, `diagnoses`, `medications`, `retests[].judgeable`).
- Proactive care (scripts/proactive.py, schemas, api/openapi.yaml).
- `evals/`: conversation evals for `claude plugin eval` (`.claude-plugin/plugin.json` makes the repository a plugin).
- Product metric definitions in `references/product-thesis.md`.

### Changed
- Ground rule 2: diagnoses, medication suggestions (with doses) and "will it work" probabilities are given only as
  labelled items with their source and kind (guideline, CPIC, statistical model, AI judgement); AI judgements are named as
  such. Starting, stopping or changing a medicine goes on the doctor list. README Boundaries and persona follow.
- Emergencies: the first sentence is "建议你现在就拨打 120 或尽快就医。"
- Deep-analysis cost: read the analyst's preflight estimate; without one, give the full-analysis range and say the
  labs-only retest figure is still being calibrated.
- `hosts/longpi.md`: `read_deep_analysis` carries trends and concordance; note on the LongPi website host, which has its
  own rules and no check-ins.
