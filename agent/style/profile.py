"""
Writer brief (plan §6.1): a recommendation card's hook / voice / landmark / nickname / angle /
calendar theme / promo become an explicit instruction block in the writer prompt.

    from agent.style.profile import brief
    brief(task)   # "" for the manual flow (task.source == "manual"), so that path is unchanged

Everything here is instruction text built from the card's own fields. No fact, price or customer
quote is invented: the promo block can only echo the card's promo record, and the customer hook can
only echo the card's logged question.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from agent.recommend.common import INPUTS, load_json

# Tone directions per voice id (angles.json). These describe HOW to sound, never WHAT to claim.
VOICE_TONE = {
    "manager": "像店长跟熟客说话：亲切、直白，先关心对方怎么用，再说产品，不用推销话术。",
    "techie": "像懂技术的店员：讲清楚参数在实际使用里意味着什么，克制、不夸张，不堆形容词。",
    "senior": "像学长学姐分享经验：口语、平等，讲校园里的具体场景；不摆推销腔，也不要编造自己的使用经历。",
}

# Opening instruction per hook id (angles.json). The customer hook is special: it may only quote the log.
HOOK_OPENING = {
    "scene": "开头用一个具体场景切入（时间、地点、正在做的事），不要先列参数。",
    "question": "开头用一个顾客真实会问的问题切入；全文反问句不超过 1 个。",
    "myth": "开头先点出常见的误解，再说明资料里的事实；不贬低其他品牌，不做对比。",
    "checklist": "开头用清单式引入（例如“买之前先看这几点”），后面每条对应事实编号。",
}
CUSTOMER_HOOK = "customer"


@lru_cache(maxsize=1)
def _angles() -> dict:
    return load_json(INPUTS / "angles.json")


def _label(items: list[dict], key: Optional[str]) -> Optional[str]:
    item = next((i for i in items if i.get("id") == key), None)
    return item.get("label") if item else None


def voice_label(voice_id: Optional[str]) -> Optional[str]:
    return _label(_angles()["voices"], voice_id) if voice_id else None


def hook_label(hook_id: Optional[str]) -> Optional[str]:
    return _label(_angles()["hooks"], hook_id) if hook_id else None


def _hook_block(task) -> list[str]:
    hook = getattr(task, "hook", None)
    if hook == CUSTOMER_HOOK:
        q = getattr(task, "question", None)
        if not q:
            # No logged question: the customer hook must not be used. Say so explicitly instead of
            # quietly falling back, so the writer never invents a customer quote to fill the opening.
            return ["开头不得使用“顾客问答”式开头：本店没有该问题的记录。改用场景或问题开场。",
                    "不得虚构顾客提问、顾客原话、评价或反馈。"]
        text = (q or {}).get("text") or ""
        count = (q or {}).get("count")
        times = f"（近 7 天被问到 {count} 次）" if count else ""
        return [f"开头用“顾客问答”式切入，且只能引用本店真实记录过的这一个问题：“{text}”{times}。",
                "不得添加其他顾客问题、顾客原话、评价或人数统计；不得写成“很多顾客都说好”。"]
    opening = HOOK_OPENING.get(hook or "")
    return [f"开头方式：{hook_label(hook) or '场景开头'}。{opening or HOOK_OPENING['scene']}"]


def _voice_block(task) -> list[str]:
    voice = getattr(task, "voice", None)
    if not voice:
        return []
    label = voice_label(voice) or voice
    tone = VOICE_TONE.get(voice, "")
    staff = getattr(task, "staff", None) or {}
    who = f"（本条按 {staff['display_name']} 的版本发布）" if staff.get("display_name") else ""
    return [f"语气：{label}。{tone}{who}"]


def _detail_block(task) -> list[str]:
    out: list[str] = []
    landmark = getattr(task, "landmark", None)
    if landmark:
        out.append(f"可以在正文里自然带一次门店位置：{landmark}。最多出现一次，不要重复，也不要写地址细节之外的信息。")
    nickname = getattr(task, "nickname", None)
    if nickname and (getattr(task, "platform", "") == "moments"):
        out.append(f"结尾可以用「{nickname}」署名，只出现一次。")
    elif nickname:
        out.append("本平台不用署名：正文里不要出现昵称或店名落款。")
    return out


def _angle_block(task) -> list[str]:
    out: list[str] = []
    angle = getattr(task, "angle", None)
    if angle:
        out.append(f"内容角度：{angle}。整篇围绕这个角度组织，不要写成参数清单。")
    theme = getattr(task, "calendar_theme", None)
    if theme:
        out.append(f"时间背景：{theme}。只用来说明“什么时候适合看/买”，不得暗示折扣、优惠、降价、库存或促销价。")
    return out


def _promo_block(task) -> list[str]:
    promo = getattr(task, "promo", None)
    price = (promo or {}).get("price_info") if promo else None
    if not price:
        return ["本文没有任何价格记录：不得写价格、优惠、补贴、立减、折扣、分期、免息或库存说法。"]
    label = price.get("label") or "活动价"
    value = str(price.get("value") or "")
    cur = price.get("currency") or "CNY"
    cond = (price.get("conditions") or "").strip()
    demo = (promo or {}).get("source") == "DEMO"
    lines = [f"唯一允许出现的价格来自活动记录「{(promo or {}).get('name', '')}」：{label} {value} {cur}"
             + (f"，适用条件：{cond}" if cond else "") + "。",
             "金额与条件必须与这条记录完全一致：不改数字、不加码、不叠加其他优惠、不写“到手价”。"]
    if cond:
        lines.append(f"提到这个价格时，必须同时写出适用条件：{cond}。")
    if demo:
        lines.append("这是演示活动价：写出价格时紧跟在金额后面标注 [演示活动]（例如 4999 元 [演示活动]）。")
    return lines


def _sales_block() -> list[str]:
    return ["不得提销量、排名、人气或流行度：不写 热销、爆款、销量第一、卖断货、抢疯了、很多人买 之类说法。",
            "不得使用“最 / 第一 / 唯一 / 顶级 / 全网 / 首选”等绝对化用语，包括与产品无关的生活描写。"]


def brief(task) -> str:
    """Instruction block for the writer, built only from the card's own brief fields.

    Returns "" for the manual flow (source != "card"), so prompts/writer.md behaviour is unchanged there."""
    if getattr(task, "source", "manual") != "card":
        return ""
    lines: list[str] = ["以下要求来自门店今日推荐卡，优先级高于通用写作偏好。"]
    lines += _hook_block(task)
    lines += _voice_block(task)
    lines += _detail_block(task)
    lines += _angle_block(task)
    lines += _promo_block(task)
    lines += _sales_block()
    lines += ["仍然要满足：每个产品说法后标注事实编号 [F#]；不得引用清单外的任何产品信息。"]
    return "\n".join(f"- {line}" for line in lines if line)


__all__ = ["brief", "voice_label", "hook_label", "VOICE_TONE", "HOOK_OPENING", "CUSTOMER_HOOK"]
