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

1. In `inputs/models.csv`, replace `<...从catalog填写>` with real catalog names, and keep or rename the `MODEL_*` IDs to match `agent/catalog.py`.
2. Fill the `why_*` columns with the KB fact behind each affinity score.
3. Re-run and check the sanity table.

## Rules

- Product facts, specs and images are **never** generated here. They come from the ima KB via the fact ledger.
- Every row is `is_demo`. The UI shows a 模拟数据 badge on anything derived from it.
- Promo prices exist only in `inputs/promotions.json`. Copy may quote a price **only** if it matches an active promotion record exactly.
