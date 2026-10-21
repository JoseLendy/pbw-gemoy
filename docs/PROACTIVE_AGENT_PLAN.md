# pbw gemoy — Proactive Store Post Agent (复赛 plan)

> Team design doc for the 复赛 (semi-final → final) round.
> Status: **v2.3, Phase 4 implementation**. Suggested repo location: `docs/PROACTIVE_AGENT_PLAN.md`.
> Deadline: **video submission, Fri Oct 23, 17:00**.

**Changelog**
- **v2.3 (Wed Oct 21, Phase 4):** real model mapping applied (`docs/model_mapping.md`); peer-aware hook/angle assignment replaces per-store md5 rotation (§6.4); `generate_batch` adds 8E regeneration and before/after similarity; 8C/8D duplicate hits are merged into one line with both checker IDs; `reset_demo_state`, `runs/` real-run logs and `latest_run` added (Phase 3 UI can call them); `gen_fake_data.py --check-only` supports a safe Amap swap. 8A auto-cite now refuses sentences with unsupported numbers; 8B money patterns are as broad as the old 8A price rule.
- **v2.2 (Wed Oct 21, Phase 2):** the 8D blocklist drops its `absolute` group (absolute claims are 8B's job; a bare 最/第一 substring match would false-flag 最近/第一次). Customer-hook wording loses its 最 ("这几天好几位顾客都在问……"). Recommendation cards gain an explicit, calendar-aware `scenario` field (§10.7), so the pipeline no longer guesses a stage from the segment.
- **v2 (Wed Oct 21):** organizer confirmed we may use fake data. §10 rewritten around a ready-to-run data kit (`scripts/gen_fake_data.py` + templates in `data/demo/inputs/`). Demo promos may now carry demo prices, with a new price-traceability rule (§4.3, §6.5). Affinity scores moved into `models.csv`. Configs are JSON. Amap POI codes verified. Timeline updated.
- v1 (Tue Oct 20): initial proposal.

---

## 0. TL;DR

Right now our agent is **pull-based**: a store employee has to type what they want to promote, then the agent writes it.

The new version is **push-based**: when a store employee opens the app, **today's post is already prepared for their specific store**. They check it, tap copy, and post. Target: under 30 seconds of effort per day.

What decides the post:

| Signal | Scope | Decides | Data in demo |
|---|---|---|---|
| Store surroundings (schools, offices, housing, malls) | Per store | Who the audience is → which angle | **Real** Amap POI if the key is ready; **fake fixture** otherwise (same format) |
| Store sales vs. similar stores | Per store | Which product is the "potential" pick | **Fake**, generated with planted stories (§10) |
| National promotions | All stores | Whether a promo card appears | **Fake**, may include demo prices (§4.3) |
| New releases | All stores | Whether a new-product card appears | Facts **real** from KB; release status fake (draft → verified) |
| Calendar (双十一, 开学季…) | All stores | Timing and theme | Static table |
| Customer questions, posting log, engagement | Per store | 顾客问答 card, HQ view | **Fake** |

Core rules:
1. **National signals decide WHAT, regional signals decide the ANGLE.**
2. **We don't push the best-seller or the worst-seller. We push the product that *should* sell well here but doesn't** (under-index score, §5).
3. **Sales data is only used to choose products. It never appears in the copy.**
4. **Facts are locked before writing; creativity only touches wording** (two-temperature design, §6).
5. **Store data may be fake; product facts never are.** Specs, features and images always come from the ima KB.

The existing pipeline (fact ledger, model-ID image matching, 8A/8B/8C check loop, 4-section output) stays. The new work sits **in front of it** (recommendation) and **around the writer** (style + variation).

---

## 1. Context: what Huawei told us

The 复赛 only requires a video. No reference data or fixed requirements are given; the organizer has confirmed we may create fake data. They described three business problems and asked us not to be limited by the original brief.

| # | Pain (their words, summarized) | What we do about it |
|---|---|---|
| 1 | Stores are required to post to 小红书 / 公众号 / 朋友圈 regularly. Staff are busy, don't want extra work, write badly or post carelessly → posting becomes box-ticking (形式主义). | **Push model**: the post is ready when they open the app. Explanation card, one tap copy, zero setup (§4, §9). |
| 2 | The current system's output feels AI-written and identical. Sent to thousands of stores, it's unusable. | Region-driven angles, store voice profile, anti-AI style layer, cross-store similarity check (§6). |
| 3 | LLMs hallucinate about new products, which are the top priority. KB attempts (own KB, ima) still fail on "attractive + accurate + no overpromising". They suspect temperature / KB dependency design. | Two-temperature design + locked fact card + existing ledger; new-product rule: **HQ verifies once, stores generate many** (§6.2, §7). |

---

## 2. User flow (what the store employee sees)

```
Open app (store already bound to account)
   │
   ▼
┌──────────────────────────────────────┐
│ 今日推荐 · 紫金港店                    │
│                                       │
│ [潜力款] <型号>  → 朋友圈              │
│  为什么推这条：                        │
│  · 门店1.5km内有2所高校 → 学生客群为主  │
│  · 该型号本店销量占比低于同类商圈门店 64% │
│  · 距双十一还有 21 天                  │
│                                       │
│  [ 查看文案 ]   [ 换一条 ]              │
└──────────────────────────────────────┘
   │ tap
   ▼
Post preview (phone mockup, images from ima, 4-section verification hidden in a fold)
   │
   ▼
[ 一键复制文案 ]  [ 保存图片 ]  [ 已发布 ✓ ]
```

(The card text above is real generator output for store S01; see `data/demo/generated/today_cards.json`.)

- Default is **one post per day** ("今日一条"). "换一条" shows the other slots (活动款 / 新品款 / 顾客问答).
- "已发布 ✓" is how HQ knows the store posted (no auto-posting: 朋友圈 and personal 小红书 have no open posting API; we don't claim otherwise).
- Optional: "拍一张店内实拍" prompt. One real photo of the product on the display table removes most of the AI feel and fits 小红书's rule against faked experience. Real photo is added *alongside* ima images, never replaces the model-verified product image.

---

## 3. Architecture

```
                 ┌─────────────── SIGNALS ────────────────┐
 store profile ─▶│ poi.py        POI → segment weights      │
 sales (fake)  ─▶│ sales.py      under-index per model      │
 promotions    ─▶│ campaigns.py  active national promos     │
 fact cards    ─▶│ releases.py   HQ-verified new products   │
 calendar      ─▶│ calendar.py   upcoming events            │
 questions     ─▶│ questions.py  customer question log      │
                 └──────────────────┬───────────────────────┘
                                    ▼
                 ┌──────────── RECOMMENDER ────────────────┐
                 │ scoring.py   fit + under-index           │
                 │ slots.py     潜力 / 活动 / 新品 / 问答    │
                 │ planner.py   platform rotation (week)    │
                 │ explain.py   "为什么推这条" (template)    │
                 └──────────────────┬───────────────────────┘
                                    ▼  recommendation card (§10.7) = the task
                 ┌──────── EXISTING PIPELINE (kept) ───────┐
                 │ catalog → retrieval (ima) → fact ledger  │
                 │ (temp 0) → reconcile → image plan        │
                 │ → writer (temp high, fact-locked)        │
                 │ → 8A facts / 8B compliance / 8C platform │
                 │ + NEW 8D anti-AI style                   │
                 │ + NEW 8E cross-store similarity          │
                 └──────────────────┬───────────────────────┘
                                    ▼
                 4-section output + phone preview + copy/download
```

Key integration point: today `intake.py` turns a user sentence into a task. The recommender produces **a recommendation card** (format fixed in §10.7) that carries everything intake used to extract, so intake is skipped. Manual input stays available as a fallback tab.

**Shortcut for parallel work:** `scripts/gen_fake_data.py` already contains working reference implementations of the POI weighting, under-index scoring and card building, and it writes `today_cards.json`. WS-D can build the UI on those cards today while WS-B ports the logic into `agent/recommend/`.

### Files

```
agent/recommend/          # NEW - port from scripts/gen_fake_data.py
  poi.py  sales.py  campaigns.py  calendar.py  questions.py
  scoring.py  slots.py  planner.py  explain.py
agent/style/              # NEW
  profile.py      # store voice profile, auto landmark, overrides
  antiai.py       # 8D, reads data/demo/inputs/antiai_blocklist.json
  similarity.py   # 8E cross-store similarity
  hooks.py        # opening-hook pool + deterministic assignment
data/demo/                # READY - data kit (§10)
  inputs/      stores.csv models.csv promotions.json calendar.json segments.json
               angles.json platform_quota.json question_pool.json
               antiai_blocklist.json store_profile_overrides.json poi_cache/
  generated/   (written by the script - never edit by hand)
  templates/   fact_card / poi_cache / recommendation_card examples
scripts/                  # READY
  gen_fake_data.py   # deterministic generator + reference scoring (seed=42)
  fetch_poi.py       # optional: real Amap POI into inputs/poi_cache/
```

All configs are JSON (no PyYAML dependency). The app and the generator read the **same** `segments.json` / `angles.json`, so their logic can't drift.

---

## 4. Signals

### 4.1 Location → audience

**Real path (preferred):** `scripts/fetch_poi.py` calls Amap Web Service v3 (`/v3/geocode/geo` for the store address, `/v3/place/around` for nearby POIs), with the key in `AMAP_KEY` (same handling as ima keys: never in code, README, screenshots or video). Results go to `data/demo/inputs/poi_cache/<store_id>.json`; the generator and app prefer these automatically. The demo then runs offline from the cache.

**Fallback (already working):** if a store has no cache file, the generator builds a fake POI fixture in the same format: one real anchor name per store (e.g. 浙江大学紫金港校区) plus generic `（模拟）住宅小区3`-style neighbours. Nobody is blocked on the Amap key.

**POI type codes** (verified against the Amap classification table, `data/demo/inputs/segments.json`):

| Category | Typecode | Segment | Importance |
|---|---|---|---|
| 高等院校 | 141201 | `student` | 5.0 |
| 中学 | 141202 | `family` (parents buying for kids) | 2.0 |
| 小学 | 141203 | `family` | 2.0 |
| 住宅小区 / 住宅区 | 120302 / 120300 | `family` | 1.5 |
| 商务写字楼 | 120201 | `office` | 1.0 per building (they're numerous) |
| 产业园区 | 120100 | `office` | 2.0 |
| 购物中心 / 商场 | 060101 / 060100 | `shopper` (gifting, walk-in) | 3.0 |

```
raw[s]  = Σ over POIs p within 1.5km in segment s:  importance(p) × exp(-distance(p) / 500m)
w[s]    = raw[s] / Σ raw            # normalized, sums to 1
dominant_segment = argmax w[s]
```

Actual output for S01 (campus, fixture): `{student: 0.533, family: 0.422, office: 0.044, shopper: 0.0}` → explanation line "门店1.5km内有2所高校（浙江大学紫金港校区等）→ 学生客群为主".

**POI wins over the label.** `stores.csv` has an `intended_type` column, but it is used *only* to generate sales. The audience always comes from POI. (Tested: giving residential store S07 a cache containing a university flips it to student-dominant and puts it in the campus peer group.)

### 4.2 Sales (fake)

Per store, per model, weekly units + stock, 12 weeks (§10.5). Used **only** for the under-index score. Never shown in copy; shown to staff only as a relative statement ("销量占比低于同类商圈门店 64%") with a 模拟 badge.

### 4.3 National promotions (fake, demo prices allowed)

`data/demo/inputs/promotions.json`. Each campaign: models, dates, mechanic, optional `price_info` per model, `source`.

Because the organizer allows fake data, demo campaigns may include **demo prices**. That makes the demo stronger, because it shows the real production behaviour: **prices come only from HQ campaign data, never from the LLM.**

**Price-traceability rule (enforced in 8B):**
- A price, discount, subsidy or stock claim may appear in copy **only if it matches an active promotion record for that model exactly** (value + conditions).
- Any other number tied to money is blocked, even if the user types it in ("帮我加上立减500").
- `source: "DEMO"` prices are labelled **演示活动价** in the record and shown with a **[演示活动]** tag in the preview.
- The demo includes one campaign with prices (`DEMO-1111-PRE`, active from Oct 20) and one without (`DEMO-1111-EXP`, Nov 1–11), so both paths can be shown.

Video moment: user adds an invented discount → 8B blocks it and cites the rule.

### 4.4 New releases

A new product is only recommended if its **fact card is `verified`** (§7). Unverified → locked card "新品资料待总部确认，暂不可生成". In the demo, `MODEL_N` launches Oct 28 and starts as `draft`.

### 4.5 Calendar

`data/demo/inputs/calendar.json`: 双十一, 双十二, 期末考试季, 春节 (Feb 6, 2027), 开学季.
Effect: adds a theme to the angle ("购物节前做功课") and a line in the explanation card ("距双十一还有 21 天"). It never invents a discount.

### 4.6 Customer questions

End-of-day prompt for staff: "今天顾客问了什么？" with **preset chips** (`question_pool.json`, 10 chips) plus optional free text/voice.
Next day, the most frequent question (ties go to questions that fit the store's audience) becomes a **顾客问答** card, which always uses the "顾客问答开头" hook.

Rule: a post may say "这几天常有顾客问……" **only if that question exists in this store's log**. Never fabricate customer quotes or reviews. In the demo the log itself is fake data, which is fine; the rule is about the copy not inventing beyond the log.

---

## 5. Recommendation logic

### 5.1 Audience fit

Affinity per model and segment lives in `data/demo/inputs/models.csv` (`aff_student, aff_office, aff_family, aff_shopper`), with a `why_*` column each. **Each `why_*` must cite a KB fact** (weight, battery, screen, ports, performance tier), so the reasoning is grounded even though the score is hand-set.

Use only model IDs from our catalog (`agent/catalog.py`); the template uses placeholders `MODEL_A … MODEL_N` by archetype (light/student, business, creator, family, budget, national best-seller, new release) until WS-A maps them.

```
fit(m, store) = Σ_s  w_store[s] × affinity[m][s]          # in [0,1]
```

### 5.2 Under-index (the "potential" score)

Normalize by store size using **share of store sales**, then compare with **peer stores** (same dominant segment; if a store has no peers, compare with all stores).

```
share(m, store)    = units(m, store, last 8 weeks) / units(all models, store, last 8 weeks)
expected(m, store) = mean share(m, peer) over peer stores
index(m, store)    = share / expected                       # 1.0 = normal, <1 = under-selling
potential(m,store) = fit(m,store) × (1 - index)
```

Eligibility filters (constants at the top of `gen_fake_data.py`; keep identical in `scoring.py`):

| Filter | Value | Why |
|---|---|---|
| `fit ≥ MIN_FIT` | 0.50 | only products that suit the local audience |
| `index ≤ MAX_INDEX` | 0.70 | only clear under-selling, not noise |
| `stock_on_hand > 0` | — | nothing to sell → don't promote |
| `peer units ≥ MIN_PEER_UNITS` | 10 | avoid tiny-number noise |
| not posted in last 7 days | `post_history.json` | avoid repetition |

If no model qualifies, the store simply gets no 潜力款 that day and the default falls to 活动款. That's correct behaviour ("this store is selling normally"), not a bug.

**Worked example** (actual S01 numbers, campus store):

| Model | fit | share here | peer share | index | potential |
|---|---|---|---|---|---|
| MODEL_A (light, long battery) | 0.72 | 8.4% | 23.0% | 0.37 | **0.46** ← pick |
| MODEL_F (best-seller everywhere) | — | — | — | 0.76–1.26 across stores | never picked |

Why not top-sellers: MODEL_F already sells, a post adds little. Why not bottom-sellers: a model that sells badly because it doesn't fit the audience is removed by the fit filter.

### 5.3 Daily slots

| Slot | Source | Selection |
|---|---|---|
| 潜力款 | sales + POI | max `potential` among eligible models |
| 活动款 | promotions | active campaign; among its models, max `fit` |
| 新品款 | fact cards | release within ±30 days; locked unless `verified` |
| 顾客问答 | question log | most frequent question in last 7 days |

**Default card ("今日一条")**: verified new release within ±7 days of launch → 潜力款 → 活动款 → 顾客问答.

**Angle** = one of `angles.json → segment_angles[dominant]` (picked deterministically per store/day/slot) + calendar theme:

| Segment | Angles |
|---|---|
| student | 上课携带、全天续航、手机平板电脑多设备协同、宿舍/图书馆场景 |
| office | 会议与差旅、多任务处理、文档效率、数据安全 |
| family | 上手简单、全家共用、旧电脑资料迁移、长期耐用 |
| shopper | 送礼怎么选、到店体验理由 |

Example of rule 1 in the data: MODEL_A is the 潜力款 at both S01 (campus → "宿舍/图书馆场景") and S10 (mall → "送礼怎么选"). Same product, different angle.

### 5.4 Weekly platform plan

`data/demo/inputs/platform_quota.json` maps HQ's posting requirement to a weekly rotation (Mon→Sun):

```
朋友圈 · 小红书 · 朋友圈 · 小红书 · 公众号 · 小红书 · 朋友圈
```

So Wed Oct 21 = 朋友圈, Fri Oct 23 = 公众号. We don't know HQ's real quota → keep it configurable and say so in the video. Managers/HQ see the week view; staff see only today.

### 5.5 Explanation card ("为什么推这条")

Built from **templates filled with computed values**, never by the LLM, so it can't hallucinate. Order: *where* (POI) → *why this product* (sales / promo / release / question) → *when* (calendar). Each reason carries `is_demo`, which drives the 模拟 badge.

---

## 6. Content quality layer

### 6.1 Store voice profile (zero-effort)

Generated into `data/demo/generated/store_profiles.json`:

| Field | How it's filled | Used for |
|---|---|---|
| `landmark` | **Auto**: `<anchor POI>附近`; store may edit | Local detail only this store can write ("下课走过来五分钟") |
| `voice` | Default by `md5(store_id)` among voices allowed for the dominant segment; store may change | Tone of the post |
| `nickname` | Auto from a small list; editable | Sign-off on 朋友圈 |

Use `md5`, **not** Python's `hash()` (it is randomly salted per process, so assignments would change every run).

Voice presets (`angles.json`): `亲切店长` · `懂技术的店员` · `学长学姐风` (student-dominant stores only; the generator rejects it elsewhere).

Store edits live in `inputs/store_profile_overrides.json`. The demo uses one: S01 → 学长学姐风 + "紫金港校区东门对面". So the two campus stores S01 and S02 get identical targeting signals but different voice and landmark, which is the cleanest demonstration against 千篇一律.

### 6.2 Two-temperature design (answers pain #3)

| Stage | Temperature | Input | Output |
|---|---|---|---|
| Fact extraction (existing ledger) | **0** | KB article for the exact model ID | Locked fact card: each fact with verbatim source quote (`templates/fact_card.example.json`) |
| Writer | **~0.8–0.9** (tune) | Fact IDs only + card (angle, voice, hook, landmark, platform) + promo record if any | Draft where each factual sentence is tagged `[F3]` |
| Checkers 8A–8E | **0** | Draft + fact card + promo record | Pass / targeted rewrite (max 2 rounds, existing loop) |

The writer is told: any spec, number, feature or claim **must** reference a fact ID (or the promo record for prices); anything untagged that sounds factual fails 8A. Tags are stripped before display. Result: wording is creative, facts are fixed.

### 6.3 Anti-AI style check (8D, answers pain #2)

`data/demo/inputs/antiai_blocklist.json`, checked by substring/regex first, then an LLM judge at temp 0.

- Era clichés: 在这个快节奏的时代 · 随着科技的发展 · 在当今社会
- Corporate verbs: 赋能 · 助力 · 打造 · 开启新篇章 · 全新体验 · 极致
- Template structures: `不仅.{0,20}更` · `无论.{0,20}还是.{0,20}都` · 三连反问
- Forced slang: 家人们 · 宝子们 · 绝绝子 · 冲鸭 · 闭眼入
- Sales claims (rule 3): 热销 · 爆款 · 销量第一 · 卖断货
- Absolute claims (最 · 第一 · 唯一 · 顶级 · 全网 · 首选) are **not** an 8D rule: they belong to 8B (`config/banned_words.txt`), which has no allow rule. 8D must not match bare 最/第一 by substring, or it would false-flag 最近 / 第一次.

Structural rules: ≤ 1 rhetorical question; ≤ 2 parallel sentences in a row; emoji limits per platform; **must include one concrete detail** (landmark, specific scene, or logged customer question).

Video moment: same card, **before** (plain LLM) vs **after** (our pipeline), blocklist hits highlighted.

### 6.4 Cross-store similarity check (8E)

After generating today's posts for all stores:
- Compare each post with other stores' same-day posts in the same peer group (character 3-gram Jaccard; default threshold 0.55, `SIMILARITY_THRESHOLD` env-configurable).
- If similarity > threshold → regenerate the later store once with the next hook unused by its peers today, and the next unused angle in the segment's angle list. Model, platform and facts never change; a customer-question card keeps the reserved customer hook. Max one regeneration per store.

**Peer-aware hook/angle assignment (Phase 4):** within a peer group (same dominant segment), stores are sorted by `store_id`; hooks and angles rotate by `peer_rank + days_since_epoch + slot_index`, so stores in the same group get distinct non-customer hooks and distinct angles while the segment's pool allows it. The fixed epoch is `2026-01-01`. The customer hook is reserved for 顾客问答 cards. This replaces the older per-store md5 assignment.

### 6.5 Hard rules (system prompt + checkers)

- Sales data never in copy: no 热销 / 爆款 / 销量第一 / 卖断货.
- No absolute claims: 最 / 第一 / 唯一 / 顶级 / 全网 / 首选 (existing rule, always rephrase).
- **Prices / discounts / subsidies / stock only from an active promotion record, matched exactly** (§4.3). Demo prices carry [演示活动].
- No invented awards, reviews, test results, or customer quotes beyond the question log.
- No competitor disparagement, no unsupported comparisons.
- Images: ima only, matched by model ID (existing).

---

## 7. New-product rule: HQ verifies once, stores generate many

```
New release appears in KB
   │
   ▼
Fact card generated (temp 0, verbatim quotes)  → status: draft
   │
   ▼
HQ view: one person reviews the card, ticks each fact  → status: verified
   │
   ▼
All stores: 新品款 cards unlocked; writers may use ONLY verified card facts
```

- Draft cards are never used for store posts (`locked: true` on the card).
- If KB sources conflict on a fact → that fact stays unverified and is excluded (existing conflict gate; see `conflict` in the fact-card template).
- Demo: `MODEL_N` (launch Oct 28) is `draft`. Verify it live in the HQ tab; with the video date set to Oct 23 it is within 7 days of launch, so it becomes the default card for every store.
- `agent.recommend.reset_demo_state()` clears the in-memory fact-card overrides and data cache between takes; the UI must also clear its session-level 已发布 / question chips.
- Pitch line: *one verification, thousands of accurate posts.*

---

## 8. HQ / manager view

| Panel | Content | Demo data |
|---|---|---|
| 发布情况 | Which stores posted, last 14 days, posting rate per store | `publish_log.csv` (stores have different laziness levels) |
| 待确认新品 | Draft fact cards waiting for verification (§7) | fact card status |
| 本周计划 | Weekly platform rotation | `platform_quota.json` |
| 顾客高频问题 | Aggregated question chips across stores | `customer_questions.json` |
| 推荐分布 | Which models/angles were recommended where | `today_cards.json` |
| 发布效果 *(optional)* | Views / likes / saves / inquiries per post | `engagement_log.csv` |

The last panel was roadmap in v1. Since fake data is allowed, it can be shown cheaply as a preview of the feedback loop, but say clearly in the video that real engagement integration is future work.

---

## 9. Demo views (Gradio tabs)

1. **门店端 · 今日推荐** — store selector (demo only), today's card(s), explanation, generate, preview, copy, "已发布".
2. **三店对比** — same product, same day, side by side as phone previews: S01 campus, S04 CBD, S08 residential, plus **S02, a second campus store**, to show same-type stores still differ. *The key video shot.*
3. **总部端** — panels from §8, including verifying `MODEL_N` live.
4. **手动输入** — existing pull-based flow, kept as fallback.

Retakes: call `agent.recommend.reset_demo_state()` (clears fact-card overrides + data cache) and clear the app session’s 已发布 / question state. Real runs also append `runs/<date>/<timestamp>-<store>-<slot>.json`; `agent.runs.latest_run(card_id)` returns the newest real output for a fallback display. The `runs/` directory is gitignored; these are real outputs and must never be hand-edited.

---

## 10. Demo data kit (fake data, organizer-approved)

### 10.1 What may be fake, what must stay real

| Data | Status | Why |
|---|---|---|
| Stores, sales, stock, promos (incl. demo prices), question log, posting log, engagement | **Fake** | Organizer-approved; Huawei can plug in real feeds with the same schema |
| POI around stores | **Real preferred**, fake fallback | Real makes the regional story undeniable |
| Product facts, specs, images | **Always real (ima KB)** | Pain #3 is exactly about fact accuracy; faking these would undercut our core claim |
| Release *status* (draft/verified) | Fake | Demonstrates the HQ gate |

**Still show the 模拟数据 badge** on sales-, promo- and log-derived content. The audience is Huawei business staff who know their real numbers. Unlabelled fake numbers invite "that's not right" reactions; labelled ones read as "here's where your data plugs in."

### 10.2 Layout

```
scripts/
  gen_fake_data.py          # generator + reference scoring
  fetch_poi.py              # optional real Amap POI
data/demo/
  README.md                 # quick start
  inputs/                   # EDIT THESE
    stores.csv                     12 Hangzhou demo stores
    models.csv                     7 placeholder models + affinity + why
    promotions.json                2 national demo campaigns
    calendar.json                  5 events
    segments.json                  POI typecode → segment, importance, radius, decay
    angles.json                    angles, hooks, voices, nicknames
    platform_quota.json            weekly rotation
    question_pool.json             10 question chips
    antiai_blocklist.json          8D rules
    store_profile_overrides.json   store edits to auto profiles
    poi_cache/                     real Amap results (empty until fetch_poi.py runs)
  generated/                # NEVER EDIT - regenerate
    poi_fixtures/<id>.json         fake POI (only for stores without a cache)
    store_signals.json             segment weights, dominant segment, POI source
    sales_weekly.csv               12 weeks × 12 stores × 6 models
    store_profiles.json            landmark / voice / nickname
    publish_log.csv                14 days posting log
    post_history.json              last 7 days posted (for the repeat filter)
    engagement_log.csv             views/likes/saves per post
    customer_questions.json        question log
    today_cards.json               ← what the store screen shows
    summary.txt                    sanity table
  templates/                # reference shapes
    fact_card.example.json  poi_cache.example.json  recommendation_card.example.json
```

### 10.3 Run

```bash
python scripts/gen_fake_data.py                     # today=2026-10-21, seed=42
python scripts/gen_fake_data.py --today 2026-10-23  # use the actual recording date
```

Standard library only, deterministic. If the output ends with `PROBLEMS:`, fix inputs or change `--seed`.

### 10.4 Input templates

| File | Key fields | Who edits | Notes |
|---|---|---|---|
| `stores.csv` | `store_id, store_name, district, address, intended_type, traffic_tier, anchor_poi, anchor_category, lat, lng` | WS-A | Fictional stores near real landmarks. `intended_type` drives sales generation only. `traffic_tier` 1/2/3 ≈ 15/30/50 units per week. `address` is what `fetch_poi.py` geocodes. |
| `models.csv` | `model_id, display_name, archetype, base_popularity, launch_date, is_new_release, fact_card_status, aff_*, why_*` | **WS-A must fill** | Replace `<...从catalog填写>` with real catalog names; every `why_*` cites a KB fact. `MODEL_F` is the national best-seller (popularity 1.5). `MODEL_N` is the new release. |
| `promotions.json` | `campaign_id, name, models, start, end, mechanic, price_info{model:{label,value,conditions}}, source` | WS-A | `price_info` may be `null`. Only these values may ever appear as prices in copy. |
| `calendar.json` | `event, start, end, theme, segments` | — | |
| `segments.json` | `radius_m, decay_m, categories{typecodes, segment, importance, label}` | WS-B | Shared by generator and app. |
| `angles.json` | `segment_angles, hooks, voices{allowed_segments}, nicknames` | WS-C | |
| `platform_quota.json` | `rotation[7]`, `weekly_minimum` | — | |
| `question_pool.json` | `chips{id:{text, segments}}` | WS-D | Also the UI chip list. |
| `antiai_blocklist.json` | `phrases, patterns, rules` | WS-C | |
| `store_profile_overrides.json` | `{store_id: {voice?, landmark?, nickname?}}` | — | Voice validated against segment. |

### 10.5 How generation works

1. **POI → audience:** real cache if present, else fixture (anchor + generic neighbours by type) → `segment_weights()` → `store_signals.json`.
2. **Sales:** for each store/week/model:
   `λ = TOTAL_UNITS[tier] × season × (gen_fit × popularity / Σ) × planted_multiplier`, units ~ Poisson(λ × lognormal noise). `gen_fit` uses fixed per-type weights (`GEN_WEIGHTS`), *not* POI, so sales and audience stay independent. 开学季 weeks ×1.3. The unreleased `MODEL_N` has no sales.
3. **Under-index** on the last 8 weeks vs. peers (§5.2).
4. **Logs:** profiles (+ overrides), 14-day publish log with a per-store posting propensity (0.35–0.95), post history, engagement for posted entries, 3–8 logged questions per store biased toward the dominant segment.
5. **Cards:** slots, default selection, reasons, hooks, angles → `today_cards.json`.
6. **Sanity checks:** planted stories must surface, best-seller must never be 潜力款, stock-out must be filtered.

**Planted stories** (top of the script; edit freely and re-run):

| Store | Type | Model | Sales × | What the demo shows |
|---|---|---|---|---|
| S01 紫金港店 | campus | MODEL_A | 0.40 | student-fit light model under-sells → 潜力款, study angle |
| S04 钱江新城店 | office | MODEL_B | 0.45 | business model under-sells in the CBD |
| S08 九堡店 | residential | MODEL_D | 0.50 | family model under-sells in a residential area |
| S10 湖滨商圈店 | mall | MODEL_A | 0.45 | **same model as S01, gift angle instead of study** |
| S02 下沙高教园店 | campus | MODEL_A | stock = 0 | high fit, but filtered: nothing to sell |

### 10.6 Current output (seed 42, Oct 21)

```
store type        POI      dominant w     潜力款     index  default card
S01  campus      fixture  student  0.533 MODEL_A  0.365  潜力款 MODEL_A
S02  campus      fixture  student  0.5   -        -      活动款 MODEL_A
S03  campus      fixture  student  0.596 MODEL_E  0.595  潜力款 MODEL_E
S04  office      fixture  office   0.781 MODEL_B  0.525  潜力款 MODEL_B
S05  office      fixture  office   0.81  -        -      活动款 MODEL_F
S06  office      fixture  office   0.704 -        -      活动款 MODEL_F
S07  residential fixture  family   0.98  -        -      活动款 MODEL_D
S08  residential fixture  family   0.832 MODEL_D  0.504  潜力款 MODEL_D
S09  residential fixture  family   0.923 -        -      活动款 MODEL_D
S10  mall        fixture  shopper  0.52  MODEL_A  0.561  潜力款 MODEL_A
S11  mall        fixture  shopper  0.47  -        -      活动款 MODEL_F
S12  mall        fixture  shopper  0.439 -        -      活动款 MODEL_F

best-seller MODEL_F index range: 0.76-1.26 (should hover ~1.0)
stock-out check: S02/MODEL_A stock=0 (must not be 潜力款)
All checks passed.
```

S03's MODEL_E pick is not planted; it comes from random noise in a small store. It's plausible (budget model, student area), so we keep it: real data has picks like this too.

### 10.7 Recommendation card contract (recommender → pipeline → UI)

Full example: `templates/recommendation_card.example.json`. Fields:

| Field | Meaning |
|---|---|
| `card_id, store_id, store_name, date` | identity |
| `slot, slot_label` | `potential/潜力款`, `promo/活动款`, `new_release/新品款`, `customer_question/顾客问答` |
| `model_id, display_name` | product; writer must fetch facts for exactly this ID |
| `platform` | from weekly rotation |
| `segment, segment_label, angle, calendar_theme` | targeting → writer brief |
| `scenario` | explicit Scenario key (calendar-aware; e.g. `campus_daily`, `holiday`, `new_launch`) |
| `hook{id,label}, voice{id,label}, landmark, nickname` | variation → writer brief |
| `reasons[{text, source, is_demo}]` | explanation card; `is_demo` → 模拟 badge |
| `promo{campaign_id, name, mechanic, price_info, source}` | the **only** allowed price source |
| `question{chip_id, text, count}` | for 顾客问答 |
| `locked, locked_reason` | `fact_card_draft` → show "待总部确认", don't generate |
| `scores{fit, index, potential, share, peer_share}` | debug / HQ view; never in copy |
| `is_default` | the "今日一条" card |

### 10.8 Common changes

- **Map real models:** edit `models.csv` (keep IDs or rename everywhere, including `PLANTED`/`STOCKOUT` in the script and `promotions.json`).
- **Add a store:** add a row to `stores.csv` with an `anchor_category` from `segments.json`.
- **Change a story:** edit `PLANTED` in the script; re-run; read the sanity table.
- **Recording day:** run with `--today 2026-10-23` (platform becomes 公众号; `MODEL_N` is 5 days from launch, so verifying it makes it the default card).
- **Real POI:** `export AMAP_KEY=...`, run `fetch_poi.py S01` first, inspect the file, then all stores. Expect some picks to change: that's POI winning over the label, and worth saying in the video.

---

## 11. Build plan (demo includes everything)

Now: **Wed Oct 21 morning**. Deadline: **Fri Oct 23, 17:00**.

### Workstreams

| WS | Owner | Status / tasks |
|---|---|---|
| A · Data | TBD | **Kit ready.** Remaining: map real models + `why_*` in `models.csv` (~30 min); optional Amap key + `fetch_poi.py`; re-run, check sanity table. |
| B · Recommender | TBD | Port `segment_weights`, `under_index`, `build_cards` from the script into `agent/recommend/`; keep constants identical; output must match `today_cards.json`. |
| C · Quality | TBD | Writer brief from card fields; fact-ID tagging; two-temp config; 8D from `antiai_blocklist.json`; 8B price-traceability; 8E similarity. |
| D · UI | TBD | Build all tabs on `generated/today_cards.json` **now**; swap to live recommender when B lands. HQ panels from the generated logs. 模拟 badges. |
| E · Video | TBD | Storyboard §12; record Oct 23 morning. |

### Timeline

| When | Milestone |
|---|---|
| Wed Oct 21 | Team reviews v2. A maps models. B ports scoring. C wires card → writer + 8D + price rule. D builds store tab + 三店对比 on generated cards. |
| Thu Oct 22 day | Integration: live recommender → pipeline → UI. HQ verify flow. 8E. Amap swap if key ready. |
| **Thu Oct 22 night** | **Feature freeze.** Re-generate with `--today 2026-10-23`. Run every video scenario end to end; fix only bugs. |
| Fri Oct 23 morning | Record + edit. **Submit by ~15:00** (2h buffer). |

### If we fall behind: cut order

Cut from the top first; each cut item becomes a roadmap slide with a mock screenshot:

1. Engagement panel (`engagement_log.csv`)
2. Voice input for customer questions (keep chips)
3. Weekly plan view (keep daily rotation)
4. 8E cross-store similarity (voice + landmark + hooks already create variety)
5. Real Amap POI (fixtures already work)

**Never cut:** today's card + explanation, 三店对比, two-temperature/fact lock, 8D before/after, price-traceability block, new-product verify gate. These carry the three pains.

---

## 12. Video storyboard (~4–5 min, all real runs)

| Time | Scene | Pain |
|---|---|---|
| 0:00–0:20 | The three problems, one line each, in Huawei's own framing | — |
| 0:20–1:00 | Staff POV (S01): open app → today's card → "为什么推这条" → tap → preview → copy. **On-screen timer** (< 30 s). | #1 |
| 1:00–1:40 | 三店对比: S01 / S04 / S08 + S02. Point out landmark, voice, angle differences, especially S01 vs S02 (same type, different posts). | #2 |
| 1:40–2:20 | Accuracy: fact card (temp 0) → writer (fact-tagged) → checker catches a planted error (confusable model spec) **and** an invented discount → blocked/rewritten. | #3 |
| 2:20–2:50 | Anti-AI: plain LLM output vs ours, blocklist hits highlighted. | #2 |
| 2:50–3:20 | New product: MODEL_N locked → HQ verifies → becomes every store's 今日一条. | #3 |
| 3:20–3:50 | HQ view: posting rate per store, customer questions, weekly plan. | #1 |
| 3:50–4:20 | Architecture + what's real (POI, KB facts, pipeline) vs simulated (sales, promos, logs) + "your data plugs in here" (§10.4 schemas). | trust |
| 4:20–4:40 | Roadmap: real sales feed, engagement feedback loop, mini-program. | — |

Rules for the video: no hand-edited outputs; 模拟 badges visible; never show API keys or Client ID; ima knowledge base IDs stay hidden.

---

## 13. Risks and open questions

| Risk | Mitigation |
|---|---|
| Fake data looks random or staged | Planted stories with clear logic; sanity checks; noise picks kept as realism; label 模拟 |
| Demo price mistaken for a real Huawei price | `演示活动价` label + [演示活动] tag; price-traceability rule shown blocking invented prices |
| Placeholder model names leak into the video | WS-A maps `models.csv` before any recording; grep generated files for `<` before freeze |
| Same-type stores still sound alike | Voice + landmark + hooks + 8E; S01 vs S02 in the video |
| Writer temperature too high → more check failures | Tune on all 12 stores Thursday; cap rewrites at 2 (existing) |
| Amap quota / network during recording | Everything runs from cache or fixtures |
| `fetch_poi.py` untested (written without a key) | Run on one store first; fixtures remain the fallback |
| Recommender port drifts from the script | Same JSON configs; compare `agent/recommend` output with `today_cards.json` |
| Scope too big | Cut order §11; feature freeze Thu night |

Open questions for the team:
1. Who owns each workstream (A–E)?
2. Which real catalog models map to `MODEL_A … MODEL_N`, and which one plays the new release?
3. Does anyone register an Amap key today, or do we go with fixtures?
4. Video format: screen recording + voice-over, or a face-to-camera intro too?
5. Are the demo prices in `promotions.json` plausible enough for the chosen models? (Adjust after mapping.)
