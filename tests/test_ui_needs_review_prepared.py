"""A prepared post that ended in NeedsReview must not look like a ready post (Playwright check, 2026-10-23:
S06/S07 showed the red 需人工确认 panel under a 「今日已为你准备好」 header, with the draft in the phone preview)."""
from __future__ import annotations

from agent.recommend.store_data import cards_for, reload
from ui import store_tab
from ui.components import prepared_post_html

DAY = "2026-10-23"


def _review_payload():
    return {"kind": "prepared", "status": "NeedsReview", "store_id": "S06",
            "result": {"draft": {"post": {"platform": "moments", "title": "标题", "intro": "", "body": ["草稿正文。"],
                                          "cta": "", "tags": [], "selling_points": [], "images": []}},
                       "failing": [{"field": "body[0]", "sentence": "草稿正文。", "stage": "8B", "code": "x",
                                    "reason": "原因"}],
                       "message": "需人工确认：自动核验未通过，已列出未通过的句子和原因"}}


def test_needs_review_prepared_card_header_says_needs_review():
    reload()
    card = cards_for("S06", DAY)[0]
    head = store_tab._card_panel_html(card, True, review=True)
    assert "需人工确认" in head and "今日已为你准备好" not in head


def test_passing_prepared_card_header_is_unchanged():
    reload()
    card = cards_for("S06", DAY)[0]
    assert "今日已为你准备好" in store_tab._card_panel_html(card, True)


def test_needs_review_draft_is_labelled_as_an_unpublished_draft():
    out = prepared_post_html(_review_payload())
    banner = out.split('<div class="hw-banner err">')[1].split("</div>")[0]
    assert "未发布草稿" in banner
