"""8B compliance checks (agent/checks/compliance.py)."""
from __future__ import annotations

import pytest

from agent.checks.compliance import check_compliance
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
def test_boundary_hint_warns():
    ledger = fake_ledger()
    ledger.boundaries = [{"category": "续航", "text": "不要承诺全天续航", "source_title": "卖点与限制.md"}]
    r = issues(fake_post(), ledger=ledger)
    assert "boundary_violation" not in codes(r)
    p = fake_post()
    p.body[0] = "不要承诺全天续航之外的话，重量约 1.25 kg [F1]"   # token overlap -> warn
    assert "boundary_violation" in codes(issues(p, ledger=ledger), "warn")


# ------------------------------------------------------------------ LLM layer
def test_llm_false_promise():
    llm = FakeLLM({"8B": {"issues": [{"field": "cta", "quote": "保证", "code": "false_promise", "message": "虚假承诺"}]}})
    assert "false_promise" in codes(issues(fake_post(), llm=llm), "warn")


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


def test_run_all_runs_8a_and_8b_llm_layers_concurrently():
    import threading

    from agent.checks import run_all

    barrier = threading.Barrier(2, timeout=5)

    class BarrierLLM:
        """Each LLM call waits for the other: only passes if 8A and 8B are in flight together."""

        def chat_json(self, system, user, stage="", **kw):
            barrier.wait()
            return {}

    p = fake_post()
    p.body[0] = "赋能学习，重量约 1.38 kg [F1] 最轻 —— 到店立减500元"
    r = run_all(p, fake_ledger(), SIB, fake_task(), fake_plan(), llm=BarrierLLM())
    assert "llm_check_skipped" not in codes(r)
    stages = [i.stage for i in r.issues]
    assert stages == sorted(stages), "merged order must stay 8A, 8B, 8C"
