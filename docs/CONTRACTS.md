# Team contracts: parallel build

Five workstreams build at the same time. This file fixes **who owns which files**, **the function signatures between workstreams**, and **the facts about the real KB that override `docs/WORKFLOW.md` (v4)**. Types live in `agent/schemas.py`. Fakes for every interface live in `tests/fakes.py`.

**Owner of this file, `agent/schemas.py` and `tests/fakes.py`:** the lead/integrator (P5). Feature branches never edit them; ask the lead.

---

## 1. KB facts that override WORKFLOW v4

From `docs/kb_structure.md` (live exploration, 2026-10-18):

| WORKFLOW v4 says | Reality | Use this |
|---|---|---|
| one `article.md` per model, ~314 items | No `article.md` anywhere. 537 files, 104 folders. Each model folder has `产品事实.md` (scraped specs: heading / label line / value line, footnotes start with `*`, a leave-site banner at the end), `卖点与限制.md` (curated angles with 可用结论 / 支撑事实 / 表达边界, compliance examples, image rules), `图片索引.csv`, `来源清单.csv`, `images/` | `产品事实.md` = spec facts, `卖点与限制.md` = claims + boundaries |
| walk the KB at startup, refresh on a timer | Daily quota: code **220021** after ~100 folder listings | Build the index from ~25 targeted listings (P1/01, P1/02, 10 model folders, 11 image folders). 24 h disk cache, stale-on-error. **Only P1 calls ima during development.** |
| images by model ID | 68 images in 11 folders, never inline. Folder, file-name slug and 图片索引.csv agree on all 68. The joint table lists 112 images, 44 of them don't exist. | Image belongs to M only if folder ⊂ M's subtree AND slug == M.model_id exactly AND a row in M's 图片索引.csv. Never use the joint table. |
| folders | Folders come back as `media_type: 99` with a `folder_<n>` id | Reuse returned ids only |
| prices | Real dated per-SKU price snapshots exist in `P1/08` | **Prices off by default.** Optional later: exact SKU + type + date + conditions + "以官方页面实时信息为准". Missing SKU → ask. Conflicting snapshots → stop. |
| P4–P8 | Not listable today (quota); P4 is labelled 机密 | Retry P5–P8 once after the quota resets (P1 only). Never read P4 content. Never work around a 403. |
| text-only products (擎云, monitors, …) | 45 products with no images | Articles allowed with the image section marked 待确认 ("知识库无该型号图片"), never padded. Poster → refuse. |
| Pro | Pro vs Pro S are separate; KB disagrees on whether Pro's CPU is X90 Plus | Bare "Pro" → ambiguous, ask. Pro's `cpu` is in `Model.needs_human`: if the article would use it → NeedsHuman; otherwise exclude + 待确认. |
| 最 phrases | KB values contain 最高/最长 | Never output 最. Rephrase keeping the upper-bound meaning: 最高/最长/最大 + number → 可达 / 最多支持 / 支持 + number. |

Confusable groups: MateBook 14 鸿蒙版 vs 14 酷睿 Ultra (highest risk), Pro vs Pro S, D 16 vs D 16 SE (slug prefix!), D 14 vs D 16, Fold editions. Folder names are not canonical names (`GT 系列` = GT 14, `X系列` = X Pro 微绒典藏版).

---

## 2. Ownership (one owner per file; never edit another workstream's files)

| WS | Owner | Files |
|---|---|---|
| **P1 Data** | person with the ima account | `agent/ima_wrapper.py`, `agent/catalog.py`, `agent/retrieval.py`, `agent/platform_plan.py`, `config/model_aliases.yaml`, `ima-skill/` (restore, unmodified), `scripts/smoke_official.md`, `scripts/build_index.py`, `scripts/export_dev_cache.py`, `tests/test_catalog.py`, `tests/test_retrieval.py`, `tests/test_platform_plan.py`; deletes `agent/ima_client.py`; updates `scripts/explore_kb.py` import |
| **P2 Ledger** | | `agent/ledger.py`, `agent/units.py`, `config/units.yaml`, `tests/test_ledger.py`, `tests/test_units.py` |
| **P3 Checks** | | `agent/platform_rules.py`, `agent/checks/__init__.py`, `agent/checks/facts.py`, `agent/checks/compliance.py`, `agent/checks/conformance.py`, `config/banned_words.txt`, `config/claim_patterns.yaml`, `config/competitors.txt`, `config/number_whitelist.yaml`, `tests/test_checks_*.py`, `tests/test_platform_rules.py` |
| **P4 LLM stages** | | `agent/llm.py`, `agent/intake.py`, `agent/scenario.py`, `agent/reconcile.py`, `agent/writer.py`, `config/scenarios.yaml`, `prompts/*.md`, `tests/test_intake.py`, `tests/test_reconcile.py`, `tests/test_writer.py` |
| **P5 Integrator + UI** | lead | `agent/schemas.py`, `tests/fakes.py`, `docs/CONTRACTS.md`, `CLAUDE.md`, `agent/pipeline.py`, `agent/formatter.py`, `app.py`, `static/*`, `requirements.txt`, `README.md`, `docs/项目说明.md`, `tests/test_pipeline.py`, `tests/test_formatter.py`, `tests/test_e2e.py` |

Also:
- Each workstream may add its own synthetic fixtures under `tests/fixtures/<p1|p2|p3|p4|p5>/`. The shared DemoBook fixtures in `tests/fixtures/demobook-14*/` belong to P5.
- `agent/units.py` ships with a tested first version in the contracts commit so P3 isn't blocked. P2 owns it from then on and may extend it but must keep the signatures (`normalize`, `find_all`, `same_value`, `is_upper_bound`, `nfkc`).
- `Ledger.boundaries` holds the KB's 表达边界 lines (`{"category", "text", "source_title"}`): P2 fills it, P3 (8B) and P4 (writer prompt) read it.

Need a new dependency? Ask P5 to add it to `requirements.txt`.

---

## 3. Interfaces (signatures are binding)

Every function below has a fake in `tests/fakes.py` or can be replaced by one. Code against the signature, test with the fakes.

### P1 Data
```python
# agent/ima_wrapper.py  — calls `node ima-skill/ima_api.cjs <api> '<json>'` via subprocess
class ImaClient:
    def __init__(self, cache_dir: str = ".cache/ima", list_ttl: int = 86400, timeout: int = 30): ...
    call_log: list[dict]                       # {"api", "cached", "ts", "ok"} — no ids, no keys
    def call(self, api: str, body: dict, use_cache: bool = True) -> dict      # returns data; raises ImaError
    def find_kb(self, name: str) -> dict                                      # {"id", "name"}
    def list_folder(self, kb_id: str, folder_id: str | None = None) -> list[dict]
    def search(self, kb_id: str, query: str, max_pages: int = 3) -> list[dict]
    def media_info(self, media_id: str) -> dict                                # never cached
    def fetch_media(self, media_id: str) -> tuple[int | None, bytes | None]
    def fetch_text(self, media_id: str) -> str | None
    def status(self) -> dict    # {"kb_name", "connected": bool, "configured": bool, "index_status", "error"}
class ImaError(RuntimeError): code: int; msg: str; api: str

# agent/catalog.py
class Catalog:
    models: dict[str, Model]
    def resolve(self, query: str) -> ResolveResult
    def get(self, model_id: str) -> Model
    def siblings(self, model_id: str) -> list[Model]
def load_catalog(client: ImaClient | None = None, refresh: bool = False) -> Catalog

# agent/retrieval.py
def get_model_bundle(model_id: str, catalog: Catalog | None = None) -> ModelBundle
def fetch_image_bytes(media_id: str) -> bytes            # fresh get_media_info each time; small LRU in memory
def image_belongs_to(image: ImageRef, model: Model) -> bool   # the 3-signal rule, re-checked at export

# agent/platform_plan.py
def plan_images(bundle: ModelBundle, platform: str, strategy: Strategy) -> ImagePlan
```

### P2 Ledger
```python
# agent/units.py
def normalize(value_text: str) -> tuple[float | None, str, str]   # (norm_value, norm_unit, qualifier)
def same_value(a: Fact, b_value: float, b_unit: str) -> bool

# agent/ledger.py
def build_ledger(bundle: ModelBundle, llm=None, use_cache: bool = True) -> Ledger
def find_conflicts(facts: list[Fact]) -> list[Conflict]
def quote_ok(quote: str, value: str, source_text: str) -> bool
```

### P3 Checks
```python
# agent/platform_rules.py
PLATFORM_RULES: dict[str, dict]          # image range imported from schemas.PLATFORM_IMAGE_RANGE
WRITING_RULES: list[str]
def build_prompt_rules(platform: str) -> str          # Chinese rules text for the writer prompt
def check_post(post: Post, platform: str) -> list[CheckIssue]

# agent/checks/facts.py      (8A)
def check_facts(post: Post, ledger: Ledger, sibling_ledgers: dict[str, Ledger],
                variant: str | None = None, llm=None) -> CheckReport
# agent/checks/compliance.py (8B)
def check_compliance(post: Post, ledger: Ledger, task: Task, llm=None) -> CheckReport
# agent/checks/conformance.py (8C)
def check_conformance(post: Post, platform: str, plan: ImagePlan) -> CheckReport
# agent/checks/__init__.py
def strip_fact_tags(text: str) -> tuple[str, list[tuple[str, str]]]   # (clean text, [(sentence, fact_id)])
def run_all(post, ledger, sibling_ledgers, task, plan, llm=None) -> CheckReport   # 8A → 8B → 8C
```

### P4 LLM stages
```python
# agent/llm.py   — OpenAI-compatible; env LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_MODEL_FAST
class LLM:
    def chat_json(self, system: str, user: str, stage: str = "", fast: bool = False, **kw) -> dict
    def chat_text(self, system: str, user: str, stage: str = "", fast: bool = False, **kw) -> str

# agent/intake.py
def parse_task(text: str, catalog: Catalog, form: dict | None = None, llm=None) -> Task | Clarification
# agent/scenario.py
def analyze(task: Task, llm=None) -> ScenarioAnalysis
# agent/reconcile.py
def reconcile(task: Task, analysis: ScenarioAnalysis, ledger: Ledger, model: Model, llm=None) -> Strategy | NeedsHuman
# agent/writer.py
def write_post(task: Task, strategy: Strategy, ledger: Ledger, plan: ImagePlan, llm=None) -> Post
def rewrite(post: Post, issues: list[CheckIssue], task: Task, strategy: Strategy, ledger: Ledger,
            plan: ImagePlan, llm=None) -> Post        # targeted: only failing fields
```

### P5 Integrator
```python
# agent/pipeline.py
@dataclass
class Deps:   # dependency injection: real modules by default, fakes in tests
    catalog; get_bundle; build_ledger; plan_images; parse_task; analyze; reconcile; write_post; rewrite; run_checks; llm
def run(text: str, form: dict | None = None, deps: Deps | None = None,
        on_progress=None) -> RunResult | Clarification | NeedsHuman
def edit(prev: RunResult, instruction: str, deps: Deps | None = None) -> RunResult | Clarification | NeedsHuman

# agent/formatter.py
def render_report(r: RunResult) -> str        # 4 sections, headings = schemas.SECTION_HEADINGS
def render_publishable(post: Post) -> str     # [F#] stripped, hashtags only where allowed
```

Check loop (in `pipeline.run`): `run_checks` → if errors and loops < 2: `rewrite` → `run_checks` again. After 2 loops: remaining errors become red flags + 待确认.

---

## 4. Rules for parallel work

1. **Branch per workstream:** `feat/p1-data`, `feat/p2-ledger`, `feat/p3-checks`, `feat/p4-llm`, `feat/p5-ui`. Start from `main` after the contracts commit. Open a PR to `main`; P5 merges.
2. **Only touch your files** (table in §2). Need a change in someone else's file or in `schemas.py`? Message the owner.
3. **Test with fakes.** `pytest -q` must pass on your branch before every push. Never import another workstream's real module in your unit tests; use `tests/fakes.py`.
4. **ima quota:** only P1 calls ima. Everyone else uses fixtures. P1 may export a dev cache of real bundles for 3 models (`scripts/export_dev_cache.py` → `.cache/dev_bundles/`, gitignored) and send it privately to teammates for local realism tests. Never commit it.
5. **No KB text in git:** fixtures are synthetic (DemoBook). Never paste real KB text or images into tests, prompts, configs or docs.
6. **Secrets:** never print `.env`; never show Client ID or API Key characters anywhere (status shows "已配置").
7. **Push early:** push your branch at least every hour with passing tests.
8. **Merge order:** P1, P2 and P3 first (no LLM dependency), then P4, then P5 switches `Deps` from fakes to real modules and runs `tests/test_e2e.py`.
