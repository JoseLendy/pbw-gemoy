"""
Product catalog: the model index built from targeted ima folder listings (kb_structure.md §i.1, §i.2).

Build (scripts/build_index.py): root -> P1 -> 01-鸿蒙电脑 / 02-MateBook-Windows -> model folders ->
images/ (+ 商城款式图片/), plus P1/07-扩展产品目录 for text-only product names. Each image folder's
图片索引.csv is fetched once for canonical names and captions. Never walks the whole tree.

The index is persisted to .cache/index.json (gitignored). With the ima backend, load_catalog() reads
it first and only rebuilds on refresh=True or when it is missing. With the local mirror backends
(KB_BACKEND=local|hybrid, agent/kb_local.py) the index is rebuilt from the mirror on every load:
it costs no ima calls and takes well under a second.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import time
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from agent.ima_wrapper import KB_NAME, ROOT, ImaClient, ImaError, default_client, kb_backend
from agent.platform_plan import image_role
from agent.schemas import ImageRef, Model, ResolveResult

INDEX_PATH = ROOT / ".cache" / "index.json"
LOCAL_INDEX_PATH = ROOT / ".cache" / "index_local.json"     # built from the mirror; never mixed with ima's
ALIASES_PATH = ROOT / "config" / "model_aliases.yaml"
TEXT_CACHE = ROOT / ".cache" / "text"
TEXT_TTL = 6 * 3600
INDEX_MAX_AGE = 86400

ROUTES = {"01-": "harmonyos", "02-": "windows"}
IMAGE_KINDS = ("images", "商城款式图片")
CATALOG_PREFIX = "07-"
CONSUMER_CATALOG = "消费级 PC"
CSV_NAME, FACTS_NAME, CLAIMS_NAME = "图片索引.csv", "产品事实.md", "卖点与限制.md"
CSV_MODEL_COL = "产品型号"
CSV_CAPTION_COLS = ("官网图片说明", "画面说明")
SLUG_RE = re.compile(r"^(?:hwpc|vmall)_([a-z0-9-]+)_")

_CURRENT: "Catalog | None" = None


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def is_folder(item: dict) -> bool:
    return item.get("media_type") == 99 or str(item.get("media_id", "")).startswith("folder_")


def slug_of(title: str) -> str | None:
    m = SLUG_RE.match(title or "")
    return m.group(1) if m else None


def _src(item: dict, path: str) -> dict:
    return {"title": item.get("title", ""), "source_path": f"{path}/{item.get('title', '')}",
            "media_id": item.get("media_id", ""), "media_type": item.get("media_type", 0)}


def parse_image_csv(text: str) -> dict[str, dict]:
    """图片索引.csv -> {file name: {"model", "caption"}}. Column names vary between folders."""
    rows = {}
    for r in csv.DictReader(io.StringIO((text or "").lstrip("﻿"))):
        name = (r.get("文件名") or "").strip()
        if name:
            cap = next((r[c].strip() for c in CSV_CAPTION_COLS if (r.get(c) or "").strip()), "")
            rows[name] = {"model": (r.get(CSV_MODEL_COL) or "").strip(), "caption": cap}
    return rows


def cached_text(client, media_id: str, cache_dir: Path | None = None, ttl: int | None = None
                ) -> tuple[str | None, str, bool]:
    """(text, fetched_at, stale). Disk cache by media id hash (.cache/text/, gitignored);
    the expired copy is served when ima fails. Signed URLs are never stored, only the text.
    The local mirror backends read the file directly (nothing to cache)."""
    if getattr(client, "is_local", False):
        return client.fetch_text(media_id), _now(), False
    if media_id.startswith("local:"):     # a mirror-only item can't come from ima
        from agent.kb_local import LocalKB
        return LocalKB().fetch_text(media_id), _now(), False
    cache_dir = cache_dir or TEXT_CACHE
    ttl = TEXT_TTL if ttl is None else ttl
    cache_dir.mkdir(parents=True, exist_ok=True)
    cp = cache_dir / (hashlib.sha1(media_id.encode()).hexdigest() + ".json")
    cached = json.loads(cp.read_text("utf-8")) if cp.exists() else None
    if cached and time.time() - cp.stat().st_mtime < ttl:
        return cached["text"], cached["fetched_at"], False
    try:
        text = client.fetch_text(media_id)
    except ImaError:
        if cached:
            return cached["text"], cached["fetched_at"], True
        raise
    if text is None:
        return (cached["text"], cached["fetched_at"], True) if cached else (None, _now(), False)
    rec = {"text": text, "fetched_at": _now()}
    cp.write_text(json.dumps(rec, ensure_ascii=False), "utf-8")
    return text, rec["fetched_at"], False


def _text_only_id(name: str) -> str:
    s = unicodedata.normalize("NFKC", name).lower()
    return "txt-" + re.sub(r"[\s/（）()]+", "-", s).strip("-")


# ---------------------------------------------------------------------- build
def build_index(client: ImaClient, previous: dict | None = None) -> dict:
    """Targeted listings only. Unlistable folders and unreadable 图片索引.csv files are recorded
    in `unlisted` (status partial), never fatal. `previous` (the last saved index) supplies CSV rows
    when a fetch fails; that is marked stale."""
    unlisted, issues = [], []
    prev_csv = {p: rows for m in (previous or {}).get("models", []) if m for p, rows in m.get("csv", {}).items()}

    def ls(folder_id, path):
        try:
            return client.list_folder(kb["id"], folder_id)
        except ImaError as e:
            unlisted.append({"path": path, "code": e.code})
            return None

    def child(items, pred):
        return next((i for i in items or [] if is_folder(i) and pred(i.get("title", ""))), None)

    kb = client.find_kb(KB_NAME)
    top = ls(None, "/")
    p1 = child(top, lambda t: t.startswith("P1-"))
    if p1 is None:   # the KB root holds one folder named after the KB
        for f in [i for i in top or [] if is_folder(i)]:
            p1 = child(ls(f["media_id"], f["title"]), lambda t: t.startswith("P1-"))
            if p1:
                break
    if p1 is None:
        raise ImaError(-100, "知识库中未找到 P1-产品参数库", "get_knowledge_list")
    p1_path = p1["title"]
    p1_items = ls(p1["media_id"], p1_path) or []

    models, text_only, catalog_names = [], [], []
    for prefix, route in ROUTES.items():
        rf = child(p1_items, lambda t, p=prefix: t.startswith(p))
        if not rf:
            unlisted.append({"path": f"{p1_path}/{prefix}*", "code": 404})
            continue
        rpath = f"{p1_path}/{rf['title']}"
        for mf in [i for i in ls(rf["media_id"], rpath) or [] if is_folder(i)]:
            models.append(_build_model(client, ls, mf, f"{rpath}/{mf['title']}", route, issues,
                                       unlisted, prev_csv))

    cat = child(p1_items, lambda t: t.startswith(CATALOG_PREFIX))
    if cat:
        cpath = f"{p1_path}/{cat['title']}"
        for sub in [i for i in ls(cat["media_id"], cpath) or [] if is_folder(i)]:
            spath = f"{cpath}/{sub['title']}"
            for it in ls(sub["media_id"], spath) or []:
                t = it.get("title", "")
                if is_folder(it) or not t.endswith(".md"):
                    continue
                name = re.sub(r"^\d+-", "", t[:-3]).strip()
                if sub["title"] == CONSUMER_CATALOG:
                    catalog_names.append(name)
                else:
                    text_only.append({"model_id": _text_only_id(name), "canonical_name": name,
                                      "folder_name": sub["title"], "route": "text_only",
                                      "entry": _src(it, spath)})
    else:
        unlisted.append({"path": f"{p1_path}/{CATALOG_PREFIX}*", "code": 404})

    _check_slug_uniqueness(models, issues)
    models = [m for m in models if m]
    status = "partial" if unlisted else ("stale" if client.stale_served else "complete")
    return {"version": 1, "built_at": _now(), "status": status, "kb_name": kb["name"],
            "backend": getattr(client, "mode", "ima"),
            "unlisted": unlisted, "issues": issues, "models": models, "text_only": text_only,
            "catalog_names": catalog_names}


def _build_model(client, ls, mf, mpath, route, issues, unlisted, prev_csv) -> dict | None:
    items = ls(mf["media_id"], mpath) or []
    files = {i["title"]: i for i in items if not is_folder(i)}
    entry = {"folder_name": mf["title"], "folder_path": mpath, "route": route,
             "facts": _src(files[FACTS_NAME], mpath) if FACTS_NAME in files else None,
             "claims": _src(files[CLAIMS_NAME], mpath) if CLAIMS_NAME in files else None,
             "images": [], "csv": {}, "image_index_ok": True}

    def load_csv(item, key):
        try:
            txt, _, stale = cached_text(client, item["media_id"])
            client.stale_served |= stale
        except ImaError as e:
            txt = None
            if key in prev_csv:
                entry["csv"][key] = prev_csv[key]
                client.stale_served = True
                issues.append({"model": mf["title"], "issue": f"图片索引读取失败 code {e.code}，使用上次索引"})
                return
            unlisted.append({"path": f"{key}/{CSV_NAME}", "code": e.code})
        entry["csv"][key] = parse_image_csv(txt) if txt else {}

    if CSV_NAME in files:
        load_csv(files[CSV_NAME], f"{mpath}/images")
    for sub in [i for i in items if is_folder(i) and i.get("title") in IMAGE_KINDS]:
        spath = f"{mpath}/{sub['title']}"
        sitems = ls(sub["media_id"], spath) or []
        for it in sitems:
            if is_folder(it):
                continue
            if it.get("title") == CSV_NAME:
                load_csv(it, spath)
            elif it.get("media_type") == 9:
                entry["images"].append({"media_id": it["media_id"], "title": it["title"],
                                        "source_path": spath, "folder_kind": sub["title"]})

    slugs = Counter(slug_of(i["title"]) for i in entry["images"])
    if not slugs:
        issues.append({"model": mf["title"], "issue": "无图片条目"})
        return None
    if len(slugs) > 1 or None in slugs:
        entry["image_index_ok"] = False
        issues.append({"model": mf["title"], "issue": f"文件夹内有多个或无法解析的图片前缀: {sorted(map(str, slugs))}"})
    entry["model_id"] = slugs.most_common(1)[0][0]

    names = Counter(r["model"] for rows in entry["csv"].values() for r in rows.values() if r["model"])
    if not names:
        issues.append({"model": mf["title"], "issue": "图片索引.csv 无产品型号，型号已跳过"})
        return None
    if len(names) > 1:
        issues.append({"model": mf["title"], "issue": "图片索引.csv 中出现多个产品型号，非多数型号的图片将被排除"})
    entry["canonical_name"] = names.most_common(1)[0][0]
    for im in entry["images"]:
        row = entry["csv"].get(im["source_path"], {}).get(im["title"], {})
        im["caption"] = row.get("caption", "")
    return entry


def _check_slug_uniqueness(models, issues):
    seen = Counter(m["model_id"] for m in models if m)
    for m in models:
        if m and seen[m["model_id"]] > 1:
            m["image_index_ok"] = False
            issues.append({"model": m["folder_name"], "issue": f"图片前缀 {m['model_id']} 不唯一，该型号不提供图片"})


# ---------------------------------------------------------------------- tokens
_SPLIT_TERMS = sorted(["鸿蒙版", "鸿蒙", "酷睿", "华为", "擎云", "非凡大师", "企业版", "典藏版",
                       "笔记本电脑", "笔记本", "电脑"], key=len, reverse=True)
_SYNONYMS = {"harmonyos": "鸿蒙", "鸿蒙版": "鸿蒙", "windows": "酷睿", "win": "酷睿"}
_FILLER = {"huawei", "华为", "版", "系列", "款", "新款", "笔记本", "电脑", "笔记本电脑", "的", "和"}
_ROUTE_TOKEN = {"harmonyos": "鸿蒙", "windows": "酷睿"}
_VARIANT_RE = re.compile(r"\d+\s*(?:gb|tb)\b")
_TOKEN_RE = re.compile(r"[a-z]+|\d+(?:\.\d+)?|[㐀-鿿]+")


def tokens(text: str, vocab: set[str] | None = None) -> frozenset[str]:
    """NFKC, lower case, drop HUAWEI/华为 and fillers, OS words as their own tokens. Never substrings."""
    s = unicodedata.normalize("NFKC", text or "").lower()
    s = _VARIANT_RE.sub(" ", s)
    for t in _SPLIT_TERMS:
        s = s.replace(t, f" {t} ")
    out = []
    for tok in _TOKEN_RE.findall(s):
        if vocab and tok.isascii() and tok.isalpha() and tok not in vocab:
            out += _segment(tok, vocab)
        else:
            out.append(tok)
    out = [_SYNONYMS.get(t, t) for t in out]
    return frozenset(t for t in out if t not in _FILLER)


def _segment(word: str, vocab: set[str]) -> list[str]:
    """Split glued Latin words ("matebookpro") using catalog vocabulary; unchanged if it can't."""
    parts, i = [], 0
    while i < len(word):
        j = next((j for j in range(len(word), i, -1) if word[i:j] in vocab), None)
        if j is None:
            return [word]
        parts.append(word[i:j])
        i = j
    return parts


# ---------------------------------------------------------------------- catalog
class Catalog:
    def __init__(self, index: dict, aliases_cfg: dict | None = None, client: ImaClient | None = None):
        self.index, self.client = index, client
        cfg = aliases_cfg if aliases_cfg is not None else _load_aliases()
        cfg_models = (cfg or {}).get("models") or {}
        self.unlisted = [u["path"] for u in index.get("unlisted", [])]
        self.status = index.get("status", "complete")
        try:
            age = time.time() - datetime.fromisoformat(index["built_at"]).timestamp()
            if age > INDEX_MAX_AGE and self.status == "complete":
                self.status = "stale"
        except (KeyError, ValueError):
            pass

        self.entries: dict[str, dict] = {}
        self.models: dict[str, Model] = {}
        self._listed: dict[str, dict] = {}   # media_id -> image record as listed
        image_models = [e for e in index.get("models", []) if e]
        for e in image_models:
            self.entries[e["model_id"]] = e
            for im in e["images"]:
                self._listed[im["media_id"]] = im
        for e in image_models:
            c = cfg_models.get(e["model_id"], {})
            catalog_aliases = [n for n in index.get("catalog_names", [])
                               if tokens(n) == tokens(e["canonical_name"])]
            aliases = _dedupe([*c.get("aliases", []), e["folder_name"], *catalog_aliases],
                              exclude=e["canonical_name"])
            m = Model(model_id=e["model_id"], canonical_name=e["canonical_name"], folder_name=e["folder_name"],
                      route=e["route"], aliases=aliases,
                      siblings=[s for s in c.get("siblings", []) if s != e["model_id"]],
                      needs_human=list(c.get("needs_human", [])))
            self.models[m.model_id] = m
        for m in self.models.values():
            m.siblings = [s for s in m.siblings if s in self.models]
            m.has_images = any(self.belongs(self._ref(im, m), m) for im in self.entries[m.model_id]["images"])
        for t in index.get("text_only", []):
            self.entries[t["model_id"]] = t
            self.models[t["model_id"]] = Model(model_id=t["model_id"], canonical_name=t["canonical_name"],
                                               folder_name=t["folder_name"], route="text_only", has_images=False)

        vocab_src = [n for m in self.models.values() for n in (m.canonical_name, *m.aliases)]
        self._vocab = {t for n in vocab_src for t in tokens(n) if t.isascii() and t.isalpha()}
        self._name_sets: dict[str, list[frozenset]] = {}
        self._canonical_sets: dict[str, set[frozenset]] = {}
        for m in self.models.values():
            base = tokens(m.canonical_name, self._vocab)
            rt = _ROUTE_TOKEN.get(m.route)
            self._canonical_sets[m.model_id] = {base, base | {rt}} if rt else {base}
            sets = []
            for n in (m.canonical_name, *m.aliases):
                base = tokens(n, self._vocab)
                if base:
                    sets.append(base)
                    rt = _ROUTE_TOKEN.get(m.route)
                    if rt:
                        sets.append(base | {rt})
            self._name_sets[m.model_id] = sets

    # ------------------------------------------------------------ images
    def _ref(self, im: dict, model: Model) -> ImageRef:
        return ImageRef(media_id=im["media_id"], title=im["title"], source_path=im["source_path"],
                        model_id=slug_of(im["title"]) or "", caption=im.get("caption", ""),
                        folder_kind=im["folder_kind"], role=image_role(im["title"], im.get("caption", "")))

    def images_for(self, model_id: str) -> list[ImageRef]:
        """Images that pass the 3-signal rule, in KB order (by the NN number in the file name)."""
        m = self.models[model_id]
        if m.route == "text_only":
            return []
        refs = [self._ref(im, m) for im in self.entries[model_id]["images"]]
        return sorted([r for r in refs if self.belongs(r, m)], key=lambda r: (r.folder_kind != "images", _nn(r.title)))

    def is_listed_image(self, media_id: str) -> bool:
        return media_id in self._listed

    def belongs(self, image: ImageRef, model: Model) -> bool:
        """kb_structure §i.4: folder AND slug AND index row must all agree; otherwise False."""
        e = self.entries.get(model.model_id)
        if not e or model.route == "text_only" or not e.get("image_index_ok", False):
            return False
        rec = self._listed.get(image.media_id)
        if rec is None:                                    # not returned by any listing (e.g. joint table)
            return False
        # 1. folder: listed inside M's own subtree, and the ref agrees with the listing
        if rec["source_path"] != f"{e['folder_path']}/{rec['folder_kind']}" or rec["folder_kind"] not in IMAGE_KINDS:
            return False
        if image.source_path != rec["source_path"] or image.title != rec["title"]:
            return False
        # 2. slug: exactly equal, never prefix
        if slug_of(rec["title"]) != model.model_id or image.model_id != model.model_id:
            return False
        # 3. index row in that folder's 图片索引.csv; a named model must be the canonical name
        row = e["csv"].get(rec["source_path"], {}).get(rec["title"])
        return row is not None and row["model"] in ("", model.canonical_name)

    # ------------------------------------------------------------ lookup
    def get(self, model_id: str) -> Model:
        return self.models[model_id]

    def siblings(self, model_id: str) -> list[Model]:
        return [self.models[s] for s in self.models[model_id].siblings if s in self.models]

    def resolve(self, query: str) -> ResolveResult:
        q = tokens(query, self._vocab)
        if not q:
            return ResolveResult("not_found", candidates=self._nearest(q), reason="未识别到型号名称")
        exact, contains = [], []
        for mid, sets in self._name_sets.items():
            if any(q == s for s in sets):
                exact.append(mid)
            if any(q <= s for s in sets):
                contains.append(mid)
        # The full official name is unambiguous even when a sibling's name extends it
        # ("MateBook D 16 2024" vs "MateBook D 16 SE 版 2024"). Folder names and aliases are not.
        canonical = [mid for mid in exact if q in self._canonical_sets[mid]]
        if len(canonical) == 1:
            exact = contains = canonical
        if len(contains) == 1 and exact == contains:
            m = self.models[exact[0]]
            if m.route == "text_only":
                return ResolveResult("text_only", model=m, reason="知识库只有该产品的文字资料，没有图片")
            return ResolveResult("resolved", model=m)
        if contains:
            ranked = sorted(contains, key=lambda mid: (mid not in exact, self.models[mid].route == "text_only",
                                                       min(len(s - q) for s in self._name_sets[mid] if q <= s)))
            cands = [self.models[mid] for mid in ranked]
            if len(cands) == 1:
                reason = "名称不完整，请确认是否为该型号"
            elif all(c.route == "text_only" for c in cands):
                reason = f"名称匹配 {len(cands)} 个仅有文字资料的产品，请选择具体型号"
            else:
                reason = f"名称同时匹配 {len(cands)} 个型号，请选择"
            return ResolveResult("ambiguous", candidates=cands, reason=reason)
        return ResolveResult("not_found", candidates=self._nearest(q), reason="知识库中未找到该型号")

    def _nearest(self, q: frozenset, n: int = 3) -> list[Model]:
        def score(mid):
            j = max((len(q & s) / len(q | s) for s in self._name_sets[mid] if s), default=0)
            return (-j, self.models[mid].route == "text_only", mid)
        return [self.models[mid] for mid in sorted(self._name_sets, key=score)[:n]]


def _nn(title: str) -> int:
    m = re.search(r"_(\d{2})(?:_[0-9a-f]+)?\.\w+$", title)
    return int(m.group(1)) if m else 99


def _dedupe(names, exclude=""):
    out, seen = [], {exclude}
    for n in names:
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


def _load_aliases() -> dict:
    try:
        return yaml.safe_load(ALIASES_PATH.read_text("utf-8")) or {}
    except FileNotFoundError:
        return {}


# ---------------------------------------------------------------------- load
def save_index(index: dict, path: Path | None = None) -> None:
    path = path or INDEX_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, ensure_ascii=False, indent=1), "utf-8")


def load_catalog(client: ImaClient | None = None, refresh: bool = False) -> Catalog:
    """Cached index first; rebuild only on refresh=True or when the cache is missing.
    A failed rebuild falls back to the last good index, marked stale."""
    global _CURRENT
    if _CURRENT is not None and not refresh and (client is None or _CURRENT.client is client):
        return _CURRENT
    if client is None and kb_backend() != "ima":
        client = default_client()
    if getattr(client, "is_local", False):
        index = build_index(client)                 # from the mirror: zero listing calls
        save_index(index, LOCAL_INDEX_PATH)
    elif not refresh and INDEX_PATH.exists():
        index = json.loads(INDEX_PATH.read_text("utf-8"))
    else:
        client = client or default_client()
        previous = json.loads(INDEX_PATH.read_text("utf-8")) if INDEX_PATH.exists() else None
        try:
            index = build_index(client, previous)
            save_index(index)
        except ImaError:
            if not INDEX_PATH.exists():
                raise
            index = json.loads(INDEX_PATH.read_text("utf-8"))
            index["status"] = "stale"
    cat = Catalog(index, client=client)
    if client is not None:
        client.index_status = cat.status
    _CURRENT = cat
    return cat


def current_catalog() -> Catalog:
    return _CURRENT or load_catalog()


def set_current(catalog: Catalog | None) -> None:
    """Tests and the pipeline can inject a catalog."""
    global _CURRENT
    _CURRENT = catalog
