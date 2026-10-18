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
    """Same interface as agent.catalog.Catalog."""
    models = MODELS

    def resolve(self, query: str) -> ResolveResult:
        q = (query or "").replace(" ", "").lower()
        if q in ("demobook14se", "demobook14se版"):
            return ResolveResult("resolved", model=DEMO_SE)
        if q in ("demobook14（演示版）", "demobook14演示版", "演示本14"):
            return ResolveResult("resolved", model=DEMO)
        if q in ("demobook14", "demobook"):
            return ResolveResult("ambiguous", candidates=[DEMO, DEMO_SE], reason="名称同时匹配 2 个型号")
        if "商用台式机" in q:
            return ResolveResult("text_only", model=DEMO_TEXT_ONLY)
        return ResolveResult("not_found", candidates=[DEMO, DEMO_SE], reason="知识库中未找到该型号")

    def get(self, model_id: str) -> Model:
        return MODELS[model_id]

    def siblings(self, model_id: str) -> list[Model]:
        return [MODELS[s] for s in MODELS[model_id].siblings]


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
