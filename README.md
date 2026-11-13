# 政策监测 Workflow · Policy Monitor Workflow

> **English abstract.** A reusable, source-first workflow for monitoring public policy updates. It fetches public listing pages, archives the original HTML, normalizes titles, dates, document numbers and deadlines, builds a stable `index.json` plus a `changes.csv`, and renders daily, weekly and monthly report drafts. The scripts deliberately stop at collection, normalization, indexing and change detection; relevance, impact and sign-off stay with people, and AI is used only for first-pass triage. The demo is fully offline, uses fictional data and needs nothing beyond the Python standard library.

这是一套从「每天手工翻政策网站」里抽出来的通用工作流：**先接信源、存原文，再做索引和报告**。它不绑定某个行业、某个城市或某个工作台，换一套信源和关键词就能用在新的监测主题上。

## 这是什么

- 一个**可离线运行**的政策监测流水线：`采集 → 解析 → 索引 → 变更 → 日报/周报/月报草稿`。
- 一个**可直接抄的配置和模板**：信源 YAML、主题词表、三类报告模板、四份提示词。
- 一个**给非技术同事看的操作说明**：每天做什么、每周做什么、源失效怎么办。
- 一个**给开发者的数据契约**：`index.json` 是稳定读模型，`changes.csv` 是变更流水，Markdown 只是展示层。

## 不是什么

- **不是政策数据库**。仓库里只有 8 条虚构示例，没有真实政策、真实机构或真实联系方式。
- **不是自动签发系统**。脚本不会判断「这条政策对我们重不重要」，也不会自动对外发布。
- **不是爬虫框架**。它只处理公开列表页和详情页；不绕过登录、验证码、付费墙或访问控制。
- **不是法律意见**。报告是监测草稿，适用性、合规义务和行动建议必须由人核验。
- **不替代原文**。摘要和字段抽取都可能出错；每条都保留原文链接和解析警告。

## 核心原则

1. **先信源，后输出。** 没有稳定的信源清单，就没有可复现的监测；报告只是流水线的最后一公里。
2. **先存档，再加工。** 原始 HTML 和条目 JSON 都落盘；报告可以重生成，原文不能靠记忆。
3. **脚本只做机械工作。** 采集、去重、字段抽取、索引、变更记录、模板渲染，都是可验证的规则。
4. **判断和签发留给人。** 相关性、影响、优先级取舍、对外措辞，由人完成；AI 只做初判和草稿。
5. **离线可复现。** demo 不联网、不依赖第三方包，任何人 clone 后都能跑出同样的结果。

## Quick start（30 秒，离线）

要求：Python 3.10+。demo 只用标准库，不需要 `pip install`。

```bash
cd policy-monitor-workflow
python scripts/run_pipeline.py --demo
```

你会得到：

```text
data/demo/raw/raw.json                 # 原始记录（demo 内联 HTML）
data/demo/raw/health.csv               # 信源健康
examples/items/*.json                  # 8 条标准化条目
examples/outputs/index.json            # 索引（给工作台/人读）
examples/outputs/changes.csv           # 变更流水（Excel 可直接打开）
examples/outputs/daily/2026-11-12.md   # 日报草稿
examples/outputs/weekly/2026-W46.md    # 周报草稿
examples/outputs/monthly/2026-11.md    # 月报草稿
```

demo 数据固定在 2026 年 11 月，方便对照。想换日期：

```bash
python scripts/run_pipeline.py --demo --date 2026-11-13
```

也可以逐段跑，便于调试：

```bash
python scripts/fetch.py --demo
python scripts/parse.py --demo
python scripts/index.py --demo --fresh
python scripts/report.py --demo --kind all --date 2026-11-12
```

> `index.py --demo` 不带 `--fresh` 时会和上一版 `index.json` 比较；第二次跑就可能显示「未变 8 条」。这是变更检测在工作，不是 demo 坏了。一键 demo 每次都从零开始，保证示例稳定。

## 目录

```text
policy-monitor-workflow/
├── README.md
├── LICENSE                  # MIT：代码
├── LICENSE-docs             # CC BY 4.0：文档、提示词、模板
├── LICENSE-data             # CC0：示例数据
├── SECURITY.md
├── requirements.txt         # 仅 live 模式需要；demo 不用
├── docs/
│   ├── architecture.md      # 源→抓取→解析→索引→变更→报告
│   ├── sources.md           # 怎么加源、源类型、选择器、健康检查
│   ├── workflow.md          # daily/weekly/monthly 流程与工作台接入
│   ├── customization.md     # 换领域、换关键词、换模板
│   └── desensitization.md   # 从私人项目公开前的脱敏清单
├── sources/
│   └── sources.example.yaml # 11 个虚构示例源
├── scripts/
│   ├── common.py            # 日期、JSON、迷你 DOM/CSS 选择器
│   ├── fetch.py             # 采集
│   ├── parse.py             # 字段抽取与规范化
│   ├── index.py             # index.json + changes.csv
│   ├── report.py            # 日报/周报/月报
│   ├── export_workbench.py  # 导出 workbench 数据包
│   └── run_pipeline.py      # 一键 demo/live
├── prompts/
│   ├── daily.md             # AI 日报初判
│   ├── weekly.md            # AI 周报 3–5 条信号
│   ├── monthly.md           # AI 月报趋势/增量/建议
│   └── source-discovery.md  # 找新信源与验收
├── templates/
│   ├── daily-brief.md       # 1 页日报
│   ├── weekly-report.md     # 3–5 条信号
│   ├── monthly-report.md    # 趋势 + 增量 + 建议
│   └── policy-card.md       # 单条政策卡片
└── examples/
    ├── sources/             # 4 个离线 HTML 快照 + demo 配置
    ├── items/               # 8 条虚构条目 JSON
    └── outputs/             # 索引、报告，以及 workbench/ 数据包
```

## 流水线

| 阶段 | 脚本 | 输入 | 输出 | 只做什么 |
|---|---|---|---|---|
| 采集 | `fetch.py` | `sources/*.yaml` 或 demo 快照 | `raw.json`、`html/`、`health.csv` | 取列表、取详情、存档、记录失败 |
| 解析 | `parse.py` | `raw.json` + HTML | `items/<doc_id>.json` | 抽标题/正文/日期/文号/机构/截止/施行日期 |
| 索引 | `index.py` | `items/*.json` | `index.json`、`changes.csv` | 汇总、排序、变更比对、统计 |
| 报告 | `report.py` | `index.json` + `templates/` | `daily/*.md` 等 | 按模板填数据，不做判断 |
| 导出（可选） | `export_workbench.py` | `index.json` + 报告 | `workbench/index.json` 等 | 投影成 agent-workbench-template 数据包 |
| 初判 | `prompts/*.md` | 条目/索引 | AI 草稿 | 摘要、信号候选、待核验问题 |
| 签发 | 人 | 草稿 + 原文 | 对外版本 | 判断、改写、负责 |

更细的契约见 [docs/architecture.md](docs/architecture.md)。

## 输出物

### `index.json`

给人和工作台读的稳定读模型。每条只放展示/筛选需要的字段，正文在 `items/` 里。

```json
{
  "schema_version": "1.0",
  "generated_at": "2026-11-12T18:00:00+08:00",
  "mode": "demo",
  "stats": {
    "items": 8,
    "added": 8,
    "updated": 0,
    "removed": 0,
    "unchanged": 0,
    "by_level": {"市级部门": 4, "市级": 2, "区级": 2}
  },
  "items": [
    {
      "doc_id": "CITY-2026-57699d4f",
      "title": "关于组织开展2026年度示例市智能工厂梯度培育申报工作的通知",
      "issuer": "示例市经济和信息化局",
      "doc_number": "示例经信〔2026〕42号",
      "level": "市级部门",
      "type": "申报",
      "themes": ["智能制造"],
      "publish_date": "2026-11-09",
      "deadline": "2026-12-05",
      "status": "待研判",
      "priority": 5,
      "summary": "为加快推动制造业数字化转型……",
      "source_url": "https://jxj.example.gov.cn/zcwj/2026/11/09/item-001.html",
      "content_path": "examples/items/CITY-2026-57699d4f.json",
      "review": {"required": true, "reasons": ["核对申报对象、材料清单与截止时间"]},
      "change": "added"
    }
  ]
}
```

关键点：

- `schema_version` 用于工作台判断兼容性；字段只增不删时升小版本。
- `doc_id` 稳定，由「层级前缀 + 年份 + URL 哈希」组成；同一 URL 重跑不会变。
- `content_path` 是相对仓库根目录的路径，不含本机绝对路径。
- `review.required` 永远为 `true`：脚本不替人做相关性判断。
- `change` 是 `added / updated / unchanged / removed` 之一。

### `changes.csv`

一行一次变化，UTF-8 BOM，Excel 直接打开：

```text
change_id,change_type,doc_id,title,issuer,level,publish_date,changed_fields,detected_at,source_url
chg-1a2b3c4d5e,added,CITY-2026-57699d4f,...,2026-11-12T18:00:00+08:00,...
```

用途：做「本周新增了哪些」「某条政策改过几次」的流水；不要拿它当政策全文库。

### 报告草稿

- **日报**：1 页。概览、建议先看 3 条、全部新增表、截止提醒、核验清单。
- **周报**：3–5 条信号 + 全部条目表 + 截止日历 + 下周观察清单 + 来源覆盖。
- **月报**：总量/层级/类型/主题分布 + 计数趋势 + 重点增量 + 下月建议 + 附录。
- 三份报告都可以直接复制成文档；模板见 `templates/`，占位符见 [docs/customization.md](docs/customization.md)。

## Live 模式

demo 是假数据；接真实信源时：

```bash
cp sources/sources.example.yaml sources/sources.local.yaml
python -m pip install -r requirements.txt
python scripts/run_pipeline.py --config sources/sources.local.yaml
```

Windows PowerShell：

```powershell
Copy-Item sources/sources.example.yaml sources/sources.local.yaml
python -m pip install -r requirements.txt
python scripts/run_pipeline.py --config sources/sources.local.yaml
```

`requirements.txt` 只有两项：

```text
requests
PyYAML
```

解析器用的是标准库 `html.parser` + 一个够用的迷你 CSS 选择器，不依赖 BeautifulSoup/lxml。缺依赖时脚本会直接告诉你安装命令，不会静默失败。

### 加一个源的最小步骤

1. 在 `sources/sources.local.yaml` 里复制一个 `type: html` 的条目。
2. 填 `id`、`name`、`level`、`department`、`list_url`、`link_pattern`。
3. 用浏览器确认列表链接和日期位置，填 `list_date_selector` 或 `date_from_url`。
4. 打开一条详情，确认正文/日期/文号的选择器，填 `body_selector`、`date_selector`、`doc_no_selector`。
5. 先只检查列表：

   ```bash
   python scripts/fetch.py --config sources/sources.local.yaml --source 你的源id --check
   ```

6. 再跑单源采集：

   ```bash
   python scripts/fetch.py --config sources/sources.local.yaml --source 你的源id
   ```

7. 看 `data/raw/health.csv` 和 `data/raw/raw.json`，确认条数、标题、日期。

完整字段表和常见坑见 [docs/sources.md](docs/sources.md)。

## 接到工作台（agent-workbench-template 等）

这套 workflow 不绑定工作台，但输出是特意按「壳读取」设计的：

| 输出 | 工作台怎么用 |
|---|---|
| `outputs/index.json` | 列表页、筛选器、详情页的数据源；按 `doc_id` 打开条目 |
| `outputs/changes.csv` | 「本周新增/更新」时间线；不要反向写回 |
| `outputs/daily/*.md`、`weekly/*.md` | 阅读视图、导出、发送前的草稿 |
| `examples/items/*.json` / `data/items/*.json` | 单条详情和原文摘录；按 `content_path` 读 |
| `review` 字段 | 待核校队列；工作台把人的结论写到覆盖层 |
| `outputs/workbench/` | 按 agent-workbench-template 合同导出的数据包（推荐接法） |

### 导出 workbench 数据包

```bash
python scripts/export_workbench.py
```

默认读取 `examples/outputs/index.json`，生成：

```text
examples/outputs/workbench/
├── index.json           # workbench-index/v1
├── annotations.json     # workbench-annotations/v1
├── reports.json         # workbench-reports/v1
└── items/<id>/content.md
```

字段映射：

| workflow | workbench | 规则 |
|---|---|---|
| `doc_id` | `id` | 原值 |
| `type` | `kind` | 政策 / 通知 / 征求意见 / 公告 → 原文；申报类 → 申报；解读类 → 解读；数据 / 研究 / 竞品保留；其他 → 原文，并在 `warnings` 保留原 type |
| `level` | `level` | 市级 → 示例市；市级部门 → 示例部门；区级 → 示例区；省级 → 示例省；其他保留 |
| `status` | `status` | 已读 / 已研判 → 已研判；跟进中 / 在跟 → 在跟；已归档 → 已归档；其他 → 待研判 |
| `publish_date` | `published_at` | 原值 |
| `deadline` | `deadline` | 原值 |
| `themes` | `themes` | 保留 |
| 条目 `body` | `content_path` | 写入 `items/<id>/content.md` |

把 `examples/outputs/workbench/` 下的内容复制到 [agent-workbench-template](https://github.com/Fanghj256/agent-workbench-template) 的 `workbench/`，或让工作台把数据目录指向这里。`annotations.json` 来自同级的 `overrides.json`；没有覆盖层时是空对象。`reports.json` 收录 `daily/`、`weekly/`、`monthly/` 下的 Markdown，类型分别为日报、周报、月报。

导出后的 `kind`、`status`、`level` 是工作台筛选器的受控值，不会直接透传内部分类；无法映射的 type 会落到 `原文`，并在该条的 `warnings` 里保留原值。

导出脚本只读 `index.json` 和报告，不改原始数据；`--fresh` 会先清空上一次生成的 `items/` 与三个 JSON。

推荐做法：

- **工作台只读生成物**。不要把人的修改直接写进 `index.json`，下一次索引会覆盖。
- 人工结论写到 `outputs/overrides.json`，以 `doc_id` 为键，由工作台合并展示：

  ```json
  {
    "CITY-2026-57699d4f": {
      "status": "跟进中",
      "owner": "示例同事",
      "decision": "相关",
      "note": "已建截止提醒"
    }
  }
  ```

- `agent-workbench-template` 这类壳可以把 `index.json` 当成唯一读模型，把 `changes.csv` 当成变更流；Markdown 只用于展示，不要用正则从报告里抠数据。
- 如果壳支持工具调用，建议暴露四个动作：`list_new_items`、`get_item(doc_id)`、`save_review(doc_id, patch)`、`render_report(kind, date)`。
- 升级时先看 `schema_version`；字段只增不删，旧壳可以忽略新字段。

一段最小读取示例：

```python
import json
from pathlib import Path

index = json.loads(Path("outputs/index.json").read_text(encoding="utf-8"))
queue = [
    item for item in index["items"]
    if item["review"]["required"] and item["status"] == "待研判"
]
for item in sorted(queue, key=lambda row: (-row["priority"], row["publish_date"])):
    print(item["doc_id"], item["title"], item["source_url"])
```

更完整的接入说明见 [docs/workflow.md](docs/workflow.md)。

## 定制

- **换领域**：改 `taxonomy` 主题词表、源清单和类型规则；报告模板不用动。
- **换关键词**：源级 `keywords` 只影响「这条标题要不要抓」，`taxonomy` 影响「这条属于什么主题」。
- **换报告**：改 `templates/*.md` 的文案和章节；`report.py` 只替换 `{{KEY}}` 占位符。
- **换语言**：模板和提示词都是 Markdown，直接改写；日期格式仍建议保持 `YYYY-MM-DD`。
- **换节奏**：日报/周报/月报的选择窗口在 `report.py` 的 `select_items`；模板章节独立。

详见 [docs/customization.md](docs/customization.md)。

## 常见问题

**Q：demo 会联网吗？需要装包吗？**  
A：不会。`--demo` 只读 `examples/sources/*.html`，只用标准库。live 才需要 `requests` + `PyYAML`。

**Q：为什么第二次跑 demo，`changes.csv` 是空的？**  
A：单独跑 `index.py` 默认是增量的：第二次没有变化，所以变更流水为空。想看「全部新增」用 `--fresh`；一键 demo 内部已经用了 fresh。

**Q：为什么不用 BeautifulSoup？**  
A：demo 必须零依赖。`common.py` 里有一个够用的迷你 DOM + CSS 选择器，支持 `tag`、`.class`、`#id`、`[attr]`、后代和 `>`。真实站点如果选择器很复杂，可以在 `fetch.py`/`parse.py` 里换成 BeautifulSoup，数据契约不变。

**Q：真实网站抓不到/返回空？**  
A：先跑 `--check` 看列表；再看是不是 JS 渲染、登录、验证码、频率限制或页面改版。不要绕过访问控制；这类源标成 `manual`，人工转发。详见 `docs/sources.md`。

**Q：日期抓错了怎么办？**  
A：看条目 JSON 的 `extraction.date_source` 和 `warnings`。详情页日期优先于列表日期；如果站点把日期放在奇怪的位置，补 `date_selector` 或 `date_meta`。

**Q：文号抓到的是引用文件怎么办？**  
A：脚本会提示「正文中出现多个文号」。优先用 `doc_no_selector` 精确取；没有选择器时，人工在条目里改，或用 `--skip-existing` 保留人工修改。

**Q：能修改/删除一条吗？**  
A：可以。直接改 `data/items/<doc_id>.json`，再跑 `index.py`；删除 JSON 后重跑，`changes.csv` 会记录 `removed`。重新解析前加 `--skip-existing`，避免覆盖人工修改。

**Q：CSV 在 Excel 里乱码？**  
A：`changes.csv` 和 `health.csv` 都带 UTF-8 BOM，Excel 可直接打开。如果仍乱码，用「数据 → 从文本/CSV」并选 UTF-8。

**Q：能定时跑吗？**  
A：可以。Linux/macOS 用 cron，Windows 用任务计划程序，命令就是 `python scripts/run_pipeline.py --config ...`。建议先跑 `--check` 做健康检查，再跑正式采集。

**Q：AI 在哪一步？**  
A：在报告草稿之后、人工签发之前。`prompts/` 里的提示词把条目 JSON 变成初判草稿；不要把 AI 输出直接当结论，也不要把未核验的内容自动发出去。

**Q：示例数据能直接用吗？**  
A：不能。全部是虚构的 `示例市 / 示例区 / 示例部门`，域名是保留的 `example.gov.cn`。它们只用于演示流程。

## 限制

- demo 数据是冻结的，不代表任何真实政策或趋势。
- live 选择器需要按站点维护；页面改版会导致解析失败，`health.csv` 和 `warnings` 是第一现场。
- 不处理 JS 渲染、登录、验证码、PDF/OCR、附件表格；这些需要单独适配。
- 没有数据库。`index.json` 适合几千条以内的个人/小团队监测；更大规模建议换 SQLite/Postgres，保持同样字段。
- 日期、文号、截止日期都是启发式抽取；报告里的每条都应回原文核验。
- 不包含调度、发布、权限和审计；这些由工作台或你的现有系统承担。

## 安全与许可

- 安全策略、凭据处理、日志与数据保留：见 [SECURITY.md](SECURITY.md)。
- 代码：MIT，见 [LICENSE](LICENSE)。
- 文档、提示词、模板：CC BY 4.0，见 [LICENSE-docs](LICENSE-docs)。
- 示例数据：CC0，见 [LICENSE-data](LICENSE-data)。
- 真实信源页面的版权归原站点所有；采集和再利用前请确认站点条款、robots 约定和当地法律。报告里只放摘要和原文链接，不复制全文对外发布。

---

*如果这套流程帮你省掉了每天翻网站的时间，欢迎把它改成你自己的领域版本。*
