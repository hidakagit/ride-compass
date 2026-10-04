"""文書とコメントが「パス: 名前」の形で名指ししたものが、今のリポジトリに実在することの検査。

名指しした名前が消えても・動いても、書いた側は何も壊れない。読んだ人は無い関数を探して迷う。
何を読み、何を実在とみなすかの規約は`docs/conventions/documentation.md`「他のファイルの名前は
「パス: 名前」で指す」が持つ。ここでは見ないもの: 形を外れた名指し（「`page.tsx`の`X`」等）は
周期レビューの「名指しの実在」が見る。
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import tokenize
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

TARGET_EXTENSIONS = r"(?:py|tsx?|js|mjs|cjs|ya?ml|json|sql|sh|toml|ini|css)"

# コロンの後は空白1つ以上か改行（行を折り返した先の行頭のコメント記号は読み飛ばす）。
# `host.json:ro`のようにコロンの直後に続く綴りは名指しではない。
REFERENCE = re.compile(
    r"(?<![A-Za-z0-9_./*-])"
    r"(?P<path>[A-Za-z0-9_.*/-]*[A-Za-z0-9_*-]\." + TARGET_EXTENSIONS + r")"
    r"`?:(?:[ \t]+|[ \t]*\n[ \t]*(?:#|//|\*|>)?[ \t]*)`?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)"
)

HASH_COMMENT_SUFFIXES = {".yml", ".yaml", ".sh", ".ini", ".toml"}
SLASH_COMMENT_SUFFIXES = {".ts", ".tsx", ".js", ".mjs", ".cjs", ".css"}
SCANNED_SUFFIXES = {".md", ".py", ".sql"} | HASH_COMMENT_SUFFIXES | SLASH_COMMENT_SUFFIXES
UNMAINTAINED_PREFIXES = ("docs/records/",)


def _line_offsets(text: str) -> list[int]:
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _python_prose_spans(text: str) -> list[tuple[int, int]]:
    offsets = _line_offsets(text)

    def at(row: int, col: int) -> int:
        return offsets[row - 1] + col

    spans = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT:
                spans.append((at(*tok.start), at(*tok.end)))
        tree = ast.parse(text)
    except (SyntaxError, tokenize.TokenError):
        return [(0, len(text))]
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
            and node.end_lineno is not None
            and node.end_col_offset is not None
        ):
            # ASTの列はUTF-8のバイト数なので、行の中の位置は文字数へ直す。
            start_line = text[offsets[node.lineno - 1] : offsets[node.lineno]].encode("utf-8")
            end_line = text[offsets[node.end_lineno - 1] : offsets[node.end_lineno]].encode("utf-8")
            start_col = len(start_line[: node.col_offset].decode("utf-8"))
            end_col = len(end_line[: node.end_col_offset].decode("utf-8"))
            spans.append((at(node.lineno, start_col), at(node.end_lineno, end_col)))
    return spans


def _slash_prose_spans(text: str) -> list[tuple[int, int]]:
    """`//`・`/* */`のコメント。文字列（'・"・`）の中の記号はコメントの始まりに数えない。"""
    spans = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in "'\"`":
            j = i + 1
            while j < n and text[j] != c:
                if text[j] == "\\":
                    j += 1
                elif text[j] == "\n" and c != "`":
                    break
                j += 1
            i = j + 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            spans.append((i, end))
            i = end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            spans.append((i, end))
            i = end
        else:
            i += 1
    return spans


def _line_comment_spans(text: str, marker: str) -> list[tuple[int, int]]:
    pattern = re.compile(r"(?:^|(?<=\s))" + re.escape(marker) + r"[^\n]*", re.MULTILINE)
    return [m.span() for m in pattern.finditer(text)]


def prose_spans(rel_path: str, text: str) -> list[tuple[int, int]]:
    """そのファイルのうち、人が読む文として書かれた範囲（Markdownは全文、ソースはコメントとdocstring）。"""
    suffix = Path(rel_path).suffix
    if suffix == ".md":
        return [(0, len(text))]
    if suffix == ".py":
        return _python_prose_spans(text)
    if suffix in SLASH_COMMENT_SUFFIXES:
        return _slash_prose_spans(text)
    if suffix in HASH_COMMENT_SUFFIXES:
        return _line_comment_spans(text, "#")
    if suffix == ".sql":
        return _line_comment_spans(text, "--")
    return []


def _keep(text: str, spans: list[tuple[int, int]], *, inside: bool) -> str:
    """spansの内側（inside=True）か外側だけを残し、残りは改行を保って空白にする（位置と行番号を保つ）。"""
    mask = [not inside] * len(text)
    for start, end in spans:
        for k in range(start, end):
            mask[k] = inside
    return "".join(ch if keep or ch == "\n" else " " for ch, keep in zip(text, mask, strict=True))


def repository_files(root: Path) -> list[str]:
    """追跡下のファイルと、まだ`git add`していない無視されていないファイル。"""
    out = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8")
    return [f for f in out.split("\0") if f]


class _Repository:
    def __init__(self, root: Path, files: list[str]) -> None:
        self.root = root
        self.files = files
        self._by_name: dict[str, list[str]] = {}
        for f in files:
            self._by_name.setdefault(Path(f).name, []).append(f)
        self._code: dict[str, str] = {}

    def text(self, rel_path: str) -> str:
        try:
            return (self.root / rel_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return ""

    def resolve(self, written: str) -> list[str]:
        written = written.lstrip("./")
        if "*" in written:
            pattern = re.compile(r"^(?:.*/)?" + re.escape(written).replace(r"\*", "[^/]*") + "$")
            return [f for f in self.files if pattern.match(f)]
        return [f for f in self._by_name.get(Path(written).name, []) if f == written or f.endswith("/" + written)]

    def code(self, rel_path: str) -> str:
        if rel_path not in self._code:
            text = self.text(rel_path)
            self._code[rel_path] = _keep(text, prose_spans(rel_path, text), inside=False)
        return self._code[rel_path]


def _names_in(code: str, dotted: str) -> bool:
    return all(
        re.search(r"(?<![A-Za-z0-9_$])" + re.escape(part) + r"(?![A-Za-z0-9_$])", code) for part in dotted.split(".")
    )


def dangling_references(root: Path, files: list[str]) -> list[str]:
    """「パス: 名前」の名指しのうち、実在しないものを`書いた場所: 名指し（理由）`で返す。"""
    repo = _Repository(root, files)
    found = []
    for rel_path in files:
        if Path(rel_path).suffix not in SCANNED_SUFFIXES or rel_path.startswith(UNMAINTAINED_PREFIXES):
            continue
        text = repo.text(rel_path)
        if not REFERENCE.search(text):
            continue
        prose = _keep(text, prose_spans(rel_path, text), inside=True)
        for m in REFERENCE.finditer(prose):
            written, name = m.group("path"), m.group("name")
            where = f"{rel_path}:{prose.count(chr(10), 0, m.start()) + 1}: {written}: {name}"
            candidates = repo.resolve(written)
            if not candidates:
                found.append(f"{where}（そのパスのファイルが無い）")
            elif len(candidates) > 1 and "*" not in written:
                found.append(f"{where}（パスが{len(candidates)}本に当たる。親ディレクトリを足して1本に決める）")
            elif not any(_names_in(repo.code(c), name) for c in candidates):
                found.append(f"{where}（そのファイルのコードに名前が無い）")
    return found


def test_named_references_exist() -> None:
    dangling = dangling_references(REPO_ROOT, repository_files(REPO_ROOT))

    assert dangling == [], (
        "文書・コメントが「パス: 名前」で名指ししたものが見つからない。今の名前・パスへ直すか、"
        "名前を出さずに挙動を書く:\n  " + "\n  ".join(dangling)
    )


def test_detects_dangling_references(tmp_path: Path) -> None:
    """検査が効いていること（消えた名前・無いパス・曖昧なパスを置いて捕まえ、正しい名指しと
    文字列リテラルは見逃す）。"""
    files = {
        "app/a.py": '"""モジュール。"""\n\nLIVE = 1\n# GONE はコメントにだけ残っている\n',
        "app/b/util.ts": "export const helper = 1;\n",
        "app/c/util.ts": "export const helper = 2;\n",
        "app/d.py": (
            "# `a.py: LIVE`は実在する。`a.py: GONE`はコードに無い。\n"
            'MESSAGE = "a.py: NOT_A_REFERENCE"\n'
            "# 折り返した名指しも読む: a.py:\n"
            "# GONE_TOO\n"
        ),
        "app/e.ts": '// `a.py: GONE_TS`\nconst url = "https://x/a.py: NOT_A_REFERENCE";\n',
        "docs/guide.md": "`util.ts: helper`と`b/util.ts: helper`と`missing.py: X`。\n",
        "docs/records/old.md": "`a.py: GONE`\n",
    }
    for rel, body in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body, encoding="utf-8")

    assert dangling_references(tmp_path, sorted(files)) == [
        "app/d.py:1: a.py: GONE（そのファイルのコードに名前が無い）",
        "app/d.py:3: a.py: GONE_TOO（そのファイルのコードに名前が無い）",
        "app/e.ts:1: a.py: GONE_TS（そのファイルのコードに名前が無い）",
        "docs/guide.md:1: util.ts: helper（パスが2本に当たる。親ディレクトリを足して1本に決める）",
        "docs/guide.md:1: missing.py: X（そのパスのファイルが無い）",
    ]


def test_untracked_files_count_as_existing(tmp_path: Path) -> None:
    """`git add`前の新しいファイルは実在に数え、無視されたファイルは数えない。"""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    files = {
        ".gitignore": "ignored.py\n",
        "app/new.py": "LIVE = 1\n",
        "app/ignored.py": "HIDDEN = 1\n",
        "docs/guide.md": "`new.py: LIVE`と`ignored.py: HIDDEN`。\n",
    }
    for rel, body in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(body, encoding="utf-8")

    assert dangling_references(tmp_path, repository_files(tmp_path)) == [
        "docs/guide.md:1: ignored.py: HIDDEN（そのパスのファイルが無い）",
    ]
