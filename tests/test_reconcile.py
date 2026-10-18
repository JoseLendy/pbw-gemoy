import dataclasses

from agent.reconcile import reconcile
from agent.schemas import Conflict, NeedsHuman, ScenarioAnalysis, Strategy
from tests.fakes import DEMO, FakeLLM, fake_ledger, fake_task


def _analysis(cats):
    return ScenarioAnalysis("新生", "比较", "怕重", "到店", cats)


def _llm(ids, **extra):
    d = {"angle": "宿舍教室来回跑", "cta_type": "到店体验", "talk_card": ["a", "b", "c"],
         "selling_points": [{"fact_id": i, "reason": "匹配"} for i in ids]}
    d.update(extra)
    return FakeLLM({"reconcile": d})


def test_categories_without_facts_are_dropped():
    s = reconcile(fake_task(), _analysis(["portability", "security", "service"]), fake_ledger(), DEMO,
                  _llm(["F1", "F7"]))
    assert isinstance(s, Strategy)
    assert set(s.dropped_categories) == {"security", "service"}
    assert s.dropped_categories["security"] == "知识库无该类资料"


def test_invalid_fact_id_rejected():
    s = reconcile(fake_task(), _analysis(["portability", "battery"]), fake_ledger(), DEMO,
                  _llm(["F99", "F1", "F7"]))
    ids = [sp.fact_id for sp in s.selling_points]
    assert "F99" not in ids and ids == ["F1", "F7"]


def test_moments_exactly_one():
    s = reconcile(fake_task("moments"), _analysis(["portability", "battery"]), fake_ledger(), DEMO,
                  _llm(["F1", "F7", "F11"]))
    assert len(s.selling_points) == 1


def test_poster_at_most_three():
    s = reconcile(fake_task("poster"), _analysis(["portability", "battery", "display", "ports"]),
                  fake_ledger(), DEMO, _llm(["F1", "F7", "F3", "F10"]))
    assert 1 <= len(s.selling_points) <= 3


def test_needs_human_attribute_chosen():
    model = dataclasses.replace(DEMO, needs_human=["cpu"])
    r = reconcile(fake_task(), _analysis(["performance", "portability"]), fake_ledger(), model,
                  _llm(["F8", "F1"]))
    assert isinstance(r, NeedsHuman)
    assert "cpu" in r.message


def test_needs_human_attribute_unchosen_goes_to_pending():
    model = dataclasses.replace(DEMO, needs_human=["cpu"])
    s = reconcile(fake_task(), _analysis(["portability", "battery"]), fake_ledger(), model,
                  _llm(["F1", "F7"]))
    assert isinstance(s, Strategy)
    assert any("cpu" in p for p in s.pending)


def test_conflict_on_chosen_fact_stops():
    led = fake_ledger()
    led.conflicts = [Conflict("weight", "标准版", ["F1", "F2"], "同变体数值不同")]
    r = reconcile(fake_task(), _analysis(["portability"]), led, DEMO, _llm(["F1", "F7"]))
    assert isinstance(r, NeedsHuman) and "weight" in r.message


def test_conflict_on_unchosen_attribute_goes_to_pending():
    led = fake_ledger()
    led.conflicts = [Conflict("brightness", "all", ["F5"], "两处数值不同")]
    s = reconcile(fake_task(), _analysis(["portability", "battery", "display"]), led, DEMO,
                  _llm(["F1", "F7"]))
    assert isinstance(s, Strategy)
    assert any("brightness" in p for p in s.pending)


def test_talk_card_has_no_absolute_words():
    s = reconcile(fake_task(), _analysis(["portability", "battery"]), fake_ledger(), DEMO,
                  _llm(["F1", "F7"], talk_card=["本地视频播放最长约 14 小时", "客户最怕没电", "邀请到店试重量"]))
    assert all("最" not in t for t in s.talk_card)
    assert s.talk_card[0] == "本地视频播放可达约 14 小时"
    assert len(s.talk_card) == 2
