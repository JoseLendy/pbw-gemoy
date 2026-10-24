"""Every generated post gets the full control set: 恢复原文 / 检查并保存, 复制, .md, 发布包, 保存图片, 已发布.
Fakes only; no ima or LLM."""
from __future__ import annotations

import dataclasses

import pytest

from agent.pipeline import Deps, run_from_card
from ui import state
from ui.components import fresh_session, phone_html

NAME = "DemoBook 14（演示版）"


def _demo_result(store_id: str = "S01"):
    s = fresh_session()
    state.load_store(s, store_id)
    card, key = state._current_card(s)
    demo = dataclasses.replace(card, model_id="demobook-14", display_name=NAME)
    return s, card, key, run_from_card(demo, Deps.fake())


# ---------------------------------------------------------------- 门店端: a next-card fallback stays editable
def test_next_card_fallback_keeps_the_edit_buttons():
    s, card, key, r = _demo_result()
    other = next(c for c in s["cards"] if c.card_id != card.card_id and not c.locked)
    r = dataclasses.replace(r, fallback="next_card",
                            task=dataclasses.replace(r.task, card_id=other.card_id, slot=other.slot))
    s["results"][key] = r
    out = state.render(s)
    assert out["editable"] is True and out["publishable"] is True
    assert out["downloadable"] is True and out["publish_label"].startswith("标记为已发布")


# ---------------------------------------------------------------- 朋友圈 preview shows every word that is posted
def test_moments_phone_shows_title_and_intro_that_the_copy_contains():
    _, _, _, r = _demo_result()
    post = dataclasses.replace(r.post, platform="moments", title="先看屏幕色准", intro="盯屏幕的时间不短。")
    out = phone_html(dataclasses.replace(r, post=post), None, allow_fetch=False)
    assert "先看屏幕色准" in out and "盯屏幕的时间不短。" in out


# ---------------------------------------------------------------- 生成 tab: the same controls as 门店端
@pytest.fixture()
def manual(monkeypatch):
    from fastapi.testclient import TestClient

    import server
    acct = {"username": "manager-s01", "role": "manager", "store_id": "S01", "store_name": "紫金港店"}
    monkeypatch.setattr(server, "_require", lambda sid, roles=None: acct)
    marks = []
    monkeypatch.setattr("agent.ui_data.mark_published", lambda *a, **k: marks.append(a))
    _, _, _, r = _demo_result()
    sid = "manual-controls-test"
    m = server._manual(server._session(sid))
    m["result"] = r
    return TestClient(server.app), sid, r, marks


def test_manual_result_carries_every_control(manual):
    import server
    client, sid, r, _ = manual
    out = server._manual_render(r, server._manual(server._session(sid)))
    assert out["editable"] and out["publishable"] and out["can_copy"]
    assert out["publish_label"] == "标记为已发布（朋友圈）" and out["final_text"]


def test_manual_check_save_pass_then_revert(manual):
    client, sid, r, _ = manual
    from agent.formatter import render_publishable
    edited = render_publishable(r.post).replace("周末来店里上手试试。", "周末来店里上手试试 DemoBook 14（演示版）。周末店里人少一些。")
    out = client.post("/api/manual/check-save", json={"session_id": sid, "text": edited}).json()
    assert out["edited"] is True and "已修改·已核验" in out["edit_status_html"]
    assert "周末店里人少一些" in out["final_text"] and "周末店里人少一些" in out["pub_text"]
    out = client.post("/api/manual/revert", json={"session_id": sid}).json()
    assert out["edited"] is False and "周末店里人少一些" not in out["pub_text"]


def test_manual_check_save_failure_blocks_copy(manual):
    client, sid, r, _ = manual
    from agent.formatter import render_publishable
    bad = render_publishable(r.post).replace("1.25 kg", "1.2 kg")
    out = client.post("/api/manual/check-save", json={"session_id": sid, "text": bad}).json()
    assert out["can_copy"] is False and "未通过核验" in out["edit_status_html"]


def test_manual_publish_marks_the_store_week(manual):
    client, sid, r, marks = manual
    out = client.post("/api/manual/publish", json={"session_id": sid}).json()
    assert out["published"] is True and out["publish_label"].startswith("已发布 ✓（朋友圈")
    assert marks and marks[0][0] == "S01" and marks[0][1] == "朋友圈"


def test_manual_export_zip_is_a_zip(manual):
    client, sid, r, _ = manual
    resp = client.get(f"/api/manual/export-zip?session_id={sid}")
    assert resp.status_code == 200 and resp.content[:2] == b"PK"


# ---------------------------------------------------------------- 门店端 保存图片: one image or all of them
def test_store_save_image_by_index_and_all_as_zip(monkeypatch):
    import zipfile, io
    from agent.schemas import PostImage
    s, card, key, r = _demo_result()
    imgs = [PostImage(media_id=f"m{i}", position="", caption="") for i in range(3)]
    s["results"][key] = dataclasses.replace(r, post=dataclasses.replace(r.post, images=imgs))
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 16
    monkeypatch.setattr(state, "_post_image_bytes", lambda media_id: png + media_id.encode())
    assert state.render(s)["images"] == 3
    name, data = state.save_image(s, 2)
    assert name.endswith("_3.png") and data.endswith(b"m2")
    name, data = state.save_images(s)
    assert name.endswith(".zip")
    assert sorted(zipfile.ZipFile(io.BytesIO(data)).namelist()) == ["1.png", "2.png", "3.png"]


# ---------------------------------------------------------------- 需人工确认: a person fixes the draft, then it may publish
def _review_session():
    from agent.schemas import FailingSentence, NeedsReview
    s, card, key, r = _demo_result()
    bad = FailingSentence(field="cta", sentence="周末来店里上手试试。", stage="8A", code="unsupported_claim",
                          reason="未引用声明")
    s["results"][key] = NeedsReview(card=card, draft=r, failing=[bad])
    return s, key, r


def test_needs_review_shows_the_draft_for_editing_but_not_for_publishing():
    s, key, r = _review_session()
    out = state.render(s)
    assert out["editable"] is True and out["pub_text"]
    assert out["publishable"] is False and out["can_copy"] is False and out["downloadable"] is False
    assert state.export_zip(s) is None and state.download_text(s) is None


def test_needs_review_save_is_refused_while_the_failing_sentence_remains():
    s, key, r = _review_session()
    from agent.formatter import render_publishable
    kept = render_publishable(r.post).replace("周末来店里上手试试。", "周末来店里上手试试。DemoBook 14（演示版）到店可以试。")
    out = state.on_check_save(kept, s)
    assert out["publishable"] is False and "请改写或删除" in out["edit_status_html"]


def test_needs_review_fixed_by_hand_becomes_publishable():
    s, key, r = _review_session()
    from agent.formatter import render_publishable
    fixed = render_publishable(r.post).replace("周末来店里上手试试。", "DemoBook 14（演示版）到店可以试。")
    out = state.on_check_save(fixed, s)
    assert out["publishable"] is True and out["can_copy"] is True
    assert "已人工处理" in out["status_html"] and "DemoBook 14（演示版）到店可以试" in out["final_text"]
    assert state.download_text(s) is not None


# ---------------------------------------------------------------- 生成 tab: both input modes × every platform
PLATFORMS = ["朋友圈", "小红书", "公众号", "海报", "抖音"]


@pytest.fixture()
def manual_api(monkeypatch):
    import types
    from fastapi.testclient import TestClient

    import server
    from agent import ui_data
    fake = Deps.fake()
    monkeypatch.setattr(server, "DEPS", fake)
    monkeypatch.setattr(server, "_require", lambda sid, roles=None: {"username": "dev", "role": "developer",
                                                                    "store_id": ""})
    monkeypatch.setattr(server, "rate_check", lambda *a, **k: None)
    # the deterministic edit checker has its own tests; here the controls' wiring is what is checked
    monkeypatch.setattr(ui_data, "check_edit", lambda text, r: types.SimpleNamespace(passed=True, post=r.post,
                                                                                    failing=[]))
    return TestClient(server.app), server, fake


def _generate(client, fake, sid, text, fail, monkeypatch):
    import json
    from agent.formatter import strip_fact_tags
    from agent.schemas import CheckIssue, CheckReport
    if fail:   # one red error on a real sentence, as a real run can return
        # stays red even after the trim step removes that sentence (the trimmed post is re-checked too)
        first = lambda post: strip_fact_tags(next((b for b in post.body if b.strip()), post.title or "x")).split("。")[0]  # noqa: E731
        monkeypatch.setattr(fake, "run_checks", lambda post, *a, **k: CheckReport([CheckIssue(
            stage="8A", severity="error", code="x", message="未引用声明", field="body", span=first(post))]))
    lines = client.post("/api/manual/generate", json={"session_id": sid, "text": text}).text.splitlines()
    events = [json.loads(x) for x in lines if x.strip()]
    return [e for e in events if e.get("event") == "done"][-1]["data"]


@pytest.mark.parametrize("mode", ["点选", "直接输入"])
@pytest.mark.parametrize("platform", PLATFORMS)
def test_generate_tab_has_every_control_on_every_platform(manual_api, monkeypatch, mode, platform):
    client, server, fake = manual_api
    text = (f"一位大学生顾客，开学季，想买 DemoBook 14（演示版），发{platform}" if mode == "点选"
            else f"大学生开学买 DemoBook 14（演示版），发{platform}")
    sid = f"ctl-{mode}-{platform}"
    if mode == "直接输入":
        assert client.post("/api/manual/check", json={"session_id": sid, "text": text}).json()["kind"] == "ok"
    d = _generate(client, fake, sid, text, False, monkeypatch)
    assert d["kind"] == "result" and d["editable"] and d["publishable"] and d["can_copy"]
    assert d["publish_label"].startswith("标记为已发布（")


@pytest.mark.parametrize("platform", PLATFORMS)
def test_generate_tab_failed_post_is_fixed_by_hand(manual_api, monkeypatch, platform):
    from agent.formatter import strip_fact_tags
    from agent.pipeline import failing_sentences
    client, server, fake = manual_api
    sid = f"fix-{platform}"
    d = _generate(client, fake, sid, f"一位大学生顾客，开学季，想买 DemoBook 14（演示版），发{platform}", True,
                  monkeypatch)
    # failed: still editable (so it can be fixed), nothing may leave yet
    assert d["editable"] is True and d["publishable"] is False and d["can_copy"] is False
    assert client.get(f"/api/manual/export-zip?session_id={sid}").status_code == 409
    assert client.get(f"/api/manual/download-md?session_id={sid}").status_code == 409
    r = server._manual(server._session(sid))["result"]
    listed = [strip_fact_tags(f.sentence).strip() for f in failing_sentences(r.post, r.report) if f.sentence]
    assert listed
    kept = client.post("/api/manual/check-save", json={"session_id": sid, "text": d["pub_text"] + "\n\n到店可以试。"}).json()
    assert kept["publishable"] is False and "请改写或删除" in kept["edit_status_html"]
    fixed = d["pub_text"]
    for sentence in listed:             # what a person does: delete each sentence the red box lists
        fixed = fixed.replace(sentence, "")
    out = client.post("/api/manual/check-save", json={"session_id": sid, "text": fixed}).json()
    assert out["publishable"] is True and out["can_copy"] is True and "已人工处理" in out["edit_status_html"]
    assert client.post("/api/manual/publish", json={"session_id": sid}).json()["published"] is True
    assert client.get(f"/api/manual/export-zip?session_id={sid}").status_code == 200
    assert client.get(f"/api/manual/download-md?session_id={sid}").status_code == 200


# ---------------------------------------------------------------- 生成 tab: the trim step (same as 门店端 fallback step 1)
def _fails_while_present(sentence_of):
    """A run_checks fake: one red error while the given sentence is still in the post, clean once it is gone."""
    from agent.formatter import strip_fact_tags
    from agent.schemas import CheckIssue, CheckReport

    def check(post, *a, **k):
        target = sentence_of(post)
        text = "".join(strip_fact_tags(b) for b in post.body)
        if target and target in text:
            return CheckReport([CheckIssue(stage="8A", severity="error", code="uncited_claim",
                                           message="未引用声明", field="body", span=target)])
        return CheckReport([])
    return check


@pytest.mark.parametrize("platform", PLATFORMS)
def test_generate_tab_trims_failing_sentences_before_showing_red(manual_api, monkeypatch, platform):
    import json
    from agent.formatter import strip_fact_tags
    client, server, fake = manual_api
    # flag the 2nd body sentence: removing it still leaves a deliverable post (title, a selling point, a CTA)
    seen = {}

    def second(post):
        bodies = [strip_fact_tags(b) for b in post.body if b.strip()]
        seen.setdefault("s", bodies[1] if len(bodies) > 1 else "")
        return seen["s"]
    monkeypatch.setattr(fake, "run_checks", _fails_while_present(second))
    text = f"一位大学生顾客，开学季，想买 DemoBook 14（演示版），发{platform}"
    lines = client.post("/api/manual/generate", json={"session_id": f"trim-{platform}", "text": text}).text.splitlines()
    events = [json.loads(x) for x in lines if x.strip()]
    d = [e for e in events if e.get("event") == "done"][-1]["data"]
    if not seen.get("s"):
        pytest.skip(f"the fake {platform} post has a single body sentence")
    assert d["publishable"] is True and d["can_copy"] is True, platform       # no hand fix needed
    assert "已删去未通过核验的句子" in d["banner_html"] and seen["s"] not in d["pub_text"]
    assert any("删去" in (e.get("message") or "") for e in events if e.get("event") == "progress")


def test_trim_that_still_fails_stays_red_and_editable(manual_api, monkeypatch):
    import json
    from agent.formatter import strip_fact_tags
    from agent.schemas import CheckIssue, CheckReport
    client, server, fake = manual_api
    always = lambda post, *a, **k: CheckReport([CheckIssue(stage="8A", severity="error", code="x", message="m",  # noqa: E731
                                                           field="body", span=strip_fact_tags(post.body[0])[:6])])
    monkeypatch.setattr(fake, "run_checks", always)
    lines = client.post("/api/manual/generate", json={"session_id": "trim-red",
                        "text": "一位大学生顾客，开学季，想买 DemoBook 14（演示版），发小红书"}).text.splitlines()
    d = [json.loads(x) for x in lines if x.strip() and json.loads(x).get("event") == "done"][-1]["data"]
    assert d["editable"] is True and d["publishable"] is False


def test_card_fallback_still_trims_first():
    """apply_fallback now calls the shared _try_trim; it still deletes the failing sentence and re-checks."""
    from agent.pipeline import apply_fallback
    s, card, key, r = _demo_result()
    extra = "这一句会被标红并删去。"
    r = dataclasses.replace(r, post=dataclasses.replace(r.post, body=[*r.post.body, extra]))
    deps = Deps.fake()
    deps.run_checks = _fails_while_present(lambda post: extra.rstrip("。"))
    failed = dataclasses.replace(r, report=deps.run_checks(r.post))
    assert not failed.report.passed
    out = apply_fallback(card, failed, deps)
    assert getattr(out, "fallback", None) == "trimmed" and out.report.passed
    assert extra not in "".join(out.post.body)


def test_trim_explains_why_it_did_not_fix_a_whole_post_error(manual_api, monkeypatch):
    """A whole-post error (no single sentence to delete) cannot be trimmed: the 生成 tab says so."""
    import json
    from agent.schemas import CheckIssue, CheckReport
    client, server, fake = manual_api
    whole = lambda post, *a, **k: CheckReport([CheckIssue(stage="8C", severity="error", code="missing_cta",  # noqa: E731
                                                          message="缺少「到店或咨询引导」")])
    monkeypatch.setattr(fake, "run_checks", whole)
    lines = client.post("/api/manual/generate", json={"session_id": "trim-whole",
                        "text": "一位大学生顾客，开学季，想买 DemoBook 14（演示版），发小红书"}).text.splitlines()
    events = [json.loads(x) for x in lines if x.strip()]
    d = [e for e in events if e.get("event") == "done"][-1]["data"]
    assert d["publishable"] is False and "自动删句未执行" in d["edit_status_html"]
    assert any("自动删句未执行" in (e.get("message") or "") for e in events if e.get("event") == "progress")


# ---------------------------------------------------------------- 门店端: a failed 快速调整 result can be fixed by hand
def _failed_quick_edit():
    from agent.schemas import CheckIssue, CheckReport
    s, card, key, r = _demo_result()
    s["results"][key] = dataclasses.replace(r, report=CheckReport([CheckIssue(
        stage="8A", severity="error", code="uncited_claim", message="未引用声明", field="cta", span="周末来店里上手试试")]))
    return s, key, r


def test_failed_quick_edit_is_editable_but_nothing_leaves():
    s, key, r = _failed_quick_edit()
    out = state.render(s)
    assert out["editable"] is True and out["pub_text"] and "改写或删除" in out["status_html"]
    assert out["publishable"] is False and out["can_copy"] is False and out["downloadable"] is False
    assert out["image_ok"] is False
    assert state.download_text(s) is None and state.export_zip(s) is None and state.save_image(s) is None


def test_failed_quick_edit_save_refused_while_flagged_sentence_remains():
    s, key, r = _failed_quick_edit()
    from agent.formatter import render_publishable
    kept = render_publishable(r.post) + "\n\nDemoBook 14（演示版）到店可以试。"
    out = state.on_check_save(kept, s)
    assert out["publishable"] is False and "请改写或删除" in out["edit_status_html"]


def test_failed_quick_edit_fixed_by_hand_unlocks_every_button():
    """Was a dead end: 检查并保存 silently ignored a failed 快速调整 result."""
    s, key, r = _failed_quick_edit()
    from agent.formatter import render_publishable
    fixed = render_publishable(r.post).replace("周末来店里上手试试。", "DemoBook 14（演示版）到店可以试。")
    out = state.on_check_save(fixed, s)
    assert out["publishable"] is True and out["can_copy"] is True and out["downloadable"] is True
    assert "已人工处理" in out["status_html"] and "DemoBook 14（演示版）到店可以试" in out["final_text"]
    assert state.download_text(s) is not None
    assert state.on_publish(s)["published"] is True
