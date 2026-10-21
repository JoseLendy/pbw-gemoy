# ErrorReport1792578570

- Repository: `T:\GithubRepo\pbw-gemoy`
- Branch: `feat/proactive-ui`
- Commit audited: `3f5b05d` (`Status bar: show local KB mirror as available, not disconnected`)
- Audited: 2026-10-21
- Scope: `docs/UI_SPEC.md`, `docs/UI_BACKEND_CONTRACT.md`, Stage 1–3 UI, `agent/ui_data.py`, UI tests, demo data
- PR: #6 (`feat/proactive-ui` → `feat/proactive-recommender`), open, not merged
- Method: independent @Explore read-only audit + in-process reproductions + Playwright at 1920×1080 + full pytest

## Verdict

The app builds, all five tabs render, and there is **no P0 startup blocker**. The queue fix, Stage 2 tabs and Stage 3 tab are usable at 1920×1080. However, Stage 1 has several state/identity defects that are visible in normal use, and the “new product verified” panel overstates what was actually verified. **Do not call Stage 1–3 fully DONE before these P1 items are fixed.**

Full suite: **682 passed, 1 skipped** (`pytest -q`, with the GitHub Desktop bundled `git` on `PATH` because `test_freeze_check.py` calls `git`). Passing tests do not cover the findings below.

## P1 — fix before demo / merge

### P1-1. `已发布` can be set before any result, on locked cards, and on `NeedsReview`; copy remains available for `NeedsReview`

**Spec** (`UI_SPEC.md:77-78`): RunResult gets copy/save/download/已发布; `NeedsReview` gets no copy button. `UI_BACKEND_CONTRACT.md:62` forbids copy **and** publish for `NeedsReview`.

**Evidence** (`ui/store_tab.py`):
- `on_publish()` at `:303-307` writes `session["published"][cid] = True` with no result/type check.
- The publish button is always created at `:386`; only the generate button is hidden (`:139`).
- `pub = gr.Textbox(..., buttons=["copy"])` at `:377` always exposes a copy control.
- `NeedsReview` sets `pub_text=""` at `:178-182`, but the copy box and publish button stay active.

**Repro**
```
1 publish_before_result: {'S01-2026-10-23-potential': True} label= 标记为已发布
3 needs_review pub_text: '' publish_label: 标记为已发布
  publish_before: {'S01-2026-10-23-potential': True}
```
A locked card is also markable as published. Impact: the demo can claim a post was published without a delivered post, and an unreviewed draft can be published.

**Fix direction:** introduce one `publishable = isinstance(result, RunResult)` gate (a `RunResult` includes `fallback=next_card`, which passed checks). Wrap the copy/publish controls in a `gr.Group` and show it only when `publishable`; clear `published[cid]` whenever a new generation starts for that card. Hide/disable edit/download/save/publish for locked/NeedsReview/NeedsHuman.

### P1-2. `fallback="next_card"` renders the post under the wrong card header, platform and reasons

**Spec** (`UI_SPEC.md:78`): show the fallback note; `UI_BACKEND_CONTRACT.md:56` requires using `task.slot` / `task.card_id` for the header.

**Evidence** (`ui/store_tab.py:117-193`): `_render()` builds the panel from `card` (the requested card) and only appends the actual slot to the note at `:164-166`. It never uses `result.task.card_id`, the actual display name, platform or reasons.

**Repro**
```
2 next_card panel: 今日一条 HUAWEI MateBook 14（鸿蒙版） · 朋友圈 ...
  next_card status: ℹ️ 今日一条未通过核验，已换成下一条推荐（活动款）
```
The note says the promo card was used, while the header still says 今日一条/潜力款 and the original product. Impact: the user copies a post whose visible identity does not match the generated content.

**Fix direction:** resolve the actual card from `result.task.card_id` in `session["cards"]`; use its slot/display/platform/reasons. If the actual card is not in the session, build the header from `result.task.slot` and show a clear “已采用下一条推荐” label. Apply the same rule to compare and baseline.

### P1-3. Prepared posts and recovery results are not rendered as full results

**Spec** (`UI_SPEC.md:72,77`): prepared post appears under 今日已为你准备好 and a RunResult shows the phone preview + four sections; the same result behavior applies.

**Evidence** (`ui/store_tab.py`):
- A prepared payload goes into `status_box` (`:158`), not the phone column. `phone_out` stays empty; `talk_out` and `report_md` stay `""`.
- `prepared_post_html` (`ui/components.py:299-313`) builds a generic phone from the raw post dict; no platform skin, no talk card, no four-section report.
- `last_real_run_html` uses the same simplified path (`components.py:329-334`).

**Repro**
```
4 prepared phone_out has hw-phone: False status has hw-phone: True report empty: True talk empty: True
```
Impact: the morning “ready when you open” screen lacks the four-section output the demo promises, and the phone appears in the wrong column.

**Fix direction:** put prepared/recovery content in the phone column. Either reconstruct a read-only display from the stored `result` including its `report`/ledger fields, or explicitly render “该记录未保存四段式报告” rather than silently dropping it. Do not pass real images through a blocking fetch on page load (see P2-3); render a placeholder/cache and hydrate asynchronously.

### P1-4. A failed `重新生成` is silent when a previous result exists; the last-real-run offer is unreachable

**Spec** (`UI_SPEC.md:79`): on generation failure, offer 显示最近一次真实运行结果 with its timestamp; never present the old result as fresh.

**Evidence** (`ui/store_tab.py:145-147`): `recovery_on` requires `cid not in results`. After the first successful result, `cid` is always in `results`, so the recovery group is hidden and `recovery_msg` is empty; `:149-160` keeps showing the old phone unchanged.

**Repro**
```
5 regen_failure recovery_visible: {'__type__': 'update', 'visible': False} recovery_msg: '' old phone still shown: True
```
Impact: a 402/timeout/ima failure during a re-generation looks like a successful no-op. This is especially risky on the demo laptop with the known 402 key.

**Fix direction:** show the recovery/error banner whenever `session["recovery"]` matches the current card, even if an old result exists. Keep the old result visibly labelled “上次结果”, and offer 显示最近一次真实运行结果 with its timestamp. Clear the recovery state on the next successful run.

### P1-5. The Stage 1 role rule is dead code

**Spec** (`UI_SPEC.md:75`): 朋友圈 actionable by everyone; 公众号/小红书 show 「由店长发布」 for staff role (view only).

**Evidence** (`ui/store_tab.py:67`): `role_notice(card, None)` is the only UI call. `can_act()` (`ui/components.py:53-61`) treats `staff=None` as actionable for every platform, so `role_notice` always returns `None`; no `StaffContext` is constructed anywhere in `ui/`, and `ui_data.generate(card)` is called without a staff argument (`store_tab.py:246`). Generate visibility only checks `card.locked`.

**Repro**
```
6 role card: 公众号 notice: None panel has 店长: False
```
(That card is visible with `DEMO_TODAY=2026-10-19`; the default Friday date happens to use 朋友圈 everywhere, hiding the bug from the camera.)

**Fix direction:** without the optional Staff picker, use an explicit demo `StaffContext(role="staff")` (or a clear demo role selector). Pass it to `can_act`/`role_notice` and `ui_data.generate`; show 「由店长发布」 and hide/disable generation/edits for 小红书/公众号. Add a test using a Monday card.

### P1-6. 三店对比 shows the pre-8E hook/angle for regenerated stores

**Spec** (`UI_SPEC.md:100`): under each phone show store, segment, scenario, voice, landmark, hook; mark regenerated stores.

**Evidence:** `generate_batch` replaces the card and result after 8E (`agent/pipeline.py:537-562`). `ui/compare_tab.py:51-66` receives only the original `card` and reads `card.hook` / `card.angle`; the updated hook/angle live in `result.task.hook` / `result.task.angle`.

**Repro**
```
regenerated ['S02']
S02 orig hook/angle question 全天续航
result task hook/angle myth 手机平板电脑多设备协同
```
The UI still shows 问题开头 / 全天续航 for a store whose post was rewritten to a myth hook / multi-device angle. Impact: on camera the “regenerated” badge and the metadata contradict each other.

**Fix direction:** use `result.task.hook` / `result.task.angle` (and `result.task.slot`) for the per-store metadata when the result is a `RunResult`; keep store/segment/landmark from the original card. Add a regression that forces 8E and asserts the displayed hook/angle equals `result.task`.

### P1-7. 对照组 claims “同一张卡” even when `generate()` falls back

**Spec** (`UI_SPEC.md:121`): right is our result for the same card. Contract: baseline is never our result, and fallback result identity must use the actual task.

**Evidence** (`ui/baseline_tab.py:81-100`): `on_baseline` writes “同一张卡” before generation; `ours_html()` (`:62-78`) never calls `fallback_note()`. If `generate()` returns `fallback="next_card"`, the right phone is the next card but the meta still claims the original card; `trimmed` is not mentioned.

**Fix direction:** pass `fallback_note(result)` and the actual task slot/card into `ours_html`; if `next_card`, change the meta to “原卡未通过核验，已换成下一条推荐” and use the actual card identity. Do not claim same-card comparison after fallback.

### P1-8. `重置演示` leaves the HQ “已确认发布” message on screen

**Spec** (`UI_SPEC.md:104`): reset clears all UI session state; contract §3 assigns reset state to the UI.

**Evidence** (`ui/hq_tab.py`): `on_verify()` returns four outputs including `verify_msg` (`:133-140`); `on_reset()` returns seven outputs `[posting, release, verify, reset_msg, questions, plan, distribution]` (`:143-148`) and does not include `verify_msg`, so the green “已确认发布…” banner survives. Compare/baseline results also have no reset hook; the store tab only clears when selected (`ui/store_tab.py:210-222`).

**Repro**
```
10 verify tuple len/message: 4 True
   reset tuple len: 7 includes verify_msg? False
```
Impact: after reset the new-release panel says 待总部确认 while a green banner says it was published.

**Fix direction:** include `verify_msg` in the reset outputs and clear it; clear compare/baseline outputs on reset via the existing `reset_token`; keep prepared posts untouched. Add an end-to-end reset test that checks every visible panel, not only backend state.

### P1-9. HQ “最近 14 天” is not anchored to the demo date

**Spec** (`UI_SPEC.md:63,103`): demo date is 2026-10-23; posting rate is a 14-day rate.

**Evidence** (`agent/ui_data.py:179-193`): `publish_stats` takes the last 14 distinct dates in `publish_log.csv`, not the 14 days ending at `today()`. The fixture runs 2026-10-07 … 2026-10-20, so the UI says “最近 14 天（2026-10-07 至 2026-10-20）” while the header says 演示日期 2026-10-23 and the weekly plan highlights 10-23. `data/demo/generated/summary.txt` says `today=2026-10-21`.

**Repro**
```
7 hq window: ['2026-10-07', '2026-10-20'] demo today: 2026-10-23
```
Impact: a judge checking date consistency sees the HQ data ending three days before “today”. This is partly a data-fixture issue and partly a label issue.

**Fix direction:** either regenerate the demo data with `--today 2026-10-23`, or compute the window ending at `today()` and explicitly label it “截至 2026-10-20（最新记录日）”. Add a test that the window end equals either `today()` or the latest record date, and that the label matches.

### P1-10. New-release “fact IDs” and “verified” wording are fabricated/overstated

**Spec** (`UI_SPEC.md:104`): the draft panel should show its fact IDs, field names and source titles; 确认发布 should run `verify_new_product(model_id)`.

**Evidence** (`agent/ui_data.py:244-267`): `new_release_drafts()` makes `F1..F4` from the four `why_*` cells in `models.csv`; no real fact-card file exists for `matebook-pro-s` (only `data/demo/templates/fact_card.example.json`, which is illustrative). `ui/hq_tab.py:64-66` says “总部已确认：字段与资料来源已核验” after `verify_new_product()` — but that function only flips an in-memory `fact_card_status` flag (`agent/ui_data.py:152-155`); no fact value was reviewed.

**Repro**
```
9 new-release refs: [('F1','重量/屏幕/电池','产品事实.md'), ('F2','安全/接口/续航','卖点与限制.md'), ...]
  real fact-card file exists: False
```
Impact: the demo's core “new products are accurate” story is weakened exactly where the judges look. The panel is also using `launch_date` from `models.csv` (a demo scheduling date, not a KB fact).

**Fix direction:** do not invent fact IDs. Either (a) have the data owner add a sanitized demo fact-card JSON for the new model with real `facts[]` IDs/fields/source titles (no KB values needed for the demo), or (b) relabel the panel as “字段与来源参考（演示，未核验）” and remove the “已核验/确认发布” claim from the fact card. Keep `verify_new_product` as the unlock action, but state that it only unlocks the demo fact card. Add a test that the panel never labels invented rows as verified facts.

## P2 — polish / consistency

### P2-1. Compare summary, threshold and scenario labels are not driven by data
- `ui/compare_tab.py:116-117` always says “4 店完成” even when `BatchResult.results` contains an `Exception` for a store; the per-store panel shows the error but the summary contradicts it. Repro with one exception: `8 compare exception summary: 4 店完成 · 总耗时 1.0s · 8E 重写 0 店（无）`.
- `:80,:84` hardcode “8E：阈值 0.550”; the actual threshold is `SIMILARITY_THRESHOLD` in `agent/style/similarity.py`. If the env changes, the table header is wrong. Confirmed with a similarity pair: the body contains `0.550` regardless.
- `:24-29` maps only four scenario keys; other valid keys (e.g. `family_upgrade`, `store_visit`, `back_to_school`) fall back to raw English keys. Add a fallback label map or show a Chinese label.
- `:89-113` returns a blank panel before the first run; spec does not require a placeholder, but the 1920 screenshot has a large empty area. Add a short empty-state explanation.
- `:126-131` only offers products in an active campaign; this is contract-driven (`product_card` requires it) but UI_SPEC says “one product” without the restriction. Document it or show the restriction in the control.

### P2-2. Prepared `NeedsHuman`/`Locked` payloads lose their message
`ui/components.py:272-283` only distinguishes `NeedsReview` from “generic”. A prepared `NeedsHuman` payload with `message`/`conflicts` renders an empty generic phone:
```
<div class="hw-phone"><div class="screen"><h2></h2><div class="p"></div><div class="cta"></div></div></div>
```
The contract says `NeedsHuman` shows `message` + conflicts and no post. Handle all statuses explicitly in `prepared_payload_view`/`prepared_post_html`.

### P2-3. Prepared images can synchronously fetch over the network on page load/store switch
`ui/store_tab.py:158` passes `ui_data.DEPS` into `prepared_post_html`; `components.py:286-296` calls `image_data_uri` → `fetch_image_bytes` for each image. With a 0.4s fake fetch, `_load_store` + `_render` took **0.4s** and the page-load event is local-only (`store_tab.py:415`). In real deps this is `agent.retrieval.fetch_image_bytes`, which may hit ima. This undermines the queue-bypass fix. Render cached/placeholder images and hydrate asynchronously; add a timing regression for prepared posts with images.

### P2-4. Action buttons are active where they cannot work
`ui/store_tab.py:379-386` always shows 短一点/换卖点/换个角度/加上立减500/下载/保存图片/已发布. For locked cards they produce “请先生成一条内容”; for `NeedsReview`, `_do_edit()` (`:265-284`) calls `ui_data.edit(prev)`, and `agent/pipeline.py:794-800` expects `prev.task`, so the user can see `生成失败：'NeedsReview' object has no attribute 'task'`. Hide/disable these controls unless a publishable `RunResult` is shown, or make `_do_edit` handle `NeedsReview` by offering 重新生成 only.

### P2-5. Duplicate demo date and sparse Stage 1 layout
`app.py:339` and `ui/store_tab.py:354` both render 「演示日期」, so it appears twice at 1920. The default screen has an empty left half next to the phone placeholder; screenshots `10/18` show the gap. Remove the duplicate and either put the phone placeholder in the main preview area or use the left half for “为什么推这条”/next actions.

### P2-6. Compare screenshot evidence is from a probe, not the real backend
`eval/ui_screens/12-compare-result.png` shows three cross-segment similarity pairs and S02 regenerated with unchanged metadata. Current `generate_batch` groups by segment, and the four cards are student/office/family/student; a real run yields only the S01↔S02 pair. The screenshot was produced by the temporary deterministic 7862 probe (because the real key has 402 Insufficient Balance); it does not prove the current backend behavior. Keep it as a layout probe, or label it “模拟生成结果，非真实 LLM 运行” in the handover; do not cite it as a real backend screenshot.

### P2-7. `UI_SPEC.md` has stale/contradictory status markers
- `UI_SPEC.md:255` says “then Stage 2: Status PENDING … before Stage 2 was started”, while `:110` says Stage 2 DONE and `compare_tab.py`/`hq_tab.py` exist.
- `:55` says “only `binding_tab.py` is PENDING”; Stage 4 also requires the staff picker and 发布效果 panel (`:130-132`), neither exists.
- `:78` says `trimmed` is “mentioned only in 四、核验结果”; `:88-89` says it is also shown alongside the post. `agent/formatter.py` has no fallback text, so the first claim is false and the implementation follows the contract note instead.
- `:80` calls 「加上立减500」 “to show the price block”, but the backend intentionally blocks it (`PROACTIVE_AGENT_PLAN.md` §4.3 and `FREEZE_CHECKLIST.md`); the current behavior is correct, the spec parenthetical is misleading.
- Stage 1 DONE (`:85-93`) does not mention P1-1/P1-3/P1-5; Stage 3 DONE (`:126`) says “both run on the same card/model/platform”, false under fallback.

### P2-8. Customer-question reason can overstate “近7天”
This is backend/display data, not `ui/*.py`: `agent/recommend/slots.py:84-88` counts every `customer_questions.json` row without a date filter, while `agent/recommend/explain.py:73` displays “本店近7天顾客问… {count} 次”. Questions run 10-14…10-20 and the demo date is 10-23; some counts include older rows. Either filter by date or change the copy to “近期/累计”. Flag to the data owner; do not fix by changing UI text alone.

## UI_SPEC / documentation errors summary

1. Stage 2 “PENDING” at `UI_SPEC.md:255` conflicts with Stage 2 DONE at `:110`.
2. “Only binding_tab.py PENDING” at `:56` understates Stage 4 (staff picker + 发布效果 missing).
3. `trimmed` placement contradicts itself (`:78` vs `:88-89`) and the formatter does not add it to 四.
4. Stage 1/3 DONE claims are stronger than the actual behavior (P1-1/P1-3/P1-5/P1-7).
5. Stage 2 screenshot evidence (`:115-117`) is from a deterministic probe and contains non-reproducible similarity pairs; label it.
6. `eval/ui_screens` / HANDOVER text says browser verification was not completed (`HANDOVER_UI.md:168-171`) while `UI_SPEC.md:201-208` says it was; the handover is stale.
7. 「加上立减500」 description (“show the price block”) contradicts the intended 8B block.
8. Stage 2 product control is restricted to active campaigns; UI_SPEC only says “one product”.

## Fix prompt (copy-paste for the next coding agent)

```text
You are fixing the Stage 1–3 UI on branch `feat/proactive-ui` in T:\GithubRepo\pbw-gemoy.
Read first: CLAUDE.md, docs/WORKFLOW.md, docs/UI_SPEC.md, docs/UI_BACKEND_CONTRACT.md,
docs/HANDOVER_UI.md, and ErrorReport1792578570.md.

SHARED-REPO RULES
- Only edit app.py, ui/, agent/ui_data.py, UI tests, and data/demo/inputs/staff.csv. Never edit
  agent/pipeline.py, agent/recommend/, agent/checks/, agent/style/, prompts/, scripts/, or other
  backend code.
- Do not merge PR #6. Do not push to main. Never force-push. Never commit .env or kb_snapshot/.
- Keep the app on port 7861 for the live instance; use 7862 for automated/Playwright tests.
- Keep the queue fix intact: generation events use the shared "generation" pool; page load/store
  switch stay concurrency_limit=None and must not fetch images/network synchronously.
- Add regression tests for every behavior change; run the full pytest suite; run Playwright at
  1920x1080 with wait_until="load" (never networkidle).

FIX IN THIS ORDER

1. Result state gate (P1-1)
   - Define publishable = isinstance(result, RunResult) for the currently displayed result.
   - Wrap copy/publish in a gr.Group visible only when publishable; for NeedsReview, NeedsHuman,
     Locked and no-result states hide copy and publish. If the Gradio Textbox copy button cannot
     be hidden dynamically, replace it with a separate copy button inside the same group.
   - Clear session["published"][card_id] when a new generation starts for that card.
   - Disable/hide short/point/angle/price/download/save for non-publishable states.
   - Tests: publish before generate is ignored; NeedsReview/locked cannot be marked published.

2. Actual result identity (P1-2, P1-6, P1-7)
   - Add a helper that resolves the delivered card from result.task.card_id/slot in session cards.
   - Store tab: for fallback="next_card", render the actual card's slot/display/platform/reasons,
     or a clear "已采用下一条推荐" header if the card is unavailable.
   - Compare tab: use result.task.hook/angle for the per-store metadata when available; keep
     store/segment/landmark from the original card. Verify the displayed hook/angle equals
     result.task after a forced 8E regeneration.
   - Baseline tab: pass fallback_note(result) and actual task identity into ours_html; never say
     "同一张卡" after next_card fallback.
   - Tests: synthesize a RunResult with fallback="next_card" and assert the header/card identity;
     force 8E with fakes and assert S02 metadata matches result.task.

3. Prepared/recovery result rendering (P1-3, P2-2, P2-3)
   - Put prepared/recovery content in the phone column, not status_box.
   - Render a platform-skinned phone from the stored payload; if the payload has no report, show an
     explicit "该记录未保存四段式报告" note instead of silently rendering an empty generic phone.
   - Handle NeedsHuman and Locked explicitly (message + conflicts, no post/publish).
   - Do not call fetch_image_bytes synchronously from on_initial/on_store_change. Use cached/local
     bytes or a placeholder, hydrate images asynchronously, and keep page load <1s.
   - Add a timing test with a prepared payload containing an image and a 0.4s fetch, asserting the
     local load handler does not block.

4. Failed re-generation (P1-4)
   - Show session["recovery"] whenever it matches the current card, even if a previous result
     exists. Label the old result "上次结果"; offer 显示最近一次真实运行结果 with its timestamp.
   - Clear recovery on the next successful run. Add a test with a stored result + raising generate().

5. Role rule (P1-5)
   - Until the optional staff picker exists, use an explicit demo StaffContext(role="staff") (or a
     clearly labelled demo role selector). Pass it to can_act/role_notice and ui_data.generate.
   - For 小红书/公众号 staff cards show 「由店长发布」 and hide/disable generation and edits.
   - Test with a Monday card (DEMO_TODAY=2026-10-19) so the rule is visible.

6. HQ reset (P1-8)
   - Include verify_msg in on_reset outputs and clear it.
   - Clear compare/baseline outputs when ui_data.reset_token() changes.
   - Keep prepared posts intact. Add an end-to-end reset test covering every visible panel.

7. HQ date window (P1-9)
   - Either regenerate the demo data with `python scripts/gen_fake_data.py --today 2026-10-23`
     (coordinate with the data owner), or compute the post window ending at today() and label it
     explicitly with the latest record date. Add a test that the displayed window is consistent.

8. New-release panel (P1-10)
   - Do not invent F1-F4 from models.csv. Either add a sanitized demo fact-card JSON with real
     facts[] IDs/fields/source titles (data-owner approval; no KB values), or relabel the panel as
     "字段与来源参考（演示，未核验）" and remove the "已核验" wording.
   - clarify that verify_new_product only flips the demo unlock status; it does not verify values.
   - Add a test that the panel does not present invented rows as verified facts.

9. Compare polish (P2-1)
   - Count actual RunResults in the summary; don't say "4 店完成" when a store returned an Exception.
   - Get the 8E threshold from a ui_data adapter (or env) instead of hardcoding 0.550.
   - Add Chinese labels/fallbacks for every scenario key used by cards; never show a raw key.
   - Add a short empty state before the first compare run.
   - Hide or explain the active-campaign restriction in the product dropdown.

10. Documentation (P2-5, P2-7, P2-6)
   - Remove the duplicate 演示日期 line.
   - Correct UI_SPEC stale markers: Stage 2 status, Stage 4 summary, trimmed wording, plus500
     description, screenshot provenance.
   - Label probe screenshots as simulated; do not claim they prove real backend behavior.

ACCEPTANCE
- `python -m pytest -q` green, with new regression tests for P1-1..P1-7 and HQ reset.
- `python scripts/gen_fake_data.py --check-only` still passes.
- Playwright at 1920x1080: warm page load/store switch <1s, no horizontal overflow, no console
  errors, no MODEL_/angle placeholders; Sunday/Monday role-rule check.
- Report exactly what was fixed, what remains, and the new commit/PR state. Do not merge PR #6.
```
