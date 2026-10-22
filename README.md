# 华为 PC 门店图文软文 Agent

浙客松 AI+X 破界黑客松 · 华为赛道参赛作品。

**门店店员打开应用，今天要发的那条软文已经写好了。** Agent 根据门店周边客群、门店销量与同类门店的差距、全国活动、新品与节日日历，每天早上为每家门店挑出「今日一条」，写成适配朋友圈 / 小红书 / 公众号 / 海报 / 抖音图文的图文软文。每条产品事实、每张产品图片都来自 ima 共享知识库「任德耀新建华为PC知识库」，并经过事实、合规、平台、去 AI 味、跨店相似度五道核验。店员看一眼、点复制、发出去，再点「标记为已发布」，总部就能看到。

它针对华为提出的三个痛点：

| 痛点 | 我们的做法 |
|---|---|
| 门店被要求定期发帖，店员没时间、写不好，发帖变成形式主义 | **推送模式**：每天早上预先生成，打开即用；附「为什么推这条」；一键复制、下载发布包 |
| 统一下发的文案一股 AI 味、千店一面 | 按门店周边客群定角度、门店语气与地标、去 AI 味检查（8D）、跨店相似度检查（8E） |
| 大模型写新品容易编参数、过度承诺 | **双温度设计**：事实在温度 0 下锁定，只有文字表达有创意；**新品由总部核验一次，门店再生成**；数字、价格、首发措辞全部可追溯 |

## 界面

一个 FastAPI 服务（`server.py`）同时提供接口和 Vue 前端（`frontend/`）。

| 页面 | 给谁用 | 内容 |
|---|---|---|
| **门店端**（默认页） | 店员 / 店长 | 今日一条：推荐型号、平台、「为什么推这条」（模拟数据有标注）；打开即显示早上预先生成的文案；重新生成、换一条（活动款 / 新品款 / 顾客问答）；手机预览、快速调整（短一点 / 换卖点 / 换个角度）、正文可直接修改并重新核验；复制文案、下载发布包 / .md、保存图片、标记为已发布；本周发布进度、顾客提问记录、导购话术 |
| **生成** | 店员 | 不走推荐时手动生成：「点选」四步（产品 → 顾客 → 场景 → 平台）或「直接输入」一句话；信息不全时用选项追问 |
| **总部端** | 总部运营 | 各门店发布情况、本周平台计划、推荐分布、新品上市审核（确认发布后新品款对所有门店解锁）、顾客高频问题、重置演示 |
| **登录** | 所有人 | 选择门店与身份（店员 / 店长），或总部账号；工程师入口 |
| **四店对比**、**对照组** | 工程师（演示功能） | 同一产品在四家门店的文案并排对比；未经约束的普通大模型输出 vs 我们的结果。需在「登录 → 工程师入口」输入 `ENGINEER_PASSCODE` 才显示（只是隐藏，不是权限控制） |

左下角「系统状态」显示知识库连接、索引状态、模型名，密钥只显示「已配置」。

## 快速开始

需要 **Python 3.10+** 和 **Node.js 18+**（前端构建，以及 `ima-skill/ima_api.cjs` 调用 ima）。

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt     # Windows: .venv\Scripts\pip
cp .env.example .env                          # 填入自己的密钥，切勿提交

npm --prefix frontend install                 # 首次
npm --prefix frontend run build               # 前端代码改动后重新执行

python server.py                              # http://localhost:7861
```

- 端口用 `PORT` 修改（默认 7861）。打开页面看到「frontend 未构建」说明漏了 `npm run build`。
- **改前端时**用开发模式，保存即刷新：一个终端 `python server.py`，另一个终端 `npm --prefix frontend run dev`，打开 <http://localhost:5173>（`/api` 自动转发到 7861）。
- **早上预生成**（推送模式的关键，录制前执行）：

  ```bash
  python scripts/prepare_today.py --today 2026-10-23          # 每家门店的今日一条，朋友圈 + 小红书（必要时 + 公众号）
  python scripts/prepare_today.py --today 2026-10-23 --demo   # 另外生成其他推荐、四店对比、对照组
  python scripts/prepare_today.py --today 2026-10-23 --fake   # 不调用 ima / LLM 的彩排，写到 runs/_rehearsal/
  python scripts/prepare_today.py --today 2026-10-23 --only S01:小红书,S08:公众号   # 只重做指定门店 + 平台的版本
  ```

  未预生成时应用照常可用，只是门店端打开后要现场生成（演示日实测每条约 1 分钟，慢时数分钟）。

### 配置（`.env`）

| 变量 | 作用 |
|---|---|
| `IMA_OPENAPI_CLIENTID`、`IMA_OPENAPI_APIKEY` | ima 凭证，在 <https://ima.qq.com/agent-interface> 获取；账号需已加入共享知识库「任德耀新建华为PC知识库」 |
| `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_MODEL_FAST` | 任意 OpenAI 兼容端点（如 DashScope / Qwen、DeepSeek） |
| `KB_BACKEND`、`KB_LOCAL_DIR` | 知识库来源，见下表 |
| `WRITER_TEMPERATURE` | 撰写温度（默认 0.85）；事实提取与核验固定为 0 |
| `DEMO_TODAY` | 演示日期（默认 `2026-10-23`） |
| `ENGINEER_PASSCODE` | 解锁「四店对比」「对照组」的口令；不设置则这两个页面不可用 |
| `PORT` | 服务端口（默认 7861） |

未配置密钥时，应用以**开发模式**运行在合成数据（DemoBook）上，系统状态里会明确标注「部分模块为模拟数据」。

### 知识库来源

仓库**不包含**知识库镜像（`kb_snapshot/` 在 `.gitignore` 中）。`KB_BACKEND` 决定资料来源：

| `KB_BACKEND` | 资料来源 | 新克隆的仓库 |
|---|---|---|
| `ima`（默认） | ima 实时接口（需凭证） | 直接可用 |
| `hybrid`（推荐录制时用） | 本地镜像 + ima 实时确认 | 需要镜像；镜像缺失且已配置 ima 凭证时自动改用实时接口 |
| `local` | 只读本地镜像，零 ima 调用 | 需要镜像；缺失时给出明确提示 |

镜像向队友获取，解压到 `kb_snapshot/kb_v7/`（或用 `KB_LOCAL_DIR` 指向解压目录）。镜像只供本机使用，不得提交、上传或转发。

## 工作原理

```
门店信号（周边 POI · 销量 · 活动 · 新品 · 日历 · 顾客提问）
   │  agent/recommend/：潜力款 / 活动款 / 新品款 / 顾客问答 → 今日一条 + 「为什么推这条」（模板生成，不经 LLM）
   ▼
推荐卡片（型号、平台、角度、语气、地标、场景）
   │  agent/pipeline.py
   ▼
资料检索（ima）→ 事实台账（温度 0，逐字原文引用）→ 卖点匹配（冲突即停）→ 按型号 ID 选图
   → 撰写（温度 0.85，每条主张引用事实编号）
   → 核验循环：8A 事实 · 8B 合规与价格 · 8C 平台规范 · 8D 去 AI 味（最多 2 轮定向改写）
   → 8E 跨店相似度：同日同类门店文案过于相似时，换开头 / 角度重写一次
   → 仍未通过：删句 → 换下一张卡 → 「需人工确认」，未通过核验的文案绝不交付
   ▼
四段式输出（一、场景判断 / 二、知识库依据 / 三、图文软文 / 四、核验结果）+ 手机预览 + 可直接发布的正文
```

完整说明（架构、知识库调用、提示词、事实台账、图片规则、核验、平台适配、运行结果、已知限制）见 [`docs/项目说明.md`](docs/项目说明.md)。

## 输出样例

[`samples/`](samples/README.md) 是 2026-10-23 演示日的真实输出，由 `scripts/export_samples.py` 从运行记录自动导出、未经手工编辑：校园 / 写字楼 / 社区 / 商圈门店的今日一条（朋友圈、小红书、公众号）、同类型门店不雷同、同型号换角度、新品锁定、以及一条「需人工确认」。只含可直接发布的文案、推荐理由与核验结果，不含知识库原文、文章路径或图片。

## 演示数据

门店、销量、活动（含演示活动价）、顾客提问、发布记录均为**合成数据**（主办方已确认允许），界面上标注「模拟数据」/「演示活动」；**产品事实与图片始终来自 ima 知识库**。数据与生成脚本在 [`data/demo/`](data/demo/README.md)：

```bash
python scripts/gen_fake_data.py --today 2026-10-23   # seed=42 时与仓库内文件一致
```

## 测试

```bash
.venv/bin/python -m pytest -q          # 全部跑在 fakes 上，不调用 ima / LLM
RUN_E2E=1 .venv/bin/python -m pytest -q  # 额外跑真实端到端测试（需要凭证）
```

## 项目结构

```
server.py               # FastAPI：/api/*（JSON 与 NDJSON 流式进度）+ 托管 frontend/dist
frontend/               # Vue 3 + Vite 前端（views/：门店端、生成、总部端、登录、四店对比、对照组）
ui/                     # 与框架无关的界面逻辑：state.py（门店端会话）、hq_view / compare_view / baseline_view、components.py
agent/
  schemas.py            # 共享类型（团队契约）
  pipeline.py           # 编排：run / run_from_card / edit / generate_batch / generate_baseline，核验循环与兜底
  recommend/            # 推荐：POI 客群、销量潜力、活动、新品、日历、周平台计划、推荐理由
  ima_wrapper.py catalog.py retrieval.py platform_plan.py   # ima 只读封装、型号目录、资料检索、按型号选图
  ledger.py units.py fact_cache.py                          # 事实台账、单位归一、按产品缓存
  checks/ platform_rules.py style/                          # 8A–8C 核验、平台规范、8D 去 AI 味 / 8E 相似度
  llm.py intake.py scenario.py reconcile.py writer.py       # LLM 各阶段
  formatter.py export.py runs.py ui_data.py                 # 四段式输出、导出、运行记录、界面数据接口
prompts/  config/       # 提示词；禁用词、竞品、场景、型号别名、数字白名单等配置
data/demo/              # 合成门店数据与生成模板
scripts/                # prepare_today、gen_fake_data、export_samples、eval_cards、freeze_check 等
samples/                # 真实输出样例
ima-skill/ima_api.cjs   # ima 官方统一调用脚本（原样保留）
docs/                   # 项目说明、工作流、契约、知识库结构、设计文档
tests/                  # 单元测试（fakes）+ RUN_E2E=1 的真实测试
```

## 安全与合规

- 知识库只读；仅调用 `search_knowledge_base`、`get_knowledge_list`、`search_knowledge`、`get_media_info` 四个接口。
- 密钥与 Client ID 只存在于环境变量；界面只显示「已配置」，日志与错误信息会过滤；图片以内嵌数据提供，页面上不出现媒体 ID 或访问链接。
- 仓库不包含知识库原文、引用、价格、文章路径或图片文件；测试使用合成数据。唯一例外是 `samples/` 中导出的发布文案，导出时会扫描并拒绝密钥、原文引用、媒体 ID、图片文件名与文章路径。
- 公开演示有按会话与全局的限流；不提供知识库原文浏览或批量导出。
- 不输出「最 / 第一 / 唯一 / 顶级 / 全网 / 首选」等绝对化用语；不虚构价格、销量、库存、奖项、评测、政策；文案不出现店员姓名。

---

## English (short)

A hackathon agent for Huawei PC retail stores. When a store employee opens the app, **today's post is already written for their store**: the recommender picks a product from local audience (POI), under-selling vs. peer stores, national promotions, new releases and the calendar; the pipeline writes it for 朋友圈 / 小红书 / 公众号 / poster / 抖音 with every fact and image traced to an ima shared knowledge base. Facts are locked at temperature 0 and the writer only varies wording; every post passes five checks (facts, compliance and prices, platform, anti-AI style, cross-store similarity) with up to two targeted rewrites, and a post that still fails is never delivered. HQ verifies a new product's facts once, then every store can generate from them.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                                          # ima Client ID/Key + an OpenAI-compatible LLM endpoint
npm --prefix frontend install && npm --prefix frontend run build
python scripts/prepare_today.py --today 2026-10-23            # optional morning precompute
python server.py                                              # http://localhost:7861
```

Runs fully on synthetic fakes without keys. Architecture and results: [`docs/项目说明.md`](docs/项目说明.md).
