"""Offline stand-in for agent.ima_wrapper.ImaClient, serving the synthetic tree in kb_tree.json."""
from __future__ import annotations

import copy
import json
from pathlib import Path

from agent.ima_wrapper import ImaError

TREE = json.loads((Path(__file__).parent / "kb_tree.json").read_text("utf-8"))

DEMO_ALIASES = {"models": {
    "demobook-14": {"aliases": ["演示本 14"], "siblings": ["demobook-14-se"]},
    "demobook-14-se": {"aliases": ["DemoBook 14 SE"], "siblings": ["demobook-14"], "needs_human": ["cpu"]},
}}


class FakeIma:
    def __init__(self, tree: dict | None = None, fail_folders: dict[str, int] | None = None,
                 fail_media: dict[str, int] | None = None):
        self.tree = copy.deepcopy(tree or TREE)
        self.fail_folders = fail_folders or {}
        self.fail_media = fail_media or {}
        self.calls: list[tuple[str, str]] = []
        self.call_log: list[dict] = []
        self.live_calls = 0
        self.stale_served = False
        self.index_status = "unknown"
        self.last_error = ""

    def find_kb(self, name):
        self.calls.append(("search_knowledge_base", name))
        return dict(self.tree["kb"])

    def list_folder(self, kb_id, folder_id=None):
        fid = folder_id or ""
        self.calls.append(("get_knowledge_list", fid))
        if fid in self.fail_folders:
            raise ImaError(self.fail_folders[fid], "synthetic failure", "get_knowledge_list")
        return copy.deepcopy(self.tree["folders"].get(fid, []))

    def fetch_text(self, media_id):
        self.calls.append(("get_media_info", media_id))
        if media_id in self.fail_media:
            raise ImaError(self.fail_media[media_id], "synthetic failure", "get_media_info")
        return self.tree["texts"].get(media_id)

    def fetch_media(self, media_id):
        self.calls.append(("get_media_info", media_id))
        return 9, f"bytes:{media_id}".encode()
