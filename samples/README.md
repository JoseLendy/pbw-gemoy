# 输出样例

由 `scripts/export_samples.py` 从 2026-10-23 的**真实运行记录**（runs/，未纳入仓库）自动导出，未经手工编辑。
文案为店员复制即发的版本（已去掉事实编号）；不含配图图片、图片文件名与知识库文章路径；不含知识库原文引用，事实来源统一标为「知识库产品参数」。

| 样例 | 展示什么 |
|---|---|
| [S01-potential-moments.md](S01-potential-moments.md) | 地域定向：校园店（高校周边 → 学生客群）的今日一条；核验可追溯（四、核验结果：事实编号 → 字段 → 文中取值） |
| [S02-promo-moments.md](S02-promo-moments.md) | 同类型门店也不雷同：与 S01 同为校园店，文案相似度 0.023（3-gram Jaccard，阈值 0.55）；核验可追溯（四、核验结果：事实编号 → 字段 → 文中取值） |
| [S04-promo-moments.md](S04-promo-moments.md) | 地域定向：写字楼（CBD）店 → 上班族客群；核验可追溯（四、核验结果：事实编号 → 字段 → 文中取值） |
| [S08-potential-moments.md](S08-potential-moments.md) | 地域定向：社区店 → 家庭客群；核验可追溯（四、核验结果：事实编号 → 字段 → 文中取值） |
| [S10-potential-moments.md](S10-potential-moments.md) | 同一型号、不同角度：与 S01 同型号，商圈店换成送礼/到店体验角度；核验可追溯（四、核验结果：事实编号 → 字段 → 文中取值） |
| [S01-new_release-locked.md](S01-new_release-locked.md) | 新品闸门：资料未经总部确认时直接锁定，不生成 |
| [S01-edit-blocked.md](S01-edit-blocked.md) | 价格拦截：「加上立减500」没有活动记录，写作前即拦截 |
| [S07-needs-review.md](S07-needs-review.md) | 兜底：两轮改写、删句、换卡后仍未通过 → 需人工确认，不交付 |

**说明**：门店销量、库存、活动（含演示活动价）、顾客提问与发布记录均为**模拟数据**（标注「模拟数据」/「演示活动」）；产品事实与图片来自 ima 共享知识库，每条产品说法都带事实编号、经过核验。
