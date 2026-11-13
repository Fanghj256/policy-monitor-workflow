# 运行流程：daily / weekly / monthly

这套 workflow 的节奏是「每天看新增，每周看信号，每月看结构」。频率可按团队调整，但三件事不要混：

- **采集**：机器做，每天固定时间；
- **初筛**：人做，判断相关/参考/不相关；
- **签发**：人做，对外版本必须有人负责。

## 一、节奏总览

| 频率 | 耗时 | 输入 | 输出 | 谁做 |
|---|---|---|---|---|
| 每天 | 15–30 分钟 | `index.json` 当日新增 | 日报草稿 + 状态更新 | 监测员 |
| 每周 | 60–90 分钟 | 当周条目 | 周报 3–5 条信号 | 研究员 + 监测员 |
| 每月 | 2–3 小时 | 当月索引 | 月报 + 信源复盘 | 负责人 |
| 每季 | 半天 | 3 个月索引 | 主题/信源策略调整 | 负责人 + 研究员 |

## 二、每日（15–30 分钟）

### 1. 跑流水线

```bash
python scripts/run_pipeline.py --config sources/sources.local.yaml --kind daily
```

如果已经跑过采集，只想重生成报告：

```bash
python scripts/run_pipeline.py --config sources/sources.local.yaml --kind daily --no-fetch
```

### 2. 看三样东西

1. `data/raw/health.csv`：有没有源失败/为空；
2. `outputs/daily/YYYY-MM-DD.md`：今天新增几条、有没有截止；
3. `outputs/index.json` 的 `stats.by_confidence`：有没有低置信度条目。

### 3. 逐条初筛

对每条新增，只做四个判断：

- **相关**：与监测主题直接相关，需要跟进；
- **参考**：主题相关，但暂时没有行动；
- **不相关**：误抓/无关，归档；
- **待核**：信息不全，先放着，标明缺什么。

判断依据写进 `overrides.json` 或条目 JSON 的 `review.notes`，不要只留在脑子里。

### 4. 截止提醒

- 把 `deadline` 在 14 天内的条目加入提醒；
- 申报类确认「申报对象、材料、截止时间」；
- 征求意见类确认「反馈渠道、反馈格式、截止时间」；
- 截止已过的条目标「已截止」，不要继续放在待办。

### 5. 状态更新

建议状态机：

```text
待研判 → 跟进中 → 已归档
       ↘ 不相关
       ↘ 已截止
```

状态和负责人写进覆盖层，不要改 `index.json`。

### 每日检查表

- [ ] 流水线跑完，无未处理错误
- [ ] `health.csv` 没有连续失败
- [ ] 当日新增全部初筛
- [ ] 14 天内截止已建提醒
- [ ] 低置信度条目标注缺什么
- [ ] 日报草稿发给需要的人（如团队群）

## 三、每周（60–90 分钟）

### 1. 跑周报

```bash
python scripts/run_pipeline.py --config sources/sources.local.yaml --kind weekly
```

周报按「发布日期」归入 ISO 周（周一到周日）。如果周一跑，默认生成上一周；用 `--date` 指定周内任意一天。

### 2. 从条目里选 3–5 条信号

不要把所有条目塞进周报。选信号的标准：

- **规则变化**：新办法、新标准、申报口径变化、征求意见；
- **时间敏感**：截止在 2–4 周内；
- **层级重要**：国家/省级/市级的新文件优先；
- **与业务相关**：能对应到具体产品、场景、区域或申报计划；
- **有不确定性**：需要核验、需要跨部门确认的，也值得列为信号。

每条信号写四段：

1. **事实**：谁、什么时候、发了什么、文号；
2. **依据**：原文链接 + 关键条款；
3. **为什么现在看**：时间窗、适用范围、变化点；
4. **待确认**：不明确的地方 + 下一步找谁/查什么。

### 3. 人工改写

`report.py` 生成的周报是「骨架」：事实、表格、截止、来源。把 3–5 条信号改写成给人读的段落，删掉不重要的条目，补上判断和下一步。

### 4. 来源复盘

- 本周哪些源 0 条？是没更新，还是抓不到？
- 哪些源贡献了信号？哪些只是噪声？
- 有没有新的源需要补？用 `prompts/source-discovery.md` 做评估。
- 更新 `sources.local.yaml` 的 `notes`，记录改版和坑。

### 每周检查表

- [ ] 周报覆盖周一到周日
- [ ] 3–5 条信号，每条有事实/依据/待确认
- [ ] 截止日历更新
- [ ] 来源覆盖有记录
- [ ] 失效源已处理或降级
- [ ] 周报由人签发后发出

## 四、每月（2–3 小时）

### 1. 跑月报

```bash
python scripts/run_pipeline.py --config sources/sources.local.yaml --kind monthly
```

或指定月份：

```bash
python scripts/report.py --index outputs/index.json --kind monthly --month 2026-11
```

### 2. 看结构，不看单条

月报回答四个问题：

- **总量**：本月多少条？比上月多还是少？
- **结构**：主题、层级、类型怎么分布？申报/征求意见占比多少？
- **变化**：哪些主题连续出现？哪些源开始/停止更新？
- **缺口**：哪些层级/主题没有覆盖？哪些源长期失效？

### 3. 写趋势和建

月报的「趋势」不是预测，是**计数描述 + 待验证假设**：

- 不要说「某主题正在升温」，除非连续 3 个月计数上升且源覆盖稳定；
- 不要说「政策收紧/放松」，除非有具体条款对比；
- 可以写「本月某主题出现 6 次，较上月 +3；建议下月重点核验」。

### 4. 信源与模板复盘

- 复测 `dead` 源；
- 检查 `health.csv` 的失败率；
- 看 `extraction.warnings` 的高频问题，决定改选择器还是改流程；
- 更新模板/提示词：哪些段落没人看？哪些字段总缺？

### 每月检查表

- [ ] 月报完成，含趋势/增量/建议
- [ ] 连续 3 个月的主题变化有记录
- [ ] 失效源复测
- [ ] 解析警告TOP3 有处理
- [ ] 模板/提示词有一次小复盘
- [ ] 下月重点主题和源清单确定

## 五、角色与分工

小团队可以一人多角，但**判断和签发不要合并到同一个人**（至少隔一次复核）。

| 角色 | 负责 | 不负责 |
|---|---|---|
| 监测员 | 跑流水线、初筛、截止提醒、源健康 | 对外结论 |
| 研究员 | 读原文、判断影响、写信号 | 采集脚本 |
| 签发人 | 对外版本、合规、最终措辞 | 日常抓取 |
| 开发者 | 脚本、选择器、数据契约 | 政策判断 |

## 六、失败与值班

### 当日失败

1. 看 `health.csv` 的 `error`；
2. 单源失败：跳过，先出报告，标记「本期缺某源」；
3. 全部失败：检查网络、依赖、配置路径；
4. 不要为了赶报告手工编条目。

### 连续失败

- 连续 2 次 `empty`：人工打开列表，确认是否改版/停更；
- 连续 2 次 `error`：降级 `manual`，在 `notes` 写原因和复测日期；
- 连续 1 周失败：换源或补备用源。

### 数据错误

- 日期/文号错：改条目 JSON，重跑 `index.py`；
- 正文抓错：改 `body_selector`，重跑 `parse.py`（加 `--skip-existing` 保护人工修改）；
- 条目重复：检查 URL 是否带跟踪参数；必要时在 `fetch.py` 做 URL 规范化。

## 七、归档与保留

- `data/raw/html/`：原始页面，建议保留 12 个月；按 `record_id` 命名。
- `data/items/`：条目 JSON，长期保留；它是索引和报告的重建基础。
- `outputs/`：报告草稿，按日期保留；对外版本另存。
- `changes.csv`：长期保留；用于审计「什么时候看到/改过什么」。
- 日志：至少保留 90 天；含 URL 和标题，对外分享前脱敏。

## 八、指标

不要用「抓了多少条」当唯一指标。建议每季度看：

| 指标 | 定义 | 目标 |
|---|---|---|
| 源覆盖率 | 有更新的 L1 源 / 配置的 L1 源 | > 90% |
| 采集新鲜度 | 最新条目发布日期距今天数 | 工作日 ≤ 2 天 |
| 解析置信度 | 高/中/低占比 | 低 < 10% |
| 初筛及时率 | 24 小时内完成初筛的条目占比 | > 90% |
| 信号命中率 | 周报信号中被采纳/转发的比例 | 团队自定 |
| 截止遗漏 | 过期未提醒的申报/征求意见 | 0 |

## 九、接到工作台

### 读模型

工作台只需要读三样：

```text
outputs/index.json      列表、筛选、详情入口
outputs/changes.csv     变更时间线
outputs/daily|weekly/*.md  阅读视图
```

不要把 Markdown 当数据源。报告是展示层，字段会随模板变；`index.json` 才是契约。

### 生成 workbench 数据包

如果目标工作台是 [agent-workbench-template](https://github.com/Fanghj256/agent-workbench-template)（或实现了同一合同的壳），先导出：

```bash
python scripts/export_workbench.py
```

默认读取 `examples/outputs/index.json`，输出到 `examples/outputs/workbench/`：

```text
workbench/
├── index.json           # workbench-index/v1
├── annotations.json     # workbench-annotations/v1
├── reports.json         # workbench-reports/v1
└── items/<id>/content.md
```

映射关系：

| workflow | workbench | 规则 |
|---|---|---|
| `doc_id` | `id` | 原值 |
| `type` | `kind` | 政策 / 通知 / 征求意见 / 公告 → 原文；申报类 → 申报；解读类 → 解读；数据 / 研究 / 竞品保留；其他 → 原文，并在 `warnings` 保留原 type |
| `level` | `level` | 市级 → 示例市；市级部门 → 示例部门；区级 → 示例区；省级 → 示例省；其他保留 |
| `status` | `status` | 已读 / 已研判 → 已研判；跟进中 / 在跟 → 在跟；已归档 → 已归档；其他 → 待研判 |
| `publish_date` | `published_at` | 原值 |
| `deadline` | `deadline` | 原值 |
| `themes` | `themes` | 保留 |
| `body` | `items/<id>/content.md` | 正文写入 |
| `overrides.json` | `annotations.json` | `decision` → `judgment`，`note` → `summary` |
| `daily/weekly/monthly/*.md` | `reports.json` | 日报/周报/月报 |

导出后的 `kind` 只会落在 `原文 / 解读 / 数据 / 申报 / 竞品 / 研究`，`status` 只会落在 `待研判 / 在跟 / 已研判 / 已归档`；`level` 在 demo 中映射为 `示例市 / 示例部门 / 示例区 / 示例省`。这样工作台的筛选器不需要理解内部类型。

把 `examples/outputs/workbench/` 下的内容复制到 agent-workbench-template 的 `workbench/`，或让工作台直接指向这个目录。也可以用参数接 live 产出：

```bash
python scripts/export_workbench.py --index outputs/index.json --out outputs/workbench --fresh
```

`--fresh` 只清空上一次生成的 `index.json`、`annotations.json`、`reports.json` 和 `items/`，不碰原始数据。导出是只读投影；人的结论仍然写在 `overrides.json`，不要写回 `index.json`。

### 覆盖层

人的判断写到 `outputs/overrides.json`，按 `doc_id` 合并：

```json
{
  "CITY-2026-57699d4f": {
    "status": "跟进中",
    "owner": "示例同事",
    "decision": "相关",
    "note": "已建截止提醒",
    "updated_at": "2026-11-12"
  }
}
```

工作台合并逻辑：

```python
def merge(item, overrides):
    patch = overrides.get(item["doc_id"], {})
    return {**item, **patch, "generated": item}
```

这样下一次 `index.py` 重跑不会覆盖人的结论。

### 工作台动作

如果壳支持工具调用，建议四个动作：

| 动作 | 输入 | 输出 |
|---|---|---|
| `list_new_items` | `since`、`level`、`status` | `index.json` 过滤结果 |
| `get_item` | `doc_id` | 条目 JSON + 原文链接 |
| `save_review` | `doc_id`、`patch` | 写入覆盖层 |
| `render_report` | `kind`、`date` | 调 `report.py` 或读取现有 Markdown |

### agent-workbench-template 这类壳

这类壳通常提供「项目 + 会话 + 文件」的界面。推荐用 workbench 数据包接入：

1. 运行 `python scripts/export_workbench.py`；
2. 把 `outputs/workbench/` 复制到 agent-workbench-template 的 `workbench/`，或把它的数据目录指向这里；
3. 首屏读 `workbench/index.json` 的 `items`；
4. 详情页按 `content_path` 打开 `items/<id>/content.md`，按 `source_url` 打开原文；
5. 审核动作写回本仓库的 `overrides.json`，再重新 export 成 `annotations.json`；
6. 报告页读 `reports.json`，不要从 Markdown 反解析字段；
7. 升级时检查 `schema` 字段（`workbench-index/v1` 等），旧壳忽略新增字段即可。

如果壳只想读原生 workflow 输出，也可以把 `outputs/` 作为只读数据目录，按 `index.json` / `changes.csv` / Markdown 三件套接入。

### 定时任务

Linux/macOS：

```cron
30 8 * * 1-5  cd /path/to/policy-monitor-workflow && python scripts/run_pipeline.py --config sources/sources.local.yaml --kind daily
0 9 * * 1     cd /path/to/policy-monitor-workflow && python scripts/run_pipeline.py --config sources/sources.local.yaml --kind weekly
```

Windows 任务计划程序：

- 程序：`python`
- 参数：`scripts/run_pipeline.py --config sources/sources.local.yaml --kind daily`
- 起始于：仓库根目录

定时任务只负责生成草稿；签发仍然是人。

## 十、一页纸检查表

### 每天

- [ ] 跑 daily
- [ ] 看 health
- [ ] 初筛新增
- [ ] 建截止提醒
- [ ] 更新状态

### 每周

- [ ] 跑 weekly
- [ ] 选 3–5 条信号
- [ ] 人工改写
- [ ] 来源复盘
- [ ] 签发

### 每月

- [ ] 跑 monthly
- [ ] 看结构变化
- [ ] 复测失效源
- [ ] 处理解析警告
- [ ] 定下月重点

---

流程的目的不是「生成更多报告」，而是**让该看的人在对的时间看到对的那几条**。如果某份报告没人看，先删报告，不要加自动化。
