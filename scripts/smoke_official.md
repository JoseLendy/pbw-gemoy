# Official ima skill smoke test

The handbook's two standard commands, run once each with `ima-skill/` v1.1.10 (unmodified) and credentials from the environment (`.env`, never in argv). `<kb_id>` is a placeholder: the real id stays inside the program.

```bash
node ima-skill/ima_api.cjs openapi/wiki/v1/search_knowledge_base '{"query":"任德耀新建华为PC知识库","cursor":"","limit":20}'
node ima-skill/ima_api.cjs openapi/wiki/v1/get_knowledge_list '{"knowledge_base_id":"<kb_id>","cursor":"","limit":20}'
```

## Result (2026-10-18, 15:05)

| # | Command | Result |
|---|---|---|
| 1 | `search_knowledge_base` | exit 0, `code 0`: found the KB by its exact name (1 hit) |
| 2 | `get_knowledge_list` (root) | exit 0, `code 220021`: daily fetch quota already used up by the morning's exploration; no items returned. Same root listed fine at 14:18 earlier the same day (served from `.cache/ima/` since) |

Note: the script exits 0 even when the API returns an error code, so callers must check `code` in stdout. `agent/ima_wrapper.py` does.

Re-run command 2 after the quota resets to confirm "root lists N items".
