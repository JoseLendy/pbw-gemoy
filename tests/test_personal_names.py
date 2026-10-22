"""8B personal_name: no staff name or sign-off anywhere in a post or its 导购话术 (synthetic text)."""
from __future__ import annotations

from agent.checks.compliance import check_compliance
from agent.checks.names import names_in, personal_name_issues
from agent.reconcile import reconcile
from agent.schemas import ScenarioAnalysis, Task
from tests.fakes import DEMO, FakeLLM, fake_ledger, fake_post, fake_task


def _post(body, cta="想上手试试，私信我或到店找我。"):
    p = fake_post("moments")
    p.body, p.cta = list(body), cta
    return p


def _name_codes(post):
    return [i for i in check_compliance(post, fake_ledger(), fake_task("moments")).issues if i.code == "personal_name"]


def test_post_ending_in_a_sign_off_fails():
    issues = _name_codes(_post(["重量约 1.25 kg [F1]，演示广场附近的门店。"], cta="到店上手试试。\n小王"))
    assert issues and all(i.severity == "error" and i.stage == "8B" for i in issues)


def test_sign_off_glued_on_with_a_comma_fails():
    assert _name_codes(_post(["重量约 1.25 kg [F1]。"], cta="想上手试试，小王"))


def test_name_inside_the_text_fails():
    assert _name_codes(_post(["重量约 1.25 kg [F1]，来了找小许。"]))
    assert _name_codes(_post(["重量约 1.25 kg [F1]。", "到店招呼一声小周就行。"]))


def test_unlisted_name_standing_alone_at_the_end_fails():
    assert _name_codes(_post(["重量约 1.25 kg [F1]。"], cta="到店上手试试。\n王磊"))


def test_post_without_names_passes():
    assert not _name_codes(_post(["重量约 1.25 kg [F1]，演示广场附近的门店，续航可达约 14 小时 [F7]。"]))
    for cta in ("私信我", "想上手试试，到店找我。", "到店看看。\n欢迎来", "有问题问老师也行，到店找我。"):
        assert not _name_codes(_post(["重量约 1.25 kg [F1]。"], cta=cta)), cta


def test_hours_and_everyday_words_are_not_names():
    assert not personal_name_issues([("body[0]", "本地视频播放可达约 14 小时")])
    assert names_in("家里老人和小孩都能用") == []


def test_reconcile_drops_a_talk_card_line_with_a_name():
    llm = FakeLLM({"reconcile": {"angle": "背着跑", "selling_points": [{"fact_id": "F1", "reason": "轻"}],
                                 "cta_type": "到店体验", "talk_card": ["先问顾客平时背包走多远", "有问题找小王", "邀请到店上手"]}})
    a = ScenarioAnalysis(audience="学生", buying_stage="比较", problem="背着跑", content_goal="到店",
                         categories=["portability"])
    s = reconcile(Task(raw_text="", model_id="demobook-14", platform="moments"), a, fake_ledger(), DEMO, llm)
    assert s.talk_card == ["先问顾客平时背包走多远", "邀请到店上手"]


def test_brief_asks_for_first_person_without_a_name():
    from agent.style.profile import brief
    t = Task(raw_text="", model_id="demobook-14", platform="moments", source="card", landmark="演示广场附近")
    b = brief(t)
    assert "私信我" in b and "署名" in b and "不出现任何人名" in b
