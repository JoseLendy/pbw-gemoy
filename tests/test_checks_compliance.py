"""8B compliance checks (agent/checks/compliance.py)."""
from __future__ import annotations

import pytest

from agent.checks.compliance import boundary_phrases, check_compliance
from agent.checks import load_lines
from tests.fakes import FakeLLM, fake_ledger, fake_plan, fake_post, fake_task

SIB = {"demobook-14-se": fake_ledger("demobook-14-se")}


def issues(post, task=None, ledger=None, llm=None):
    return check_compliance(post, ledger or fake_ledger(), task or fake_task(post.platform), llm=llm)


def codes(report, severity=None):
    return {i.code for i in report.issues if severity is None or i.severity == severity}


def with_text(text, field="cta", platform="xiaohongshu"):
    p = fake_post(platform)
    if field == "cta":
        p.cta = text
    elif field == "title":
        p.title = text
    else:
        p.body[0] = text
    return p


# ------------------------------------------------------------------ happy path
@pytest.mark.parametrize("platform", ["xiaohongshu", "wechat_article", "moments"])
def test_fake_post_is_compliant(platform):
    assert codes(issues(fake_post(platform)), "error") == set()


# ------------------------------------------------------------------ banned words
@pytest.mark.parametrize("text", [
    "最高支持 120 Hz [F4]", "最强的轻薄本", "第一选择", "全网都在买", "100% 满意",
    "绝对是你要的", "史上最轻", "永久耐用", "顶级做工", "首选轻薄本", "遥遥领先",
    "国家级认证", "唯一选择", "万能办公本", "极致手感", "王牌配置", "销量冠军",
])
def test_every_absolute_is_an_error(text):
    r = issues(with_text(text))
    assert "banned_word" in codes(r, "error"), text


def test_every_zui_has_no_allow_rule():
    p = fake_post()
    p.body = ["重量最轻 [F1]", "续航最长 [F7]", "多屏协同最好用 [F11]"]
    r = issues(p)
    zui = [i for i in r.issues if i.code == "banned_word"]
    assert len(zui) == 3


def test_upper_bound_rephrase_is_suggested():
    r = issues(with_text("续航最高可达 14 小时"))
    msg = next(i.message for i in r.issues if i.code == "banned_word")
    assert "可达 14 小时" in msg and "最" in msg


def test_zui_has_no_exceptions_even_inside_ordinary_words():
    # The handbook bans absolute claims with no exceptions, so 最后/最近 are flagged too.
    for text in ("最后提醒一句，到店看看", "最近想换电脑"):
        assert "banned_word" in codes(issues(with_text(text)), "error"), text


# ------------------------------------------------------------------ competitors
@pytest.mark.parametrize("text", ["比 MacBook 轻", "苹果用户也适合", "联想同价位", "Dell 的接口少",
                                  "惠普", "华硕", "小米", "荣耀", "微软 Surface", "ASUS"])
def test_competitor_mentions(text):
    assert "competitor" in codes(issues(with_text(text)), "error"), text


def test_word_bounded_competitor_terms():
    # must not fire inside unrelated words
    assert "competitor" not in codes(issues(with_text("到店体验一下 app 里的预约功能")))


# ------------------------------------------------------------------ task requests
@pytest.mark.parametrize("req", ["加上500元补贴", "写上三年上门质保", "说它热销", "加上以旧换新", "标一个学生优惠价"])
def test_unsupported_task_request_is_pending(req):
    t = fake_task()
    t.extra_requirements = [req]
    r = issues(fake_post(), task=t)
    pend = [i for i in r.issues if i.code == "pending_request"]
    assert pend and pend[0].severity == "warn"
    assert pend[0].message == f"{req}：知识库中未提供，需人工确认后补充"


def test_harmless_request_is_not_pending():
    t = fake_task()
    t.extra_requirements = ["标题更活泼一点"]
    assert "pending_request" not in codes(issues(fake_post(), task=t))


def test_request_supported_by_ledger_is_not_pending():
    ledger = fake_ledger()
    f0 = ledger.facts[0]
    ledger.facts[0] = f0.__class__(**{**f0.__dict__, "value": "约 1.25 kg（赠双肩包）"})
    t = fake_task()
    t.extra_requirements = ["提一下赠双肩包"]
    assert "pending_request" not in codes(issues(fake_post(), task=t, ledger=ledger))


# ------------------------------------------------------------------ xhs fake experience
@pytest.mark.parametrize("text", ["亲测很轻", "我用了两周", "入手三个月，聊聊感受", "自用分享", "真实体验"])
def test_xhs_fake_experience(text):
    assert "fake_experience" in codes(issues(with_text(text, field="body")), "error")


def test_fake_experience_only_on_xhs():
    p = with_text("自用分享：重量约 1.25 kg [F1]", field="body", platform="wechat_article")
    assert "fake_experience" not in codes(issues(p))


# ------------------------------------------------------------------ boundaries
def test_boundary_phrase_warns():
    ledger = fake_ledger()
    ledger.boundaries = [{"category": "battery", "text": "续航为实验室数据，不得承诺“全天不用充电”。",
                          "source_title": "卖点与限制.md"}]
    assert "boundary_violation" not in codes(issues(fake_post(), ledger=ledger))
    p = fake_post()
    p.body[1] = "续航可达约 14 小时 [F7]，全天不用充电。"
    r = issues(p, ledger=ledger)
    hit = [i for i in r.issues if i.code == "boundary_violation"]
    assert len(hit) == 1 and hit[0].severity == "warn" and hit[0].span == "全天不用充电"
    assert "待确认" not in hit[0].message


@pytest.mark.parametrize("text,phrases", [
    ("表达边界：不要写成支持所有显示器。", ["支持所有显示器"]),
    ("表达边界：不要写成\"最轻\"，不要与其他品牌比较重量。", ["最轻"]),
    ("不要写：\"全网最轻的笔记本。\"", ["全网最轻的笔记本"]),
    ("避免使用“秒开”这类说法", ["秒开"]),
    ("圆角屏按标准矩形测量，14.2 英寸为标准矩形对角线长度。", []),
    ("USB-C 接口支持充电与数据传输，HDMI 接口最高支持 4K 输出。", []),
])
def test_boundary_phrases_only_from_forbid_lines(text, phrases):
    assert boundary_phrases(text) == phrases


def test_correct_post_has_no_boundary_noise():
    """Boundary lines that merely mention 14.2 英寸 / USB-C / HDMI must not flag a post that uses those terms."""
    ledger = fake_ledger()
    ledger.boundaries = [
        {"category": "display", "text": "圆角屏按标准矩形测量，14.2 英寸为标准矩形对角线长度，实际可视区域略小。",
         "source_title": "产品事实.md"},
        {"category": "ports", "text": "USB-C 接口支持充电与数据传输，HDMI 接口外接显示器时以实际设备为准。",
         "source_title": "产品事实.md"},
        {"category": "ports", "text": "表达边界：不要写成支持所有显示器。", "source_title": "卖点与限制.md"},
    ]
    p = fake_post()
    p.body = ["14.2 英寸屏幕 [F3]，看课件更舒服。",
              "2 个 USB-C 接口 [F10]，外接 HDMI 扩展坞也方便。"]
    assert [i for i in issues(p, ledger=ledger).issues if i.code == "boundary_violation"] == []


def test_boundaries_reach_8b_llm_prompt():
    ledger = fake_ledger()
    ledger.boundaries = [{"category": "portability", "text": "不要写成“最轻”", "source_title": "卖点与限制.md"},
                         {"category": "security", "text": "不得承诺数据绝对安全", "source_title": "卖点与限制.md"}]
    seen = {}

    class Spy:
        def chat_json(self, system, user, stage="", **kw):
            seen[stage] = (system, user)
            return {"issues": []}
    check_compliance(fake_post(), ledger, fake_task(), llm=Spy())
    system, user = seen["8B"]
    assert "<boundaries>" in user and "不要写成“最轻”" in user       # F1 is portability -> relevant
    assert "数据绝对安全" not in user                                   # no cited security fact
    assert "表达边界" in system


# ------------------------------------------------------------------ LLM layer
def test_llm_false_promise():
    llm = FakeLLM({"8B": {"issues": [{"field": "cta", "quote": "保证", "code": "false_promise", "message": "虚假承诺"}]}})
    assert "false_promise" in codes(issues(fake_post(), llm=llm), "error")


def test_llm_failure_is_skipped_not_fatal():
    class Boom:
        def chat_json(self, *a, **k):
            raise TimeoutError("x")
    r = issues(fake_post(), llm=Boom())
    assert codes(r, "error") == set() and "llm_check_skipped" in codes(r, "warn")


# ------------------------------------------------------------------ config sanity
def test_config_files_loaded_from_repo():
    assert "最" in load_lines("banned_words.txt")
    assert "MacBook" in load_lines("competitors.txt")
    assert not any(w.startswith("#") or not w for w in load_lines("banned_words.txt"))


def test_run_all_merges_all_stages():
    from agent.checks import run_all
    p = fake_post()
    p.body[0] = "赋能学习，重量约 1.38 kg [F1] 最轻 —— 到店立减500元"
    r = run_all(p, fake_ledger(), SIB, fake_task(), fake_plan())
    assert {"8A", "8B", "8C"} <= {i.stage for i in r.issues}
    assert not r.passed


# ------------------------------------------------------------------ Phase 5 eval: store context (false-positive proof)
def _card_task():
    from agent.recommend.store_data import cards_for
    from agent.recommend.to_task import card_to_task
    return card_to_task(next(c for c in cards_for("S09", "2026-10-23") if c.slot == "promo"))


def _8b_prompt(task):
    seen = {}

    class Spy:
        def chat_json(self, system, user, stage="", **kw):
            seen[stage] = (system, user)
            return {"issues": []}
    p = fake_post("moments")
    p.body = [f"我店在{task.landmark}附近，过来坐坐。"]
    check_compliance(p, fake_ledger(), task, llm=Spy())
    return seen["8B"]


def test_8b_judge_is_told_the_cards_store_context():
    """Real 朋友圈 eval S09: the brief told the writer to name the store's landmark; the 8B judge, never shown that context, called '我店在良渚文化村附近…' an invented personal
    experience. The judge must see the store data the card supplied."""
    task = _card_task()
    assert task.landmark
    system, user = _8b_prompt(task)
    assert "<store>" in user and task.landmark in user.split("<store>")[1] and "署名" not in user
    assert "不算编造" in system and "顾客" in system          # still: no invented customer experience


def test_manual_flow_8b_prompt_has_no_store_block():
    _, user = _8b_prompt(fake_task("moments"))
    assert "<store>" not in user


def test_8b_judge_is_told_the_cards_logged_customer_question():
    """Real 朋友圈 eval run 4, S09 customer_question card: '这几天有家长来问：学生用够不够' quotes the store's
    logged question (4 times in 7 days) exactly as the brief asks, but the 8B judge, never shown the log,
    called it an invented customer experience."""
    from agent.recommend.store_data import cards_for
    from agent.recommend.to_task import card_to_task
    task = card_to_task(next(c for c in cards_for("S09", "2026-10-23") if c.slot == "customer_question"))
    system, user = _8b_prompt(task)
    store = user.split("<store>")[1].split("</store>")[0]
    assert task.question["text"] in store and str(task.question["count"]) in store
    assert "记录过的顾客问题" in system


def test_no_logged_question_means_none_is_shown_to_the_judge():
    _, user = _8b_prompt(_card_task())            # S09 promo card: no logged question
    assert "顾客问题" not in user.split("<store>")[1].split("</store>")[0]


# ------------------------------------------------------------------ canary: price record shown to the judges (false-positive proof)
def _judge_prompts(task, sentence):
    """The 8A and 8B judge prompts run_all builds for one post (fake ledger, spy LLM)."""
    from agent.checks import run_all
    from tests.fakes import fake_plan
    seen = {}

    class Spy:
        def chat_json(self, system, user, stage="", **kw):
            seen[stage] = (system, user)
            return {"issues": []}
    p = fake_post("moments")
    p.body = [sentence]
    run_all(p, fake_ledger(), SIB, task, fake_plan(), llm=Spy())
    return seen


def _s02_promo_task():
    from agent.recommend.store_data import cards_for
    from agent.recommend.to_task import card_to_task
    return card_to_task(next(c for c in cards_for("S02", "2026-10-23") if c.slot == "promo"))


def test_8a_and_8b_judges_are_shown_the_active_price_record():
    """Real canary clean draft 3: '演示活动价 4999 元 [演示活动]，活动期内有效，以门店实际为准。' matches the active
    HQ record exactly (8B's code-level price check passes it), yet the 8A judge called it uncited_claim and the
    8B judge false_promise: neither prompt contained the record."""
    from agent.checks.prices import valid_price_record
    task = _s02_promo_task()
    rec = valid_price_record(task)
    assert rec is not None
    seen = _judge_prompts(task, f"{rec['label']} {rec['value']} 元 [演示活动]，{rec['conditions']}。")
    for stage in ("8A", "8B"):
        promo = seen[stage][1].split("<promo>")[1].split("</promo>")[0]
        assert rec["value"] in promo and rec["conditions"] in promo and rec["label"] in promo


def test_no_price_record_means_no_promo_block_for_either_judge():
    from agent.recommend.store_data import cards_for
    from agent.recommend.to_task import card_to_task
    task = card_to_task(next(c for c in cards_for("S01", "2026-10-23") if c.slot == "potential"))
    seen = _judge_prompts(task, "演示活动价 4999 元。")
    assert all("<promo>" not in seen[s][1] for s in ("8A", "8B"))
    seen = _judge_prompts(fake_task("moments"), "演示活动价 4999 元。")
    assert all("<promo>" not in seen[s][1] for s in ("8A", "8B"))


def test_a_wrong_price_on_a_promo_card_is_still_blocked_in_code():
    """Showing the record to the judges must not loosen the code-level price rule."""
    from agent.checks.prices import check_prices
    p = fake_post("moments")
    p.body = ["演示活动价 3999 元，活动期内有效，以门店实际为准。"]
    assert "price_mismatch" in {i.code for i in check_prices(p, _s02_promo_task())}


# ------------------------------------------------------------------ 2026-10-23: card brief shown to the 8B judge (false-positive proof)
def _scene_card_task():
    """A card whose writer brief asks for a scene opening in the store manager's voice."""
    from agent.recommend.store_data import cards_for
    from agent.recommend.to_task import card_to_task
    for store in ("S04", "S06", "S01", "S02", "S03", "S05", "S07", "S08", "S09", "S10", "S11", "S12"):
        for c in cards_for(store, "2026-10-23"):
            t = card_to_task(c)
            if t.hook == "scene" and t.voice == "manager":
                return t
    raise AssertionError("no scene/manager card on 2026-10-23")


def test_8b_judge_is_told_the_cards_opening_and_voice():
    """Real 朋友圈 run S04 promo 2026-10-23: the brief told the writer to open with a concrete scene (time, place,
    what the reader is doing) written as the READER's scene, and to say when a parameter matters. The draft did
    exactly that (a second-person meeting/travel scene, then where the battery figure matters); the 8B judge,
    never shown the brief, called it an invented personal experience."""
    from agent.style.profile import HOOK_OPENING, VOICE_TONE
    task = _scene_card_task()
    system, user = _8b_prompt(task)
    brief = user.split("<brief>")[1].split("</brief>")[0]
    assert HOOK_OPENING["scene"] in brief and VOICE_TONE["manager"] in brief
    assert "<brief>" in system and "不算编造经历" in system


def test_brief_note_keeps_invented_experience_and_promises_in_scope():
    """Guard: the note only covers reader-side scenes; author / staff / other-customer experience and outcomes
    or service promises not in the facts stay problems, and every original category is still asked for."""
    system, _ = _8b_prompt(_scene_card_task())
    for must in ("虚假承诺", "无依据的比较", "误导性价格", "贬低其他品牌", "编造个人使用经历", "表达边界",
                 "作者、店员或其他顾客的亲身经历", "体验结果", "服务承诺", "仍然是问题"):
        assert must in system, must


def test_manual_flow_8b_prompt_has_no_brief_block():
    system, user = _8b_prompt(fake_task("moments"))
    assert "<brief>" not in user and "<brief>" not in system


def test_judge_flag_on_a_card_run_is_still_an_error():
    """Guard: a first-person invented experience the judge flags on a card run still blocks (no filtering)."""
    task = _scene_card_task()
    p = fake_post("moments")
    p.body = ["我自己背着它跑了一周会议室，电量一整天都够用 [F6]。"]
    llm = FakeLLM({"8B": {"issues": [{"field": "body[0]", "quote": p.body[0], "code": "false_promise",
                                      "message": "编造店员亲身使用经历，并承诺续航结果"}]}})
    r = check_compliance(p, fake_ledger(), task, llm=llm)
    assert "false_promise" in codes(r, "error")


# ------------------------------------------------------------------ 2026-10-23: '客户资料' is not a customer quote
def test_customer_data_noun_is_not_a_customer_quote():
    """Real 朋友圈 run S04 potential 2026-10-23: a sentence saying the reader's work files and 客户资料 are on the
    laptop was blocked as invented_customer_quote because 客户 … 都在 matched."""
    task = _card_task()                     # card run, no logged question
    assert not task.question
    p = fake_post("moments")
    p.body = ["工作文件、客户资料都在电脑里，开机这一步值得先看。"]
    assert "invented_customer_quote" not in codes(check_compliance(p, fake_ledger(), task))


@pytest.mark.parametrize("text", ["很多客户都在问续航", "客户说这台很轻", "顾客反馈键盘好用", "客户资料之外，客户都在问重量",
                                  "客户信息里大家都在问续航", "客户名单上的老客都说这台轻", "顾客数据显示都推荐这台"])
def test_real_customer_references_are_still_blocked(text):
    task = _card_task()
    p = fake_post("moments")
    p.body = [text]
    assert "invented_customer_quote" in codes(check_compliance(p, fake_ledger(), task), "error"), text


# ------------------------------------------------------------------ a qualifier the KB says must not be dropped
def _ledger_with_keep_rule():
    import copy
    led = copy.deepcopy(fake_ledger())
    led.boundaries = list(led.boundaries or []) + [
        {"category": "ports", "text": "DemoPort 标注为 DemoPort 9 XYZ，不应省略 XYZ 限定。", "source_title": "卖点与限制.md"}]
    return led


def test_hdmi_without_the_required_qualifier_fails_in_code():
    """Real 2026-10-23 S10 (after the writer rule): a port was named without the qualifier the KB says must never be
    dropped; the LLM judge let it through, so the KB's explicit rule is checked in code."""
    p = fake_post("moments")
    p.body = ["接口保留了 DemoPort 和两个 USB-A [F1]。"]
    issues = check_compliance(p, _ledger_with_keep_rule(), fake_task("moments")).issues
    assert any(i.code == "qualifier_omitted" and i.severity == "error" for i in issues)


def test_hdmi_with_its_qualifier_or_not_mentioned_passes():
    for body in ("接口有 DemoPort 9 XYZ [F1]。", "接口有两个 USB-A [F1]。"):
        p = fake_post("moments")
        p.body = [body]
        assert not [i for i in check_compliance(p, _ledger_with_keep_rule(), fake_task("moments")).issues
                    if i.code == "qualifier_omitted"]


def test_keep_qualifier_rule_ignores_kb_captions_and_tags():
    """Review: a KB image caption is copied verbatim and a tag is not a claim; neither can be rewritten."""
    p = fake_post("moments")
    p.body = ["接口有两个 USB-A [F1]。"]
    p.tags = ["DemoPort"]
    if p.images:
        p.images[0].caption = "DemoPort 接口特写"
    assert not [i for i in check_compliance(p, _ledger_with_keep_rule(), fake_task("moments")).issues
                if i.code == "qualifier_omitted"]


@pytest.mark.parametrize("rule", ["左侧 DemoPort 9 标注为 DemoPort 9 XYZ，不应省略 XYZ 限定。",
                                  "演示屏幕亮度标注为 500 尼特典型值，不应省略典型值限定。"])
def test_keep_qualifier_rule_never_fires_on_a_misparsed_term(rule):
    import copy
    led = copy.deepcopy(fake_ledger())
    led.boundaries = [{"category": "ports", "text": rule, "source_title": "卖点与限制.md"}]
    p = fake_post("moments")
    p.body = ["版本 9 和 2.1 都有，屏幕亮度也不错 [F1]。"]
    assert not [i for i in check_compliance(p, led, fake_task("moments")).issues if i.code == "qualifier_omitted"]
