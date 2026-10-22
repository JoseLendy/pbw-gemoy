#!/usr/bin/env python3
"""
Freeze check: the automatable items of docs/FREEZE_CHECKLIST.md. Prints ✅ / ❌ / ⏭ per item; exit code 1
if any item is ❌. Makes no ima or LLM calls (it only reads files, runs the offline test suite and the
offline data checks). Never prints keys, the Client ID or KB IDs.

    python scripts/freeze_check.py [--today 2026-10-23]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import subprocess
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OK, FAIL, SKIP = "✅", "❌", "⏭"
# Demo placeholders are standalone MODEL_A … MODEL_N (not env names like LLM_MODEL_FAST).
PLACEHOLDER_RE = re.compile(r"(?<![A-Za-z0-9_])MODEL_[A-Z]\b|<[^<>]*从catalog填写[^<>]*>")
SECRET_RES = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),                       # OpenAI-style keys
    re.compile(r"\bAKID[A-Za-z0-9]{10,}"),                         # Tencent-style key ids
    re.compile(r"\b[0-9a-fA-F]{32,}\b"),                           # long hex tokens
    re.compile(r"(?i)(api[_-]?key|client[_-]?id|secret|token)\s*[=:]\s*['\"][A-Za-z0-9_\-]{16,}['\"]"),
]
SECRET_ENV = ("LLM_API_KEY", "IMA_OPENAPI_APIKEY", "IMA_OPENAPI_CLIENTID", "IMA_API_KEY", "IMA_CLIENT_ID", "AMAP_KEY")


def _py():
    venv = ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def _run(*args, timeout=600) -> tuple[int, str]:
    p = subprocess.run([_py(), *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def _tracked() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if l]


# ---------------------------------------------------------------- checks
def check_tests(day):
    code, out = _run("-m", "pytest", "-q", "-p", "no:cacheprovider")
    last = next((l for l in reversed(out.splitlines()) if "passed" in l or "failed" in l or "error" in l), "")
    return (OK if code == 0 else FAIL), last.strip()


def check_gen_data(day):
    code, out = _run("scripts/gen_fake_data.py", "--check-only", "--today", day)
    return (OK if code == 0 and "All checks passed" in out else FAIL), f"gen_fake_data --check-only --today {day}"


def check_catalog_guard(day):
    code, out = _run("-m", "pytest", "-q", "-rs", "-p", "no:cacheprovider", "tests/test_catalog_guard.py")
    if code != 0:
        return FAIL, "catalog guard failed"
    if "skipped" in out.lower():
        return FAIL, "catalog guard was skipped (no catalog to check against)"
    return OK, "every models.csv id resolves in the catalog (not skipped)"


def _string_literals(path: Path) -> list[str]:
    try:
        toks = tokenize.generate_tokens(io.StringIO(path.read_text("utf-8")).readline)
        return [t.string for t in toks if t.type == tokenize.STRING]
    except (tokenize.TokenError, SyntaxError, UnicodeDecodeError):
        return []


def check_placeholders(day):
    hits = []
    for p in (ROOT / "data" / "demo").rglob("*"):
        if p.is_file() and p.suffix in (".csv", ".json", ".md", ".txt"):
            if PLACEHOLDER_RE.search(p.read_text("utf-8", errors="ignore")):
                hits.append(str(p.relative_to(ROOT)))
    for p in (ROOT / "agent").rglob("*.py"):
        if any(PLACEHOLDER_RE.search(s) for s in _string_literals(p)):
            hits.append(str(p.relative_to(ROOT)))
    ui = ROOT / "ui"
    ui_note = ""
    if ui.is_dir():
        for p in ui.rglob("*.py"):
            if any(PLACEHOLDER_RE.search(s) for s in _string_literals(p)):
                hits.append(str(p.relative_to(ROOT)))
    else:
        ui_note = "；ui/ skipped (ui/ not merged)"
    return (FAIL if hits else OK), (f"placeholders in {hits}" if hits else "no MODEL_* / <…从catalog填写> in data/demo, agent/") + ui_note


def check_secrets(day):
    tracked = _tracked()
    problems = []
    if ".env" in tracked:
        problems.append(".env is tracked")
    values = [v for v in (os.getenv(k) for k in SECRET_ENV) if v and len(v) >= 8]
    try:  # the configured secrets themselves (never printed): no tracked file may contain one
        from dotenv import dotenv_values
        values += [v for k, v in (dotenv_values(ROOT / ".env") or {}).items() if k in SECRET_ENV and v and len(v) >= 8]
    except Exception:  # noqa: BLE001
        pass
    for rel in tracked:
        p = ROOT / rel
        if not p.is_file() or p.stat().st_size > 2_000_000:
            continue
        try:
            text = p.read_text("utf-8")
        except UnicodeDecodeError:
            continue
        if any(v in text for v in values):
            problems.append(f"{rel}: contains a configured secret value")
        elif any(r.search(text) for r in SECRET_RES):
            problems.append(f"{rel}: key-like token")
    return (FAIL if problems else OK), ("; ".join(problems[:5]) if problems else
                                        f"{len(tracked)} tracked files clean; .env not tracked")


def check_kb_untracked(day):
    n = len([f for f in _tracked() if f.startswith("kb_snapshot/")])
    return (FAIL if n else OK), (f"kb_snapshot/ has {n} tracked files" if n else "kb_snapshot/ not tracked")


def check_model_facts(day):
    """Every models.csv model has a 产品事实 source in the configured backend (no ima calls)."""
    import csv
    from agent.ima_wrapper import kb_backend
    from agent.recommend.common import INPUTS
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except Exception:  # noqa: BLE001
        pass
    backend = kb_backend()
    ids = [r["model_id"] for r in csv.DictReader((INPUTS / "models.csv").open(encoding="utf-8"))]
    missing = []
    if backend in ("local", "hybrid"):
        from agent.catalog import build_index
        from agent.kb_local import LocalKB
        try:
            kb = LocalKB()
        except Exception as e:  # noqa: BLE001
            return FAIL, f"{backend}: {getattr(e, 'msg', e)}"
        index = build_index(kb)
        entries = {m["model_id"]: m for m in index["models"]}
        for mid in ids:
            src = (entries.get(mid) or {}).get("facts")
            if not src or not (kb.fetch_text(src["media_id"]) or "").strip():
                missing.append(mid)
    else:
        from agent.catalog import INDEX_PATH
        if not INDEX_PATH.exists():
            return FAIL, "ima: no cached index (.cache/index.json)"
        entries = {m["model_id"]: m for m in json.loads(INDEX_PATH.read_text("utf-8")).get("models", []) if m}
        missing = [mid for mid in ids if not (entries.get(mid) or {}).get("facts")]
    return (FAIL if missing else OK), (f"{backend}: no facts for {missing}" if missing
                                       else f"{backend}: facts for all {len(ids)} models")


def check_prepared(day):
    from agent.recommend.store_data import default_card, load_store_data
    from agent.runs import prepared_post
    stores = [s["store_id"] for s in load_store_data().stores]
    unlocked = [s for s in stores if (c := default_card(s, day)) is not None and not c.locked]
    missing = []
    for sid in unlocked:
        rec = prepared_post(sid, day)
        if rec is None or rec.get("dev_mode"):
            missing.append(sid)
    return (FAIL if missing else OK), (f"no real prepared post for {missing}" if missing
                                       else f"prepared posts for all {len(unlocked)} unlocked stores")


def check_scenes(day):
    from agent.runs import RUNS_DIR
    files = sorted((RUNS_DIR / day).glob("*-demo_scenes.json")) if (RUNS_DIR / day).exists() else []
    real = [json.loads(p.read_text("utf-8")) for p in files]
    real = [r for r in real if not r.get("fake")]
    if not real:
        return FAIL, f"no real demo_scenes.py run for {day} in runs/"
    last = real[-1]
    bad = [f"{s['n']}" for s in last["scenes"] if not s["ok"]]
    return (FAIL if bad else OK), (f"latest real run: scenes {bad} FAIL" if bad
                                   else f"latest real run: all {len(last['scenes'])} scenes PASS")


def check_labels(day):
    """The labels the video relies on come out of the backend code paths (fakes, no calls)."""
    import dataclasses
    from agent.baseline import wrap
    from agent.checks.prices import DEMO_TAG, mark_demo_prices
    from agent.recommend import explain
    from agent.recommend.store_data import cards_for
    from agent.recommend.to_task import card_to_task
    import datetime as dt
    from tests.fakes import fake_post
    missing = []
    promo = next((c for sid in ("S02", "S01", "S04") for c in cards_for(sid, day)
                  if c.slot == "promo" and c.promo and c.promo.price_info), None)
    if promo is None:
        missing.append("演示活动 (no promo card with a demo price)")
    else:
        task = card_to_task(promo)
        p = fake_post("moments")
        p.body = [f"演示活动价 {promo.promo.price_info['value']} 元。"]
        if DEMO_TAG.strip("[]") not in mark_demo_prices(p, task).all_text() or "演示活动" not in DEMO_TAG:
            missing.append("演示活动")
    if "对照组" not in wrap("x"):
        missing.append("对照组")
    if explain.release_reason(dt.date(2026, 10, 28), True) != "总部新品推送（演示流程）":
        missing.append("总部新品推送（演示流程）")
    return (FAIL if missing else OK), (f"missing labels: {missing}" if missing
                                       else "演示活动 · 对照组 · 总部新品推送（演示流程）")


CHECKS = [
    ("Full test suite", check_tests),
    ("Demo data check (--check-only)", check_gen_data),
    ("Catalog guard passes (not skipped)", check_catalog_guard),
    ("No placeholders in data/demo, agent/, ui/", check_placeholders),
    ("Secrets scan of tracked files", check_secrets),
    ("kb_snapshot/ not tracked", check_kb_untracked),
    ("Facts for every mapped model in the configured KB backend", check_model_facts),
    ("Prepared posts for every unlocked store", check_prepared),
    ("Real demo_scenes.py run, every scene PASS", check_scenes),
    ("Required labels in backend outputs", check_labels),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--today", default="2026-10-23")
    args = ap.parse_args(argv)
    failed = 0
    print(f"freeze check · {args.today}")
    for name, fn in CHECKS:
        try:
            mark, detail = fn(args.today)
        except Exception as e:  # noqa: BLE001 - a broken check is a failed check
            mark, detail = FAIL, f"check crashed: {type(e).__name__}: {str(e)[:120]}"
        failed += mark == FAIL
        print(f"{mark} {name} — {detail}")
    print(f"\n{'all automatable items pass' if not failed else f'{failed} item(s) failing'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
