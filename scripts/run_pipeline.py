# -*- coding: utf-8 -*-
"""一键流水线：采集 → 解析 → 索引 → 报告。

用法：
    python scripts/run_pipeline.py --demo
    python scripts/run_pipeline.py --config sources/sources.local.yaml
    python scripts/run_pipeline.py --config sources/sources.local.yaml --no-fetch

demo 只用 Python 标准库，读 examples/sources 下的假 HTML，不联网。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from common import DEMO_AS_OF, DEMO_DATE, ROOT, as_of_iso, parse_date, rel_path, write_text
import fetch
import index as index_mod
import parse as parse_mod
import report as report_mod

DEMO_SOURCES = ROOT / "examples" / "sources" / "demo_sources.json"
DEFAULT_CONFIG = ROOT / "sources" / "sources.local.yaml"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="一键运行政策监测流水线；--demo 完全离线。",
    )
    parser.add_argument("--demo", action="store_true", help="离线 demo：读 examples/sources 的假 HTML")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="live 信源配置（YAML）")
    parser.add_argument("--date", default=None, help="报告日期/周/月；demo 默认 2026-11-12")
    parser.add_argument("--as-of", default=None, help="生成时点；默认 demo 固定，live 用当前时间")
    parser.add_argument("--kind", choices=["daily", "weekly", "monthly", "all"], default="all")
    parser.add_argument("--source", action="append", default=None, help="只跑匹配 id/名称的信源，可重复")
    parser.add_argument("--limit", type=int, default=None, help="每个信源最多抓多少条")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP 超时秒数")
    parser.add_argument("--no-fetch", action="store_true", help="跳过采集，直接用已有 raw.json")
    parser.add_argument("--keep-existing", action="store_true", help="解析时跳过已有同 URL 条目，保留人工修改")
    parser.add_argument("--fresh", action="store_true", help="索引时忽略上一版，全部按新增处理")
    return parser


def run_demo(args: argparse.Namespace) -> int:
    as_of = as_of_iso(args.as_of or (args.date + "T18:00:00" if args.date else DEMO_AS_OF))
    anchor = parse_date(args.date or DEMO_DATE)
    raw_dir = ROOT / "data" / "demo" / "raw"
    items_dir = ROOT / "examples" / "items"
    out_dir = ROOT / "examples" / "outputs"

    print("=" * 68)
    print("政策监测 workflow · 离线 demo")
    print(f"观察时点：{as_of} ｜ 报告日期：{anchor}")
    print("=" * 68)

    if not args.no_fetch:
        print("\n[1/4] 采集：读取离线 HTML 快照")
        records, health, errors = fetch.fetch_demo(
            DEMO_SOURCES, raw_dir, as_of, only=args.source,
        )
        if not records:
            print("[run] 没有采集到记录，停止。", file=sys.stderr)
            return 2
    else:
        print("\n[1/4] 采集：跳过（--no-fetch）")

    print("\n[2/4] 解析：抽取标题/正文/日期/文号/截止日期")
    written = parse_mod.run(
        raw_dir / "raw.json", items_dir, DEMO_SOURCES, as_of,
        skip_existing=args.keep_existing, limit=args.limit,
    )
    if not written:
        print("  ! 没有新条目；继续用已有条目生成索引和报告。")

    print("\n[3/4] 索引：生成 index.json 与 changes.csv")
    # demo 每次都从零开始，保证示例输出稳定、可复现。
    result = index_mod.build_index(
        items_dir, out_dir, as_of, "demo", fresh=True,
    )
    stats = result["stats"]
    print(
        f"  {stats['items']} 条：新增 {stats['added']} / 更新 {stats['updated']} / "
        f"未变 {stats['unchanged']}"
    )

    print("\n[4/4] 报告：按模板生成草稿")
    written_reports = []
    if args.kind in ("daily", "all"):
        text, date = report_mod.render_daily(result, anchor)
        path = out_dir / "daily" / f"{date}.md"
        write_text(path, text)
        written_reports.append(path)
    if args.kind in ("weekly", "all"):
        text, label = report_mod.render_weekly(result, anchor)
        path = out_dir / "weekly" / f"{label}.md"
        write_text(path, text)
        written_reports.append(path)
    if args.kind in ("monthly", "all"):
        month = anchor[:7]
        text, label = report_mod.render_monthly(result, month + "-01")
        path = out_dir / "monthly" / f"{month}.md"
        write_text(path, text)
        written_reports.append(path)

    print("\n完成：")
    print(f"  raw      {rel_path(raw_dir / 'raw.json')}")
    print(f"  items    {rel_path(items_dir)}（{len(written)} 条）")
    print(f"  index    {rel_path(out_dir / 'index.json')}")
    print(f"  changes  {rel_path(out_dir / 'changes.csv')}")
    for path in written_reports:
        print(f"  report   {rel_path(path)}")
    print("\n提示：示例日期固定在 2026 年 11 月；用 --date YYYY-MM-DD 可生成其他日期。")
    return 0


def run_live(args: argparse.Namespace) -> int:
    as_of = as_of_iso(args.as_of or (args.date + "T18:00:00" if args.date else None))
    anchor = parse_date(args.date or as_of[:10])
    raw_dir = ROOT / "data" / "raw"
    items_dir = ROOT / "data" / "items"
    out_dir = ROOT / "outputs"

    print("=" * 68)
    print("政策监测 workflow · live")
    print(f"生成时点：{as_of} ｜ 报告日期：{anchor}")
    print("=" * 68)

    if not args.no_fetch:
        print("\n[1/4] 采集")
        records, health, errors = fetch.fetch_live(
            args.config, raw_dir, as_of, only=args.source,
            limit=args.limit, timeout=args.timeout,
        )
        if not records:
            print("[run] 没有采集到记录；检查 health.csv 与信源配置。", file=sys.stderr)
            return 2
    else:
        print("\n[1/4] 采集：跳过（--no-fetch）")

    print("\n[2/4] 解析")
    written = parse_mod.run(
        raw_dir / "raw.json", items_dir, args.config, as_of,
        skip_existing=args.keep_existing, limit=args.limit,
    )
    if not written:
        print("  ! 没有新条目；继续用已有条目生成索引和报告。")

    print("\n[3/4] 索引")
    result = index_mod.build_index(
        items_dir, out_dir, as_of, "live", fresh=args.fresh,
    )
    stats = result["stats"]
    print(
        f"  {stats['items']} 条：新增 {stats['added']} / 更新 {stats['updated']} / "
        f"移除 {stats['removed']} / 未变 {stats['unchanged']}"
    )

    print("\n[4/4] 报告")
    written_reports = []
    if args.kind in ("daily", "all"):
        text, date = report_mod.render_daily(result, anchor)
        path = out_dir / "daily" / f"{date}.md"
        write_text(path, text)
        written_reports.append(path)
    if args.kind in ("weekly", "all"):
        text, label = report_mod.render_weekly(result, anchor)
        path = out_dir / "weekly" / f"{label}.md"
        write_text(path, text)
        written_reports.append(path)
    if args.kind in ("monthly", "all"):
        month = anchor[:7]
        text, label = report_mod.render_monthly(result, month + "-01")
        path = out_dir / "monthly" / f"{month}.md"
        write_text(path, text)
        written_reports.append(path)

    print("\n完成：")
    print(f"  raw      {rel_path(raw_dir / 'raw.json')}")
    print(f"  health   {rel_path(raw_dir / 'health.csv')}")
    print(f"  items    {rel_path(items_dir)}（{len(written)} 条）")
    print(f"  index    {rel_path(out_dir / 'index.json')}")
    print(f"  changes  {rel_path(out_dir / 'changes.csv')}")
    for path in written_reports:
        print(f"  report   {rel_path(path)}")
    print("\n下一步：人工核校报告；核校后的条目状态写回条目 JSON 或工作台覆盖层。")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.demo:
            return run_demo(args)
        return run_live(args)
    except (fetch.FetchError, parse_mod.ParseError, index_mod.IndexBuildError,
            report_mod.ReportError, RuntimeError, ValueError) as exc:
        print(f"\n[run] 失败：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
