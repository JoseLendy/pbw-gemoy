"""
Price traceability (plan §4.3, §6.5; Phase 2 task 4). Part of 8B.

A price, discount, subsidy, installment or stock claim may appear in copy ONLY if it matches an active
promotion record for that model exactly (value AND conditions). The record must:
  * be on the task (card.promo → Task.promo), and
  * match data/demo/inputs/promotions.json for the same campaign_id + model (guards a tampered card), and
  * be active on the card's date.
Anything else is blocked, including a user edit like "加上立减500".

    valid_price_record(task)            -> dict | None     # {"value", "conditions", "label", "source", ...}
    check_prices(post, task)            -> list[CheckIssue]  (stage 8B)
    price_request_block(text, task)     -> str | None       # message if an edit must be blocked
    mark_demo_prices(post, task)        -> Post             # adds [演示活动] next to a DEMO price

Issue codes (stage "8B"):
  price_untraceable         a money / discount / subsidy / installment / stock claim with no record   error
  price_mismatch            a money amount that differs from the record's value                       error
  price_conditions_missing  the record's price is quoted without its conditions                        error
"""
from __future__ import annotations

import copy
import datetime as dt
import re
from typing import Optional

from agent.schemas import CheckIssue, Post

STAGE = "8B"
DEMO_TAG = "[演示活动]"
RULE = "价格可追溯规则：价格、优惠、补贴、分期、库存说法只能来自总部当前有效的活动记录，且金额与条件必须完全一致"

# A money amount: ¥4999 / 4999元 / 4,999 元 / 活动价4999.
_NUM = r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
MONEY_RE = re.compile(
    rf"[¥￥]\s*{_NUM}|(?:价|售价|活动价|到手价|特价)\s*[:：]?\s*{_NUM}(?:\s*(?:元|块钱|块|CNY|RMB|rmb))?"
    rf"|{_NUM}\s*(?:元|块钱|块|CNY|RMB|rmb)")
# Money-adjacent mechanics the demo records never carry (a record only has label + value + conditions).
TERM_RE = re.compile(r"(立减|直降|降价|优惠|补贴|折扣|打折|\d+\s*折|满减|分期|免息|到手价|特价|赠品|赠送|买赠|"
                     r"库存|现货|仅剩|限量|手慢无|售罄)")
_WS_RE = re.compile(r"\s+")


def _norm(s: str) -> str:
    return _WS_RE.sub("", s or "")


def _amount(m: re.Match) -> Optional[float]:
    raw = next((g for g in m.groups() if g), None)
    try:
        return float(raw.replace(",", "")) if raw else None
    except ValueError:
        return None


def _card_date(task) -> Optional[dt.date]:
    d = getattr(task, "card_date", None)
    try:
        return dt.date.fromisoformat(d) if d else None
    except ValueError:
        return None


def valid_price_record(task, promotions: Optional[list[dict]] = None) -> Optional[dict]:
    """The one price this task may quote, or None. Checked against promotions.json, not just the card."""
    promo = getattr(task, "promo", None) or None
    price = (promo or {}).get("price_info") if promo else None
    if not price or not price.get("value"):
        return None
    if promotions is None:
        from agent.recommend.common import INPUTS, load_json
        promotions = load_json(INPUTS / "promotions.json")
    rec = next((p for p in promotions if p.get("campaign_id") == promo.get("campaign_id")), None)
    model_id = getattr(task, "model_id", None)
    if rec is None or model_id not in (rec.get("models") or []):
        return None
    truth = (rec.get("price_info") or {}).get(model_id)
    if not truth or str(truth.get("value")) != str(price.get("value")) \
            or (truth.get("conditions") or "") != (price.get("conditions") or ""):
        return None                      # the card disagrees with HQ's record: trust neither
    day = _card_date(task)
    if day is None or not (dt.date.fromisoformat(rec["start"]) <= day <= dt.date.fromisoformat(rec["end"])):
        return None                      # campaign not active on the card's date
    return {"campaign_id": rec["campaign_id"], "name": rec.get("name", ""), "value": str(truth["value"]),
            "conditions": truth.get("conditions") or "", "label": truth.get("label") or "",
            "currency": truth.get("currency") or "CNY", "source": rec.get("source", "")}


def _issue(code: str, message: str, field: str = "", span: str = "") -> CheckIssue:
    return CheckIssue(stage=STAGE, severity="error", code=code, message=message, field=field, span=span)


def _fields(post: Post) -> list[tuple[str, str]]:
    out = [("title", post.title), ("intro", post.intro)]
    out += [(f"body[{i}]", p) for i, p in enumerate(post.body)]
    out.append(("cta", post.cta))
    out += [(f"images[{i}].caption", im.caption) for i, im in enumerate(post.images)]
    return [(f, t or "") for f, t in out]


def _allowed_terms(rec: Optional[dict]) -> str:
    return _norm(" ".join([rec.get("label", ""), rec.get("conditions", ""), rec.get("name", "")])) if rec else ""


def check_prices(post: Post, task) -> list[CheckIssue]:
    """8B price traceability for card runs. The manual flow is left to 8A's invented_price (unchanged)."""
    if task is None or (getattr(task, "source", "manual") != "card" and not getattr(task, "promo", None)):
        return []
    rec = valid_price_record(task)
    allowed = _allowed_terms(rec)
    issues: list[CheckIssue] = []
    quoted = False
    for field, text in _fields(post):
        for m in MONEY_RE.finditer(text):
            amt = _amount(m)
            if rec is None:
                issues.append(_issue("price_untraceable", f"「{m.group(0)}」没有对应的有效活动记录，删掉。{RULE}",
                                     field, m.group(0)))
            elif amt is None or amt != float(rec["value"]):
                issues.append(_issue("price_mismatch",
                                     f"金额「{m.group(0)}」与活动记录「{rec['name']}」的 {rec['value']} 不一致，"
                                     f"改成记录里的金额或删掉。{RULE}", field, m.group(0)))
            else:
                quoted = True
        for m in TERM_RE.finditer(text):
            if _norm(m.group(0)) and _norm(m.group(0)) in allowed:
                continue
            issues.append(_issue("price_untraceable",
                                 f"「{m.group(0)}」没有出现在任何有效活动记录里（活动记录只给出 "
                                 f"{rec['label'] + ' ' + rec['value'] if rec else '无价格'}），删掉。{RULE}",
                                 field, m.group(0)))
    if quoted and rec and rec["conditions"] and _norm(rec["conditions"]) not in _norm(post.all_text()):
        issues.append(_issue("price_conditions_missing",
                             f"写了活动价却没写适用条件，必须原样写出：「{rec['conditions']}」。{RULE}",
                             "body", rec["conditions"]))
    return issues


def price_request_block(instruction: str, task) -> Optional[str]:
    """For the edit flow: a message if the instruction asks for a price-type claim the record cannot back.
    None when the instruction has no price ask, or every amount in it equals the record's value."""
    text = instruction or ""
    money = list(MONEY_RE.finditer(text))
    bare = re.findall(r"(?:立减|直降|补贴|优惠|减)\s*(\d+)", text)
    terms = [m.group(0) for m in TERM_RE.finditer(text)]
    if not money and not terms and not bare:
        return None
    rec = valid_price_record(task)
    if rec is not None and not terms:
        amounts = [_amount(m) for m in money] + [float(b) for b in bare]
        if amounts and all(a == float(rec["value"]) for a in amounts):
            return None
    what = (money[0].group(0) if money else (terms[0] if terms else bare[0]))
    have = f"当前有效记录只有「{rec['name']}」{rec['label']} {rec['value']}（{rec['conditions']}）" if rec \
        else "本条推荐没有任何有效的活动价格记录"
    return f"已拦截「{instruction.strip()}」：{have}，「{what}」无法追溯，未调用写作。{RULE}。"


def mark_demo_prices(post: Post, task) -> Post:
    """Publishable copy shows [演示活动] right after a DEMO record's price (added once, in code)."""
    rec = valid_price_record(task) if task is not None else None
    if not rec or rec.get("source") != "DEMO":
        return post
    new = copy.deepcopy(post)

    def tag(text: str) -> str:
        def repl(m: re.Match) -> str:
            if _amount(m) != float(rec["value"]):
                return m.group(0)
            rest = text[m.end():m.end() + len(DEMO_TAG) + 2]
            return m.group(0) if DEMO_TAG in rest else f"{m.group(0)} {DEMO_TAG}"
        return MONEY_RE.sub(repl, text or "")

    new.title, new.intro, new.cta = tag(new.title), tag(new.intro), tag(new.cta)
    new.body = [tag(p) for p in new.body]
    return new


__all__ = ["check_prices", "price_request_block", "mark_demo_prices", "valid_price_record", "DEMO_TAG", "RULE"]
