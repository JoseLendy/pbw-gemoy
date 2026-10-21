# ErrorReport1792581313

- Repository: `T:\GithubRepo\pbw-gemoy`
- Branch: `feat/proactive-ui`
- Round: second QA pass after fixing `ErrorReport1792578570.md`
- Audited: 2026-10-21
- Verification: `pytest -q` → **700 passed, 1 skipped**; Playwright at 1920×1080; live app on 7861
- Test instance: 7862 with deterministic fake generation for screenshot paths; the live key still
  returns 402 Insufficient Balance

## Verdict

The P1 state/identity defects from the first report are fixed and covered by regression tests. No
remaining **P0** and no remaining P1 **code** defect was reproduced in the tested flows. The remaining
issues are one data-contract gap (new-release fact card), one demo-data date inconsistency, and
polish/visual items. The app, queue, Stage 1–3 tabs and reset flow are usable.

## Fixed in this round

| # | Fix | Evidence |
|---|---|---|
| 1 | Copy/publish/download/edit are gated on a publishable, passed `RunResult` | `tests/test_ui_contract_fixes.py::test_publish_is_ignored_before_a_result_and_for_needs_review`; initial page has no copy/publish/edit/download; after generate all appear |
| 2 | `fallback=next_card` uses the delivered card in store, prepared, compare and baseline | prepared/live next_card tests; store header shows 活动款, not 今日一条 |
| 3 | Prepared/recovery `RunResult` rehydrates into phone + talk card + four-section report | rehydrated all 31 JSON records in `runs/2026-10-23`: 23 RunResults render; NeedsReview/batch return None safely |
| 4 | Failed `重新生成` is visible with an existing result and offers recovery | test asserts recovery group visible and friendly 402 message |
| 5 | Role rule is live via a default demo `StaffContext(role="staff")` | Monday card shows 由店长发布 and hides generate; Friday 朋友圈 flow unchanged |
| 6 | 8E regenerated metadata uses `result.task.hook/angle` | forced 8E test: S02 metadata follows `myth` / 多设备协同 |
| 7 | Baseline shows the fallback note and delivered product | `test_baseline_renders_fallback_note` + delivered name in meta |
| 8 | HQ reset clears the verify message and compare/baseline outputs | verify returns reset_msg="" ; reset returns verify_msg=""; tab select restores placeholders; store dropdown updates |
| 9 | New-release panel stops claiming invented facts were verified | uses `R1…R4` references and says “未核验具体数值” |
| 10 | Compare summary counts failures, threshold is read from the backend, scenario labels expanded | `3/4 店完成（1 店失败）`, threshold from `ui_data.similarity_threshold()` |
| 11 | Placeholders no longer poison the image cache; local store switches do not fetch live images | `test_image_placeholder_is_not_cached_as_a_real_image`; `test_local_store_switch_does_not_fetch_live_result_images` |
| 12 | Duplicate demo date removed; no-result/locked/NeedsReview published label hidden | initial/after-reset screenshots |
| 13 | Prepared `NeedsHuman` shows message + conflicts; baseline NeedsReview shows its draft; malformed records show a note | regression tests |
| 14 | Double error prefix removed; compare/baseline concurrency limit uses `UI_GENERATION_CONCURRENCY`; cleared store dropdown is guarded | code review + build |

Playwright after the fixes:
- warm reload **452/399 ms**, store switch **451 ms**
- no console/page errors, no horizontal overflow, no `MODEL_`/`<…>` on screen
- initial store tab has no copy/publish/edit/download controls; after a generated result they are visible

## Remaining issues

### R-1 (P1 data/spec gap, requires data owner): new-release review has no real fact card

`docs/UI_SPEC.md:104` asks for the draft's fact IDs, field names and source titles. The repository has
only `data/demo/templates/fact_card.example.json` (illustrative); there is no fact card for
`matebook-pro-s`. `agent/ui_data.py` now derives **reference** rows from `models.csv` and labels them
`R1…R4`; `ui/hq_tab.py` explicitly says the values were not verified. That is honest, but the underlying
“one verification, thousands of accurate posts” demo still lacks a real fact-level artifact.
`verify_new_product()` only flips `fact_card_status`.

**Fix:** with the data owner, add a sanitized demo fact card (e.g. `data/demo/inputs/fact_cards/
matebook-pro-s.json`) with real `facts[]` ids/fields/source titles/quotes (no secret KB text), expose it
through `agent/ui_data.py`, render those rows, and make `确认发布` require them. This is outside the
UI-only file set and must be coordinated, not hand-written.

### R-2 (P2 data): demo date vs HQ posting window

The demo date is 2026-10-23, while `publish_log.csv` ends 2026-10-20 and `summary.txt` says
`today=2026-10-21`. The label now says “截至最新记录”, so it is no longer misleading, but the demo
still has three days of missing HQ data.

**Fix options:** regenerate `data/demo/generated` with
`python scripts/gen_fake_data.py --today 2026-10-23`, or set `DEMO_TODAY=2026-10-21` for the whole demo
(including the weekly plan). Do not mix dates. Re-run `--check-only` and the full suite after either.

### R-3 (P2): prepared/recovery images are placeholders on first page load

The page-load path correctly avoids network fetches (`allow_fetch=False`), but a prepared RunResult's
product images are SVG placeholders until a later live render. The spec's “ready when you open” screen
is text-accurate but visually incomplete. Add asynchronous hydration (prefetch bytes in a background
thread and update the phone HTML) or a local cache warmed by `prepare_today`, without blocking the
local event.

### R-4 (P2 visual): store tab has a large empty left column

`ui/store_tab.py` still creates an empty `gr.Column(scale=1)` beside the phone. At 1920×1080 the
initial screen and the post-generation view show ~40% blank space on the left (`eval/ui_screens/10`,
`16`, `19`). Use that column for the talk card / “为什么推这条” / next actions, or make the phone span
the row.

### R-5 (P2): compare/baseline next_card identity is only partial

The note now names the delivered product, and metadata uses `result.task`, but the compare tab's global
product control and each store heading still describe the requested product/platform. If the delivered
card differs, make the column heading explicitly say “已换成下一条推荐：<display>” and hide the copy
of the requested product; or disable comparison for a fallback result. Baseline already says the original
card was replaced and names the delivered product.

### R-6 (P3): 保存图片 is visible for a RunResult with no images

`ui/store_tab.py` shows the file group for every live RunResult, but `on_save_image` returns `None` when
`post.images` is empty. Hide the save-image button when there is no image (keep download).

### R-7 (P3/docs): original UI_SPEC brief still has pre-fix wording

The status notes now explain the corrections, but the quoted brief still says “fact IDs” (`:104`),
“trimmed only in 四” (`:78`), and “to show the price block” (`:80`). A reader who skims only the brief can
be misled. Add a “superseded by status note” marker inline or move the corrected text into the status
block; do not silently rewrite the original brief.

### R-8 (environment/evidence): real generated content is still unverified

The live key returns 402, so the compare/baseline screenshots are from the deterministic 7862 fake
probe, not the real writer. The UI claims are code/test-verified, but a non-zero balance is required
before recording the final demo and before claiming the real post visuals. Keep the probe label.

### R-9 (optional, expected): Stage 4

Staff picker, 绑定演示 and 发布效果 remain unimplemented. They are optional by `UI_SPEC.md:128-134`;
the demo currently uses a fixed `StaffContext(role="staff")` and no binding/engagement tab.

## Fix prompt for the remaining issues

```text
You are continuing `feat/proactive-ui` in T:\GithubRepo\pbw-gemoy after
ErrorReport1792581313.md. Read docs/UI_SPEC.md, docs/UI_BACKEND_CONTRACT.md,
docs/HANDOVER_UI.md, and both ErrorReport files first.

SHARED-REPO RULES
- Do not merge PR #6, do not push to main, never force-push, never commit .env or kb_snapshot/.
- UI-only files: app.py, ui/, agent/ui_data.py, UI tests, data/demo/inputs/staff.csv. Backend files
  (agent/pipeline.py, agent/recommend/, agent/checks/, agent/style/, prompts/, scripts/) must not be
  edited by this workstream.
- Port 7861 is the live instance; 7862 is the throwaway Playwright instance. Use wait_until="load".

TASKS

1. R-1 new-release fact card (coordinate with the data owner; do not fake it)
   - Ask for a sanitized demo fact card with facts[] ids/fields/source titles/quotes for matebook-pro-s.
   - Add an adapter that returns those rows; render ids/fields/sources in the HQ panel.
   - Make 确认发布 require the fact card and keep the explicit “not verified” note for any reference-only
     fallback. Add a test that an R-row is never labelled as a verified fact.

2. R-2 date consistency
   - Choose one as-of date: regenerate generated/ with --today 2026-10-23, or run the demo with
     DEMO_TODAY=2026-10-21. Do not leave the HQ window three days behind the header.
   - Update UI_SPEC/HANDOVER and screenshot timestamps; run --check-only and full pytest.

3. R-3 async prepared images
   - Prefetch prepared/recovery image bytes in a background thread or warm a cache in prepare_today.
   - Never block on_initial/on_store_change; when bytes arrive, update the phone HTML. Add a timing
     test that a 0.4s image fetch does not delay the local load handler.

4. R-4 store layout
   - Remove the empty left column or move the talk/reason panel into it. Verify 1920x1080 with a
     screenshot of initial, generated and locked states.

5. R-5 compare/baseline fallback identity
   - When result.task.card_id differs from the requested card, change the column heading/meta to
     “已换成下一条推荐：<delivered display name>” and do not show the requested product as the
     generated product. Add a forced-fallback test.

6. R-6 save-image visibility
   - Hide 保存图片 when the current RunResult has no images; keep 下载 .md. Add a test.

7. R-7 docs
   - Mark the original brief lines as superseded inline (fact IDs, trimmed, plus500). Keep the status
     notes as the source of truth. Update counts and screenshot provenance.

8. Regression gate
   - `python -m pytest -q` green.
   - Playwright 1920x1080: initial/generated/locked/reset/compare/HQ/baseline, console clean, no overflow,
     no MODEL_/<…>, warm load/store switch <1s.
   - Re-run the ErrorReport loop if a new failing behavior is found; do not merge PR #6 yourself.
```
