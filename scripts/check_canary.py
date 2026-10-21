#!/usr/bin/env python3
"""
Checker canary: planted-error drafts must be caught; clean drafts must pass. Runs the full check stack
(8A–8D with their LLM layers, main model) once per draft. No writer, no rewrites.

    RUN_E2E=1 python scripts/check_canary.py --today 2026-10-23     # real ledger + real LLM judges
    python scripts/check_canary.py --fake                           # plumbing on synthetic DemoBook

Drafts are built at run time from the target model's own ledger facts (nothing from the KB is stored in
this file). Planted errors: wrong spec value, wrong tag with a correct value, a price with no promotion
record, the price of a different model, untagged 新品首发, an invented customer quote, 热销/爆款,
赋能 + 不仅…更…, and a MateBook 14 2024 spec stated under MateBook 14 (鸿蒙版).
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

TARGET, SIBLING = "matebook-14-harmonyos", "matebook-14-2024"
FAKE_TARGET, FAKE_SIBLING = "demobook-14", "demobook-14-se"
PREFERRED = ("weight", "battery_capacity", "screen_size", "refresh_rate", "brightness")


@dataclasses.dataclass
class Case:
    name: str
    planted: bool
    caught: bool = False
    hits: list = dataclasses.field(default_factory=list)       # (stage, code, span)
    reasons: list = dataclasses.field(default_factory=list)    # (stage, code, span, message)


def _numeric(ledger, exclude=()):
    for attr in PREFERRED:
        f = next((f for f in ledger.facts if f.attribute == attr and f.norm_value is not None
                  and f.id not in exclude), None)
        if f:
            return f
    return next(f for f in ledger.facts if f.norm_value is not None and f.id not in exclude)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--today", default="2026-10-23")
    ap.add_argument("--fake", action="store_true")
    args = ap.parse_args(argv)
    if not args.fake and os.environ.get("RUN_E2E") != "1":
        print("check_canary.py uses real deps (ima + LLM). Set RUN_E2E=1 to run it, or pass --fake.")
        return 2

    from agent.fact_cache import get_facts
    from agent.pipeline import Deps
    from agent.recommend.store_data import cards_for, default_card
    from agent.recommend.to_task import card_to_task
    from agent.schemas import ImagePlan, PlannedImage, PostImage, Post
    from agent.checks.prices import valid_price_record

    try:
        deps = Deps.fake() if args.fake else Deps.real()
    except Exception as e:  # noqa: BLE001 - e.g. the KB mirror is missing: say why, no traceback
        print(f"真实依赖不可用：{getattr(e, 'msg', None) or e}")
        return 2
    if args.fake:   # the real check stack with the fake LLM (Deps.fake's run_checks is canned)
        from agent.checks import run_all
        deps.run_checks = run_all
    target, sibling = (FAKE_TARGET, FAKE_SIBLING) if args.fake else (TARGET, SIBLING)
    day = args.today
    bundle, ledger = get_facts(deps, target, day)
    _, sib_ledger = get_facts(deps, sibling, day)
    siblings = {sibling: sib_ledger}

    def task_for(store, slot):
        card = next(c for c in cards_for(store, day) if c.slot == slot)
        return card_to_task(dataclasses.replace(card, model_id=target))

    plain = task_for("S01", default_card("S01", day).slot)              # no price record
    promo_card = next((c for c in cards_for("S02", day) if c.slot == "promo"), None)
    promo = card_to_task(dataclasses.replace(promo_card, model_id=target)) if promo_card else None
    rec = valid_price_record(card_to_task(promo_card)) if promo_card else None

    images = bundle.images[:2]
    plan = ImagePlan(platform="moments", items=[PlannedImage(im, "文末", im.caption) for im in images])
    post_images = [PostImage(im.media_id, "文末", im.caption) for im in images]
    a = _numeric(ledger)
    b = _numeric(ledger, exclude={a.id} | {f.id for f in ledger.facts if f.attribute == a.attribute})
    invite = f"店在{plain.landmark}附近，想上手可以过来看看。" if plain.landmark else "想上手可以来店里看看。"
    cta = "有问题可以私信我。"          # no 周末 / opening-hours promise: the store data has none

    def draft(*sentences, task=None):
        return Post(platform="moments", title="", intro="", body=[" ".join(sentences), invite],
                    cta=cta, tags=["门店推荐"],
                    selling_points=[a.id], images=copy.deepcopy(post_images)), (task or plain)

    # Clean drafts are built strictly from the ledger (the writer brief's rules): only tagged facts, values copied
    # verbatim (qualifiers included), usage as the reader's own question, nothing implied beyond the fact.
    #  - claim: a KB 可用结论 quoted verbatim; it carries its own suitability wording and caveats.
    #  - entity: one fact from a category with no 表达边界 lines, so no qualifier can be missing.
    bounded = {bd.get("category") for bd in (ledger.boundaries or []) if bd.get("category")}
    blocked = {fid for c in (ledger.conflicts or []) for fid in c.fact_ids}
    usable = [f for f in ledger.facts if f.id not in blocked]
    claim = next((f for f in usable if f.kind == "claim" and "适合" in f.value),
                 next((f for f in usable if f.kind == "claim"), a))
    entity = next((f for f in usable if f.kind != "claim" and f.category not in bounded | {"other"}
                   and f.attribute not in ("battery_life", "battery_capacity")), b)
    clean_a = f"挑电脑前先看看它适合谁：{claim.value} [{claim.id}]。"
    clean_b = f"如果你想先确认一项配置，可以看这一项：{entity.value} [{entity.id}]。"
    promo_ok = promo is not None and valid_price_record(promo) is not None
    clean_c = (f"{clean_a} {rec['label']} {rec['value']} 元 [演示活动]，{rec['conditions']}。" if promo_ok and rec else None)
    wrong_value = re.sub(r"\d+(?:\.\d+)?", "0.86", a.value, count=1)      # first number → one no fact has
    sib = next((f for f in sib_ledger.facts if f.norm_value is not None and f.attribute in {x.attribute for x in ledger.facts}
                and not any(x.value == f.value for x in ledger.facts)), None)
    same_attr = {f.attribute: f.id for f in ledger.facts}
    other_price = None
    if rec:   # the same campaign's price for a DIFFERENT model
        from agent.recommend.common import INPUTS, load_json
        camp = next(p for p in load_json(INPUTS / "promotions.json") if p["campaign_id"] == rec["campaign_id"])
        other_price = next((v["value"] for m, v in (camp.get("price_info") or {}).items()
                            if m != promo_card.model_id and v.get("value") != rec["value"]), None)

    cases: list[tuple[Case, tuple]] = [
        (Case("错误参数值（数值改成 0.86）", True), draft(f"先看这一项：{wrong_value} [{a.id}]。")),
        (Case("数值正确但标错编号", True), draft(f"先看这一项：{a.value} [{b.id}]。")),
        (Case("无活动记录的价格", True), draft(clean_a, "现在到手价 3999 元。")),
        (Case("其他型号的活动价", True),
         draft(clean_a, f"演示活动价 {other_price} 元，{rec['conditions']}。", task=promo) if other_price
         else draft(clean_a, "演示活动价 6999 元。", task=promo or plain)),
        (Case("无编号的「新品首发」", True), draft(clean_a, "新品首发，赶紧来看看。")),
        (Case("编造顾客原话", True), draft(clean_a, "好多顾客都说这台用着很顺手。")),
        (Case("热销 / 爆款", True), draft(clean_a, "这是店里的热销爆款。")),
        (Case("赋能 + 不仅…更…", True), draft(clean_a, "它不仅仅是一台电脑，更是赋能学习的伙伴。")),
        (Case(f"{sibling} 的参数写在 {target} 下", True),
         draft(clean_a, f"这一项是 {sib.value} [{same_attr[sib.attribute]}]。") if sib else draft(clean_a)),
        (Case("干净稿 1 · 潜力款 · 可用结论原文", False), draft(clean_a)),
        (Case("干净稿 2 · 潜力款 · 无边界的参数", False), draft(clean_b)),
    ]
    if clean_c:
        cases.append((Case("干净稿 3 · 活动款 · 原文结论 + 演示活动价与条件", False), draft(clean_c, task=promo)))
    print(f"canary {day} · {'fakes' if args.fake else 'real deps'} · target {target} · LLM judges on")
    for case, (post, task) in cases:
        post.selling_points = list(dict.fromkeys(re.findall(r"\[(F\d+)\]", post.all_text())))[:1]
        report = deps.run_checks(post, ledger, siblings, task, plan, deps.llm)
        case.hits = [(i.stage, i.code, (i.span or "")[:24]) for i in report.issues if i.severity == "error"]
        case.reasons = [(i.stage, i.code, (i.span or "")[:40], i.message) for i in report.issues
                        if i.severity == "error"]
        case.caught = bool(case.hits)
    print("\n| 稿件 | 植入错误 | 结果 | 命中 |\n|---|---|---|---|")
    for case, _ in cases:
        verdict = ("✅ 拦截" if case.caught else "❌ 漏过") if case.planted else ("✅ 通过" if not case.caught else "⚠️ 误报")
        hits = "；".join(f"{s} {c}「{sp}」" for s, c, sp in case.hits[:3]) or "—"
        print(f"| {case.name} | {'是' if case.planted else '否'} | {verdict} | {hits} |")
    for case, _ in cases:      # reasons for anything flagged on a clean draft (a false positive to inspect)
        if not case.planted and case.caught:
            print(f"\n{case.name}：")
            for stage, code, span, msg in case.reasons:
                print(f"  - {stage} {code}「{span}」{msg[:160]}")
    planted = [c for c, _ in cases if c.planted]
    clean = [c for c, _ in cases if not c.planted]
    missed = [c.name for c in planted if not c.caught]
    false_pos = [c.name for c in clean if c.caught]
    print(f"\nplanted errors caught {len(planted) - len(missed)}/{len(planted)} · "
          f"clean drafts passed {len(clean) - len(false_pos)}/{len(clean)}")
    print(f"calls: LLM {len(getattr(deps.llm, 'calls', []) or [])}")
    return 0 if not missed and not false_pos else 1


if __name__ == "__main__":
    sys.exit(main())
