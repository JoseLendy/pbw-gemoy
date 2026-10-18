"""8A fact and entity checks (agent/checks/facts.py)."""
from __future__ import annotations

import pytest

from agent.checks.facts import check_facts, mask_whitelisted
from agent.checks import strip_fact_tags
from tests.fakes import FakeLLM, fake_ledger, fake_post

SIB = {"demobook-14-se": fake_ledger("demobook-14-se")}


def issues(post, ledger=None, sibs=SIB, variant=None, llm=None):
    return check_facts(post, ledger or fake_ledger(), sibs, variant=variant, llm=llm)


def codes(report, severity=None):
    return {i.code for i in report.issues if severity is None or i.severity == severity}


def with_body(*paragraphs, **kw):
    p = fake_post(kw.pop("platform", "xiaohongshu"))
    p.body = list(paragraphs)
    return p


# ------------------------------------------------------------------ happy path
@pytest.mark.parametrize("platform", ["xiaohongshu", "wechat_article", "moments"])
def test_fake_post_passes_facts(platform):
    assert codes(issues(fake_post(platform)), severity="error") == set()


def test_units_module_is_used_not_duplicated():
    from agent import units
    assert units.same_value(1250, "g", 1250, "g")


# ------------------------------------------------------------------ numbers
def test_unit_trap_grams_for_kg_fact():
    assert codes(issues(with_body("重量 1250 克 [F1]")), "error") == set()


def test_unknown_number():
    assert "unsupported_number" in codes(issues(with_body("电池 70 Wh [F6]")), "error")


def test_sibling_number():
    p = with_body("重量约 1.38 kg [F1]")
    r = issues(p)
    assert "sibling_value" in codes(r, "error")
    assert any("相近型号" in i.message for i in r.issues if i.code == "sibling_value")


def test_sibling_entity():
    r = issues(with_body("接口有 USB-C 和 HDMI [F10]"))
    assert "sibling_entity" in codes(r, "error")


def test_target_entities_and_values_are_not_sibling_entities():
    # USB-C / 多屏协同 / 演示芯片 D90 belong to the target
    assert "sibling_entity" not in codes(issues(with_body("多屏协同 [F11]，2 个USB-C口 [F10]，采用演示芯片 D90 [F8]")))


def test_entity_check_is_word_bounded():
    # "Apple" must not fire on an unrelated word
    p = with_body("重量约 1.25 kg [F1]，放到背包里 Appear 也不占地方")
    assert "sibling_entity" not in codes(issues(p))


# ------------------------------------------------------------------ whitelist
def test_list_count_and_year_whitelisted():
    r = issues(with_body("2026 开学季，三个方面的 3 个理由：重量约 1.25 kg [F1]，续航约 14 小时 [F7]"))
    assert codes(r, "error") == set()


def test_usb_port_count_is_a_spec_not_a_list():
    assert "unsupported_number" in codes(issues(with_body("3 个USB口 [F10]")), "error")
    assert "unsupported_number" not in codes(issues(with_body("2 个USB-C口 [F10]")), "error")


def test_mask_whitelisted_prefers_longer_span():
    assert not mask_whitelisted("3 个理由").strip()
    assert "3" in mask_whitelisted("3 个USB口")


def test_date_and_store_hours_whitelisted():
    r = issues(with_body("9月1日到店，营业时间 9:00-21:00，重量约 1.25 kg [F1]"))
    assert codes(r, "error") == set()


def test_hashtag_numbers_whitelisted():
    r = issues(with_body("重量约 1.25 kg [F1] #2026开学季"))
    assert codes(r, "error") == set()


# ------------------------------------------------------------------ invented claims
@pytest.mark.parametrize("text,cat", [
    ("到店立减500元", "price"),
    ("热销10万台", "sales"),
    ("现货充足", "stock"),
    ("荣获年度大奖", "award"),
    ("好评如潮", "review"),
    ("渲染时间更短", "benchmark"),
    ("三年上门质保", "policy"),
])
def test_invented_claims_are_errors(text, cat):
    p = fake_post()
    p.cta = text
    r = issues(p)
    assert f"invented_{cat}" in codes(r, "error"), [i.message for i in r.issues]


def test_invented_claim_passes_when_ledger_supports_it():
    ledger = fake_ledger()
    ledger.facts[0] = ledger.facts[0].__class__(**{**ledger.facts[0].__dict__, "value": "约 1.25 kg（含三年质保）"})
    p = with_body("约 1.25 kg [F1]，含三年质保")
    assert "invented_policy" not in codes(issues(p, ledger))


# ------------------------------------------------------------------ fact ids
def test_unknown_fact_tag_and_selling_point():
    p = fake_post()
    p.body[0] += " [F99]"
    p.selling_points.append("F98")
    r = issues(p)
    assert "unknown_fact_id" in codes(r, "error")
    assert {i.span for i in r.issues if i.code == "unknown_fact_id"} == {"F99", "F98"}


def test_sibling_ids_are_unknown_in_target_ledger():
    # demobook-14-se has F4 = cpu, the target F4 = refresh rate; ids are per ledger, not global
    assert codes(issues(with_body("多屏协同 [F11]")), "error") == set()


# ------------------------------------------------------------------ variants
def test_variant_specified_allows_matching_fact():
    assert codes(issues(with_body("重量约 1.27 kg（触控版）[F2]"), variant="触控版"), "error") == set()


def test_variant_mismatch_is_error():
    assert "variant_mismatch" in codes(issues(with_body("重量约 1.27 kg（触控版）[F2]"), variant="标准版"), "error")


def test_variant_unspecified_warns():
    r = issues(with_body("重量约 1.27 kg（触控版）[F2]"))
    assert "variant_unspecified" in codes(r, "warn")
    assert "未指定配置，已写入的数值属于某一配置" == next(
        i.message for i in r.issues if i.code == "variant_unspecified")[:18]


def test_all_variant_fact_needs_no_variant():
    assert "variant_unspecified" not in codes(issues(with_body("屏幕 14.2 英寸 [F3]")))


# ------------------------------------------------------------------ upper bounds
def test_upper_bound_written_plain_is_warn():
    r = issues(with_body("支持 120 Hz [F4]"))
    assert "upper_bound_plain" in codes(r, "warn")
    assert codes(r, "error") == set()


def test_upper_bound_word_present_is_fine():
    assert "upper_bound_plain" not in codes(issues(with_body("刷新率可达 120 Hz [F4]")))


# ------------------------------------------------------------------ LLM layer
def test_llm_uncited_claim():
    llm = FakeLLM({"8A": {"issues": [{"field": "body[0]", "sentence": "一整天不用充电",
                                      "code": "uncited_claim", "message": "无编号的续航表述"}]}})
    r = issues(fake_post(), llm=llm)
    assert "uncited_claim" in codes(r, "error")


def test_llm_unsupported_claim():
    llm = FakeLLM({"8A": {"issues": [{"field": "body[0]", "code": "weird_code", "message": "事实不支持"}]}})
    r = issues(fake_post(), llm=llm)
    assert "unsupported_claim" in codes(r, "error")


def test_llm_failure_does_not_crash():
    class Boom:
        def chat_json(self, *a, **k):
            raise RuntimeError("down")
    r = issues(fake_post(), llm=Boom())
    assert codes(r, "error") == set()
    assert "llm_check_skipped" in codes(r, "warn")


def test_llm_none_works():
    assert codes(issues(fake_post()), "error") == set()


# ------------------------------------------------------------------ strip_fact_tags
def test_strip_fact_tags_returns_sentence_and_id():
    clean, pairs = strip_fact_tags("重量约 1.25 kg [F1]，放包里不占地方。续航可达约 14 小时 [F7]。")
    assert "[F" not in clean
    assert pairs == [("重量约 1.25 kg，放包里不占地方。", "F1"), ("续航可达约 14 小时。", "F7")]


def test_strip_fact_tags_multiple_ids_in_one_sentence():
    clean, pairs = strip_fact_tags("接口 [F10][F11]")
    assert clean.strip() == "接口"
    assert [p[1] for p in pairs] == ["F10", "F11"]
