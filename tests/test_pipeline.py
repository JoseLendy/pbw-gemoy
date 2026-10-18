"""Pipeline tests on fakes only (no ima, no LLM)."""
from __future__ import annotations

import pytest

from agent.pipeline import Deps, check_loop, classify_edit, edit, run, run_all_platforms
from agent.schemas import (
    CheckIssue, CheckReport, Clarification, Model, NeedsHuman, RunResult, SECTION_HEADINGS,
)
from agent.formatter import render_report
from tests import fakes as F

TEXT = "一位妈妈想给下个月上大学的女儿买 DemoBook 14（演示版），发小红书"


@pytest.fixture
def deps() -> Deps:
    return Deps.fake()


def test_happy_path_returns_four_section_result(deps):
    lines = []
    r = run(TEXT, deps=deps, on_progress=lambda s, m: lines.append(m))
    assert isinstance(r, RunResult)
    assert r.post.platform == "xiaohongshu"
    assert r.task.scenario == "back_to_school"
    assert r.report.passed and r.pending == [] and r.loops == 0
    assert set(r.timings) >= {"intake", "retrieval", "ledger", "analyze", "reconcile", "plan", "write",
                              "check", "total"}
    md = render_report(r)
    for h in SECTION_HEADINGS:
        assert f"## {h}" in md
    assert any("读取产品资料" in m for m in lines)
    assert any("匹配到" in m and "张图片" in m for m in lines)
    assert any("核验" in m and "✓" in m for m in lines)
    assert any("合规检查 ✓" in m for m in lines)


def test_ambiguous_product_returns_clarification(deps):
    c = run("给上大学的女儿买 DemoBook 14，发小红书", deps=deps)
    assert isinstance(c, Clarification)
    q = [q for q in c.questions if q.slot == "product"][0]
    assert q.options == ["DemoBook 14（演示版）", "DemoBook 14 SE（演示版）"]
    assert c.partial.platform == "xiaohongshu"
    # chips answered via form → continues
    r = run("给上大学的女儿买 DemoBook 14，发小红书", form={"product": "DemoBook 14（演示版）"}, deps=deps)
    assert isinstance(r, RunResult) and r.model.model_id == "demobook-14"


def test_missing_platform_asks_once_for_everything(deps):
    c = run("DemoBook 14 SE 给女儿", deps=deps)
    assert isinstance(c, Clarification)
    assert {q.slot for q in c.questions} == {"platform", "scenario"}


def test_needs_human_when_cpu_chosen(deps):
    pro = Model(model_id="demobook-14", canonical_name="DemoBook 14（演示版）", folder_name="DemoBook 14",
                route="harmonyos", aliases=["DemoBook 14（演示版）"], needs_human=["cpu"])
    deps.catalog = F.FakeCatalog({**F.MODELS, "demobook-14": pro})

    def analyze_perf_first(task, llm=None):
        a = F.fake_analyze(task, llm)
        a.categories = ["performance", *a.categories]
        return a

    deps.analyze = analyze_perf_first
    r = run(TEXT, deps=deps)
    assert isinstance(r, NeedsHuman)
    assert "cpu" in r.message and r.conflicts


def test_needs_human_attribute_not_used_goes_to_pending(deps):
    pro = Model(model_id="demobook-14", canonical_name="DemoBook 14（演示版）", folder_name="DemoBook 14",
                route="harmonyos", aliases=["DemoBook 14（演示版）"], needs_human=["cpu"])
    deps.catalog = F.FakeCatalog({**F.MODELS, "demobook-14": pro})
    r = run(TEXT, deps=deps)
    assert isinstance(r, RunResult)
    assert any("cpu" in p for p in r.pending)


def _failing_checks(n_fail: int):
    calls = {"n": 0}

    def run_checks(post, ledger, sibling_ledgers, task, plan, llm=None):
        calls["n"] += 1
        if calls["n"] <= n_fail:
            return CheckReport([CheckIssue("8B", "error", "banned_word", "含绝对化用语", field="body[0]",
                                           span="课多")])
        return CheckReport()

    return run_checks, calls


def test_check_loop_fails_twice_then_passes(deps):
    deps.run_checks, calls = _failing_checks(2)
    r = run(TEXT, deps=deps)
    assert r.loops == 2 and calls["n"] == 3
    assert r.report.passed and r.pending == []
    assert "课多" not in r.post.body[0]      # rewritten


def test_check_loop_gives_up_after_two_loops(deps):
    deps.run_checks, calls = _failing_checks(3)
    r = run(TEXT, deps=deps)
    assert r.loops == 2 and calls["n"] == 3
    assert not r.report.passed
    assert any("含绝对化用语" in p for p in r.pending)


def test_image_shortage_is_pending_not_padded(deps):
    deps.get_bundle = lambda model_id, catalog=None: F.fake_bundle(model_id, n_images=1)
    r = run(TEXT, deps=deps)
    assert r.plan.shortage and len(r.plan.items) == 1
    assert any("图片不足" in p for p in r.pending)


def test_text_only_model_has_no_images(deps):
    r = run("Demo 商用台式机 Pro 企业采购 发公众号", deps=deps)
    assert isinstance(r, RunResult)
    assert r.post.images == [] and any("无该型号图片" in p for p in r.pending)


def test_edit_platform_reuses_bundle_and_ledger(deps):
    r = run(TEXT, deps=deps)
    calls = {"bundle": 0, "ledger": 0}

    def no_bundle(*a, **k):
        calls["bundle"] += 1
        raise AssertionError("get_bundle must not be called on edit")

    def no_ledger(*a, **k):
        calls["ledger"] += 1
        raise AssertionError("build_ledger must not be called on edit")

    deps.get_bundle, deps.build_ledger = no_bundle, no_ledger
    r2 = edit(r, "换成朋友圈", deps)
    assert isinstance(r2, RunResult)
    assert r2.post.platform == "moments" and r2.plan.platform == "moments"
    assert r2.ledger is r.ledger and r2.strategy is r.strategy
    assert len(r2.post.images) <= 3 and len(r2.post.body) == 1
    assert calls == {"bundle": 0, "ledger": 0}


def test_every_edit_path_ends_in_check_loop(deps):
    r = run(TEXT, deps=deps)
    for instr in ("短一点", "换成公众号", "突出续航", "换个角度", "换成职场办公人群"):
        deps.run_checks, calls = _failing_checks(1)
        r2 = edit(r, instr, deps)
        assert isinstance(r2, RunResult), instr
        assert calls["n"] == 2 and r2.loops == 1, instr


def test_edit_classifier():
    assert classify_edit("换成朋友圈")[0] == "platform"
    assert classify_edit("改成公众号")[1]["platform"] == "wechat_article"
    assert classify_edit("短一点")[0] == "writer"
    assert classify_edit("语气亲切一点")[0] == "writer"
    assert classify_edit("突出续航")[0] == "reconcile"
    assert classify_edit("换个角度")[0] == "reconcile"
    assert classify_edit("换人群，面向上班族")[0] == "analyze"
    assert classify_edit("换成职场办公场景") == ("analyze", {"scenario": "office", "requirement": "换成职场办公场景"})


def test_edit_scenario_changes_angle_and_order(deps):
    r = run(TEXT, deps=deps)
    r2 = edit(r, "换成职场办公场景", deps)
    assert r2.task.scenario == "office"
    assert r2.strategy.angle != r.strategy.angle
    assert [s.fact_id for s in r2.strategy.selling_points] != [s.fact_id for s in r.strategy.selling_points]


def test_all_platforms(deps):
    r = run(TEXT, deps=deps)
    out = run_all_platforms(r, deps=deps)
    assert set(out) == {"wechat_article", "xiaohongshu", "moments"}
    assert all(isinstance(v, RunResult) and v.post.platform == p for p, v in out.items())


def test_check_loop_direct(deps):
    r = run(TEXT, deps=deps)
    post, report, loops = check_loop(r.post, r.task, r.strategy, r.ledger, {}, r.plan, deps)
    assert report.passed and loops == 0


def test_auto_reports_fake_fields():
    d = Deps.auto()   # real where the module imports, fake otherwise
    assert d.is_dev_mode == bool(d.fake_fields)
    assert set(d.fake_fields) <= {"catalog", "get_bundle", "build_ledger", "plan_images", "parse_task",
                                  "analyze", "reconcile", "write_post", "rewrite", "run_checks", "llm",
                                  "status"}


# ---------------------------------------------------------------- citation auto-fix in the check loop
def _renumbered_ledger():
    """The DemoBook ledger with F1 -> F51 and F7 -> F57 (the shape of the live-run case)."""
    import dataclasses
    led = F.fake_ledger()
    ren = {"F1": "F51", "F7": "F57"}
    led.facts = [dataclasses.replace(f, id=ren.get(f.id, f.id)) for f in led.facts]
    return led


def test_missing_citation_fixed_in_code_without_rewrite(deps):
    from agent.checks import run_all
    ledger = _renumbered_ledger()
    sentence = "重量约 1.25 kg，本地视频播放可达约 14 小时"
    post = F.fake_post()
    post.body = [f"重量约 1.25 kg [F51]，本地视频播放可达约 14 小时。", "多屏协同 [F11] 让手机里的课件直接拖到电脑上。"]
    post.selling_points = ["F51", "F11"]

    class OnceLLM:   # 8A flags the missing F57 once; after the code fix it has nothing to say
        def __init__(self):
            self.n8a = 0

        def chat_json(self, system, user, stage="", **kw):
            if stage == "8A":
                self.n8a += 1
                if self.n8a == 1:
                    return {"issues": [{"field": "body[0]", "sentence": sentence, "code": "uncited_claim",
                                        "message": "续航未标注编号", "fact_id": "F57"}]}
            return {"issues": []}

    rewrites = []
    deps.llm = OnceLLM()
    deps.run_checks = run_all
    deps.rewrite = lambda *a, **k: rewrites.append(1) or a[0]
    task, strategy = F.fake_task(), F.fake_strategy()
    lines = []
    new, report, loops = check_loop(post, task, strategy, ledger, {}, F.fake_plan(), deps,
                                    on_progress=lambda s, m: lines.append(m))
    assert report.passed, [i.message for i in report.issues if i.severity == "error"]
    assert loops == 1 and rewrites == []
    assert new.body[0] == "重量约 1.25 kg [F51]，本地视频播放可达约 14 小时 [F57]。"
    assert "F57" in new.selling_points
    assert any("补上 1 处事实编号" in m for m in lines)


def test_auto_cite_plus_other_errors_rewrites_only_the_rest(deps):
    ledger = F.fake_ledger()
    post = F.fake_post()
    post.body[0] = "重量约 1.25 kg，放进双肩包不占地方。"
    cite = CheckIssue("8A", "error", "uncited_claim", "x", "body[0]", "重量约 1.25 kg，放进双肩包不占地方", "F1")
    other = CheckIssue("8B", "error", "banned_word", "x", "cta", "最")
    reports = iter([CheckReport([cite, other]), CheckReport()])
    deps.run_checks = lambda *a, **k: next(reports)
    got = []
    deps.rewrite = lambda p, errors, *a, **k: got.append(errors) or p
    new, report, loops = check_loop(post, F.fake_task(), F.fake_strategy(), ledger, {}, F.fake_plan(), deps)
    assert report.passed and loops == 1
    assert got == [[other]] and "[F1]" in new.body[0]


# ---------------------------------------------------------------- variant check after the ledger
def test_unknown_variant_becomes_pending_note(deps):
    base = deps.parse_task

    def parse(text, catalog, form=None, llm=None):
        t = base(text, catalog, form, llm)
        t.variant = "64GB"
        return t
    deps.parse_task = parse
    r = run(TEXT, deps=deps)
    assert isinstance(r, RunResult) and r.task.variant is None
    note = "配置「64GB」未在该型号资料中找到，已按全部配置处理"
    assert note in r.pending
    r2 = edit(r, "短一点", deps=deps)              # the note survives edits
    assert note in r2.pending


def test_known_variant_kept(deps):
    r = run(TEXT, form={"variant": "触控版"}, deps=deps)
    assert isinstance(r, RunResult) and r.task.variant == "触控版" and r.pending == []
