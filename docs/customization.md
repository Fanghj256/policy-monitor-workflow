# 定制：换领域、换关键词、换报告

这套 workflow 的默认示例是「智能制造 / 数据要素 / 人工智能」，但代码不绑定这个领域。定制分五层，从轻到重：

1. **主题词表**：这条政策属于什么主题；
2. **信源与关键词**：抓哪些站、标题命中什么才抓；
3. **类型规则**：政策/申报/征求意见/解读怎么分；
4. **报告模板**：日报/周报/月报长什么样；
5. **提示词**：AI 初判的角色、输出格式、约束。

大部分团队只需要改 1–3；4–5 是展示和写作层的调整。

## 一、五步换领域

以「示例：从智能制造换成社区养老服务」为例（仍然是虚构领域，只演示方法）。

### 第 1 步：列出新领域的对象

先不要写代码，先列：

- **政策主体**：民政、卫健、住建、市场监管、街道/社区；
- **政策类型**：养老服务机构补贴、社区食堂、适老化改造、护理人才、长期照护；
- **时间敏感点**：申报截止、验收、征求意见、试点名单；
- **关键文件**：办法、细则、标准、规划、申报指南。

这张表决定信源、主题词和报告结构。

### 第 2 步：换主题词表

主题词表在 `sources/sources.example.yaml` 的 `taxonomy`（live）或 `examples/sources/demo_sources.json`（demo）。**配置里一旦提供 `taxonomy`，就会完整替换内置词表**；不想保留旧领域的词，就把需要的主题都写上。

```yaml
taxonomy:
  社区养老:
    - 社区养老
    - 居家养老
    - 养老服务
    - 日间照料
    - 老年助餐
  适老化改造:
    - 适老化
    - 无障碍
    - 家庭床位
  护理人才:
    - 护理员
    - 养老护理
    - 职业技能
  长期照护:
    - 长期护理
    - 长期照护
    - 失能等级
  标准合规:
    - 标准化
    - 等级评定
    - 服务质量
```

原则：

- 一个主题 4–10 个词，太多会误匹配；
- 避免「服务」「管理」这类泛词；
- 主题名用业务语言，不用部门语言；
- 先跑 20 条样本，看主题分布是否合理，再扩词。

### 第 3 步：换信源

按 `docs/sources.md` 的步骤加源。优先顺序：

1. 主管部门官网的政策/通知栏目；
2. 区/街道的申报通知；
3. 行业协会/公共服务平台；
4. 媒体/研究机构（只做参考）。

每个源至少填 `level`、`department`、`source_tier`、`keywords`。关键词只影响「标题要不要抓」，不要写太宽。

### 第 4 步：换类型规则

类型规则在 `scripts/parse.py` 的 `infer_type`。默认规则：

```python
"解读" -> 解读
"征求意见" -> 征求意见
"申报/征集/揭榜挂帅/遴选" -> 申报
"规划/行动计划/实施方案" -> 规划
"标准/标准化" -> 标准
"办法/规定/细则/意见/通知/决定/公告/措施/指引" -> 政策
其他 -> 其他
```

换领域时通常只需要：

- 加行业词：如「备案」「验收」「试点」「名单」；
- 调整顺序：如「申报指南」里也含「指南」，应归申报而不是政策；
- 加子类型：`subtype` 用于报告展示，不影响索引。

改完跑 10–20 条样本，检查 `type` 和 `subtype` 是否符合预期。

### 第 5 步：换报告模板

模板在 `templates/`，占位符是 `{{KEY}}`。`report.py` 只替换占位符，不解析 Markdown 结构。你可以：

- 改章节标题和文案；
- 增删章节（保留必需占位符即可）；
- 调整表格列（改 `report.py` 的 `item_table`）；
- 换语言（模板和提示词都是 Markdown）。

## 二、关键词的两层

| 层 | 位置 | 作用 | 误用后果 |
|---|---|---|---|
| 源级 `keywords` | `sources/*.yaml` | 标题命中才抓，减少无关条目 | 太窄会漏；太宽会噪声 |
| 主题 `taxonomy` | `sources/*.yaml` / demo JSON | 给已抓条目打主题标签 | 太宽会「每条都像」 |

建议：

- 源级关键词用「领域词 + 动作词」：`智能工厂`、`申报`、`征求意见`；
- 主题词用「业务对象 + 政策工具」：`公共数据`、`数据授权`、`数据流通`；
- 每季度看一次主题分布，清理长期 0 条或过宽的词。

## 三、模板占位符

### 日报 `templates/daily-brief.md`

| 占位符 | 内容 |
|---|---|
| `{{DATE}}` | 日期 `YYYY-MM-DD` |
| `{{WINDOW_NOTE}}` | 统计口径说明 |
| `{{GENERATED_AT}}` | 生成时点 |
| `{{ITEM_COUNT}}` | 条目数 |
| `{{OVERVIEW}}` | 概览 bullet |
| `{{HIGHLIGHTS}}` | 建议先看 3 条 |
| `{{ITEMS}}` | 全部新增表 |
| `{{DEADLINES}}` | 截止表 |
| `{{SOURCES}}` | 来源表 |

### 周报 `templates/weekly-report.md`

| 占位符 | 内容 |
|---|---|
| `{{WEEK}}` | ISO 周，如 `2026-W46` |
| `{{RANGE}}` | 周一到周日 |
| `{{GENERATED_AT}}` | 生成时点 |
| `{{ITEM_COUNT}}` | 条目数 |
| `{{LEVEL_SUMMARY}}` | 层级分布一句话 |
| `{{SIGNALS}}` | 3–5 条信号 |
| `{{TABLE}}` | 全部条目表 |
| `{{DEADLINES}}` | 截止日历 |
| `{{WATCHLIST}}` | 下周观察清单 |
| `{{SOURCES}}` | 来源覆盖 |
| `{{METHOD_NOTE}}` | 方法与限制 |

### 月报 `templates/monthly-report.md`

| 占位符 | 内容 |
|---|---|
| `{{MONTH}}` | `YYYY-MM` |
| `{{GENERATED_AT}}` | 生成时点 |
| `{{ITEM_COUNT}}` | 条目数 |
| `{{OVERVIEW}}` | 总量/层级/类型/环比 |
| `{{DISTRIBUTION}}` | 主题/层级/类型分布 |
| `{{TRENDS}}` | 计数趋势 |
| `{{INCREMENTS}}` | 重点增量 |
| `{{RECOMMENDATIONS}}` | 下月建议 |
| `{{APPENDIX}}` | 全部条目 |
| `{{METHOD_NOTE}}` | 方法与限制 |

### 政策卡片 `templates/policy-card.md`

| 占位符 | 内容 |
|---|---|
| `{{TITLE}}` / `{{DOC_ID}}` | 标题 / 条目 ID |
| `{{ISSUER}}` / `{{DOC_NUMBER}}` | 机构 / 文号 |
| `{{PUBLISH_DATE}}` / `{{DEADLINE}}` | 发布 / 截止 |
| `{{LEVEL}}` / `{{TYPE}}` / `{{THEMES}}` | 层级 / 类型 / 主题 |
| `{{SOURCE_URL}}` | 原文 |
| `{{SUMMARY}}` / `{{BODY_EXCERPT}}` | 摘要 / 摘录 |
| `{{REVIEWER}}` / `{{REVIEW_DATE}}` | 核验人 / 日期 |

`report.py` 只渲染前三类；政策卡片是给人手工填的模板，或由工作台填充。

## 四、改报告窗口

`report.py` 的 `select_items` 决定「哪些条目进哪份报告」：

- 日报：`first_seen == date`（首次发现日）；
- 周报：`publish_date` 在 ISO 周内；
- 月报：`publish_date` 在自然月内；
- 没有发布日期的条目，退回 `first_seen`。

想改成「按发布日期归日」：把日报条件改成 `publish_date`，并在文档里说明口径变化。不要同时用两个口径，否则同一条会在两份日报里重复。

## 五、改提示词

`prompts/` 里四份提示词：

- `daily.md`：当日新增的初判；
- `weekly.md`：3–5 条信号；
- `monthly.md`：趋势/增量/建议；
- `source-discovery.md`：找新源和验收。

改提示词时保留四个约束：

1. 只使用输入里的条目，不补外部事实；
2. 事实和推断分开；
3. 不编造日期、文号、截止；
4. 输出是草稿，不是签发稿。

如果模型支持结构化输出，建议让它输出 JSON（字段见提示词），再由工作台渲染；不要让模型直接写最终 Markdown，否则格式会漂。

## 六、改输出路径

默认路径：

| 模式 | raw | items | index/reports |
|---|---|---|---|
| demo | `data/demo/raw/` | `examples/items/` | `examples/outputs/` |
| live | `data/raw/` | `data/items/` | `outputs/` |

脚本都支持显式路径：

```bash
python scripts/fetch.py --config sources/sources.local.yaml --out var/raw
python scripts/parse.py --raw var/raw/raw.json --out var/items
python scripts/index.py --items var/items --out var/index
python scripts/report.py --index var/index/index.json --out var/reports
```

如果换路径，记得同步工作台读取路径和 `.gitignore`。不要把 `data/` 和 `outputs/` 提交到公开仓库。

## 七、换语言 / 换地区

- **语言**：模板、提示词、字段标签都是中文；换成英文时，保留 `doc_id`、字段名和 `schema_version` 不变，只改展示文案。
- **地区**：`level` 的词表可以换（如 `federal / state / local`），但要在 `parse.py` 的 `LEVEL_PREFIX` 和 `priority_for` 里同步，否则 `doc_id` 前缀和排序会怪。
- **日期**：内部统一 `YYYY-MM-DD`；展示层可以本地化，但不要改存储格式。

## 八、定制后的验收

- [ ] `python -m py_compile scripts/*.py` 通过；
- [ ] `python scripts/run_pipeline.py --demo` 仍能跑；
- [ ] 用 20–50 条真实样本跑一遍，主题分布合理；
- [ ] 日报/周报/月报各生成一份，章节完整；
- [ ] 抽 5 条回原文，标题/日期/文号正确；
- [ ] `changes.csv` 连续跑两次，第二次为空（无变化）；
- [ ] 模板里的占位符没有残留 `{{...}}`；
- [ ] 工作台能读 `index.json`，`schema_version` 未变。

## 九、不要这样定制

- 不要把判断逻辑写进模板（模板只展示，不计算）。
- 不要让 AI 直接改 `index.json`。
- 不要为了一个源改坏通用选择器；用源级配置。
- 不要把真实凭据写进示例配置。
- 不要把「今天没抓到」解释成「今天没政策」；先看 `health.csv`。
