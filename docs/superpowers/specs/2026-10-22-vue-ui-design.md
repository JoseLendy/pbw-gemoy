# Vue + FastAPI UI (feat/ui-polish) — design

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
- Images: `/api/image/{token}` serves bytes from the in-process cache by opaque token; never a media id.
- `agent/ui_data.py`: unchanged surface; `generate()` / `edit()` / `compare()` / `baseline()` accept an
  optional `on_progress` passthrough.
- Retired: `app.py`, `ui/*_tab.py`, `ui/theme.py`, `static/phone.css`; Gradio-bound tests replaced by tests
  against `ui/state.py` views and the FastAPI app (TestClient, fakes only).

## Screens
Shell: video bg, hero (title · 演示日期), frosted tab bar (门店端·今日推荐 / 手机发布 / 三店对比 / 总部端 /
对照组 / 手动输入), status HUD bottom-left (密钥 shows 已配置 only), footer.
1. 门店端: store select, 店员/店长, 平台版本 pills, 周进度; 今日一条 card (headers, 🔒, 由店长发布, 为什么推这条
   + 模拟数据 badges); 生成/重新生成/生成公众号文章, 换一条 → slot buttons; status area (edit-blocked,
   recovery + 显示最近一次真实运行结果, 导购话术, fallback note, banner, 需人工确认, stop, progress);
   quick edits 短一点/换卖点/换个角度/加上立减500; phone stage with zoom and spinner; editable 正文 +
   检查并保存/恢复原文 + edit status; 复制文案 · 下载发布包 · 下载 .md · 保存图片 · 标记为已发布; 四段式 fold;
   顾客提问 chips.
2. 手机发布: final text + plain images + 复制文案; empty-state note.
3. 三店对比: product + platform, 4 phones in a row at 1920, meta, summary (stored-first), 8E table.
4. 总部端: 发布情况, 新品审核 + 确认发布, 顾客高频问题, 本周计划, 推荐分布, 重置演示.
5. 对照组: 「对照组：未经约束的普通大模型输出」 + 8D hits | 我们的结果 phone + 四、核验结果; stored-first.
6. 手动输入: Davin's flow (composer, examples, clarification, phone + zoom/换平台, 导购话术, banner,
   quick edits, copy box, 复制正文/下载 .md/下载图片, report fold, 重新输入) + 全平台.

## Hard rules carried over
Headings verbatim; 模拟数据 / 演示 / 对照组 / 需人工确认 / banner always visible; no keys, IDs, raw errors,
"MODEL_" or "<…>"; post text at full contrast; behaviour of generation, edit+check, export, platform
versions, weekly progress, 确认发布, 重置演示 unchanged; tests green.
