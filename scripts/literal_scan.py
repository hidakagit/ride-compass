#!/usr/bin/env python3
"""同じリテラルが複数ファイルへ散っている箇所を洗い出す参考ツール。

コピペ検出（jscpd、`review_checks.py duplication`）が捕まえるのは完全一致のクローンだけ
で、「設定値・外部仕様の値が、それを使う場所へ直書きされている」型は原理的に検出できない。
そちらの手がかりを出すためのもの。

**誤検出を含む前提の道具であり、合否を判定しない**。`review_checks.py`のサブコマンドへは
入れていない——出力の大半はドメイン語彙（材料id等、散っていて当然のもの）やフレームワークの
定型で、機械的にノイズと本物を分けられなかった。人が`/review:complexity`の「写経の監視」で
材料として眺める用途に限る。

実際に見つかる例:
- `result`/`miss`/`cache`/`error_type` が13〜16ファイル … `log_external_call`へ渡す
  `fields`の定型。同じ処理順序が各モジュールへ書き写されているサイン。
- 一方で`maxzoom: 11`のような**単独の数値リテラルは拾えない**。閾値を下げるとノイズが
  支配的になるため。

対象は文字列リテラルとパス断片、および`キー: 数値`の形。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

INCLUDE_PREFIXES = ("backend/app/", "frontend/src/")
EXCLUDE_RE = re.compile(r"(\.test\.|\.spec\.|\.bench\.|/types/generated/|/__pycache__/|\.d\.ts$)")

# 文字列リテラル（3文字以上、URLパス断片・キー名を想定）。
STRING_LITERAL_RE = re.compile(r"""["']([A-Za-z0-9_./:{}\-]{4,80})["']""")
# `key: 数値` の形（maxzoom: 11 等、外部仕様の値が直書きされている型）。
KEYED_NUMBER_RE = re.compile(r"\b([a-z_][a-z0-9_]{3,30})\s*[:=]\s*(\d{2,})\b", re.I)

# 言語・フレームワークの定型で、散っていても問題にならないもの。
IGNORE_LITERALS = {
    "utf-8", "application/json", "http", "https", "true", "false", "none", "null",
    "text/plain", "GET", "POST", "PUT", "DELETE", "error", "warning", "info", "debug",
    "class", "type", "name", "value", "label", "color", "width", "height", "size",
}
# HTML/JSXの要素名・属性値。散っているのが当たり前で、集約する対象ではない。
IGNORE_JSX = {
    "button", "div", "span", "input", "label", "section", "header", "footer", "nav",
    "ul", "li", "table", "thead", "tbody", "tr", "td", "th", "form", "svg", "path",
    "checkbox", "radio", "text", "number", "range", "submit", "hidden", "none",
    "polyline", "circle", "rect", "line", "group", "region", "dialog", "menu",
}
IGNORE_KEYS = {"status_code", "timeout", "port", "line", "column", "index", "length", "max_length"}


def tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    ).stdout
    return [
        f for f in out.splitlines()
        if f.startswith(INCLUDE_PREFIXES) and f.endswith((".py", ".ts", ".tsx"))
        and not EXCLUDE_RE.search(f)
    ]


def strip_comment(line: str, path: str) -> str:
    """コメント部分を落とす（コメント中の例示を数えないため）。"""
    if path.endswith(".py"):
        return line.split("#", 1)[0]
    stripped = line.lstrip()
    if stripped.startswith(("//", "*", "/*")):
        return ""
    return line.split("//", 1)[0]


def scan(min_files: int) -> None:
    literal_hits: dict[str, list[str]] = defaultdict(list)
    keyed_hits: dict[str, list[str]] = defaultdict(list)

    for path in tracked_files():
        text = (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace")
        for lineno, raw in enumerate(text.splitlines(), 1):
            line = strip_comment(raw, path)
            if not line.strip():
                continue
            # import/from行のモジュール名は「散っている」ことに意味が無い。
            if re.match(r'\s*(import|from|export)', line):
                continue
            for literal in STRING_LITERAL_RE.findall(line):
                lowered = literal.lower()
                if lowered in IGNORE_LITERALS or lowered in IGNORE_JSX or literal.isdigit():
                    continue
                literal_hits[literal].append(f"{path}:{lineno}")
            for key, number in KEYED_NUMBER_RE.findall(line):
                if key.lower() in IGNORE_KEYS:
                    continue
                keyed_hits[f"{key}={number}"].append(f"{path}:{lineno}")

    def report(title: str, hits: dict[str, list[str]], note: str) -> None:
        rows = []
        for value, places in hits.items():
            files = {p.rsplit(":", 1)[0] for p in places}
            if len(files) >= min_files:
                rows.append((len(files), len(places), value, sorted(files)))
        rows.sort(key=lambda r: (-r[0], -r[1]))
        print(f"## {title}: {len(rows)}件（{min_files}ファイル以上に散っているもの）")
        print(f"   {note}")
        print()
        for file_count, hit_count, value, files in rows[:25]:
            print(f"- `{value}` … {file_count}ファイル / {hit_count}箇所")
            for f in files[:5]:
                print(f"    {f}")
            if len(files) > 5:
                print(f"    …他{len(files) - 5}ファイル")
        print()

    report(
        "同じ文字列リテラルが複数ファイルに散っている", literal_hits,
        "URL断片・キー名・要素idなど。1箇所へ集約すべきか、たまたま同じ語かを見る。",
    )
    report(
        "同じ`キー=数値`が複数ファイルに散っている", keyed_hits,
        "外部仕様の値・閾値・TTLの直書き。T633のmaxzoom=11がこの型だった。",
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-files", type=int, default=3, help="何ファイル以上に散っていたら報告するか")
    args = parser.parse_args()
    scan(args.min_files)
    return 0


if __name__ == "__main__":
    sys.exit(main())
