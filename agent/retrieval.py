"""
Step 3 retrieval: the per-model bundle (facts, claims, images, sources) from the catalog.

- facts_text = 产品事实.md with the trailing leave-site banner stripped; claims_text = 卖点与限制.md.
- images = only those passing the 3-signal rule (kb_structure §i.4). Price cards are never included.
- Text is cached in .cache/text/ (gitignored) for TEXT_TTL, with a stale-on-error fallback.
- Image bytes: a fresh get_media_info per fetch (signed URLs are never stored), small in-memory LRU.
- KB_BACKEND=local|hybrid (agent/kb_local.py): text and image bytes come from the local mirror.
  hybrid adds, per bundle, one live search (model canonical name) and a get_media_info check of the
  2 docs; each image actually fetched for an output is checked the same way. source_origin() tells
  whether a source was confirmed live ("ima") or is mirror-only ("本地镜像").
"""
from __future__ import annotations

import re
from collections import OrderedDict

from agent.catalog import TEXT_CACHE, TEXT_TTL, Catalog, cached_text, current_catalog
from agent.ima_wrapper import ImaClient, ImaError, default_client
from agent.kb_local import LocalKB, is_local_id
from agent.schemas import ImageRef, Model, ModelBundle, SourceRecord

IMAGE_LRU_SIZE = 30

_BANNER_START = re.compile(r"^\s*即将离开\s*[\w.-]+\.[a-z]{2,}\s*$")
_BANNER_END = "继续访问"
_images: "OrderedDict[str, bytes]" = OrderedDict()


def strip_banner(text: str) -> str:
    """Drop the scraped leave-site dialog at the end of a spec page (site chrome, not product facts)."""
    lines = (text or "").splitlines()
    for i in range(len(lines) - 1, max(-1, len(lines) - 15), -1):
        if _BANNER_START.match(lines[i]) and _BANNER_END in "\n".join(lines[i:]):
            return "\n".join(lines[:i]).rstrip() + "\n"
    return text


def _client(catalog: Catalog) -> ImaClient:
    return catalog.client or default_client()


def _fetch_text(client: ImaClient, src: dict) -> tuple[str | None, str, bool]:
    return cached_text(client, src["media_id"], TEXT_CACHE, TEXT_TTL)


def _record(src: dict, fetched_at: str) -> SourceRecord:
    return SourceRecord(title=src["title"], source_path=src["source_path"], media_id=src["media_id"],
                        media_type=int(src.get("media_type") or 0), fetched_at=fetched_at)


def get_model_bundle(model_id: str, catalog: Catalog | None = None) -> ModelBundle:
    cat = catalog or current_catalog()
    model = cat.get(model_id)
    entry = cat.entries[model_id]
    client = _client(cat)
    status, any_stale = cat.status, False

    def load(src):
        nonlocal any_stale
        if not src:
            return "", None
        text, ts, stale = _fetch_text(client, src)
        any_stale |= stale
        return text or "", _record(src, ts)

    if model.route == "text_only":
        facts, fs = load(entry.get("entry"))
        sources = [fs] if fs else []
        return ModelBundle(model=model, facts_text=facts, claims_text="", images=[], sources=sources,
                           facts_source=fs, index_status="stale" if any_stale else status,
                           unlisted=list(cat.unlisted))

    facts, fs = load(entry.get("facts"))
    claims, cs = load(entry.get("claims"))
    images = [im for im in cat.images_for(model_id) if cat.belongs(im, model)]
    if hasattr(client, "live_search"):              # hybrid: cached, falls back to the mirror on any error
        client.live_search(model.canonical_name)
        for src in (fs, cs):
            if src:
                client.confirm(src.media_id)
    return ModelBundle(model=model, facts_text=strip_banner(facts), claims_text=claims, images=images,
                       sources=[s for s in (fs, cs) if s], facts_source=fs, claims_source=cs,
                       index_status="stale" if any_stale and status == "complete" else status,
                       unlisted=list(cat.unlisted))


def source_origin(source_path: str, catalog: Catalog | None = None) -> str:
    """"ima" if the source was confirmed live, "本地镜像" if it comes from the local mirror only.
    For an image pass f"{image.source_path}/{image.title}". Shows no ids."""
    client = _client(catalog or current_catalog())
    return client.origin(source_path) if hasattr(client, "origin") else "ima"


def image_belongs_to(image: ImageRef, model: Model) -> bool:
    """The 3-signal rule (kb_structure §i.4), re-checked at export against the current catalog."""
    return current_catalog().belongs(image, model)


def fetch_image_bytes(media_id: str) -> bytes:
    """Only images the catalog listed can be fetched (no arbitrary KB media through the app)."""
    if media_id in _images:
        _images.move_to_end(media_id)
        return _images[media_id]
    cat = current_catalog()
    if not cat.is_listed_image(media_id):
        raise ValueError("该图片不在产品索引中")
    client = _client(cat)
    if is_local_id(media_id) and not getattr(client, "is_local", False):
        client = LocalKB()                            # mirror-only item: never sent to ima
    _, raw = client.fetch_media(media_id)
    if not raw:
        raise ImaError(-100, "图片获取失败", "get_media_info")
    _images[media_id] = raw
    while len(_images) > IMAGE_LRU_SIZE:
        _images.popitem(last=False)
    return raw
