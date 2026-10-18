# Huawei PC Marketing Advertorial Agent (浙客松 AI+X Hackathon, Huawei track)

## Context
- The Agent writes illustrated marketing articles for WeChat Official Account (公众号), Xiaohongshu (小红书), store Moments (门店朋友圈) and store poster (门店海报) about Huawei PCs.
- ALL product facts and images must come from the ima shared knowledge base "任德耀新建华为PC知识库", read live through the ima OpenAPI. Our own Agent does scenario analysis, platform strategy, writing, fact verification and compliance checking. If ima generates the final article and we just forward it, we are disqualified.
- Scoring traps: an image that is not from ima, or shows the wrong model, zeroes the image criterion. Any invented price, subsidy, sales figure, award or review zeroes accuracy and compliance. Model disambiguation and image-to-model matching are critical.
- Stack: Python 3.9+, Gradio (later deployed on ModelScope Studio), an OpenAI-compatible LLM API. No Node needed. `agent/ima_client.py` is a tested Python re-implementation of the official ima_api.cjs: POST https://ima.qq.com/openapi/wiki/v1/<api> with headers ima-openapi-clientid / ima-openapi-apikey / ima-openapi-ctx.
- Read APIs used: search_knowledge_base, get_knowledge_list (folders and files mixed; folder IDs come from returned IDs, never construct them), search_knowledge, get_media_info (temporary signed url plus optional headers; media_type 7 = markdown, 9 = image). An empty search result does NOT mean no permission: browse folders instead.
- The KB has ~314 items. Product specs live under a folder like "P1-产品参数库", one article.md per model.

## HARD RULES (whole project)
1. Never print, echo, cat, log or display the contents of `.env` or any API key. To check that credentials exist, print only True/False or masked values via `mask()` in agent/ima_client.py.
2. Git: commits only after `git add --dry-run .` shows no .env, .zip, kb_snapshot/, .cache/, .venv/ or ima-skill/; never push without my explicit approval.
3. Never write to the knowledge base. Only use read APIs. Never call create_media, add_knowledge, import_urls, check_repeated_names or any upload script.
4. `kb_snapshot/` and `.cache/` are local study copies only. They stay gitignored and are never committed. The KB may not be redistributed.
5. No .zip files and no official `ima-skill/` folder in the repo.
6. If something fails, show the error and your diagnosis. Never work around it by weakening a rule above.

## Required output format and platform rules

Workflow: 场景解析 → 平台策略 → ima素材与图片检索 → 事实点抽取 → 图文编排 → 软文生成 → 事实与图片校验 → 合规检查 → 导出.

Every final output has 4 sections:
- 一、场景判断: 目标人群 / 使用场景 / 用户问题 / 内容目标 / 发布平台 (+ purchase stage)
- 二、知识库依据: 产品型号 / 事实点 (each with source title) / 素材标题
- 三、图文软文: 标题 / 导语 / 正文 / 行动号召 + per image: 图片名称 / 来源 / 插入位置 / 图片说明 (+ platform tags)
- 四、校验结果: 产品事实 / 图片型号 / 合规 / 待确认信息

Platforms:
- 公众号: title, intro, sectioned body, closing CTA; 2–4 images, each with source and insertion position.
- 小红书: conversational title, short paragraphs, usage scenarios, hashtags; 3–6 images; NEVER fake personal experience ("我用了三个月" is forbidden).
- 门店朋友圈: short copy, ONE core selling point, consult or visit-store CTA; 1–3 images (main image and scene images first).
- 门店海报: main title, subtitle, ≤3 selling points, event line; exactly 1 key visual; no model mismatch.

Judging rule: changing the scenario must change the content angle and the selling-point order. Changing the platform must change structure, tone, image count AND CTA. Changing only length or the platform name does NOT count.

Scenarios:
- 开学季 (students/parents: study, portability, battery, multi-device; don't reduce to one performance metric)
- 职场办公 (meetings, travel, documents, multitasking, security)
- 内容创作 (screen, performance, file transfer, workflow; never invent benchmark results)
- 家庭换新 (ease of use, whole family, data migration)
- 企业采购 (deployment, management, stability, service; never promise policies not in the KB)
- 门店到店 (one selling point + reason to visit + consult)
- 新品上市 (what's new, who it suits; prices and benefits need KB sources)
- 节日营销 (gifting, scenarios; never invent discounts, subsidies or stock)

Compliance: no absolute claims (最/第一/顶级/唯一/国家级/全网/100%...), no false promises, no unsupported comparisons, no price/discount/subsidy/sales/award/review not in the KB, no denigrating competitors. If KB sources conflict → stop and request human confirmation.
