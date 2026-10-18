# Huawei PC Marketing Advertorial Agent — project rules for Claude Code

Hackathon entry: 浙客松 AI+X 破界黑客松, Huawei track. A self-developed Agent that writes illustrated marketing articles about Huawei PCs, with every fact and image taken from the ima shared knowledge base 任德耀新建华为PC知识库.

## Sources of truth (read before working)
1. `docs/CONTRACTS.md`: file ownership, binding interfaces, and **KB facts that override WORKFLOW v4**.
2. `docs/WORKFLOW.md` (v4): the team's pipeline design, rules, test plan.
3. `docs/kb_structure.md`: what the real KB looks like.
4. `agent/schemas.py`: shared types. `tests/fakes.py`: fakes for every interface.
If they disagree: CONTRACTS.md §1 > kb_structure.md > WORKFLOW.md.

## Hard rules (never break)
1. Never print, echo, cat, log or display `.env` or any API Key or Client ID, not even masked. Status UIs show "已配置".
2. KB is read-only. Only use read APIs: search_knowledge_base, get_knowledge_list, search_knowledge, get_media_info. Never call create_media, add_knowledge, import_urls, check_repeated_names or any upload script.
3. Never commit KB content: no KB text, quotes, prices or image files in code, tests, prompts, configs, docs or examples. Fixtures are synthetic (DemoBook). `kb_snapshot/`, `.cache/`, `outputs/`, `logs/` stay gitignored.
4. ima quota: only the P1 (data) workstream calls ima, with targeted calls and the disk cache. Never walk the whole KB tree. Never work around a 403 or a quota error (220021).
5. ima is called only through `ima-skill/ima_api.cjs` (kept unmodified in the repo) via `agent/ima_wrapper.py`.
6. Only edit files your workstream owns (CONTRACTS.md §2). Never edit `agent/schemas.py`, `tests/fakes.py`, `docs/CONTRACTS.md` or `CLAUDE.md` unless you are P5.
7. Output format headings are verbatim: 一、场景判断 / 二、知识库依据 / 三、图文软文 / 四、核验结果. Use 行动引导 for the CTA.
8. Never output 最/第一/唯一/顶级/全网/首选 etc. Never invent prices, discounts, subsidies, stock, sales, awards, reviews, benchmark results or policies.
9. Git: work on your feature branch. Commit only after `git add --dry-run .` shows no .env, .zip, kb_snapshot/, .cache/, .venv/, outputs/ or __pycache__/. Never push to main; push your branch and open a PR. Never force-push.
10. If something fails, show the error and your diagnosis. Never weaken a rule to work around it.

## Environment
- Python: use the repo's `.venv` (`.venv/bin/python`, `.venv/bin/pip`). Tests: `.venv/bin/python -m pytest -q`.
- Node 18+ is required for `ima-skill/ima_api.cjs`.
- LLM: OpenAI-compatible endpoint from env `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`, `LLM_MODEL_FAST`.
