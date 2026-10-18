"""
P3 checks package: 8A facts -> 8B compliance -> 8C conformance.

    from agent.checks import run_all, strip_fact_tags

All checks run without an LLM (llm=None); the LLM layers are optional extras.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from agent.schemas import CheckReport, ImagePlan, Ledger, Post, Task

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

FACT_TAG_RE = re.compile(r"\s*\[(F\d+)\]")
_SENT_END_RE = re.compile(r"(?<=[。！？!?；;\n])")


def strip_fact_tags(text: str) -> tuple[str, list[tuple[str, str]]]:
    """Remove [F#] tags. Returns (clean text, [(sentence the tag sat in, fact_id)]).

    A sentence that cites several facts yields one pair per tag. The sentence text is clean (no tags)."""
    text = text or ""
    pairs: list[tuple[str, str]] = []
    for sent in _SENT_END_RE.split(text):
        if not sent:
            continue
        ids = FACT_TAG_RE.findall(sent)
        if ids:
            clean_sent = FACT_TAG_RE.sub("", sent).strip()
            pairs += [(clean_sent, fid) for fid in ids]
    return FACT_TAG_RE.sub("", text), pairs


@lru_cache(maxsize=None)
def load_lines(name: str) -> tuple[str, ...]:
    """Non-empty, non-comment lines of config/<name>."""
    p = CONFIG_DIR / name
    if not p.exists():
        return ()
    out = []
    for line in p.read_text("utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return tuple(out)


@lru_cache(maxsize=None)
def load_yaml(name: str) -> dict:
    import yaml  # pyyaml is in requirements.txt
    p = CONFIG_DIR / name
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text("utf-8")) or {}


def run_all(post: Post, ledger: Ledger, sibling_ledgers: dict[str, Ledger], task: Task,
            plan: ImagePlan, llm=None) -> CheckReport:
    """8A → 8B → 8C, merged into one report (8C last because stripping in 8A/8B can break structure)."""
    from agent.checks.compliance import check_compliance
    from agent.checks.conformance import check_conformance
    from agent.checks.facts import check_facts

    variant = getattr(task, "variant", None)
    platform = post.platform or getattr(task, "platform", None) or plan.platform
    report = check_facts(post, ledger, sibling_ledgers or {}, variant=variant, llm=llm)
    report = report.merge(check_compliance(post, ledger, task, llm=llm))
    report = report.merge(check_conformance(post, platform, plan))
    return report


__all__ = ["run_all", "strip_fact_tags", "load_lines", "load_yaml", "CONFIG_DIR", "FACT_TAG_RE"]
