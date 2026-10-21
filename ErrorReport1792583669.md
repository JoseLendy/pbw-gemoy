# ErrorReport1792583669

- Repository: `T:\GithubRepo\pbw-gemoy`
- Branch: `feat/proactive-ui`
- Round: fourth pass — all UI-only items from `ErrorReport1792582675.md` plus a real backend run
- Date: 2026-10-21
- Full suite: **702 passed, 1 skipped**
- Live app: http://127.0.0.1:7861
- Evidence: `eval/ui_screens/10`–`25`

## Verdict

All UI-only errors identified in the prior reports are fixed and tested. **No remaining P0/P1 UI code
error was reproduced.** The live LLM key is funded again: a real S01 generation completed in 143.8s
and the backend checks returned `NeedsReview`; the UI correctly rendered the draft read-only with no
copy/publish controls. That remaining rejection is backend content quality, not a UI defect.

## Fixed in this round

- **Readability**: `ui/theme.py` + `app.py` CSS append; light page background, white card surfaces,
  stronger phone body text, dark captions, readable tables, card shadows.
- **Layout**: the store tab now has the workflow/talk/status/report/edit controls in the left column
  and the phone/preview/copy/publish/download controls in the right column. S04/S08/S10 captures show
  the higher-contrast card.
- **Manual tab reset**: `app.py` now has `on_manual_tab` and a reset-token state. HQ 重置演示 clears the
  pre-existing manual-flow session and outputs when the user returns to 手动输入.
- **Prepared headings**: a prepared `NeedsReview`/`NeedsHuman` record is now labelled
  「今日已为你准备好」; a prepared `next_card` adds the delivered slot to that heading.
- **Missing evidence**: captured S04 (`21`), S08 (`22`), S10 (`23`), locked new release (`24`) and a
  real backend run (`25`).
- **Docs**: corrected PR #5 status, cold-load timing, screenshot claims, handover-queue wording, tests
  list, and added the “original brief is superseded” note. Test count updated to 702.
- Earlier fixes remain: publish/copy gating, delivered-card identity, prepared/recovery rehydration,
  async image prefetch, role rule, HQ reset messages, new-release honesty, compare summary/threshold,
  save-image visibility, dynamic publish label.

## Verification

- `pytest -q`: **702 passed, 1 skipped**.
- Playwright 1920×1080: initial, S04/S08/S10, locked new release, generated result, published state,
  compare, HQ verify/reset, baseline, real NeedsReview. No console/page errors, no horizontal
  overflow, no `MODEL_`/`<…>`.
- Warm page load 439–462 ms; store switch 347–583 ms; first asset load ~1.7s.
- Store result: copy/publish/edit/download present only after a publishable result; publish button
  changes from 标记为已发布 to 已发布 ✓（已记录）.
- Real generation (S01, 143.8s): backend checks returned `NeedsReview`; UI showed the failure
  sentences and read-only draft, with no copy/publish controls.

## Remaining (not UI defects / data or backend owner)

### B-1 (backend content): real S01 run returns NeedsReview

The real run after 143.8s produced three 8A failures, including a 1.33 kg → 1.32 kg value conflict and
a product-fact sentence the ledger did not fully support. The UI handles it correctly. The writer /
check / fact-ledger owner must decide whether these are prompt/ledger issues; do not weaken the checks
in the UI.

### B-2 (data): real new-release fact card

`matebook-pro-s` still has no committed fact card; HQ shows honest `R1…R4` reference rows and says the
values are not verified. Needs the data owner.

### B-3 (data): demo date

Demo date 2026-10-23 vs generated logs ending 2026-10-20. The HQ window is labelled “截至最新记录”,
which is honest, but a consistent fixture or `DEMO_TODAY` is still needed for the final recording.

### B-4 (evidence): compare/baseline real content

`12` and `17` are still deterministic 7862 probe layouts. A real compare/baseline run can be captured
now that the key is funded; it may also return `NeedsReview` until B-1 is resolved.

### B-5 (optional): Stage 4

Staff picker, 绑定演示 and 发布效果 remain optional/unimplemented.

### B-6 (minor): compare product control after fallback

If a compare result falls back to another card, the column/meta names the delivered product, but the
global product dropdown still displays the requested product. This is explicit rather than silent;
a future fix can disable/switch the control.

## Fix prompt for the remaining work

```text
You are continuing `feat/proactive-ui` in T:\GithubRepo\pbw-gemoy after
ErrorReport1792583669.md. Read docs/UI_SPEC.md, docs/UI_BACKEND_CONTRACT.md,
docs/HANDOVER_UI.md and the ErrorReport files first.

SHARED-REPO RULES
- Do not merge PR #6, push to main, force-push, or commit .env/kb_snapshot.
- UI-only files: app.py, ui/, agent/ui_data.py, UI tests, data/demo/inputs/staff.csv. Backend files
  (agent/pipeline.py, agent/recommend/, agent/checks/, agent/style/, prompts/, scripts/) belong to the
  other workstreams.
- 7861 is the live instance; 7862 is a throwaway Playwright instance.

1. B-1: hand the real NeedsReview evidence to the writer/check/ledger owner. Reproduce with the S01
   default card, inspect the 8A failures, and fix the prompt/ledger/check source—not the UI checks.
   Re-run a real generation and capture a successful post if it passes.

2. B-2: obtain a sanitized demo fact card for matebook-pro-s; render its facts[] ids/fields/source
   titles/quotes instead of R rows, and make HQ verification use it.

3. B-3: make the demo date consistent (regenerate generated/ with --today 2026-10-23 or run with
   DEMO_TODAY=2026-10-21), then update HQ window, weekly plan and screenshots.

4. B-4: after B-1/B-3, rerun compare and baseline for real; replace probe screenshots only when the
   live output is correct.

5. B-6: if a compare result's task.card_id differs from the requested card, disable or switch the
   product dropdown and make the column heading name the delivered product.

6. B-5 only if time: Stage 4 in the spec's cut order.

ACCEPTANCE
- pytest green; Playwright 1920×1080 initial/generated/locked/compare/HQ/baseline; no console errors,
  no overflow, readable CJK, warm load/store switch <1s.
- No commit on main; PR #6 stays review-owned.
```
