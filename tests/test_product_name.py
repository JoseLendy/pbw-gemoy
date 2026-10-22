"""8C product_unnamed: a publishable post names its product (full display name or an unambiguous official
short form) at least once. Texts are synthetic (S11's shape: only 「这台」, or a bare ambiguous name)."""
from __future__ import annotations

from agent.checks import run_all
from agent.checks.conformance import accepted_product_names, check_product_name
from agent.schemas import Post, PostImage, Task
from tests.fakes import fake_ledger, fake_plan

S11_SHAPE_BODY = ["挑礼物送人，你担心对方不会用？", "这台的演示触控板 [F1] 可以试试三指手势。",
                  "逛街路过就进来摸一摸，合不合手，自己试了才知道。"]


def _post(body, title="送人一台电脑，先来摸摸触控板", cta="私信我约个时间，到店上手试试。") -> Post:
    plan = fake_plan("moments")
    return Post("moments", title, "", list(body), cta, ["朋友圈"], ["F1"],
                [PostImage(p.image.media_id, p.position, p.caption) for p in plan.items[:1]])


def _card_task(model_id="demobook-14", display="DemoBook 14（演示版）") -> Task:
    return Task(raw_text="", product_query=display, model_id=model_id, platform="moments", source="card")


def _codes(issues):
    return {i.code for i in issues}


def test_s11_shape_with_no_product_name_fails():
    issues = check_product_name(_post(S11_SHAPE_BODY), _card_task())
    assert "product_unnamed" in _codes(issues)
    assert all(i.stage == "8C" and i.severity == "error" for i in issues if i.code == "product_unnamed")


def test_full_display_name_once_passes():
    body = [S11_SHAPE_BODY[0], "这台 DemoBook 14（演示版）的演示触控板 [F1] 可以试试。", S11_SHAPE_BODY[2]]
    assert check_product_name(_post(body), _card_task()) == []


def test_name_in_title_or_cta_counts():
    assert check_product_name(_post(S11_SHAPE_BODY, title="DemoBook 14（演示版）：先摸摸触控板"), _card_task()) == []
    assert check_product_name(_post(S11_SHAPE_BODY, cta="想摸摸 DemoBook 14（演示版），到店上手试试。"),
                              _card_task()) == []


def test_bare_ambiguous_name_fails():
    """「HUAWEI MateBook 14」 also names two other models: it does not name the D 14."""
    body = [S11_SHAPE_BODY[0], "这台 HUAWEI MateBook 14 的演示触控板 [F1] 可以试试。"]
    task = _card_task("matebook-d-14-2024", "HUAWEI MateBook D 14 2024")
    assert "product_unnamed" in _codes(check_product_name(_post(body), task))


def test_unambiguous_official_short_form_passes():
    task = _card_task("matebook-d-14-2024", "HUAWEI MateBook D 14 2024")
    body = [S11_SHAPE_BODY[0], "这台 MateBook D 14 的演示触控板 [F1] 可以试试。"]
    assert check_product_name(_post(body), task) == []


def test_short_form_that_is_part_of_another_models_name_is_not_accepted():
    """「MateBook D 16」 is the start of 「MateBook D 16 SE」: never an accepted form for the D 16 2024."""
    names = accepted_product_names("matebook-d-16-2024", "HUAWEI MateBook D 16 2024")
    assert "MateBook D 16" not in names
    assert "HUAWEI MateBook D 16 2024" in names


def test_fact_tags_and_spacing_do_not_hide_the_name():
    body = ["这台 DemoBook  14 （演示版）[F1] 的演示触控板可以试试。"]
    assert check_product_name(_post(body), _card_task()) == []


def test_run_all_reports_product_unnamed_for_a_card_post():
    report = run_all(_post(S11_SHAPE_BODY), fake_ledger(), {}, _card_task(), fake_plan("moments"))
    assert "product_unnamed" in {i.code for i in report.issues if i.severity == "error"}


def test_no_known_name_skips_the_check():
    """A manual-flow task without a display name on record is not judged on names it cannot know."""
    task = Task(raw_text="", product_query="DemoBook", model_id="demobook-14", platform="moments")
    assert check_product_name(_post(S11_SHAPE_BODY), task) == []
