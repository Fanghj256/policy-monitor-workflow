# -*- coding: utf-8 -*-
"""把本 workflow 的 index / 报告导出成 agent-workbench-template 的数据包。

用法：
    python scripts/export_workbench.py
    python scripts/export_workbench.py --index outputs/index.json --out outputs/workbench
    python scripts/export_workbench.py --fresh

输出（默认 examples/outputs/workbench/）：
    index.json          workbench-index/v1
    annotations.json    workbench-annotations/v1（来自 overrides.json）
    reports.json        workbench-reports/v1（日报/周报/月报）
    items/<id>/content.md

只读投影：不修改 index.json、overrides.json 或报告原文。
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from common import (
    ROOT,
    normalize_space,
    parse_date,
    read_json,
    rel_path,
    truncate,
    write_json,
    write_text,
)

DEFAULT_INDEX = ROOT / "examples" / "outputs" / "index.json"
DEFAULT_OUT = ROOT / "examples" / "outputs" / "workbench"

REPORT_GROUPS = [
    ("daily", "日报", "daily"),
    ("weekly", "周报", "weekly"),
    ("monthly", "月报", "monthly"),
]
REPORT_ORDER = {"日报": 0, "周报": 1, "月报": 2}

# workbench 筛选器的受控词表。导出时把内部字段映射到这些值，
# 避免“政策/通知/征求意见”等内部分类直接漏进筛选器。
KIND_MAP = {
    "政策": "原文",
    "通知": "原文",
    "征求意见": "原文",
    "公告": "原文",
    "原文": "原文",
    "申报": "申报",
    "申报通知": "申报",
    "申报指南": "申报",
    "解读": "解读",
    "政策解读": "解读",
    "数据": "数据",
    "研究": "研究",
    "竞品": "竞品",
}
KIND_ALLOWED = {"原文", "解读", "数据", "申报", "竞品", "研究"}

LEVEL_MAP = {
    "市级": "示例市",
    "市级部门": "示例部门",
    "区级": "示例区",
    "省级": "示例省",
}

STATUS_MAP = {
    "待研判": "待研判",
    "已读": "已研判",
    "已研判": "已研判",
    "跟进中": "在跟",
    "在跟": "在跟",
    "已归档": "已归档",
}
STATUS_ALLOWED = {"待研判", "在跟", "已研判", "已归档"}


class ExportError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# 读取与映射
# ---------------------------------------------------------------------------

def load_index(path: Path) -> dict[str, Any]:
    data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ExportError(
            f"index.json 不存在或格式不对：{rel_path(path)}\n"
            "先运行：python scripts/run_pipeline.py --demo"
        )
    return data


def generated_date(index: dict[str, Any]) -> str:
    return parse_date(index.get("generated_at")) or dt.date.today().isoformat()


def safe_id(value: str, used: set[str]) -> str:
    base = normalize_space(value)
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("._-")
    if not base:
        base = "item"
    candidate = base
    counter = 2
    while candidate in used:
        candidate = f"{base}-{counter}"
        counter += 1
    used.add(candidate)
    return candidate


def resolve_content_file(value: str, index_path: Path) -> Path | None:
    if not value:
        return None
    raw = Path(value)
    candidates = [raw] if raw.is_absolute() else [
        ROOT / raw,
        index_path.parent / raw,
        index_path.parent.parent / raw,
        Path.cwd() / raw,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def item_content(item: dict[str, Any], index_path: Path, item_id: str) -> str:
    inline_body = item.get("body")
    if isinstance(inline_body, str) and inline_body.strip():
        return inline_body.rstrip() + "\n"

    content_file = resolve_content_file(str(item.get("content_path") or ""), index_path)
    if content_file is not None:
        if content_file.suffix.lower() == ".json":
            content_data = read_json(content_file) or {}
            body = content_data.get("body") if isinstance(content_data, dict) else ""
            if isinstance(body, str) and body.strip():
                return body.rstrip() + "\n"
        elif content_file.suffix.lower() in (".md", ".txt"):
            body = content_file.read_text(encoding="utf-8")
            if body.strip():
                return body.rstrip() + "\n"

    # 没有正文时，至少让工作台能读到标题、摘要和原文入口。
    title = normalize_space(item.get("title")) or item_id
    summary = normalize_space(item.get("summary"))
    url = normalize_space(item.get("source_url"))
    parts = [f"# {title}"]
    if summary:
        parts.extend(["", summary])
    if url:
        parts.extend(["", f"原文：{url}"])
    return "\n".join(parts).rstrip() + "\n"


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def map_kind(value: Any) -> tuple[str, list[str]]:
    raw = normalize_space(value)
    mapped = KIND_MAP.get(raw)
    if mapped in KIND_ALLOWED:
        return mapped, []
    return "原文", [f"未映射的 type={raw or '(空)'}，按原文处理"]


def map_level(value: Any) -> str:
    raw = normalize_space(value)
    return LEVEL_MAP.get(raw, raw)


def map_status(value: Any) -> str:
    raw = normalize_space(value)
    mapped = STATUS_MAP.get(raw)
    if mapped in STATUS_ALLOWED:
        return mapped
    return "待研判"


def to_workbench_item(
    item: dict[str, Any],
    item_id: str,
) -> dict[str, Any]:
    themes = item.get("themes") or []
    if isinstance(themes, str):
        themes = [themes]
    kind, warnings = map_kind(item.get("type"))
    result = {
        "id": item_id,
        "title": normalize_space(item.get("title")),
        "level": map_level(item.get("level")),
        "kind": kind,
        "issuer": normalize_space(item.get("issuer")),
        "doc_number": normalize_space(item.get("doc_number")),
        "published_at": parse_date(item.get("publish_date")),
        "deadline": parse_date(item.get("deadline")),
        "status": map_status(item.get("status")),
        "priority": as_int(item.get("priority")),
        "themes": [normalize_space(theme) for theme in themes if normalize_space(theme)],
        "summary": normalize_space(item.get("summary")),
        "source_url": normalize_space(item.get("source_url")),
        "content_path": f"items/{item_id}/content.md",
    }
    if warnings:
        result["warnings"] = warnings
    return result


def export_items(
    index: dict[str, Any],
    index_path: Path,
    out_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    workbench_items: list[dict[str, Any]] = []
    id_by_doc_id: dict[str, str] = {}
    used: set[str] = set()

    for position, item in enumerate(index.get("items") or [], 1):
        if not isinstance(item, dict):
            continue
        doc_id = normalize_space(item.get("doc_id")) or f"ex-{position:03d}"
        item_id = safe_id(doc_id, used)
        id_by_doc_id[doc_id] = item_id

        content = item_content(item, index_path, item_id)
        write_text(out_dir / "items" / item_id / "content.md", content)
        workbench_items.append(to_workbench_item(item, item_id))

    return workbench_items, id_by_doc_id


# ---------------------------------------------------------------------------
# annotations
# ---------------------------------------------------------------------------

def load_overrides(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = read_json(path)
    if not isinstance(data, dict):
        raise ExportError(f"overrides.json 格式不对：{rel_path(path)}")
    nested = data.get("items")
    if isinstance(nested, dict):
        return nested
    return data


def export_annotations(
    overrides: dict[str, Any],
    id_by_doc_id: dict[str, str],
    generated_at: str,
    out_dir: Path,
) -> int:
    known_ids = set(id_by_doc_id.values())
    annotations: dict[str, Any] = {}
    skipped: list[str] = []

    for key, value in overrides.items():
        if not isinstance(value, dict):
            skipped.append(str(key))
            continue
        if isinstance(value.get("annotation"), dict):
            value = {**value, **value["annotation"]}

        doc_id = str(key)
        item_id = id_by_doc_id.get(doc_id)
        if item_id is None and doc_id in known_ids:
            item_id = doc_id
        if item_id is None:
            skipped.append(doc_id)
            continue

        raw_status = normalize_space(value.get("status"))
        annotations[item_id] = {
            "summary": normalize_space(value.get("summary") or value.get("note")),
            "judgment": normalize_space(value.get("judgment") or value.get("decision")),
            "status": map_status(raw_status) if raw_status else "",
            "updated_at": normalize_space(
                value.get("updated_at")
                or value.get("checked_at")
                or value.get("date")
                or generated_at
            ),
        }

    write_json(out_dir / "annotations.json", {
        "schema": "workbench-annotations/v1",
        "items": annotations,
    })
    if skipped:
        print(f"  ! 跳过 {len(skipped)} 条无法匹配的 overrides：{', '.join(skipped[:5])}")
    return len(annotations)


# ---------------------------------------------------------------------------
# reports
# ---------------------------------------------------------------------------

def clean_inline_markdown(value: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", value)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"^\s*(?:[-+*]|\d+\.)\s+", "", text)
    return normalize_space(text)


def report_title(content: str, type_label: str, period: str) -> str:
    for line in content.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return clean_inline_markdown(match.group(1))
    return f"政策监测{type_label} · {period}"


def report_summary(content: str, title: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("#", ">", "|", "```", "---")):
            continue
        if stripped.startswith("*本报告") or stripped.startswith("*月报看") or stripped.startswith("*建议流程"):
            continue
        text = clean_inline_markdown(stripped)
        if len(text) >= 8:
            return truncate(text, 240)
    return title


def collect_reports(index_path: Path, generated_at: str, out_dir: Path) -> int:
    reports: list[dict[str, Any]] = []
    used: set[str] = set()

    for folder, type_label, prefix in REPORT_GROUPS:
        directory = index_path.parent / folder
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.md")):
            content = path.read_text(encoding="utf-8")
            period = path.stem
            title = report_title(content, type_label, period)
            report_id = safe_id(f"report-{prefix}-{period}", used)
            reports.append({
                "id": report_id,
                "title": title,
                "type": type_label,
                "period": period,
                "date": generated_at,
                "summary": report_summary(content, title),
                "content": content.rstrip() + "\n",
            })

    reports.sort(key=lambda report: (REPORT_ORDER.get(report["type"], 99), report["period"]))
    write_json(out_dir / "reports.json", {
        "schema": "workbench-reports/v1",
        "reports": reports,
    })
    return len(reports)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------

def clear_generated(out_dir: Path) -> None:
    for name in ("index.json", "annotations.json", "reports.json"):
        path = out_dir / name
        if path.exists():
            path.unlink()
    items_dir = out_dir / "items"
    if items_dir.exists():
        shutil.rmtree(items_dir)


def run(index_path: Path, out_dir: Path, fresh: bool = False) -> dict[str, Any]:
    index = load_index(index_path)
    generated_at = generated_date(index)

    if out_dir.exists() and not out_dir.is_dir():
        raise ExportError(f"输出路径不是目录：{rel_path(out_dir)}")
    if fresh:
        clear_generated(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    workbench_items, id_by_doc_id = export_items(index, index_path, out_dir)
    write_json(out_dir / "index.json", {
        "schema": "workbench-index/v1",
        "generated_at": generated_at,
        "items": workbench_items,
    })

    overrides = load_overrides(index_path.parent / "overrides.json")
    annotation_count = export_annotations(
        overrides, id_by_doc_id, generated_at, out_dir,
    )

    report_count = collect_reports(index_path, generated_at, out_dir)
    return {
        "generated_at": generated_at,
        "items": len(workbench_items),
        "annotations": annotation_count,
        "reports": report_count,
        "out_dir": out_dir,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="把 index.json 和报告导出为 agent-workbench-template 数据包。",
    )
    parser.add_argument(
        "--index", type=Path, default=DEFAULT_INDEX,
        help="workflow 的 index.json；默认 examples/outputs/index.json",
    )
    parser.add_argument(
        "--out", type=Path, default=None,
        help="输出目录；默认 index.json 同级的 workbench/",
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="先清空上一次生成的 index/annotations/reports/items",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    index_path = args.index
    out_dir = args.out or (index_path.parent / "workbench")

    print(f"[export] {rel_path(index_path)} -> {rel_path(out_dir)}")
    try:
        result = run(index_path, out_dir, fresh=args.fresh)
    except (ExportError, ValueError, OSError) as exc:
        print(f"\n[export] 失败：{exc}", file=sys.stderr)
        return 2

    print(
        f"\n[export] 完成：{result['items']} 条条目 / "
        f"{result['reports']} 份报告 / {result['annotations']} 条标注"
    )
    print(f"  index       {rel_path(result['out_dir'] / 'index.json')}")
    print(f"  annotations {rel_path(result['out_dir'] / 'annotations.json')}")
    print(f"  reports     {rel_path(result['out_dir'] / 'reports.json')}")
    print(f"  content     {rel_path(result['out_dir'] / 'items')}/<id>/content.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
