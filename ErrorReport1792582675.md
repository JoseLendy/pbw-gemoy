# ErrorReport1792582675

> **Status update 2026-10-21:** the live key is funded again. The 402 issue in this report no longer
> reproduces; a real S01 run returned `NeedsReview` after 143.8s. See
> `ErrorReport1792583669.md` for the current state. The data-dependent R-1/R-2 items remain.

- Repository: `T:\GithubRepo\pbw-gemoy`
- Branch: `feat/proactive-ui`
- Round: third pass, after fixing the UI-only items in `ErrorReport1792581313.md`
- Date: 2026-10-21
- Full suite: **701 passed, 1 skipped**
- Browser: Playwright at 1920×1080; live app on 7861; deterministic 7862 probe for generated screenshots
  (the live key still returns 402 Insufficient Balance)
- Screenshots: `eval/ui_screens/10`–`20`

## What was fixed in this round

### Readability / layout (the user-visible request)

- Added `ui/theme.py` and appended it after `static/phone.css` from `app.py`. No backend or
  `static/` edit.
- The page now has a soft #f3f6fa background; the recommendation, compare and baseline panels are
  white/off-white cards with borders and shadows instead of blending into the page.
- The phone mock has a darker frame, stronger shadow, 15.5px body text at #172033, darker captions
  and source lines, and a light top bar. Moment/WeChat/Xiaohongshu screens no longer render in
  low-contrast grey.
- The status strip is a white card with dark #334155 text.
- HQ tables use 14px text; compare metadata uses 14px dark text.
- The store tab's empty left column now holds a “店员今天怎么用” workflow card and the talk/status
  banners, so the phone preview is no longer floating in a blank page.
- Publish state is explicit: the button starts as 「标记为已发布」 and changes to
  「已发布 ✓（已记录）」 after the click (verified in Playwright).

### UI-only report items

- **R-3 prepared images**: background `prefetch_images()` + a 1.5s store-tab timer swap placeholders
  for real cached images without blocking `on_initial`/`on_store_change`. An image-fetch test asserts
  the cache warms; a page-load timing test asserts no synchronous fetch.
- **R-4 blank layout**: workflow/status moved into the left column and card surfaces added. Some
  whitespace remains below the short workflow on the initial screen, but the page is no longer an
  empty half.
- **R-5 fallback identity**: compare metadata and baseline meta now name the delivered product and
  say “已换成下一条推荐”; metadata reads `result.task.hook/angle`.
- **R-6 save image**: 保存图片 is now inside its own group and hidden when the current RunResult has
  no images; download remains available.
- **R-7 docs**: original brief is explicitly marked as superseded by the status notes for fact IDs,
  trimmed placement and 加上立减500.
- Also fixed: restore of a live result on store reload, stale store dropdown after reset, placeholder
  image-cache poisoning, double error prefix, hardcoded compare/baseline concurrency limit, and the
  published-note duplicate.

## Verification evidence

- `pytest -q`: **701 passed, 1 skipped**.
- Playwright: warm reload 462/439 ms (one transient 1287ms outlier), store switch 347–583 ms,
  no console/page errors, no horizontal overflow, no `MODEL_`/`<…>`.
- Store initial screen: no copy/publish/edit/download controls; after generate all appear; publish
  click changes the label correctly.
- HQ verify/reset: message cleared on reset; store cards re-fetch and unlock; compare/baseline
  placeholders return after reset.
- Live app: http://127.0.0.1:7861 (7862 probe stopped after screenshots).

## Remaining issues (not fixable with the UI-only data currently available)

### R-1 (P1 data/spec): no real new-release fact card

The repo still has only `data/demo/templates/fact_card.example.json`. The new-release panel now uses
honest `R1…R4` reference rows from `models.csv` and says the values are not verified. To satisfy the
spec's fact IDs/fields/source titles, the data owner must provide a sanitized demo fact card for
`matebook-pro-s`; `verify_new_product()` currently only flips an unlock flag.

### R-2 (P2 data): demo date vs HQ data

Demo date 2026-10-23; `publish_log.csv` ends 2026-10-20 and `summary.txt` is 2026-10-21. The UI now
labels the window “截至最新记录”, but the data should be regenerated with
`--today 2026-10-23` or the demo should run with `DEMO_TODAY=2026-10-21`. This needs the data owner.

### R-8 (external): real generated content still unverified

The live LLM key returns 402, so compare/baseline screenshots are from the deterministic probe, not
the real writer. The UI and fake paths are verified, but a funded key is required for the final video
and real-content QA.

### R-9 (optional): Stage 4

Staff picker, 绑定演示 and 发布效果 remain optional/unimplemented. The demo uses a fixed
`StaffContext(role="staff")`; no binding or engagement tab exists.

### R-10 (minor): compare/baseline global product control after fallback

If `generate()` returns `next_card`, the column/meta names the delivered product, but the compare
tab's product dropdown still shows the requested product. This is now explicit rather than silently
wrong; a future fix can disable the control or switch it to the delivered product.

## Fix prompt for the remaining work

```text
You are continuing `feat/proactive-ui` in T:\GithubRepo\pbw-gemoy after
ErrorReport1792582675.md. Read docs/UI_SPEC.md, docs/UI_BACKEND_CONTRACT.md,
docs/HANDOVER_UI.md and both ErrorReport files first.

SHARED-REPO RULES
- Do not merge PR #6, push to main, force-push, or commit .env/kb_snapshot.
- UI-only files: app.py, ui/, agent/ui_data.py, UI tests, data/demo/inputs/staff.csv. Backend files
  (agent/pipeline.py, agent/recommend/, agent/checks/, agent/style/, prompts/, scripts/) are owned by
  other workstreams; do not hand-edit them.
- 7861 is the live instance; 7862 is a throwaway Playwright instance. Use wait_until="load".

1. R-1: coordinate with the data owner for a sanitized demo fact card for matebook-pro-s.
   Add an adapter that reads facts[] ids/fields/source titles/quotes, render those rows, and make
   确认发布 require the card. Keep the current R-row panel as an explicit unverified fallback.
   Test that an R row is never labelled as a verified fact.

2. R-2: make the demo date consistent. Regenerate data/demo/generated with --today 2026-10-23, or
   run the demo with DEMO_TODAY=2026-10-21. Update HQ window, weekly plan, screenshots and docs.
   Run `python scripts/gen_fake_data.py --check-only` and full pytest.

3. R-10: when result.task.card_id differs from the requested card, make the compare product control
   and column heading explicitly show the delivered product (or disable the control for that run).
   Keep the baseline delivered-product note.

4. R-3 follow-up: verify the image-prefetch timer with a real prepared post containing images; if the
   source is slow, confirm the first paint stays under 1s and the timer fills images in afterwards.

5. R-8: fund/test the LLM key, then rerun the compare and baseline flows for real; replace the probe
   screenshots only after the live output looks right.

6. R-9 only if time: staff picker, binding tab, engagement preview, in the spec's cut order.

ACCEPTANCE
- pytest green; Playwright 1920×1080 initial/generated/locked/compare/HQ/baseline; no console errors,
  no overflow, readable CJK, warm load/store switch <1s.
- No new commit on main; PR #6 remains review-owned.
```
