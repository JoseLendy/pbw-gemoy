"""
Step 5: strategy reconciliation. Code groups facts and enforces the gate; the strong LLM only chooses and orders.
"""
from __future__ import annotations

import re
from collections import defaultdict

from agent.schemas import (
    Conflict, Ledger, Model, NeedsHuman, PLATFORM_LABELS, ScenarioAnalysis, SellingPoint, Strategy, Task,
)

NO_FACTS_REASON = "知识库无该类资料"

_UPPER = [(re.compile(r"最长约?|最久约?"), "可达约"), (re.compile(r"最高(?:可达|达到)?"), "可达"),
          (re.compile(r"最大(?:支持)?"), "最多支持")]
_ABSOLUTE = re.compile(r"[最]|第一|唯一|顶级|全网|首选|史上")


def clean_talk_line(line: str) -> str:
    """Talk-card lines are checked like the post: upper bounds become 可达/最多支持, any other absolute is dropped."""
    s = str(line).strip()
    for pat, rep in _UPPER:
        s = pat.sub(rep, s)
    return "" if _ABSOLUTE.search(s) else s


def _limits(platform: str | None) -> tuple[int, int]:
    """(min, max) number of selling points."""
    if platform == "moments":
        return 1, 1
    if platform == "poster":
        return 1, 3
    return 2, 4


def _fact_line(f, flagged: bool) -> str:
    mark = " ⚠资料有分歧" if flagged else ""
    return f"{f.id} | {f.category} | {f.attribute} | {f.value} | 变体={f.variant}{mark}"


def _fallback_ids(analysis: ScenarioAnalysis, by_cat: dict[str, list], skip: set[str], n: int,
                  have: list[str]) -> list[str]:
    """Deterministic fill: the first usable fact of each ranked category."""
    out = list(have)
    for cat in analysis.categories:
        for f in by_cat.get(cat, []):
            if f.id not in out and f.id not in skip:
                out.append(f.id)
                break
        if len(out) >= n:
            break
    return out


def reconcile(task: Task, analysis: ScenarioAnalysis, ledger: Ledger, model: Model,
              llm=None) -> Strategy | NeedsHuman:
    from agent.llm import load_prompt
    if llm is None:
        from agent.llm import LLM
        llm = LLM()

    needs_human = set(model.needs_human or [])
    conflict_ids = {fid for c in ledger.conflicts for fid in c.fact_ids}

    def risky(f) -> bool:
        return f.attribute in needs_human or f.id in conflict_ids

    # ---- code: group by category, drop categories without facts
    by_cat: dict[str, list] = defaultdict(list)
    for f in ledger.facts:
        by_cat[f.category].append(f)
    dropped = {c: NO_FACTS_REASON for c in analysis.categories if not by_cat.get(c)}
    kept_cats = [c for c in analysis.categories if c not in dropped]

    # ---- LLM: choose and order
    lo, hi = _limits(task.platform)
    facts_for_llm = [f for c in kept_cats for f in by_cat[c]]
    user = (
        f"平台：{PLATFORM_LABELS.get(task.platform or '', task.platform)}；卖点数量：{lo if lo == hi else f'{lo} 到 {hi}'} 个\n"
        f"任务变体：{task.variant or '未指定'}\n"
        f"场景分析：人群={analysis.audience}；问题={analysis.problem}；目标={analysis.content_goal}；"
        f"类别排序={kept_cats}\n"
        f"已剔除类别：{dropped or '无'}\n"
        "可用事实（编号 | 类别 | 属性 | 取值 | 变体）：\n"
        + "\n".join(_fact_line(f, risky(f)) for f in facts_for_llm)
    )
    data = llm.chat_json(load_prompt("reconcile"), user, stage="reconcile") or {}

    # ---- code: validate ids
    valid_ids = {f.id for f in facts_for_llm}
    chosen: list[str] = []
    reasons: dict[str, str] = {}
    for sp in data.get("selling_points") or []:
        fid = sp.get("fact_id") if isinstance(sp, dict) else None
        if fid in valid_ids and fid not in chosen:
            chosen.append(fid)
            reasons[fid] = str(sp.get("reason", "")).strip()
    chosen = chosen[:hi]
    if len(chosen) < lo:
        chosen = _fallback_ids(analysis, by_cat, set(), lo, chosen)[:hi]
        for fid in chosen:
            reasons.setdefault(fid, "按场景类别排序补充")

    # ---- gate
    chosen_facts = [ledger.get(i) for i in chosen]
    blocking: list[Conflict] = []
    for f in chosen_facts:
        if f is None:
            continue
        for c in ledger.conflicts:
            if f.id in c.fact_ids and c not in blocking:
                blocking.append(c)
        if f.attribute in needs_human and not any(f.id in c.fact_ids for c in blocking):
            blocking.append(Conflict(attribute=f.attribute, variant=f.variant, fact_ids=[f.id],
                                     reason="知识库对该属性存在已知分歧，需要人工确认"))
    if blocking:
        attrs = "、".join(sorted({c.attribute for c in blocking}))
        return NeedsHuman(conflicts=blocking, message=(
            f"知识库资料在「{attrs}」上存在冲突或分歧，而这篇文章需要用到它。"
            "为避免写错，已停止生成，请先人工确认后再继续。"))

    # ---- pending: unchosen conflicts / needs_human attributes are excluded and listed
    pending: list[str] = []
    seen: set[str] = set()
    for c in ledger.conflicts:
        if not set(c.fact_ids) & set(chosen) and c.attribute not in seen:
            seen.add(c.attribute)
            pending.append(f"待确认：{c.attribute}（{c.variant}）知识库资料存在冲突，本文未使用。{c.reason}".strip())
    for f in ledger.facts:
        if f.attribute in needs_human and f.attribute not in seen:
            seen.add(f.attribute)
            pending.append(f"待确认：{f.attribute} 知识库资料存在已知分歧，本文未使用。")

    talk = [t for t in (clean_talk_line(x) for x in (data.get("talk_card") or [])) if t][:3]
    return Strategy(
        analysis=analysis,
        angle=str(data.get("angle") or "").strip() or analysis.content_goal,
        selling_points=[SellingPoint(fid, reasons.get(fid, "")) for fid in chosen],
        dropped_categories=dropped,
        talk_card=talk,
        cta_type=str(data.get("cta_type") or "").strip(),
        pending=pending,
    )
