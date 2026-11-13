# -*- coding: utf-8 -*-
"""解析阶段：把原始 HTML 规范化为一条条可索引的 JSON。

用法：
    python scripts/parse.py --demo
    python scripts/parse.py --raw data/raw/raw.json --out data/items

原则：
- 只做标题、正文、日期、文号、机构、截止日期等“可核对字段”的抽取。
- 摘要使用原文前几句（抽取式），不改写；影响判断留给人和 AI 初判。
- 每个字段都记录来源，无法确认时留空并写入 warnings。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

from common import (
    DEMO_AS_OF,
    ROOT,
    as_of_iso,
    days_between,
    first_sentences,
    load_structured,
    meta_content,
    normalize_lines,
    normalize_space,
    parse_date,
    parse_html,
    read_json,
    rel_path,
    sha1_text,
    sha256_text,
    truncate,
    write_json,
)

DEMO_RAW = ROOT / "data" / "demo" / "raw" / "raw.json"
DEMO_ITEMS = ROOT / "examples" / "items"
DEMO_SOURCES = ROOT / "examples" / "sources" / "demo_sources.json"
LIVE_RAW = ROOT / "data" / "raw" / "raw.json"
LIVE_ITEMS = ROOT / "data" / "items"

MAX_BODY = 60000

DEFAULT_TAXONOMY: dict[str, list[str]] = {
    "智能制造": ["智能制造", "智能工厂", "工业互联网", "数字化转型", "技术改造", "未来工厂"],
    "人工智能": ["人工智能", "大模型", "生成式", "智能体", "算法", "AIGC", "生成内容"],
    "数据要素": ["数据要素", "公共数据", "数据授权", "数据流通", "数据资产", "数据交易", "语料"],
    "机器人": ["机器人", "具身智能", "人形机器人", "智能装备"],
    "科技创新": ["科技创新", "研发", "成果转化", "创新平台", "实验室", "科技计划"],
    "企业培育": ["专精特新", "小巨人", "高新技术企业", "科技型中小企业", "企业培育", "独角兽"],
    "人才": ["人才", "职称", "落户", "博士后", "技能人才", "引才"],
    "标准合规": ["标准化", "标准体系", "团体标准", "地方标准", "认证", "合规", "标识", "检验检测"],
    "规划": ["规划", "行动计划", "三年行动", "十五五", "十四五"],
}

DATE_META_NAMES = [
    "PubDate", "publishdate", "publish_date", "article:published_time",
    "date", "dc.date", "dc.date.issued", "og:published_time", "parsely-pub-date",
]

DOC_NO_RE = re.compile(
    r"[\u4e00-\u9fa5A-Za-z]{1,16}[〔\[（(]\s*20\d{2}\s*[〕\]）)]\s*第?\s*\d{1,5}\s*号"
)

BODY_SELECTORS = [
    ".article-body", ".article-content", ".article", ".content", "#content",
    "#ivs_content", ".TRS_Editor", ".text-main", "article", "main",
]

BOILERPLATE_RE = re.compile(
    r"^(打印本页|关闭窗口|字体[：:]|字号[：:]|分享到|扫一扫|返回顶部|上一篇|下一篇|"
    r"责任编辑[：:]|来源[：:]|作者[：:]|编辑[：:]|审核[：:]|签发[：:]|"
    r"版权所有|网站地图|联系我们)"
)

LEVEL_PREFIX = {
    "国家": "CN",
    "省级": "PROV",
    "市级": "CITY",
    "市级部门": "CITY",
    "区级": "DIST",
    "园区": "PARK",
    "协会": "ASSOC",
    "媒体": "MEDIA",
    "行业": "IND",
}


class ParseError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 主题与类型
# ---------------------------------------------------------------------------

def load_taxonomy(path: Path | None = None) -> dict[str, list[str]]:
    if not path:
        return dict(DEFAULT_TAXONOMY)
    if not path.exists():
        print(f"[parse] 提示：主题配置不存在，使用内置主题：{rel_path(path)}")
        return dict(DEFAULT_TAXONOMY)
    data = load_structured(path) or {}
    custom = data.get("taxonomy") if isinstance(data, dict) else None
    if custom is None and isinstance(data, dict):
        # 也允许直接传 {"主题": ["关键词"]} 形式。
        if all(isinstance(value, (list, dict)) for value in data.values()):
            custom = data
    if not isinstance(custom, dict) or not custom:
        return dict(DEFAULT_TAXONOMY)

    # 配置里给了 taxonomy 就完整替换内置表，避免旧领域的词继续误命中。
    taxonomy: dict[str, list[str]] = {}
    for theme, words in custom.items():
        if isinstance(words, dict):
            words = words.get("keywords") or words.get("words") or []
        if isinstance(words, str):
            words = [words]
        if isinstance(words, list):
            cleaned = [str(word) for word in words if str(word).strip()]
            if cleaned:
                taxonomy[str(theme)] = cleaned
    return taxonomy or dict(DEFAULT_TAXONOMY)


def match_themes(text: str, taxonomy: dict[str, list[str]]) -> tuple[list[str], list[str]]:
    lowered = text.lower()
    themes: list[str] = []
    matched_words: list[str] = []
    for theme, words in taxonomy.items():
        hits = [word for word in words if word and word.lower() in lowered]
        if hits:
            themes.append(theme)
            matched_words.extend(hits)
    return themes[:6], list(dict.fromkeys(matched_words))[:20]


def infer_type(title: str, body: str, signal: str) -> tuple[str, str]:
    if "解读" in title or signal == "解读":
        return "解读", "政策解读"
    if "征求意见" in title or "征求意见稿" in title or "公开征求意见" in title:
        return "征求意见", "征求意见稿"
    if any(word in title for word in ["申报", "征集", "揭榜挂帅", "遴选", "申报指南"]):
        subtype = "申报指南" if "指南" in title else "申报通知"
        return "申报", subtype
    if any(word in title for word in ["规划", "行动计划", "实施方案", "三年行动"]):
        return "规划", "规划/方案"
    if any(word in title for word in ["标准", "标准化", "团体标准", "地方标准"]):
        return "标准", "标准"
    if any(word in title for word in ["办法", "规定", "细则", "意见", "通知", "决定", "公告", "措施", "指引"]):
        if "办法" in title:
            return "政策", "办法"
        if "细则" in title:
            return "政策", "细则"
        if "措施" in title:
            return "政策", "措施"
        if "指引" in title:
            return "政策", "指引"
        return "政策", "通知/意见"
    if signal in ("舆情", "资讯"):
        return "资讯", "资讯"
    return "其他", "其他"


# ---------------------------------------------------------------------------
# 字段抽取
# ---------------------------------------------------------------------------

def clean_title(value: str) -> str:
    text = normalize_space(value)
    text = re.sub(r"^[\s·•\-—|]+", "", text)
    # 只去掉明显是站点名的尾巴，避免误伤“……的通知 - 解读”这类标题。
    for separator in [" - ", "_", "|", "—"]:
        if separator in text:
            head, tail = text.rsplit(separator, 1)
            if len(tail) <= 24 and any(
                word in tail for word in ["网", "政府", "委员会", "局", "站", "频道", "新闻", "门户"]
            ):
                text = head.strip()
    return normalize_space(text)


def extract_title(tree: Any, selectors: dict[str, str], hint: str) -> tuple[str, str]:
    if selectors.get("title_selector"):
        node = tree.select_one(selectors["title_selector"])
        if node and node.inner_text():
            return clean_title(node.inner_text()), "选择器"

    for selector in ["h1", ".article-title", ".news-title", ".title"]:
        node = tree.select_one(selector)
        if node and node.inner_text():
            return clean_title(node.inner_text()), f"页面 {selector}"

    meta_title = meta_content(tree, ["og:title", "twitter:title"])
    if meta_title:
        return clean_title(meta_title), "meta"

    title_node = tree.select_one("title")
    if title_node and title_node.inner_text():
        return clean_title(title_node.inner_text()), "title 标签"

    if hint:
        return clean_title(hint), "列表标题"
    return "", "未识别"


def clean_body(text: str) -> str:
    lines: list[str] = []
    for line in normalize_lines(text).split("\n"):
        if not line or BOILERPLATE_RE.match(line):
            continue
        if re.fullmatch(r"[\-—_=·\s]+", line):
            continue
        lines.append(line)
    return "\n".join(lines)


def extract_body(tree: Any, selectors: dict[str, str], title: str) -> tuple[str, str, list[str]]:
    warnings: list[str] = []
    candidates: list[tuple[int, str, str]] = []

    configured = selectors.get("body_selector")
    if configured:
        node = tree.select_one(configured)
        if node:
            text = clean_body(node.text())
            if text:
                candidates.append((100, text, configured))

    for selector in BODY_SELECTORS:
        if selector == configured:
            continue
        node = tree.select_one(selector)
        if node:
            text = clean_body(node.text())
            if text:
                candidates.append((60, text, selector))

    if not candidates:
        body_node = tree.select_one("body")
        if body_node:
            text = clean_body(body_node.text(skip={
                "script", "style", "noscript", "template", "svg", "nav", "footer", "header",
            }))
            if text:
                candidates.append((20, text, "body 兜底"))
                warnings.append("未命中正文选择器，使用整页文本兜底")

    if not candidates:
        return "", "未识别", ["未提取到正文"]

    # 优先使用配置选择器；没有配置时选文本最长者，避免抓到导航短块。
    candidates.sort(key=lambda item: (item[0], len(item[1])), reverse=True)
    _, body, source = candidates[0]

    if title and body.startswith(title) and len(body) > len(title) + 20:
        body = body[len(title):].lstrip(" \n：:—")
    if len(body) < 120:
        warnings.append("正文较短，可能只抓到了摘要或列表信息")
    if len(body) > MAX_BODY:
        body = body[:MAX_BODY]
        warnings.append(f"正文超过 {MAX_BODY} 字，已截断；完整内容见原文")
    return body, source, warnings


def extract_date(
    tree: Any,
    selectors: dict[str, str],
    body: str,
    url: str,
    hint: str,
    as_of_date: str,
) -> tuple[str, str, list[str]]:
    warnings: list[str] = []
    candidates: list[tuple[int, str, str]] = []

    def add(priority: int, value: str, source: str) -> None:
        parsed = parse_date(value)
        if parsed:
            candidates.append((priority, parsed, source))

    if selectors.get("date_selector"):
        node = tree.select_one(selectors["date_selector"])
        if node:
            add(100, node.get("datetime") or node.inner_text(), "选择器")

    meta_names = []
    if selectors.get("date_meta"):
        meta_names.append(selectors["date_meta"])
    meta_names.extend(DATE_META_NAMES)
    for name in dict.fromkeys(meta_names):
        value = meta_content(tree, [name])
        if value:
            add(90, value, f"meta {name}")

    for node in tree.select("time[datetime]"):
        add(85, node.get("datetime"), "time 标签")

    for pattern, source in [
        (r"(?:发布时间|发布日期|成文日期|发文日期|日期)[：:]\s*(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)", "正文日期"),
        (r"(?:发布于|发表于)\s*(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)", "正文日期"),
    ]:
        match = re.search(pattern, body[:3000])
        if match:
            add(70, match.group(1), source)

    match = re.search(r"/(20\d{2})[/-]?(\d{2})[/-]?(\d{2})(?:/|$)", url)
    if match:
        add(50, f"{match.group(1)}-{match.group(2)}-{match.group(3)}", "URL")

    if hint:
        add(40, hint, "列表日期")

    if not candidates:
        warnings.append("未识别到发布日期")
        return "", "未识别", warnings

    candidates.sort(key=lambda item: item[0], reverse=True)
    _, chosen, source = candidates[0]
    unique_dates = list(dict.fromkeys(item[1] for item in candidates))
    if len(unique_dates) > 1:
        warnings.append(
            "存在多个日期候选（" + "、".join(unique_dates[:4]) + f"），采用 {chosen}；请回原文核对"
        )

    if chosen > as_of_date:
        delta = days_between(as_of_date, chosen)
        if delta > 30:
            warnings.append(f"发布日期晚于观察时点 {delta} 天，可能是预发布或抓取错误")
    return chosen, source, warnings


def clean_doc_number(value: str) -> str:
    text = normalize_space(value)
    text = re.sub(r"^(文号|发文字号|索引号)[：:]\s*", "", text)
    match = DOC_NO_RE.search(text)
    if match:
        return normalize_space(match.group(0)).replace(" ", "")
    return text if len(text) <= 60 else ""


def extract_doc_number(
    tree: Any,
    selectors: dict[str, str],
    body: str,
    hint: str,
) -> tuple[str, str, list[str]]:
    warnings: list[str] = []
    if selectors.get("doc_no_selector"):
        node = tree.select_one(selectors["doc_no_selector"])
        if node:
            value = clean_doc_number(node.inner_text())
            if value:
                return value, "选择器", warnings

    if hint:
        value = clean_doc_number(hint)
        if value:
            return value, "字段映射", warnings

    matches = list(DOC_NO_RE.finditer(body[:4000]))
    if matches:
        value = normalize_space(matches[0].group(0)).replace(" ", "")
        if len(matches) > 1:
            warnings.append("正文中出现多个文号，采用第一个；请确认不是引用其他文件")
        return value, "正文规则", warnings
    return "", "未识别", warnings


def clean_issuer(value: str) -> str:
    text = normalize_space(value)
    text = re.sub(r"^(发布机构|发文机关|来源|作者)[：:]\s*", "", text)
    return truncate(text, 60)


def extract_issuer(
    tree: Any,
    selectors: dict[str, str],
    hint: str,
    source_name: str,
) -> tuple[str, str]:
    if selectors.get("issuer_selector"):
        node = tree.select_one(selectors["issuer_selector"])
        if node and node.inner_text():
            return clean_issuer(node.inner_text()), "选择器"

    for selector in [".issuer", ".publish-agency", ".source"]:
        node = tree.select_one(selector)
        if node and node.inner_text():
            return clean_issuer(node.inner_text()), f"页面 {selector}"

    # meta author 有时是个人姓名；只有看起来像机构时才采用，避免把个人信息带进索引。
    author = meta_content(tree, ["author", "article:author", "dc.creator"])
    if author and any(
        word in author for word in ("局", "委", "办", "政府", "中心", "协会", "公司", "机构", "大学", "研究院", "厅", "部")
    ):
        return clean_issuer(author), "meta"

    if hint:
        return clean_issuer(hint), "信源配置"
    return clean_issuer(source_name), "信源名称"


def extract_summary(
    tree: Any,
    selectors: dict[str, str],
    body: str,
    hint: str,
) -> tuple[str, str]:
    if selectors.get("summary_selector"):
        node = tree.select_one(selectors["summary_selector"])
        if node and node.inner_text():
            return truncate(node.inner_text(), 220), "选择器"

    description = meta_content(tree, ["description", "og:description"])
    if description:
        return truncate(description, 220), "meta"

    if body:
        return first_sentences(body, 200, 2), "正文抽取"

    if hint:
        return truncate(hint, 220), "列表摘要"
    return "", "未识别"


def extract_deadlines(text: str) -> list[dict[str, str]]:
    patterns = [
        r"(?:申报|提交|报送|反馈|截止)(?:时间|日期)?(?:为|至|：|:)?\s*(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)",
        r"(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)\s*(?:\d{1,2}[:：]\d{2})?\s*(?:前|之前)",
    ]
    found: dict[str, str] = {}
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            date = parse_date(match.group(1))
            if not date:
                continue
            start = max(0, match.start() - 30)
            end = min(len(text), match.end() + 30)
            context = normalize_space(text[start:end])
            found.setdefault(date, context)
    rows = [{"date": key, "context": value} for key, value in sorted(found.items())]
    return rows[:5]


def extract_effective_date(text: str) -> str:
    patterns = [
        r"自\s*(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)\s*起\s*(?:施行|实施|执行|生效)",
        r"(?:施行日期|生效日期|实施日期)[：:]\s*(20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}日?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return parse_date(match.group(1))
    return ""


def priority_for(
    policy_type: str,
    level: str,
    deadline: str,
    publish_date: str,
    as_of_date: str,
) -> tuple[int, str]:
    base = {
        "申报": 5, "征求意见": 4, "规划": 4, "政策": 3,
        "标准": 3, "解读": 2, "资讯": 2, "其他": 2,
    }.get(policy_type, 2)
    level_bonus = {
        "国家": 1, "省级": 1, "市级": 1, "市级部门": 1,
        "区级": 0, "园区": 0, "协会": 0, "媒体": -1, "行业": -1,
    }.get(level, 0)
    score = base + level_bonus
    reasons = [f"{policy_type}类", level or "层级未标"]

    if deadline and publish_date:
        remaining = days_between(publish_date, deadline)
        if 0 <= remaining <= 14:
            score += 1
            reasons.append(f"截止 {remaining} 天内")
        elif remaining < 0:
            reasons.append("截止日期早于发布日期")

    score = max(1, min(5, score))
    return score, "；".join(reasons)


def make_doc_id(level: str, date_text: str, url: str, title: str, as_of_date: str) -> str:
    prefix = LEVEL_PREFIX.get(level, "DOC")
    year = (parse_date(date_text) or as_of_date)[:4]
    digest = sha1_text(url or title)[:8]
    return f"{prefix}-{year}-{digest}"


def load_existing(items_dir: Path) -> dict[str, dict[str, Any]]:
    if not items_dir.exists():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(items_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = read_json(path)
        if isinstance(data, dict) and data.get("source_url"):
            result[data["source_url"]] = data
    return result


# ---------------------------------------------------------------------------
# 主解析
# ---------------------------------------------------------------------------

def parse_record(
    record: dict[str, Any],
    taxonomy: dict[str, list[str]],
    as_of: str,
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []
    url = str(record.get("url") or "")
    html_text = record.get("html") or ""
    html_path = record.get("html_path") or ""
    if not html_text and html_path:
        path = Path(html_path)
        if not path.is_absolute():
            path = ROOT / path
        if path.exists():
            html_text = path.read_text(encoding="utf-8")
        else:
            warnings.append(f"原始 HTML 存档不存在：{html_path}")

    tree = parse_html(html_text)
    selectors = record.get("extract") or {}
    title_hint = str(record.get("title_hint") or "")
    date_hint = str(record.get("date_hint") or "")

    title, title_source = extract_title(tree, selectors, title_hint)
    if not title:
        raise ParseError("标题为空，无法生成条目")

    body, body_source, body_warnings = extract_body(tree, selectors, title)
    warnings.extend(body_warnings)

    publish_date, date_source, date_warnings = extract_date(
        tree, selectors, body, url, date_hint, as_of[:10],
    )
    warnings.extend(date_warnings)

    doc_number, doc_source, doc_warnings = extract_doc_number(
        tree, selectors, body, str(record.get("doc_no_hint") or ""),
    )
    warnings.extend(doc_warnings)

    issuer, issuer_source = extract_issuer(
        tree, selectors, str(record.get("department") or ""), str(record.get("source_name") or ""),
    )
    summary, summary_source = extract_summary(
        tree, selectors, body, str(record.get("summary_hint") or ""),
    )

    deadlines = extract_deadlines(body)
    deadline = deadlines[0]["date"] if deadlines else ""
    effective_date = extract_effective_date(body)

    policy_type, subtype = infer_type(title, body, str(record.get("signal") or "政策"))
    theme_text = title + "\n" + body[:4000]
    themes, matched_keywords = match_themes(theme_text, taxonomy)
    priority, priority_reason = priority_for(
        policy_type, str(record.get("level") or ""), deadline, publish_date, as_of[:10],
    )

    if not publish_date:
        warnings.append("发布日期缺失；报告会退回使用首次发现日期")
    if not doc_number and policy_type in ("政策", "规划", "标准"):
        warnings.append("未识别到文号，请回原文核对")
    if deadline and publish_date and deadline < publish_date:
        warnings.append(f"截止日期 {deadline} 早于发布日期 {publish_date}")
    if effective_date and publish_date and effective_date < publish_date:
        warnings.append(f"施行日期 {effective_date} 早于发布日期 {publish_date}")
    if not body:
        warnings.append("没有正文，只保留标题与列表摘要")

    if not title or not publish_date or len(body) < 120:
        confidence = "低"
    elif doc_number or policy_type in ("解读", "资讯"):
        confidence = "高"
    else:
        confidence = "中"

    review_reasons = []
    if not publish_date:
        review_reasons.append("核对发布日期")
    if not doc_number and policy_type in ("政策", "规划", "标准"):
        review_reasons.append("核对文号")
    if policy_type == "申报":
        review_reasons.append("核对申报对象、材料清单与截止时间")
    if policy_type == "征求意见":
        review_reasons.append("核对反馈渠道与反馈截止时间")
    if policy_type == "解读":
        review_reasons.append("解读不是原文，引用前需回源")
    if str(record.get("source_tier") or "") == "L3":
        review_reasons.append("媒体/行业来源，需回原文交叉核对")
    if confidence == "低":
        review_reasons.append("解析置信度低，先补全正文/日期")

    existing = existing or {}
    first_seen = (
        existing.get("first_seen")
        or parse_date(record.get("first_seen_hint"))
        or parse_date(publish_date)
        or as_of[:10]
    )
    doc_id = existing.get("doc_id") or make_doc_id(
        str(record.get("level") or ""), publish_date, url, title, as_of[:10],
    )
    content_hash = sha256_text("\n".join([title, publish_date, body]))

    previous_review = existing.get("review") or {}
    review = {
        "required": True,
        "reasons": review_reasons,
        "checked_by": previous_review.get("checked_by", ""),
        "checked_at": previous_review.get("checked_at", ""),
        "decision": previous_review.get("decision", ""),
        "notes": previous_review.get("notes", ""),
    }

    item = {
        "schema_version": "1.0",
        "doc_id": doc_id,
        "title": title,
        "issuer": issuer,
        "doc_number": doc_number,
        "level": str(record.get("level") or ""),
        "type": policy_type,
        "subtype": subtype,
        "themes": themes,
        "keywords": matched_keywords,
        "publish_date": publish_date,
        "effective_date": effective_date,
        "deadline": deadline,
        "deadlines": deadlines,
        "status": existing.get("status") or "待研判",
        "priority": priority,
        "priority_reason": priority_reason,
        "signal": record.get("signal") or "政策",
        "summary": summary,
        "body": body,
        "source_url": url,
        "source": {
            "id": record.get("source_id", ""),
            "name": record.get("source_name", ""),
            "tier": record.get("source_tier", ""),
            "level": record.get("level", ""),
            "department": record.get("department", ""),
            "signal": record.get("signal", ""),
            "list_url": record.get("list_url", ""),
        },
        "first_seen": first_seen,
        "last_updated": as_of[:10],
        "parsed_at": as_of,
        "content_hash": content_hash,
        "extraction": {
            "title_source": title_source,
            "date_source": date_source,
            "doc_number_source": doc_source,
            "issuer_source": issuer_source,
            "summary_source": summary_source,
            "body_source": body_source,
            "body_chars": len(body),
            "html_available": bool(html_text),
            "confidence": confidence,
            "warnings": warnings,
        },
        "review": review,
        "owner": existing.get("owner", ""),
        "tags": existing.get("tags", []),
        "notes": existing.get("notes", ""),
    }
    return item


def run(
    raw_path: Path,
    items_dir: Path,
    taxonomy_path: Path | None,
    as_of: str,
    skip_existing: bool = False,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    if not raw_path.exists():
        raise ParseError(
            f"找不到原始数据：{rel_path(raw_path)}\n"
            "先运行采集：python scripts/fetch.py --demo"
        )
    raw = read_json(raw_path) or {}
    records = raw.get("records") or []
    if limit:
        records = records[:limit]
    if not records:
        raise ParseError("raw.json 中没有记录；检查信源是否抓取成功，或先运行 --check。")

    taxonomy = load_taxonomy(taxonomy_path)
    items_dir.mkdir(parents=True, exist_ok=True)
    existing_by_url = load_existing(items_dir)
    written: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    for index, record in enumerate(records, 1):
        url = str(record.get("url") or "")
        existing = existing_by_url.get(url)
        if skip_existing and existing:
            print(f"  [{index}/{len(records)}] 跳过已有条目：{truncate(existing.get('title', ''), 48)}")
            continue
        try:
            item = parse_record(record, taxonomy, as_of, existing)
            write_json(items_dir / f"{item['doc_id']}.json", item)
            existing_by_url[url] = item
            written.append(item)
            print(
                f"  [{index}/{len(records)}] {truncate(item['title'], 48)} | "
                f"{item['publish_date'] or '日期待定'} | {item['extraction']['confidence']}"
            )
        except Exception as exc:  # noqa: BLE001
            message = f"{type(exc).__name__}: {exc}"[:240]
            errors.append({
                "url": url,
                "title_hint": record.get("title_hint", ""),
                "error": message,
            })
            print(f"  [{index}/{len(records)}] [x] {message}")

    error_path = items_dir / "_parse_errors.json"
    if errors:
        write_json(error_path, {
            "generated_at": as_of,
            "errors": errors,
        })
    elif error_path.exists():
        error_path.unlink()

    return written


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="解析 raw.json 中的 HTML，输出标准化条目 JSON。",
    )
    parser.add_argument("--demo", action="store_true", help="使用 examples 的离线数据与固定时点")
    parser.add_argument("--raw", type=Path, default=None, help="raw.json 路径")
    parser.add_argument("--out", type=Path, default=None, help="条目输出目录")
    parser.add_argument("--taxonomy", type=Path, default=None, help="主题词表（JSON/YAML）；默认使用内置词表")
    parser.add_argument("--as-of", default=None, help="观察时点；demo 默认 2026-11-12T18:00:00+08:00")
    parser.add_argument("--skip-existing", action="store_true", help="已有同 URL 条目则跳过，保留人工修改")
    parser.add_argument("--limit", type=int, default=None, help="本次最多解析多少条")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        as_of = as_of_iso(args.as_of or (DEMO_AS_OF if args.demo else None))
    except ValueError as exc:
        print(f"[parse] 参数错误：{exc}", file=sys.stderr)
        return 2
    raw_path = args.raw or (DEMO_RAW if args.demo else LIVE_RAW)
    items_dir = args.out or (DEMO_ITEMS if args.demo else LIVE_ITEMS)
    taxonomy_path = args.taxonomy
    if taxonomy_path is None and args.demo:
        taxonomy_path = DEMO_SOURCES

    print(f"[parse] {'demo' if args.demo else 'live'} · {rel_path(raw_path)}")
    try:
        written = run(
            raw_path, items_dir, taxonomy_path, as_of,
            skip_existing=args.skip_existing, limit=args.limit,
        )
    except (ParseError, RuntimeError) as exc:
        print(f"\n[parse] 失败：{exc}", file=sys.stderr)
        return 2

    errors_path = items_dir / "_parse_errors.json"
    error_count = len((read_json(errors_path) or {}).get("errors", [])) if errors_path.exists() else 0
    print(
        f"\n[parse] 完成：写入 {len(written)} 条 / 错误 {error_count} 条 -> "
        f"{rel_path(items_dir)}"
    )
    # 没有新条目不等于失败：增量运行时，全部跳过是正常结果。
    return 0 if error_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
