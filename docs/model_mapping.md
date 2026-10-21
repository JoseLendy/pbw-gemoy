# Demo model mapping

Status: Phase 4 mapping **applied**; Phase 5 proposals below are **pending confirmation** and not applied yet.

`why_*` cells and the references below are **references**, not values or quotes: they name fact fields, KB article paths or KB case IDs. This keeps KB text out of the repository (WORKFLOW v4 rule 11).

## Current mapping (Phase 4)

| Demo ID | Real catalog `model_id` | Canonical display name | Archetype | Demo role |
|---|---|---|---|---|
| `MODEL_A` | `matebook-14-harmonyos` | HUAWEI MateBook 14（鸿蒙版） | light_student | campus light/portable potential |
| `MODEL_B` | `matebook-pro-s` | HUAWEI MateBook Pro S | business | CBD business potential |
| `MODEL_C` | `matebook-gt-14` | HUAWEI MateBook GT 14 | creator_perf | creator/performance option |
| `MODEL_D` | `matebook-d-16-se-2024` | HUAWEI MateBook D 16 SE 版 2024 | family_allround | residential family potential |
| `MODEL_E` | `matebook-d-14-2024` | HUAWEI MateBook D 14 2024 | budget | budget option |
| `MODEL_F` | `matebook-14-2024` | HUAWEI MateBook 14 酷睿 Ultra | flagship_bestseller | national best-seller; never 潜力款 |
| `MODEL_N` | `matebook-fold-ultimate-design` | HUAWEI MateBook Fold 非凡大师 | new_release | “new release” demo; fact card starts `draft` |

## KB release order

Method (Phase 5, Task 1, real deps, `KB_BACKEND=hybrid`): loaded the real catalog, built the real bundle + ledger for every full catalog model, and searched every ledger fact for release/launch wording. Then read the dated launch records the KB keeps outside P1 (P6 case-study metadata: 原始页面日期 / published_at). Cost: 0 LLM calls, ~30 ima calls (hybrid `live_search` + `confirm`, cached afterwards).

**Key finding: no ledger fact for any model states a release or launch date.** P1 (产品事实 / 卖点与限制 / 型号检索卡 / 扩展产品目录) only states the fetch date. Release dates exist only in P6 case-study records, which the KB itself marks as research notes, not product facts. So under the Phase 5 truthfulness rule no public copy may say 新品 / 首发 / 新上市 for any model today.

Newest first, by the model's earliest dated release record in the KB:

| # | `model_id` | Release information as stated in the KB | KB reference |
|---|---|---|---|
| 1 | `matebook-pro-s` | 2026-08-05: listed among products “全新发布” at a 新品发布会. No earlier date in the KB. | P6-营销素材库/12-…/02-消费者业务官网发布会/MC-020 |
| 2 | `matebook-fold-ultimate-design` | **First** release 2025-05-19 (新品发布会; first-look, on-site and livestream records dated the same day; a media brief dated 2025-05-21). Also listed again among “全新发布” products at the 2026-08-05 event, plus a 2026-08-05 third-party unboxing. The KB does not say whether 2026-08-05 is a new SKU or a re-listing. | MC-029; P6 cases 10, 27, 42, 46; MC-020; case 26 |
| 3 | `matebook-14-harmonyos` | 2026-04-20: 上市报道 of MateBook 14 鸿蒙版; the same-day 新品发布会 lists “HUAWEI MateBook 14”. | P6 case 09; MC-022 |
| 4 | `matebook-pro-harmonyos` | 2025-05-19: 新品发布会 (with the Fold). | MC-029; P6 case 46 |
| 5 | `matebook-14-2024` | 2024-05-15: a 新品发布会 lists “HUAWEI MateBook 14” **without the variant**; matching it to the 酷睿 Ultra model is an inference from the date, not a KB statement. | MC-035 |
| – | `matebook-d-14-2024` | No release date in the KB (only “2024” in the product name). | — |
| – | `matebook-d-16-2024` | No release date in the KB (only “2024” in the product name). | — |
| – | `matebook-d-16-se-2024` | No release date in the KB (only “2024” in the product name). | — |
| – | `matebook-gt-14` | No release date in the KB. | — |
| – | `matebook-x-pro-ultra` | No release date in the KB (the KB’s 2020/2021 X Pro records are earlier generations). | — |

The 45 text-only catalog entries (擎云 commercial PCs, printers, monitors, accessories from P1/07) carry no release information.

## Phase 5 proposal 1 — MODEL_N (needs confirmation)

Problem: `matebook-fold-ultimate-design` first launched 2025-05-19 per the KB, so presenting it as the HQ “new release” would rest on a false premise.

**Proposal: `MODEL_N` = `matebook-pro-s`** (HUAWEI MateBook Pro S), the only catalog model whose earliest KB release record is the newest (2026-08-05).

Knock-on changes:
- `MODEL_B` (business) needs a new model. **Proposal: `matebook-x-pro-ultra`** (HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版): business/ultralight fit, 2 own images (朋友圈 needs 2). Rejected alternative: `matebook-pro-harmonyos`, because `config/model_aliases.yaml` marks its CPU `needs_human` (KB conflict), and a business post that cites the CPU stops with NeedsHuman.
- `matebook-fold-ultimate-design` leaves the demo set (it stays in the catalog; manual flow unaffected).
- The `launch_date` in `models.csv` stays a **demo scheduling date** (it places the 新品款 card in the ±30-day window). It is never a fact, never reaches the writer, and the card reason reads “总部新品推送（演示流程）” because the KB does not state that date (Task 2).
- Even with Pro S, public copy will not say 新品 / 首发: no ledger fact supports it (see the key finding above).

## Phase 5 proposal 2 — MODEL_A vs MODEL_F (needs a choice)

`MODEL_A` (`matebook-14-harmonyos`) and `MODEL_F` (`matebook-14-2024`) are both “MateBook 14”. They are already declared siblings in `config/model_aliases.yaml`, so 8A loads each one’s ledger when checking the other.

- **(a) Replace one** (e.g. `MODEL_F` → `matebook-d-16-2024`): no same-name pair on screen, but D 16 2024 has 2 KB images and is itself a sibling of `MODEL_D` (D 16 SE), so the confusion moves rather than disappears, and a 2-image best-seller is thin for 小红书.
- **(b) Keep both deliberately and add a “confusable model” demo case** (recommended): the sibling check is real, not staged, and the video gains a scene where a `MODEL_F` spec written under `MODEL_A` is blocked by 8A. The cost is two “MateBook 14” names on screen, so every surface must show the full canonical name (鸿蒙版 / 酷睿 Ultra).

## Files the confirmed mapping touches

- `data/demo/inputs/models.csv`: model rows, archetypes, `is_new_release` / `fact_card_status` / demo `launch_date`, `why_*` references.
- `data/demo/inputs/promotions.json`: campaign model lists and demo price keys.
- `scripts/gen_fake_data.py`: `PLANTED` and `STOCKOUT` keys.
- `tests/test_recommend.py`, `tests/test_runs.py`, other tests naming mapped IDs.
- `data/demo/generated/*` and `data/demo/templates/recommendation_card.example.json`: regenerated.
- Then `python scripts/gen_fake_data.py --today 2026-10-21` and `--today 2026-10-23` must print “All checks passed.”
