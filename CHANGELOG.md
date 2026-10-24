# Changelog

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
