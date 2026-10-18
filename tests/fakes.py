"""
SHARED FAKES. Every workstream can run end to end WITHOUT ima and WITHOUT an LLM.

- Synthetic data only (DemoBook 14 + its sibling DemoBook 14 SE). Never put KB text here.
- Owner: the integrator. Add new fakes via the lead.

Usage:
    from tests.fakes import FakeCatalog, fake_bundle, fake_ledger, fake_strategy, fake_plan, fake_post, FakeLLM
"""
from __future__ import annotations

import json
from pathlib import Path

from agent.schemas import (
    CheckReport, Fact, ImagePlan, ImageRef, Ledger, Model, ModelBundle, PlannedImage, Post,
    PostImage, ResolveResult, ScenarioAnalysis, SellingPoint, SourceRecord, Strategy, Task,
    PLATFORM_IMAGE_RANGE,
)

FIX = Path(__file__).parent / "fixtures"
TS = "2026-10-18T00:00:00+08:00"

DEMO = Model(
    model_id="demobook-14", canonical_name="DemoBook 14（演示版）", folder_name="DemoBook 14",
    route="harmonyos", aliases=["DemoBook 14", "演示本 14"], siblings=["demobook-14-se"],
)
DEMO_SE = Model(
    model_id="demobook-14-se", canonical_name="DemoBook 14 SE（演示版）", folder_name="DemoBook 14 SE",
    route="windows", aliases=["DemoBook 14 SE"], siblings=["demobook-14"],
)
DEMO_TEXT_ONLY = Model(
    model_id="demo-desk-pro", canonical_name="Demo 商用台式机 Pro", folder_name="Demo 商用台式机 Pro",
    route="text_only", has_images=False,
)
MODELS = {m.model_id: m for m in (DEMO, DEMO_SE, DEMO_TEXT_ONLY)}


def _src(model: Model, name: str) -> SourceRecord:
    return SourceRecord(title=name, source_path=f"P1-产品参数库/01-鸿蒙电脑/{model.folder_name}/{name}",
                        media_id=f"fake-{model.model_id}-{name}", media_type=7, fetched_at=TS)


def _images(model: Model, n: int) -> list[ImageRef]:
    roles = ["main", "scene", "detail", "color", "scene", "detail"]
    return [ImageRef(media_id=f"fake-img-{model.model_id}-{i:02d}",
                     title=f"hwpc_{model.model_id}_示例图_{i:02d}.png",
                     source_path=f"P1-产品参数库/01-鸿蒙电脑/{model.folder_name}/images",
                     model_id=model.model_id, caption=f"{model.canonical_name} 示例图 {i}",
                     role=roles[(i - 1) % len(roles)]) for i in range(1, n + 1)]


class FakeCatalog:
    """Same interface as agent.catalog.Catalog. Pass `models` to override a model (e.g. add needs_human)."""

    models = MODELS  # class-level default (other workstreams read FakeCatalog.models)

    def __init__(self, models: dict[str, Model] | None = None):
        self.models = dict(models) if models else dict(MODELS)

    def resolve(self, query: str) -> ResolveResult:
        q = (query or "").replace(" ", "").lower()
        demo, se = self.models["demobook-14"], self.models["demobook-14-se"]
        if q in ("demobook14se", "demobook14se（演示版）", "demobook14se演示版"):
            return ResolveResult("resolved", model=se)
        if q in ("demobook14（演示版）", "demobook14演示版", "演示本14"):
            return ResolveResult("resolved", model=demo)
        if q in ("demobook14", "demobook"):
            return ResolveResult("ambiguous", candidates=[demo, se], reason="名称同时匹配 2 个型号")
        if "商用台式机" in q:
            return ResolveResult("text_only", model=self.models["demo-desk-pro"])
        return ResolveResult("not_found", candidates=[demo, se], reason="知识库中未找到该型号")

    def get(self, model_id: str) -> Model:
        return self.models[model_id]

    def siblings(self, model_id: str) -> list[Model]:
        return [self.models[s] for s in self.models[model_id].siblings if s in self.models]


def fake_bundle(model_id: str = "demobook-14", n_images: int = 6) -> ModelBundle:
    m = MODELS[model_id]
    folder = FIX / model_id
    facts = (folder / "产品事实.md").read_text("utf-8") if folder.exists() else ""
    claims = (folder / "卖点与限制.md").read_text("utf-8") if folder.exists() else ""
    fs, cs = _src(m, "产品事实.md"), _src(m, "卖点与限制.md")
    imgs = _images(m, n_images) if m.has_images else []
    return ModelBundle(model=m, facts_text=facts, claims_text=claims, images=imgs, sources=[fs, cs],
                       facts_source=fs, claims_source=cs)


def _f(i, model_id, attribute, category, value, quote, unit="", norm_value=None, norm_unit="",
       qualifier="", variant="all", kind="spec", upper=False, src="产品事实.md"):
    m = MODELS[model_id]
    return Fact(id=f"F{i}", model_id=model_id, attribute=attribute, category=category, value=value,
                quote=quote, source_title=src,
                source_path=f"P1-产品参数库/01-鸿蒙电脑/{m.folder_name}/{src}", kind=kind,
                variant=variant, unit=unit, norm_value=norm_value, norm_unit=norm_unit,
                qualifier=qualifier, upper_bound=upper)


def fake_ledger(model_id: str = "demobook-14") -> Ledger:
    """A correct ledger for the fixtures (what ledger.build_ledger should roughly produce)."""
    if model_id == "demobook-14":
        facts = [
            _f(1, model_id, "weight", "portability", "约 1.25 kg（标准版含电池）", "约 1.25 kg（标准版含电池）",
               "kg", 1250, "g", "约", variant="标准版"),
            _f(2, model_id, "weight", "portability", "约 1.27 kg（触控版含电池）", "约 1.27 kg（触控版含电池）",
               "kg", 1270, "g", "约", variant="触控版"),
            _f(3, model_id, "screen_size", "display", "14.2 英寸", "14.2 英寸", "英寸", 14.2, "inch"),
            _f(4, model_id, "refresh_rate", "display", "最高 120 Hz", "最高 120 Hz", "Hz", 120, "Hz",
               "最高", upper=True),
            _f(5, model_id, "brightness", "display", "500 nits（典型值）", "500 nits（典型值）", "nits", 500,
               "nits", "典型值"),
            _f(6, model_id, "battery_capacity", "battery", "65 Wh（额定容量）", "65 Wh（额定容量）", "Wh", 65,
               "Wh", "额定"),
            _f(7, model_id, "battery_life", "battery", "本地视频播放最长约 14 小时", "本地视频播放最长约 14 小时",
               "小时", 14, "h", "最长", upper=True),
            _f(8, model_id, "cpu", "performance", "演示芯片 D90", "演示芯片 D90", kind="entity"),
            _f(9, model_id, "memory", "storage_memory", "16 GB / 32 GB", "16 GB / 32 GB", "GB"),
            _f(10, model_id, "ports", "ports", "2 × USB-C，1 × USB-A，1 × 3.5 mm 耳机接口",
               "2 × USB-C，1 × USB-A，1 × 3.5 mm 耳机接口", kind="entity"),
            _f(11, model_id, "collaboration", "collaboration", "多屏协同，跨设备文件拖拽", "多屏协同，跨设备文件拖拽",
               kind="entity"),
            _f(12, model_id, "feature", "portability", "适合经常带出门的学生和通勤用户",
               "可用结论：适合经常带出门的学生和通勤用户。", kind="claim", src="卖点与限制.md"),
        ]
        entities = ["演示芯片 D90", "USB-C", "USB-A", "多屏协同", "DemoOS 5"]
    else:
        facts = [
            _f(1, model_id, "weight", "portability", "约 1.38 kg（含电池）", "约 1.38 kg（含电池）", "kg", 1380, "g", "约"),
            _f(2, model_id, "refresh_rate", "display", "60 Hz", "60 Hz", "Hz", 60, "Hz"),
            _f(3, model_id, "battery_capacity", "battery", "56 Wh（额定容量）", "56 Wh（额定容量）", "Wh", 56, "Wh", "额定"),
            _f(4, model_id, "cpu", "performance", "演示芯片 D70", "演示芯片 D70", kind="entity"),
            _f(5, model_id, "ports", "ports", "2 × USB-C，1 × HDMI，1 × 3.5 mm 耳机接口",
               "2 × USB-C，1 × HDMI，1 × 3.5 mm 耳机接口", kind="entity"),
        ]
        entities = ["演示芯片 D70", "USB-C", "HDMI", "DemoOS 5"]
    return Ledger(model_id=model_id, facts=facts, entities=entities)


def fake_task(platform: str = "xiaohongshu", scenario: str = "back_to_school") -> Task:
    return Task(raw_text="一位妈妈想给下个月上大学的女儿买笔记本，发小红书", product_query="DemoBook 14（演示版）",
                model_id="demobook-14", audience="大学新生（购买人：家长）", scenario=scenario, platform=platform)


def fake_strategy(scenario: str = "back_to_school") -> Strategy:
    if scenario == "office":
        cats, ids, angle = ["battery", "collaboration", "portability"], ["F6", "F11", "F1"], "出差一天，电量和文件都跟得上"
    else:
        cats, ids, angle = ["portability", "battery", "collaboration"], ["F1", "F7", "F11"], "宿舍、教室、图书馆来回跑也不累"
    a = ScenarioAnalysis(audience="大学新生（购买人：家长）", buying_stage="比较", problem="课多、教室分散，怕重怕没电",
                         content_goal="让家长把该型号放进候选并到店体验", categories=cats)
    return Strategy(analysis=a, angle=angle, selling_points=[SellingPoint(i, "场景匹配") for i in ids],
                    talk_card=["先问孩子平时背包走多远", "重点讲重量和续航", "邀请到店上手试重量"], cta_type="到店体验")


def fake_plan(platform: str = "xiaohongshu", model_id: str = "demobook-14") -> ImagePlan:
    lo, hi = PLATFORM_IMAGE_RANGE[platform]
    imgs = fake_bundle(model_id).images[:hi]
    pos = ["标题下方", "第1段后", "第2段后", "第3段后", "文末", "文末"]
    return ImagePlan(platform=platform, items=[PlannedImage(im, pos[i % len(pos)], im.caption)
                                               for i, im in enumerate(imgs)],
                     shortage=len(imgs) < lo)


def fake_post(platform: str = "xiaohongshu") -> Post:
    """A post that PASSES all checks for the fixtures (use it as the 'good' case in tests)."""
    plan = fake_plan(platform)
    imgs = [PostImage(p.image.media_id, p.position, p.caption) for p in plan.items]
    if platform == "moments":
        return Post(platform, "", "", ["背着跑一天也不累，重量约 1.25 kg [F1]，放进双肩包不占地方。"],
                    "周末来店里上手掂一掂。", ["开学季", "轻薄本"], ["F1"], imgs[:2])
    return Post(platform, "开学装备清单：一台背得动的笔记本", "宿舍、教室、图书馆来回跑，电脑的重量每天都在你肩上。",
                ["重量约 1.25 kg [F1]，放进双肩包不占地方。",
                 "本地视频播放可达约 14 小时 [F7]，一天的课上下来少找插座。",
                 "多屏协同 [F11] 让手机里的课件直接拖到电脑上。"],
                "想试试重量，可以来店里上手。", ["开学季", "大学生笔记本", "轻薄本"], ["F1", "F7", "F11"], imgs)


class FakeLLM:
    """Canned LLM. chat_json returns `responses[key]` where key is the `stage` argument."""

    def __init__(self, responses: dict | None = None):
        self.responses = responses or {}
        self.calls: list[dict] = []

    def chat_json(self, system: str, user: str, stage: str = "", **kw) -> dict:
        self.calls.append({"stage": stage, "system": system[:200], "user": user[:200]})
        r = self.responses.get(stage, {})
        return json.loads(json.dumps(r, ensure_ascii=False))

    def chat_text(self, system: str, user: str, stage: str = "", **kw) -> str:
        self.calls.append({"stage": stage})
        return str(self.responses.get(stage, ""))


def empty_report() -> CheckReport:
    return CheckReport()


# ---------------------------------------------------------------- stage fakes (same signatures as the real modules)
# Deterministic, code-only stand-ins so agent/pipeline.py and app.py run end to end before P1–P4 land.
import copy as _copy  # noqa: E402
import re as _re  # noqa: E402

from agent.schemas import (  # noqa: E402
    CheckIssue, Clarification, Conflict, NeedsHuman, PLATFORM_LABELS, Question, SCENARIO_LABELS,
)

_PLATFORM_WORDS = {"小红书": "xiaohongshu", "朋友圈": "moments", "公众号": "wechat_article",
                   "海报": "poster", "抖音": "douyin"}
_SCENARIO_WORDS = {"开学": "back_to_school", "大学": "back_to_school", "学生": "back_to_school",
                   "办公": "office", "出差": "office", "职场": "office", "白领": "office",
                   "创作": "creator", "剪辑": "creator", "设计": "creator",
                   "换新": "family_upgrade", "家庭": "family_upgrade", "父母": "family_upgrade",
                   "企业": "enterprise", "采购": "enterprise",
                   "到店": "store_visit", "门店": "store_visit",
                   "新品": "new_launch", "首发": "new_launch",
                   "节日": "holiday", "双十一": "holiday", "年货": "holiday"}
_AUDIENCE_DEFAULT = {"back_to_school": "大学新生（购买人：家长）", "office": "经常出差的职场人",
                     "creator": "自媒体内容创作者", "family_upgrade": "为父母换新电脑的家庭用户",
                     "enterprise": "中小企业 IT 采购负责人", "store_visit": "到店体验的顾客",
                     "new_launch": "关注新品的科技爱好者", "holiday": "节日送礼的消费者"}


def _norm(s: str) -> str:
    return (s or "").replace(" ", "").lower()


def fake_parse_task(text: str, catalog, form: dict | None = None, llm=None):
    """Keyword intake + catalog resolver. One question round covers everything missing."""
    form = form or {}
    task = Task(raw_text=text)
    low = _norm(text)
    for w, p in _PLATFORM_WORDS.items():
        if w in text:
            task.platform = p
            break
    for w, s in _SCENARIO_WORDS.items():
        if w in text:
            task.scenario = s
            break
    best = ""  # product: longest alias / canonical name found in the text
    for m in catalog.models.values():
        for name in [m.canonical_name, *m.aliases]:
            if name and _norm(name) in low and len(name) > len(best):
                best = name
    task.product_query = form.get("product") or best or None
    if form.get("platform"):
        task.platform = {v: k for k, v in PLATFORM_LABELS.items()}.get(form["platform"], form["platform"])
    if form.get("scenario"):
        task.scenario = {v: k for k, v in SCENARIO_LABELS.items()}.get(form["scenario"], form["scenario"])
    if form.get("audience"):
        task.audience = form["audience"]
    if form.get("variant"):
        task.variant = form["variant"]
    m = _re.search(r"(加上|写上|提一下|强调)([^，。,]+)", text)
    if m:
        task.extra_requirements.append(m.group(2).strip())

    questions: list[Question] = []
    if task.product_query:
        rr = catalog.resolve(task.product_query)
        if rr.status in ("resolved", "text_only"):
            task.model_id = rr.model.model_id
        elif rr.status == "ambiguous":
            questions.append(Question("product", f"“{task.product_query}”对应多个型号，请选择：",
                                      [c.canonical_name for c in rr.candidates[:4]]))
        else:
            questions.append(Question("product", "知识库中未找到该型号，请从以下型号中选择：",
                                      [c.canonical_name for c in rr.candidates[:4]]))
    else:
        questions.append(Question("product", "请选择要介绍的型号：",
                                  [m.canonical_name for m in list(catalog.models.values())[:4]]))
    if not task.platform:
        questions.append(Question("platform", "发布到哪个平台？", ["小红书", "门店朋友圈", "公众号", "门店海报"]))
    if not task.scenario:
        questions.append(Question("scenario", "主要是什么场景？", ["开学季", "职场办公", "内容创作", "家庭换新"]))
    if questions:
        return Clarification(questions=questions, partial=task)
    task.audience = task.audience or _AUDIENCE_DEFAULT.get(task.scenario, "普通消费者")
    return task


_SCENARIO_CATS = {
    "back_to_school": ["portability", "battery", "collaboration", "display"],
    "office": ["battery", "collaboration", "portability", "ports"],
    "creator": ["display", "performance", "storage_memory", "ports"],
    "family_upgrade": ["display", "system", "collaboration", "service"],
    "enterprise": ["security", "service", "performance", "ports"],
    "store_visit": ["design", "display", "portability", "collaboration"],
    "new_launch": ["performance", "display", "design", "system"],
    "holiday": ["design", "display", "portability", "collaboration"],
}
_SCENARIO_PROBLEM = {
    "back_to_school": ("课多、教室分散，怕重怕没电", "让家长把该型号放进候选并到店体验"),
    "office": ("出差路上要开会改文件，怕没电怕不好带", "让职场人把该型号列入换机候选"),
    "creator": ("修图剪辑看颜色、等导出，怕屏幕不准怕卡", "让创作者愿意到店看屏幕"),
    "family_upgrade": ("父母用旧电脑卡顿、不会折腾", "让家庭用户觉得省心好上手"),
    "enterprise": ("批量采购要稳定好管理", "让采购负责人联系门店了解方案"),
    "store_visit": ("路过门店想快速了解", "吸引顾客上手体验"),
    "new_launch": ("想知道新品值不值得关注", "引导关注与到店"),
    "holiday": ("送礼要体面实用", "引导节日到店"),
}


_CAT_WORDS = {"battery": ("续航", "电池"), "portability": ("轻", "重量", "便携"), "display": ("屏", "显示"),
              "collaboration": ("协同", "互联"), "performance": ("性能", "芯片"), "ports": ("接口",)}


def _prioritise(cats: list[str], task: Task) -> list[str]:
    """"突出续航" / "换卖点" style requirements move that category first (or rotate the order)."""
    for req in task.extra_requirements:
        hit = False
        for cat, words in _CAT_WORDS.items():
            if any(w in req for w in words) and cat in cats:
                cats.remove(cat)
                cats.insert(0, cat)
                hit = True
        if not hit and ("换卖点" in req or "角度" in req) and len(cats) > 1:
            cats.append(cats.pop(0))
    return cats


def fake_analyze(task: Task, llm=None) -> ScenarioAnalysis:
    sc = task.scenario or "back_to_school"
    problem, goal = _SCENARIO_PROBLEM.get(sc, _SCENARIO_PROBLEM["back_to_school"])
    cats = _prioritise(list(_SCENARIO_CATS.get(sc, _SCENARIO_CATS["back_to_school"])), task)
    return ScenarioAnalysis(audience=task.audience or _AUDIENCE_DEFAULT.get(sc, "普通消费者"),
                            buying_stage="比较", problem=problem, content_goal=goal, categories=cats,
                            reasons={c: "与场景痛点相关" for c in cats})


_ANGLES = {"back_to_school": "宿舍、教室、图书馆来回跑也不累", "office": "出差一天，电量和文件都跟得上",
           "creator": "看得准、存得下，先把屏幕看明白", "family_upgrade": "给父母一台省心的电脑",
           "enterprise": "稳定、好管理的办公设备", "store_visit": "到店三分钟，上手就知道",
           "new_launch": "新品到了，先看这几点", "holiday": "送一台实用的礼物"}


def fake_reconcile(task: Task, analysis: ScenarioAnalysis, ledger: Ledger, model: Model, llm=None):
    """Maps categories → ledger facts (first fact per category), stops on a needs_human attribute."""
    chosen: list[SellingPoint] = []
    dropped: dict[str, str] = {}
    pending: list[str] = []
    used_attrs: set[str] = set()
    for cat in _prioritise(list(analysis.categories), task):
        facts = [f for f in ledger.facts if f.category == cat and f.attribute not in used_attrs]
        if not facts:
            dropped[cat] = "知识库无该类事实，未使用"
            continue
        f = facts[0]
        if f.attribute in model.needs_human:
            conflicts = [c for c in ledger.conflicts if c.attribute == f.attribute] or \
                        [Conflict(f.attribute, f.variant, [f.id], "知识库资料对该参数说法不一致")]
            return NeedsHuman(conflicts=conflicts,
                              message=f"知识库中关于「{model.canonical_name}」的 {f.attribute} 资料存在冲突，"
                                      f"而本文需要使用该参数。已停止输出，请人工确认后再生成。")
        used_attrs.add(f.attribute)
        chosen.append(SellingPoint(f.id, f"对应场景需求：{cat}"))
        if len(chosen) >= 3:
            break
    for attr in model.needs_human:
        if attr not in used_attrs:
            pending.append(f"知识库对该型号的 {attr} 资料存在冲突，本文未使用该参数")
    if not chosen:
        chosen = [SellingPoint(ledger.facts[0].id, "兜底：知识库首条事实")]
    angle = _ANGLES.get(task.scenario or "", "先说贴近使用的一点")
    if any("角度" in r for r in task.extra_requirements):
        angle = "换个角度：从一天的使用过程说起"
    return Strategy(analysis=analysis, angle=angle, selling_points=chosen, dropped_categories=dropped,
                    talk_card=["先问顾客平时怎么用、带去哪里", "按知识库事实讲前两个卖点，不比较其他品牌",
                               "邀请到店上手体验"], cta_type="到店体验", pending=pending)


def fake_plan_images(bundle: ModelBundle, platform: str, strategy: Strategy) -> ImagePlan:
    lo, hi = PLATFORM_IMAGE_RANGE[platform]
    imgs = [im for im in bundle.images if im.model_id == bundle.model.model_id][:hi]
    pos = ["标题下方", "第1段后", "第2段后", "第3段后", "文末", "文末", "文末", "文末", "文末"]
    shortage = len(imgs) < lo
    note = ""
    if shortage:
        note = "知识库无该型号图片" if not imgs else f"知识库该型号图片不足（{len(imgs)} 张，平台建议至少 {lo} 张）"
    return ImagePlan(platform=platform, shortage=shortage, note=note,
                     items=[PlannedImage(im, pos[i], im.caption) for i, im in enumerate(imgs)])


def _say(f: Fact) -> str:
    """Rephrase a KB value for the post: 最高/最长/最大 → 可达, keep the number."""
    v = _re.sub(r"最(高|长|大)约?", "可达", f.value)
    return f"{v} [{f.id}]"


_TITLES = {"back_to_school": "开学装备清单：一台背得动的笔记本", "office": "出差包里只放一台电脑够不够",
           "creator": "修图剪辑前，先把屏幕看明白", "family_upgrade": "给爸妈换电脑，省心比参数重要",
           "enterprise": "办公电脑怎么选更省心", "store_visit": "路过门店，三分钟上手一台笔记本",
           "new_launch": "新品到店，先看这几点", "holiday": "送电脑这件事，可以更实用一点"}
_LEAD = {"weight": "重量", "battery_life": "续航", "battery_capacity": "电池", "refresh_rate": "刷新率",
         "brightness": "亮度", "screen_size": "屏幕", "cpu": "处理器", "memory": "内存", "ports": "接口",
         "collaboration": "协同", "feature": ""}


def fake_write_post(task: Task, strategy: Strategy, ledger: Ledger, plan: ImagePlan, llm=None) -> Post:
    """Deterministic writer: one cited claim per selling point, structure per platform."""
    p = task.platform or plan.platform
    facts = [ledger.get(sp.fact_id) for sp in strategy.selling_points if ledger.get(sp.fact_id)]
    ids = [f.id for f in facts]
    imgs = [PostImage(it.image.media_id, it.position, it.caption) for it in plan.items]
    sc = task.scenario or "back_to_school"
    short = any("短" in r for r in task.extra_requirements)
    tags = [SCENARIO_LABELS.get(sc, "笔记本"), "轻薄本", "笔记本推荐"]
    pain = strategy.analysis.problem.split("，")[0]
    paras = [f"{_LEAD.get(f.attribute, '')}{_say(f)}，{pain}这件事就轻松一些。" for f in facts]
    if p == "moments":
        f = facts[0]
        return Post(p, "", "", [f"{strategy.angle}：{_LEAD.get(f.attribute, '')}{_say(f)}。"],
                    "周末来店里上手试试。", tags[:2], [f.id], imgs[:3])
    if p == "poster":
        return Post(p, "轻装上阵", strategy.angle, [_say(f) for f in facts[:3]], "欢迎到店体验",
                    tags[:1], ids[:3], imgs[:1])
    if p == "douyin":
        return Post(p, f"{strategy.angle}？", "先说结论：这几点和你有关。", paras[:3], "想看实机评论区留言。",
                    tags[:3], ids, imgs[:9])
    if p == "wechat_article":
        body = [f"{strategy.analysis.problem}。{strategy.angle}。"] + \
               [pp + "日常使用中这类细节决定体验。" for pp in paras] + \
               ["以上参数均来自官方资料，实际体验建议到店上手。"]
        return Post(p, _TITLES.get(sc, "一台更贴近日常的笔记本"), strategy.analysis.problem + "，这篇说清楚。",
                    body if not short else body[:2], "欢迎到店体验，也可以留言告诉我们你的使用场景。", tags, ids, imgs[:4])
    body = paras if not short else paras[:1]  # xiaohongshu (default)
    return Post(p, _TITLES.get(sc, "一台更贴近日常的笔记本"), f"{strategy.analysis.problem}，{strategy.angle}。",
                body, "想试试手感，可以来店里上手。", tags, ids, imgs[:6])


def fake_rewrite(post: Post, issues: list[CheckIssue], task: Task, strategy: Strategy, ledger: Ledger,
                 plan: ImagePlan, llm=None) -> Post:
    """Targeted: removes each issue's span from its field; drops a paragraph that has no span."""
    new = _copy.deepcopy(post)
    for i in issues:
        m = _re.match(r"body\[(\d+)\]", i.field or "")
        if m and int(m.group(1)) < len(new.body):
            k = int(m.group(1))
            new.body[k] = new.body[k].replace(i.span, "") if i.span else ""
        elif i.field in ("title", "intro", "cta") and i.span:
            setattr(new, i.field, getattr(new, i.field).replace(i.span, ""))
    new.body = [b for b in new.body if b.strip()] or post.body
    return new


def fake_run_checks(post: Post, ledger: Ledger, sibling_ledgers: dict, task: Task, plan: ImagePlan,
                    llm=None) -> CheckReport:
    """Empty report (passes). Tests that need failures pass their own fake."""
    return CheckReport()


def fake_status() -> dict:
    """Stand-in for ImaClient.status(): never contains key or Client ID characters."""
    return {"kb_name": "任德耀新建华为PC知识库", "connected": False, "configured": False,
            "index_status": "partial", "error": "开发模式：未连接 ima"}
