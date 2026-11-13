# -*- coding: utf-8 -*-
"""报告阶段：从 index.json 生成日报、周报、月报草稿。

用法：
    python scripts/report.py --demo --kind all --date 2026-11-12
    python scripts/report.py --index outputs/index.json --kind weekly --date 2026-11-12

报告模板在 templates/，占位符是 {{KEY}} 形式；模板可以直接复制给同事改。
报告里的排序、计数、截止提醒都是机械规则，不代替人的判断。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from common import (
    DEMO_DATE,
    ROOT,
    days_between,
    md_link,
    month_of,
    month_range,
    parse_date,
    previous_month,
    read_json,
    rel_path,
    table,
    truncate,
    week_range,
    write_text,
)

DEMO_INDEX = ROOT / "examples" / "outputs" / "index.json"
DEMO_OUT = ROOT / "examples" / "outputs"
LIVE_INDEX = ROOT / "outputs" / "index.json"
LIVE_OUT = ROOT / "outputs"
TEMPLATE_DIR = ROOT / "templates"

METHOD_NOTE = (
    "统计口径：日报按首次发现日期归日；周报/月报按发布日期归入周期，"
    "没有发布日期的条目退回使用首次发现日期。摘要为脚本从原文抽取的前几句，"
    "不是 AI 改写；优先级是按类型、层级、截止时间计算的机械排序，不代表重要性结论。"
    "报告只覆盖公开信源，未抓取登录、付费或受访问控制的内容；不构成法律意见。"
)

FALLBACK_DAILY = """# 政策监测日报 · {{DATE}}

> 草稿，待人工核校后签发。生成：{{GENERATED_AT}}

## 一、今日概览

{{OVERVIEW}}

## 二、建议先看

{{HIGHLIGHTS}}

## 三、全部新增

{{ITEMS}}

## 四、截止与时间窗

{{DEADLINES}}

## 五、核验清单

- [ ] 打开原文核对标题、日期、文号
- [ ] 确认适用对象、截止时间与材料
- [ ] 标记相关/参考/不相关并指定跟进人

## 六、来源

{{SOURCES}}
"""

FALLBACK_WEEKLY = """# 政策监测周报 · {{WEEK}}

> 周期：{{RANGE}} · 草稿，待人工核校后签发

## 一、本周 3–5 条信号

{{SIGNALS}}

## 二、全部条目

{{TABLE}}

## 三、截止日历

{{DEADLINES}}

## 四、下周观察清单

{{WATCHLIST}}

## 五、来源与覆盖率

{{SOURCES}}

## 六、方法与限制

{{METHOD_NOTE}}
"""

FALLBACK_MONTHLY = """# 政策监测月报 · {{MONTH}}

> 草稿，待人工核校后签发 · 生成：{{GENERATED_AT}}

## 一、本月概况

{{OVERVIEW}}

## 二、主题与层级分布

{{DISTRIBUTION}}

## 三、趋势观察

{{TRENDS}}

## 四、重点增量

{{INCREMENTS}}

## 五、下月建议

{{RECOMMENDATIONS}}

## 六、附录：全部条目

{{APPENDIX}}

## 七、方法与限制

{{METHOD_NOTE}}
"""


class ReportError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 选择与统计
# ---------------------------------------------------------------------------

def load_index(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if not isinstance(data, dict) or "items" not in data:
        raise ReportError(
            f"index.json 不存在或格式不对：{rel_path(path)}\n"
            "先运行：python scripts/index.py --demo --fresh"
        )
    return data


def item_date(item: dict[str, Any]) -> str:
    return item.get("publish_date") or item.get("first_seen") or ""


def select_items(index: dict[str, Any], kind: str, anchor: str) -> tuple[list[dict[str, Any]], dict[str, str]]:
    items = index.get("items") or []
    anchor = parse_date(anchor)
    if not anchor:
        raise ReportError(f"日期无效：{anchor}")

    if kind == "daily":
        selected = [
            item for item in items
            if (item.get("first_seen") or item.get("publish_date")) == anchor
        ]
        return selected, {"date": anchor, "note": f"统计首次发现日期为 {anchor} 的条目。"}

    if kind == "weekly":
        label, start, end = week_range(anchor)
        selected = [item for item in items if start <= item_date(item) <= end]
        return selected, {
            "week": label, "start": start, "end": end,
            "note": f"统计发布日期在 {start} 至 {end} 的条目。",
        }

    if kind == "monthly":
        month = month_of(anchor)
        start, end = month_range(month)
        selected = [item for item in items if item_date(item).startswith(month)]
        return selected, {
            "month": month, "start": start, "end": end,
            "note": f"统计发布日期在 {month} 的条目。",
        }

    raise ReportError(f"未知报告类型：{kind}")


def sort_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            int(item.get("priority") or 0),
            item_date(item),
            item.get("doc_id") or "",
        ),
        reverse=True,
    )


def counts(items: list[dict[str, Any]], field: str, fallback: str = "未标注") -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        if field == "themes":
            values = item.get("themes") or [fallback]
        else:
            values = [item.get(field) or fallback]
        for value in values:
            result[value] = result.get(value, 0) + 1
    return dict(sorted(result.items(), key=lambda pair: (-pair[1], pair[0])))


def format_counts(data: dict[str, int], limit: int = 8) -> str:
    if not data:
        return "无"
    parts = [f"{key} {value}" for key, value in list(data.items())[:limit]]
    if len(data) > limit:
        parts.append(f"其他 {sum(list(data.values())[limit:])}")
    return " · ".join(parts)


def themes_text(item: dict[str, Any]) -> str:
    return "、".join(item.get("themes") or []) or "未标注"


def overview_block(items: list[dict[str, Any]]) -> str:
    if not items:
        return "- 新增条目：0 条。\n- 建议先检查信源健康（`health.csv`）与采集窗口。"
    level = counts(items, "level")
    policy_type = counts(items, "type")
    themes = counts(items, "themes")
    confidence = counts(items, "confidence")
    review_required = sum(
        1 for item in items if (item.get("review") or {}).get("required")
    )
    lines = [
        f"- 新增条目：**{len(items)} 条**",
        f"- 层级分布：{format_counts(level)}",
        f"- 类型分布：{format_counts(policy_type)}",
        f"- 涉及主题：{format_counts(themes)}",
        f"- 解析置信度：{format_counts(confidence)}",
        f"- 待人工核校：{review_required} 条",
    ]
    return "\n".join(lines)


def highlight_block(items: list[dict[str, Any]], limit: int = 3) -> str:
    if not items:
        return "今日没有新增条目。"
    lines = []
    for index, item in enumerate(sort_items(items)[:limit], 1):
        title = md_link(item.get("title", ""), item.get("source_url", ""))
        meta = " · ".join(filter(None, [
            item.get("issuer", ""),
            item.get("publish_date", ""),
            item.get("type", ""),
            item.get("level", ""),
        ]))
        lines.append(f"{index}. **{title}**  \n   {meta}")
        detail = []
        if item.get("doc_number"):
            detail.append(f"文号 {item['doc_number']}")
        if item.get("deadline"):
            detail.append(f"截止 {item['deadline']}")
        if item.get("priority"):
            detail.append(f"规则排序 {item['priority']}/5（{item.get('priority_reason', '')}）")
        if detail:
            lines.append("   " + " ｜ ".join(detail))
        if item.get("summary"):
            lines.append(f"   {truncate(item['summary'], 150)}")
    return "\n".join(lines)


def item_table(items: list[dict[str, Any]], include_confidence: bool = False) -> str:
    if not items:
        return "无。"
    headers = ["日期", "层级", "类型", "标题", "机构", "截止"]
    if include_confidence:
        headers.append("置信度")
    rows = []
    for item in sort_items(items):
        row = [
            item.get("publish_date") or item.get("first_seen") or "日期待定",
            item.get("level", ""),
            item.get("type", ""),
            md_link(item.get("title", ""), item.get("source_url", "")),
            item.get("issuer", ""),
            item.get("deadline", "") or "—",
        ]
        if include_confidence:
            row.append(item.get("confidence", ""))
        rows.append(row)
    return table(headers, rows)


def deadline_table(
    items: list[dict[str, Any]],
    anchor: str,
    horizon: int = 45,
) -> str:
    rows = []
    for item in items:
        deadline = parse_date(item.get("deadline"))
        if not deadline:
            continue
        remaining = days_between(anchor, deadline)
        if remaining < 0 or remaining > horizon:
            continue
        rows.append((
            remaining,
            [
                deadline,
                f"{remaining} 天",
                md_link(item.get("title", ""), item.get("source_url", "")),
                item.get("type", ""),
                item.get("level", ""),
            ],
        ))
    if not rows:
        return f"未来 {horizon} 天没有已识别的截止日期；如为申报/征求意见类，请回原文确认。"
    rows.sort(key=lambda pair: pair[0])
    return table(["截止", "剩余", "条目", "类型", "层级"], [row for _, row in rows])


def sources_table(items: list[dict[str, Any]]) -> str:
    if not items:
        return "无。"
    aggregated: dict[str, dict[str, Any]] = {}
    for item in items:
        name = item.get("source_name") or item.get("issuer") or "未标注"
        row = aggregated.setdefault(name, {
            "name": name,
            "tier": item.get("source_tier", ""),
            "level": item.get("level", ""),
            "items": 0,
            "latest": "",
        })
        row["items"] += 1
        date = item.get("publish_date") or ""
        if date > row["latest"]:
            row["latest"] = date
    rows = [
        [row["name"], row["tier"], row["level"], row["items"], row["latest"] or "—"]
        for row in sorted(aggregated.values(), key=lambda row: (-row["items"], row["name"]))
    ]
    return table(["信源", "层级标记", "层级", "条数", "最新发布"], rows)


def signal_block(items: list[dict[str, Any]], limit: int = 5) -> str:
    if not items:
        return "本周没有新增条目。先检查信源健康与采集任务，再决定是否补采。"
    chosen = sort_items(items)[:limit]
    lines = [
        f"> 按机械优先级选出 {len(chosen)} 条，供人工初筛；排序不代表重要性结论。",
        "",
    ]
    for index, item in enumerate(chosen, 1):
        title = md_link(item.get("title", ""), item.get("source_url", ""))
        facts = " · ".join(filter(None, [
            item.get("issuer", ""),
            item.get("publish_date", ""),
            f"{item.get('level', '')} {item.get('type', '')}".strip(),
        ]))
        lines.append(f"### 信号 {index}｜{title}")
        lines.append("")
        lines.append(f"- **事实**：{facts}。")
        if item.get("doc_number"):
            lines.append(f"- **文号**：{item['doc_number']}。")
        lines.append(f"- **主题**：{themes_text(item)}。")
        if item.get("deadline"):
            lines.append(f"- **截止**：{item['deadline']}。")
        rule = f"规则排序 {item.get('priority', '')}/5"
        if item.get("priority_reason"):
            rule += f"（{item['priority_reason']}）"
        lines.append(f"- **规则提示**：{rule}。")
        if item.get("summary"):
            lines.append(f"- **摘要（原文抽取）**：{truncate(item['summary'], 180)}")
        lines.append(
            "- **待人工确认**：适用对象、条件、材料清单与截止口径；"
            "摘要未覆盖的条款需回原文核对。"
        )
        lines.append("- **下一步**：打开原文；如适用，登记截止提醒并指定跟进人。")
        lines.append("")
    return "\n".join(lines).rstrip()


def watchlist_block(items: list[dict[str, Any]], anchor: str) -> str:
    if not items:
        return "- 本周无新增；优先检查信源是否改版、接口是否失效、采集任务是否运行。"
    lines = []
    upcoming = []
    for item in items:
        deadline = parse_date(item.get("deadline"))
        if deadline:
            remaining = days_between(anchor, deadline)
            if 0 <= remaining <= 14:
                upcoming.append(f"{deadline}（{remaining} 天）｜{item.get('title', '')}")
    if upcoming:
        lines.append("**近期截止**：")
        lines.extend(f"- {row}" for row in sorted(upcoming))
    else:
        lines.append("- 未来 14 天没有已识别的截止日期；申报类仍需回原文确认。")

    consultations = [item for item in items if item.get("type") == "征求意见"]
    if consultations:
        lines.append(f"- 有 {len(consultations)} 条征求意见稿，核对反馈渠道与截止时间。")

    low = [item for item in items if item.get("confidence") == "低"]
    if low:
        lines.append(f"- 有 {len(low)} 条解析置信度低，先补全正文/日期/文号再判断。")

    tiers = {item.get("source_tier") for item in items}
    if not ({"L3", "L2"} & tiers):
        lines.append("- 本周样本全部来自 L1 官方源，建议补充 1–2 个媒体/解读源做交叉验证。")

    return "\n".join(lines)


def month_overview(items: list[dict[str, Any]], previous: list[dict[str, Any]]) -> str:
    if not items:
        baseline = "本月没有新增条目。"
        if previous:
            baseline += f" 上月有 {len(previous)} 条，建议检查信源健康与采集窗口。"
        return baseline
    lines = [
        f"- 本月条目：**{len(items)} 条**",
        f"- 信源数量：{len({item.get('source_name') for item in items})} 个",
        f"- 层级分布：{format_counts(counts(items, 'level'))}",
        f"- 类型分布：{format_counts(counts(items, 'type'))}",
        f"- 待人工核校：{sum(1 for item in items if (item.get('review') or {}).get('required'))} 条",
    ]
    if previous:
        delta = len(items) - len(previous)
        sign = "+" if delta >= 0 else ""
        lines.append(f"- 与上月相比：{sign}{delta} 条（上月 {len(previous)} 条）")
    else:
        lines.append("- 上月无样本，本月作为基线月")
    return "\n".join(lines)


def distribution_block(items: list[dict[str, Any]]) -> str:
    if not items:
        return "无。"
    total = len(items)
    theme_rows = [
        [theme, count, f"{count / total:.0%}"]
        for theme, count in counts(items, "themes").items()
    ]
    level_rows = [
        [level, count, f"{count / total:.0%}"]
        for level, count in counts(items, "level").items()
    ]
    type_rows = [
        [policy_type, count, f"{count / total:.0%}"]
        for policy_type, count in counts(items, "type").items()
    ]
    return "\n\n".join([
        "**主题分布**（一条政策可命中多个主题，占比之和可能超过 100%）\n\n"
        + table(["主题", "条数", "占比"], theme_rows),
        "**层级分布**\n\n" + table(["层级", "条数", "占比"], level_rows),
        "**类型分布**\n\n" + table(["类型", "条数", "占比"], type_rows),
    ])


def trends_block(items: list[dict[str, Any]], previous: list[dict[str, Any]]) -> str:
    if not items:
        return "本月无样本，无法做计数描述。"
    themes = counts(items, "themes")
    types = counts(items, "type")
    levels = counts(items, "level")
    lines = []
    if themes:
        top_theme, top_count = next(iter(themes.items()))
        lines.append(
            f"- 主题频次最高的是「{top_theme}」，{top_count} 条，"
            f"占本月样本的 {top_count / len(items):.0%}。"
        )
    if types:
        top_type, top_count = next(iter(types.items()))
        lines.append(f"- 类型以「{top_type}」为主，{top_count} 条，占 {top_count / len(items):.0%}。")
    if levels:
        top_level, top_count = next(iter(levels.items()))
        lines.append(f"- 层级以「{top_level}」为主，{top_count} 条，占 {top_count / len(items):.0%}。")
    if previous:
        delta = len(items) - len(previous)
        direction = "增加" if delta > 0 else ("减少" if delta < 0 else "持平")
        lines.append(f"- 与上月相比，条目总量{direction} {abs(delta)} 条。")
    else:
        lines.append("- 当前只有一个月样本，暂不判断环比趋势。")
    lines.append(
        "- 以上是计数描述，不是因果判断；建议积累至少 3 个月样本后，"
        "再讨论主题升温、政策收紧或申报窗口变化。"
    )
    return "\n".join(lines)


def increments_block(items: list[dict[str, Any]], limit: int = 6) -> str:
    if not items:
        return "无。"
    rows = []
    for item in sort_items(items)[:limit]:
        rows.append([
            item.get("publish_date") or "—",
            item.get("level", ""),
            item.get("type", ""),
            md_link(item.get("title", ""), item.get("source_url", "")),
            item.get("deadline", "") or "—",
            f"{item.get('priority', '')}/5",
        ])
    return table(["日期", "层级", "类型", "条目", "截止", "规则排序"], rows)


def recommendations_block(items: list[dict[str, Any]]) -> str:
    if not items:
        return "- 本月无新增；先检查信源健康、接口/页面改版与定时任务。\n- 补充 1–2 个备用源，避免单点失效。"
    lines = []
    applications = [item for item in items if item.get("type") == "申报"]
    if applications:
        deadlines = sorted(
            item["deadline"] for item in applications if parse_date(item.get("deadline"))
        )
        suffix = f"，最早截止 {deadlines[0]}" if deadlines else ""
        lines.append(f"- 建立/更新截止台账：{len(applications)} 条申报类条目{suffix}。")

    consultations = [item for item in items if item.get("type") == "征求意见"]
    if consultations:
        lines.append(f"- 安排意见反馈：{len(consultations)} 条征求意见稿，先核对反馈渠道与截止时间。")

    low = [item for item in items if item.get("confidence") == "低"]
    if low:
        lines.append(f"- 复核低置信度条目：{len(low)} 条，优先补正文、日期和文号。")

    tiers = {item.get("source_tier") for item in items}
    l3_count = sum(1 for item in items if item.get("source_tier") == "L3")
    if not ({"L2", "L3"} & tiers):
        lines.append("- 补充媒体/解读源 1–2 个，用于交叉验证官方源没有覆盖的背景信息。")
    elif l3_count / len(items) > 0.5:
        lines.append("- 媒体/解读来源占比偏高，补充官方原文源，避免二手信息偏差。")

    themes = list(counts(items, "themes").keys())[:3]
    if themes:
        lines.append(
            "- 下月观察主题：" + "、".join(themes) + "（按本月频次排序，不代表重要性）。"
        )
    lines.append("- 对本月条目做一次抽样复核：随机抽 3–5 条回原文核对日期、文号和截止时间。")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 模板渲染
# ---------------------------------------------------------------------------

def render_template(name: str, mapping: dict[str, str], fallback: str) -> str:
    path = TEMPLATE_DIR / name
    if path.exists():
        template = path.read_text(encoding="utf-8")
    else:
        template = fallback
    for key, value in mapping.items():
        template = template.replace("{{" + key + "}}", str(value))
    # 模板里残留的占位符不应出现在成品中。
    template = re.sub(r"\{\{[A-Z0-9_]+\}\}", "", template)
    return template.rstrip() + "\n"


def render_daily(index: dict[str, Any], anchor: str) -> tuple[str, str]:
    items, meta = select_items(index, "daily", anchor)
    date = meta["date"]
    deadlines = items if items else index.get("items") or []
    mapping = {
        "DATE": date,
        "GENERATED_AT": index.get("generated_at", ""),
        "ITEM_COUNT": str(len(items)),
        "WINDOW_NOTE": meta["note"],
        "OVERVIEW": overview_block(items),
        "HIGHLIGHTS": highlight_block(items),
        "ITEMS": item_table(items, include_confidence=True),
        "DEADLINES": deadline_table(deadlines, date, horizon=45),
        "SOURCES": sources_table(items),
    }
    text = render_template("daily-brief.md", mapping, FALLBACK_DAILY)
    return text, date


def render_weekly(index: dict[str, Any], anchor: str) -> tuple[str, str]:
    items, meta = select_items(index, "weekly", anchor)
    label = meta["week"]
    all_items = index.get("items") or []
    mapping = {
        "WEEK": label,
        "RANGE": f"{meta['start']} 至 {meta['end']}",
        "GENERATED_AT": index.get("generated_at", ""),
        "ITEM_COUNT": str(len(items)),
        "LEVEL_SUMMARY": format_counts(counts(items, "level")),
        "SIGNALS": signal_block(items, 5),
        "TABLE": item_table(items, include_confidence=True),
        "DEADLINES": deadline_table(all_items, meta["end"], horizon=45),
        "WATCHLIST": watchlist_block(items, meta["end"]),
        "SOURCES": sources_table(items),
        "METHOD_NOTE": METHOD_NOTE,
    }
    text = render_template("weekly-report.md", mapping, FALLBACK_WEEKLY)
    return text, label


def render_monthly(index: dict[str, Any], anchor: str) -> tuple[str, str]:
    items, meta = select_items(index, "monthly", anchor)
    month = meta["month"]
    prev_month = previous_month(month)
    previous = [
        item for item in index.get("items") or []
        if item_date(item).startswith(prev_month)
    ]
    mapping = {
        "MONTH": month,
        "GENERATED_AT": index.get("generated_at", ""),
        "ITEM_COUNT": str(len(items)),
        "OVERVIEW": month_overview(items, previous),
        "DISTRIBUTION": distribution_block(items),
        "TRENDS": trends_block(items, previous),
        "INCREMENTS": increments_block(items),
        "RECOMMENDATIONS": recommendations_block(items),
        "APPENDIX": item_table(items, include_confidence=True),
        "METHOD_NOTE": METHOD_NOTE,
    }
    text = render_template("monthly-report.md", mapping, FALLBACK_MONTHLY)
    return text, month


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从 index.json 生成日报、周报、月报草稿。",
    )
    parser.add_argument("--demo", action="store_true", help="使用 examples/outputs/index.json 与固定日期")
    parser.add_argument("--index", type=Path, default=None, help="index.json 路径")
    parser.add_argument("--out", type=Path, default=None, help="报告输出目录")
    parser.add_argument("--kind", choices=["daily", "weekly", "monthly", "all"], default="all")
    parser.add_argument("--date", default=None, help="日报日期 / 周报所在周 / 月报所在月，默认 demo 2026-11-12")
    parser.add_argument("--month", default=None, help="月报月份 YYYY-MM；优先于 --date")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    index_path = args.index or (DEMO_INDEX if args.demo else LIVE_INDEX)
    out_dir = args.out or (DEMO_OUT if args.demo else LIVE_OUT)
    anchor = parse_date(args.date or (DEMO_DATE if args.demo else ""))
    if not anchor:
        if args.date:
            print(f"[report] 日期无效：{args.date}（建议 YYYY-MM-DD）", file=sys.stderr)
            return 2
        import datetime as dt
        anchor = dt.date.today().isoformat()

    print(f"[report] {'demo' if args.demo else 'live'} · {rel_path(index_path)}")
    try:
        index = load_index(index_path)
        written = []
        if args.kind in ("daily", "all"):
            text, date = render_daily(index, anchor)
            path = out_dir / "daily" / f"{date}.md"
            write_text(path, text)
            written.append(path)
        if args.kind in ("weekly", "all"):
            text, label = render_weekly(index, anchor)
            path = out_dir / "weekly" / f"{label}.md"
            write_text(path, text)
            written.append(path)
        if args.kind in ("monthly", "all"):
            month = args.month or month_of(anchor)
            text, label = render_monthly(index, month + "-01")
            path = out_dir / "monthly" / f"{month}.md"
            write_text(path, text)
            written.append(path)
    except (ReportError, RuntimeError) as exc:
        print(f"\n[report] 失败：{exc}", file=sys.stderr)
        return 2

    print(f"\n[report] 生成 {len(written)} 份草稿：")
    for path in written:
        print(f"  {rel_path(path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
