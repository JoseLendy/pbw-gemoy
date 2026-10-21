"""
New-release truthfulness (Phase 5, Task 2). Part of 8B, card runs only.

Public copy may call a product new (新品 / 首发 / 新上市 / 刚发布 / 即将上市 …) or state a launch / release
date ONLY in a sentence that cites a ledger fact which itself carries release information. The demo
`launch_date` in data/demo/inputs/models.csv only schedules the 新品款 card; it is never a fact and never
reaches the writer, so it can never support a claim.

    release_facts(ledger)            -> list[Fact]        # facts that state a release / launch
    check_release(post, ledger, task) -> list[CheckIssue] (stage 8B)

Issue code (stage "8B"):
  release_unsupported   new-release wording or a release date with no tagged release fact   error
"""
from __future__ import annotations

import re

from agent.schemas import CheckIssue, Ledger, Post

STAGE = "8B"
RULE = "新品真实性规则：“新品、首发、新上市、刚发布、即将上市”等说法和上市/发布日期，只能写在引用了知识库上市/发布事实的句子里"

# Release wording. Kept to phrases that only mean "this product is new / launched / launching";
# 全新 (全新体验) and 换新机 (buying a new laptop) are ordinary words, not release claims.
RELEASE_RE = re.compile(
    r"新品|首发|首销|首卖|新上市|刚上市|即将上市|即将发布|即将开售|上市|刚刚?发布|新发布|正式发布|全新发布|"
    r"发布会|开售|预售|上新|新款|面世|问世")
RELEASE_ATTRS = {"release_date", "launch_date", "release", "launch"}
# A calendar date next to the claim: 2026年10月28日 / 10月28日 / 2026-10-28 / 2026.10.28
DATE_RE = re.compile(r"(?:(\d{4})\s*[年.\-/]\s*)?(\d{1,2})\s*[月.\-/]\s*(\d{1,2})\s*[日号]?")
_TAG_RE = re.compile(r"\[(F\d+)\]")
_SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?；;\n])")


def release_facts(ledger: Ledger) -> list:
    """Ledger facts that state a release or launch (by attribute, or release wording in value / quote)."""
    out = []
    for f in ledger.facts if ledger else []:
        if f.attribute in RELEASE_ATTRS or RELEASE_RE.search(f"{f.value} {f.quote}"):
            out.append(f)
    return out


def _dates(text: str) -> set[tuple[int, int]]:
    out = set()
    for m in DATE_RE.finditer(text or ""):
        month, day = int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            out.add((month, day))
    return out


def _fields(post: Post) -> list[tuple[str, str]]:
    out = [("title", post.title), ("intro", post.intro)]
    out += [(f"body[{i}]", p) for i, p in enumerate(post.body)]
    out.append(("cta", post.cta))
    out += [(f"images[{i}].caption", im.caption) for i, im in enumerate(post.images)]
    out += [("tags", t) for t in post.tags]
    return [(f, t or "") for f, t in out]


def _supported(sentence: str, by_id: dict) -> bool:
    """The sentence cites a release fact, and any date it states is a date that fact states."""
    cited = [by_id[i] for i in _TAG_RE.findall(sentence) if i in by_id]
    if not cited:
        return False
    stated = _dates(_TAG_RE.sub("", sentence))
    return not stated or any(stated <= _dates(f"{f.value} {f.quote}") for f in cited)


def check_release(post: Post, ledger: Ledger, task) -> list[CheckIssue]:
    if task is None or getattr(task, "source", "manual") != "card":
        return []
    by_id = {f.id: f for f in release_facts(ledger)}
    issues: list[CheckIssue] = []
    for field, text in _fields(post):
        for sent in _SENT_SPLIT_RE.split(text):
            m = RELEASE_RE.search(sent)
            if not m or _supported(sent, by_id):
                continue
            span = m.group(0)
            have = "、".join(by_id) if by_id else "本型号台账里没有任何上市/发布事实"
            issues.append(CheckIssue(
                stage=STAGE, severity="error", code="release_unsupported",
                message=f"「{span}」没有知识库上市/发布事实支持（{have}），删掉这类说法，改写成不提新品或上市时间的描述。{RULE}",
                field=field, span=span))
    return issues


__all__ = ["check_release", "release_facts", "RELEASE_RE", "RULE"]
