from agent.units import find_all, is_upper_bound, normalize, same_value


def test_weight_kg_and_grams_equal():
    a = normalize("约 1.25 kg（标准版含电池）")
    b = normalize("1250 克")
    assert a == (1250.0, "g", "约")
    assert same_value(a[0], a[1], b[0], b[1])


def test_inches_and_fullwidth():
    assert normalize("14.2 英寸")[:2] == (14.2, "inch")
    assert normalize("１４．２英寸")[:2] == (14.2, "inch")


def test_upper_bound_and_qualifier():
    v, u, q = normalize("最高 120 Hz")
    assert (v, u, q) == (120.0, "Hz", "最高")
    assert is_upper_bound("本地视频播放最长约 14 小时")
    assert not is_upper_bound("65 Wh（额定容量）")


def test_storage_tiers():
    tb = normalize("1 TB")
    assert same_value(tb[0], tb[1], 1024.0, "GB")
    assert same_value(tb[0], tb[1], 1000.0, "GB")
    assert not same_value(512.0, "GB", 1000.0, "GB")


def test_find_all_and_no_false_units():
    spans = find_all("重量约 1.25 kg，续航可达约 14 小时，3 个理由")
    assert [(v, u) for _, v, u in spans] == [(1250.0, "g"), (14.0, "h")]
    assert normalize("2026 开学季") == (None, "", "")


def test_different_values_not_equal():
    assert not same_value(1250.0, "g", 1380.0, "g")
    assert not same_value(120.0, "Hz", 60.0, "Hz")


# ---------------------------------------------------------------------- P2 extensions
import pytest  # noqa: E402

from agent.units import canonical, find_values, parse_dimensions, parse_resolution  # noqa: E402


@pytest.mark.parametrize("a,b", [("1.25kg", "1.25 kg"), ("500 尼特", "500nits"), ("326 PPI", "326 ppi"),
                                 ("1250 克", "1.25 kg"), ("65瓦时", "65 Wh"), ("14 英寸", "14寸")])
def test_spellings_are_the_same_value(a, b):
    va, ua, _ = normalize(a)
    vb, ub, _ = normalize(b)
    assert same_value(va, ua, vb, ub)


def test_resolution_is_a_pair_not_two_numbers():
    assert parse_resolution("2880 × 1920") == (2880, 1920)
    assert parse_resolution("3120x2080 像素") == (3120, 2080)
    assert find_values("2880 × 1920") == [] and normalize("2880 × 1920")[0] is None
    assert canonical("2880 × 1920") == canonical("2880x1920") != canonical("2560 × 1600")
    assert parse_resolution("313 × 222 × 15.9 mm") is None


def test_dimensions():
    assert parse_dimensions("约 313 mm × 222 mm × 15.9 mm") == [313.0, 222.0, 15.9]
    assert parse_dimensions("313 × 222 × 15.9 mm") == [313.0, 222.0, 15.9]
    assert parse_dimensions("31.3 cm × 22.2 cm") == [313.0, 222.0]
    assert parse_dimensions("1 × 3.5 mm 耳机接口") is None                # a count, not a size
    assert canonical("313 mm × 222 mm × 15.9 mm") == canonical("313 × 222 × 15.9 mm")


def test_ranges_give_multiple_values():
    assert find_values("16 GB / 32 GB") == [(16.0, "GB"), (32.0, "GB")]
    assert find_values("512 GB / 1 TB") == [(512.0, "GB"), (1000.0, "GB")]


@pytest.mark.parametrize("text,q,upper", [("约 1.25 kg", "约", False), ("500 nits（典型值）", "典型值", False),
                                          ("峰值亮度 1000 nits", "峰值", False), ("65 Wh（额定容量）", "额定", False),
                                          ("最高 120 Hz", "最高", True), ("最长约 14 小时", "最长", True)])
def test_qualifiers(text, q, upper):
    assert normalize(text)[2] == q and is_upper_bound(text) is upper


def test_no_false_units_in_model_names():
    assert find_values("Intel Core Ultra 7 155H") == []          # CPU suffix, not 155 hours
    assert find_values("支持 5G 网络") == []                       # network, not 5 grams
    assert find_values("麒麟 X90 处理器") == [] and find_values("2 in 1") == []
    assert find_values("14 h 续航，65 W 快充") == [(14.0, "h"), (65.0, "W")]


def test_same_value_contract_style_with_a_fact():
    from agent.schemas import Fact
    f = Fact(id="F1", model_id="m", attribute="weight", category="portability", value="约 1.25 kg", quote="约 1.25 kg",
             source_title="t", source_path="p", norm_value=1250.0, norm_unit="g")
    assert same_value(f, 1250.0, "g") and not same_value(f, 1380.0, "g")
