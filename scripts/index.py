# -*- coding: utf-8 -*-
"""索引阶段：把条目 JSON 汇总成 index.json 与 changes.csv。

用法：
    python scripts/index.py --demo --fresh
    python scripts/index.py --items data/items --out outputs

index.json 是给人和工作台读的稳定读模型；changes.csv 只记录新增/更新/移除。
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path
from typing import Any

from common import (
    DEMO_AS_OF,
    ROOT,
    as_of_iso,
    read_json,
    rel_path,
    sha1_text,
    write_json,
)

DEMO_ITEMS = ROOT / "examples" / "items"
DEMO_OUT = ROOT / "examples" / "outputs"
LIVE_ITEMS = ROOT / "data" / "items"
LIVE_OUT = ROOT / "outputs"

CHANGE_FIELDS = [
    "title", "issuer", "doc_number", "level", "type", "publish_date",
    "deadline", "status", "summary", "priority", "content_hash",
]


class IndexBuildError(RuntimeError):
    pass


def load_items(items_dir: Path) -> list[tuple[dict[str, Any], Path]]:
    if not items_dir.exists():
        raise IndexBuildError(f"条目目录不存在：{rel_path(items_dir)}")
    rows: list[tuple[dict[str, Any], Path]] = []
    for path in sorted(items_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        data = read_json(path)
        if not isinstance(data, dict):
            continue
        if not data.get("doc_id") or not data.get("title"):
            print(f"  ! 跳过字段不完整的条目：{rel_path(path)}")
            continue
        rows.append((data, path))
    return rows


def summarize(item: dict[str, Any], path: Path, change: str = "unchanged") -> dict[str, Any]:
    extraction = item.get("extraction") or {}
    review = item.get("review") or {}
    source = item.get("source") or {}
    return {
        "doc_id": item.get("doc_id", ""),
        "title": item.get("title", ""),
        "issuer": item.get("issuer", ""),
        "doc_number": item.get("doc_number", ""),
        "level": item.get("level", ""),
        "type": item.get("type", ""),
        "subtype": item.get("subtype", ""),
        "themes": item.get("themes", []),
        "publish_date": item.get("publish_date", ""),
        "effective_date": item.get("effective_date", ""),
        "deadline": item.get("deadline", ""),
        "status": item.get("status", ""),
        "priority": item.get("priority", 0),
        "priority_reason": item.get("priority_reason", ""),
        "signal": item.get("signal", ""),
        "summary": item.get("summary", ""),
        "source_name": source.get("name", "") or item.get("issuer", ""),
        "source_tier": source.get("tier", ""),
        "source_url": item.get("source_url", ""),
        "first_seen": item.get("first_seen", ""),
        "last_updated": item.get("last_updated", ""),
        "content_hash": item.get("content_hash", ""),
        "content_path": rel_path(path),
        "body_chars": extraction.get("body_chars", 0),
        "confidence": extraction.get("confidence", ""),
        "review": {
            "required": bool(review.get("required", True)),
            "reasons": review.get("reasons", []),
            "checked_by": review.get("checked_by", ""),
            "checked_at": review.get("checked_at", ""),
            "decision": review.get("decision", ""),
            "notes": review.get("notes", ""),
        },
        "change": change,
    }


def diff_fields(previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
    labels = {
        "title": "标题",
        "issuer": "机构",
        "doc_number": "文号",
        "level": "层级",
        "type": "类型",
        "publish_date": "发布日期",
        "deadline": "截止日期",
        "status": "状态",
        "summary": "摘要",
        "priority": "优先级",
        "content_hash": "正文",
    }
    changed = []
    for field in CHANGE_FIELDS:
        if previous.get(field, "") != current.get(field, ""):
            changed.append(labels.get(field, field))
    return changed


def aggregate(items: list[dict[str, Any]]) -> dict[str, Any]:
    by_level: dict[str, int] = {}
    by_type: dict[str, int] = {}
    by_theme: dict[str, int] = {}
    by_source: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    sources: dict[str, dict[str, Any]] = {}
    dates = []
    undated = 0
    review_required = 0

    for item in items:
        level = item.get("level") or "未标注"
        policy_type = item.get("type") or "未标注"
        by_level[level] = by_level.get(level, 0) + 1
        by_type[policy_type] = by_type.get(policy_type, 0) + 1

        for theme in item.get("themes") or ["未标注"]:
            by_theme[theme] = by_theme.get(theme, 0) + 1

        source_name = item.get("source_name") or "未标注"
        by_source[source_name] = by_source.get(source_name, 0) + 1
        confidence = item.get("confidence") or "未标注"
        by_confidence[confidence] = by_confidence.get(confidence, 0) + 1

        source = sources.setdefault(source_name, {
            "name": source_name,
            "tier": item.get("source_tier", ""),
            "level": level,
            "items": 0,
            "latest_publish": "",
        })
        source["items"] += 1
        if item.get("publish_date") and item["publish_date"] > source["latest_publish"]:
            source["latest_publish"] = item["publish_date"]

        if item.get("publish_date"):
            dates.append(item["publish_date"])
        else:
            undated += 1
        if (item.get("review") or {}).get("required"):
            review_required += 1

    def sort_dict(data: dict[str, int]) -> dict[str, int]:
        return dict(sorted(data.items(), key=lambda pair: (-pair[1], pair[0])))

    return {
        "by_level": sort_dict(by_level),
        "by_type": sort_dict(by_type),
        "by_theme": sort_dict(by_theme),
        "by_source": sort_dict(by_source),
        "by_confidence": sort_dict(by_confidence),
        "earliest_publish": min(dates) if dates else "",
        "latest_publish": max(dates) if dates else "",
        "undated": undated,
        "review_required": review_required,
        "sources": sorted(
            sources.values(),
            key=lambda row: (-row["items"], row["name"]),
        ),
    }


def build_index(
    items_dir: Path,
    out_dir: Path,
    generated_at: str,
    mode: str,
    fresh: bool = False,
    no_removals: bool = False,
) -> dict[str, Any]:
    rows = load_items(items_dir)
    if not rows:
        raise IndexBuildError(f"没有可用条目：{rel_path(items_dir)}。先运行 parse。")

    previous_path = out_dir / "index.json"
    previous = None if fresh else read_json(previous_path)
    previous_items: dict[str, dict[str, Any]] = {}
    if isinstance(previous, dict):
        for item in previous.get("items") or []:
            if item.get("doc_id"):
                previous_items[item["doc_id"]] = item

    current_ids = set()
    indexed: list[dict[str, Any]] = []
    changes: list[dict[str, Any]] = []

    for item, path in rows:
        doc_id = item["doc_id"]
        current_ids.add(doc_id)
        old = previous_items.get(doc_id)
        if old is None:
            change = "added"
            changed = []
        else:
            changed = diff_fields(old, item)
            change = "updated" if changed else "unchanged"

        summary = summarize(item, path, change)
        indexed.append(summary)
        if change in ("added", "updated"):
            changes.append({
                "change_id": "chg-" + sha1_text(
                    f"{doc_id}|{change}|{summary['content_hash']}|{generated_at}"
                )[:10],
                "change_type": change,
                "doc_id": doc_id,
                "title": summary["title"],
                "issuer": summary["issuer"],
                "level": summary["level"],
                "publish_date": summary["publish_date"],
                "changed_fields": ";".join(changed),
                "detected_at": generated_at,
                "source_url": summary["source_url"],
            })

    removed = []
    if isinstance(previous, dict) and not no_removals:
        for doc_id, old in previous_items.items():
            if doc_id in current_ids:
                continue
            removed.append(old)
            changes.append({
                "change_id": "chg-" + sha1_text(
                    f"{doc_id}|removed|{old.get('content_hash', '')}|{generated_at}"
                )[:10],
                "change_type": "removed",
                "doc_id": doc_id,
                "title": old.get("title", ""),
                "issuer": old.get("issuer", ""),
                "level": old.get("level", ""),
                "publish_date": old.get("publish_date", ""),
                "changed_fields": "",
                "detected_at": generated_at,
                "source_url": old.get("source_url", ""),
            })

    indexed.sort(key=lambda item: (
        item.get("publish_date") or "0000-00-00",
        int(item.get("priority") or 0),
        item.get("doc_id") or "",
    ), reverse=True)
    changes.sort(key=lambda row: (row["detected_at"], row["change_id"]), reverse=True)

    aggregates = aggregate(indexed)
    stats = {
        "items": len(indexed),
        "added": sum(1 for item in indexed if item["change"] == "added"),
        "updated": sum(1 for item in indexed if item["change"] == "updated"),
        "removed": len(removed),
        "unchanged": sum(1 for item in indexed if item["change"] == "unchanged"),
        **aggregates,
    }

    result = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "mode": mode,
        "indexed_from": rel_path(items_dir),
        "stats": stats,
        "items": indexed,
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    write_json(out_dir / "index.json", result)
    write_changes(out_dir / "changes.csv", changes)
    return result


def write_changes(path: Path, changes: list[dict[str, Any]]) -> None:
    fields = [
        "change_id", "change_type", "doc_id", "title", "issuer", "level",
        "publish_date", "changed_fields", "detected_at", "source_url",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in changes:
            writer.writerow({key: row.get(key, "") for key in fields})


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="汇总条目 JSON，生成 index.json 与 changes.csv。",
    )
    parser.add_argument("--demo", action="store_true", help="使用 examples 的条目与固定时点")
    parser.add_argument("--items", type=Path, default=None, help="条目目录")
    parser.add_argument("--out", type=Path, default=None, help="索引输出目录")
    parser.add_argument("--fresh", action="store_true", help="忽略已有 index.json，全部按新增处理")
    parser.add_argument("--no-removals", action="store_true", help="不把上一版索引中消失的条目标为 removed")
    parser.add_argument("--now", default=None, help="生成时点；demo 默认 2026-11-12T18:00:00+08:00")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    items_dir = args.items or (DEMO_ITEMS if args.demo else LIVE_ITEMS)
    out_dir = args.out or (DEMO_OUT if args.demo else LIVE_OUT)
    try:
        generated_at = as_of_iso(args.now or (DEMO_AS_OF if args.demo else None))
    except ValueError as exc:
        print(f"[index] 参数错误：{exc}", file=sys.stderr)
        return 2
    mode = "demo" if args.demo else "live"

    print(f"[index] {mode} · {rel_path(items_dir)} -> {rel_path(out_dir)}")
    try:
        result = build_index(
            items_dir, out_dir, generated_at, mode,
            fresh=args.fresh, no_removals=args.no_removals,
        )
    except (IndexBuildError, RuntimeError) as exc:
        print(f"\n[index] 失败：{exc}", file=sys.stderr)
        return 2

    stats = result["stats"]
    print(
        f"\n[index] {stats['items']} 条：新增 {stats['added']} / "
        f"更新 {stats['updated']} / 移除 {stats['removed']} / 未变 {stats['unchanged']}"
    )
    print(f"  index：{rel_path(out_dir / 'index.json')}")
    print(f"  changes：{rel_path(out_dir / 'changes.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
