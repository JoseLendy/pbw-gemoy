#!/usr/bin/env python3
"""
Refresh ONE model's entry in the cached ima index (.cache/index.json) with targeted calls only.

    python scripts/refresh_model_index.py --folder "P1-产品参数库/02-MateBook-Windows/MateBook X系列" --route windows

Lists that model folder and its image folders, reads their 图片索引.csv, and replaces (or adds) the entry.
The folder's media id comes from the saved KB walk (.cache/ima_ids.json), so nothing above it is listed and
the KB tree is never walked. Prints the number of live ima calls. Never prints ids or keys.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.catalog import INDEX_PATH, KB_NAME, _build_model, save_index  # noqa: E402
from agent.ima_wrapper import ImaClient, ImaError  # noqa: E402
from agent.kb_local import load_id_map  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--folder", required=True, help="KB path of the model folder (under P1-产品参数库)")
    ap.add_argument("--route", required=True, choices=("harmonyos", "windows"))
    args = ap.parse_args(argv)
    if not INDEX_PATH.exists():
        print("no cached ima index (.cache/index.json): build it first with scripts/build_index.py")
        return 2
    folder_id = load_id_map().get(args.folder)
    if not folder_id:
        print("folder not found in the saved KB walk; check the path")
        return 2
    index = json.loads(INDEX_PATH.read_text("utf-8"))
    client = ImaClient()
    unlisted, issues = [], []
    try:
        kb = client.find_kb(KB_NAME)

        def ls(fid, path):
            try:
                return client.list_folder(kb["id"], fid)
            except ImaError as e:
                unlisted.append({"path": path, "code": e.code})
                return None

        mf = {"media_id": folder_id, "title": args.folder.rsplit("/", 1)[-1]}
        entry = _build_model(client, ls, mf, args.folder, args.route, issues, unlisted, prev_csv={})
    except ImaError as e:
        print(f"ima error code {e.code}: {e.msg} · live calls {client.live_calls}")
        return 1
    print(f"live ima calls: {client.live_calls}")
    if entry is None or unlisted:
        print(f"not refreshed: {issues or unlisted}")
        return 1
    models = [m for m in index.get("models", []) if m and m.get("model_id") != entry["model_id"]]
    index["models"] = models + [entry]
    index["unlisted"] = [u for u in index.get("unlisted", []) if not u.get("path", "").startswith(args.folder)]
    index["issues"] = [i for i in index.get("issues", []) if i.get("model") != mf["title"]] + issues
    if not index["unlisted"] and index.get("status") == "partial":
        index["status"] = "stale" if any("上次索引" in i.get("issue", "") for i in index["issues"]) else "complete"
    save_index(index)
    print(f"refreshed {entry['model_id']} · {len(entry['images'])} images · index status {index['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
