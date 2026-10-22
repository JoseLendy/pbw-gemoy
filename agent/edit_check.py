"""
Inline editing (store tab 「检查并保存」): staff edit the publishable text by hand; this re-checks it with the
deterministic checks only (no LLM call, well under 2 s) before it can be copied, exported or published.

    chk = check_edit(edited_text, result)      # result: the RunResult whose post was shown
    chk.passed, chk.post, chk.failing          # failing: [FailingSentence(field, sentence, stage, code, reason)]

What is checked (the same code rules the pipeline runs, nothing loosened):
  - every number / spec matches a fact of THIS model's ledger, with the fact's qualifier and system (8A, 8B)
  - prices, discounts and subsidies only from the active promotion record (8B price traceability)
  - banned words: absolute claims (8B) and sales / cliché phrases (8D blocklist)
  - no personal name or sign-off (8B personal_name)
  - the product's name is still there (8C product_unnamed)
  - platform structure; for 朋友圈 the paragraph limit is an error here (a human edit has no rewrite loop)

The edited text carries no [F#] tags. A sentence left exactly as it was keeps its original tags; a changed
sentence gets the tag of the fact whose value it states, so the fact rules (qualifier, system) apply to it.
A number that matches no fact of this model stays untagged and fails as unsupported.
"""
from __future__ import annotations

import copy
import re
import time
from dataclasses import dataclass, field

from agent.schemas import CheckIssue, CheckReport, FailingSentence, Post, RunResult

_PARA_SPLIT = re.compile(r"\n\s*\n")
_HASHTAG_LINE = re.compile(r"^(?:#\S+\s*)+$")
_SENT_PIECE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;\n]*")
_TAG = re.compile(r"\s*\[F\d+\]")
_NORM = re.compile(r"[\s，,。！？!?；;：:、“”\"「」（）()]+")
_END = re.compile(r"([。！？!?；;\n]*)$")
# 8D style rules that are about wording a human may legitimately change (openers, rhythm, the LLM judge) are
# not edit blockers; the blocklist (sales / cliché phrases) is.
_STYLE_BLOCKING = {"ai_cliche", "ai_pattern"}


@dataclass
class EditCheck:
    passed: bool
    post: Post
    failing: list[FailingSentence] = field(default_factory=list)
    issues: list[CheckIssue] = field(default_factory=list)
    seconds: float = 0.0


def _norm(text: str) -> str:
    return _NORM.sub("", _TAG.sub("", text or ""))


def post_from_text(text: str, original: Post) -> Post:
    """Edited publishable text → a Post shaped like the original (title / intro if it had them, CTA last)."""
    paras = [p.strip() for p in _PARA_SPLIT.split((text or "").strip()) if p.strip()]
    tags = list(original.tags)
    if paras and _HASHTAG_LINE.match(paras[-1]):
        tags = [t.lstrip("#") for t in paras.pop().split()]
    title = paras.pop(0) if original.title and paras else ""
    intro = paras.pop(0) if original.intro and len(paras) > 1 else ""
    cta = paras.pop() if paras and original.cta else ""
    return Post(platform=original.platform, title=title, intro=intro, body=paras, cta=cta, tags=tags,
                selling_points=[], images=copy.deepcopy(original.images))


def _retag(post: Post, original: Post, ledger) -> Post:
    from agent import units
    from agent.checks.facts import _matching_facts, mask_whitelisted
    known: dict[str, str] = {}
    for raw in [original.title, original.intro, *original.body, original.cta]:
        for piece in _SENT_PIECE.findall(raw or ""):
            if _norm(piece):
                known.setdefault(_norm(piece), piece)

    def tag_field(text: str) -> str:
        out = []
        for piece in _SENT_PIECE.findall(text or ""):
            if _norm(piece) in known:
                out.append(known[_norm(piece)])
                continue
            ids = []
            for _span, value, unit in units.find_all(mask_whitelisted(piece)):
                for f in _matching_facts(ledger, value, unit)[:1]:
                    if f.id not in ids:
                        ids.append(f.id)
            if ids:
                end = _END.search(piece).group(1)
                piece = piece[:len(piece) - len(end)] + " " + " ".join(f"[{i}]" for i in ids) + end
            out.append(piece)
        return "".join(out)

    new = copy.deepcopy(post)
    new.title, new.intro, new.cta = tag_field(post.title), tag_field(post.intro), tag_field(post.cta)
    new.body = [tag_field(b) for b in post.body]
    cited = list(dict.fromkeys(re.findall(r"\[(F\d+)\]", new.all_text())))
    new.selling_points = [i for i in cited if ledger.get(i)]
    return new


def check_edit(text: str, result: RunResult) -> EditCheck:
    from agent.checks import run_all
    from agent.pipeline import failing_sentences
    t0 = time.perf_counter()
    post = _retag(post_from_text(text, result.post), result.post, result.ledger)
    siblings = getattr(result, "_sibling_ledgers", None) or {}
    report = run_all(post, result.ledger, siblings, result.task, result.plan, llm=None)
    issues = []
    for i in report.issues:
        if i.code == "paragraph_count" and post.platform == "moments":
            i = copy.copy(i)
            i.severity = "error"
        if i.severity != "error" or (i.stage == "8D" and i.code not in _STYLE_BLOCKING):
            continue
        issues.append(i)
    failing = failing_sentences(post, CheckReport(issues))
    return EditCheck(passed=not issues, post=post, failing=failing, issues=issues,
                     seconds=round(time.perf_counter() - t0, 3))


__all__ = ["check_edit", "post_from_text", "EditCheck"]
