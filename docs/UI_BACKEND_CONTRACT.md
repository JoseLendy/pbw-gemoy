# UI ↔ backend contract

Status: **binding for the UI merge**. `tests/test_ui_contract.py` asserts every function below exists at
this path with these parameters, and every result type has the fields listed. Renaming anything here
without updating both the doc and the test fails the suite.

The UI (`server.py`, `ui/`) only imports from the modules below. It never calls ima, the LLM or the checks
directly.

## 1. Functions the UI calls

### Cards (offline, no LLM / ima)

| Function | Signature | Returns |
|---|---|---|
| `agent.recommend.store_data.cards_for` | `(store_id, today, data=None)` | `list[RecommendationCard]` for that store and date |
| `agent.recommend.store_data.default_card` | `(store_id, today, data=None)` | the `is_default` card (今日一条) or `None` |
| `agent.recommend.store_data.product_card` | `(store_id, model_id, today, data=None)` | 四店对比: the store's 活动款 card pointed at one product, or `None` if no active campaign has it |
| `agent.recommend.store_data.set_fact_card_status` | `(model_id, status)` | `None`; `status` ∈ `"draft"`, `"verified"` (总部端 确认发布). In memory only |
| `agent.recommend.store_data.fact_card_overrides` | `()` | `dict[model_id, status]` set in this process |
| `agent.recommend.store_data.reset_demo_state` | `()` | `None` (重置演示; see §3) |

### Generation (real deps call ima + LLM)

| Function | Signature | Returns |
|---|---|---|
| `agent.pipeline.run_from_card` | `(card, deps=None, staff=None, on_progress=None, fallback=True)` | `RunResult` · `LockedResult` · `NeedsHuman` · `NeedsReview` (重新生成 / 换一条 run this live) |
| `agent.pipeline.generate_batch` | `(cards, deps=None, staff_map=None, on_progress=None)` | `BatchResult` (四店对比) |
| `agent.pipeline.generate_baseline` | `(card, deps=None, llm=None)` | `BaselineResult` · `LockedResult` (对照组) |
| `agent.pipeline.edit` | `(prev, instruction, deps=None, on_progress=None)` | `RunResult` · `Clarification` · `NeedsHuman` · `EditBlocked` (quick edits) |
| `agent.pipeline.prepare_today` | `(date, deps=None, runs_dir=None, on_progress=None, card_map=None)` | `PreparedDay` (the morning run; normally `scripts/prepare_today.py`, not the UI) |
| `agent.pipeline.run` | `(text, form=None, deps=None, on_progress=None)` | `RunResult` · `Clarification` · `NeedsHuman` (生成 page, the original manual flow) |

`on_progress(stage, message)` receives short Chinese progress lines; a failing callback never breaks a run.

### Stored outputs (read-only, no network)

| Function | Signature | Returns |
|---|---|---|
| `agent.runs.prepared_post` | `(store_id, date, card_id=None, model_id=None, runs_dir=None)` | the stored morning post (dict) for the store's **current** default card, or `None` (then generate live) |
| `agent.runs.latest_run` | `(card_id, runs_dir=None)` | the newest real run record (dict) for that card, or `None` (fallback display if the API fails; show its `timestamp`) |
| `agent.runs.clear_prepared` | `(date, runs_dir=None)` | number of prepared posts deleted (explicit; never part of 重置演示) |
| `agent.fact_cache.clear_fact_cache` | `(day=None)` | number of cached fact entries dropped (only after a KB update) |

### Rendering

| Function | Signature | Returns |
|---|---|---|
| `agent.formatter.render_publishable` | `(post)` | the text staff copy (no `[F#]` tags) |
| `agent.formatter.render_report` | `(result)` | the 四段式 output (一、场景判断 … 四、核验结果) for a `RunResult` |

## 2. Result types and how the UI shows them

| Type | Fields the UI may read | Show |
|---|---|---|
| `RunResult` | `task`, `model`, `post`, `report`, `pending`, `sources`, `timings`, `loops`, `fallback` | phone preview of `render_publishable(post)`, copy / 已发布 buttons, `render_report` in a fold. `fallback="trimmed"` → note 「已删去未通过核验的句子」; `fallback="next_card"` → use `task.slot` / `task.card_id` for the header, note 「今日一条未通过核验，已换成下一条推荐」 |
| `Clarification` | `questions` (each a `Question`: `slot`, `text`, `options`), `partial` | option chips; resubmit with the answers |
| `NeedsHuman` | `conflicts`, `message` | `message` + the conflicting facts; no post |
| `LockedResult` | `card`, `reason`, `message` | `message` (新品资料待总部确认，暂不可生成); no generate button |
| `EditBlocked` | `instruction`, `message`, `rule`, `prev` | `message`, keep showing `prev` unchanged |
| `BaselineResult` | `card_id`, `model_id`, `platform`, `prompt`, `text`, `display_text`, `hits`, `label`, `is_baseline` | always `display_text` (starts with 【对照组：未经约束的普通大模型输出】) and highlight `hits` (8D); never as our result |
| `NeedsReview` | `card`, `draft`, `failing`, `message`, `attempts` | 「需人工确认」 panel: `draft.post` read-only with each `failing[i].sentence` highlighted and its `reason`; **no copy / publish button**; offer 重新生成 |
| `BatchResult` | `results` (store → any type above or an `Exception`), `similarity` (`SimilarityPair`: `segment`, `store_a`, `store_b`, `before`, `after`, `regenerated`), `regenerated`, `seconds`, `regen_seconds`, `wall_seconds` | 四店对比: one phone preview per store; `similarity` as before → after; an `Exception` is that store's error line only |
| `PreparedDay` | `date`, `batch`, `paths`, `locked`, `errors` | not shown in the UI (CLI) |

A delivered card post always passed every check: with `fallback=True`, `run_from_card` never returns a failing `RunResult`.

### `NeedsReview` detail

| Field | Type | Meaning |
|---|---|---|
| `card` | `RecommendationCard` | the card that was asked for (the morning default card in `prepare_today`) |
| `draft` | `RunResult` | the best checked draft (fewest errors); its `post` must **not** be published |
| `failing` | `list[FailingSentence]` | `field` (title / intro / body[i] / cta), `sentence` (publishable text; empty when the error has no single sentence, e.g. a missing store detail), `stage` (8A–8D), `code`, `reason` (Chinese) |
| `message` | `str` | 「需人工确认：自动核验未通过，已列出未通过的句子和原因」 |
| `attempts` | `list[str]` | what was tried, e.g. `["S01-2026-10-23-potential", "trimmed", "S01-2026-10-23-promo"]` |

### Prepared post / run record (dicts)

`prepared_post(...)` returns `{kind: "prepared", card_id, store_id, store_name, date, slot, model, card, status, passed, rewrites, seconds, similarity, regenerated, dev_mode, temperatures, timestamp, result}`. `status` is the result type name (`"RunResult"`, `"NeedsReview"`, `"LockedResult"`, …); `result` is that object as a dict. `latest_run(...)` returns `{card_id, store_id, store_name, staff, scenario, model, platform, temperatures, kind, timestamp, result}`.

### Card fields the UI shows

`RecommendationCard`: `card_id`, `store_id`, `store_name`, `date`, `slot`, `slot_label` (潜力款 / 活动款 / 新品款 / 顾客问答), `model_id`, `display_name` (always show in full: two models are both "MateBook 14"), `platform`, `segment_label`, `angle`, `hook`, `voice`, `landmark`, `reasons` (`CardReason`: `text`, `source`, `is_demo` → 模拟 badge), `locked`, `locked_reason`, `promo`, `question`, `is_default`. The 新品款 reason reads 「总部新品推送（演示流程）」.

## 3. State: what 重置演示 clears

| State | Owner | Cleared by `reset_demo_state()` |
|---|---|---|
| HQ fact-card overrides (`set_fact_card_status`) | backend, in memory | **yes** |
| store data cache (`load_store_data`) | backend, in memory | **yes** |
| prepared posts + stored versions / 四店对比 / 对照组 (`runs/<date>/prepared/**`) | backend, on disk (real run logs) | no: `clear_prepared(date)` only |
| today's 已发布 marks (`runs/published/<date>.json`, weekly progress) | backend, on disk | no; `ui_data.reset()` (重置演示) clears them |
| real run logs (`runs/<date>/*.json`) | backend, on disk | never |
| per-product fact cache (`runs/cache/`, in memory) | backend | no: `clear_fact_cache()` only after a KB update |
| 已发布 marks, question chips, selected store / staff, current preview, edit history | **UI session** | no: the UI must clear these itself on 重置演示 |

## 4. Platform versions, precompute, edit and export (2026-10-22)

- **One card, every platform.** Cards open on 朋友圈. `prepare_today` stores a 朋友圈 and a 小红书 version of each default card (same model, angle and fact card), plus 公众号 where the store's weekly 公众号 minimum is not met. `prepare_today --demo` (`prepare_demo`) also stores every other unlocked slot, the 四店对比 set and the S01 对照组 pair. Files: `runs/<date>/prepared/versions/<card_id>__<platform>.json`, `…/compare/<model>__<platform>.json`, `…/baseline/<card_id>.json`.
- **Read first, generate second.** `ui_data.stored_version(card, platform)`, `stored_compare(model, platform)`, `stored_baseline(card_id)` (+ `baseline_from_payload`). The UI shows a stored result at once, labelled 「生成于 …」; live generation only on 重新生成 / 生成公众号文章 or when nothing is stored.
- **Weekly progress (a suggestion, not a lock).** `ui_data.weekly_progress(store_id)` → `{progress, suggestion, line}`; `weekly_progress_all()` for 总部端 本周计划; `mark_published(store_id, platform, card_id)` records 已发布 per platform.
- **Inline edit.** `ui_data.check_edit(text, result)` → `EditCheck(passed, post, failing, issues, seconds)`: deterministic checks only, no LLM. On pass the UI keeps `post` as 「已修改·已核验」 and calls `log_human_edit(card, platform, original, edited)`.
- **Export.** `agent.export.wechat_text(post)` is the 复制文案 text; `ui_data.export_zip(post, store_id, text)` writes `<store>-<date>-<platform>.zip` (文案.txt, 1.jpg…, 文章.md for 公众号).
- **No personal names.** Cards and tasks carry no `nickname`; 8B `personal_name` fails any name or sign-off.

## 5. Fallback counts (CLI)

`scripts/prepare_today.py` and `scripts/eval_cards.py` print each store's status: `PASS`, `PASS (trimmed)`, `PASS (next_card)`, `NEEDS_REVIEW（需人工确认）`, `LOCKED`, or the error. The eval counts a pass only when no fallback was needed.
