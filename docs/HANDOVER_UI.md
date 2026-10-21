# UI handover

Written for a teammate picking this up on a different laptop, in a fresh Claude Code session, continuing
`feat/proactive-ui`. Read `docs/UI_SPEC.md` first for exactly what was asked and what's DONE/PENDING;
this file is the runbook and the bug list.

## What works now

- `agent/ui_data.py`: the single adapter between the UI and the backend (recommender + pipeline + runs).
  One shared `Deps` for the whole app (`agent.ui_data.DEPS`), built once with `Deps.auto()`.
- `ui/components.py`: pure display-data helpers (role rule, slot ordering, reason badges, result
  classification) plus the HTML render panels (`phone_html`, `banner_html`, `talk_card_html`,
  `stop_html`, `needs_review_html`, `prepared_post_html`, `last_real_run_html`) - shared by the new
  store tab and the pre-existing manual-flow tab (relocated from `app.py`, behaviour unchanged).
- `ui/store_tab.py`: Stage 1, 门店端·今日推荐. Store selector (12 stores, no login), today's default
  card with its reasons (模拟数据 badges), 换一条 revealing the other slots, locked new-product handling,
  生成/重新生成, quick edits (短一点/换卖点/换个角度 + the 加上立减500 price-block demo), 已发布 marking,
  download (.md text, one image at a time), the 显示最近一次真实运行结果 recovery offer after a failed
  generate, and the end-of-day customer-question chips.
- `ui/compare_tab.py`: Stage 2, 三店对比. One product + one platform; fixed S01/S04/S08/S02; four
  phone previews with each store's segment/scenario/voice/landmark/hook; 8E before→after scores and
  regenerated badges.
- `ui/hq_tab.py`: Stage 2, 总部端. 14-day posting rate (lowest 3 highlighted), new-release draft review
  with fact IDs / fields / source titles, 确认发布 (store tab re-fetches and unlocks on return),
  customer questions, weekly plan with today highlighted, recommendation distribution, 重置演示.
- `ui/baseline_tab.py`: Stage 3, 对照组. Left `baseline()` always under
  「对照组：未经约束的普通大模型输出」 with 8D hits marked; right our verified `generate()` result.
- `app.py`: assembles 门店端·今日推荐 + 三店对比 + 总部端 + 对照组 + 手动输入 (unchanged) under one header.
- The branch has been merged with `origin/feat/proactive-recommender` (brings in PR #4 / Phase 5 and
  PR #5 / freeze prep: new model mapping, fallback policy, prepared posts, latency tracking, KB mirror
  untracked). `ui/components.py` and `agent/ui_data.py` follow the real `docs/UI_BACKEND_CONTRACT.md`.
- Stage 4 (staff picker / 绑定演示 / 发布效果) is **not started** (optional in the spec).

## How to run it

```bash
cd pbw-gemoy-ui
.venv/bin/python app.py
```

Opens on **port 7861** by default (`GRADIO_SERVER_PORT` env var overrides it; the old `PORT` env var
still works as a second fallback). `DEMO_TODAY` (default `2026-10-23`) controls the UI's "today" - set
it to change which card is the default / which new release is in its priority window, e.g.:

```bash
DEMO_TODAY=2026-10-23 .venv/bin/python app.py
```

`.venv` was created fresh in this worktree (it didn't exist before); `pip install -r requirements.txt`
if it's missing again. Playwright was installed for browser testing but **not** added to
`requirements.txt` on purpose (dev-only tool, see below) - reinstall with
`pip install playwright && python -m playwright install chromium` if you need it again.

## How to test

**Unit/integration tests** (fakes only, no network): `.venv/bin/python -m pytest -q`. Should be green
(613 passed, 1 skipped at the time of this handover). `tests/test_ui_data.py` and
`tests/test_ui_components.py` are the Stage 1 UI tests.

**Browser testing with Playwright** (not yet completed this session - see the first known-bug item
below for why it's worth doing before anything else):

```bash
.venv/bin/pip install playwright   # not in requirements.txt - dev tool only
.venv/bin/python -m playwright install chromium
GRADIO_SERVER_PORT=7862 .venv/bin/python app.py &   # a throwaway instance, NOT 7861
```

Then drive it with `playwright.sync_api`, viewport `{"width": 1920, "height": 1080}`, headless
Chromium. **Important:** `page.goto(url, wait_until="networkidle")` never resolves against this app -
Gradio keeps a live connection open (status polling), so the network never looks idle to Playwright.
Use `wait_until="load"` and then an explicit `page.wait_for_timeout(...)` or wait for a specific text/
selector to appear instead. Also: a stray `pageerror`/`console` listener
(`page.on("console", ...)` / `page.on("pageerror", ...)`) is the right way to check for the "no JS
errors" requirement from the spec. Use `127.0.0.1` or `localhost`, not `0.0.0.0` - the server binds
`0.0.0.0` (all interfaces) but that address may render as a literal, unreachable host in some
browsers/editor previews; it is not the app being broken.

Kill whatever instance you started when done; never kill port 7861 if someone else (a person, or
another session) is using it as their live demo/test instance.

## Adapter paths: real vs fallback

Check at runtime, don't assume:

```python
import agent.ui_data as ui_data
print(ui_data.DEPS.is_dev_mode, ui_data.DEPS.fake_fields)   # which pipeline stages are faked
print(ui_data.ACTIVE_PATHS)                                  # {"prepared_post": bool, "clear_prepared": bool}
print(ui_data.DEPS.status())                                 # KB connection / index status (never prints keys)
```

On this machine, at the time of this handover: `fake_fields == []` (catalog, retrieval, ledger,
platform_plan, intake, scenario, reconcile, writer, checks, llm, ima_wrapper are all real), ima
connected with a complete index, and `ACTIVE_PATHS` both `True` (`agent.runs.prepared_post` /
`clear_prepared` are real, merged in PR #4). **This will differ on another laptop** depending on that
machine's `.env` - `Deps.auto()` falls back to fakes per-module if a real one fails to import/construct,
and shows "开发模式" in the status bar when anything is fake.

## Known bugs

### FIXED: the store tab (and everything else) froze behind one slow request

**Resolved on 2026-10-21.** The real cause was worse than the queue default: the machine's system
proxy (127.0.0.1:7890) intercepted Gradio's launch self-check `GET /gradio_api/startup-events`, which
returned 502. `launch()` aborted before that endpoint ran - and that endpoint is what starts Gradio's
queue. The page therefore loaded with every event showing `queue: 1/1` forever, regardless of
concurrency. Fixes in `app.py` / `ui/store_tab.py`:
- add `127.0.0.1,localhost,::1` to `NO_PROXY`/`no_proxy` before Gradio/httpx read the environment;
- retry `/gradio_api/startup-events` with `trust_env=False` if launch's self-check still fails;
- `demo.queue(default_concurrency_limit=4)` + one shared `"generation"` pool (limit 4) for slow
  events, while page load / store switch / publish / chips use `concurrency_limit=None`;
- render the KB status bar from cache immediately and refresh it in a daemon thread (2s Timer update).
Verified with Playwright at 1920×1080 while a 25s generation was running: cold load 383ms, second
visitor load 360ms, store switch 384ms, no console errors, no horizontal overflow, no `MODEL_`/<…>.
Regression tests: `tests/test_ui_queue.py`.

The original diagnosis (kept for context) follows.

### TOP PRIORITY (historical): the store tab and everything else froze behind one slow request

**Symptom reported by the user:** in a real browser at `http://localhost:7861`, the store tab never
finishes loading. Every component shows `queue: 1/1 | 131.1s` (the number keeps growing), and the page
is stuck.

**Diagnosed root cause (confirmed, not a guess):** Gradio's queue defaults to
`default_concurrency_limit = 1` (see `gradio/blocks.py`, the `concurrency_limit` and `queue()` docstrings)
when `.queue()` is never called and no event sets its own `concurrency_limit`. **Neither `app.py` nor
`ui/store_tab.py` calls `.queue()` or sets `concurrency_limit=` anywhere.** That means the *entire app*
- both tabs, every button, every page load, every user - shares exactly one execution slot. If any one
event takes a long time, every other queued event (including a brand new page's own `demo.load` /
`on_initial`) sits behind it and never runs until it finishes. Two realistic ways to occupy that one
slot for a long time in this app:

1. `ui/store_tab.py`'s `on_generate` / `on_short` / `on_point` / `on_angle` / `on_price` call
   `agent.ui_data.generate()` / `.edit()` **synchronously**, directly inside the Gradio event handler.
   A real run (ima retrieval + ledger + LLM writer + up to 2 check/rewrite loops) can legitimately take
   tens of seconds; `131.1s` is very plausibly just a real pipeline run's actual wall-clock time. Compare
   this to `app.py`'s pre-existing manual-flow `on_generate`, which runs the pipeline in a background
   `threading.Thread` specifically so the Gradio event can stream live progress text instead of blocking
   - but that handler *still* occupies the one global queue slot for its full duration; threading only
   improves that one request's own UX, it doesn't free the slot for anyone else.
2. `app.py`'s status bar does `demo.load(lambda: status_html(), None, status)`, which calls
   `kb_status()` → `DEPS.status()` → a real ima call on the first request after each 10-minute cache
   window. If that call is slow or hangs on a given network, it alone can occupy the one slot.

**What page load and store switching should NOT do, and currently don't:** `ui/store_tab.py`'s
`on_initial` / `on_store_change` → `_load_store` → `agent.ui_data.get_cards` /
`agent.ui_data.prepared_post` are already local-only (CSV/JSON reads + in-memory computation in
`agent.recommend`, a local JSON file read in `agent.runs`) - **no LLM or ima call is reachable from
page load or a store switch in the current code.** So the fix is not "stop calling the network on
load" (already true); it's "stop sharing one global queue slot between fast local UI events and slow
network-bound generation."

**Fix applied:** see the "FIXED" section above - explicit `demo.queue(default_concurrency_limit=4)`,
one shared `"generation"` pool, `concurrency_limit=None` on page load / store switch / other local
events, a non-blocking `kb_status()`, and the `NO_PROXY` + startup-events retry that actually gets the
queue started on machines with a system proxy. Playwright verified 360-420ms for all three paths while
a generation was running.

### Secondary / lower priority

- **`kb_snapshot/` is no longer tracked in git** upstream (PR #5, merged into `feat/proactive-recommender`,
  **not yet merged into `feat/proactive-ui`**). This branch's `kb_snapshot/` is still tracked as of this
  commit. When you merge `feat/proactive-recommender` again to pick up PR #5, check its updated README
  section for how to restore the KB mirror on a fresh clone (PR #5's description says it added one;
  this branch's current `README.md` does not have it yet, precisely because PR #5 isn't merged here).
- **Playwright visual verification (1920×1080, screenshots, console-error check) was not completed**
  this session - it was interrupted mid-script by the handover request. `eval/ui_screens/` (gitignored)
  was created but is empty. Do this early; it's the fastest way to catch anything that "looks wrong on
  camera" (overflow, cut-off CJK text, a stray model_id, etc.) before Stage 2 adds more screens.
- The LLM key configured in this worktree's `.env` returned `402 Insufficient Balance` on every real
  generate attempt tested this session. That's an account/billing issue, not a code bug - `plain_error`
  now shows a friendly message for it (「模型账户额度不足，请联系管理员充值后重试。」) instead of the
  raw provider JSON, but you still need a funded key to actually see a generated post on screen.
- `pip install -r requirements.txt` resolves `gradio>=4.44` to **6.30.0** as of this session (a major
  jump from what the project was originally built against). A one-time Gradio self-check race on
  `launch()` (`GET .../gradio_api/startup-events` returning a transient 503 even though the server is
  already up) was observed and worked around in `app.py`'s `__main__` (retried at most once, only for
  that specific error). If Gradio's queue defaults or API shift again in a future minor/major version,
  re-check that workaround and the concurrency fix above against whatever version is actually installed.
- `agent/ui_data.prepared_post` / `last_real_run` return the **raw logged dict** from `agent.runs`
  (`{"status": ..., "result": {...}, "timestamp": ...}`), not a live `RunResult`. `ui/components.py`'s
  `prepared_post_html` / `prepared_pub_text` / `prepared_payload_view` render straight from that dict
  (title/intro/body/cta, images by media id) rather than reconstructing live `Ledger`/`Post` objects, so
  these two paths don't get the full interactive phone preview (fact-popover, platform skin) or the
  four-section report that a freshly generated `RunResult` gets - just a simplified card. Known,
  intentional scope cut for Stage 1, not a bug, but worth knowing before building on it further.

## Branch / commit

Branch: `feat/proactive-ui`. See the chat reply for the exact commit hash this was pushed at.
