# UI ↔ backend contract

Status: **started in Phase 5 (T4)** for the result types the UI must handle. The full function list
(module paths, signatures, state ownership) is added in the video-prep phase.

## Result types a card run can return

`agent.pipeline.run_from_card(card, deps=None, staff=None, on_progress=None, fallback=True)`;
`generate_batch(...)` and `prepare_today(...)` return the same types per store.

| Type | When | What the UI shows |
|---|---|---|
| `RunResult` with `fallback=None` | passed all checks within 2 rewrites | the post (phone preview), copy button, 四、核验结果 fold |
| `RunResult` with `fallback="trimmed"` | still failing after 2 rewrites; the failing sentences were removed and **all checks re-ran and passed** | the post as normal, plus a small note 「已删去未通过核验的句子」 |
| `RunResult` with `fallback="next_card"` | the trimmed draft did not pass; the store's next unlocked card (潜力款 → 活动款 → 顾客问答 → 新品款 if verified) was generated once and **passed** | the post as normal; the card header must use `result.task.slot` / `result.task.card_id` (the card that was actually written), with a note 「今日一条未通过核验，已换成下一条推荐」 |
| `NeedsReview` | none of the above passed | 「需人工确认」 panel, see below. **Never** show a copy / publish button for it |
| `LockedResult` | the card is locked (新品资料待总部确认) | `result.message`; no generate button |
| `NeedsHuman` | KB facts conflict | `result.message` + the conflicts |
| `Exception` (batch / prepare only) | that store's run crashed | an error line for that store; the other stores are unaffected |

`RunResult.report.passed` is always `True` for a delivered post: an unchecked or failing post is never returned as a `RunResult` from a card run with `fallback=True`.

## `NeedsReview` (new in Phase 5)

`agent.schemas.NeedsReview`

| Field | Type | Meaning |
|---|---|---|
| `card` | `RecommendationCard` | the card that was asked for (the morning default card in `prepare_today`) |
| `draft` | `RunResult` | the best checked draft (fewest errors); its `post` must **not** be published |
| `failing` | `list[FailingSentence]` | each remaining error: `field` (title / intro / body[i] / cta), `sentence` (publishable text, no `[F#]`; empty if the error has no single sentence, e.g. a missing store detail), `stage` (8A–8D), `code`, `reason` (Chinese) |
| `message` | `str` | 「需人工确认：自动核验未通过，已列出未通过的句子和原因」 |
| `attempts` | `list[str]` | what was tried, e.g. `["S01-2026-10-23-potential", "trimmed", "S01-2026-10-23-promo"]` |

UI: show the draft text read-only with each `failing[i].sentence` highlighted and its `reason` next to it; offer 「重新生成」 (`run_from_card` live). In `prepare_today` records (`agent.runs.prepared_post`) the stored record has `status == "NeedsReview"` and `result` holds the fields above.

## Fallback counts

`scripts/prepare_today.py` and `scripts/eval_cards.py` print the status per store (`PASS (trimmed)`, `PASS (next_card)`, `NEEDS_REVIEW（需人工确认）`). The eval counts a pass only when no fallback was needed.
