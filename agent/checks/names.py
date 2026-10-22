"""
8B personal_name: a post (and its 导购话术) carries no personal name. Posts speak in the first person without a
name (「私信我」「到店找我」), so they work for whoever posts them. Deterministic, no LLM.

    personal_name_issues(fields) -> list[CheckIssue]      fields: [(field, text), ...] in reading order
    names_in(text) -> list[str]                           every personal name found (for 导购话术 lines)

A name is found when
  - a name from config/personal_names.txt appears anywhere;
  - a name-shaped word (小/阿/老 + one character) follows 找 / 问 / 叫 / 喊 / 招呼 / 联系 / 我是 (「来了找小许」);
  - the post ends with a sign-off: a 2–3 character line standing alone at the end, or a name-shaped word
    closing the last field after a comma or sentence end (「……上手试试，小王」「……试试。小王」).
Common words of that shape (小时, 老师, 阿姨 …) are not names.
"""
from __future__ import annotations

import re

from agent.schemas import CheckIssue

STAGE = "8B"
_CJK = "一-鿿"
_NAME_SHAPE = rf"(?:小|阿|老)[{_CJK}]"
_NOT_NAMES = {"小时", "小孩", "小区", "小店", "小巧", "小屏", "小包", "小时候", "小伙", "小朋", "小姐", "小心",
              "小事", "小白", "小米", "老人", "老师", "老板", "老家", "老款", "老机", "老电", "老式", "阿姨"}
_ADDRESSED = re.compile(rf"(?:找|问|叫|喊|招呼|联系|我是)\s*({_NAME_SHAPE})(?![{_CJK}])")
_CLOSING = re.compile(rf"(?:^|[，,、。！!？?～~\s—\-])({_NAME_SHAPE}[{_CJK}]?)\s*[。！!～~]?\s*$")
_STANDALONE = re.compile(rf"^[—\-～~\s]*([{_CJK}]{{2,3}})\s*$")
_TAG = re.compile(r"\s*\[F\d+\]")
# A short last line with any of these is a phrase (「私信我」「欢迎来」「谢谢」), not a name standing alone.
_PHRASE_CHARS = set("我你您他她们来去看试店的了吧呢吗啊哦呀欢迎谢好在有是不到约聊问")


def _listed() -> tuple[str, ...]:
    from agent.checks import load_lines
    return load_lines("personal_names.txt")


def names_in(text: str) -> list[str]:
    """Personal names in a piece of text (list matches and addressed name-shaped words; no sign-off rule)."""
    t = _TAG.sub("", text or "")
    found = [n for n in _listed() if n in t]
    found += [m.group(1) for m in _ADDRESSED.finditer(t) if m.group(1) not in _NOT_NAMES]
    return list(dict.fromkeys(found))


def _issue(message: str, field: str, span: str) -> CheckIssue:
    return CheckIssue(stage=STAGE, severity="error", code="personal_name", message=message, field=field, span=span)


def personal_name_issues(fields: list[tuple[str, str]]) -> list[CheckIssue]:
    issues: list[CheckIssue] = []
    for field, text in fields:
        for n in names_in(text):
            issues.append(_issue(f"文案里出现了人名「{n}」：不写任何人名或署名，用“私信我”“到店找我”", field, n))
    last = next(((f, _TAG.sub("", t).strip()) for f, t in reversed(fields) if (t or "").strip()), None)
    if last:
        field, text = last
        line = text.splitlines()[-1].strip() if text else ""
        m = _STANDALONE.match(line)
        name = m.group(1) if m and not (set(m.group(1)) & _PHRASE_CHARS) else ""
        if not name and (m := _CLOSING.search(text)):
            name = "" if (m.group(1) in _NOT_NAMES or m.group(1)[:2] in _NOT_NAMES) else m.group(1)
        if name and not any(name in i.span or i.span in name for i in issues):
            issues.append(_issue(f"结尾像是署名「{name}」：不写署名，发布人用第一人称邀请即可", field, name))
    return issues


__all__ = ["personal_name_issues", "names_in", "STAGE"]
