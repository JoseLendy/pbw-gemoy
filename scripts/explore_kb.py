"""
Step-1 smoke test + KB structure mapper. Run this FIRST, with credentials in env.

    pip install requests python-dotenv
    python scripts/explore_kb.py            # connection test + full tree
    python scripts/explore_kb.py --sample 3 # also download 3 article.md files

Writes to ./kb_snapshot/ (GITIGNORED - for studying structure only; the agent must
still read from the live API at runtime, and the KB must not be redistributed).
"""
import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from agent.ima_wrapper import ImaClient  # noqa: E402

KB_NAME = "任德耀新建华为PC知识库"
OUT = Path("kb_snapshot")


def is_folder(item: dict) -> bool:
    # Observed live: folders come back as media_type 99 with a "folder_<n>" media_id
    # and none of the folder_id/file_number keys the starter assumed.
    return (
        item.get("media_type") == 99
        or str(item.get("media_id", "")).startswith("folder_")
        or "folder_id" in item or "file_number" in item or "folder_number" in item
    )


def walk(client, kb_id, folder_id=None, path="", depth=0, rows=None, max_depth=6):
    rows = [] if rows is None else rows
    try:
        items = client.list_folder(kb_id, folder_id)
    except Exception as e:  # one 403 folder or the daily cap (code 220021) must not abort the walk
        rows.append({"type": "unlisted", "path": path or "/", "id": folder_id, "error": str(e)[:200]})
        return rows
    for it in items:
        title = it.get("title") or it.get("name") or "?"
        p = f"{path}/{title}"
        if is_folder(it) and depth < max_depth:
            fid = it.get("folder_id") or it.get("media_id")
            rows.append({"type": "folder", "path": p, "id": fid, "raw": it})
            walk(client, kb_id, fid, p, depth + 1, rows, max_depth)
        else:
            rows.append({"type": "file", "path": p, "id": it.get("media_id"), "raw": it})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="download N article.md files")
    args = ap.parse_args()

    c = ImaClient()
    if not c.status()["configured"]:
        sys.exit("[1] ima 凭证未配置 (set IMA_OPENAPI_CLIENTID / IMA_OPENAPI_APIKEY in .env)")
    print("[1] ima 凭证: 已配置")

    kb = c.find_kb(KB_NAME)
    print(f"[2] Found KB: {kb['name']}")

    rows = walk(c, kb["id"])
    files = [r for r in rows if r["type"] == "file"]
    folders = [r for r in rows if r["type"] == "folder"]
    unlisted = [r for r in rows if r["type"] == "unlisted"]
    print(f"[3] Walked tree: {len(folders)} folders, {len(files)} files, {len(unlisted)} unlistable folders (handbook says ~314 items)")

    OUT.mkdir(exist_ok=True)
    (OUT / "tree.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), "utf-8")
    with open(OUT / "tree.txt", "w", encoding="utf-8") as f:
        for r in rows:
            f.write({"folder": "📁 ", "unlisted": "⛔ "}.get(r["type"], "   📄 ") + r["path"] + "\n")
    exts = Counter(Path(r["path"]).suffix.lower() or "(none)" for r in files)
    print(f"[4] File types: {dict(exts)}")
    print(f"    Tree written to {OUT/'tree.txt'}  <- read this to see how models/images are organized")

    # Probe media types: are images separate items (media_type 9)?
    print("[5] Probing get_media_info on up to 8 files...")
    probes = []
    for r in files[:8]:
        info = c.media_info(r["id"])
        has_url = bool((info.get("url_info") or {}).get("url"))
        probes.append({"path": r["path"], "media_type": info.get("media_type"), "has_url": has_url})
        print(f"    type={info.get('media_type')} url={'yes' if has_url else 'NO'}  {r['path']}")
    (OUT / "media_probe.json").write_text(json.dumps(probes, ensure_ascii=False, indent=1), "utf-8")

    if args.sample:
        md = [r for r in files if r["path"].lower().endswith(".md")][: args.sample]
        for r in md:
            txt = c.fetch_text(r["id"]) or ""
            safe = r["path"].strip("/").replace("/", "__")
            (OUT / safe).write_text(txt, "utf-8")
            n_img = txt.count("![")
            print(f"[6] Saved {safe}  ({len(txt)} chars, {n_img} markdown images)")
    print("Done. Check kb_snapshot/ - NEVER commit it.")


if __name__ == "__main__":
    main()
