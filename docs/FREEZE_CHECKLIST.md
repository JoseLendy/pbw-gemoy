# Freeze checklist — 复赛 video

Deadline: **Fri Oct 23, 17:00**. Record Friday morning; submit by ~15:00 with a 2-hour buffer.
This is the Phase 4 freeze gate. Tick every item before recording.

## Data and model mapping

- [ ] `data/demo/inputs/models.csv` uses real catalog IDs and canonical names; no `<` or `MODEL_` remains.
- [ ] `why_*` cells are **references** (fact fields + KB article path), never values or quotes.
- [ ] `promotions.json` uses the mapped model IDs; demo prices are labelled 演示活动价 / source DEMO.
- [ ] `PLANTED` and `STOCKOUT` in `scripts/gen_fake_data.py` use the mapped IDs.
- [ ] `python scripts/gen_fake_data.py --today 2026-10-23` prints `All checks passed.`
- [ ] The catalog guard passes: `pytest -q tests/test_catalog_guard.py` (not skipped).
- [ ] `grep -R "<" data/demo` and `grep -R "MODEL_" data/demo` return nothing (templates included).

## Tests and quality

- [ ] `python -m pytest -q` green.
- [ ] 8A auto-cite never adds a tag to a sentence with an unsupported number.
- [ ] 8B money patterns cover the old 8A price rule; non-matching / different-model / unrecorded mechanic claims fail.
- [ ] 8C/8D duplicate style hits are one line with both checker IDs, including in 四、核验结果.
- [ ] 8E peer-aware hooks/angles are distinct inside each peer group where the pool allows.
- [ ] `RUN_E2E=1 python scripts/eval_cards.py --today 2026-10-23` — tune `WRITER_TEMPERATURE` until
      ≥10/12 stores pass within 2 rewrites; record the final value in `.env.example` comments.
- [ ] Similarity before/after is visible in the eval report; no pair above threshold after regeneration
      (or the remaining pair is explicitly noted).

## Amap / POI

- [ ] Real POI swapped and verified **or** explicitly skipped. Decision/time: __________________.
- [ ] `python scripts/gen_fake_data.py --check-only` still ends with `All checks passed.`
- [ ] Go/no-go at Thu 18:00. If not clean, keep fixtures for the recording.

## Demo controls

- [ ] `reset_demo_state()` is called between takes; the app session’s 已发布 / question state is cleared.
- [ ] Real runs write `runs/<date>/<timestamp>-<store>-<slot>.json`; `latest_run(card_id)` works.
- [ ] `runs/` is gitignored; no run log or KB text is committed.
- [ ] `phase4.md` is not committed to the wrong branch.

## Video scenes

Dry-run each scene once and list the exact store/card/input:

## Video scenes

Dry-run each scene once and list the exact store/card/input:

| Scene | Exact demo input |
|---|---|
| S01 default | Store `S01` 紫金港店; date `2026-10-23`; slot `potential`; platform `公众号`; open → “为什么推这条” → preview → copy → 已发布. |
| 三店对比 | Stores `S01` / `S04` / `S08` / `S02`; date `2026-10-23`; fixed platform `公众号`; S01 vs S02 are the same model, S04/S08 are their own models. |
| Wrong-number edit | S01 card; edit “把续航写成 15 小时”; expect 8A fail + rewrite, no false auto-cite. |
| Price block | S01 or S02 card; edit “加上立减500”; expect 8B block before the writer. |
| Baseline | S01 default card; `generate_baseline`; label 对照组. |
| New product | `matebook-pro-s`; fact card draft → HQ verifies → every store’s 今日一条 becomes the new release. |
| HQ panels | 12-store posting table, questions, weekly plan; 模拟 badges visible. |

- [ ] S01 default card: open → “为什么推这条” → preview → copy → 已发布.
- [ ] 三店对比: S01 / S04 / S08 / S02 with a fixed platform; S01 vs S02 are the same model.
- [ ] Planted wrong-number edit: 8A fails and rewrites; no false auto-cite.
- [ ] “加上立减500” edit: 8B blocks before the writer.
- [ ] Baseline vs ours: `generate_baseline` clearly labelled 对照组.
- [ ] New product: `matebook-pro-s` draft → HQ verifies → every store’s 今日一条 becomes the new release.
- [ ] HQ panels: posting rate, questions, weekly plan.

## Screen and submission

- [ ] No API key, Client ID, ima KB ID, or `.env` content visible.
- [ ] 模拟数据 / 演示活动 / 对照组 labels visible where required.
- [ ] No 开发占位 text, no `MODEL_*`, no `<...>` on screen.
- [ ] Recording resolution and browser zoom fixed; one continuous run plus the required scenario/platform switches.
- [ ] `runs/` log present for every recorded scene.
- [ ] GitHub + ModelScope + 说明书 links accessible; 说明书 has ≥3 results / ≥2 scenarios / ≥2 platforms.
- [ ] Submit by 15:00 Friday (2-hour buffer).
