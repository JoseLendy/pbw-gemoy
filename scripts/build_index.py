"""
Build (or reload) the product index and print a summary. Prints no KB text, ids or keys.

    .venv/bin/python scripts/build_index.py                  # backend from env KB_BACKEND (default local)
    .venv/bin/python scripts/build_index.py --backend local  # from the local mirror, zero ima calls
    .venv/bin/python scripts/build_index.py --backend ima    # targeted listings (disk cache first)
    .venv/bin/python scripts/build_index.py --backend ima --cached   # only read .cache/index.json
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.catalog import INDEX_PATH, LOCAL_INDEX_PATH, load_catalog  # noqa: E402
from agent.ima_wrapper import BACKENDS, kb_backend, make_client  # noqa: E402

PROBES = ["MateBook 14", "MateBook 14 酷睿 Ultra", "Pro", "擎云"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=BACKENDS, default=None, help="default: env KB_BACKEND or local")
    ap.add_argument("--cached", action="store_true", help="ima backend: read the saved index, never call ima")
    ap.add_argument("--probe", nargs="*", default=PROBES, help="queries to resolve")
    args = ap.parse_args()

    backend = args.backend or kb_backend()
    client = make_client(backend)
    st = client.status()
    print(f"backend: {backend} ({st.get('mode', 'ima')})  ima 凭证: {'已配置' if st['configured'] else '未配置'}")
    cat = load_catalog(client, refresh=not args.cached)
    path = LOCAL_INDEX_PATH if getattr(client, "is_local", False) else INDEX_PATH
    print(f"index: {path.relative_to(path.parents[1])}  built_at={cat.index['built_at']}  "
          f"status={cat.status}  unlisted={cat.unlisted or 'none'}")
    for i in cat.index.get("issues", []):
        print(f"  issue: {i['model']}: {i['issue']}")

    img_models = [m for m in cat.models.values() if m.route != "text_only"]
    text_only = [m for m in cat.models.values() if m.route == "text_only"]
    print(f"\n{len(img_models)} models with images, {len(text_only)} text-only products\n")
    print(f"{'canonical name':<44} {'model_id':<30} {'route':<10} {'img':>4}  siblings")
    for m in img_models:
        n = len(cat.images_for(m.model_id))
        flag = f"  needs_human={m.needs_human}" if m.needs_human else ""
        print(f"{m.canonical_name:<44} {m.model_id:<30} {m.route:<10} {n:>4}  {', '.join(m.siblings) or '-'}{flag}")
    print(f"{'total':<86} {sum(len(cat.images_for(m.model_id)) for m in img_models):>4}")

    print()
    for q in args.probe:
        r = cat.resolve(q)
        who = r.model.canonical_name if r.model else ", ".join(c.canonical_name for c in r.candidates[:6])
        more = f" (+{len(r.candidates) - 6})" if len(r.candidates) > 6 else ""
        print(f"resolve({q!r:<26}) -> {r.status:<10} {who}{more}  {r.reason}")

    calls = [c for c in client.call_log if not c["cached"]]
    print(f"\nima: {client.live_calls} live script calls, "
          f"{sum(c['cached'] and not c['stale'] for c in client.call_log)} cache hits, "
          f"{sum(c['stale'] for c in client.call_log)} stale, {sum(not c['ok'] for c in calls)} failed")


if __name__ == "__main__":
    main()
