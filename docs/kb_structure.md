# KB structure analysis: 任德耀新建华为PC知识库

Snapshot taken 2026-10-18 through the read-only ima OpenAPI. Structure and patterns only: no IDs, no signed URLs, no price figures, no verbatim KB text (WORKFLOW rule 11). Spec values are shown as placeholders and KB wording is paraphrased; model, folder and file names are kept because they are needed to navigate.

## 0. Evidence and gaps

- Listed live: 104 folders and 537 files (the brief said ~314; the KB is newer, it ships `版本变更说明_v6/_v7`).
- Not listable: 8 folders. Seven returned ima code `220021` ("资料获取次数已达上限，请明天再尝试", a fetch quota) during the walk: `P3/07`, `P3/08`, `P4`, `P5`, `P6`, `P7`, `P8`. One returned HTTP 403: `P3/06-维度对比/联想`. Whether the 403 is a permission gap or a throttle is unknown.
- Read: 10 markdown files (2 of them only in part: the price card and the mall snapshot) and 3 CSV indexes. Fetched 5 images, viewed 2. Everything about P4 to P8 below is unknown, not absent.
- Only one model's `产品事实.md` and `卖点与限制.md` were read (MateBook 14 鸿蒙版). Other models are assumed to follow the same template because the folder file names are identical across all 10 (verified from the tree, not from content).

## a. Top-level layout

| Folder | Files seen | Contents |
|---|---|---|
| (KB root) | 9 | README, navigation, version notes v6/v7, stats report, SHA256 manifest, source table, import note |
| `00-建库规范` | 22 | The KB's own governance rules: naming, metadata template, source authority order, fact and image verification flow, pre-publish checklist, conflict handling, agent rules (retrieval order, refusal and human handoff, citation format), sensitive info, glossary, research notes |
| `P1-产品参数库` | 321 | Product facts, images, model lookup cards, extended catalog, dated official price snapshots |
| `P2-卖点话术库` | 101 | Selling-point and talk-track material by channel, plus 8 persona cards per model |
| `P3-竞品资料库` | 82 seen | Competitor comparisons (ThinkPad, 华硕, 小米, 惠普, 戴尔, 苹果MacBook, 12 files each; 联想 not listable) |
| `P4-价格政策库（机密）` | ? | Not listable. The KB's own rules call P4 the only source for dynamic price and policy, and say it needs authorization |
| `P5-培训赋能库`, `P6-营销素材库`, `P7-常见问题库`, `P8-客户场景库` | ? | Not listable. Per the KB retrieval rule, P2/P5/P6/P8 supply expression, platform and scenario structure |
| `90-待审核`, `99-历史归档` | 1 each | Usage notes only |

P1 subfolders: `00-全库横向索引` (15: an overview, a joint image table, a joint parameter matrix, 12 spec matrices), `01-鸿蒙电脑` (55), `02-MateBook-Windows` (54), `03-华为擎云商用` (1, index only), `04-华为商城销售款式` (3), `05-华为智选及生态产品` (1, index only), `06-型号检索卡` (61), `07-扩展产品目录` (56), `08-官方公开价格快照` (75).

P2 subfolders: `00-使用说明`, `01-零售`, `02-渠道分销`, `03-政企`, `04-教育`, `05-售后价值`, `06-换机迁移` (1 to 2 files each), `07-按型号角色` (80 = 10 models x 8 cards), `08-方法论` (10).

There is no `article.md` anywhere in the KB. The brief's "one article.md per model" does not match reality (see section h).

## b. How models are organized

One folder per model under `P1/01-鸿蒙电脑` (4 models) and `P1/02-MateBook-Windows` (6 models). Every model folder holds the same 4 files, plus an `images/` subfolder (and, for MateBook 14 鸿蒙版 only, `商城款式图片/`):

| File | Type | Role |
|---|---|---|
| `产品事实.md` | md | Scraped official spec page (flattened key/value, footnotes kept) |
| `卖点与限制.md` | md | Curated: positioning, six communication angles (each with usable conclusion, supporting facts, expression boundary), suitable and unsuitable tasks, must-ask-before-publish list, compliant and non-compliant phrasing, image usage rules |
| `图片索引.csv` | csv | One row per image: file name, model, source page, caption, size, suggested use |
| `来源清单.csv` | csv | Source records (not read) |

The same models also appear in:
- `P1/06-型号检索卡/<model>/`: six lookup cards per model (01 型号身份, 02 屏幕与显示, 03 性能与存储, 04 便携续航接口, 05 系统协同与兼容, 06 适用人群与限制). In the one card read (01 型号身份), the model-specific content is short, followed by a long generic template that starts at the marker `<!-- v6-expanded-lookup-card -->`. The other 5 card types were not read, so assume the same pattern but verify.
- `P2/07-按型号角色/<model>/`: eight persona cards per model: 企业采购人, 内容创作者, 商务差旅用户, 学生用户, 教师用户, 旧机换新用户, 管理者, 门店顾客.
- `P1/08-官方公开价格快照/01-消费级PC/<model>-价格卡.md`: one price card per model.
- `P1/07-扩展产品目录/消费级 PC/`: one catalog entry per model.

### All models (10 consumer models with images)

| KB folder name | Official name (from image index / price cards) | System | Processor family (from overview, for disambiguation only) | Images | Image slug |
|---|---|---|---|---|---|
| HUAWEI MateBook 14 | HUAWEI MateBook 14（鸿蒙版） | HarmonyOS 6 | 麒麟 X90 | 4 + 15 | `matebook-14-harmonyos` |
| HUAWEI MateBook Pro | HUAWEI MateBook Pro（鸿蒙版） | HarmonyOS 6.1 | 麒麟 X90 Plus | 8 | `matebook-pro-harmonyos` |
| HUAWEI MateBook Pro S | HUAWEI MateBook Pro S | HarmonyOS 6.1 | 麒麟 XE90 | 6 | `matebook-pro-s` |
| HUAWEI MateBook Fold 非凡大师 | HUAWEI MateBook Fold 非凡大师 | HarmonyOS 6.1 | 麒麟 X90 Plus | 5 | `matebook-fold-ultimate-design` |
| MateBook 14 酷睿 Ultra | HUAWEI MateBook 14 酷睿 Ultra | Windows 11 / Linux V20 | Core Ultra 7 155H / 5 125H | 8 | `matebook-14-2024` |
| MateBook D 14 | HUAWEI MateBook D 14 2024 | Windows 11 / Linux V20 | 13th-gen Core i5 / i7 | 7 | `matebook-d-14-2024` |
| MateBook D 16 | HUAWEI MateBook D 16 2024 | Windows 11 / Linux V20 | 13th-gen Core i9 / i5 | 2 | `matebook-d-16-2024` |
| MateBook D 16 SE 版 | HUAWEI MateBook D 16 SE 版 2024 | Windows 11 / Linux V20 | 13th-gen i5 / 12th-gen i5 | 5 | `matebook-d-16-se-2024` |
| MateBook GT 系列 | HUAWEI MateBook GT 14 | Windows 11 / Linux V20 | Core Ultra 9 185H / 5 125H | 6 | `matebook-gt-14` |
| MateBook X系列 | HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版 | Windows 11 / Linux | Core Ultra 9 185H / 7 155H | 2 | `matebook-x-pro-ultra` |

Total 68 image items (4 + 15 + 8 + 6 + 5 + 8 + 7 + 2 + 5 + 6 + 2 = 68).

Folder names are NOT the official names. "MateBook GT 系列" holds only GT 14 and "MateBook X系列" holds only the X Pro 微绒典藏版, so a series-level name hides which model is actually documented.

### Models with text only, no images

`P1/07-扩展产品目录` lists 45 more products with spec entries and price cards but no image items: 14 commercial (华为擎云 desktops and laptops, plus MateBook Fold 企业版), 10 printers, 11 monitors, 10 accessories. The 企业采购 scenario therefore has no product image for 擎云 or Fold 企业版.

## c. Confusable models

The KB itself warns about most of these: it explicitly cautions against applying the Windows model's specs on the strength of the shared "MateBook 14" name alone.

| Group | Members | How they differ |
|---|---|---|
| **"MateBook 14" name collision** (highest risk) | `HUAWEI MateBook 14`（鸿蒙版）vs `MateBook 14 酷睿 Ultra` | Same display name, different OS (HarmonyOS 6 vs Windows 11), CPU (麒麟 X90 vs Intel Core Ultra) and generation. Image slugs `matebook-14-harmonyos` vs `matebook-14-2024`. Folder names differ only by the `HUAWEI` prefix and the missing "酷睿 Ultra" |
| **"Pro" family** | `HUAWEI MateBook Pro`, `HUAWEI MateBook Pro S`, and the mall's "MateBook Pro 麒麟 X90 Plus" | Pro vs Pro S are separate models (different CPU, weight and screen). The mall snapshot lists a "麒麟 X90 Plus" Pro as a separate sales variant from the base Pro. The overview lists Pro with X90 Plus, so which Pro variant the Pro folder documents is itself unclear. Decision: one model per KB folder; a bare "Pro" is ambiguous and the user is asked (section h item 6 for the CPU fact) |
| **"X" family** | folder `MateBook X系列` vs the one product inside (`MateBook X Pro 酷睿 Ultra 微绒典藏版`) | A series-level folder name covering one specific edition |
| **"GT" family** | folder `MateBook GT 系列` vs the one product inside (`GT 14`) | Same issue |
| **D 16 vs D 16 SE** | `MateBook D 16`, `MateBook D 16 SE 版` | Same year, different CPU generations (13th-gen i9/i5 vs 13th-gen/12th-gen i5). Image slugs `matebook-d-16-2024` vs `matebook-d-16-se-2024`: one is a prefix of the other, so naive substring matching would mis-assign SE images to D 16 |
| **D 14 vs D 16** | `MateBook D 14`, `MateBook D 16` | Size and CPU differ |
| **Fold** | `MateBook Fold 非凡大师`, mall "麒麟 X90 Plus" Fold, `MateBook Fold 企业版` (text only) | Base vs processor variant vs enterprise edition |
| **Variants inside one model** | MateBook 14 鸿蒙版: round vs square keyboard (slightly different weights), standard vs 柔光 screen (different brightness), several RAM and storage options | Facts must keep the variant qualifier. Pro S has 3 screen types |
| **Same slug as prefix** | `matebook-14-2024` and `matebook-14-harmonyos` both start `matebook-14-` | Same prefix hazard as D 16 / D 16 SE |

## d. Where images live

- Images are separate KB items (media_type 9). No markdown file contains an image link: all 10 fetched markdown files have 0 `![` and 0 `<img`. Images are never inline.
- 68 image items sit in 11 folders: `<model>/images/` (10 folders, 53 items) plus `HUAWEI MateBook 14/商城款式图片/` (15 items, prefix `vmall_`; the 53 are prefix `hwpc_`).
- Formats: png 31, jpg 36, webp 1.
- The joint table `P1/00/全部图片联合检索表.csv` lists 112 images but only 68 exist as items. The other 44 are rows pointing at a local folder `02-华为商城电脑专区素材` that does not exist in the KB. They have a source URL but no ima item, so they are not usable.

### Image to model mapping

Three independent signals, and they agree on all 68 items:

1. Folder: the image sits inside exactly one model folder (verified: every `本地目录` value in the joint table matches the real tree folder for all 68).
2. File name: `<hwpc|vmall>_<model-slug>_<scene>_<NN>[_<hash>].<ext>`. Each folder contains exactly one slug, and each slug belongs to exactly one model (MateBook 14 鸿蒙版 uses its slug in two subfolders, `images/` and `商城款式图片/`).
3. Metadata: `图片索引.csv` in the model folder has the model name, a Chinese caption (`画面说明` or `官网图片说明`), source page URL and original URL for each file. The joint table repeats this.

Caveats found:
- 15 `vmall_` images have an empty `产品型号` column in the joint table (their per-folder index carries the model only implicitly, by folder). They are still unambiguous by folder and slug.
- Mapping model to image is exact; mapping image to what it depicts is not. An image's caption can say 原野绿 (green) or 樱粉金 (pink), and the KB says the colour and screen variant shown must match the SKU being sold. Several images are plain colour swatches.
- Captions are marketing text and sometimes generic: some only say, in a few words, that the picture shows the colour and design, without naming the variant.
- I viewed 2 images (MateBook 14 鸿蒙版 深空灰, and MateBook 14 酷睿 Ultra 主视觉). They differ in colour and background, but both are 14-inch laptops with a green wallpaper, and neither shows a model name: the only text is a short marketing slogan on one and the HUAWEI logo on the other. Model identity cannot be read from the pixels, so the folder/slug rule must decide, never visual inspection or file-name similarity.

## e. What the text files look like

There is no `article.md`. The two files an agent needs per model are `产品事实.md` (facts) and `卖点与限制.md` (what may be said).

`产品事实.md` is a scraped official spec page, flattened: every spec is a heading, then the label on one line and the value on the next, separated by blank lines (not a markdown table). Footnotes start with `*`. It ends with scrape noise (the site's "leaving consumer.huawei.com" banner with continue/cancel buttons) that must be stripped. Layout (shape only; values replaced by placeholders):

```
## 尺寸与重量
重量
约 X.XX kg（变体A）
约 X.XX kg（变体B）
*<footnote: weight varies with configuration and measurement>
## 电池
容量
XX Wh（额定容量）
```

Units are written with a space and Latin abbreviations: `kg`, `mm`, `Wh`, `GB`, `Hz`, `nits`, `W`. Screen size is `XX.X 英寸`. Weight is kg in the spec file (the mall snapshot's one-line selling points use 克, e.g. "XXX 克"). Resolution is `XXXX × XXXX`. Qualifiers are part of the value and must travel with it: `约`, `典型值`, `峰值`, `额定容量`, `最高`, `含电池`. Unit style is not uniform across models: the overview shows `nits` for one model and `尼特` for another, and `ppi` vs `PPI`, so normalise before comparing.

`卖点与限制.md` is curated, structured text (not scraped). Its fixed sections: 一句话定位, 六个沟通角度 (each: 可用结论 / 支撑事实 / 表达边界), 适合进入候选清单的任务, 不适合直接下结论的任务, 发布或销售前必须追问, 建议的内容组织, 合规表达示例, 图片使用, 事实来源. This is the most directly usable file for fact-point extraction and compliance checking. It also states the KB's image rule: take images only from the target model's own index, record file name, source, content, insertion position and limits, and never let an exterior photo support a performance claim.

## f. Non-spec materials, prices and promotions

| Material | Where | Notes |
|---|---|---|
| Selling points and talk tracks | `P2` | By channel (retail, distribution, government/enterprise, education, after-sales, trade-in) and by model x persona (8 cards). These map well onto our scenarios: 学生 to 开学季, 商务差旅 to 职场办公, 内容创作者 to 内容创作, 旧机换新 to 家庭换新, 企业采购人 to 企业采购, 门店顾客 to 门店到店 |
| Compliance wording | inside `卖点与限制.md`, every P2 card ("合规边界"), and `00-建库规范` | Good source for our compliance rules |
| Platform rules, marketing cases, FAQ, customer scenarios | `P5` to `P8` | Not readable today (quota). Unknown |
| Competitors | `P3` | Comparisons; the KB marks them as needing sources |
| **Prices, discounts, gifts, stock** | `P1/08-官方公开价格快照` and `P1/04-华为商城销售款式` | **Present, and risky.** See below |

Price risk, in detail. The price cards contain real RMB amounts, strike-through prices, "直降" amounts, points-redemption, gift items, stock and shipping states ("现货", "预售", "缺货", "当日达"), all dated 2026-10-17 and tied to an exact SKU (RAM/storage/keyboard/screen/colour). Three things follow:
- Prices are in the KB, so quoting one is allowed in principle. But the KB's own rule says a price may only be cited with exact SKU, price type, conditions, source and verification time, and must never be written as "now" or "long-term". One model has up to 15 rows with different amounts, so "the price" of a model does not exist.
- A later fetch of the same page can disagree with the snapshot (the card itself shows one SKU as 可购买 at one time and 暂时缺货 at another). Conflicting KB entries mean stop and ask a human.
- The mall snapshot says it does not prove stock, long-term sale, subsidies or gifts. `卖点与限制.md` says price, stock, subsidy, gifts, sales volume and ranking are deliberately NOT stored in it.

I did not copy any price figure into this document.

## g. Do get_media_info URLs expire, and are the headers needed?

- Response shape: `{media_type, notebook_ext_info, url_info: {url, headers}}`.
- URL host is a Tencent COS domain (`skb.ima.myqcloud.com`). The query string carries `media_id`, `media_title`, `sign`, `t` (and `response-content-type` for text). `sign` + `t` indicate a signed, time-limited URL. I did not measure the lifetime. Treat it as short and never store it.
- `headers` holds six `X-IMA-*` keys (create-time, platform, resource category, sign, trace id, uid hash).
- Test: fetching an image URL with no headers returned HTTP 200. So headers are not required today. `ima_client.fetch_media` sends them anyway; keep that, because the API does return them for a reason and may start enforcing them.
- Text files come back as `text/markdown; charset=utf-8`, images as `image/png` or `image/jpeg`.
- Every `get_media_info` call counts toward a quota (see h).

## h. Surprises and risks for our design

1. **Fetch quota (ima code 220021): the main operational risk.** After roughly 100 uncached folder listings (spread over two walks within about 20 minutes), listings began failing with "资料获取次数已达上限，请明天再尝试". Calls to `get_media_info` kept working afterward (about 20 more fetches succeeded), so the cap may be per API. This is an inference from one session. The cap number and reset time are unknown. A live agent that browses folders per request will hit it. Consequences for the build:
   - The product index is built with **targeted listing calls only** (section i.1, about 25 calls), never a full-tree walk. No more full walks, for testing or otherwise.
   - The index lives in a **disk cache** (`.cache/`, gitignored) with a long TTL and a **stale-on-error fallback**: if a refresh fails with 220021 (or any error), serve the last good copy and show "KB index may be stale". A quota error is a degraded mode, never a crash.
   - Current state of `agent/ima_client.py`: disk cache by request hash, 30-minute default TTL, 220021 is not retried (good). **Missing:** on a failed call it does not fall back to an expired cache file, it raises. The stale-on-error fallback and the longer TTL are still to build (next phase, with the catalog module).
   - P5 to P8 will get one targeted, read-only listing after the quota resets. P4 content is not read, and the 403 folder is not retried.
2. **The brief's premise is wrong in two places.** The KB has 537 files, not ~314, and has no `article.md`. Anything keyed on `article.md` will find nothing.
3. **`explore_kb.py` `is_folder()` was wrong.** The starter looked for `folder_id`/`file_number` keys. Live folders are `media_type: 99` with a `folder_<n>` `media_id`. Fixed in the script (and `walk()` now records unlistable folders instead of crashing).
4. **Folder IDs.** The list API returns folder `media_id`s with a `folder_` prefix, and the walk passes that string back as `folder_id` and it works. Still: never construct IDs, only reuse returned ones.
5. **Partial listings must be visible.** One 403 folder or a quota error leaves part of the tree unread. The walk must report which folders are unlisted, and the UI must not present a model or image list as complete when it is not.
6. **Possible KB self-conflict.** The overview says MateBook Pro uses 麒麟 X90 Plus, while the mall snapshot treats "MateBook Pro 麒麟 X90 Plus" as a separate, newly added variant that should not share configuration with the base Pro. Not verified beyond these two files. Decision (WORKFLOW rule 4): if the article would use the CPU fact, stop and ask a human; otherwise exclude the CPU fact and list it under 待确认.
7. **Series-level folder names hide the real product** (GT 系列, X系列), and the mall/price/catalog name for a model differs from the folder name. A name-to-folder alias table is required.
8. **The 44 phantom images.** The joint image table advertises 112 images but 44 do not exist in the KB. If the agent used the table instead of the folder listing it would reference images it cannot fetch.
9. **Colour and screen variants.** An image may show 樱粉金 while the fact text is about the green 柔光 SKU. Correct model but wrong variant is still a defensible mismatch for a poster. Image captions should be stored and shown.
10. **Many scenarios have thin coverage.** Only 10 consumer models have images. 企业采购 with 擎云, and any monitor, printer or accessory, can only be text-only. Decision: articles are allowed for text-only products, with the image section marked 待确认 ("知识库无该型号图片") and never padded with other models' images. The poster platform requires exactly 1 key visual, so it is refused for text-only products.
11. **MateBook 14 鸿蒙版 vs 酷睿 Ultra is the most likely scoring trap.** The KB repeatedly says not to mix them, and a user who types "MateBook 14" matches both.
12. **Prices and subsidies are in the KB, but only P1/08 (public snapshots), not P4.** P4 (the "机密" price/policy library) was not listable. We must not infer policy from P1/08. For 国补/教育优惠/以旧换新 the KB says eligibility must be verified, so default to not mentioning them. Decision: prices are off by default. A later optional mode quotes exact-SKU prices only, with price type, date, conditions and "以官方页面实时信息为准"; a missing SKU means ask, conflicting snapshots mean stop.
13. **Sensitive/controlled folder.** P4 is labelled confidential and the KB rules say it needs authorization. We only read what the API lists to our account; do not try to work around the 403/quota.
14. **Starter `requirements.txt` was not installed in the repo `.venv`.** Smoke test ran with the parent `../.venv` interpreter. Fixed 2026-10-18: installed into the repo `.venv` and the imports verified.

## i. Proposed data layer (design only, nothing built yet)

Everything below is derived from section a to h. Module names follow `docs/WORKFLOW.md` (`agent/catalog.py` and friends) where it exists.

### i.1 Build the index from folder listings only

Walk only `P1/01-鸿蒙电脑` and `P1/02-MateBook-Windows` (about 25 listing calls: root, P1, the two route folders, 10 model folders, 11 image folders), not the whole KB (about 100 calls, which is what triggered the quota). `P2/07-按型号角色` adds about 11 more calls if persona cards are wanted. The walk records every folder it could not list and reports the index as `complete` or `partial`.

### i.2 ModelCatalog

One entry per model folder (10 today):

```
Model:
  model_id        slug taken from image file names, e.g. "matebook-14-harmonyos"  (unique, stable)
  canonical_name  official name from the model's 图片索引.csv 产品型号 column
                  e.g. "HUAWEI MateBook 14（鸿蒙版）". Never the folder name.
  folder_name     as in the KB, used only to locate files
  route           "harmonyos" | "windows"            (from 01 vs 02)
  aliases         hand-maintained list + folder name + price-card/catalog name
  siblings        model_ids in the same confusable group (section c)
  items           {facts, claims, image_index_csv, source_csv, images[], cards[]}  (refs, not content)
```

Hand-maintained `config/model_aliases.yaml` is small (10 rows) and is the place to record: "MateBook 14" is ambiguous; "GT" and "GT 14" mean GT 系列; "X Pro" and "微绒典藏版" mean X系列; "擎云" is text-only.

Matching (code, not LLM):
1. Normalise: lower-case, full-width to half-width, drop `HUAWEI` and spaces, split into tokens, add OS tokens (`鸿蒙版`/`HarmonyOS` and `酷睿`/`Windows`) as their own tokens.
2. Score against canonical name and aliases by token overlap. Never by substring or prefix.
3. Result is one of `resolved`, `ambiguous`, `not_found`:
   - `resolved` only if the query's token set equals one model's canonical or alias token set;
   - `ambiguous` if the query's tokens are a subset of two or more models' sets and equal none ("MateBook 14", "Pro", "D 16 SE" is fine, "16" is not), or if two models score within a small margin;
   - `not_found` otherwise, with the nearest 3 models as suggestions;
   - if the text-only catalog (P1/07) matches, return `text_only` with no images (e.g. 擎云).
4. `ambiguous` and `not_found` stop the pipeline and the UI asks the user to pick from the candidates, shown with canonical name, OS and processor. The pipeline never picks one itself.
5. SKU-level variant (keyboard, screen type, RAM/storage, colour) is a second, separate slot. It is not resolved from the model name. If the scenario needs it (price, weight, brightness) and it is missing, ask or write the fact with all variants and their qualifiers.
6. A known KB conflict on a model fact (e.g. the Pro CPU, section h item 6) marks that fact `needs_human`: if the article needs it, generation stops until a person confirms; otherwise the fact is excluded and listed under 待确认.

### i.3 get_model_bundle(model_id)

```
ModelBundle:
  model            the Model above
  facts_text       产品事实.md, scrape noise stripped (leave-site banner), nothing summarised
  claims_text      卖点与限制.md
  cards            optional: 6 lookup cards (core part only), P2 persona card for the scenario
  images           [ImageRef]
  sources          [SourceRecord]
  index_status     complete | partial (+ which folders were unlisted)

ImageRef:    media_id, title (file name), source_path (KB folder path), model_id,
             caption (画面说明), page_url (来源页面), width, height, folder_kind (images | 商城款式图片)
SourceRecord: title, source_path, media_id, media_type, fetched_at
```

- Every fact in the ledger cites a `SourceRecord`. The output's "知识库依据" section prints `title` and `source_path`, never `media_id`.
- Price cards are NOT in the default bundle. A separate `get_price_snapshot(model_id, sku)` exists, off by default, and returns only records whose SKU exactly matches the request, with date and conditions attached. If no exact SKU match exists, it returns nothing (no averages, no "from" prices, no nearest SKU).
- No `article.md` is assumed anywhere.

### i.4 THE rule that guarantees an image belongs to the target model

> An image is attached to model M only if **all three** hold:
> 1. **Folder**: the item was returned by listing a folder inside M's own subtree (`…/<M.folder_name>/**`). The folder is the identity.
> 2. **Slug**: the file name's slug (the text between the `hwpc_`/`vmall_` prefix and the next `_`) is **exactly equal** to `M.model_id`. Equality, never prefix (`matebook-d-16-2024` is a prefix of `matebook-d-16-se-2024`).
> 3. **Index row**: M's `图片索引.csv` has a row with this file name, and where that row names a model it equals `M.canonical_name`.
>
> Any disagreement drops the image and logs the reason. If the model's slug is not unique across the catalog, or a folder holds two slugs, the **whole model** is marked `image_index_invalid` and no images are offered for it (fail closed).

Enforced at three points:
- **Build time:** assert slug uniqueness and one slug per folder.
- **Plan time:** the writer can only choose from `bundle.images` by index, never by free text name, and never from search results or the joint table.
- **Check time:** a final validator re-derives the model of every image in the article from its `media_id` and compares with the target model(s). Mismatch means the article cannot be exported.

What the rule does not prove: that the picture shows the right colour or screen variant. The caption and `folder_kind` travel with the image into "图片说明" and into the 核验结果 "待确认信息" when the SKU is known (section d). Visual inspection is not used, because model identity is not readable from the pixels (section d).

Never used for identity: the joint image table (44 of its 112 rows point to files that do not exist), search hits, caption similarity, or an LLM's opinion.

### i.5 Caching: IDs and metadata, signed URLs at display time

| Layer | What | Where | Lifetime |
|---|---|---|---|
| Tree/catalog | folder listings → Model and ImageRef metadata, including `media_id` | `.cache/` on disk and in memory | long (24 h, plus manual refresh); on a quota error serve the last good copy and show "KB index may be stale" |
| Text docs | `产品事实.md`, `卖点与限制.md`, cards | memory (+ `.cache/`) | hours; texts change rarely |
| Signed URLs | never stored | not cached | resolved by `get_media_info` only when an image is actually shown or exported |
| Image bytes | fetched server-side right after resolving, kept in a small in-memory LRU for the session | memory only | minutes; never written into the repo or committed |

Notes:
- `ImaClient.call` already caches responses on disk by request hash and deliberately skips the cache for `get_media_info`. Keep both behaviours, but raise the folder-listing TTL (the default 30 minutes is too short for the quota situation) and add the stale-on-error fallback, which does not exist yet (section h item 1).
- A page view costs one `get_media_info` per displayed image, so only the 1 to 6 images chosen for the output are resolved, not the whole gallery.
- The cache holds KB metadata and text. It is local, gitignored, and must not be exposed through the app (no bulk export, no raw document viewer).
- On a cold start (e.g. ModelScope) the cache is empty and the first build costs about 25 calls. Pre-warm once at startup and tolerate partial results.

### i.6 Decisions (2026-10-18) and remaining open question

1. **WORKFLOW vs CLAUDE.md**: `docs/WORKFLOW.md` (v4) is the team's plan and wins over `CLAUDE.md`. No code migration yet (no ima_wrapper, no `ima-skill/` restore, no `CLAUDE.md` rewrite); the next phase does that in one step.
2. **Pro variants**: one model per KB folder. A bare "Pro" query (Pro vs Pro S) is ambiguous and the user is asked. The X90 Plus CPU conflict follows section h item 6.
3. **Text-only products** (擎云, monitors, etc.): articles allowed, image section marked 待确认 ("知识库无该型号图片"), never padded. Poster platform is refused for them.
4. **Prices**: off by default; later optional exact-SKU mode as in section h item 12.
5. **P4 to P8 and 联想**: after the quota resets (not on 2026-10-18), one targeted, read-only listing of P5 to P8 only. P4 content is not read. The 403 folder is not retried.
6. **Still open: quota.** What is the cap, and does the judges' demo share our key? The app needs the degraded mode in section h item 1 either way.
