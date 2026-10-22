"""
Export the whole post (store tab 「复制文案」/「下载发布包」, 手机发布 view).

    wechat_text(post)                       # the text staff paste: title merged into the opening line, no tags
    publish_zip(post, store_id, date, fetch)  -> (file name, zip bytes)

The zip <store>-<date>-<platform>.zip holds 文案.txt (exactly wechat_text) and the post's own images numbered
in posting order (1.jpg, 2.jpg …); a 公众号 post also gets 文章.md with headings. It is one post's package, not a
bulk export of the KB: only the 1–9 images this post uses, fetched one by one through the read-only client.
"""
from __future__ import annotations

import io
import re
import zipfile
from typing import Callable, Optional

from agent.formatter import HASHTAG_PLATFORMS
from agent.schemas import PLATFORM_LABELS, Post

_TAG = re.compile(r"\s*\[F\d+\]")
_LEAD = re.compile(r"^([^。！？!?：:\n]{2,14})[：:]\s*(.+)$", re.S)
_END_PUNCT = "。！？!?…～~"


def _clean(text: str) -> str:
    return _TAG.sub("", text or "").strip()


def wechat_text(post: Post) -> str:
    """WeChat-ready: the title merged into the opening line, then the paragraphs; no fact tags, no internal
    labels. 小红书 keeps its #话题 line (they are part of that post)."""
    paras = [p for p in (_clean(x) for x in [post.intro, *post.body, post.cta]) if p]
    title = _clean(post.title)
    if title:
        joiner = "" if title[-1] in _END_PUNCT else "｜"
        paras = [title + joiner + paras[0], *paras[1:]] if paras else [title]
    text = "\n\n".join(paras)
    if post.platform in HASHTAG_PLATFORMS and post.tags:
        text += "\n\n" + " ".join(f"#{t.lstrip('#')}" for t in post.tags)
    return text


def article_md(post: Post) -> str:
    """公众号 文章.md: H1 title, the intro, body paragraphs (a short 「小标题：」 lead becomes an H2), images
    at their planned positions as 1.jpg, 2.jpg … (same numbering as the zip), then the CTA."""
    lines = [f"# {_clean(post.title)}", ""] if post.title else []
    if post.intro:
        lines += [_clean(post.intro), ""]
    imgs = {i + 1: im for i, im in enumerate(post.images)}
    after = {}
    for n, im in imgs.items():
        m = re.search(r"第(\d+)段后", im.position or "")
        after.setdefault(int(m.group(1)) if m else (0 if "标题" in (im.position or "") else 999), []).append(n)
    for n in after.get(0, []):
        lines += [f"![]({n}.jpg)", ""]
    for k, para in enumerate(post.body, start=1):
        p = _clean(para)
        m = _LEAD.match(p)
        lines += ([f"## {m.group(1)}", "", m.group(2).strip(), ""] if m else [p, ""])
        for n in after.get(k, []):
            lines += [f"![]({n}.jpg)", ""]
    for n in after.get(999, []):
        lines += [f"![]({n}.jpg)", ""]
    if post.cta:
        lines += [_clean(post.cta), ""]
    return "\n".join(lines).strip() + "\n"


def _jpeg(data: bytes) -> Optional[bytes]:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            rgba = im.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.split()[-1])
        out = io.BytesIO()
        flat.save(out, "JPEG", quality=90)
        return out.getvalue()
    except Exception:  # noqa: BLE001 - an unreadable image is left out, never a broken file
        return None


def image_files(post: Post, fetch: Optional[Callable[[str], bytes]]) -> list[tuple[str, bytes]]:
    """[(n.jpg, bytes)] in posting order; images that cannot be fetched are skipped (numbering stays dense)."""
    out: list[tuple[str, bytes]] = []
    for im in post.images:
        try:
            data = fetch(im.media_id) if fetch else None
        except Exception:  # noqa: BLE001
            data = None
        jpg = _jpeg(data) if data else None
        if jpg:
            out.append((f"{len(out) + 1}.jpg", jpg))
    return out


SHORT_LABELS = {"moments": "朋友圈", "xiaohongshu": "小红书", "wechat_article": "公众号"}


def zip_name(store_id: str, date: str, platform: str) -> str:
    return f"{store_id}-{date}-{SHORT_LABELS.get(platform) or PLATFORM_LABELS.get(platform, platform)}.zip"


def publish_zip(post: Post, store_id: str, date: str, fetch: Optional[Callable[[str], bytes]],
                text: Optional[str] = None) -> tuple[str, bytes]:
    """text: the final text (edited if edited); defaults to wechat_text(post)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("文案.txt", text if text is not None else wechat_text(post))
        for name, data in image_files(post, fetch):
            z.writestr(name, data)
        if post.platform == "wechat_article":
            z.writestr("文章.md", article_md(post))
    return zip_name(store_id, date, post.platform), buf.getvalue()


__all__ = ["wechat_text", "article_md", "image_files", "publish_zip", "zip_name"]
