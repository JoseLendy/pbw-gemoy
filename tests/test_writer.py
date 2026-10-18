from agent.schemas import CheckIssue
from agent.writer import rewrite, write_post
from tests.fakes import FakeLLM, fake_ledger, fake_plan, fake_post, fake_strategy, fake_task


def _draft(plan):
    first = plan.items[0]
    return {
        "title": "开学装备清单", "intro": "每天背着电脑跑教室。",
        "body": ["重量约 1.25 kg [F1]，放进双肩包不占地方。", "文件拖拽很顺手 [F99]。"],
        "cta": "来店里掂一掂。", "tags": ["开学季"], "selling_points": ["F1", "F99"],
        "images": [
            {"media_id": first.image.media_id, "position": "标题下方", "caption": first.caption},
            {"media_id": "not-in-plan", "position": "文末", "caption": "x"},
        ],
    }


def test_write_post_cleans_images_and_unknown_tags():
    plan = fake_plan()
    llm = FakeLLM({"writer": _draft(plan)})
    post = write_post(fake_task(), fake_strategy(), fake_ledger(), plan, llm)
    assert [i.media_id for i in post.images] == [plan.items[0].image.media_id]
    assert "[F99]" not in post.all_text()
    assert "F99" not in post.selling_points
    assert "F1" in post.selling_points
    assert post.platform == "xiaohongshu"


def test_tags_always_filled():
    plan = fake_plan()
    d = _draft(plan)
    d["tags"] = []
    post = write_post(fake_task(), fake_strategy(), fake_ledger(), plan, FakeLLM({"writer": d}))
    assert post.tags


def test_rewrite_changes_only_failing_fields():
    plan = fake_plan()
    before = fake_post("xiaohongshu")
    issues = [CheckIssue("8B", "error", "banned_word", "含绝对化用语", field="title", span="最轻")]
    llm = FakeLLM({"rewrite": {
        "title": "背得动的笔记本",
        "body": ["不该被改动 [F1]"],          # not a failing field: must be ignored
        "intro": "不该被改动",
    }})
    after = rewrite(before, issues, fake_task(), fake_strategy(), fake_ledger(), plan, llm)
    assert after.title == "背得动的笔记本"
    assert after.intro == before.intro
    assert after.body == before.body
    assert after.cta == before.cta
    assert after.images == before.images


def test_rewrite_cannot_add_new_facts():
    plan = fake_plan()
    before = fake_post("xiaohongshu")
    issues = [CheckIssue("8A", "error", "unsupported_number", "数字无依据", field="body[0]")]
    llm = FakeLLM({"rewrite": {"body": ["亮度 500 nits [F5]，还有 [F99]。"]}})
    after = rewrite(before, issues, fake_task(), fake_strategy(), fake_ledger(), plan, llm)
    text = after.all_text()
    assert "[F99]" not in text
    assert "[F5]" not in text          # F5 was never chosen or cited: not allowed to appear in a rewrite


def test_stray_absolute_word_triggers_one_self_repair():
    plan = fake_plan()
    d = _draft(plan)
    d["intro"] = "肩膀最先吃不消。"
    llm = FakeLLM({"writer": d, "rewrite": {"intro": "肩膀先吃不消。"}})
    post = write_post(fake_task(), fake_strategy(), fake_ledger(), plan, llm)
    assert "最" not in post.all_text()
    assert post.title == "开学装备清单"
