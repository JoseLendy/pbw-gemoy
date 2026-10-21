#!/usr/bin/env python3
"""
Build samples/ from REAL run records in runs/ (never hand-written, never edited afterwards).

    python scripts/export_samples.py --today 2026-10-23

Selection: the prepared posts of S01 + S02 (same store type), S04 (CBD), S08 (residential), S10 (mall,
same product as S01, different angle); one 新品款 locked card (the lock message only); one EditBlocked for
「加上立减500」 if a real record exists; one NeedsReview with its failing sentences.

Each sample shows the store type, audience, 为什么推这条 (simulated reasons marked 模拟数据), the
publishable text exactly as staff copy it, image references by file name / caption only, a condensed
四、核验结果 (fact ID → field → source article, check results), the run timestamp and the model ID.

Before writing, every sample is scanned: no key-like token, no configured secret value, no KB media id and
no verbatim ledger quote outside the publishable text. Any hit aborts without writing. Dev-mode (fake)
records are never used.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT = ROOT / "samples"
STAGES = ("8A", "8B", "8C", "8D")
TYPE_CN = {"campus": "校园店", "office": "写字楼（CBD）店", "residential": "社区店", "mall": "商圈店"}
PLATFORM_CN = {"moments": "朋友圈", "xiaohongshu": "小红书", "wechat_article": "公众号", "poster": "海报",
               "douyin": "抖音图文"}
TAG_RE = re.compile(r"\s*\[F\d+\]")


class LeakError(RuntimeError):
    pass


# ---------------------------------------------------------------- records
def _records(runs_dir: Path, day: str, allow_dev: bool = False) -> list[dict]:
    out = []
    for p in sorted((runs_dir / day).glob("**/*.json")):
        try:
            d = json.loads(p.read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if d.get("dev_mode") and not allow_dev:
            continue
        d["_path"] = p
        out.append(d)
    return out


def _post_text(result: dict) -> str:
    from agent.formatter import render_publishable
    from agent.schemas import Post, PostImage
    pd = dict(result["post"])
    pd["images"] = [PostImage(**i) for i in pd.get("images") or []]
    return render_publishable(Post(**pd))


# ---------------------------------------------------------------- rendering
def _store_meta(store_id: str) -> tuple[str, str]:
    from agent.recommend.store_data import load_store_data
    data = load_store_data()
    st = data.store(store_id)
    seg = data.signals[store_id]["dominant"]
    return TYPE_CN.get(st.get("intended_type"), st.get("intended_type", "")), data.seg_cfg["segment_labels"][seg]


def _reasons(card: dict) -> list[str]:
    return [f"- {r['text']}" + ("（模拟数据）" if r.get("is_demo") else "") for r in card.get("reasons") or []
            if r.get("text")]


def _images(result: dict) -> list[str]:
    plan = {it["image"]["media_id"]: it["image"] for it in (result.get("plan") or {}).get("items", [])}
    lines = []
    for im in (result.get("post") or {}).get("images") or []:
        ref = plan.get(im.get("media_id"), {})
        lines.append(f"- {ref.get('title', '（图片）')}：{im.get('caption') or ref.get('caption', '')}")
    return lines or ["- （无配图）"]


def _verification(result: dict) -> list[str]:
    facts = {f["id"]: f for f in (result.get("ledger") or {}).get("facts", [])}
    used = list(dict.fromkeys(re.findall(r"\[(F\d+)\]", json.dumps(result.get("post"), ensure_ascii=False))))
    lines = ["| 事实编号 | 字段 | 来源文章 |", "|---|---|---|"]
    for fid in used:
        f = facts.get(fid)
        if f:
            src = "/".join((f.get("source_path") or f.get("source_title") or "").split("/")[-2:])
            lines.append(f"| {fid} | {f.get('attribute', '')} | {src} |")
    issues = (result.get("report") or {}).get("issues", [])
    marks = []
    for s in STAGES:
        errs = [i for i in issues if i.get("stage") == s and i.get("severity") == "error"]
        marks.append(f"{s} {'✅' if not errs else '❌ ' + '、'.join(i.get('code', '') for i in errs)}")
    lines += ["", "核验：" + " · ".join(marks) + f" · 改写 {result.get('loops', 0)} 轮"
              + (f" · 兜底：{result['fallback']}" if result.get("fallback") else "")]
    return lines


def _header(rec: dict, title: str) -> list[str]:
    sid = rec.get("store_id", "")
    stype, seg = _store_meta(sid) if sid else ("", "")
    model = rec.get("model") or ""
    return [f"# {title}", "",
            f"- 门店：{sid} {rec.get('store_name', '')} · {stype} · 客群：{seg}",
            f"- 型号：`{model}`",
            f"- 运行时间（UTC）：{rec.get('timestamp', '')} · 写作温度 {(rec.get('temperatures') or {}).get('writer', '')}",
            f"- 来源记录：{rec.get('kind', '')} · `{rec['_path'].name}`" if "_path" in rec else "",
            ""]


def render_post_sample(rec: dict) -> tuple[str, str]:
    result, card = rec["result"], rec.get("card") or {}
    slot, platform = card.get("slot_label") or rec.get("slot", ""), (result.get("post") or {}).get("platform", "")
    title = f"{rec['store_id']} {rec.get('store_name', '')} · {slot} · {PLATFORM_CN.get(platform, platform)}"
    body = _header(rec, title) + ["## 为什么推这条", ""] + (_reasons(card) or ["- —"])
    body += ["", f"内容角度：{(result.get('task') or {}).get('angle', '')} · 开头方式：{(result.get('task') or {}).get('hook', '')}", ""]
    body += ["## 可直接发布的文案（店员复制即发）", "", "```text", _post_text(result), "```", ""]
    body += ["## 配图（只列文件名与说明，不含图片文件）", ""] + _images(result) + [""]
    body += ["## 四、核验结果（精简）", ""] + _verification(result) + [""]
    name = f"{rec['store_id']}-{rec.get('slot') or card.get('slot', '')}-{platform}.md"
    return name, "\n".join(l for l in body if l is not None)


def render_locked_sample(rec: dict) -> tuple[str, str]:
    r = rec["result"]
    card = r.get("card") or {}
    body = _header(rec, f"{rec['store_id']} · 新品款 · 锁定") + [
        "## 结果", "", f"「{r.get('message', '')}」", "",
        f"新品资料（fact card）状态为 draft，总部确认前不调用知识库或大模型，也不生成任何文案（`{r.get('reason', '')}`）。",
        "", "## 为什么推这条", ""] + (_reasons(card) or ["- —"]) + [""]
    return f"{rec['store_id']}-new_release-locked.md", "\n".join(body)


def render_blocked_sample(rec: dict) -> tuple[str, str]:
    r = rec["result"]
    body = _header(rec, f"{rec['store_id']} · 编辑被拦截：「{r.get('instruction', '')}」") + [
        "## 结果", "", r.get("message", ""), "",
        "价格、优惠、补贴说法只能来自总部当前有效的活动记录；这条编辑在调用写作之前就被拦下，原文案保持不变。", ""]
    return f"{rec['store_id']}-edit-blocked.md", "\n".join(body)


def render_review_sample(rec: dict) -> tuple[str, str]:
    r = rec["result"]
    draft = r.get("draft") or {}
    text = _post_text(draft) if draft.get("post") else ""
    for f in r.get("failing") or []:
        s = TAG_RE.sub("", f.get("sentence") or "").strip().rstrip("。！？")
        if s and s in text:
            text = text.replace(s, f"【{s}】", 1)
    card = r.get("card") or {}
    body = _header(rec, f"{rec['store_id']} · 需人工确认（NeedsReview）") + [
        "## 为什么推这条", ""] + (_reasons(card) or ["- —"]) + [
        "", "## 草稿（未发布；【】内为未通过核验的句子）", "", "```text", text, "```", "", "## 未通过的原因", ""]
    body += [f"- {f.get('stage')} · {f.get('code')}：{f.get('reason')}" for f in r.get("failing") or []]
    body += ["", f"已尝试：{' → '.join(r.get('attempts') or [])}", "",
             "删去问题句子和改用下一条推荐都没有通过全部核验，所以没有交付任何文案，转人工确认。", ""]
    return f"{rec['store_id']}-needs-review.md", "\n".join(body)


# ---------------------------------------------------------------- leak scan
def scan(text: str, publishable: str, ledgers: list[dict], media_ids: set[str]) -> list[str]:
    from scripts.freeze_check import SECRET_ENV, SECRET_RES
    import os
    problems = []
    if any(r.search(text) for r in SECRET_RES):
        problems.append("key-like token")
    secrets = [v for v in (os.getenv(k) for k in SECRET_ENV) if v and len(v) >= 8]
    if any(v in text for v in secrets):
        problems.append("configured secret value")
    if any(m and m in text for m in media_ids):
        problems.append("KB media id")
    outside = text.replace(publishable, "") if publishable else text
    for led in ledgers:
        for f in led.get("facts", []):
            q = (f.get("quote") or "").strip()
            if len(q) >= 12 and q in outside:
                problems.append(f"verbatim KB quote ({f.get('id')})")
                break
    return problems


def _media_ids(result: dict) -> set[str]:
    ids = set()
    for it in (result.get("plan") or {}).get("items", []):
        ids.add(it.get("image", {}).get("media_id", ""))
    for s in result.get("sources") or []:
        ids.add(s.get("media_id", ""))
    return {i for i in ids if i}


# ---------------------------------------------------------------- selection
POST_STORES = ("S01", "S02", "S04", "S08", "S10")


def select(records: list[dict]) -> dict:
    prepared = {r["store_id"]: r for r in records if r.get("kind") == "prepared"}
    picks = {"posts": [prepared[s] for s in POST_STORES if s in prepared and prepared[s].get("status") == "RunResult"]}
    locked = [r for r in records if (r.get("result") or {}).get("reason") == "fact_card_draft"]
    picks["locked"] = locked[-1] if locked else None
    blocked = [r for r in records if r.get("kind") == "edit_blocked" and "立减500" in (r.get("result") or {}).get("instruction", "")]
    picks["blocked"] = blocked[-1] if blocked else None
    review = [r for r in records if (r.get("result") or {}).get("failing") is not None]
    picks["review"] = review[-1] if review else None
    return picks


def build(day: str, runs_dir: Path, out: Path, allow_dev: bool = False) -> list[tuple[str, str]]:
    records = _records(runs_dir, day, allow_dev)
    picks = select(records)
    files: list[tuple[str, str, str, dict]] = []      # name, text, publishable, result
    for rec in picks["posts"]:
        name, text = render_post_sample(rec)
        files.append((name, text, _post_text(rec["result"]), rec["result"]))
    for key, fn in (("locked", render_locked_sample), ("blocked", render_blocked_sample),
                    ("review", render_review_sample)):
        if picks[key]:
            name, text = fn(picks[key])
            r = picks[key]["result"]
            res = r.get("draft") or r.get("prev") or r
            files.append((name, text, _post_text(res) if res.get("post") else "", res))
    ledgers = [res.get("ledger") or {} for *_, res in files]
    media = set().union(*[_media_ids(res) for *_, res in files]) if files else set()
    readme = render_readme(picks, day)
    problems = []
    for name, text, pub, _ in files:
        problems += [f"{name}: {p}" for p in scan(text, pub, ledgers, media)]
    problems += [f"README.md: {p}" for p in scan(readme, "", ledgers, media)]
    if problems:
        raise LeakError("; ".join(problems))
    out.mkdir(parents=True, exist_ok=True)
    written = [(n, t) for n, t, *_ in files] + [("README.md", readme)]
    for name, text in written:
        (out / name).write_text(text.rstrip() + "\n", encoding="utf-8")
    return written


def render_readme(picks: dict, day: str) -> str:
    rows = []
    posts = {r["store_id"]: r for r in picks["posts"]}

    def link(rec, fn):
        return f"[{fn(rec)[0]}]({fn(rec)[0]})"

    sim = next((p for p in (posts.get("S01") or {}).get("similarity", []) if {p["store_a"], p["store_b"]} == {"S01", "S02"}), None)
    what = {
        "S01": "地域定向：校园店（高校周边 → 学生客群）的今日一条",
        "S02": "同类型门店也不雷同：与 S01 同为校园店" + (f"，文案相似度 {sim['after']}（3-gram Jaccard，阈值 0.55）" if sim else ""),
        "S04": "地域定向：写字楼（CBD）店 → 上班族客群",
        "S08": "地域定向：社区店 → 家庭客群",
        "S10": "同一型号、不同角度：与 S01 同型号，商圈店换成送礼/到店体验角度",
    }
    for sid in POST_STORES:
        if sid in posts:
            rows.append(f"| {link(posts[sid], render_post_sample)} | {what[sid]}；事实可追溯（四、核验结果：事实编号 → 来源文章） |")
    if picks["locked"]:
        rows.append(f"| {link(picks['locked'], render_locked_sample)} | 新品闸门：资料未经总部确认时直接锁定，不生成 |")
    if picks["blocked"]:
        rows.append(f"| {link(picks['blocked'], render_blocked_sample)} | 价格拦截：「加上立减500」没有活动记录，写作前即拦截 |")
    if picks["review"]:
        rows.append(f"| {link(picks['review'], render_review_sample)} | 兜底：两轮改写、删句、换卡后仍未通过 → 需人工确认，不交付 |")
    return "\n".join([
        "# 输出样例", "",
        f"由 `scripts/export_samples.py` 从 {day} 的**真实运行记录**（runs/，未纳入仓库）自动导出，未经手工编辑。",
        "文案为店员复制即发的版本（已去掉事实编号）；配图只列文件名与说明，不含图片文件；不含知识库原文引用。", "",
        "| 样例 | 展示什么 |", "|---|---|", *rows, "",
        "**说明**：门店销量、库存、活动（含演示活动价）、顾客提问与发布记录均为**模拟数据**（标注「模拟数据」/「演示活动」）；"
        "产品事实与图片来自 ima 共享知识库，可按事实编号追溯到来源文章。", ""])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--today", default="2026-10-23")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)
    from agent.runs import RUNS_DIR
    try:
        written = build(args.today, RUNS_DIR, Path(args.out))
    except LeakError as e:
        print(f"NOT written, leak check failed: {e}")
        return 1
    posts = sum(1 for n, _ in written if n not in ("README.md",) and not n.endswith(("locked.md", "blocked.md", "review.md")))
    print(f"wrote {len(written)} files to {args.out} ({posts} posts)")
    missing = [s for s in POST_STORES if not any(n.startswith(s + "-") and "locked" not in n for n, _ in written)]
    if missing:
        print(f"no real prepared post for {missing}: run scripts/prepare_today.py first")
    return 0


if __name__ == "__main__":
    sys.exit(main())
