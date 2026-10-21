# Backend handover (2026-10-21)

For the teammate continuing on another laptop with a fresh Claude Code session. Read `CLAUDE.md` first, then this file.

## Where things stand

- **Branch:** `feat/proactive-samples` (from `origin/feat/proactive-recommender` after PR #5 was merged). Not yet a PR.
- **Tests:** `.venv/bin/python -m pytest -q` → **618 passed, 1 skipped, 1 xfailed**. The xfail is the pending proof test from item 1 below; it is `strict=True`, so it starts failing (on purpose) once the fix lands, and then its marker must be removed.
- **Merged already:** Phase 5 (PR #4) and freeze prep (PR #5): mapping (MODEL_N = Pro S, MODEL_B = X Pro), new-release truthfulness (8B), prepared posts (`prepare_today` / `prepared_post`), latency work (fact cache, parallel batch, per-stage timings), the T4 fallback policy (trim → next card → `NeedsReview`), `scripts/check_canary.py`, `scripts/freeze_check.py`, `scripts/export_samples.py`, `docs/UI_BACKEND_CONTRACT.md` + `tests/test_ui_contract.py`, `kb_snapshot/` untracked.
- **On this branch so far:** README warning about `kb_snapshot/` being deleted on pull (with the restore command); canary clean drafts rebuilt strictly from ledger facts (work in progress, see item 1); two proof tests for the "；" split (one xfail).

### Results so far today (real runs, 2026-10-23, 朋友圈)

**Canary (`RUN_E2E=1 python scripts/check_canary.py --today 2026-10-23`), last run:** planted errors caught **9/9**, clean drafts passed **1/3**. Classification done so far (item 1, steps 1–3 not finished):

| Clean draft | Flag | Class | Status |
|---|---|---|---|
| 1 (潜力款, KB 可用结论 verbatim) and 3 | 8A `untagged_claim` / `uncited_claim` on the verbatim claim fact, which IS tagged | (b) the fact value contains "；"; 8A splits sentences on "；" and reports the first half as untagged | proof tests written in `tests/test_checks_facts.py` (`…semicolon…`); **fix not written** (xfail) |
| 3 (活动款 + demo price) | 8A `uncited_claim` + 8B `false_promise` on 「演示活动价 4999 元 [演示活动]，活动期内有效，以门店实际为准。」 | (b) the price matches the active HQ record exactly and the code-level 8B price check passes it, but neither LLM judge is shown the record | not started: prove (judge prompt lacks the record) and pass the record to the 8A and 8B judges, like the `<store>` block |
| 3 | 8B: landmark 紫金港 on an S02 card | (a) canary bug: `invite` in `scripts/check_canary.py` uses the S01 landmark for every card | not fixed: build the invite from each case's task |
| 3 | 8D `ai_no_detail` | (a) follows from the wrong landmark | fix with the row above |
| 1 | 8D `ai_judge` (reads like a generic machine draft) | (a) a post that is only a KB conclusion is generic | add a reader-side scene sentence (no product claim) |

Earlier flags on the old clean drafts were all (a) and are fixed in the script: suitability asserted with a battery fact, a "周末" opening-hours promise in the CTA, and a battery-plus-afternoon implication.

**`demo_scenes.py --today 2026-10-23` (real, finished):** PASS 6 (对照组) and 8 (新品 gate); FAIL 1–5 and 7. All FAILs trace to **S01 (MateBook 14 鸿蒙版) ending as `NeedsReview`**: scene 1 stored 12 prepared posts, 11/12 passed, S01 NeedsReview; scene 2 (S01 live) NeedsReview; scene 3 failed only on S01; scenes 4, 5 and 7 depend on scene 2's result. **Likely cause (unconfirmed):** the "；"-split false positive above, since this model's KB conclusions contain "；". Seconds: scene 1 245 s (12 stores), scene 3 147 s (4 stores; S01 alone 147 s, the others 29–83 s), scene 2 192 s.

**Prepared posts from that scene-1 run exist locally** (see Environment) but were made before the canary fixes; item 3 regenerates them.

**Calls today:** LLM ≈ 715 (Phase 5 evals) + 31 + 32 (canary) + 276 (demo_scenes). ima: 3 (X Pro index refresh); everything else ran from the mirror / caches.

## PENDING queue (in order)

### 1. Canary clean-draft investigation (the user's instructions, verbatim)

> On the canary: a check that flags everything also "catches 9/9", so the clean drafts must pass for the canary to mean anything. Before prepare_today:
>
> 1. For each flagged clean draft, list the exact sentence and the judge's reason, and classify it: (a) the draft genuinely has an issue, or (b) the check over-flags correct content.
> 2. For (a): fix the draft. Build at least one clean draft per card strictly from ledger facts: only tagged facts, qualifiers copied exactly, usage phrased as the reader's scenario, no borderline wording. Re-run; it must PASS all checks.
> 3. For (b): treat it as a false positive. Prove it with a minimal test and fix narrowly, as before; never loosen a rule broadly.
> 4. If even a strictly fact-built draft can't pass, stop and tell me before running prepare_today: that would mean real posts are being blocked unfairly.
> Report the final canary as: planted errors caught X/9, clean drafts passed Y/Z.

State: step 1 done (table above). Next: fix the two (b) items with narrow code changes (8A "；" split for a verbatim tagged fact; price record shown to the 8A and 8B judges when `valid_price_record(task)` exists), fix the canary's (a) items, re-run the canary once.

### 2. `demo_scenes.py` for 2026-10-23
Finished (results above), but with S01 failing. Re-run after item 1 so every scene can PASS: `RUN_E2E=1 python scripts/demo_scenes.py --today 2026-10-23`. Explain any FAIL.

### 3. `prepare_today` for 2026-10-23
`python scripts/prepare_today.py --today 2026-10-23` (real deps). Report per store: direct / trimmed / next_card / NeedsReview (`PASS`, `PASS (trimmed)`, `PASS (next_card)`, `NEEDS_REVIEW` in the output).

### 4. `export_samples`
`python scripts/export_samples.py --today 2026-10-23` → `samples/` (S01, S02, S04, S08, S10 prepared posts; the locked 新品款; the 加上立减500 EditBlocked; a NeedsReview). It refuses to write if a sample contains a key-like token, a configured secret, a KB media id or a verbatim ledger quote. Check the files by eye before committing. Needs a real scene 5 / scene 8 run for the locked and EditBlocked samples.

### 5. K3: README "Samples" section
Add a short section linking `samples/README.md`; keep the statement that the repo contains no KB text, quotes or images.

### 6. `freeze_check.py`
`python scripts/freeze_check.py` and report the full output. Expected ❌ until items 2–3 succeed: prepared posts, demo_scenes run.

### 7. Push and open a PR
Push `feat/proactive-samples` and open a PR into `feat/proactive-recommender`. **Do not merge it.**

## Environment notes

- **LLM:** OpenAI-compatible endpoint from `.env` (`LLM_MODEL=deepseek-flash`; `LLM_MODEL_FAST` unset, so the check judges use the main model; changing models needs the user's OK). The balance was topped up on 2026-10-21; a `402 Insufficient Balance` means it ran out again (it is not retried; `prepare_today` never stores a crashed store).
- **`.env`:** never print, echo or cat it. Copy it from the user over a private channel; it is gitignored.
- **`KB_BACKEND`:** `hybrid` (recommended: mirror + live ima confirmation; falls back to live ima if the mirror is missing and credentials exist), `local` (mirror only, zero ima calls; clear error if the mirror is missing), `ima` (live only; the cached ima index now includes X Pro after `scripts/refresh_model_index.py`, 3 calls).
- **KB mirror `kb_snapshot/`:** not in the repo (untracked in PR #5). Get it from a teammate, or restore it from git history: `git restore --source=1f6f8f6 --worktree -- kb_snapshot` (files land untracked and ignored). **Warning:** checking out an old local branch that still tracks `kb_snapshot/` and then pulling deletes it from disk (this happened once on 2026-10-21); back it up before switching branches.
- **`runs/` is local only (gitignored), including prepared posts and the fact cache.** Prepared posts live in `runs/<date>/prepared/<store_id>.json` (read them with `agent.runs.prepared_post(store_id, date)`; the UI must run on the machine that ran `prepare_today`, or the posts must be regenerated there). Run logs: `runs/<date>/*.json`; fact cache: `runs/cache/<date>/`; rehearsals: `runs/_rehearsal/`. **Regenerate on the new machine** (items 2–3); nothing in `runs/` comes with the repo. `eval/` (reports, samples for review) is local too.
- **Python:** the repo's `.venv` (`.venv/bin/python`); on the old laptop it lived one level up. `pip install -r requirements.txt` includes pytest.
- **Real-call scripts** need `RUN_E2E=1` (eval_cards, demo_scenes, check_canary); `prepare_today.py` refuses fake deps unless `--fake`.

### Known: 8D `ai_judge` run-to-run variance (recorded 2026-10-21)

The 8D LLM judge ("整篇仍像机器写的通用稿") gives different verdicts on an **identical** draft between runs, although judges run at `CHECK_TEMPERATURE=0`: canary clean draft 1 (reader-side scene sentence + verbatim KB conclusion) passed in one run and failed in the next with the same text; clean draft 3 likewise flipped. 8A/8B are stable on the same drafts. Decision (user, 2026-10-21): **accept it for now and proceed**; in real runs an `ai_judge` flag triggers a rewrite, then the T4 fallback. Do **not** change the judge yet. If it has to be addressed, look first at how the writer generates the scene sentence (generic reader scenes read as machine-written), not at judge voting.

## Open decisions

- **Git history still contains the old KB files** (from commit `ddf3b1a`). Removing them needs a history rewrite and a force-push. Decision: **only after Friday's submission**, and only by the repo owner; until then do not publish the repository.
- Whether to set a faster `LLM_MODEL_FAST` for the 8A/8B judges (they dominate latency); not changed without the user's OK.

## Status log

- 2026-10-21 · item 1 · (b) fixes landed with proof tests: 8A keeps a verbatim tagged fact's own "；" (xfail removed, +2 guard tests); the active HQ price record is shown to the 8A and 8B judges as `<promo>` (proof test failed before the fix). (a) canary fixes: per-card invite landmark; reader-side scene sentence (first-person version was rightly flagged by 8B and rephrased). Real canary, 3 runs: planted 9/9 every run; clean 2/3 → 2/3 → 1/3. 8A/8B are now clean on all clean drafts; the remaining flags are only 8D `ai_judge`, which flips on an identical draft between runs (at CHECK_TEMPERATURE=0). **Stopped before items 2–3 per instruction 4; waiting on the user.**
- 2026-10-21 · item 2 · `demo_scenes --today 2026-10-23`: PASS 1, 6, 8; FAIL 2 (S01 live → NeedsReview: 8A tag_mismatch, 8C moments_focus, 8B false_promise), 3 (S04 NeedsReview, 8B false_promise), 4/5/7 (depend on scene 2). LLM 243, ima 2.
- 2026-10-21 · item 3 · `prepare_today --today 2026-10-23`: 12/12 stored, 10 passing (direct 4, trimmed 1 [S08, 8D ai_judge only], next_card 5), **NeedsReview 2: S01, S06**. S01 (demo store) has no passing prepared post (this run replaced scene 1's passing one). Most common final blocker: 8C moments_focus (6 card runs), then 8B false_promise (4). 8D-triggered rewrite share **not measurable**: check_loop keeps only the final report. Batch 3876 s with an unexplained ~60 min stall (no record 11:34–12:34Z; only 4 LLM timeouts logged). **Stopped before items 4–7 (S01 short); waiting on the user.**
