# -*- coding: utf-8 -*-
"""共享工具：日期、JSON、HTML 解析与精简 CSS 选择器。

整个模块只依赖 Python 标准库，保证 `--demo` 在没有任何第三方包时也能运行。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import html
import json
import re
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "1.0"

# demo 的固定观察时点：让示例输出可复现，不随运行日期漂移。
DEMO_AS_OF = "2026-11-12T18:00:00+08:00"
DEMO_DATE = "2026-11-12"

ROOT = Path(__file__).resolve().parent.parent

# HTML 中不需要成对闭合的标签。
VOID_TAGS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
}

# 提取纯文本时视为“块”的标签，用于在段落之间插入换行。
BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl",
    "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2",
    "h3", "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p",
    "pre", "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr",
    "ul",
}

# 默认跳过这些标签里的文本：脚本、样式、模板和嵌入式图形。
SKIP_TEXT_TAGS = {"script", "style", "noscript", "template", "svg"}


# ---------------------------------------------------------------------------
# 路径与读写
# ---------------------------------------------------------------------------

def rel_path(path: Path) -> str:
    """返回相对仓库根目录的 POSIX 路径；不在仓库内时只返回文件名。

    这样生成的 JSON / Markdown 不会泄漏作者机器上的绝对路径。
    """
    path = Path(path)
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.name


def read_json(path: Path, default: Any = None) -> Any:
    path = Path(path)
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8-sig") as fh:
        return json.load(fh)


def write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def load_structured(path: Path) -> Any:
    """读取 JSON 或 YAML（YAML 仅在 live 模式需要）。"""
    path = Path(path)
    if path.suffix.lower() == ".json":
        return read_json(path)
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "读取 YAML 需要 PyYAML。请先安装：python -m pip install -r requirements.txt"
        ) from exc
    with path.open("r", encoding="utf-8-sig") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# 文本与日期
# ---------------------------------------------------------------------------

def normalize_space(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    text = text.replace("\u00a0", " ").replace("\u3000", " ")
    return re.sub(r"\s+", " ", text).strip()


def normalize_lines(value: Any) -> str:
    if value is None:
        return ""
    lines = []
    for line in str(value).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = normalize_space(line)
        if line:
            lines.append(line)
    return "\n".join(lines)


def truncate(text: str, limit: int = 180, suffix: str = "…") -> str:
    text = normalize_space(text)
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip("，,。.;；、 ") + suffix


def sha1_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_date(value: Any) -> str:
    """把常见日期写法转成 YYYY-MM-DD；无法识别时返回空字符串。"""
    if value is None or value == "":
        return ""

    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()

    if isinstance(value, (int, float)):
        stamp = float(value)
        if stamp > 1e12:  # 毫秒时间戳
            stamp /= 1000.0
        try:
            return dt.datetime.fromtimestamp(stamp).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return ""

    text = normalize_space(value)
    if not text:
        return ""

    # 纯 8 位或 10/13 位数字：先判断是不是紧凑日期，再判断时间戳。
    if re.fullmatch(r"\d{8}", text):
        try:
            return dt.date(int(text[:4]), int(text[4:6]), int(text[6:8])).isoformat()
        except ValueError:
            return ""
    if re.fullmatch(r"\d{10}|\d{13}", text):
        return parse_date(int(text))

    # RFC 2822（RSS 常见）
    if "," in text and re.search(r"[A-Za-z]{3}", text):
        try:
            return parsedate_to_datetime(text).date().isoformat()
        except (TypeError, ValueError, IndexError):
            pass

    match = re.search(
        r"(19\d{2}|20\d{2})\s*[-/.年]\s*(\d{1,2})\s*[-/.月]\s*(\d{1,2})\s*日?",
        text,
    )
    if not match:
        match = re.search(r"(19\d{2}|20\d{2})(\d{2})(\d{2})", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        try:
            result = dt.date(year, month, day)
        except ValueError:
            return ""
        if 1990 <= result.year <= 2100:
            return result.isoformat()
    return ""


def parse_as_of(value: str | None) -> dt.datetime:
    """解析命令行里的时点；无时区时按本机时区理解。"""
    if not value:
        return dt.datetime.now().astimezone()
    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        text = text + "T18:00:00"
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"无法解析时间：{value}（建议 YYYY-MM-DD 或 ISO 8601）") from exc
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed


def as_of_iso(value: dt.datetime | str | None) -> str:
    if isinstance(value, dt.datetime):
        return value.isoformat(timespec="seconds")
    if value:
        return parse_as_of(value).isoformat(timespec="seconds")
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def date_only(value: Any, fallback: str = "") -> str:
    return parse_date(value) or fallback


def week_range(date_text: str) -> tuple[str, str, str]:
    """返回 (ISO 周标签, 周一, 周日)。"""
    day = dt.date.fromisoformat(parse_date(date_text) or DEMO_DATE)
    monday = day - dt.timedelta(days=day.weekday())
    sunday = monday + dt.timedelta(days=6)
    iso = day.isocalendar()
    label = f"{iso.year}-W{iso.week:02d}"
    return label, monday.isoformat(), sunday.isoformat()


def month_of(date_text: str) -> str:
    day = parse_date(date_text) or DEMO_DATE
    return day[:7]


def month_range(month_text: str) -> tuple[str, str]:
    year, month = (int(part) for part in month_text.split("-")[:2])
    first = dt.date(year, month, 1)
    if month == 12:
        next_first = dt.date(year + 1, 1, 1)
    else:
        next_first = dt.date(year, month + 1, 1)
    last = next_first - dt.timedelta(days=1)
    return first.isoformat(), last.isoformat()


def previous_month(month_text: str) -> str:
    year, month = (int(part) for part in month_text.split("-")[:2])
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def days_between(start: str, end: str) -> int:
    a = dt.date.fromisoformat(parse_date(start))
    b = dt.date.fromisoformat(parse_date(end))
    return (b - a).days


def deep_get(data: Any, path: str, default: Any = None) -> Any:
    """按点号路径取嵌套字段，例如 data.list。"""
    if not path:
        return data if data is not None else default
    current = data
    for key in str(path).split("."):
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list) and key.isdigit():
            index = int(key)
            current = current[index] if 0 <= index < len(current) else None
        else:
            return default
        if current is None:
            return default
    return current


def first_sentences(text: str, limit: int = 180, max_sentences: int = 2) -> str:
    """抽取式摘要：取开头若干句，不做改写。"""
    text = normalize_lines(text)
    if not text:
        return ""
    sentences = re.split(r"(?<=[。！？!?；;])\s*", text.replace("\n", ""))
    picked = []
    used = 0
    for sentence in sentences:
        sentence = normalize_space(sentence)
        if not sentence:
            continue
        if used + len(sentence) > limit and picked:
            break
        picked.append(sentence)
        used += len(sentence)
        if len(picked) >= max_sentences:
            break
    result = "".join(picked)
    return truncate(result, limit) if result else truncate(text, limit)


# ---------------------------------------------------------------------------
# 迷你 DOM 与 CSS 选择器
# ---------------------------------------------------------------------------

class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, Any] | None = None, parent: "Node | None" = None):
        self.tag = tag.lower()
        self.attrs = {
            str(key).lower(): ("" if value is None else str(value))
            for key, value in (attrs or {}).items()
        }
        self.children: list[Node | str] = []
        self.parent = parent

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def get(self, name: str, default: str = "") -> str:
        return self.attrs.get(name.lower(), default)

    def append(self, child: "Node | str") -> None:
        if isinstance(child, Node):
            child.parent = self
        self.children.append(child)

    def text(self, sep: str = "\n", skip: Iterable[str] | None = None) -> str:
        """提取纯文本。块级元素之间用 sep 分隔。"""
        skip_set = set(SKIP_TEXT_TAGS if skip is None else skip)
        parts: list[str] = []

        def walk(node: Node | str) -> None:
            if isinstance(node, str):
                parts.append(node)
                return
            if node.tag in skip_set:
                return
            is_block = node.tag in BLOCK_TAGS
            if is_block and parts:
                parts.append(sep)
            for child in node.children:
                walk(child)
            if is_block:
                parts.append(sep)

        walk(self)
        raw = "".join(parts)
        if sep == "\n":
            return normalize_lines(raw)
        return normalize_space(raw)

    def inner_text(self) -> str:
        return self.text(sep=" ")

    def inner_html(self) -> str:
        out: list[str] = []

        def serialize(node: Node | str) -> None:
            if isinstance(node, str):
                out.append(html.escape(node, quote=False))
                return
            attrs = "".join(
                f' {key}="{html.escape(value, quote=True)}"'
                for key, value in node.attrs.items()
            )
            out.append(f"<{node.tag}{attrs}>")
            if node.tag not in VOID_TAGS:
                for child in node.children:
                    serialize(child)
                out.append(f"</{node.tag}>")

        for child in self.children:
            serialize(child)
        return "".join(out)

    def select(self, selector: str) -> list["Node"]:
        groups = _parse_selector(selector)
        found: list[Node] = []
        seen: set[int] = set()

        def walk(node: Node) -> None:
            for child in node.children:
                if not isinstance(child, Node):
                    continue
                if any(_matches_chain(child, group) for group in groups):
                    marker = id(child)
                    if marker not in seen:
                        seen.add(marker)
                        found.append(child)
                walk(child)

        walk(self)
        return found

    def select_one(self, selector: str) -> "Node | None":
        matches = self.select(selector)
        return matches[0] if matches else None


class _TreeBuilder(HTMLParser):
    # HTML 允许省略结束标签的常见元素。
    OPTIONAL_CLOSE = {"li", "p", "tr", "td", "th", "option", "dt", "dd"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.stack: list[Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in self.OPTIONAL_CLOSE and self.stack[-1].tag == tag:
            self.stack.pop()
        node = Node(tag, dict(attrs), self.stack[-1])
        self.stack[-1].append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        node = Node(tag, dict(attrs), self.stack[-1])
        self.stack[-1].append(node)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].append(data)


def parse_html(text: str) -> Node:
    builder = _TreeBuilder()
    builder.feed(text or "")
    builder.close()
    return builder.root


class _SimpleSelector:
    __slots__ = ("tag", "classes", "element_id", "attrs")

    def __init__(
        self,
        tag: str | None = None,
        classes: list[str] | None = None,
        element_id: str | None = None,
        attrs: list[tuple[str, str, str]] | None = None,
    ):
        self.tag = tag
        self.classes = classes or []
        self.element_id = element_id
        self.attrs = attrs or []


def _parse_simple(text: str) -> _SimpleSelector:
    text = text.strip()
    if not text:
        raise ValueError("空的选择器片段")

    tag: str | None = None
    match = re.match(r"^([a-zA-Z][\w-]*|\*)", text)
    if match:
        tag = match.group(1).lower()
        if tag == "*":
            tag = None
        text = text[match.end():]

    classes: list[str] = []
    element_id: str | None = None
    attrs: list[tuple[str, str, str]] = []

    while text:
        if text[0] == ".":
            match = re.match(r"\.([\w-]+)", text)
            if not match:
                raise ValueError(f"无效的类选择器：{text}")
            classes.append(match.group(1))
            text = text[match.end():]
        elif text[0] == "#":
            match = re.match(r"#([\w-]+)", text)
            if not match:
                raise ValueError(f"无效的 ID 选择器：{text}")
            element_id = match.group(1)
            text = text[match.end():]
        elif text[0] == "[":
            end = text.find("]")
            if end < 0:
                raise ValueError(f"属性选择器缺少 ]：{text}")
            expression = text[1:end].strip()
            text = text[end + 1:]
            attr_match = re.match(
                r"^([\w:-]+)\s*(?:(\*=|\^=|\$=|~=|\|=|=)\s*(.*))?$",
                expression,
            )
            if not attr_match:
                raise ValueError(f"无效的属性选择器：[{expression}]")
            name, operator, value = attr_match.groups()
            value = (value or "").strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            attrs.append((name.lower(), operator or "", value))
        else:
            raise ValueError(f"不支持的选择器片段：{text}")

    return _SimpleSelector(tag, classes, element_id, attrs)


def _parse_selector(selector: str) -> list[list[tuple[str | None, _SimpleSelector]]]:
    groups: list[list[tuple[str | None, _SimpleSelector]]] = []
    for raw_group in selector.split(","):
        raw_group = raw_group.strip()
        if not raw_group:
            continue
        normalized = re.sub(r"\s*>\s*", " > ", raw_group)
        pieces = normalized.split()
        chain: list[tuple[str | None, _SimpleSelector]] = []
        pending_combinator: str | None = None
        expect_simple = True
        for piece in pieces:
            if piece == ">":
                if expect_simple:
                    raise ValueError(f"选择器中的 > 位置不正确：{raw_group}")
                pending_combinator = ">"
                expect_simple = True
                continue
            if piece == "+":
                raise ValueError("暂不支持相邻兄弟选择器（+）")
            combinator = pending_combinator if pending_combinator else (" " if chain else None)
            chain.append((combinator, _parse_simple(piece)))
            pending_combinator = None
            expect_simple = False
        if not chain:
            raise ValueError(f"无效的选择器：{selector}")
        groups.append(chain)
    if not groups:
        raise ValueError(f"无效的选择器：{selector}")
    return groups


def _matches_simple(node: Node, simple: _SimpleSelector) -> bool:
    if node.tag == "#document":
        return False
    if simple.tag and node.tag != simple.tag:
        return False
    if simple.element_id and node.get("id") != simple.element_id:
        return False
    node_classes = node.classes
    if any(name not in node_classes for name in simple.classes):
        return False
    for name, operator, expected in simple.attrs:
        actual = node.attrs.get(name)
        if actual is None:
            return False
        if not operator:
            continue
        if operator == "=" and actual != expected:
            return False
        if operator == "*=" and expected not in actual:
            return False
        if operator == "^=" and not actual.startswith(expected):
            return False
        if operator == "$=" and not actual.endswith(expected):
            return False
        if operator == "~=" and expected not in actual.split():
            return False
        if operator == "|=" and not (actual == expected or actual.startswith(expected + "-")):
            return False
    return True


def _matches_chain(node: Node, chain: list[tuple[str | None, _SimpleSelector]]) -> bool:
    def match_at(candidate: Node | None, index: int) -> bool:
        if candidate is None or not _matches_simple(candidate, chain[index][1]):
            return False
        if index == 0:
            return True
        combinator = chain[index][0]
        if combinator == ">":
            return match_at(candidate.parent, index - 1)
        parent = candidate.parent
        while parent is not None:
            if match_at(parent, index - 1):
                return True
            parent = parent.parent
        return False

    return match_at(node, len(chain) - 1)


def meta_content(tree: Node, names: Iterable[str]) -> str:
    wanted = {name.lower() for name in names}
    for meta in tree.select("meta"):
        key = (
            meta.get("name")
            or meta.get("property")
            or meta.get("http-equiv")
            or ""
        ).lower()
        if key in wanted:
            content = normalize_space(meta.get("content"))
            if content:
                return content
    return ""


def strip_html_fragment(value: str) -> str:
    if not value:
        return ""
    return parse_html(value).text(sep=" ")


# ---------------------------------------------------------------------------
# Markdown 辅助
# ---------------------------------------------------------------------------

def md_cell(value: Any) -> str:
    text = normalize_space(value)
    return text.replace("|", "\\|")


def md_link(title: str, url: str) -> str:
    title = normalize_space(title).replace("[", "\\[").replace("]", "\\]")
    if not url:
        return title
    return f"[{title}]({url})"


def bullet_list(lines: Iterable[str], empty: str = "无。") -> str:
    lines = [line for line in lines if line]
    if not lines:
        return empty
    return "\n".join(f"- {line}" for line in lines)


def table(headers: list[str], rows: list[list[Any]], align: str | None = None) -> str:
    if not rows:
        return "无。"
    head = "| " + " | ".join(md_cell(h) for h in headers) + " |"
    sep = "|" + "|".join("---" for _ in headers) + "|"
    body = [
        "| " + " | ".join(md_cell(cell) for cell in row) + " |"
        for row in rows
    ]
    return "\n".join([head, sep, *body])
