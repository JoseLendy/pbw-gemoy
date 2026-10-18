"""
Step 2: scenario analysis. Category-level only: this stage has not seen the KB, so no specs or numbers.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

from agent.schemas import CATEGORIES, SCENARIO_LABELS, PLATFORM_LABELS, ScenarioAnalysis, Task

CONFIG = Path(__file__).resolve().parent.parent / "config" / "scenarios.yaml"
_DIGIT = re.compile(r"[0-9０-９]|[一二三四五六七八九十百千]+\s*(?:小时|克|公斤|英寸|寸|瓦|核|GB|TB|Hz)", re.I)


@lru_cache(maxsize=1)
def load_scenarios() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _has_spec(text: str) -> bool:
    return bool(_DIGIT.search(text or ""))


def analyze(task: Task, llm=None) -> ScenarioAnalysis:
    from agent.llm import load_prompt
    if llm is None:
        from agent.llm import LLM
        llm = LLM()

    cfg = load_scenarios().get(task.scenario or "", {})
    defaults = [c for c in cfg.get("categories", []) if c in CATEGORIES]

    user = (
        f"任务：人群={task.audience or '未说明'}；场景={SCENARIO_LABELS.get(task.scenario or '', '未说明')}；"
        f"平台={PLATFORM_LABELS.get(task.platform or '', '未说明')}；额外要求={task.extra_requirements or '无'}\n"
        f"原话：{task.raw_text}\n"
        f"场景参考：关注点={cfg.get('focus', '')}；默认类别排序={defaults}；禁止事项={cfg.get('forbidden', [])}\n"
        f"可选类别：{list(CATEGORIES)}"
    )
    data = llm.chat_json(load_prompt("scenario"), user, stage="scenario") or {}

    # Code validation: known categories only, deduplicated, in the LLM's order.
    cats: list[str] = []
    for c in data.get("categories") or []:
        if c in CATEGORIES and c not in cats:
            cats.append(c)
    if not cats:
        cats = defaults[:]

    reasons = {k: v for k, v in (data.get("reasons") or {}).items()
               if k in cats and isinstance(v, str) and not _has_spec(v)}

    def text(field: str, fallback: str) -> str:
        v = data.get(field)
        return v if isinstance(v, str) and v.strip() and not _has_spec(v) else fallback

    return ScenarioAnalysis(
        audience=text("audience", task.audience or cfg.get("audience", "")),
        buying_stage=text("buying_stage", "比较"),
        problem=text("problem", cfg.get("focus", "")),
        content_goal=text("content_goal", cfg.get("cta_style", "")),
        categories=cats,
        reasons=reasons,
    )
