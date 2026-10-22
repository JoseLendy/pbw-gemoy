"""8D anti-AI style check (agent/style/antiai.py). Fakes only; the LLM judge is a FakeLLM."""
from __future__ import annotations

import dataclasses

import pytest

from agent.checks import run_all
from agent.style.antiai import SKIP_GROUPS, check_style, load_blocklist
from tests.fakes import FakeLLM, fake_ledger, fake_plan, fake_post, fake_task

SIB = {"demobook-14-se": fake_ledger("demobook-14-se")}


def codes(report, severity=None):
    return {i.code for i in report.issues if severity is None or i.severity == severity}


def spans(report, code):
    return {i.span for i in report.issues if i.code == code}


def with_body(*paragraphs, platform="xiaohongshu", cta=None):
    p = fake_post(platform)
    p.body = list(paragraphs)
    if cta is not None:
        p.cta = cta
    return p


def card_task(platform="moments", **kw):
    base = dict(source="card", card_id="S01-x", store_id="S01", slot="potential", segment="student",
                hook="scene", voice="senior", landmark="紫金港校区东门对面",
                angle="宿舍/图书馆场景", question=None)
    base.update(kw)
    return dataclasses.replace(fake_task(platform), **base)


# ------------------------------------------------------------------ blocklist config
def test_blocklist_has_no_absolute_group():
    bl = load_blocklist()
    assert "absolute" not in bl["phrases"]
    assert set(bl["phrases"]) == {"era_cliche", "corporate", "forced_slang", "sales_claims"}
    assert "absolute" in SKIP_GROUPS          # defensive: even if someone re-adds it, 8D ignores it


# ------------------------------------------------------------------ happy path
@pytest.mark.parametrize("platform", ["xiaohongshu", "wechat_article", "moments"])
def test_fake_post_passes_style(platform):
    assert codes(check_style(fake_post(platform))) == set()


# ------------------------------------------------------------------ phrases + patterns
def test_corporate_verb_fails():
    r = check_style(with_body("赋能学习，重量约 1.25 kg [F1]。"))
    assert "ai_cliche" in codes(r, "error") and spans(r, "ai_cliche") == {"赋能"}


def test_not_only_but_also_pattern_fails():
    r = check_style(with_body("不仅轻薄，更有长续航 [F1]。"))
    assert "ai_pattern" in codes(r, "error")
    assert any(s.startswith("不仅") and s.endswith("更") for s in spans(r, "ai_pattern"))


@pytest.mark.parametrize("word", ["热销", "爆款", "销量第一", "卖断货", "抢疯了"])
def test_sales_claim_words_fail(word):
    r = check_style(with_body(f"{word}款，重量约 1.25 kg [F1]。"))
    assert "ai_cliche" in codes(r, "error") and word in spans(r, "ai_cliche")


def test_era_cliche_and_forced_slang_fail():
    r = check_style(with_body("在这个快节奏的时代，家人们冲鸭。重量约 1.25 kg [F1]。"))
    assert spans(r, "ai_cliche") >= {"在这个快节奏的时代", "家人们", "冲鸭"}


def test_zuijin_and_diyici_do_not_trigger_8d():
    """最近 / 第一次 are everyday words: 8B owns absolute claims, 8D must never substring-match 最 / 第一."""
    r = check_style(with_body("最近第一次带去图书馆，重量约 1.25 kg [F1]。"))
    assert codes(r) == set()


def test_rewrite_instruction_names_the_exact_hit():
    r = check_style(with_body("赋能学习 [F1]。"))
    i = next(x for x in r.issues if x.code == "ai_cliche")
    assert i.field == "body[0]" and i.span == "赋能" and "赋能" in i.message


# ------------------------------------------------------------------ structure
def test_two_rhetorical_questions_fail_one_passes():
    two = with_body("要不要带充电器？", "放得下书包吗？", "重量约 1.25 kg [F1]。")
    one = with_body("要不要带充电器？", "重量约 1.25 kg [F1]。")
    assert "ai_rhetorical" in codes(check_style(two), "error")
    assert "ai_rhetorical" not in codes(check_style(one))


def test_three_parallel_sentences_fail():
    r = check_style(with_body("它很轻。它很薄。它很稳。重量约 1.25 kg [F1]。"))
    assert "ai_parallel" in codes(r, "error") and spans(r, "ai_parallel") == {"它很"}


def test_two_parallel_sentences_are_fine():
    assert "ai_parallel" not in codes(check_style(with_body("它很轻。它很薄。重量约 1.25 kg [F1]。")))


def test_emoji_limit_per_platform():
    assert "ai_emoji" in codes(check_style(with_body("好轻 😀😀😀，重量约 1.25 kg [F1]。", platform="moments")))
    assert "ai_emoji" not in codes(check_style(with_body("好轻 😀，重量约 1.25 kg [F1]。", platform="moments")))
    assert "ai_emoji" in codes(check_style(with_body("好轻 😀 [F1]。", platform="wechat_article")))


# ------------------------------------------------------------------ concrete detail (card posts only)
def test_card_post_without_concrete_detail_fails():
    r = check_style(with_body("重量约 1.25 kg [F1]，放进包里。", platform="moments", cta="来店里上手。"), card_task())
    assert "ai_no_detail" in codes(r, "error")


@pytest.mark.parametrize("detail", ["紫金港校区东门对面，重量约 1.25 kg [F1]。",     # landmark
                                    "下课去图书馆，重量约 1.25 kg [F1]。"])          # specific scene
def test_card_post_with_detail_passes(detail):
    r = check_style(with_body(detail, platform="moments", cta="来店里上手。"), card_task())
    assert "ai_no_detail" not in codes(r)


def test_logged_question_counts_as_detail():
    task = card_task(hook="customer", question={"chip_id": "q1", "text": "续航够一天吗", "count": 3})
    r = check_style(with_body("顾客常问“续航够一天吗”。重量约 1.25 kg [F1]。", platform="moments", cta="来店里。"), task)
    assert "ai_no_detail" not in codes(r)


def test_manual_flow_never_requires_a_detail():
    r = check_style(with_body("重量约 1.25 kg [F1]，放进包里。", platform="moments", cta="来店里上手。"),
                    fake_task("moments"))
    assert "ai_no_detail" not in codes(r)


# ------------------------------------------------------------------ LLM judge (stage 2)
def test_judge_runs_only_when_stage_1_is_clean():
    llm = FakeLLM({"8D": {"pass": False, "sentences": ["这是一款卓越的产品"]}})
    r = check_style(fake_post(), llm=llm)
    assert "ai_judge" in codes(r, "error") and spans(r, "ai_judge") == {"这是一款卓越的产品"}
    assert [c["stage"] for c in llm.calls] == ["8D"]

    llm2 = FakeLLM({"8D": {"pass": False}})
    r2 = check_style(with_body("赋能学习 [F1]。"), llm=llm2)
    assert "ai_cliche" in codes(r2) and "ai_judge" not in codes(r2)
    assert llm2.calls == []                     # stage 1 failed → judge never called


def test_judge_pass_is_clean():
    assert codes(check_style(fake_post(), llm=FakeLLM({"8D": {"pass": True}}))) == set()


def test_judge_failure_does_not_crash():
    class Boom:
        def chat_json(self, *a, **k):
            raise RuntimeError("down")
    r = check_style(fake_post(), llm=Boom())
    assert codes(r, "error") == set() and "ai_check_skipped" in codes(r, "warn")


# ------------------------------------------------------------------ wired into the loop
def test_run_all_includes_8d():
    p = fake_post()
    p.body[0] = "赋能学习，重量约 1.25 kg [F1]。"
    r = run_all(p, fake_ledger(), SIB, fake_task(), fake_plan())
    assert "8D" in {i.stage for i in r.issues} and not r.passed


def test_run_all_clean_post_has_no_8d_issue():
    r = run_all(fake_post(), fake_ledger(), SIB, fake_task(), fake_plan())
    assert not [i for i in r.issues if i.stage == "8D"]
