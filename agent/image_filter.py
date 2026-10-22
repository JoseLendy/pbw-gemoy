"""
Which KB images a post may show (used by agent.platform_plan before any image is chosen).

    usable(images) -> list[ImageRef]      # denylisted images removed; a picture saved twice is kept once
    is_denied(media_id) / media_hash(media_id) / same_picture(a, b)

1. Manual denylist: config/image_denylist.yaml lists the first 16 hex characters of sha256(media_id) only,
   with a generic reason (16, so the secrets scan never sees a key-like token). No raw media id
   (it embeds a KB id), no file name and no caption is ever committed.
2. Same picture: the KB stores some pictures twice under different names (re-encoded or colour-graded copies).
   Two images are the same picture when their 8x8 difference hash differs in at most 3 bits AND their coarse
   colours are close (colourways of one product shot differ in colour, so they stay separate). The pixels come
   from the local mirror (KB_LOCAL_DIR); without a mirror file an image is simply not compared. Never calls ima.
"""
from __future__ import annotations

import hashlib
import logging
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Optional

from agent.schemas import ImageRef

log = logging.getLogger(__name__)

DENYLIST = "image_denylist.yaml"
MAX_HASH_BITS = 3          # calibrated on the 2026-10 KB: copies 0-2 bits; different shots / colourways 5+
MAX_COLOUR_DIFF = 64       # coarse 4x4 colour, per channel: colour-graded copies <= 48; colourways >= 95

_fingerprints: dict[str, Optional[tuple[int, tuple]]] = {}

__all__ = ["usable", "is_denied", "media_hash", "same_picture", "fingerprint", "clear_cache"]


HASH_CHARS = 16


def media_hash(media_id: str) -> str:
    return hashlib.sha256((media_id or "").encode("utf-8")).hexdigest()[:HASH_CHARS]


@lru_cache(maxsize=1)
def _denied_hashes() -> frozenset:
    from agent.checks import load_yaml
    try:
        rows = (load_yaml(DENYLIST) or {}).get("images") or []
    except Exception as e:  # noqa: BLE001 - a broken denylist must be visible, not silently empty
        log.warning("image denylist unreadable: %s", e)
        return frozenset()
    return frozenset(str(r.get("id_hash", "")).lower() for r in rows if isinstance(r, dict))


def is_denied(media_id: str) -> bool:
    return media_hash(media_id) in _denied_hashes()


def _mirror_file(im: ImageRef) -> Optional[Path]:
    try:
        from agent.kb_local import local_dir
        p = local_dir() / (im.source_path or "").strip("/") / im.title
    except Exception:  # noqa: BLE001
        return None
    return p if p.is_file() else None


def fingerprint(im: ImageRef) -> Optional[tuple[int, tuple]]:
    """(difference hash, coarse colours) of the mirror file, or None if there is no readable file."""
    if im.media_id in _fingerprints:
        return _fingerprints[im.media_id]
    fp = None
    path = _mirror_file(im)
    if path is not None:
        try:
            from PIL import Image
            with Image.open(path) as raw:
                rgba = raw.convert("RGBA")
            flat = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            flat.alpha_composite(rgba)
            rgb = flat.convert("RGB")
            g = rgb.convert("L").resize((9, 8), Image.LANCZOS)
            px = [g.getpixel((c, r)) for r in range(8) for c in range(9)]
            bits = sum(1 << k for k, (r, c) in enumerate((r, c) for r in range(8) for c in range(8))
                       if px[r * 9 + c] > px[r * 9 + c + 1])
            small = rgb.resize((4, 4), Image.LANCZOS)
            colours = tuple(small.getpixel((c, r)) for r in range(4) for c in range(4))
            fp = (bits, colours)
        except Exception as e:  # noqa: BLE001 - an unreadable image is just not compared
            log.debug("fingerprint failed for an image: %s", type(e).__name__)
    _fingerprints[im.media_id] = fp
    return fp


def same_picture(a: ImageRef, b: ImageRef) -> bool:
    fa, fb = fingerprint(a), fingerprint(b)
    if fa is None or fb is None:
        return False
    if bin(fa[0] ^ fb[0]).count("1") > MAX_HASH_BITS:
        return False
    return max(abs(x - y) for p, q in zip(fa[1], fb[1]) for x, y in zip(p, q)) <= MAX_COLOUR_DIFF


def usable(images: Iterable[ImageRef]) -> list[ImageRef]:
    """Denylisted images dropped; of several copies of one picture only the first (KB order) is kept."""
    kept: list[ImageRef] = []
    for im in images:
        if is_denied(im.media_id):
            continue
        if any(same_picture(im, k) for k in kept):
            continue
        kept.append(im)
    return kept


def clear_cache() -> None:
    _fingerprints.clear()
    getattr(_denied_hashes, "cache_clear", lambda: None)()     # tests may replace it with a plain function
