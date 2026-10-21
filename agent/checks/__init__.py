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


def _norm_span(span: str) -> str:
    return re.sub(r"[\s…，。！？、；;:：“”\"「」『』·]+", "", span or "")


def _same_style_span(a: str, b: str) -> bool:
    """Exact span, or a shared >=4-char prefix for 8C's pair phrase (不仅仅是…更是) and 8D's
    regex match (不仅仅是轻薄，更)."""
    na, nb = _norm_span(a), _norm_span(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    k = 0
    while k < min(len(na), len(nb)) and na[k] == nb[k]:
        k += 1
    return k >= 4


def dedupe_style_hits(report: "CheckReport") -> "CheckReport":
    """8C's ai_tell and 8D's ai_cliche/ai_pattern can flag the same phrase twice. Keep one line, using
    the 8D issue as primary and recording 8C in also_stages so 四、核验结果 shows `[8D/8C]`."""
    d_hits: dict[str, list] = {}
    for i in report.issues:
        if i.stage == "8D" and i.code in ("ai_cliche", "ai_pattern") and i.span:
            d_hits.setdefault(i.field, []).append(i)
    out = []
    for i in report.issues:
        if i.stage == "8C" and i.code == "ai_tell" and i.span:
            primary = next((d for d in d_hits.get(i.field, []) if _same_style_span(i.span, d.span)), None)
            if primary is not None:
                if "8C" not in primary.also_stages:
                    primary.also_stages.append("8C")
                continue
        out.append(i)
    return CheckReport(out)


def run_all(post: Post, ledger: Ledger, sibling_ledgers: dict[str, Ledger], task: Task,
            plan: ImagePlan, llm=None) -> CheckReport:
    """8A → 8B → 8C → 8D, merged into one report (8C before 8D because stripping in 8A/8B can break
    structure, and 8D's structural counts should see the final text).

    8A, 8B and 8D are independent of each other (each reads only the post, ledger and task). With an LLM
    they run concurrently (CHECK_PARALLEL=0 turns that off); the merged report is identical either way."""
    import os
    from agent.checks.compliance import check_compliance
    from agent.checks.conformance import check_conformance
    from agent.checks.facts import check_facts
    from agent.timing import stage

    variant = getattr(task, "variant", None)
    platform = post.platform or getattr(task, "platform", None) or plan.platform

    def facts():
        from agent.checks.prices import valid_price_record
        rec = valid_price_record(task)
        with stage("check.8A"):
            report = check_facts(post, ledger, sibling_ledgers or {}, variant=variant, llm=llm, price_record=rec)
        if rec is not None:
            # An active promotion record exists: 8B's exact price-traceability check owns money claims, and
            # 8A's generic "no price facts in the KB" rule would otherwise block the one allowed price.
            report = CheckReport([i for i in report.issues if i.code != "invented_price"])
        return report

    def compliance():
        with stage("check.8B"):
            return check_compliance(post, ledger, task, llm=llm)

    def style():
        try:  # Phase 2: 8D anti-AI style. A missing/broken style module must never stop a run.
            from agent.style.antiai import check_style
            with stage("check.8D"):
                return check_style(post, task, llm)
        except Exception as e:  # noqa: BLE001
            import logging
            logging.getLogger("agent.checks").warning("8D unavailable: %s", e)
            return CheckReport()

    if llm is not None and os.getenv("CHECK_PARALLEL", "1") != "0":
        import contextvars
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = [ex.submit(contextvars.copy_context().run, fn) for fn in (facts, compliance, style)]
            r_facts, r_comp, r_style = (f.result() for f in futs)
    else:
        r_facts, r_comp, r_style = facts(), compliance(), style()
    with stage("check.8C"):
        r_conf = check_conformance(post, platform, plan)
    return dedupe_style_hits(r_facts.merge(r_comp).merge(r_conf).merge(r_style))


__all__ = ["run_all", "strip_fact_tags", "load_lines", "load_yaml", "CONFIG_DIR", "FACT_TAG_RE"]
