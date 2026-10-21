# Demo data kit

Fake store data for the 复赛 demo (organizer approved fake data on Oct 21).
Full design and rules: `docs/PROACTIVE_AGENT_PLAN.md` §10.

## Run

```bash
python scripts/gen_fake_data.py                     # today=2026-10-21, seed=42
python scripts/gen_fake_data.py --today 2026-10-23  # date you record the video
```

Standard library only. Prints a sanity table and writes `generated/summary.txt`.
**If it prints `PROBLEMS:`, fix inputs or try another `--seed` before using the data.**

Optional real map data:

```bash
export AMAP_KEY=...                 # never commit
python scripts/fetch_poi.py S01     # test one store first
python scripts/fetch_poi.py         # then all
python scripts/gen_fake_data.py     # cached real POI now replaces fake fixtures
```

## Folders

| Folder | What | Edit by hand? |
|---|---|---|
| `inputs/` | Templates: stores, models, promos, calendar, configs | **Yes** |
| `inputs/poi_cache/` | Real Amap results (from `fetch_poi.py`) | No |
| `generated/` | Everything the app reads | **No** - regenerate |
| `templates/` | Example shapes of fact cards, POI cache, recommendation cards | Reference only |

## Before first real use (WS-A, ~30 min)

On `feat/proactive-phase4` the mapping is already applied (see `docs/model_mapping.md`):

1. `inputs/models.csv` uses real catalog IDs and canonical names.
2. `why_*` columns point at the KB article paths (no values or quotes in the repo).
3. The generator sanity table passes.

If the data owner changes a mapping, update `models.csv`, `promotions.json`, `PLANTED`/`STOCKOUT` in
`scripts/gen_fake_data.py`, then re-run the generator and the catalog guard test.

## Check a real-POI swap without writing files

Run the generator once, add the Amap cache, then:

```bash
python scripts/fetch_poi.py S01     # test one store first
python scripts/gen_fake_data.py --check-only
```

`--check-only` recomputes from `inputs/` (including `inputs/poi_cache/`) and the **existing**
`generated/` sales/logs, prints the sanity table, and writes nothing. It is safe to run repeatedly.

**Swap acceptance criteria**

- The sanity table still ends with `All checks passed.`
- Each store type still has one clear planted story (`S01`, `S04`, `S08`, `S10`).
- No `PROBLEMS:` line. If a real POI flips a store's dominant segment and breaks a planted story, either
  adjust `PLANTED` for that store or keep that store on its fixture.
- **Go/no-go: Thu 18:00.** If the table is not clean, keep fixtures for the recording; do not edit
  `generated/` by hand.

## Rules

- Product facts, specs and images are **never** generated here. They come from the ima KB via the fact ledger.
- Every row is `is_demo`. The UI shows a 模拟数据 badge on anything derived from it.
- Promo prices exist only in `inputs/promotions.json`. Copy may quote a price **only** if it matches an active promotion record exactly.
