"""Phase 4: 8C ai_tell and 8D ai_cliche/ai_pattern must not double-report the same hit."""
from __future__ import annotations

from agent.checks import run_all
from agent.formatter import _issue_line, render_report
from agent.pipeline import Deps, run
from agent.schemas import Post
from tests.fakes import fake_ledger, fake_plan, fake_post, fake_task


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


def test_pair_pattern_is_deduped_in_the_four_section_report():
    deps = Deps.fake()

    def write(task, strategy, ledger, plan, llm=None):
        p = fake_post("moments")
        p.body = ["这款产品不仅仅是轻薄，更是效率的体现。"]
        return p

    deps.write_post = write
    deps.run_checks = run_all
    deps.rewrite = lambda post, *a, **k: post   # keep the bad sentence so the final report shows the hit
    r = run("一位妈妈想给上大学的女儿买 DemoBook 14（演示版），发朋友圈", deps=deps)
    md = render_report(r)
    sec4 = md.split("## 四、核验结果", 1)[1]
    block = sec4.split("**文风（去模板化）**", 1)[1].split("**待确认信息**", 1)[0]
    hits = [line for line in block.splitlines() if "不仅仅是" in line]
    assert len(hits) == 1, hits
    assert "[8D/8C]" in hits[0]
