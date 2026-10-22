# Vue + FastAPI UI (feat/ui-polish) — design

> **Status: shipped** (merged to `main`). The Screens section below describes what shipped; the original goal text is kept.

Goal: the look and stack of branch `Davin` (Vue 3 + Vite + FastAPI, video background, frosted glass,
Huawei-red buttons, phone simulator with 5 skins, page transitions, typewriter reveal, zoom / 换平台
tools) with **every feature of the Gradio UI on feat/ui-polish** (six tabs, all gating rules), served as
one process on port 7861. Backend untouched (`agent/` except `agent/ui_data.py`).

## Architecture
- `server.py` (FastAPI): `/api/*` JSON + NDJSON streams, serves `frontend/dist` as static. Sessions are a
  server-side dict keyed by a client-generated `session_id` (same dict shape as the old `gr.State`).
  Slow calls (generate / edit / compare / baseline / manual) run in a 4-slot pool and stream
  `{"event":"progress"}` lines then one terminal `{"event":"view"}` line. Rate limits kept.
- `ui/state.py`: Gradio-free port of `ui/store_tab.py` session logic (prepared-first, publish/edit
  gating, delivered card, recovery, reset token, inline edit check, exports). `render()` returns a dict
  view instead of a Gradio tuple.
- `ui/compare_view.py`, `ui/hq_view.py`, `ui/baseline_view.py`: bodies of the old tabs minus `gr.*`.
- `ui/components.py` kept; phone / banner / NeedsReview HTML is rendered by Vue via `v-html` and restyled
  by `frontend/src/style.css` (Davin's file + the existing skins).
- Images: embedded in the phone HTML as data URIs from the in-process cache; never a media id or signed URL in the page. 保存图片 / 发布包 download through `/api/store/save-image` and `/api/store/export-zip`.
- `agent/ui_data.py`: unchanged surface; `generate()` / `edit()` / `compare()` / `baseline()` accept an
  optional `on_progress` passthrough.
- Retired: `app.py`, `ui/*_tab.py`, `ui/theme.py`, `static/phone.css`; Gradio-bound tests replaced by tests
  against `ui/state.py` views and the FastAPI app (TestClient, fakes only).

## Screens (as shipped)

The first draft planned a video-background shell with six frosted tabs. The redesign shipped as a **light
pastel sidebar app** (sidebar on desktop, bottom tab bar on phones), with a login page and the two demo
views moved behind an engineer passcode. 手机发布 was removed: the 门店端 result already has 复制文案 and
the 发布包 download.

Sidebar: logo · 演示日期; nav 门店端 / 生成 / 总部端 / 登录; 演示功能 group (四店对比 / 对照组) only after
unlock; account chip (门店 + 身份, 总部运营, or 未登录); 系统状态 fold (知识库, 索引, 模型, 密钥 shows 已配置
only, 开发模式 + 模拟数据 note). Tabs are deep-linkable with `#tab=<key>` (old `store` / `manual` keys still
work) and `#store=S0x`.

1. **门店端** (`HomeView.vue`, default): 你好，<门店> · date · role. 今日一条 tile (header incl. 生成于 time,
   platform tag, 🔒 + 「去总部端确认发布」 for a locked 新品款, notice, 为什么推这条 + 模拟数据 badges); platform
   pills 朋友圈 / 小红书 / 公众号 / 海报 / 抖音; 生成 / 重新生成 / 生成公众号文章; 换一条 → slot buttons. Result
   card: progress line, phone stage with zoom, quick edits 短一点 / 换卖点 / 换个角度 / 加上立减500, edit
   message, recovery + 显示最近一次真实运行结果, status, banner, editable 正文 + 检查并保存 / 恢复原文 + edit
   status, 复制文案 · 下载 .md · 发布包 · 保存图片, 标记为已发布, 四段式 fold. Aside: 本周发布, 今天顾客问了什么？
   chips, 导购话术, 切换门店账号.
2. **生成** (`ClickView.vue`): 点选 — four steps 产品 → 顾客 → 场景 → 平台 with a 你的选择 summary and
   生成软文; 直接输入 — one sentence (Enter to generate), clarification options + 继续生成. Result: phone,
   banner, quick edits 短一点 / 换卖点 / 换个角度, 正文 copy box, 复制正文 / 下载 .md, 全平台, report fold,
   talk card (导购话术) in the aside, 重新选择.
3. **总部端** (`HqView.vue`): 发布情况, 本周计划, 推荐分布 (今日一条), 新品上市审核 + 确认发布, 顾客高频问题,
   重置演示.
4. **登录** (`LoginView.vue`): choose store (12) and 身份 (店员 / 店长), or 总部运营; 当前账号; 工程师入口
   (passcode checked server-side against `ENGINEER_PASSCODE`; hides views, not access control).
5. **四店对比** (`CompareView.vue`, engineer): product + platform, four stores side by side, stored set first,
   「生成四店对比」 live; similarity summary and 8E table.
6. **对照组** (`BaselineView.vue`, engineer): 「对照组：未经约束的普通大模型输出」 + 8D hits vs our phone +
   四、核验结果; stored first.

## Hard rules carried over
Headings verbatim; 模拟数据 / 演示 / 对照组 / 需人工确认 / banner always visible; no keys, IDs, raw errors,
"MODEL_" or "<…>"; post text at full contrast; behaviour of generation, edit+check, export, platform
versions, weekly progress, 确认发布, 重置演示 unchanged; tests green.
