# 信源：怎么加、怎么验、怎么维护

信源是整套 workflow 的地基。这篇文档按「先选源，再写配置，再验证，再维护」的顺序讲。

## 一、先选对源

### 源的分层

| 层级 | 典型来源 | 用途 | 注意 |
|---|---|---|---|
| L1 | 政府、部门、园区官网的政策/通知栏目 | 原文、申报、征求意见 | 最高优先级；每条都应能回到原文 |
| L2 | 协会、联盟、公共服务平台、政策聚合站 | 补充覆盖、申报汇总 | 可能转载；尽量回源 |
| L3 | 媒体、行业自媒体、研究机构 | 背景、解读、线索 | 不作为唯一依据；必须回源 |

`source_tier` 写进条目和索引，报告会提示「本周样本全部来自 L1」这类覆盖问题。

### 选源检查表

- [ ] 有稳定的列表页，不是一次性专题页。
- [ ] 列表能看到标题和日期；点进去有正文。
- [ ] 更新频率与监测节奏匹配（日更/周更/月更）。
- [ ] 页面是公开的，不需要登录、验证码或付费。
- [ ] 站点条款、robots 约定允许低频访问。
- [ ] 同一主题至少有 2 个独立来源，避免单点失效。

### 不收录的源

- 需要登录、绕过验证码、破解接口的；
- 纯图片/PDF 且没有文字层的（除非你另有 OCR 流程）；
- 来源不明、无法回到原文的二手汇总；
- 更新已停止、打不开、证书异常的（标 `manual` 或 `dead`，按月复测）。

## 二、源的类型

`fetch.py` 支持五种 `type`（也接受旧字段名 `adapter`）：

| 类型 | 用途 | 必填字段 |
|---|---|---|
| `html` | 普通列表页 + 详情页 | `list_url`、`link_pattern` |
| `json` | 返回 JSON 的搜索/列表接口 | `api_url`、`items_path`、字段映射 |
| `rss` | RSS/Atom | `list_url` |
| `manual` | 公众号、需要人工转发的源 | `notes` |
| `dead` | 已停更/长期不可用 | `notes`、复测日期 |

`manual` 和 `dead` 不会自动抓取，但会保留在配置里，提醒你「这里还有覆盖缺口」。

## 三、字段表

### 通用字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 稳定短 ID，建议小写字母/数字/连字符；用于过滤和日志 |
| `name` | 是 | 人读名称，进报告 |
| `enabled` | 否 | 默认 `true`；`false` 时跳过 |
| `type` | 是 | `html / json / rss / manual / dead` |
| `signal` | 否 | `政策 / 舆情 / 同行 / 解读`，用于区分原文与参考 |
| `level` | 是 | `国家 / 省级 / 市级 / 市级部门 / 区级 / 园区 / 协会 / 媒体 / 行业` |
| `department` | 否 | 发布机构；解析不到 issuer 时兜底 |
| `source_tier` | 是 | `L1 / L2 / L3` |
| `keywords` | 否 | 标题命中任一关键词才抓；空表示全抓 |
| `max_items` | 否 | 单次最多抓多少条，默认 20 |
| `fetch_detail` | 否 | 是否抓详情，默认 `true`；列表源可设 `false` |
| `delay` | 否 | 每次请求间隔秒数，默认 0.8；请勿设太小 |
| `notes` | 否 | 维护备注：改版、坑、复测日期 |

### HTML 源

| 字段 | 说明 |
|---|---|
| `list_url` | 列表页地址 |
| `link_pattern` | 匹配详情链接的正则；对 `href` 和绝对 URL 都试一次 |
| `date_from_url` | 从 URL 提日期。URL 形如 `/20261109/` 用 `'/(\d{4})(\d{2})(\d{2})/'`；形如 `/2026/11/09/` 用 `'/(\d{4})/(\d{2})/(\d{2})/'` |
| `list_date_selector` | 列表项里的日期选择器；会在 `a` 自身和向上 4 层父节点里找 |
| `date_from_title` | 从标题尾部提日期，如 `'(20\d{2}-\d{2}-\d{2})\s*$'` |
| `title_selector` | 列表项标题选择器；不填则用 `a` 的文本 |
| `body_selector` | 详情页正文选择器；不填则按内置候选兜底 |
| `date_selector` | 详情页日期选择器 |
| `date_meta` | 详情页 meta 名称，如 `PubDate` |
| `doc_no_selector` | 文号选择器 |
| `issuer_selector` | 发布机构选择器 |
| `summary_selector` | 摘要/导语选择器 |

### JSON 源

| 字段 | 说明 |
|---|---|
| `api_url` | 接口地址；可含 `{q}` 占位符 |
| `api_method` | `GET`（默认）或 `POST` |
| `api_params` | GET 查询参数（dict） |
| `api_body` | POST 请求体（dict 或 JSON 字符串） |
| `api_content_type` | `json`（默认）/ `form` / `text` |
| `api_headers` | 额外请求头；只放在本地配置，不要进 Git |
| `items_path` | 列表在响应里的点号路径，如 `data.list`；根数组留空 |
| `title_field` | 标题字段，支持点号路径 |
| `url_field` | 链接字段 |
| `url_template` | 没有 `url_field` 时，用字段拼接链接 |
| `date_field` | 日期字段 |
| `date_format` | `auto` / `epoch_ms` / `epoch_s` |
| `summary_field` | 摘要字段 |
| `department_field` | 机构字段 |
| `doc_no_fields` | 文号字段列表，按顺序拼接 |
| `queries` | 多关键词查询；会替换 `{q}` 并合并去重 |

### RSS 源

| 字段 | 说明 |
|---|---|
| `list_url` | feed 地址 |
| `max_items` | 最多取多少条 |
| `fetch_detail` | 是否再抓详情页 |

## 四、加一个 HTML 源：逐步操作

### 1. 复制一个模板

```yaml
- id: example-dept
  name: 示例部门
  enabled: true
  type: html
  signal: 政策
  level: 市级部门
  department: 示例部门
  source_tier: L1
  list_url: https://dept.example.gov.cn/tzgg/
  link_pattern: '^/tzgg/\d{8}/[0-9a-z]+\.html$'
  date_from_url: '/(\d{4})/(\d{2})/(\d{2})/'
  body_selector: '.article-body'
  date_selector: '.article-meta .date'
  doc_no_selector: '.article-meta .doc-number'
  issuer_selector: '.article-meta .issuer'
  max_items: 10
  delay: 1.0
  notes: "示例：列表 10 条/页；详情正文 .article-body。"
```

### 2. 用 `--check` 只验列表

```bash
python scripts/fetch.py --config sources/sources.local.yaml --source example-dept --check
```

输出会告诉你列表取到几条、有没有报错。`--check` 不抓详情、不写文件，适合反复调 `link_pattern`。

### 3. 跑单源采集

```bash
python scripts/fetch.py --config sources/sources.local.yaml --source example-dept
```

看三处：

- `data/raw/health.csv`：状态、条数、错误；
- `data/raw/raw.json`：标题、日期 hint、URL；
- `data/raw/html/`：详情 HTML 是否真的抓到了。

### 4. 跑解析

```bash
python scripts/parse.py --raw data/raw/raw.json --out data/items --taxonomy sources/sources.local.yaml
python scripts/index.py --items data/items --out outputs --fresh
python scripts/report.py --index outputs/index.json --kind daily --date 2026-11-12
```

看条目 JSON 的 `extraction`：日期来源、文号来源、置信度、warnings。字段不对就回去改选择器。

### 5. 把源加进日常

确认 3–5 天稳定后，再把 `enabled` 设为 `true`，加入定时任务。

## 五、选择器支持范围

`common.py` 有一个精简 CSS 选择器，支持：

- `tag`、`.class`、`#id`、`*`
- `tag.class`、`tag#id`
- 后代：`.article .body`
- 子元素：`.article > .body`
- 属性：`[href]`、`[data-type="policy"]`、`[class*="article"]`
- 逗号分组：`h1, .title`

不支持：伪类（`:nth-child`）、相邻兄弟（`+`）、复杂属性运算。遇到不支持的选择器，优先改页面结构或换 BeautifulSoup；不要硬写正则去解析 HTML。

## 六、健康检查

### 每次采集后

看 `health.csv`：

```text
source_id,source_name,status,items,fetched_at,error
demo-city-gov,示例市人民政府,ok,2,2026-11-12T18:00:00+08:00,
```

- `ok`：有条目；
- `empty`：请求成功但 0 条，可能是改版、关键词太窄或列表为空；
- `error`：请求/解析失败，看 `error`；
- `manual` / `dead`：人工或停更源，不算失败。

### 每周

- 连续 2 次 `empty` 的源，人工打开列表确认；
- 连续 2 次 `error` 的源，降级为 `manual` 或修选择器；
- 新增源先跑 `--check`，不要直接进日报；
- 记录一次「源覆盖」：国家/省/市/区/媒体各几个，是否单点。

### 每月

- 复测 `dead` 源；
- 清理长期不更新的栏目；
- 对 1–2 个源做抽样回源，确认标题/日期/文号没有漂移。

## 七、demo 的离线快照约定

`examples/sources/*.html` 不是真实网站，而是「列表 + 内联详情」的离线快照：

```html
<li class="news-item">
  <a class="news-link" href="/zhengce/2026/11/09/item-001.html">
    <span class="news-title">……</span>
    <time class="news-date" datetime="2026-11-09">2026-11-09</time>
  </a>
  <p class="news-summary">……</p>
  <template class="demo-detail">
    <article class="policy-detail">
      <h1>……</h1>
      <div class="meta">
        <span class="issuer">……</span>
        <span class="publish-date">2026-11-09</span>
        <span class="doc-number">……</span>
      </div>
      <p class="lead">……</p>
      <div class="article-body">……</div>
    </article>
  </template>
</li>
```

`fetch.py --demo` 读 `a.news-link`，把 `<template class="demo-detail">` 里的 HTML 当作详情；这样 4 个文件就能覆盖「列表 + 详情」两条路径，且不联网。

正式接源时不要用这个约定；直接用 `list_url` + 详情链接。

## 八、常见坑

### 1. 列表日期 ≠ 发布日期

很多站点的 URL 日期是栏目归档日期，不是发布日期。优先用详情页的 `date_selector` / `date_meta`；列表日期只做 hint。

### 2. 文号抓到引用文件

正文里出现「根据《……》（某〔2025〕X号）」时，简单正则会把引用文号当成本文文号。优先用 `doc_no_selector`；没有选择器时，解析会提示「正文中出现多个文号」，请人工核对。

### 3. 相对链接和 `//` 开头

`fetch.py` 用 `urljoin` 处理相对链接；JSON 接口里的 `//host/path` 会补 `https:`。如果站点用 `javascript:` 打开详情，考虑 `manual` 或单独适配。

### 4. JS 渲染

列表由前端 JS 渲染、HTML 里没有链接时，`requests` 抓不到。不要为了一个源引入无头浏览器；先看有没有 JSON 接口，没有就标 `manual`。

### 5. 编码

脚本统一 UTF-8。某些站点返回 GBK/GB2312，`fetch.py` 会用响应头或 `apparent_encoding` 兜底；如果仍乱码，在源配置里指定编码（需要小改 adapter）或先人工确认。

### 6. 频率与礼貌

- 默认 `delay: 0.8`，别改成 0；
- 单源 `max_items` 控制在 10–30；
- 避开整点/高峰；
- 遵守站点条款和 robots 约定；
- 被封不是「技术问题」，是访问策略问题。

### 7. 分页

当前版本只抓列表第一页。需要更多时：

- 优先用接口的 `pageSize`；
- 或在 `list_url` 里直接写多页（每页一个源条目）；
- 或给 `fetch.py` 加 `pagination` adapter，保持 raw 结构不变。

## 九、源配置模板

完整示例见 `sources/sources.example.yaml`（11 个虚构源，覆盖 html/json/rss/manual）。复制成 `sources/sources.local.yaml` 后修改；`*.local.yaml` 已在 `.gitignore` 里，适合放本地路径和请求头。

不要把真实凭据写进示例配置，也不要把 `sources.local.yaml` 提交到公开仓库。
