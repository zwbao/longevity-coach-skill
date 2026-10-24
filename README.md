# longevity-coach-skill

Pi is a longevity coach for AI agents that load Agent Skills (Cursor, Claude Code and others). Pi keeps a long-term
relationship with one person: it remembers their goals and life in a plain markdown file on this computer, turns
findings into small commitments the person chooses, praises every concrete step, and says honestly whether a change
is real or still within that person's normal variation. Pi speaks Chinese.

Pi runs on its own in any agent that loads skills, or inside [LongPi](https://github.com/zwbao/dsh-plugin-longpi), the
DeepSeek Harness plugin, where LongPi keeps the records, the health page and the reminders and Pi does the talking.
The coaching method is the same in both; only where the member file lives and which tools run the analyses differ.

Pi does not compute biomarkers itself. It works through two other skills, and the person only ever talks to Pi:

- **[longevity-skills](https://github.com/zwbao/longevity-skills)** (required): published methods, the evidence
  store, and the tables of within-person biological variation and trial-average effects.
- **[longevity-analyst-skill](https://github.com/zwbao/longevity-analyst-skill)** (optional): turns a folder of raw
  test data (WGS, methylation, gut metagenome, proteomics, lab reports) into a multi-omics report, an organ checkup
  table, a digital twin and an intervention plan. Without it, Pi uses the method library only.

## Install

Clone the repositories side by side; Pi finds the other two by itself.

```bash
git clone https://github.com/zwbao/longevity-coach-skill
git clone https://github.com/zwbao/longevity-skills
git clone https://github.com/zwbao/longevity-analyst-skill   # optional, see its README for dependencies
```

Link the skills into your agent's skills folder, for example for Cursor:

```bash
ln -s "$PWD/longevity-coach-skill/skills/longevity-coach" ~/.cursor/skills/longevity-coach
ln -s "$PWD/longevity-analyst-skill/skills/longevity-analyst" ~/.cursor/skills/longevity-analyst
```

If longevity-skills lives somewhere else, set `LONGEVITY_SKILLS_HOME` to its folder. Pi needs Python 3 and nothing
else.

## Use

Start a conversation, for example 我想活得健康点, 帮我看看这份体检单 or 减盐对我的血压有没有用. On the first meeting Pi
asks why this matters now and what the person wants to still be able to do at 70 or 80, then creates their member
file at `~/.longevity-coach/<name>.md`. Pi reads that file at the start of every conversation and updates it at the
end. The person can open, edit or delete it at any time.

## What is inside

All files are under `skills/longevity-coach/`.

| File | Content |
|---|---|
| `SKILL.md` | Entry point: who Pi is, which host it runs in, the member file, how a conversation runs, deep analysis, the three ground rules |
| `persona.md`, `examples.md` | Pi's character, how it gives positive feedback, sample conversations |
| `references/coaching.md` | First meeting, review, explaining results, personal experiments, welcoming someone back |
| `references/product-thesis.md` | What traditional health products got right and wrong, and the design that follows |
| `templates/member.md` | What the member file holds |
| `hosts/standalone.md` | Running on its own: the member file on disk, calling the analyst and the method library, `noise.py` |
| `hosts/longpi.md` | Running inside LongPi: LongPi's memory and tools; deep analysis only through `run_deep_analysis` |
| `scripts/noise.py` | Whether a change or a slow trend exceeds normal variation, whether one person could see an intervention's effect, and the probability that it works for them (statistical model) |
| `scripts/exposures.py` | Turns the member file's commitments and review records into `la-exposures/1` for the analyst's twin |
| `evals/` | Conversation evals for `claude plugin eval` |

`noise.py` uses the reference change value from published within-person biological variation, the same calculation
as the analyst's `twin compare`:

```bash
python3 skills/longevity-coach/scripts/noise.py change --marker 收缩压 --before 138 141 135 --after 131 129 128 --gap-days 30
python3 skills/longevity-coach/scripts/noise.py plan --marker 收缩压 --intervention 减盐 --baseline 138 --unit mmHg --repeats 14
python3 skills/longevity-coach/scripts/noise.py trend --marker 空腹血糖 --series 2023-09-01:4.6 2024-09-03:5.0 2025-09-02:5.3 2026-09-01:5.6
python3 skills/longevity-coach/scripts/noise.py predict --marker 收缩压 --intervention 减盐 --baseline 138 --unit mmHg --repeats 14
python3 skills/longevity-coach/scripts/noise.py markers
python3 skills/longevity-coach/scripts/exposures.py --member ~/.longevity-coach/老王.md --export la-export.json --out exposures.json
```

## Tests

```bash
python3 -m pytest -q tests
```

The noise tests need longevity-skills cloned beside this repository. With longevity-analyst-skill there too, they also
check that both compute the same reference change value, and run the shared cases in
`longevity-analyst-skill/tests/fixtures/`: `rcv_cases.json`, `trend_cases.json` and `prediction_cases.json` (or the files
`LONGEVITY_RCV_CASES`, `LONGEVITY_TREND_CASES`, `LONGEVITY_PREDICTION_CASES` name). The exposures test validates its
output against the analyst's `la-exposures-1.schema.json` (needs `jsonschema`).

Conversation evals live in `evals/` (one directory per case: `prompt.md`, `case.yaml`, `graders/`) and run with
`claude plugin eval .` from the repository root (`.claude-plugin/plugin.json` makes the repository a plugin).

## Boundaries

Pi is an AI coach, not a doctor. Diagnostic conclusions, medication suggestions (including doses) and "will this work
for me" probabilities reach the person only as labelled items: each says where it comes from and what kind of judgement
it is (measurement, published model, a named guideline's criteria or recommendation, CPIC, statistical model estimate,
or AI judgement). AI judgements are always called AI judgements, and a dose that no source prints is labelled as one.
Starting, stopping, switching or adjusting a medicine is something to confirm with a doctor, and Pi puts it on the
list of questions for the doctor. In an emergency the first thing Pi says is to call 120. Where a host has stricter
rules (LongPi), the host's rules win.

## License

[MIT](LICENSE)
