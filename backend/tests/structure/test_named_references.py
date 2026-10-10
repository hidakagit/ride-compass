"""文書とコメントが名指ししたもの（「パス: 名前」・ファイルのパス・APIのパス）が、今のリポジトリに実在することの検査。

名指しした名前が消えても・動いても、書いた側は何も壊れない。読んだ人は無い関数・ファイル・APIを探して迷う。
書く側の約束は`.claude/rules/documentation.md`「他のファイルの名前は「パス: 名前」で指す」が持つ。

何を読み、何を実在とみなすか:

- 読む側はMarkdownの全文と、ソースのコメント・docstring。文字列リテラルと`docs/records/`は読まない。
- 手元では`git add`前の新しいファイルも実在に数える（`.gitignore`で無視されたものは数えない）。
- 「パス: 名前」のパスは末尾一致でファイルに当てる。同じ名前のファイルが後から増えて2本以上に当たると「曖昧」として
  落とす。`*`を含むパスは、当たったファイルのどれかに名前があればよい。名前はそのファイルのコードに現れる綴りで探し、
  コメント・docstringにだけ残った名前は無いものに数える。
- ファイルのパスは、テストのファイル名（`test_*.py`・`*.test.ts(x)`）と、リポジトリの最上位のディレクトリから
  書いたパス（`backend/`・`docs/`等で始まるもの）だけを読み、末尾一致でどれかのファイルに当たれば実在に数える。
  `.gitignore`が無視するパス（`.env`等）も実在に数える。ほかの拡張子つきの綴りは読まない。
- APIのパス（`/api/…`）は、backendのOpenAPIの生成物とNextのroute handlerに照らし、APIのパスそのものか、
  その先頭の区切り（`/api/admin`）か、`{…}`の位置に値を埋めたもの（`/api/jma-tile/a/b.png`）なら実在に数える。
- `<…>`・`{…}`を含む綴りは、ファイルのパスとしては読まず、APIのパスではその位置に何かが入るものとして読む。

ここでは見ないもの: 形を外れた名指し（「`page.tsx`の`X`」・最上位の
ディレクトリから書いていない、テストでないファイルのパス等）は周期レビューの「名指しの実在」が見る。
"""

from __future__ import annotations

import ast
import io
import json
import re
import subprocess
import tokenize
from collections.abc import Iterator
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

# ファイルのパスとして読むのは、テストのファイル名と、リポジトリの最上位のディレクトリから書いたパスだけ。
# ほかの拡張子つきの綴り（外部の配信のファイル名・ライブラリの名前）は、消えたファイルの名指しと書いた位置で
# 見分けられない。`<…>`・`{…}`を含む綴りは例の形なので、綴りごと読まない。
PATH = re.compile(
    r"(?<![A-Za-z0-9_./*:<>{}\[\]-])"
    r"(?P<path>[A-Za-z0-9_.*/\[\]-]*[A-Za-z0-9_*\]-]\.[A-Za-z0-9]+)"
    r"(?![A-Za-z0-9_/<>{}])"
)
TEST_FILE = re.compile(r"(?:^|/)(?:test_[^/]*\.py|[^/]*\.test\.tsx?)$")

# `<…>`・`{…}`はその位置に何かが入る例として読む（`/api/admin<X>`・`/api/admin/<X>`）。
API_PATH = re.compile(r"(?<![A-Za-z0-9_./:<>{}-])(?P<path>/api/(?:<[^<>\s]*>|[A-Za-z0-9_.{}*/-])*)")
OPENAPI = "frontend/src/types/generated/openapi.json"
ROUTE_HANDLER = re.compile(r"^frontend/src/app/(?P<path>.*)/route\.ts$")

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
        written = re.sub(r"^(?:\.\.?/)+", "", written)
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


def _prose_files(repo: _Repository) -> Iterator[tuple[str, str]]:
    """維持するファイルごとの、人が読む文の範囲だけを残したテキスト。"""
    for rel_path in repo.files:
        if Path(rel_path).suffix not in SCANNED_SUFFIXES or rel_path.startswith(UNMAINTAINED_PREFIXES):
            continue
        text = repo.text(rel_path)
        yield rel_path, _keep(text, prose_spans(rel_path, text), inside=True)


def _line_of(prose: str, match: re.Match[str]) -> int:
    return prose.count("\n", 0, match.start()) + 1


def dangling_references(root: Path, files: list[str]) -> list[str]:
    """「パス: 名前」の名指しのうち、実在しないものを`書いた場所: 名指し（理由）`で返す。"""
    repo = _Repository(root, files)
    found = []
    for rel_path, prose in _prose_files(repo):
        for m in REFERENCE.finditer(prose):
            written, name = m.group("path"), m.group("name")
            where = f"{rel_path}:{_line_of(prose, m)}: {written}: {name}"
            candidates = repo.resolve(written)
            if not candidates:
                found.append(f"{where}（そのパスのファイルが無い）")
            elif len(candidates) > 1 and "*" not in written:
                found.append(f"{where}（パスが{len(candidates)}本に当たる。親ディレクトリを足して1本に決める）")
            elif not any(_names_in(repo.code(c), name) for c in candidates):
                found.append(f"{where}（そのファイルのコードに名前が無い）")
    return found


def _ignored(root: Path, paths: set[str]) -> set[str]:
    """`.gitignore`が無視するパス。開発機にだけ置くファイル（`.env`等）は、リポジトリがその置き場を宣言している。"""
    out = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin", "-z"],
        cwd=root,
        input="\0".join(sorted(paths)).encode("utf-8"),
        capture_output=True,
    )
    # 終了コード1は「どれも無視されない」。
    if out.returncode not in (0, 1):
        raise RuntimeError(out.stderr.decode("utf-8"))
    return {p for p in out.stdout.decode("utf-8").split("\0") if p}


def dangling_paths(root: Path, files: list[str]) -> list[str]:
    """名指ししたファイルのパスのうち、実在しないものを`書いた場所: パス（理由）`で返す。"""
    repo = _Repository(root, files)
    top_dirs = {f.split("/", 1)[0] for f in files if "/" in f}
    unresolved = []
    for rel_path, prose in _prose_files(repo):
        for m in PATH.finditer(prose):
            written = m.group("path")
            if not (TEST_FILE.search(written) or ("/" in written and written.split("/", 1)[0] in top_dirs)):
                continue
            if not repo.resolve(written):
                unresolved.append((f"{rel_path}:{_line_of(prose, m)}: {written}", written))
    ignored = _ignored(root, {written for _, written in unresolved})
    return [f"{where}（そのパスのファイルが無い）" for where, written in unresolved if written not in ignored]


def _route_template(rel_path: str) -> str | None:
    """Nextのroute handlerのファイルが受けるURLのパス（`[x]`・`[...x]`は`{x}`、`(group)`は外す）。"""
    m = ROUTE_HANDLER.match(rel_path)
    if not m:
        return None
    segments = [s for s in m.group("path").split("/") if not (s.startswith("(") and s.endswith(")"))]
    return "/" + "/".join(re.sub(r"^\[(?:\.\.\.)?(.*)\]$", r"{\1}", s) for s in segments)


def _api_exists(written: str, routes: list[str]) -> bool:
    """書いたパスが、あるAPIのパスそのものか、その先頭の区切り（`/api/admin`）か。"""
    written = written.rstrip("./")
    pattern = re.escape(written)
    pattern = re.sub(r"<[^<>]*>", ".*", pattern)
    pattern = re.sub(r"\\\{[^/]*?\\\}", "[^/]*", pattern)
    pattern = pattern.replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
    for route in routes:
        if re.match("^" + pattern + "(?:/|$)", route):
            return True
        concrete = re.sub(r"\\\{path\\\}", ".+", re.escape(route))
        if re.fullmatch(re.sub(r"\\\{[^/]*?\\\}", "[^/]+", concrete), written):
            return True
    return False


def dangling_api_paths(root: Path, files: list[str]) -> list[str]:
    """名指ししたAPIのパス（`/api/…`）のうち、backendのOpenAPIにもNextのroute handlerにも無いものを返す。"""
    repo = _Repository(root, files)
    routes = list(json.loads(repo.text(OPENAPI))["paths"])
    routes += [t for t in map(_route_template, files) if t and t.startswith("/api/")]
    found = []
    for rel_path, prose in _prose_files(repo):
        for m in API_PATH.finditer(prose):
            if not _api_exists(m.group("path"), routes):
                found.append(f"{rel_path}:{_line_of(prose, m)}: {m.group('path')}（そのパスのAPIが無い）")
    return found


def test_named_references_exist() -> None:
    dangling = dangling_references(REPO_ROOT, repository_files(REPO_ROOT))

    assert dangling == [], (
        "文書・コメントが「パス: 名前」で名指ししたものが見つからない。今の名前・パスへ直すか、"
        "名前を出さずに挙動を書く:\n  " + "\n  ".join(dangling)
    )


def test_named_paths_exist() -> None:
    dangling = dangling_paths(REPO_ROOT, repository_files(REPO_ROOT))

    assert dangling == [], (
        "文書・コメントが名指ししたファイルが見つからない。今のパスへ直すか、例なら`<…>`の形で書く:\n  "
        + "\n  ".join(dangling)
    )


def test_named_api_paths_exist() -> None:
    dangling = dangling_api_paths(REPO_ROOT, repository_files(REPO_ROOT))

    assert dangling == [], (
        "文書・コメントが名指ししたAPIのパスが見つからない。今のパスへ直すか、例なら`<…>`の形で書く:\n  "
        + "\n  ".join(dangling)
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


def _write_repository(root: Path, files: dict[str, str]) -> list[str]:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    for rel, body in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body, encoding="utf-8")
    return repository_files(root)


def test_detects_dangling_paths(tmp_path: Path) -> None:
    """テストのファイル名と最上位のディレクトリから書いたパスだけを読み、無いものを捕まえる。ほかの綴り・例の形・
    `.gitignore`が無視するファイル・文字列リテラルは見逃す。"""
    files = _write_repository(
        tmp_path,
        {
            ".gitignore": "*.local\n",
            ".claude/settings.json": "{}\n",
            "backend/app/a.py": '"""モジュール。"""\n',
            "backend/tests/test_a.py": "",
            "backend/app/b.py": 'PATH = "backend/app/gone.py"\n# 消えた`backend/app/gone_too.py`\n',
            "docs/guide.md": (
                "`backend/app/a.py`・`app/a.py`・`test_a.py`・`backend/tests/test_*.py`・`.claude/settings.json`・"
                "`../backend/app/a.py`・`backend/.env.local`・`backend/<名前>.py`・`area.json`・`https://x/backend/gone.py`。\n"
                "`backend/app/gone.py`・`test_gone.py`・`frontend/x.test.ts`。\n"
            ),
            "docs/records/old.md": "`backend/app/gone.py`\n",
        },
    )

    assert dangling_paths(tmp_path, files) == [
        "backend/app/b.py:2: backend/app/gone_too.py（そのパスのファイルが無い）",
        "docs/guide.md:2: backend/app/gone.py（そのパスのファイルが無い）",
        "docs/guide.md:2: test_gone.py（そのパスのファイルが無い）",
        "docs/guide.md:2: frontend/x.test.ts（そのパスのファイルが無い）",
    ]


def test_detects_dangling_api_paths(tmp_path: Path) -> None:
    """backendのOpenAPIとNextのroute handlerに照らし、無いAPIのパスを捕まえる。パスそのもの・先頭の区切り・
    埋めた値・例の形は見逃す。"""
    files = _write_repository(
        tmp_path,
        {
            OPENAPI: '{"paths": {"/api/admin/items/{item_id}/values": {}, "/api/tiles/{path}": {}}}\n',
            "frontend/src/app/api/version/route.ts": "export const GET = 1;\n",
            "frontend/src/app/admin/api/[...path]/route.ts": "export const GET = 1;\n",
            "backend/app/c.py": 'URL = "/api/gone"\n',
            "docs/api.md": (
                "`GET /api/admin/items/{id}/values`・`/api/admin`・`/api/admin/`・`/api/admin<X>`・`/api/admin/*`・"
                "`/api/tiles/a/b.png`・`/api/version`・`/admin/api/x`・`https://x/api/gone`。\n"
                "`/api/items/{item_id}/values`・`/api/version/gone`・`/api/admi`。\n"
            ),
        },
    )

    assert dangling_api_paths(tmp_path, files) == [
        "docs/api.md:2: /api/items/{item_id}/values（そのパスのAPIが無い）",
        "docs/api.md:2: /api/version/gone（そのパスのAPIが無い）",
        "docs/api.md:2: /api/admi（そのパスのAPIが無い）",
    ]
