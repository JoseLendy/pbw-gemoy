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
