# 华为 PC 图文软文 Agent

浙客松 AI+X 破界黑客松 · 华为赛道参赛作品。一句话描述顾客需求，自动产出一篇**每条事实、每张图片都能追溯到 ima 共享知识库「任德耀新建华为PC知识库」**的图文软文，适配公众号 / 小红书 / 门店朋友圈 / 门店海报 / 抖音图文。

**闭环**：输入 → 型号识别（有歧义就用选项卡片追问）→ 场景分析 → 读取知识库资料 → 事实台账（逐条原文引用核验）→ 卖点匹配（资料冲突时停止，请人工确认）→ 图片规划（按型号 ID 严格匹配）→ 撰写 → 核验循环（事实 / 合规 / 平台规范，最多 2 轮定向改写）→ 四段式输出 + 手机预览 + 一键复制 / 下载。

## 快速开始

```bash
python -m venv .venv                        # 或用已存在的 .venv
.venv/bin/pip install -r requirements.txt   # Windows: .venv\Scripts\pip
cp .env.example .env                        # 填入自己的密钥，切勿提交
python app.py                               # http://0.0.0.0:7860
```

- **知识库**：需要你的 ima 账号已加入共享知识库「任德耀新建华为PC知识库」。
- **ima 密钥**：在 <https://ima.qq.com/agent-interface> 获取 Client ID / API Key，只放进环境变量（`IMA_OPENAPI_CLIENTID`、`IMA_OPENAPI_APIKEY`）。
- **Node.js 18+**：`ima-skill/ima_api.cjs` 通过 subprocess 调用，需在 PATH 中。
- **LLM**：任意 OpenAI 兼容端点，配置 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_MODEL_FAST`。
- 未配置密钥时，应用以**开发模式**运行在合成数据（DemoBook）上，状态栏会明确标注「部分模块为模拟数据」。

## 项目结构

```
app.py                  # Gradio 界面（手机预览、话术卡、核验横幅、快捷编辑、下载）
agent/
  schemas.py            # 共享类型（团队契约）
  pipeline.py           # 编排：run / edit / 核验循环；Deps.real/fake/auto
  formatter.py          # 四段式输出、可发布正文、下载 .md
  ima_wrapper.py        # ima 只读封装（P1）
  catalog.py retrieval.py platform_plan.py      # 型号目录、资料与图片、图片规划（P1）
  ledger.py units.py                            # 事实台账、单位归一（P2）
  checks/ platform_rules.py                     # 8A 事实 / 8B 合规 / 8C 平台（P3）
  llm.py intake.py scenario.py reconcile.py writer.py   # LLM 各阶段（P4）
ima-skill/ima_api.cjs   # 官方统一调用脚本（原样保留）
docs/                   # 契约、工作流、知识库结构、项目说明
static/phone.css        # 手机预览样式
tests/                  # 单元测试（全部跑在 fakes 上）+ RUN_E2E=1 的真机测试
```

## 安全与合规

- 知识库只读；仅调用 `search_knowledge_base`、`get_knowledge_list`、`search_knowledge`、`get_media_info` 四个接口。
- 密钥与 Client ID 只存在于环境变量；界面只显示「已配置」，日志与错误信息会过滤。
- 仓库不包含任何知识库原文、引用、价格或图片文件；测试使用合成数据（DemoBook）。
- 公开演示有限流、按会话配额与全局每小时上限；不提供知识库原文浏览或批量导出。
- 不输出「最 / 第一 / 唯一 / 顶级 / 全网 / 首选」等绝对化用语；不虚构价格、销量、奖项、评测、政策。

---

## English (short)

A hackathon agent that writes illustrated Huawei PC marketing posts in Chinese. Every fact and image is traced to an ima shared knowledge base: a quote-verified fact ledger, a strict model-ID image rule, a three-stage check loop (facts / compliance / platform) with at most two targeted rewrites, and a four-section output with a phone preview. Runs fully on synthetic fakes without keys. See `docs/项目说明.md` for architecture.

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # ima Client ID/Key + an OpenAI-compatible LLM endpoint
python app.py          # http://0.0.0.0:7860  (Node.js 18+ required for ima)
```
