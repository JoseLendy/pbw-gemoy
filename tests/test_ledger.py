"""Fact ledger on synthetic fixtures only (DemoBook + tests/fixtures/p2). No ima, no LLM, no KB text."""
import dataclasses
from pathlib import Path

import pytest

from agent import ledger as ledger_mod
from agent.ledger import build_ledger, find_conflicts, parse_specs, quote_ok
from agent.schemas import CATEGORIES
from agent.units import find_values, same_value
from tests.fakes import FakeLLM, fake_bundle, fake_ledger

P2 = Path(__file__).parent / "fixtures" / "p2"


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(ledger_mod, "LEDGER_CACHE", tmp_path / "ledger")


def bundle(facts_file=None, claims_file=None, model_id="demobook-14"):
    b = fake_bundle(model_id)
    if facts_file:
        b = dataclasses.replace(b, facts_text=(P2 / facts_file).read_text("utf-8"))
    if claims_file is not None:
        b = dataclasses.replace(b, claims_text=(P2 / claims_file).read_text("utf-8") if claims_file else "")
    return b


def by_attr(led, attr):
    return [f for f in led.facts if f.attribute == attr]


@pytest.fixture
def demo():
    return build_ledger(fake_bundle("demobook-14"))


def test_parser_finds_the_specs(demo):
    w = by_attr(demo, "weight")
    assert [(f.variant, f.norm_value, f.norm_unit, f.qualifier) for f in w] == [
        ("标准版", 1250.0, "g", "约"), ("触控版", 1270.0, "g", "约")]
    (screen,) = by_attr(demo, "screen_size")
    assert (screen.norm_value, screen.norm_unit, screen.category) == (14.2, "inch", "display")
    (rr,) = by_attr(demo, "refresh_rate")
    assert (rr.norm_value, rr.qualifier, rr.upper_bound) == (120.0, "最高", True)
    (bat,) = by_attr(demo, "battery_capacity")
    assert (bat.norm_value, bat.norm_unit, bat.qualifier, bat.variant) == (65.0, "Wh", "额定", "all")
    (life,) = by_attr(demo, "battery_life")
    assert (life.norm_value, life.norm_unit, life.qualifier, life.upper_bound) == (14.0, "h", "最长", True)
    (cpu,) = by_attr(demo, "cpu")
    assert cpu.kind == "entity" and cpu.value == "演示芯片 D90" and cpu.category == "performance"
    (res,) = by_attr(demo, "resolution")
    assert res.norm_value is None and res.norm_unit == "resolution"      # a pair, not two numbers
    (dims,) = by_attr(demo, "dimensions")
    assert dims.category == "portability" and dims.norm_unit == "mm"
    assert {"演示芯片 D90", "USB-C", "USB-A", "多屏协同", "DemoOS 5"} <= set(demo.entities)
    assert len(demo.entities) == len(set(demo.entities))
    assert all(f.category in CATEGORIES for f in demo.facts)
    assert [f.id for f in demo.facts] == [f"F{i}" for i in range(1, len(demo.facts) + 1)]
    assert [f.kind for f in demo.facts][-1] == "claim" and demo.facts[0].kind == "spec"   # specs first


def test_ports_are_entities_not_numbers(demo):
    (ports,) = by_attr(demo, "ports")
    assert ports.kind == "entity" and ports.norm_value is None
    assert {"USB-C", "USB-A"} <= set(demo.entities)


def test_memory_is_a_variant_set_not_a_conflict(demo):
    (mem,) = by_attr(demo, "memory")
    assert mem.value == "16 GB / 32 GB" and mem.norm_value is None and mem.norm_unit == "GB"
    assert find_values(mem.value) == [(16.0, "GB"), (32.0, "GB")]
    assert demo.conflicts == []


def test_banner_stripped_and_footnotes_are_boundaries(demo):
    assert not any("即将离开" in f.value or "继续访问" in f.quote for f in demo.facts)
    foot = [b for b in demo.boundaries if b["source_title"] == "产品事实.md"]
    assert [b["category"] for b in foot] == ["portability", "battery"]
    assert not any(f.value.startswith("*") or "实验室环境" in f.value for f in demo.facts)


def test_claims_from_angles(demo):
    claims = [f for f in demo.facts if f.kind == "claim"]
    assert [(f.attribute, f.category) for f in claims] == [
        ("angle_1", "portability"), ("angle_2", "battery"), ("angle_3", "collaboration")]
    assert claims[0].value == "适合经常带出门的学生和通勤用户"
    assert claims[0].quote == "可用结论：适合经常带出门的学生和通勤用户。"
    # every 支撑事实 matches a spec fact (weight, 65 Wh, 14 h, 多屏协同), so nothing extra is added
    assert len(demo.facts) == 18
    angle_bounds = [b for b in demo.boundaries if b["source_title"] == "卖点与限制.md"]
    assert [b["category"] for b in angle_bounds] == ["portability", "battery", "collaboration", "other"]
    assert angle_bounds[-1]["text"] == "全网最轻的笔记本"                    # the 不要写 example


def test_claims_bold_label_layout():
    led = build_ledger(bundle(claims_file="claims_bold.md"))
    claims = [f for f in led.facts if f.kind == "claim"]
    assert [(f.attribute, f.category, f.value) for f in claims] == [
        ("angle_1", "portability", "背着走一天也不累"), ("angle_2", "battery", "一天的课少找插座")]
    extra = [f for f in led.facts if f.source_title == "卖点与限制.md" and f.kind == "spec"]
    assert [f.value for f in extra] == ["机身采用演示合金材质", "演示快充 30 分钟可充入 50%"]   # not in the specs
    assert [f.category for f in extra] == ["portability", "battery"]
    texts = [b["text"] for b in led.boundaries if b["source_title"] == "卖点与限制.md"]
    assert texts == ["不要写成同类最轻。", "续航为实验室数据。", "演示本是最轻的笔记本"]


def test_unit_trap_no_conflict():
    led = build_ledger(bundle("unit_trap.md", claims_file=""))
    w = by_attr(led, "weight")
    assert len(w) == 2 and same_value(w[0], w[1].norm_value, w[1].norm_unit)
    assert led.conflicts == []


def test_variant_trap_no_conflict():
    led = build_ledger(fake_bundle("demobook-14"))
    assert {f.variant for f in by_attr(led, "weight")} == {"标准版", "触控版"}
    assert led.conflicts == []


def test_real_conflict_found_once_per_attribute():
    led = build_ledger(bundle("real_conflict.md", claims_file=""))
    by = {c.attribute: c for c in led.conflicts}
    assert set(by) == {"weight", "cpu"}
    w = by["weight"]
    assert w.variant == "all" and len(w.fact_ids) == 2
    assert {led.get(i).value for i in w.fact_ids} == {"约 1.25 kg", "约 1.38 kg"}
    assert set(by["cpu"].fact_ids) == {f.id for f in by_attr(led, "cpu")}


def test_options_under_one_label_and_sub_labels():
    led = build_ledger(bundle("options.md", claims_file=""))
    cpu = by_attr(led, "cpu")
    assert [f.variant for f in cpu] == ["配置1", "配置2"] and led.conflicts == []
    assert [(f.variant, f.norm_value) for f in by_attr(led, "brightness")] == [("标准版", 500.0), ("柔光版", 400.0)]
    feat = [f for f in led.facts if f.attribute.startswith("spec_")]
    assert len(feat) == 1 and feat[0].quote.startswith("演示助手*") and "演示助手" in led.entities
    assert [f.value for f in by_attr(led, "package")] == ["电源适配器", "演示数据线"]
    assert not any("即将离开" in f.value or "取消" == f.value for f in led.facts)


def test_hallucinated_llm_row_is_dropped():
    good = {"attribute": "feature", "category": "portability", "value": "放进双肩包不占地方",
            "quote": "演示机身轻巧，放进双肩包不占地方。", "variant": "all"}
    fake = {"attribute": "weight", "category": "portability", "value": "约 0.99 kg",
            "quote": "重量约 0.99 kg", "variant": "all"}
    off = {"attribute": "feature", "category": "portability", "value": "全天续航",
           "quote": "演示机身轻巧，放进双肩包不占地方。", "variant": "all"}
    llm = FakeLLM({"ledger_claims": {"rows": [good, fake, off]}})
    led = build_ledger(bundle(claims_file="claims_prose.md"), llm=llm)
    assert [c["stage"] for c in llm.calls] == ["ledger_claims"]
    claims = [f for f in led.facts if f.kind == "claim"]
    assert [f.value for f in claims] == ["放进双肩包不占地方"]
    assert [d["row"]["value"] for d in led.dropped] == ["约 0.99 kg", "全天续航"]
    assert all(d["reason"] for d in led.dropped)
    assert not any(f.value == "约 0.99 kg" for f in led.facts)


def test_llm_not_called_when_code_parses_angles(demo):
    llm = FakeLLM({"ledger_claims": {"rows": []}})
    build_ledger(fake_bundle("demobook-14"), llm=llm)
    assert llm.calls == []


def test_builds_without_llm_and_with_empty_claims():
    led = build_ledger(bundle(claims_file="claims_prose.md"), llm=None)
    assert led.facts and not any(f.kind == "claim" for f in led.facts)


def test_sibling_ledgers_differ():
    a, b = build_ledger(fake_bundle("demobook-14")), build_ledger(fake_bundle("demobook-14-se"))
    for attr in ("weight", "battery_capacity", "cpu", "refresh_rate"):
        va, vb = {f.value for f in by_attr(a, attr)}, {f.value for f in by_attr(b, attr)}
        assert va and vb and not va & vb, attr
    assert "HDMI" in b.entities and "HDMI" not in a.entities
    assert "演示芯片 D70" in b.entities and "演示芯片 D70" not in a.entities


@pytest.mark.parametrize("model_id", ["demobook-14", "demobook-14-se"])
@pytest.mark.parametrize("facts_file,claims_file", [(None, None), ("options.md", "claims_bold.md"),
                                                    ("real_conflict.md", None)])
def test_every_fact_is_grounded(model_id, facts_file, claims_file):
    b = bundle(facts_file, claims_file, model_id)
    led = build_ledger(b)
    for f in led.facts:
        src = b.facts_text if f.source_title == "产品事实.md" else b.claims_text
        assert quote_ok(f.quote, f.value, src), f
        assert f.source_path.endswith(f.source_title)


def test_matches_fake_ledger_values():
    for mid in ("demobook-14", "demobook-14-se"):
        mine = build_ledger(fake_bundle(mid))
        got = {(f.attribute, f.value) for f in mine.facts}
        for f in fake_ledger(mid).facts:
            if f.kind == "claim":
                assert any(g.value == f.value and g.category == f.category for g in mine.facts if g.kind == "claim")
            else:
                assert (f.attribute, f.value) in got, f
        assert set(fake_ledger(mid).entities) <= set(mine.entities)


def test_quote_ok():
    src = "## 屏幕\n刷新率\n\n最高 １２０ Hz\n"
    assert quote_ok("最高 120 Hz", "120 Hz", src)
    assert quote_ok("刷新率 最高 120 Hz", "最高 120 Hz", src)          # whitespace-normalised
    assert not quote_ok("最高 144 Hz", "144 Hz", src)
    assert not quote_ok("最高 120 Hz", "144 Hz", src)
    assert not quote_ok("", "", src)


def test_ledger_is_cached(tmp_path):
    b = fake_bundle("demobook-14")
    first = build_ledger(b)
    files = list((tmp_path / "ledger").glob("demobook-14-*.json"))
    assert len(files) == 1
    files[0].write_text(files[0].read_text("utf-8").replace("演示芯片 D90", "演示芯片 CACHED"), "utf-8")
    assert any(f.value == "演示芯片 CACHED" for f in build_ledger(b).facts)
    assert not any(f.value == "演示芯片 CACHED" for f in build_ledger(b, use_cache=False).facts)
    assert build_ledger(b).to_dict()["facts"][0] == first.to_dict()["facts"][0]


def test_find_conflicts_ignores_claims_lists_and_qualifier_kinds(demo):
    f1 = by_attr(demo, "brightness")[0]
    peak = dataclasses.replace(f1, id="X1", value="600 nits（峰值）", quote="600 nits（峰值）", norm_value=600.0,
                               qualifier="峰值")
    assert find_conflicts([f1, peak]) == []                            # typical vs peak: not the same claim
    p = by_attr(demo, "ports")[0]
    assert find_conflicts([p, dataclasses.replace(p, id="X2", value="1 × HDMI")]) == []


def test_parse_specs_unknown_label_keeps_label_in_quote():
    facts, _, _ = parse_specs("## 其他\n演示标签\n\n演示取值说明，用于测试。\n", "demobook-14")
    assert facts[0].attribute == "spec_1" and facts[0].quote == "演示标签 演示取值说明，用于测试。"
