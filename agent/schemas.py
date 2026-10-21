"""
SHARED CONTRACT. Every workstream codes against these types.

Owner: the integrator (lead). Do NOT edit in a feature branch. If you need a change,
ask the lead; the lead changes it on main and everyone rebases.

All stages pass these objects (or their .to_dict()) to each other. Field names are
final; add new optional fields only via the lead.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, Optional

# ---------------------------------------------------------------- enums / keys
Platform = Literal["wechat_article", "xiaohongshu", "moments", "poster", "douyin"]
PLATFORMS: tuple[str, ...] = ("wechat_article", "xiaohongshu", "moments", "poster", "douyin")
PLATFORM_LABELS = {
    "wechat_article": "公众号", "xiaohongshu": "小红书", "moments": "门店朋友圈",
    "poster": "门店海报", "douyin": "抖音图文",
}
# Handbook image ranges (douyin is our extension). platform_rules.py imports this; do not duplicate.
PLATFORM_IMAGE_RANGE = {
    "wechat_article": (2, 4), "xiaohongshu": (3, 6), "moments": (1, 3), "poster": (1, 1), "douyin": (3, 9),
}

Scenario = Literal["back_to_school", "office", "creator", "family_upgrade",
                   "enterprise", "store_visit", "new_launch", "holiday", "campus_daily"]
SCENARIO_LABELS = {
    "back_to_school": "开学季", "office": "职场办公", "creator": "内容创作", "family_upgrade": "家庭换新",
    "enterprise": "企业采购", "store_visit": "门店到店", "new_launch": "新品首发", "holiday": "节日营销",
    "campus_daily": "校园日常",   # student stores outside the 开学季 window (proactive cards)
}

# Selling-point categories used by scenario analysis (step 2) and the ledger (step 4).
CATEGORIES = ("portability", "battery", "display", "performance", "storage_memory", "ports",
              "collaboration", "system", "audio_camera", "design", "security", "service", "other")

# The handbook's 4 section headings, verbatim. formatter.py must use these.
SECTION_HEADINGS = ("一、场景判断", "二、知识库依据", "三、图文软文", "四、核验结果")


def _d(obj):
    return asdict(obj)


# ---------------------------------------------------------------- step 1: intake
@dataclass
class Question:
    slot: Literal["product", "audience", "scenario", "platform", "variant"]
    text: str                      # Chinese question shown to the user
    options: list[str]             # chip labels (2–4); for product: canonical model names


@dataclass
class Clarification:
    questions: list[Question]
    partial: Optional["Task"] = None   # what was understood so far
    to_dict = _d


@dataclass
class Task:
    raw_text: str
    product_query: Optional[str] = None     # what the user typed
    model_id: Optional[str] = None          # resolved catalog id (image slug), set by the resolver
    variant: Optional[str] = None           # SKU-level variant if the user gave one (e.g. "32GB")
    audience: Optional[str] = None
    scenario: Optional[str] = None          # a Scenario key
    platform: Optional[str] = None          # a Platform key
    extra_requirements: list[str] = field(default_factory=list)  # e.g. "加上500元补贴" (checks decide)
    notes: list[str] = field(default_factory=list)  # 待确认 lines from intake (e.g. a variant not in the KB)
    # -- recommender brief (PROACTIVE_AGENT_PLAN §10.7). All optional with defaults: the manual intake flow
    #    never sets them. Filled by agent/recommend/to_task.card_to_task; read by Phase 2 writer / checkers.
    source: Literal["manual", "card"] = "manual"
    card_id: Optional[str] = None
    store_id: Optional[str] = None
    store_name: Optional[str] = None
    slot: Optional[str] = None              # potential | promo | new_release | customer_question
    segment: Optional[str] = None           # student | office | family | shopper
    hook: Optional[str] = None              # hook id from angles.json
    voice: Optional[str] = None             # voice id from angles.json (staff override already applied)
    landmark: Optional[str] = None
    nickname: Optional[str] = None
    angle: Optional[str] = None
    calendar_theme: Optional[str] = None
    promo: Optional[dict] = None            # CardPromo.to_dict(): the ONLY allowed price source
    question: Optional[dict] = None         # CardQuestion.to_dict(): the only allowed customer-question source
    staff: Optional[dict] = None            # StaffContext.to_dict() if a person was given
    card_date: Optional[str] = None         # ISO date of the card: an active-campaign check needs it
    to_dict = _d


# ---------------------------------------------------------------- catalog / data layer
@dataclass
class Model:
    model_id: str                  # image slug, e.g. "matebook-14-harmonyos" (unique, stable)
    canonical_name: str            # official name from 图片索引.csv, never the folder name
    folder_name: str
    route: Literal["harmonyos", "windows", "text_only"]
    aliases: list[str] = field(default_factory=list)
    siblings: list[str] = field(default_factory=list)   # model_ids in the same confusable group
    has_images: bool = True
    needs_human: list[str] = field(default_factory=list)  # attributes with known KB conflicts, e.g. ["cpu"]


@dataclass
class ResolveResult:
    status: Literal["resolved", "ambiguous", "not_found", "text_only"]
    model: Optional[Model] = None
    candidates: list[Model] = field(default_factory=list)
    reason: str = ""


@dataclass
class ImageRef:
    media_id: str                  # internal only; never shown in the UI or committed
    title: str                     # file name
    source_path: str               # KB folder path, shown as 来源
    model_id: str
    caption: str = ""              # 画面说明 / 官网图片说明 from 图片索引.csv
    folder_kind: Literal["images", "商城款式图片"] = "images"
    role: Literal["main", "scene", "detail", "color", "unknown"] = "unknown"


@dataclass
class SourceRecord:
    title: str
    source_path: str
    media_id: str                  # internal only
    media_type: int
    fetched_at: str                # ISO timestamp


@dataclass
class ModelBundle:
    model: Model
    facts_text: str                # 产品事实.md, scrape noise stripped
    claims_text: str               # 卖点与限制.md
    images: list[ImageRef]
    sources: list[SourceRecord]
    facts_source: Optional[SourceRecord] = None
    claims_source: Optional[SourceRecord] = None
    cards: dict[str, str] = field(default_factory=dict)  # optional persona/lookup cards, by name
    index_status: Literal["complete", "partial", "stale"] = "complete"
    unlisted: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- step 4: ledger
@dataclass
class Fact:
    id: str                        # "F1", "F2", … unique within one ledger
    model_id: str
    attribute: str                 # e.g. "weight", "battery_capacity", "screen_size", "cpu", "feature"
    category: str                  # one of CATEGORIES
    value: str                     # as written in the KB, incl. qualifier text (约 / 典型值 / 最高)
    quote: str                     # verbatim text from the source; value must be inside quote
    source_title: str
    source_path: str
    kind: Literal["spec", "claim", "entity"] = "spec"
    variant: str = "all"           # "all" or e.g. "方键盘", "32GB版", "柔光屏"
    unit: str = ""                 # as written
    norm_value: Optional[float] = None   # normalised numeric value (None for non-numeric)
    norm_unit: str = ""            # canonical unit: g, inch, Wh, Hz, GB, nits, W, h, mm, ppi
    qualifier: str = ""            # 约 / 典型值 / 峰值 / 最高 / 额定 …
    upper_bound: bool = False      # True for 最高/最长/可达 values


@dataclass
class Conflict:
    attribute: str
    variant: str
    fact_ids: list[str]
    reason: str


@dataclass
class Ledger:
    model_id: str
    facts: list[Fact]
    conflicts: list[Conflict] = field(default_factory=list)
    dropped: list[dict] = field(default_factory=list)   # {"row": {...}, "reason": "..."} failed quote checks
    entities: list[str] = field(default_factory=list)   # named terms: chip names, ports, display tech, features
    boundaries: list[dict] = field(default_factory=list)  # {"category", "text", "source_title"} from 表达边界 lines
    to_dict = _d

    def get(self, fact_id: str) -> Optional[Fact]:
        return next((f for f in self.facts if f.id == fact_id), None)


# ---------------------------------------------------------------- steps 2 + 5: strategy
@dataclass
class ScenarioAnalysis:
    audience: str
    buying_stage: str              # e.g. 了解 / 比较 / 决策 / 到店
    problem: str
    content_goal: str
    categories: list[str]          # ranked CATEGORIES, no specs
    reasons: dict[str, str] = field(default_factory=dict)  # category -> why


@dataclass
class SellingPoint:
    fact_id: str
    reason: str


@dataclass
class Strategy:
    analysis: ScenarioAnalysis
    angle: str                     # content angle (切入点)
    selling_points: list[SellingPoint]   # ordered; fact_ids must exist in the ledger
    dropped_categories: dict[str, str] = field(default_factory=dict)  # category -> why dropped
    talk_card: list[str] = field(default_factory=list)  # 3 lines for the salesperson (also checked)
    cta_type: str = ""
    pending: list[str] = field(default_factory=list)    # 待确认 lines
    to_dict = _d


@dataclass
class EditBlocked:
    """pipeline.edit() refused an instruction before calling the writer (e.g. "加上立减500" with no matching
    promotion record). `prev` is the unchanged previous result, so the UI can keep showing it."""
    instruction: str
    message: str                   # Chinese, cites the rule; shown to the user
    rule: str = "price_traceability"
    prev: Optional["RunResult"] = None


@dataclass
class NeedsHuman:
    conflicts: list[Conflict]
    message: str                   # Chinese, shown to the user
    to_dict = _d


# ---------------------------------------------------------------- step 6: image plan
@dataclass
class PlannedImage:
    image: ImageRef
    position: str                  # e.g. "标题下方", "第2段后", "文末"
    caption: str                   # from KB caption / adjacent text only


@dataclass
class ImagePlan:
    platform: str
    items: list[PlannedImage]
    shortage: bool = False         # KB has fewer images than the platform minimum
    note: str = ""


# ---------------------------------------------------------------- step 7: post
@dataclass
class PostImage:
    media_id: str                  # must be one of ImagePlan items
    position: str
    caption: str


@dataclass
class Post:
    platform: str
    title: str
    intro: str
    body: list[str]                # paragraphs; may contain [F#] tags until export
    cta: str
    tags: list[str]                # 平台标签 (always filled); shown as #hashtags only where allowed
    selling_points: list[str]      # fact ids used
    images: list[PostImage]
    to_dict = _d

    def all_text(self) -> str:
        return "\n".join([self.title, self.intro, *self.body, self.cta])


# ---------------------------------------------------------------- step 8: checks
@dataclass
class CheckIssue:
    stage: Literal["8A", "8B", "8C", "8D"]
    severity: Literal["error", "warn"]
    code: str                      # e.g. "unsupported_number", "sibling_value", "banned_word", "image_count"
    message: str                   # Chinese, shown in 核验结果
    field: str = ""                # "title" | "intro" | "body[2]" | "cta" | "tags" | "images" | ""
    span: str = ""                 # offending text
    fact_id: str = ""


@dataclass
class CheckReport:
    issues: list[CheckIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(i.severity == "error" for i in self.issues)

    def merge(self, other: "CheckReport") -> "CheckReport":
        return CheckReport(self.issues + other.issues)


# ---------------------------------------------------------------- final result
@dataclass
class RunResult:
    task: Task
    model: Model
    strategy: Strategy
    ledger: Ledger
    plan: ImagePlan
    post: Post                     # after checks; [F#] tags still present (formatter strips them)
    report: CheckReport
    pending: list[str] = field(default_factory=list)   # all 待确认 lines
    sources: list[SourceRecord] = field(default_factory=list)
    timings: dict[str, float] = field(default_factory=dict)
    loops: int = 0


# ---------------------------------------------------------------- recommender (PROACTIVE_AGENT_PLAN §10.7)
# Field names match data/demo/templates/recommendation_card.example.json exactly. A card is per STORE;
# a StaffContext only overrides voice / nickname for one person's version of the post (plan §2.1 demo
# mode: no login, no auth, no session).
@dataclass
class CardReason:
    text: str
    source: Literal["poi", "sales", "promo", "release", "questions", "calendar"]
    is_demo: bool = True            # drives the 模拟 badge


@dataclass
class CardHook:
    id: str                         # scene | question | customer | myth | checklist (angles.json)
    label: str


@dataclass
class CardVoice:
    id: str                         # manager | techie | senior (angles.json)
    label: str


@dataclass
class CardPromo:
    campaign_id: str
    name: str
    mechanic: str
    price_info: Optional[dict] = None   # {label, value, currency, conditions} — the ONLY allowed price source
    source: str = "DEMO"
    to_dict = _d


@dataclass
class CardQuestion:
    chip_id: str
    text: str
    count: int
    to_dict = _d


@dataclass
class RecommendationCard:
    card_id: str
    store_id: str
    store_name: str
    date: str                       # ISO date
    slot: Literal["potential", "promo", "new_release", "customer_question"]
    slot_label: str                 # 潜力款 / 活动款 / 新品款 / 顾客问答
    model_id: Optional[str]         # writer must fetch facts for exactly this ID
    display_name: Optional[str]
    platform: str                   # Chinese label from the weekly rotation (朋友圈 / 小红书 / 公众号)
    segment: str                    # student | office | family | shopper
    segment_label: str
    angle: str
    scenario: Optional[str] = None  # a Scenario key, calendar-aware (agent/recommend/slots.scenario_for)
    calendar_theme: Optional[str] = None
    hook: Optional[CardHook] = None
    voice: Optional[CardVoice] = None
    landmark: str = ""
    nickname: str = ""
    reasons: list[CardReason] = field(default_factory=list)
    locked: bool = False
    locked_reason: Optional[str] = None    # "fact_card_draft" → show 待总部确认, don't generate
    promo: Optional[CardPromo] = None
    question: Optional[CardQuestion] = None
    scores: dict = field(default_factory=dict)   # fit / index / potential / share / peer_share; never in copy
    is_default: bool = False
    is_demo: bool = True
    to_dict = _d

    @classmethod
    def from_dict(cls, d: dict) -> "RecommendationCard":
        d = dict(d)
        d["reasons"] = [r if isinstance(r, CardReason) else CardReason(**r) for r in d.get("reasons") or []]
        for key, typ in (("hook", CardHook), ("voice", CardVoice), ("promo", CardPromo), ("question", CardQuestion)):
            v = d.get(key)
            d[key] = typ(**v) if isinstance(v, dict) else v
        return cls(**d)


@dataclass
class LockedResult:
    """run_from_card() on a locked card: nothing was generated, no LLM or ima call was made."""
    card: "RecommendationCard"
    reason: str                     # card.locked_reason, e.g. "fact_card_draft"
    message: str                    # Chinese, shown to the user: 新品资料待总部确认，暂不可生成
    to_dict = _d


BASELINE_LABEL = "对照组：未经约束的普通大模型输出"


@dataclass
class BaselineResult:
    """generate_baseline(): one naive LLM call for the video's before/after shot. NEVER our result:
    `display_text` always starts with BASELINE_LABEL and the UI must show it as the control group."""
    card_id: str
    model_id: Optional[str]
    platform: str
    prompt: str                     # the naive prompt that was sent
    text: str                       # raw model output, unchecked
    display_text: str               # label + text: the only form the UI should render
    hits: list["CheckIssue"] = field(default_factory=list)   # 8D stage-1 hits, for highlighting only
    label: str = BASELINE_LABEL
    is_baseline: bool = True
    to_dict = _d


@dataclass
class StaffContext:
    """Who is posting (demo mode, no auth). Only voice / nickname may differ from the store card."""
    staff_id: str
    display_name: str
    role: Literal["staff", "manager"] = "staff"
    voice: Optional[str] = None     # voice id override; must be allowed for the card's segment
    nickname: Optional[str] = None  # sign-off override
    to_dict = _d
