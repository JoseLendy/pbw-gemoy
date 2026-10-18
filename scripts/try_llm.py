"""
Manual live check (uses the real LLM, never ima). Fixtures only (DemoBook, synthetic).

    .venv/bin/python scripts/try_llm.py

Runs intake -> analyze -> reconcile -> write_post twice and prints both posts and per-stage timings.
The two posts must differ in angle, selling-point order, structure, image count and CTA (WORKFLOW rule 6).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.intake import parse_task  # noqa: E402
from agent.llm import LLM, LLMConfigError  # noqa: E402
from agent.reconcile import reconcile  # noqa: E402
from agent.scenario import analyze  # noqa: E402
from agent.schemas import Clarification, NeedsHuman  # noqa: E402
from agent.writer import write_post  # noqa: E402
from tests.fakes import DEMO, FakeCatalog, fake_ledger, fake_plan  # noqa: E402

CASES = [
    "一位妈妈想给下个月上大学的女儿买笔记本，DemoBook 14（演示版），发小红书",
    "经常出差的商务客户想要一台电脑，DemoBook 14（演示版），发朋友圈",
]


def run(text: str, llm: LLM):
    task = parse_task(text, FakeCatalog(), llm=llm)
    if isinstance(task, Clarification):
        print("需要澄清：", [(q.slot, q.options) for q in task.questions])
        return None
    analysis = analyze(task, llm)
    ledger = fake_ledger(task.model_id)
    strategy = reconcile(task, analysis, ledger, DEMO, llm)
    if isinstance(strategy, NeedsHuman):
        print("NeedsHuman：", strategy.message)
        return None
    plan = fake_plan(task.platform, task.model_id)
    post = write_post(task, strategy, ledger, plan, llm)
    return task, strategy, post


def show(task, strategy, post):
    print(f"\n=== {task.scenario} / {task.platform} ===")
    print("切入点：", strategy.angle)
    print("卖点顺序：", [sp.fact_id for sp in strategy.selling_points])
    print("话术卡：", strategy.talk_card)
    print("标题：", post.title)
    print("导语：", post.intro)
    for p in post.body:
        print("  -", p)
    print("行动引导：", post.cta)
    print("平台标签：", post.tags)
    print("图片数：", len(post.images), [(i.position, i.caption) for i in post.images])
    print("含「最」：", "最" in post.all_text())


def main() -> int:
    try:
        llm = LLM()
    except LLMConfigError as e:
        print(e)
        return 1
    results = [run(t, llm) for t in CASES]
    for r in results:
        if r:
            show(*r)
    print("\n阶段耗时（秒）：", {k: round(v, 2) for k, v in llm.timings.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
