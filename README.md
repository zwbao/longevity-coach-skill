# longevity-coach-skill

Pi is a longevity coach for AI agents that load Agent Skills (Cursor, Claude Code and others). Pi keeps a long-term
relationship with one person: it remembers their goals and life in a plain markdown file on this computer, turns
findings into small commitments the person chooses, praises every concrete step, and says honestly whether a change
is real or still within that person's normal variation. Pi speaks Chinese.

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
| `SKILL.md` | Entry point: who Pi is, the member file, how a conversation runs, the three ground rules |
| `persona.md`, `examples.md` | Pi's character, how it gives positive feedback, sample conversations |
| `references/coaching.md` | First meeting, review, explaining results, personal experiments, welcoming someone back |
| `references/backstage.md` | How Pi calls the analyst, the method library and the evidence store |
| `references/product-thesis.md` | What traditional health products got right and wrong, and the design that follows |
| `templates/member.md` | The member file template |
| `scripts/noise.py` | Whether a change exceeds normal variation, and whether one person could see an intervention's effect |

`noise.py` uses the reference change value from published within-person biological variation, the same calculation
as the analyst's `twin compare`:

```bash
python3 skills/longevity-coach/scripts/noise.py change --marker 收缩压 --before 138 141 135 --after 131 129 128 --gap-days 30
python3 skills/longevity-coach/scripts/noise.py plan --marker 收缩压 --intervention 减盐 --baseline 138 --unit mmHg --repeats 14
python3 skills/longevity-coach/scripts/noise.py markers
```

## Tests

```bash
python3 tests/test_noise.py
```

The tests need longevity-skills cloned beside this repository. With longevity-analyst-skill there too, they also
check that both compute the same reference change value.

## Boundaries

Pi is an AI coach, not a doctor. It does not diagnose, prescribe, set a dose or advise stopping a medicine; it helps
the person prepare questions for their doctor instead. In an emergency it tells them to call 120 first. Biological
ages and risks are model estimates, and Pi says so.

## License

[MIT](LICENSE)
