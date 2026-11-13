# -*- coding: utf-8 -*-
"""采集阶段：把信源列表页变成统一的原始记录。

用法：
    python scripts/fetch.py --demo
    python scripts/fetch.py --config sources/sources.local.yaml
    python scripts/fetch.py --config sources/sources.local.yaml --source demo-city-gov --check

设计边界：
- 只抓公开页面，不绕过登录、验证码、付费墙或访问控制。
- demo 只读 examples/sources 下的离线快照，不访问网络。
- live 需要 requests + PyYAML；缺依赖时给出安装提示，不静默失败。
- 原始 HTML 会存档，后续解析和复核都以存档/原文为准。
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

from common import (
    DEMO_AS_OF,
    ROOT,
    as_of_iso,
    deep_get,
    load_structured,
    normalize_space,
    parse_date,
    parse_html,
    read_json,
    rel_path,
    sha1_text,
    strip_html_fragment,
    write_json,
)

DEMO_SOURCES = ROOT / "examples" / "sources" / "demo_sources.json"
DEFAULT_CONFIG = ROOT / "sources" / "sources.local.yaml"
EXAMPLE_CONFIG = ROOT / "sources" / "sources.example.yaml"

DEFAULT_UA = "policy-monitor-workflow/1.0 (public-policy-monitor; low-rate)"


class FetchError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------

def default_raw_dir(demo: bool) -> Path:
    return ROOT / "data" / "demo" / "raw" if demo else ROOT / "data" / "raw"


def record_id(source_id: str, url: str) -> str:
    return "rec-" + sha1_text(f"{source_id}|{url}")[:12]


def clean_list_title(value: str) -> str:
    title = normalize_space(value)
    title = re.sub(r"^[\s·•\-—|]+", "", title)
    title = re.sub(r"\s*20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\s*$", "", title)
    return normalize_space(title)


def keywords_match(title: str, keywords: list[str] | None) -> bool:
    if not keywords:
        return True
    title_lower = title.lower()
    return any(str(word).lower() in title_lower for word in keywords if str(word).strip())


def extract_config(src: dict[str, Any]) -> dict[str, str]:
    keys = [
        "title_selector",
        "body_selector",
        "date_selector",
        "date_meta",
        "doc_no_selector",
        "issuer_selector",
        "summary_selector",
    ]
    return {key: str(src[key]) for key in keys if src.get(key)}


def source_meta(src: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": src.get("id", ""),
        "name": src.get("name", ""),
        "type": src.get("type") or src.get("adapter") or "html",
        "signal": src.get("signal", "政策"),
        "level": src.get("level", ""),
        "department": src.get("department", ""),
        "source_tier": src.get("source_tier", "L1"),
        "list_url": src.get("list_url") or src.get("api_url", ""),
    }


def build_record(
    src: dict[str, Any],
    url: str,
    title: str,
    date_hint: str,
    summary_hint: str,
    as_of: str,
    first_seen_hint: str = "",
    detail_html: str = "",
    html_path: str = "",
) -> dict[str, Any]:
    return {
        "record_id": record_id(str(src.get("id", src.get("name", ""))), url),
        "source_id": src.get("id", ""),
        "source_name": src.get("name", ""),
        "source_tier": src.get("source_tier", "L1"),
        "level": src.get("level", ""),
        "department": src.get("department", ""),
        "signal": src.get("signal", "政策"),
        "list_url": src.get("list_url") or src.get("api_url", ""),
        "url": url,
        "title_hint": normalize_space(title),
        "date_hint": parse_date(date_hint),
        "summary_hint": normalize_space(summary_hint),
        "first_seen_hint": parse_date(first_seen_hint) or parse_date(date_hint) or as_of[:10],
        "fetched_at": as_of,
        "html": detail_html,
        "html_path": html_path,
        "extract": extract_config(src),
    }


def archive_html(out_dir: Path, rec_id: str, html_text: str) -> str:
    path = out_dir / "html" / f"{rec_id}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html_text, encoding="utf-8", newline="\n")
    return rel_path(path)


def write_health(out_dir: Path, health: list[dict[str, Any]]) -> None:
    path = out_dir / "health.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["source_id", "source_name", "status", "items", "fetched_at", "error"]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in health:
            writer.writerow({key: row.get(key, "") for key in fields})


def write_raw(out_dir: Path, mode: str, as_of: str, sources: list[dict[str, Any]],
              records: list[dict[str, Any]], errors: list[dict[str, Any]]) -> Path:
    path = out_dir / "raw.json"
    write_json(path, {
        "schema_version": "1.0",
        "mode": mode,
        "generated_at": as_of,
        "sources": sources,
        "records": records,
        "errors": errors,
    })
    return path


# ---------------------------------------------------------------------------
# demo：读取离线 HTML 快照
# ---------------------------------------------------------------------------

def fetch_demo(
    sources_path: Path,
    out_dir: Path,
    as_of: str,
    only: list[str] | None = None,
    check: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    conf = read_json(sources_path)
    if not conf or not conf.get("sources"):
        raise FetchError(f"demo 信源配置为空或不存在：{rel_path(sources_path)}")

    base_dir = sources_path.parent
    records: list[dict[str, Any]] = []
    health: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    sources_meta: list[dict[str, Any]] = []

    for src in conf["sources"]:
        if src.get("enabled") is False:
            continue
        if only and not any(
            needle in str(src.get("id", "")) or needle in str(src.get("name", ""))
            for needle in only
        ):
            continue
        sources_meta.append(source_meta(src))
        name = src.get("name", src.get("id", "未命名信源"))
        snapshot = src.get("snapshot")
        if not snapshot:
            message = "demo 信源缺少 snapshot 字段"
            errors.append({"source_id": src.get("id", ""), "error": message})
            health.append({
                "source_id": src.get("id", ""), "source_name": name,
                "status": "error", "items": 0, "fetched_at": as_of, "error": message,
            })
            continue

        try:
            html_text = (base_dir / snapshot).read_text(encoding="utf-8")
            tree = parse_html(html_text)
            item_selector = src.get("item_selector", "li.news-item")
            link_selector = src.get("link_selector", "a.news-link")
            items = tree.select(item_selector)
            count = 0
            max_items = int(src.get("max_items", 20))
            for item in items:
                if count >= max_items:
                    break
                anchor = item.select_one(link_selector) or item.select_one("a[href]")
                if not anchor:
                    continue
                href = anchor.get("href").strip()
                if not href or href.startswith(("#", "javascript:", "mailto:")):
                    continue

                title_node = anchor.select_one(".news-title") or item.select_one(".news-title")
                title = clean_list_title(
                    title_node.inner_text() if title_node else anchor.inner_text()
                )
                if len(title) < 4:
                    continue
                if not keywords_match(title, src.get("keywords")):
                    continue

                date_node = item.select_one("time") or item.select_one(".news-date")
                date_hint = ""
                if date_node:
                    date_hint = date_node.get("datetime") or date_node.inner_text()

                summary_node = item.select_one(".news-summary")
                summary = summary_node.inner_text() if summary_node else ""

                detail = item.select_one("template.demo-detail")
                detail_html = detail.inner_html() if detail else ""

                url = urljoin(src.get("list_url", "https://example.gov.cn/"), href)
                records.append(build_record(
                    src=src,
                    url=url,
                    title=title,
                    date_hint=date_hint,
                    summary_hint=summary,
                    as_of=as_of,
                    first_seen_hint=date_hint,
                    detail_html=detail_html,
                ))
                count += 1

            health.append({
                "source_id": src.get("id", ""), "source_name": name,
                "status": "ok" if count else "empty", "items": count,
                "fetched_at": as_of, "error": "",
            })
            print(f"  [ok] {name}：{count} 条")
        except Exception as exc:  # noqa: BLE001 - 单源失败不应中断整条流水线
            message = f"{type(exc).__name__}: {exc}"[:240]
            errors.append({"source_id": src.get("id", ""), "error": message})
            health.append({
                "source_id": src.get("id", ""), "source_name": name,
                "status": "error", "items": 0, "fetched_at": as_of, "error": message,
            })
            print(f"  [x] {name}：{message}")

    if not check:
        out_dir.mkdir(parents=True, exist_ok=True)
        write_raw(out_dir, "demo", as_of, sources_meta, records, errors)
        write_health(out_dir, health)
    return records, health, errors


# ---------------------------------------------------------------------------
# live：HTML / JSON / RSS
# ---------------------------------------------------------------------------

def require_live_deps() -> None:
    try:
        import requests  # noqa: F401
    except ImportError as exc:
        raise FetchError(
            "live 模式需要 requests。\n"
            "安装：python -m pip install -r requirements.txt\n"
            "如果只想离线试用：python scripts/run_pipeline.py --demo"
        ) from exc
    try:
        import yaml  # noqa: F401
    except ImportError as exc:
        raise FetchError(
            "live 模式需要 PyYAML。\n"
            "安装：python -m pip install -r requirements.txt\n"
            "如果只想离线试用：python scripts/run_pipeline.py --demo"
        ) from exc


def http_get(session: Any, url: str, timeout: float) -> Any:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.get(url, timeout=timeout, allow_redirects=True)
            if response.status_code >= 400:
                raise FetchError(f"HTTP {response.status_code}")
            return response
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < 2:
                time.sleep(1.0 + attempt)
    raise FetchError(str(last_error)[:200])


def http_post(session: Any, url: str, timeout: float, **kwargs: Any) -> Any:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = session.post(url, timeout=timeout, allow_redirects=True, **kwargs)
            if response.status_code >= 400:
                raise FetchError(f"HTTP {response.status_code}")
            return response
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < 2:
                time.sleep(1.0 + attempt)
    raise FetchError(str(last_error)[:200])


def _date_from_url(href: str, pattern: str) -> str:
    if not pattern:
        return ""
    match = re.search(pattern, href)
    if not match:
        return ""
    groups = match.groups()
    if len(groups) >= 3:
        try:
            return f"{int(groups[0]):04d}-{int(groups[1]):02d}-{int(groups[2]):02d}"
        except (TypeError, ValueError):
            return ""
    if groups:
        return parse_date(groups[0])
    return ""


def _list_date(anchor: Any, href: str, src: dict[str, Any]) -> str:
    date = _date_from_url(href, str(src.get("date_from_url") or ""))
    if date:
        return date

    selector = src.get("list_date_selector")
    if selector:
        node = anchor.select_one(selector)
        if not node:
            parent = anchor.parent
            for _ in range(4):
                if parent is None or parent.tag == "#document":
                    break
                node = parent.select_one(selector)
                if node:
                    break
                parent = parent.parent
        if node:
            date = parse_date(node.get("datetime") or node.inner_text())
            if date:
                return date

    if src.get("date_from_title"):
        match = re.search(str(src["date_from_title"]), anchor.inner_text())
        if match:
            return parse_date(match.group(1) if match.groups() else match.group(0))
    return ""


def _detail_html(session: Any, url: str, timeout: float) -> str:
    response = http_get(session, url, timeout)
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def fetch_html_live(
    src: dict[str, Any],
    session: Any,
    out_dir: Path,
    as_of: str,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    list_url = src.get("list_url")
    if not list_url:
        raise FetchError("html 信源缺少 list_url")

    response = http_get(session, list_url, args.timeout)
    if not response.encoding or response.encoding.lower() == "iso-8859-1":
        response.encoding = response.apparent_encoding or "utf-8"
    tree = parse_html(response.text)

    link_pattern = str(src.get("link_pattern") or "")
    regex = re.compile(link_pattern) if link_pattern else None
    anchors = tree.select("a[href]")
    max_items = int(args.limit or src.get("max_items", 20))
    seen: set[str] = set()
    records: list[dict[str, Any]] = []

    for anchor in anchors:
        if len(records) >= max_items:
            break
        href = anchor.get("href").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        if regex and not (regex.search(href) or regex.search(urljoin(list_url, href))):
            continue
        url = urljoin(list_url, href)
        if url in seen:
            continue

        title_selector = src.get("title_selector")
        title_node = anchor.select_one(title_selector) if title_selector else None
        title = clean_list_title(title_node.inner_text() if title_node else anchor.inner_text())
        if len(title) < 4:
            continue
        if not keywords_match(title, src.get("keywords")):
            continue

        date_hint = _list_date(anchor, href, src)
        summary = ""
        summary_selector = src.get("summary_selector")
        if summary_selector:
            node = anchor.select_one(summary_selector)
            if not node:
                parent = anchor.parent
                node = parent.select_one(summary_selector) if parent else None
            if node:
                summary = node.inner_text()

        seen.add(url)
        detail_html = ""
        html_path = ""
        if src.get("fetch_detail", True) and not args.check:
            try:
                detail_html = _detail_html(session, url, args.timeout)
                rec_id = record_id(str(src.get("id", "")), url)
                html_path = archive_html(out_dir, rec_id, detail_html)
            except Exception as exc:  # noqa: BLE001
                print(f"    ! 详情抓取失败，保留列表信息：{str(exc)[:120]}")
            time.sleep(float(src.get("delay", 0.8)))

        records.append(build_record(
            src=src, url=url, title=title, date_hint=date_hint,
            summary_hint=summary, as_of=as_of, detail_html=detail_html,
            html_path=html_path,
        ))
        print(f"    [{len(records)}] {title[:48]} | {date_hint or '日期待定'}")
    return records


def _substitute(value: Any, query: str | None) -> Any:
    if query is None:
        return value
    if isinstance(value, str):
        return value.replace("{q}", query)
    if isinstance(value, list):
        return [_substitute(item, query) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, query) for key, item in value.items()}
    return value


def _epoch_date(value: Any, mode: str) -> str:
    if isinstance(value, (int, float)):
        stamp = float(value)
        if mode == "epoch_ms" or stamp > 1e12:
            stamp /= 1000.0
        import datetime as dt
        try:
            return dt.datetime.fromtimestamp(stamp).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    return parse_date(value)


def fetch_json_live(
    src: dict[str, Any],
    session: Any,
    out_dir: Path,
    as_of: str,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    import json as jsonlib

    api_url = src.get("api_url")
    if not api_url:
        raise FetchError("json 信源缺少 api_url")
    method = str(src.get("api_method", "GET")).upper()
    content_type = str(src.get("api_content_type", "json")).lower()
    headers = dict(src.get("api_headers") or {})
    queries = src.get("queries") or [None]
    if isinstance(queries, (str, int)):
        queries = [queries]
    max_items = int(args.limit or src.get("max_items", 30))
    rows: list[dict[str, Any]] = []

    for query in queries:
        url = str(api_url).replace("{q}", str(query)) if query is not None else str(api_url)
        body = _substitute(src.get("api_body"), query)
        params = _substitute(src.get("api_params"), query)
        if method == "POST":
            if content_type == "text":
                payload = body if isinstance(body, str) else jsonlib.dumps(body, ensure_ascii=False)
                response = http_post(
                    session, url, args.timeout, headers={**headers, "Content-Type": "text/plain"},
                    data=payload.encode("utf-8"),
                )
            elif content_type == "form":
                if isinstance(body, str):
                    body = jsonlib.loads(body)
                response = http_post(
                    session, url, args.timeout, headers=headers, data=body or {},
                )
            else:
                if isinstance(body, str):
                    body = jsonlib.loads(body)
                response = http_post(
                    session, url, args.timeout, headers=headers, json=body or {},
                )
        else:
            if params is None and isinstance(body, dict):
                params = body
            elif params is None and isinstance(body, str) and body.strip().startswith("{"):
                params = jsonlib.loads(body)
            if params:
                separator = "&" if "?" in url else "?"
                response = http_get(session, f"{url}{separator}{_urlencode(params)}", args.timeout)
            else:
                response = http_get(session, url, args.timeout)

        data = response.json()
        path = str(src.get("items_path") or "")
        chunk = deep_get(data, path) if path else data
        if not isinstance(chunk, list):
            raise FetchError(f"items_path={path or '(root)'} 没有返回列表")
        rows.extend(item for item in chunk if isinstance(item, dict))
        if len(rows) >= max_items:
            break
        if len(queries) > 1:
            time.sleep(float(src.get("delay", 0.4)))

    seen: set[str] = set()
    records: list[dict[str, Any]] = []
    for row in rows[:max_items]:
        title = row.get(src.get("title_field", "title"))
        title = strip_html_fragment(str(title or ""))
        if len(title) < 4 or not keywords_match(title, src.get("keywords")):
            continue

        url = row.get(src.get("url_field", "url")) if src.get("url_field") else ""
        if not url and src.get("url_template"):
            try:
                url = str(src["url_template"]).format(**row)
            except (KeyError, ValueError):
                url = ""
        url = str(url or "").strip()
        if url.startswith("//"):
            url = "https:" + url
        elif url.startswith("/"):
            url = urljoin(str(src.get("list_url") or api_url), url)
        if not url or url in seen:
            continue
        seen.add(url)

        date_mode = str(src.get("date_format", "auto"))
        date_hint = _epoch_date(row.get(src.get("date_field", "")), date_mode)
        summary_raw = row.get(src.get("summary_field", "")) if src.get("summary_field") else ""
        summary = strip_html_fragment(str(summary_raw or ""))
        department = str(row.get(src.get("department_field", "")) or "") if src.get("department_field") else ""
        doc_no = ""
        if src.get("doc_no_fields"):
            doc_no = "".join(str(row.get(field, "") or "") for field in src["doc_no_fields"])

        detail_html = ""
        html_path = ""
        if src.get("fetch_detail") and url.startswith("http") and not args.check:
            try:
                detail_html = _detail_html(session, url, args.timeout)
                rec_id = record_id(str(src.get("id", "")), url)
                html_path = archive_html(out_dir, rec_id, detail_html)
            except Exception as exc:  # noqa: BLE001
                print(f"    ! 详情抓取失败：{str(exc)[:120]}")
            time.sleep(float(src.get("delay", 0.6)))

        record = build_record(
            src={**src, "department": department or src.get("department", "")},
            url=url, title=title, date_hint=date_hint, summary_hint=summary,
            as_of=as_of, detail_html=detail_html, html_path=html_path,
        )
        if doc_no:
            record["doc_no_hint"] = doc_no
        records.append(record)
        print(f"    [{len(records)}] {title[:48]} | {date_hint or '日期待定'}")
    return records


def _urlencode(params: dict[str, Any]) -> str:
    from urllib.parse import urlencode
    return urlencode({key: value for key, value in params.items() if value is not None})


def _localname(tag: str) -> str:
    return tag.split("}")[-1]


def fetch_rss_live(
    src: dict[str, Any],
    session: Any,
    out_dir: Path,
    as_of: str,
    args: argparse.Namespace,
) -> list[dict[str, Any]]:
    list_url = src.get("list_url")
    if not list_url:
        raise FetchError("rss 信源缺少 list_url")
    response = http_get(session, list_url, args.timeout)
    root = ET.fromstring(response.content)
    entries = [node for node in root.iter() if _localname(node.tag) in ("item", "entry")]
    max_items = int(args.limit or src.get("max_items", 20))
    records: list[dict[str, Any]] = []

    for entry in entries[:max_items]:
        values: dict[str, str] = {}
        link = ""
        for child in entry:
            name = _localname(child.tag)
            if name == "link" and child.get("href"):
                link = child.get("href")
            values.setdefault(name, normalize_space(child.text))
        title = strip_html_fragment(values.get("title", ""))
        link = link or values.get("link", "")
        if len(title) < 4 or not link or not keywords_match(title, src.get("keywords")):
            continue
        date_hint = parse_date(
            values.get("pubDate") or values.get("published") or values.get("updated")
        )
        summary = strip_html_fragment(
            values.get("description") or values.get("summary") or values.get("content") or ""
        )
        detail_html = ""
        html_path = ""
        if src.get("fetch_detail") and not args.check:
            try:
                detail_html = _detail_html(session, link, args.timeout)
                rec_id = record_id(str(src.get("id", "")), link)
                html_path = archive_html(out_dir, rec_id, detail_html)
            except Exception as exc:  # noqa: BLE001
                print(f"    ! 详情抓取失败：{str(exc)[:120]}")
            time.sleep(float(src.get("delay", 0.5)))
        records.append(build_record(
            src=src, url=link, title=title, date_hint=date_hint,
            summary_hint=summary, as_of=as_of, detail_html=detail_html,
            html_path=html_path,
        ))
        print(f"    [{len(records)}] {title[:48]} | {date_hint or '日期待定'}")
    return records


def fetch_live(
    config_path: Path,
    out_dir: Path,
    as_of: str,
    only: list[str] | None = None,
    check: bool = False,
    limit: int | None = None,
    timeout: float = 20.0,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    require_live_deps()
    import requests

    if not config_path.exists():
        raise FetchError(
            f"找不到 live 配置：{rel_path(config_path)}\n"
            f"先复制示例配置：{rel_path(EXAMPLE_CONFIG)} -> {rel_path(DEFAULT_CONFIG)}\n"
            "然后按 docs/sources.md 修改信源。"
        )

    conf = load_structured(config_path) or {}
    defaults = conf.get("defaults") or {}
    sources: list[dict[str, Any]] = []
    for raw_source in conf.get("sources") or []:
        merged = {**defaults, **raw_source}
        if merged.get("enabled") is False:
            continue
        if only and not any(
            needle in str(merged.get("id", "")) or needle in str(merged.get("name", ""))
            for needle in only
        ):
            continue
        sources.append(merged)

    if not sources:
        raise FetchError("没有启用的信源；检查配置里的 enabled 与 --source 过滤条件。")

    session = requests.Session()
    session.headers.update({
        "User-Agent": str(conf.get("user_agent") or DEFAULT_UA),
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.7",
    })

    args = argparse.Namespace(timeout=timeout, limit=limit, check=check)
    records: list[dict[str, Any]] = []
    health: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    sources_meta: list[dict[str, Any]] = []

    for src in sources:
        name = src.get("name", src.get("id", "未命名信源"))
        sources_meta.append(source_meta(src))
        print(f"\n[{src.get('id', '')}] {name}")
        try:
            kind = str(src.get("type") or src.get("adapter") or "html").lower()
            if kind == "html":
                found = fetch_html_live(src, session, out_dir, as_of, args)
            elif kind == "json":
                found = fetch_json_live(src, session, out_dir, as_of, args)
            elif kind == "rss":
                found = fetch_rss_live(src, session, out_dir, as_of, args)
            elif kind in ("manual", "dead"):
                found = []
                print("    · 人工/停更信源，跳过自动抓取")
            else:
                raise FetchError(f"未知信源类型：{kind}")
            records.extend(found)
            health.append({
                "source_id": src.get("id", ""), "source_name": name,
                "status": "ok" if found else ("manual" if kind in ("manual", "dead") else "empty"),
                "items": len(found), "fetched_at": as_of, "error": "",
            })
            print(f"    = {len(found)} 条")
        except Exception as exc:  # noqa: BLE001
            message = f"{type(exc).__name__}: {exc}"[:240]
            errors.append({"source_id": src.get("id", ""), "error": message})
            health.append({
                "source_id": src.get("id", ""), "source_name": name,
                "status": "error", "items": 0, "fetched_at": as_of, "error": message,
            })
            print(f"    [x] {message}")

    if not check:
        out_dir.mkdir(parents=True, exist_ok=True)
        write_raw(out_dir, "live", as_of, sources_meta, records, errors)
        write_health(out_dir, health)
    return records, health, errors


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="采集信源列表页，输出统一的 raw.json 与 health.csv。",
    )
    parser.add_argument("--demo", action="store_true", help="读取 examples/sources 的离线快照，不访问网络")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="live 信源配置（YAML）")
    parser.add_argument("--sources-json", type=Path, default=DEMO_SOURCES, help="demo 信源清单（JSON）")
    parser.add_argument("--out", type=Path, default=None, help="输出目录；默认 demo 用 data/demo/raw，live 用 data/raw")
    parser.add_argument("--source", action="append", default=None, help="只跑匹配 id/名称的信源，可重复")
    parser.add_argument("--limit", type=int, default=None, help="每个信源最多抓多少条")
    parser.add_argument("--timeout", type=float, default=20.0, help="单次 HTTP 超时秒数")
    parser.add_argument("--as-of", default=None, help="demo 的固定观察时点，默认 2026-11-12T18:00:00+08:00")
    parser.add_argument("--check", action="store_true", help="只检查列表能否取到，不抓详情、不写文件")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        as_of = as_of_iso(args.as_of or (DEMO_AS_OF if args.demo else None))
    except ValueError as exc:
        print(f"[fetch] 参数错误：{exc}", file=sys.stderr)
        return 2
    out_dir = args.out or default_raw_dir(args.demo)

    try:
        if args.demo:
            print(f"[fetch] demo 模式 · {rel_path(args.sources_json)}")
            records, health, errors = fetch_demo(
                args.sources_json, out_dir, as_of, only=args.source, check=args.check,
            )
            mode = "demo"
        else:
            print(f"[fetch] live 模式 · {rel_path(args.config)}")
            records, health, errors = fetch_live(
                args.config, out_dir, as_of, only=args.source, check=args.check,
                limit=args.limit, timeout=args.timeout,
            )
            mode = "live"
    except FetchError as exc:
        print(f"\n[fetch] 失败：{exc}", file=sys.stderr)
        return 2

    ok_sources = sum(1 for row in health if row["status"] == "ok")
    print(
        f"\n[fetch] {mode} 完成：{len(records)} 条记录 / "
        f"{ok_sources} 个正常信源 / {len(errors)} 个错误"
    )
    if args.check:
        print("[fetch] 检查模式，未写入文件。")
    else:
        print(f"  raw：{rel_path(out_dir / 'raw.json')}")
        print(f"  health：{rel_path(out_dir / 'health.csv')}")
    return 0 if records or not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
