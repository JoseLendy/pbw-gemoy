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


class _PromptLLM(FakeLLM):
    def chat_json(self, system, user, stage="", **kw):
        self.full = (system, user)
        return super().chat_json(system, user, stage, **kw)


def test_rewrite_prompt_lists_exactly_the_ids_it_may_cite():
    """The rewrite may only cite already-cited or chosen facts; the prompt must say so explicitly, or the
    model tags a background fact, the tag is stripped and the sentence fails 8A again."""
    plan = fake_plan()
    before = fake_post("xiaohongshu")
    issues = [CheckIssue("8A", "error", "untagged_claim", "缺编号", field="body[0]")]
    llm = _PromptLLM({"rewrite": {}})
    rewrite(before, issues, fake_task(), fake_strategy(), fake_ledger(), plan, llm)
    system, user = llm.full
    section = user.split("## 本轮可用的事实编号")[1].split("## 需要修改的字段")[0]
    allowed = set(before.selling_points) | {sp.fact_id for sp in fake_strategy().selling_points}
    listed = {line.split(" | ")[0] for line in section.strip().splitlines()[1:]}
    assert listed == allowed and "F5" not in listed
    assert "整句删除" in system


def test_writer_is_shown_the_model_wide_boundaries_the_8b_judge_enforces():
    """Real 朋友圈 runs S11 2026-10-23: the 8B judge blocked a keyboard sentence citing the model-wide ("other")
    boundary that keyboard backlight must be bound to a SKU. The judge sees "other" lines
    (checks.compliance.relevant_boundaries) but the writer only got the chosen facts' categories, so it was
    never told."""
    from agent.checks.compliance import relevant_boundaries
    from agent.writer import _context
    ledger = fake_ledger()
    ledger.boundaries = [
        {"category": "other", "text": "演示边界：键盘背光必须绑定具体版本。", "source_title": "卖点与限制.md"},
        {"category": "display", "text": "演示边界：屏幕亮度为典型值。", "source_title": "产品事实.md"},
    ]
    ctx = _context(fake_task(), fake_strategy(), ledger, fake_plan())   # chosen: portability, battery, collab
    bounds = ctx.split("## 表达边界")[1].split("##")[0]
    assert "键盘背光必须绑定具体版本" in bounds
    assert "屏幕亮度为典型值" not in bounds           # an unrelated category is still left out
    assert "演示边界：键盘背光必须绑定具体版本。" in relevant_boundaries(fake_post(), ledger)


def test_writer_prompt_keeps_angle_as_direction_only():
    """Real 朋友圈 run S04 potential 2026-10-23: the strategy angle claimed company data is not seen at boot; the
    writer carried it into a privacy-screen effect no fact supports, and 8B rightly flagged it."""
    from agent.llm import load_prompt
    w = load_prompt("writer")
    assert "切入点只给方向" in w and "事实清单没有写的效果或结论" in w


# ------------------------------------------------------------------ conditioned facts (2026-10-23: 超级终端 versions, HDMI qualifier)
def test_writer_prompt_requires_stating_a_facts_condition_or_choosing_another_point():
    from agent.llm import load_prompt
    rules = load_prompt("writer")
    assert "条件" in rules and "换一个卖点" in rules and "变体" in rules
    # real 2026-10-23 S06: a KB condition was copied with an absolute word and failed 8B banned_word
    condition_rule = next(line for line in rules.splitlines() if "换一个卖点" in line)
    assert "写条件时同样不用" in condition_rule and "写成“以官网为准”" in condition_rule


def test_writer_fact_line_shows_the_variant_and_qualifier():
    import copy
    from agent.writer import _fact_line
    f = copy.deepcopy(fake_ledger().facts[0])
    f.variant, f.qualifier = "Windows 版", "以官网为准"
    line = _fact_line(f)
    assert "变体=Windows 版" in line and "限定=以官网为准" in line
