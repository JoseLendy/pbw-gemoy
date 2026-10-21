# Phase 4 implementation report

Branch: `feat/proactive-phase4` · base: `feat/proactive-recommender` · implementation commit: `418fb60` (follow-up audit fixes are in the next commit).
Scope: `phase4.md` Tasks 1–6 and the final reporting gate. No `app.py` changes (Phase 3 owns the UI).

## Task status

| Task | Status | Notes |
|---|---|---|
| 1. Model mapping | **Code complete; confirmation pending** | Mapping applied and generated data clean; data owner must confirm archetypes/prices. |
| 2. Hardening | **Complete** | 8A auto-cite guard, 8B money breadth, 8C/8D dedupe; regression tests added. |
| 3. Peer-aware variety + 8E | **Complete (backend)** | Peer-aware hooks/angles, `generate_batch`, before/after similarity; UI tab must call it. |
| 4. Demo controls | **Backend complete; UI wiring pending** | `reset_demo_state`, run logs, `latest_run`; Phase 3 must call them and clear session state. |
| 5. Amap swap support | **Complete** | `--check-only` writes nothing; README has procedure/acceptance/go-no-go. |
| 6. Docs + freeze checklist | **Complete as documents** | v2.3 plan + checklist; checklist execution is a recording task. |
| Final gate | **Code/test/commit/push done; real recording gates open** | Real E2E eval/tuning, Amap decision, UI, data-owner confirmation remain. |

## Model mapping

| Demo | Real catalog model | Canonical name |
|---|---|---|
| `MODEL_A` | `matebook-14-harmonyos` | HUAWEI MateBook 14（鸿蒙版） |
| `MODEL_B` | `matebook-pro-s` | HUAWEI MateBook Pro S |
| `MODEL_C` | `matebook-gt-14` | HUAWEI MateBook GT 14 |
| `MODEL_D` | `matebook-d-16-se-2024` | HUAWEI MateBook D 16 SE 版 2024 |
| `MODEL_E` | `matebook-d-14-2024` | HUAWEI MateBook D 14 2024 |
| `MODEL_F` | `matebook-14-2024` | HUAWEI MateBook 14 酷睿 Ultra |
| `MODEL_N` | `matebook-fold-ultimate-design` | HUAWEI MateBook Fold 非凡大师 |

`why_*` columns contain fact-field references plus KB paths, never values or quotes. Demo prices: 4999 / 6999 / 5299, labelled 演示活动价 / source DEMO. See `docs/model_mapping.md`.

## Verification

```text
python -m pytest -q
487 passed, 1 skipped
```

The skip is `tests/test_e2e.py` (`RUN_E2E=1` not set); no real ima/LLM path was exercised.

```text
python scripts/gen_fake_data.py
All checks passed.

python scripts/gen_fake_data.py --today 2026-10-23
All checks passed.

python scripts/gen_fake_data.py --check-only
All checks passed.
check-only: no files were written.
```

`data/demo` is clean of `<` and `MODEL_`; the catalog guard now has a committed catalog fixture so it enforces on a clean checkout.

## 8A vs 8B money-pattern diff

Old 8A price rule (`config/claim_patterns.yaml`):
1. `[¥￥]\s*\d+(?:\.\d+)?`
2. `\d+(?:\.\d+)?\s*(元|块钱|万元|千元)`
3. Term list: 优惠, 补贴, 立减, 直降, 降价, 到手价, 特价, 折扣, 打折, N折, 满减, 买赠, 赠送, 赠品, 免费送, 低价, 仅售, 售价, 起售, 起价, 定价, 价格, 报价.

8B `MONEY_RE` covers 1 and 2 after the Phase 4 fix (including 万元/千元 normalization). 8B `TERM_RE` covers 3 plus 分期, 免息, 库存, 现货, 仅剩, 限量, 手慢无, 售罄 and Chinese-numeral discounts. It is at least as broad as the old 8A price rule; it is intentionally broader on mechanics.

## Peer-aware hooks/angles (seed 42, 2026-10-21)

| Group | Slot | Store → hook / angle |
|---|---|---|
| student | potential | S01 question / 全天续航; S03 checklist / 宿舍/图书馆场景 |
| student | promo | S01 myth / 手机平板电脑多设备协同; S02 checklist / 宿舍/图书馆场景; S03 scene / 上课携带 |
| student | new_release | S01 checklist / 宿舍/图书馆场景; S02 scene / 上课携带; S03 question / 全天续航 |
| office | potential | S04 question / 多任务处理 |
| office | promo | S04 myth / 文档效率; S05 checklist / 数据安全; S06 scene / 会议与差旅 |
| office | new_release | S04 checklist / 数据安全; S05 scene / 会议与差旅; S06 question / 多任务处理 |
| family | potential | S08 myth / 旧电脑资料迁移 |
| family | promo | S07 myth / 旧电脑资料迁移; S08 checklist / 长期耐用; S09 scene / 上手简单 |
| family | new_release | S07 checklist / 长期耐用; S08 scene / 上手简单; S09 question / 全家共用 |
| shopper | potential | S10 question / 到店体验理由 |
| shopper | promo | S10 myth / 送礼怎么选; S11 checklist / 到店体验理由; S12 scene / 送礼怎么选 |
| shopper | new_release | S10 checklist / 到店体验理由; S11 scene / 送礼怎么选; S12 question / 到店体验理由 |

All `customer_question` cards use the reserved `customer` hook and the logged question as their angle.

## 8E before/after (`--fake` eval)

Examples from `python scripts/eval_cards.py --fake --today 2026-10-21`:

| Pair | Before | After |
|---|---|---|
| S02 × S03 (student) | 0.851 | 0.468 |
| S07 × S08 (family) | 0.872 | 0.435 |
| S01 × S03 (student) | 0.463 | 0.514 |

All remaining pairs are below the 0.55 threshold. The full table is in `eval/report.md` (gitignored). A fake eval is still a rehearsal; the real before/after requires `RUN_E2E=1`.

## Backend API the Phase 3 UI must call/handle

```text
agent.recommend.store_data:
  load_store_data(); cards_for(store_id, today, data=None); default_card(...)
  set_fact_card_status(model_id, "draft"|"verified"); fact_card_overrides(); reset_demo_state()

agent.pipeline:
  run_from_card(card, deps=None, staff=None, on_progress=None)
      -> RunResult | LockedResult | NeedsHuman
  generate_batch(cards, deps=None, staff_map=None, on_progress=None)
      -> BatchResult(results, similarity, regenerated)
  generate_baseline(card, deps=None, llm=None) -> BaselineResult | LockedResult
  edit(prev, instruction, deps=None, on_progress=None)
      -> RunResult | Clarification | NeedsHuman | EditBlocked

agent.runs:
  latest_run(card_id, runs_dir=None) -> dict | None
  RUNS_DIR
```

UI must handle `LockedResult`, `NeedsHuman`, `EditBlocked`, `BaselineResult` (always show 对照组), `BatchResult.similarity`, `latest_run(...)["timestamp"]`, and must clear its own session 已发布 / question state on retake.

## Remaining blockers

1. **Phase 3 UI is absent.** `app.py` has no 门店端 / 三店对比 / 总部端 tabs and does not call the proactive API. This is the largest recording blocker and is outside Phase 4 file ownership.
2. **Real eval/tuning not run.** `RUN_E2E=1 python scripts/eval_cards.py --today 2026-10-23` must tune `WRITER_TEMPERATURE` until ≥10/12 stores pass within 2 rewrites; record the value in `.env.example`.
3. **Amap decision not made.** Choose real POI + `--check-only` verification, or explicitly keep fixtures by Thu 18:00.
4. **Data-owner confirmation** of the model mapping and demo prices is still pending.
5. **Freeze checklist is 0/35 executed.** It is a recording-run checklist, not a code defect.
6. **Edit scenes do not write a `runs/` record.** Phase 4 requires logs for `run_from_card`/`generate_batch`/`generate_baseline`; quick edits are not in that list. If the video requires an edit log, add `kind="edit"` separately.
