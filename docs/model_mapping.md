# Demo model mapping (Phase 4, Task 1)

Status: **proposed and applied on `feat/proactive-phase4` for the demo run**. The data owner should confirm or adjust the choices; the mapping is data-only and reversible.

`why_*` cells are **references**, not values or quotes: they name the fact fields and the KB article path. This keeps KB text out of the repository (WORKFLOW v4 rule 11).

| Demo ID | Real catalog `model_id` | Canonical display name | Archetype | Demo role |
|---|---|---|---|---|
| `MODEL_A` | `matebook-14-harmonyos` | HUAWEI MateBook 14（鸿蒙版） | light_student | campus light/portable potential |
| `MODEL_B` | `matebook-pro-s` | HUAWEI MateBook Pro S | business | CBD business potential |
| `MODEL_C` | `matebook-gt-14` | HUAWEI MateBook GT 14 | creator_perf | creator/performance option |
| `MODEL_D` | `matebook-d-16-se-2024` | HUAWEI MateBook D 16 SE 版 2024 | family_allround | residential family potential |
| `MODEL_E` | `matebook-d-14-2024` | HUAWEI MateBook D 14 2024 | budget | budget option |
| `MODEL_F` | `matebook-14-2024` | HUAWEI MateBook 14 酷睿 Ultra | flagship_bestseller | national best-seller; never 潜力款 |
| `MODEL_N` | `matebook-fold-ultimate-design` | HUAWEI MateBook Fold 非凡大师 | new_release | “new release” demo; fact card starts `draft` |

## Why these models

- `matebook-14-harmonyos`: light student/portable fit, the natural S01 campus potential and S10 same-product different-angle card.
- `matebook-pro-s`: business/office fit; avoids the Pro CPU conflict recorded in `config/model_aliases.yaml`.
- `matebook-gt-14`: performance/OLED creator fit.
- `matebook-d-16-se-2024`: 16-inch family/value fit and has enough images for 小红书.
- `matebook-d-14-2024`: entry/budget fit with a full image set.
- `matebook-14-2024`: broad consumer appeal and the largest image set; demo best-seller.
- `matebook-fold-ultimate-design`: premium foldable form, real KB facts/images; the release status is demo-only.

## Applied files

- `data/demo/inputs/models.csv`: real IDs, canonical names, `why_*` references.
- `data/demo/inputs/promotions.json`: campaign model lists and demo price keys mapped to the real IDs.
- `scripts/gen_fake_data.py`: `PLANTED` and `STOCKOUT` keys.
- `tests/test_recommend.py`, `tests/test_price_traceability.py`: mapped IDs.
- `data/demo/templates/recommendation_card.example.json`: regenerated S01 default card.

## Confirmation needed

- Confirm the archetype mapping, especially `MODEL_F` (best-seller) and `MODEL_N` (new-release role).
- Confirm the demo prices in `promotions.json` (4999 / 6999) are plausible for the mapped models.
- If the data owner changes a mapping, update the same files and re-run `python scripts/gen_fake_data.py`.
