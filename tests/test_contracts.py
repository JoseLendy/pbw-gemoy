"""Sanity checks for the shared contract and fakes. Must always pass on main."""
from agent.schemas import PLATFORM_IMAGE_RANGE, PLATFORMS, SECTION_HEADINGS
from tests.fakes import FakeCatalog, fake_bundle, fake_ledger, fake_plan, fake_post, fake_strategy


def test_headings_verbatim():
    assert SECTION_HEADINGS == ("一、场景判断", "二、知识库依据", "三、图文软文", "四、核验结果")


def test_platform_ranges_cover_all_platforms():
    assert set(PLATFORM_IMAGE_RANGE) == set(PLATFORMS)


def test_catalog_fake_statuses():
    c = FakeCatalog()
    assert c.resolve("DemoBook 14").status == "ambiguous"
    assert c.resolve("DemoBook 14 SE").status == "resolved"
    assert c.resolve("Demo 商用台式机 Pro").status == "text_only"
    assert c.resolve("NoSuchBook").status == "not_found"


def test_fake_ledger_quotes_are_in_fixture_text():
    b = fake_bundle("demobook-14")
    text = b.facts_text + b.claims_text
    for f in fake_ledger("demobook-14").facts:
        assert f.quote in text, f.id
        assert f.value in f.quote or f.kind == "claim", f.id


def test_fake_post_cites_existing_facts_and_planned_images():
    led = fake_ledger()
    for p in ("xiaohongshu", "wechat_article", "moments"):
        post = fake_post(p)
        assert all(led.get(fid) for fid in post.selling_points)
        planned = {i.image.media_id for i in fake_plan(p).items}
        assert all(im.media_id in planned for im in post.images)


def test_strategy_changes_with_scenario():
    a, b = fake_strategy("back_to_school"), fake_strategy("office")
    assert [s.fact_id for s in a.selling_points] != [s.fact_id for s in b.selling_points]
