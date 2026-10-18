"""Result HTML in app.py and static/phone.css (fakes only)."""


def test_boundary_warning_is_a_note_not_pending():
    import app
    from agent.pipeline import Deps, run
    from agent.schemas import CheckIssue, CheckReport
    deps = Deps.fake()
    warn = CheckIssue("8B", "warn", "boundary_violation", "越过知识库表达边界：出现了「全天不用充电」", "body[0]",
                      "全天不用充电")
    deps.run_checks = lambda *a, **k: CheckReport([warn])
    r = run("一位妈妈想给下个月上大学的女儿买 DemoBook 14（演示版），发小红书", deps=deps)
    assert r.pending == []
    html = app.banner_html(r)
    assert "待确认" not in html and "核验提示" in html and "全天不用充电" in html
    assert 'class="hw-banner ok"' in html


def test_light_cards_use_dark_text_in_both_modes():
    import re
    from pathlib import Path
    css = (Path(__file__).resolve().parents[1] / "static" / "phone.css").read_text("utf-8")
    pairs = {".hw-talk": ("#FAEEDA", "#412402"), ".hw-banner.err": ("#FCEBEB", "#791F1F"),
             ".hw-banner.warn": ("#FAEEDA", "#633806"), ".hw-banner.ok": ("#EAF3DE", "#27500A"),
             ".hw-stop": ("#FCEBEB", "#791F1F")}
    rules = [([x.strip() for x in sels.split(",")], decl)
             for sels, decl in re.findall(r"([^{}]+)\{([^}]*)\}", re.sub(r"/\*.*?\*/", "", css, flags=re.S))]

    def decl_for(selector):
        return " ".join(d for sels, d in rules if selector in sels)
    for sel, (bg, fg) in pairs.items():
        assert f"background: {bg} !important" in decl_for(sel), sel
        assert f"color: {fg} !important" in decl_for(sel), sel
        # every descendant pinned, so the dark theme's h4/li/b colours cannot override it
        assert f"color: {fg} !important" in decl_for(f"{sel} *"), sel
