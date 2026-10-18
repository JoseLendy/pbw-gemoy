"""
Dump real bundles for 3 models into .cache/dev_bundles/<model_id>.json for teammates' local realism
tests (CONTRACTS §4 rule 4). The folder is gitignored and shared privately. NEVER commit it.

    .venv/bin/python scripts/export_dev_cache.py                    # backend from env KB_BACKEND (default local)
    .venv/bin/python scripts/export_dev_cache.py matebook-gt-14     # other models
    .venv/bin/python scripts/export_dev_cache.py --backend ima      # live ima (uses quota)

Load on the other side with:  ModelBundle(**json) is not enough (nested dataclasses), use
    from scripts.export_dev_cache import load_bundle; b = load_bundle(path)
Prints no KB text, ids or keys.
"""
import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.catalog import ROOT, load_catalog  # noqa: E402
from agent.ima_wrapper import BACKENDS, ImaError, kb_backend, make_client, plain_message  # noqa: E402
from agent.retrieval import get_model_bundle  # noqa: E402
from agent.schemas import ImageRef, Model, ModelBundle, SourceRecord  # noqa: E402

OUT = ROOT / ".cache" / "dev_bundles"
DEFAULT = ["matebook-14-harmonyos", "matebook-14-2024", "matebook-d-16-se-2024"]


def load_bundle(path) -> ModelBundle:
    d = json.loads(Path(path).read_text("utf-8"))
    src = lambda s: SourceRecord(**s) if s else None  # noqa: E731
    return ModelBundle(model=Model(**d["model"]), facts_text=d["facts_text"], claims_text=d["claims_text"],
                       images=[ImageRef(**i) for i in d["images"]], sources=[SourceRecord(**s) for s in d["sources"]],
                       facts_source=src(d["facts_source"]), claims_source=src(d["claims_source"]),
                       cards=d.get("cards", {}), index_status=d["index_status"], unlisted=d.get("unlisted", []))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*", default=DEFAULT)
    ap.add_argument("--backend", choices=BACKENDS, default=None, help="default: env KB_BACKEND or local")
    args = ap.parse_args()

    backend = args.backend or kb_backend()
    client = make_client(backend)
    cat = load_catalog(client)
    OUT.mkdir(parents=True, exist_ok=True)
    ok = 0
    for mid in args.models:
        if mid not in cat.models:
            print(f"{mid}: not in the index (status {cat.status}); skipped")
            continue
        try:
            b = get_model_bundle(mid, cat)
        except ImaError as e:
            print(f"{mid}: FAILED, {plain_message(e)}; nothing written")
            continue
        if not b.facts_text or (b.model.route != "text_only" and not b.claims_text):
            print(f"{mid}: FAILED, facts or claims text missing; nothing written")
            continue
        (OUT / f"{mid}.json").write_text(json.dumps(asdict(b), ensure_ascii=False, indent=1), "utf-8")
        ok += 1
        print(f"{mid}: ok  facts {len(b.facts_text)} chars, claims {len(b.claims_text)} chars, "
              f"{len(b.images)} images, index {b.index_status}")
    print(f"\n{ok}/{len(args.models)} bundles in {OUT.relative_to(ROOT)}/ (gitignored, share privately). "
          f"backend {backend}, ima: {client.live_calls} live calls")


if __name__ == "__main__":
    main()
