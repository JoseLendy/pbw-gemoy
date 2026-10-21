"""Phase 4: 8C ai_tell and 8D ai_cliche/ai_pattern must not double-report the same hit."""
from __future__ import annotations

from agent.checks import run_all
from agent.formatter import _issue_line
from agent.schemas import Post
from tests.fakes import fake_ledger, fake_plan, fake_task


def test_same_phrase_is_one_line_with_both_checker_ids():
    post = Post(platform="moments", title="", intro="", body=["这款产品赋能你的每一天。"],
                cta="到店看看", tags=["体验"], selling_points=[], images=[])
    report = run_all(post, fake_ledger(), {}, fake_task("moments"), fake_plan("moments"))
    hits = [i for i in report.issues if "赋能" in (i.span or "")]
    assert len(hits) == 1, [(i.stage, i.code, i.span) for i in hits]
    hit = hits[0]
    assert hit.stage == "8D" and "8C" in hit.also_stages
    line = _issue_line(hit)
    assert "[8D/8C]" in line and "赋能" in line
