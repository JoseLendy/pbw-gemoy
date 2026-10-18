"""
Local KB mirror backends (KB_BACKEND=local|hybrid). The ima daily quota (code 220021) blocks
development, so the data layer can read the organizers' source package, unzipped (top folder
stripped) into KB_LOCAL_DIR (default kb_snapshot/kb_v7, gitignored, never committed).

The mirror was verified against the live ima walk (kb_snapshot/tree.json): every file ima lists
exists in the mirror at the same KB path with identical bytes. The mirror also holds folders and
files ima does not list; the ones we must not use are hidden here (EXCLUDED_*), so no caller can
reach them:
- P4-价格政策库（机密）/ (never extracted, and refused even if present),
- the 3 statistics json files that are not in ima,
- P6-营销素材库/04-图片/02-华为商城电脑专区素材/ (images the joint table points at, not ima items).

Both backends quack like agent.ima_wrapper.ImaClient (find_kb, list_folder, fetch_text,
fetch_media, status, call_log ...), so agent/catalog.py and agent/retrieval.py work unchanged.

Media ids: kb_snapshot/tree.json (today's walk) -> .cache/ima_ids.json {kb path: ima media_id}.
Items ima doesn't know get "local:<kb path>". Ids are internal; never shown.

- LocalKB: zero ima calls. status() mode "本地镜像".
- HybridKB: index, text and images from the mirror (zero listing calls), plus a few live ima calls,
  each cached and falling back to the mirror on ANY error (incl. 220021): find_kb once at startup,
  one search_knowledge per model query (24 h disk cache in ImaClient), and get_media_info only for
  the docs and images actually used (yes/no cached 24 h in .cache/ima_confirm.json, never the URL).
  Each source's origin ("ima" = confirmed live, "本地镜像" = mirror only) is kept in `origins`
  and in the `origin` field of this backend's call_log.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from agent.ima_wrapper import KB_NAME, ROOT, ImaError, _configured

LOCAL_PREFIX = "local:"
ORIGIN_IMA, ORIGIN_LOCAL = "ima", "本地镜像"
MODE_LOCAL, MODE_HYBRID = "本地镜像", "ima + 本地镜像"

DEFAULT_LOCAL_DIR = "kb_snapshot/kb_v7"
TREE_PATH = ROOT / "kb_snapshot" / "tree.json"
IDS_PATH = ROOT / ".cache" / "ima_ids.json"
CONFIRM_PATH = ROOT / ".cache" / "ima_confirm.json"
CONFIRM_TTL = 86400
TREE_ROOT = "/" + KB_NAME            # tree.json paths start with the KB's own root folder

EXCLUDED_TOP_PREFIX = "P4-"          # P4-价格政策库（机密）: never read
EXCLUDED_FILES = {"价格采集统计.json", "全库统计.json", "重点型号构建明细.json"}
EXCLUDED_DIRS = {"P6-营销素材库/04-图片/02-华为商城电脑专区素材", "__MACOSX"}

MEDIA_TYPES = {".md": 7, ".csv": 5, ".png": 9, ".jpg": 9, ".jpeg": 9, ".webp": 9, ".gif": 9}
FOLDER = 99


def local_dir() -> Path:
    p = Path(os.getenv("KB_LOCAL_DIR") or DEFAULT_LOCAL_DIR)
    return p if p.is_absolute() else ROOT / p


def is_local_id(media_id: str) -> bool:
    return str(media_id or "").startswith(LOCAL_PREFIX)


def excluded(kb_path: str) -> bool:
    parts = [p for p in (kb_path or "").split("/") if p]
    if not parts:
        return False
    if parts[0].startswith(EXCLUDED_TOP_PREFIX) or parts[-1] in EXCLUDED_FILES:
        return True
    if any(p.startswith(".") for p in parts):
        return True
    joined = "/".join(parts)
    return any(joined == d or joined.startswith(d + "/") for d in EXCLUDED_DIRS) or parts[0] in EXCLUDED_DIRS


def build_id_map(tree_path: Path = TREE_PATH, out_path: Path | None = IDS_PATH) -> dict[str, str]:
    """{kb path: ima media_id} from the saved ima walk. Excluded paths are never mapped."""
    if not tree_path.exists():
        return {}
    ids = {}
    for n in json.loads(tree_path.read_text("utf-8")):
        path, mid = n.get("path", ""), n.get("id") or (n.get("raw") or {}).get("media_id")
        if not path.startswith(TREE_ROOT + "/") or not mid:
            continue
        kb_path = path[len(TREE_ROOT) + 1:]
        if not excluded(kb_path):
            ids[kb_path] = mid
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(ids, ensure_ascii=False, indent=0), "utf-8")
    return ids


def load_id_map(ids_path: Path = IDS_PATH, tree_path: Path = TREE_PATH) -> dict[str, str]:
    if ids_path.exists() and (not tree_path.exists() or ids_path.stat().st_mtime >= tree_path.stat().st_mtime):
        return json.loads(ids_path.read_text("utf-8"))
    return build_id_map(tree_path, ids_path)


class LocalKB:
    """Read-only view of the mirror, addressed by KB path ("P1-产品参数库/01-鸿蒙电脑/..."). Zero ima calls."""

    is_local = True
    mode = MODE_LOCAL

    def __init__(self, root: str | Path | None = None, ids: dict[str, str] | None = None):
        self.root = Path(root) if root else local_dir()
        if not self.root.is_absolute():
            self.root = ROOT / self.root
        self.root = self.root.resolve()
        if not self.root.is_dir():
            raise ImaError(-100, f"本地镜像目录不存在：{self.root.name}，请先解压知识库镜像", "local")
        self.ids = dict(load_id_map() if ids is None else ids)
        self._paths = {mid: p for p, mid in self.ids.items()}
        self.call_log: list[dict] = []     # stays empty: no ima calls
        self.live_calls = 0
        self.stale_served = False
        self.quota_exhausted = False
        self.kb_name = KB_NAME
        self.connected = False
        self.index_status = "unknown"
        self.last_error = ""

    # ------------------------------------------------------------ paths and ids
    def _fs(self, kb_path: str) -> Path | None:
        """Filesystem path inside the mirror, or None if excluded / outside the root."""
        kb_path = (kb_path or "").strip("/")
        if excluded(kb_path):
            return None
        p = (self.root / kb_path).resolve()
        if p != self.root and self.root not in p.parents:
            return None
        return p

    def media_id(self, kb_path: str) -> str:
        return self.ids.get(kb_path) or f"{LOCAL_PREFIX}{kb_path}"

    def path_of(self, media_id: str) -> str | None:
        if is_local_id(media_id):
            path = media_id[len(LOCAL_PREFIX):]
        else:
            path = self._paths.get(media_id)
        return None if path is None or excluded(path) else path

    def _item(self, kb_path: str, p: Path) -> dict:
        mt = FOLDER if p.is_dir() else MEDIA_TYPES.get(p.suffix.lower(), 0)
        return {"media_id": self.media_id(kb_path), "title": p.name, "media_type": mt}

    # ------------------------------------------------------------ by KB path
    def list_path(self, kb_path: str = "") -> list[dict]:
        p = self._fs(kb_path)
        if p is None or not p.is_dir():
            return []
        base = kb_path.strip("/")
        out = []
        for c in sorted(p.iterdir(), key=lambda c: (not c.is_dir(), c.name)):
            cp = f"{base}/{c.name}" if base else c.name
            if not excluded(cp):
                out.append(self._item(cp, c))
        return out

    def read_bytes(self, kb_path: str) -> bytes | None:
        p = self._fs(kb_path)
        return p.read_bytes() if p is not None and p.is_file() else None

    def read_text(self, kb_path: str) -> str | None:
        raw = self.read_bytes(kb_path)
        return raw.decode("utf-8", errors="replace").lstrip("﻿") if raw is not None else None

    # ------------------------------------------------------------ ImaClient-shaped API
    def find_kb(self, name: str) -> dict:
        return {"id": "local", "name": KB_NAME}

    def list_folder(self, kb_id: str, folder_id: str | None = None) -> list[dict]:
        path = "" if not folder_id else self.path_of(folder_id)
        if path is None:
            raise ImaError(-100, "本地镜像中没有该文件夹", "get_knowledge_list")
        return self.list_path(path)

    def search(self, kb_id: str, query: str, max_pages: int = 3) -> list[dict]:
        """Offline stand-in: file titles that contain every query word. No ima call."""
        words = [w for w in (query or "").lower().split() if w]
        hits = []
        for p in sorted(self.root.rglob("*")):
            kp = p.relative_to(self.root).as_posix()
            if p.is_file() and not excluded(kp) and words and all(w in kp.lower() for w in words):
                hits.append(self._item(kp, p))
        return hits[:20 * max_pages]

    def media_info(self, media_id: str) -> dict:
        path = self.path_of(media_id)
        p = self._fs(path) if path is not None else None
        if p is None or not p.is_file():
            raise ImaError(-100, "本地镜像中没有该文件", "get_media_info")
        return {"media_type": MEDIA_TYPES.get(p.suffix.lower(), 0), "url_info": {}}

    def fetch_media(self, media_id: str) -> tuple[int | None, bytes | None]:
        path = self.path_of(media_id)
        if path is None:
            return None, None
        raw = self.read_bytes(path)
        return (MEDIA_TYPES.get(Path(path).suffix.lower(), 0) if raw is not None else None), raw

    def fetch_text(self, media_id: str) -> str | None:
        path = self.path_of(media_id)
        return self.read_text(path) if path is not None else None

    # ------------------------------------------------------------ provenance
    def origin(self, source_path: str) -> str:
        return ORIGIN_LOCAL

    def confirm(self, media_id: str) -> str:
        return ORIGIN_LOCAL

    def live_search(self, query: str) -> list[dict]:
        return []

    def status(self) -> dict:
        return {"kb_name": KB_NAME, "connected": False, "configured": _configured(),
                "index_status": self.index_status, "error": self.last_error, "mode": self.mode}


class HybridKB(LocalKB):
    """Mirror for the index, text and images, plus a few cached live ima calls that confirm sources."""

    mode = MODE_HYBRID

    def __init__(self, root: str | Path | None = None, ima=None, ids: dict[str, str] | None = None,
                 confirm_path: Path | None = CONFIRM_PATH, confirm_ttl: int = CONFIRM_TTL):
        super().__init__(root, ids)
        if ima is None:
            from agent.ima_wrapper import ImaClient
            ima = ImaClient()
        self.ima = ima
        self.confirm_path, self.confirm_ttl = confirm_path, confirm_ttl
        self.origins: dict[str, str] = {}      # source_path -> "ima" | "本地镜像"
        self.live_hits: list[dict] = []        # search results recorded as live source hits (titles only)
        self._kb: dict | None = None
        self._kb_tried = False
        self._confirmed = self._load_confirmed()

    @property
    def live_calls(self) -> int:
        return getattr(self.ima, "live_calls", 0)

    @live_calls.setter
    def live_calls(self, _):   # LocalKB.__init__ assigns it; the ima client owns the count
        pass

    def _log(self, api: str, ok: bool, cached: bool, origin: str, source: str = ""):
        self.call_log.append({"api": api, "cached": cached, "stale": False, "ok": ok, "ts": time.time(),
                              "origin": origin, "source": source})

    def _fail(self, e: Exception):
        from agent.ima_wrapper import plain_message
        self.last_error = f"{plain_message(e)}；已使用本地镜像"

    # ------------------------------------------------------------ startup: find_kb once
    def find_kb(self, name: str) -> dict:
        self._live_kb()
        return {"id": "local", "name": self.kb_name}

    def _live_kb(self) -> dict | None:
        if not self._kb_tried:
            self._kb_tried = True
            try:
                self._kb = self.ima.find_kb(KB_NAME)
                self.kb_name = self._kb.get("name") or KB_NAME
                self.connected = True
                self._log("search_knowledge_base", True, False, ORIGIN_IMA)
            except Exception as e:  # noqa: BLE001  any failure -> mirror only
                self._fail(e)
                self._log("search_knowledge_base", False, False, ORIGIN_LOCAL)
        return self._kb

    # ------------------------------------------------------------ per run: one search
    def live_search(self, query: str) -> list[dict]:
        """One search_knowledge page (ImaClient caches it 24 h per query). Titles only are recorded."""
        kb = self._live_kb()
        hit = {"query": query, "titles": [], "origin": ORIGIN_LOCAL, "ts": time.time()}
        if kb and kb.get("id"):
            try:
                res = self.ima.search(kb["id"], query, max_pages=1)
                hit.update(titles=[r.get("title", "") for r in res][:10], origin=ORIGIN_IMA)
                self._log("search_knowledge", True, False, ORIGIN_IMA, query)
            except Exception as e:  # noqa: BLE001
                self._fail(e)
                self._log("search_knowledge", False, False, ORIGIN_LOCAL, query)
        self.live_hits.append(hit)
        return [{"title": t} for t in hit["titles"]]

    # ------------------------------------------------------------ used sources: get_media_info yes/no
    def _load_confirmed(self) -> dict:
        try:
            return json.loads(self.confirm_path.read_text("utf-8")) if self.confirm_path else {}
        except (OSError, ValueError):
            return {}

    def _save_confirmed(self):
        if self.confirm_path:
            self.confirm_path.parent.mkdir(parents=True, exist_ok=True)
            self.confirm_path.write_text(json.dumps(self._confirmed, ensure_ascii=False), "utf-8")

    def confirm(self, media_id: str) -> str:
        """Does this source resolve in ima? Caches yes/no for 24 h (never the signed URL).
        Recorded in `origins` under the source's full KB path (folder/title)."""
        key = self.path_of(media_id)
        if key is None:
            return ORIGIN_LOCAL
        if is_local_id(media_id):
            origin = ORIGIN_LOCAL                          # not an ima item: nothing to confirm
        else:
            rec = self._confirmed.get(key)
            if rec and time.time() - rec["ts"] < self.confirm_ttl:
                origin = ORIGIN_IMA if rec["live"] else ORIGIN_LOCAL
                self._log("get_media_info", True, True, origin, key)
            else:
                origin = ORIGIN_LOCAL
                try:
                    info = self.ima.media_info(media_id)
                    live = bool((info.get("url_info") or {}).get("url"))
                    self._confirmed[key] = {"live": live, "ts": time.time()}
                    self._save_confirmed()
                    origin = ORIGIN_IMA if live else ORIGIN_LOCAL
                    self._log("get_media_info", True, False, origin, key)
                except Exception as e:  # noqa: BLE001  any error (220021 too): not cached, mirror only
                    self._fail(e)
                    self._log("get_media_info", False, False, ORIGIN_LOCAL, key)
        self.origins[key] = origin
        return origin

    def origin(self, source_path: str) -> str:
        return self.origins.get(source_path, ORIGIN_LOCAL)

    def fetch_media(self, media_id: str) -> tuple[int | None, bytes | None]:
        mt, raw = super().fetch_media(media_id)
        if raw is not None and mt == 9:                     # an image used in an output: confirm it
            self.confirm(media_id)
        return mt, raw

    def status(self) -> dict:
        self._live_kb()
        return {"kb_name": self.kb_name or KB_NAME, "connected": self.connected, "configured": _configured(),
                "index_status": self.index_status, "error": self.last_error, "mode": self.mode}
