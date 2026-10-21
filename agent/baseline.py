"""
Baseline mode (Phase 2 task 7): the "before" half of the video's before/after shot.

    generate_baseline(card, deps=None, llm=None) -> BaselineResult | LockedResult

One plain LLM call with a naive prompt ("为<型号>写一篇<平台>推广文案"), at the writer temperature, with
no ledger, no brief and no checks. The output is always wrapped and labelled
「对照组：未经约束的普通大模型输出」 and is never shown as our result. 8D stage 1 runs on it only to
highlight hits in the UI; nothing is rewritten or "fixed".
"""
from __future__ import annotations

from agent.schemas import BASELINE_LABEL, BaselineResult, LockedResult, Post, RecommendationCard

NAIVE_SYSTEM = "你是一名营销文案写手。"


def naive_prompt(card: RecommendationCard) -> str:
    return f"为{card.display_name or card.model_id}写一篇{card.platform}推广文案"


def wrap(text: str) -> str:
    return f"【{BASELINE_LABEL}】\n{text}"


def generate_baseline(card: RecommendationCard, deps=None, llm=None) -> BaselineResult | LockedResult:
    """Never calls ima. A locked card is refused like run_from_card (no facts are verified to compare to)."""
    if card.locked:
        from agent.pipeline import LOCKED_MESSAGES
        reason = card.locked_reason or "locked"
        return LockedResult(card=card, reason=reason, message=LOCKED_MESSAGES.get(reason, "该推荐暂不可生成"))
    if llm is None:
        if deps is None:
            from agent.pipeline import default_deps
            deps = default_deps()
        llm = deps.llm
    prompt = naive_prompt(card)
    text = (llm.chat_text(NAIVE_SYSTEM, prompt, stage="baseline") or "").strip()

    hits = []
    try:  # highlight only: deterministic 8D stage 1, no LLM judge
        from agent.recommend.to_task import platform_key
        from agent.style.antiai import check_style
        post = Post(platform=platform_key(card.platform), title="", intro="", body=[text], cta="", tags=[],
                    selling_points=[], images=[])
        hits = check_style(post, task=None, llm=None).issues
    except Exception:  # noqa: BLE001 - highlighting must never break the control group
        hits = []
    result = BaselineResult(card_id=card.card_id, model_id=card.model_id, platform=card.platform, prompt=prompt,
                            text=text, display_text=wrap(text), hits=hits)
    real = deps is not None and not getattr(deps, "is_dev_mode", True)
    if deps is None and llm is not None:   # caller supplied a model directly; tests use FakeLLM
        real = not type(llm).__module__.startswith("tests")
    if real:
        try:
            from agent.runs import log_run
            log_run(card, result, kind="generate_baseline")
        except Exception:  # noqa: BLE001 - logging must never break the video run
            pass
    return result


__all__ = ["generate_baseline", "naive_prompt", "wrap", "BASELINE_LABEL"]
