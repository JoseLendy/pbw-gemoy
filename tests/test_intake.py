from agent.intake import map_platform, map_scenario, parse_task
from agent.schemas import Clarification, Task
from tests.fakes import FakeCatalog, FakeLLM


def _llm(**data):
    base = {"product_query": None, "audience": None, "scenario": None, "platform": None,
            "variant": None, "extra_requirements": []}
    base.update(data)
    return FakeLLM({"intake": base})


def test_free_text_to_task():
    llm = _llm(product_query="DemoBook 14（演示版）", audience="大学新生，购买人为家长",
               scenario="开学", platform="小红书")
    t = parse_task("妈妈给女儿买电脑，发小红书", FakeCatalog(), llm=llm)
    assert isinstance(t, Task)
    assert t.model_id == "demobook-14"
    assert t.platform == "xiaohongshu" and t.scenario == "back_to_school"


def test_vague_request_gives_one_clarification():
    c = parse_task("我想买一台轻薄本", FakeCatalog(), llm=_llm())
    assert isinstance(c, Clarification)
    slots = [q.slot for q in c.questions]
    assert slots.count("product") == 1 and "platform" in slots
    prod = next(q for q in c.questions if q.slot == "product")
    assert prod.options and all(o in {m.canonical_name for m in FakeCatalog.models.values()} for o in prod.options)
    plat = next(q for q in c.questions if q.slot == "platform")
    assert plat.options == ["小红书", "朋友圈", "公众号", "海报"]


def test_ambiguous_product_has_two_options():
    llm = _llm(product_query="DemoBook 14", scenario="办公", platform="朋友圈")
    c = parse_task("DemoBook 14", FakeCatalog(), llm=llm)
    assert isinstance(c, Clarification)
    assert [q.slot for q in c.questions] == ["product"]
    assert len(c.questions[0].options) == 2


def test_not_found_offers_nearest():
    llm = _llm(product_query="NoSuchBook", scenario="办公", platform="朋友圈")
    c = parse_task("x", FakeCatalog(), llm=llm)
    assert isinstance(c, Clarification) and c.questions[0].options


def test_text_only_is_kept():
    llm = _llm(product_query="Demo 商用台式机 Pro", scenario="企业采购", platform="公众号")
    t = parse_task("x", FakeCatalog(), llm=llm)
    assert isinstance(t, Task) and t.model_id == "demo-desk-pro"


def test_synonyms():
    assert map_platform("微信文章") == "wechat_article"
    assert map_platform("红书") == "xiaohongshu"
    assert map_platform("朋友圈") == "moments"
    assert map_platform("海报") == "poster"
    assert map_platform("抖音") == "douyin"
    assert map_scenario("新生") == "back_to_school"
    assert map_scenario("出差") == "office"
    assert map_scenario("剪辑") == "creator"
    assert map_scenario("换机") == "family_upgrade"
    assert map_scenario("团购") == "enterprise"
    assert map_scenario("到店") == "store_visit"
    assert map_scenario("首发") == "new_launch"
    assert map_scenario("双十一") == "holiday"


def test_form_overrides_llm():
    llm = _llm(product_query="DemoBook 14（演示版）", scenario="办公", platform="小红书")
    t = parse_task("x", FakeCatalog(), form={"platform": "朋友圈", "scenario": "开学季"}, llm=llm)
    assert isinstance(t, Task)
    assert t.platform == "moments" and t.scenario == "back_to_school"


def test_extra_requirement_kept_verbatim():
    llm = _llm(product_query="DemoBook 14（演示版）", scenario="开学", platform="小红书",
               extra_requirements=["加上500元补贴"])
    t = parse_task("DemoBook 14（演示版），开学，小红书，加上500元补贴", FakeCatalog(), llm=llm)
    assert isinstance(t, Task)
    assert t.extra_requirements == ["加上500元补贴"]
