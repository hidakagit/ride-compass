#!/usr/bin/env python3
"""周期レビュー（.claude/commands/review/）の機械的チェックをまとめたスクリプト。

Agent（人力）で行っていた「grep一発で済む」確認をここへ寄せ、レビューの負荷を下げる。
標準ライブラリのみで動く（backend/.venvでもシステムのpythonでもよい）。

サブコマンド:
  docs     docs/modules の死んだ参照・新規ファイルの記載漏れ・記載粒度違反、
           backend/app・frontend/src のソースコードコメントの経緯記述（docs/comments.md、
           --staged/--sinceでは追加行のみ違反として数える。フルスキャンではT567完了までの
           既存分が大量にあるため参考件数のみで違反に数えない）、
           improvement-plan.md の [x]/[ ] と docs/tasks/Txxx.md「状態:」行の照合（行頭が
           「状態:」であること自体も違反として見る）、
           history/・docs/tasks/ への死んだリンク（consistency.md「設計 ↔ 実装」節の機械的部分）。
           どの検知器をどの経路で強制するかの正本は`DETECTOR_ENFORCEMENT`（ここは要約）
  size     規模ウォッチ（complexity.md）: 実装ファイル行数の上位と前回比・閾値発火
  duplication コピペ検出（complexity.md）: jscpdでの完全一致クローンと前回比
  metrics  定量メトリクス（metrics.md）: cloc・churn・テスト件数・静的検査・依存関係
  trigger  周期レビューのトリガー判定（README.md「定期的なレビュー」節）

使い方の例:
  python scripts/review_checks.py docs                 # 全件監査（ソースコード経緯コメントは参考件数のみ）
  python scripts/review_checks.py docs --since cab1441 # 記載漏れ・ソースコード経緯コメントをこのref以降の追加分に限定（CI向け）
  python scripts/review_checks.py docs --staged        # pre-commit用（ステージ済み変更に関係する項目のみ）
  python scripts/review_checks.py size                 # 現在値と前回比を表示
  python scripts/review_checks.py size --update        # 表示したうえで前回値ファイルを今回値へ更新
  python scripts/review_checks.py duplication          # コピペ検出（npx経由でjscpd、数十秒）
  python scripts/review_checks.py duplication --update # 表示したうえで前回値ファイルを更新
  python scripts/review_checks.py metrics --full       # テスト件数・tsc/eslint・npm auditも計測（数分）
  python scripts/review_checks.py trigger

終了コード: docs は違反があれば1、それ以外は常に0（計測・判定結果の表示のみ）。
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import functools
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tokenize
from collections import defaultdict
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
REVIEW_DIR = REPO_ROOT / ".claude" / "commands" / "review"
HISTORY_DIR = REVIEW_DIR / "history"
MODULES_DIR = REPO_ROOT / "docs" / "modules"
TASKS_DIR = REPO_ROOT / "docs" / "tasks"
IMPROVEMENT_PLAN = REPO_ROOT / "docs" / "improvement-plan.md"
SIZE_BASELINE = HISTORY_DIR / "size_watch.json"
DUPLICATION_BASELINE = HISTORY_DIR / "duplication.json"

# --- 共通 -------------------------------------------------------------------

IMPL_INCLUDE_PREFIXES = ("backend/app/", "frontend/src/")
# frontend/src/testing/はテストだけが使う補助（フェイク・フィクスチャ）で、docs/modulesが
# 記述する対象は実装モジュールのため、.test.と同じく除外する（置き場所と使い方は
# docs/testing.md「パターン5」が持つ。backend側の同種の補助はbackend/tests/配下にあり、
# IMPL_INCLUDE_PREFIXESがbackend/app/しか含まないため元から対象外）。
IMPL_EXCLUDE_RE = re.compile(
    r"(\.test\.|\.spec\.|\.bench\.|/types/generated/|\.module\.css$|\.css$|\.d\.ts$"
    r"|/__init__\.py$|/__pycache__/|\.json$|\.yml$|\.yaml$|\.md$|\.snap$"
    r"|^frontend/src/testing/)"
)
# 名前だけでは特定できないファイル名は「親ディレクトリ/名前」で照合する
GENERIC_BASENAMES = {
    "page.tsx", "layout.tsx", "route.ts", "index.ts", "index.tsx", "types.ts",
    "utils.ts", "constants.ts", "config.py", "main.py", "models.py", "errors.py",
}
# docs/modules/README.md「記載粒度」節の禁止パターン。
# 唯一の定義元（scripts/pre-commit-docs-modules-history.shは2026-09-03のT561でこの関数を
# 呼ぶだけの薄いラッパへ統合し、shell側に別定義のPATTERNを持たない）。
NARRATIVE_PATTERN = re.compile(
    # 「改善計画Txxx」は後ろに何が続いても経緯参照のため、区切り文字を要求しない
    # （`で`/`：`だけを要求していたころは「改善計画T572。」「改善計画T87/T606」のような
    # 句点・スラッシュ区切りが素通りしていた）。
    r"以前は|従来は|旧「|旧『|旧T[0-9]|旧実装|旧デザイン|旧方式|改善計画T[0-9]+|T[0-9]{3,4}で"
    r"|T[0-9]{3,4}[:：]|実機報告|実機フィードバック|実機確認|実機指摘|実測で|判明した|発覚した"
    r"|指摘を受け|フィードバックを受け|ユーザー指摘|ユーザー要望|ユーザー判断|ユーザーから"
    r"|方式ではなく|していたのを|へ変更した|に変更した|を導入した|コードレビュー指摘|実バグ"
    r"|UIレビュー|ゼロベース網羅"
    # 「〜だった頃は」「〜ていたころは」という時制表現も、過去の状態を語る＝経緯にあたる。
    # 直前に`た`を要求することで「今のところは」（`たところ`）を誤検出しない。
    r"|た頃|たころ"
)
# docs/comments.md「コメント方針」節が禁止するソースコード内の経緯コメント検出用。
# docs/modules向けのNARRATIVE_PATTERNをそのまま流用する（定義元を分けない）。
# コメント行以外（実装コード・文字列リテラル）を誤検出しないよう、行のコメント部分だけを
# 抽出してから照合する（comment_only参照）。
SOURCE_COMMENT_PATHSPECS = (
    "backend/app/*.py",
    "frontend/src/*.ts",
    "frontend/src/*.tsx",
    # CSS Modulesは設計意図を長文コメントで書く運用のため対象に含める。
    "frontend/src/*.css",
)


def comment_only(line: str, path: str, jsx_state: dict[str, bool]) -> str:
    """1行のうちコメント部分だけを返す（非コメント行・コメントなしは空文字）。

    diffの追加行1行ずつを独立に見るため、複数行にまたがるブロックコメントの内部行
    （`*`始まりの継続行等）は「行頭が*・/*・*/」という単純な形で判定する——完全な
    構文解析はしない（review_checks.py全体の「grep一発規模の安価なチェック」という
    設計方針に合わせる）。JSX `{/* ... */}` ブロックは開始行が`{/*`、終了行が`*/}`を
    含む行として扱い、`jsx_state`（呼び出し元がファイル単位で使い回す辞書）へ
    「現在ブロック内か」を持たせて複数行にまたがる継続行も拾う。
    """
    stripped = line.strip()
    if path.endswith(".py"):
        # `#`コメントだけを見る。docstringは行単位では判定できないため、呼び出し元が
        # python_comment_lines()で行番号を先に絞り込む（この関数は絞り込み済みの行を受け取る）。
        idx = line.find("#")
        return line[idx:] if idx != -1 else line
    if path.endswith(".css"):
        # CSSのコメントは`/* */`のみ（`//`はコメントではない）。複数行ブロックの継続行は
        # jsx_stateと同じ方式で追う。
        if jsx_state.get("in_css_comment"):
            if "*/" in line:
                jsx_state["in_css_comment"] = False
            return line
        idx = line.find("/*")
        if idx == -1:
            return ""
        if "*/" not in line[idx:]:
            jsx_state["in_css_comment"] = True
        return line[idx:]
    # ts/tsx
    if jsx_state.get("in_jsx_comment"):
        if "*/}" in line:
            jsx_state["in_jsx_comment"] = False
        return line
    if stripped.startswith("{/*"):
        if "*/}" not in line:
            jsx_state["in_jsx_comment"] = True
        return line
    if stripped.startswith(("/**", "/*", "*/", "*")):
        return line
    idx = line.find("//")
    return line[idx:] if idx != -1 else ""


def python_comment_lines(path: str) -> set[int] | None:
    """`path`のうちコメント・docstringに属する行番号。解析できなければNone（全行を対象にする）。

    Pythonの説明文は大半がdocstringにあるため、`#`だけを見ると経緯コメントの検知が
    構造的に大きく取りこぼす。行単位のヒューリスティックでは三重引用符の開閉を追えない
    （diffの追加行は連続していない）ため、ファイル全体を`ast`で解析して
    module/class/functionのdocstringが占める行を求め、`tokenize`で`#`コメント行を足す。
    """
    try:
        source = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError, ValueError):
        return None
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            lines.update(range(first.value.lineno, (first.value.end_lineno or first.value.lineno) + 1))
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                lines.add(token.start[0])
    except (tokenize.TokenError, IndentationError):
        pass
    return lines


def find_source_narrative_violations(source_lines: dict[str, list[tuple[int, str]]]) -> list[str]:
    out = []
    for path, lines in source_lines.items():
        jsx_state: dict[str, bool] = {}
        comment_linenos = python_comment_lines(path) if path.endswith(".py") else None
        for lineno, line in lines:
            if comment_linenos is not None and lineno not in comment_linenos:
                continue
            text = comment_only(line, path, jsx_state)
            if not text:
                continue
            m = NARRATIVE_PATTERN.search(text)
            if m:
                out.append(f"{path}:{lineno}: 「{m.group(0)}」 {text.strip()[:80]}")
    return out
# Redis cache-asideの骨格（可用性チェック→クライアント取得→計測→fail-open→成否記録）は
# `redis_json_cache.py`の`get_json`/`set_json`が内包している。これを自前で書き直すと、
# 写経ミス（`record_redis_failure`の呼び忘れ等）でRedis障害の検知だけが静かに欠ける
# （アプリはfail-openのまま動き続けるため表に出ない）。docs/caching.md参照。
REDIS_SKELETON_RE = re.compile(
    r"(get_redis_client_or_none|record_redis_failure|record_redis_success|redis_available)"
)
# 骨格を自前で持ってよいファイル。増やすときは理由をモジュールのdocstringへ書くこと
# （docs/caching.md「自前で骨格を書いてよい例外」）。
REDIS_SKELETON_ALLOWLIST = {
    "backend/app/infrastructure/redis_client.py",  # 骨格が使う接続・サーキットブレーカー本体
    "backend/app/infrastructure/redis_json_cache.py",  # 骨格そのもの
    "backend/app/infrastructure/jma_tile_redis_cache.py",  # 値がバイナリでJSON化に馴染まない
    # 全国約1,300観測所をpipelineでHashへ一括読み書きする（get_json/set_jsonの単一キー
    # JSON読み書きでは表現できない）。docs/caching.md「自前で骨格を書いてよい例外」の
    # 「mget/pipelineによる一括読み書き」に当たり、fail-openと失敗の記録は満たしている。
    "backend/app/services/jma_amedas_service.py",
}


def find_redis_skeleton_violations(source_lines: dict[str, list[tuple[int, str]]]) -> list[str]:
    """許可リスト外のファイルでRedis cache-asideの骨格を自前で書いていないか。"""
    out = []
    for path, lines in source_lines.items():
        if path in REDIS_SKELETON_ALLOWLIST:
            continue
        for lineno, line in lines:
            m = REDIS_SKELETON_RE.search(line)
            if m:
                out.append(f"{path}:{lineno}: `{m.group(0)}` を直接使っている（redis_json_cacheのget_json/set_jsonを使う）")
    return out


# Pydanticの`extra`の既定は`ignore`で、モデルが知らないフィールドは例外にならず捨てられる。
# フィールドを消した・改名したときの取り残しが「値は入らないがテストは通る」という無言の形で
# 残るため、backend/app配下のモデルは`StrictModel`（extra="forbid"）を継承する
# （docs/tasks/T721.md、app/domain/strict_model.py）。
BARE_BASEMODEL_RE = re.compile(r"^class\s+(\w+)\s*\(\s*BaseModel\s*\)\s*:")
# 素のBaseModelを使ってよいファイル。増やすときは理由をそのモジュールのdocstringへ書くこと。
BARE_BASEMODEL_ALLOWLIST = {
    "backend/app/domain/strict_model.py",  # StrictModel自身の定義
}


def find_bare_basemodel_violations(source_lines: dict[str, list[tuple[int, str]]]) -> list[str]:
    """backend/app配下で`StrictModel`ではなく素の`BaseModel`を継承しているモデル。"""
    out = []
    for path, lines in source_lines.items():
        if not path.startswith("backend/app/") or path in BARE_BASEMODEL_ALLOWLIST:
            continue
        for lineno, line in lines:
            m = BARE_BASEMODEL_RE.match(line)
            if m:
                out.append(
                    f"{path}:{lineno}: `{m.group(1)}`が素のBaseModelを継承している"
                    "（StrictModelを継承する。外部ペイロードを直接受ける場合のみ"
                    "extra=\"ignore\"を明示して理由を書く）"
                )
    return out


FILE_TOKEN_RE = re.compile(
    r"`([A-Za-z0-9_./@\-]+\.(?:py|ts|tsx|css|json|yml|yaml|sql|sh|md|js|mjs|toml|txt))`"
)
TASK_LINK_RE = re.compile(r"\[T(\d{3,4})\]\(")
TASK_FILE_MENTION_RE = re.compile(r"\bT(\d{3,4})\.md\b")
HISTORY_REF_RE = re.compile(r"history/(\d{4}-\d{2}-\d{2}_[A-Za-z0-9_\-]+\.md)")
PLAN_LINE_RE = re.compile(r"^- \[( |x)\] \[T(\d{3,4})\]\(tasks/T\d{3,4}\.md\)")


def run(cmd: list[str], cwd: Path | None = None, check: bool = True, timeout: int = 600) -> str:
    proc = subprocess.run(
        cmd, cwd=str(cwd or REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout, shell=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(f"コマンド失敗: {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc.stdout


def git(*args: str, check: bool = True) -> str:
    return run(["git", *args], check=check)


def git_files() -> list[str]:
    return [line for line in git("ls-files").splitlines() if line]


def is_impl_file(path: str) -> bool:
    return (
        path.startswith(IMPL_INCLUDE_PREFIXES)
        and path.endswith((".py", ".ts", ".tsx"))
        and not IMPL_EXCLUDE_RE.search(path)
    )


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def count_lines(path: Path) -> int:
    with path.open("rb") as f:
        return sum(1 for _ in f)


def module_docs() -> list[Path]:
    return sorted(p for p in MODULES_DIR.rglob("*.md") if p.name != "README.md")


def rel(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()


# --- docs -------------------------------------------------------------------

def find_dead_file_refs(doc_lines: dict[str, list[tuple[int, str]]], files: list[str]) -> list[str]:
    """docs/modulesのバッククォート付きファイル名のうち、リポジトリに実在しないもの。"""
    file_set = set(files)
    by_basename: dict[str, set[str]] = defaultdict(set)
    for f in files:
        by_basename[f.rsplit("/", 1)[-1]].add(f)
    out = []
    for doc, lines in doc_lines.items():
        for lineno, line in lines:
            for token in FILE_TOKEN_RE.findall(line):
                if "*" in token or token.startswith(("http", "@")):
                    continue
                name = token.rsplit("/", 1)[-1]
                if "/" in token:
                    exists = token in file_set or any(f.endswith("/" + token) for f in by_basename.get(name, ()))
                else:
                    exists = name in by_basename
                if not exists:
                    out.append(f"{doc}:{lineno}: `{token}` が実在しない")
    return out


# docs/modulesがバッククォートで名指しする識別子（関数・定数・型・フック名）。
# `road_graph_repository.py: sample_way_rows`のような「ファイル名: 識別子」形式も拾う。
DOC_IDENT_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]{2,})`")
DOC_QUALIFIED_IDENT_RE = re.compile(
    r"`[A-Za-z0-9_./\-]+\.(?:py|ts|tsx|css):\s*([A-Za-z_][A-Za-z0-9_]{2,})`"
)
SOURCE_CORPUS_PREFIXES = ("backend/", "frontend/src/", "scripts/")
SOURCE_CORPUS_SUFFIXES = (".py", ".ts", ".tsx", ".css", ".sql", ".sh", ".mjs", ".js")
# テストケース本体は母集団から外す。docs/modulesが名指しするのは実装の識別子で、
# テストが古い名前を文字列やアサーションとして持っているだけで「実在する」と判定されると、
# 改名の取り残しを見逃す（この検知器自身の回帰テストが旧名を持つため、実際にそうなる）。
# テスト専用ヘルパー（`tests/geo_fixtures.py`・`frontend/src/testing/`・conftest.py）は
# 母集団に残す——docs/modulesが「本番コードには置かずテスト側に持つ」ことを明記して
# 名指しする対象で、これらを外すと正しい記述が違反になる。
SOURCE_CORPUS_EXCLUDE_RE = re.compile(
    r"(\.test\.|\.spec\.|\.bench\.|(?:^|/)test_[^/]*\.py$|/__pycache__/)"
)


def looks_like_identifier(token: str) -> bool:
    """バッククォート内の語が「コードの識別子」の形をしているか。

    英単語1語（`hidden`・`boolean`等、説明文の強調）を識別子として扱うと、実装に
    その綴りが無いだけで違反になる。スネークケース・大小混在（camel/Pascal）・
    全大文字のいずれかであることを要求して、説明文の強調と区別する。
    """
    if "_" in token:
        return True
    if token.isupper():
        return True
    return any(c.islower() for c in token) and any(c.isupper() for c in token)


# --- architecture.md（「現状の姿」を書く文書。docs/modulesとは基準が違う） -------
#
# docs/modulesの検知器をそのまま当てない。architecture.mdは「なぜその選択をしたか」
# 「何を試して駄目だったか」を書く文書で、経緯の記述自体は正当（maplibre-glの
# バージョン固定のように、コードからは導けずドキュメントだけが持つ事実がある）。
# 一方で**撤去済みのものを、撤去したと書かずに名指しする**のは読み手を誤らせる
# ——それが実在すると読める（docs/tasks/T723.md）。
#
# したがって判定は「実在しない名前を、撤去等の断りなく書いているか」に限る。
# 断りを入れれば通る＝「もう無いものを名指しするなら、無いと同じ行に書く」という
# 編集上の規則そのもので、読み手にとっても有用。
ARCHITECTURE_DOC = "docs/architecture.md"
# 「この名前はもう無い」と明示的に断っている語だけを免除の根拠にする。判定の単位が段落で
# ある以上、語彙が広いほど段落1つぶんがまとめて対象外になる——「統合」「移行」「分離」の
# ような設計変更を述べるだけの語まで入れると、現役の名前を語る段落まで免除される。
ARCHITECTURE_REMOVED_MARKER_RE = re.compile(r"撤去|削除済|廃止|かつて|旧")
# リポジトリのファイルではないもの。外部APIのパス（気象庁の`targetTimes.json`等）と、
# 他プロジェクトのファイル名を引用している箇所は実在判定の対象外。
ARCHITECTURE_EXTERNAL_REFS = frozenset({
    "targetTimes.json", "targetTimes_N1/N2.json", "targetTimes_N3.json", "static/meta.json",
})


def doc_text_at(doc: str, revision: str | None) -> str:
    """`revision`時点の文書の中身（Noneなら作業ツリーの実体）。

    段落の判定は**行番号の出所と同じ内容**で行う必要がある。`--staged`は
    `git diff --cached`＝インデックスの行番号を返すため、作業ツリーを読むと
    `git add -p`での部分ステージやステージ後の追記でずれ、**別の段落の免除が適用される**
    （見逃し・誤検知の両方向）。
    """
    if revision is None:
        path = REPO_ROOT / doc
        return read_text(path) if path.exists() else ""
    return git("show", f"{revision}:{doc}", check=False)


def paragraphs_with_removal_marker(doc: str, revision: str | None = None) -> set[int]:
    """撤去等の断りを含む段落に属する行番号（空行区切り）。

    判定の単位は物理行ではなく段落にする。この文書は編集の都合で1文が複数行へ
    折り返されるため、行で見ると「名前」と「撤去済み」が別の行へ落ちただけで違反になる
    ——読み手が受け取る単位は段落であって、折り返し位置ではない。

    `revision`は行番号の出所（`""`＝インデックス、`"HEAD"`、Noneなら作業ツリー）。
    """
    text = doc_text_at(doc, revision)
    if not text:
        return set()
    marked: set[int] = set()
    start, buffer = 1, []
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.strip():
            if not buffer:
                start = lineno
            buffer.append(line)
            continue
        if buffer and ARCHITECTURE_REMOVED_MARKER_RE.search("\n".join(buffer)):
            marked.update(range(start, start + len(buffer)))
        buffer = []
    if buffer and ARCHITECTURE_REMOVED_MARKER_RE.search("\n".join(buffer)):
        marked.update(range(start, start + len(buffer)))
    return marked


def find_undeclared_dead_refs(
    doc_lines: dict[str, list[tuple[int, str]]], files: list[str], corpus: str,
    revision: str | None = None,
) -> list[str]:
    """architecture.mdが、実在しない名前を撤去等の断りなく名指ししている箇所。

    `revision`は`doc_lines`の行番号がどこ由来かを示す（`doc_text_at`参照）。
    """
    filtered = {}
    for doc, lines in doc_lines.items():
        marked = paragraphs_with_removal_marker(doc, revision)
        filtered[doc] = [
            (no, line)
            for no, line in lines
            if not ARCHITECTURE_REMOVED_MARKER_RE.search(line) and no not in marked
        ]
    return _dead_refs_of(filtered, files, corpus)


def _dead_refs_of(
    doc_lines: dict[str, list[tuple[int, str]]], files: list[str], corpus: str
) -> list[str]:
    out = [
        v for v in find_dead_file_refs(doc_lines, files)
        if not any(f"`{ext}`" in v for ext in ARCHITECTURE_EXTERNAL_REFS)
    ]
    out.extend(find_dead_identifier_refs(doc_lines, corpus))
    return sorted(out)


def find_dead_refs_inside_exempted_paragraphs(
    doc_lines: dict[str, list[tuple[int, str]]], files: list[str], corpus: str,
    revision: str | None = None,
) -> list[str]:
    """免除した段落の中に残っている、実在しない名前。

    段落単位の免除は「その段落のどこかに撤去の断りがある」だけを見ており、
    **その名前が断られているか**は見ていない。免除した中身を黙って捨てると、
    検知器の0件が「死んだ参照が無い」と読まれる。常に参考として出す。
    """
    inside = {}
    for doc, lines in doc_lines.items():
        marked = paragraphs_with_removal_marker(doc, revision)
        inside[doc] = [
            (no, line)
            for no, line in lines
            if no in marked and not ARCHITECTURE_REMOVED_MARKER_RE.search(line)
        ]
    return _dead_refs_of(inside, files, corpus)


def source_corpus(files: list[str]) -> str:
    """識別子の実在判定に使うソース全文（実装・スクリプト）。"""
    parts = []
    for f in files:
        if not f.startswith(SOURCE_CORPUS_PREFIXES) or not f.endswith(SOURCE_CORPUS_SUFFIXES):
            continue
        if SOURCE_CORPUS_EXCLUDE_RE.search(f):
            continue
        path = REPO_ROOT / f
        if path.exists():
            parts.append(read_text(path))
    return "\n".join(parts)


SETTINGS_CONFIG_PY = "backend/app/config.py"
# `Settings`のフィールド定義行（`    weather_rate_limit_per_minute: int = 30`）。
SETTINGS_FIELD_RE = re.compile(r"^\s{4}([a-z][a-z0-9_]*)\s*:", re.MULTILINE)


@functools.cache
def settings_field_names() -> frozenset[str]:
    """pydantic `Settings`のフィールド名。環境変数名の小文字形はここにしか現れない。"""
    path = REPO_ROOT / SETTINGS_CONFIG_PY
    if not path.exists():
        return frozenset()
    return frozenset(SETTINGS_FIELD_RE.findall(read_text(path)))


def identifier_exists(token: str, corpus: str) -> bool:
    """その綴りが実装にあるか。

    `.env`で設定する環境変数名（`WEATHER_RATE_LIMIT_PER_MINUTE`等）は、実装側には
    pydantic `Settings`の小文字フィールドとしてしか現れない。そこだけを救済する
    ——corpus全体で小文字形を探すと、`AXIS_DEFINITIONS`がモジュール名
    `axis_definitions.py`に一致してしまうように、**撤去しても常に存在する**定数が
    大量にできる（実測: 文書が名指しするSCREAMING_SNAKE定数173件のうち32件が、
    緩和のせいで検知不能だった。救済が要るのは10件だけ）。
    """
    if token in corpus:
        return True
    return token.isupper() and "_" in token and token.lower() in settings_field_names()


def find_dead_identifier_refs(doc_lines: dict[str, list[tuple[int, str]]], corpus: str) -> list[str]:
    """docs/modulesが名指しする識別子のうち、実装のどこにも綴りが無いもの。

    ファイル名の実在（find_dead_file_refs）だけでは、ファイルは残ったまま中の関数・定数が
    改名・削除された参照を検出できない。綴りの単純な包含判定で、改名の取り残しを拾う。
    """
    out = []
    for doc, lines in doc_lines.items():
        for lineno, line in lines:
            tokens = set(DOC_IDENT_RE.findall(line)) | set(DOC_QUALIFIED_IDENT_RE.findall(line))
            for token in sorted(tokens):
                if looks_like_identifier(token) and not identifier_exists(token, corpus):
                    out.append(f"{doc}:{lineno}: `{token}` が実装に存在しない")
    return out


def find_narrative_violations(doc_lines: dict[str, list[tuple[int, str]]]) -> list[str]:
    out = []
    for doc, lines in doc_lines.items():
        for lineno, line in lines:
            m = NARRATIVE_PATTERN.search(line)
            if m:
                out.append(f"{doc}:{lineno}: 「{m.group(0)}」 {line.strip()[:80]}")
    return out


def count_task_links(doc_lines: dict[str, list[tuple[int, str]]]) -> list[str]:
    out = []
    for doc, lines in doc_lines.items():
        for lineno, line in lines:
            for n in TASK_LINK_RE.findall(line):
                out.append(f"{doc}:{lineno}: [T{n}]リンク")
    return out


def find_undocumented_files(candidates: list[str], modules_text: str, all_files: list[str]) -> list[str]:
    """実装ファイルのうち、docs/modules/*.md のどこにもファイル名が出現しないもの。

    汎用的な名前（page.tsx・route.ts・config.py 等）はリポジトリ内で一意なら名前だけで、
    複数あれば「親ディレクトリ/名前」で照合する。
    """
    basename_count: dict[str, int] = defaultdict(int)
    for f in all_files:
        if is_impl_file(f):
            basename_count[f.rsplit("/", 1)[-1]] += 1
    out = []
    for path in sorted(candidates):
        if not is_impl_file(path):
            continue
        name = path.rsplit("/", 1)[-1]
        needles = [name]
        if name in GENERIC_BASENAMES and basename_count.get(name, 0) > 1:
            parent = path.rsplit("/", 2)[-2] if path.count("/") >= 2 else ""
            needles = [f"{parent}/{name}"]
        if not any(n in modules_text for n in needles):
            out.append(f"{path}: 「{needles[0]}」が docs/modules/*.md のどこにも出現しない")
    return out


# トリガー待ち（improvement-plan側も [ ] のまま）は「保留」で表す。
OPEN_STATUS_WORDS = ("未着手", "着手中", "進行中", "保留", "調査中", "中断", "作業中")
# 「見送り」は「今後もやらない確定判断」でimprovement-plan側は[x]にする
# （CLAUDE.md「コミット時の同期ルール」節の用語法。トリガー待ちと混ぜない）。
CLOSED_STATUS_WORDS = ("完了", "撤回", "取り下げ", "却下", "廃止", "見送り")
# 「存在しないこと自体」を記録している参照（T356: 2026-08-26のcomplexityレビュー結果が保存されなかった件）
KNOWN_MISSING_HISTORY = {"2026-08-26_complexity.md"}


def task_status_kind(task_path: Path) -> str | None:
    """docs/tasks/Txxx.md の「状態:」行を done / open / None（行なし）に分類する。"""
    for line in read_text(task_path).splitlines():
        if line.startswith("状態:"):
            body = line[len("状態:"):].strip()
            head = re.split(r"[（(]", body, maxsplit=1)[0]
            if any(w in head for w in OPEN_STATUS_WORDS):
                return "open"
            if any(w in body for w in CLOSED_STATUS_WORDS) and "未完了" not in head:
                return "done"
            return "open"
    return None


# タスクの残りを置く節の見出し（「## 派生」「## 残課題」「## フォローアップ」等）。
# 同じ語は実装メモの散文にも現れるため、判定の単位は地の文ではなく見出しにする
# （単位ごとの検出件数の実測はdocs/tasks/T751.md）。
LEFTOVER_HEADING_RE = re.compile(
    r"^#{2,4}\s.*(派生|積み残し|フォローアップ|残課題|残作業|未検討|やり残|次のステップ)")
# その節が「別のタスクへ渡した」「今後もやらない」のどちらかを述べていれば、拾われなくなる
# 残りではない。受け皿の番号はリンク形式でなく素の言及でも数える——番号さえあれば追える。
TASK_MENTION_RE = re.compile(r"T\d{3,4}")
LEFTOVER_SETTLED_RE = re.compile(r"見送り|起票しない|新規タスク化はせず|やらない|対応しない|不要と判断")
MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s")


def newly_closed_task_numbers(base_ref: str | None) -> list[str]:
    """improvement-plan.md の差分で、この差分によって`- [x]`になったタスク番号。

    差分の前から`- [x]`だったものは除く（節の並べ替え・文言修正で行が動いただけの
    完了済みエントリを毎回蒸し返さないため）。
    """
    diff_args = ["diff", "--cached"] if base_ref is None else ["diff", f"{base_ref}..HEAD"]
    was_closed, now_closed = set(), set()
    for line in git(*diff_args, "--", str(IMPROVEMENT_PLAN.relative_to(REPO_ROOT))).splitlines():
        body = line[1:]
        m = TASK_LINK_RE.search(body)
        if not m or "- [x]" not in body:
            continue
        if line.startswith("-") and not line.startswith("---"):
            was_closed.add(m.group(1))
        elif line.startswith("+") and not line.startswith("+++"):
            now_closed.add(m.group(1))
    return sorted(now_closed - was_closed)


def find_unfiled_deferrals(base_ref: str | None) -> list[str]:
    """`[x]`にしたタスクの、残りを置く節が別タスクへ渡されていない箇所。

    `[ ]`→`[x]`の瞬間だけを見る。機械抽出は`- [ ]`行しか見ないため、本文に埋もれた残りが
    以後拾われなくなるのはこの瞬間に確定する。判定は参考出力に留める——節が完了済みの
    フォローアップの記録であることもあり、どちらかは人にしか分からない。
    """
    out = []
    for num in newly_closed_task_numbers(base_ref):
        path = TASKS_DIR / f"T{num}.md"
        if not path.exists():
            continue
        lines = read_text(path).splitlines()
        for i, line in enumerate(lines):
            if not LEFTOVER_HEADING_RE.match(line):
                continue
            j = i + 1
            while j < len(lines) and not MARKDOWN_HEADING_RE.match(lines[j]):
                j += 1
            body = "\n".join(lines[i:j])
            if TASK_MENTION_RE.search(body) or LEFTOVER_SETTLED_RE.search(body):
                continue
            out.append(f"docs/tasks/T{num}.md:{i + 1}: {line.strip()[:90]}")
    return out


GLOBAL_TOKENS_CSS = "frontend/src/app/globals.css"
# `var(--x)`と`var(--x, fallback)`の両方を参照として扱う。フォールバックは未定義を
# 隠すだけで、テーマトークンにフォールバックを付けない規約（docs/frontend-design-system.md）
# にも反する。終端に`,`か`)`を要求することで、`var(--color-*)`というワイルドカード表記や
# `var(--color-${variant})`という実行時合成を参照と誤認しない。
CSS_VAR_REF_RE = re.compile(r"var\(\s*(--[A-Za-z0-9_-]+)\s*[,)]")
CSS_VAR_DEF_RE = re.compile(r"^\s*(--[A-Za-z0-9_-]+)\s*:", re.MULTILINE)
# .ts/.tsxが実行時にelementのstyleへ設定するトークン（トークンそのものだけを引用符で
# 囲んだ文字列リテラル）。CSS側からはこれも定義済みとして扱う。`bg-[var(--color-accent)]`の
# ように長い文字列の一部として現れる参照は、引用符が密着しないためここには入らない。
CSS_VAR_RUNTIME_DEF_RE = re.compile(r"[\"\'](--[A-Za-z0-9_-]+)[\"\']")
# CSS Modulesだけでなく、Tailwindの任意値記法（`bg-[var(--color-accent)]`）でトークンを
# 参照する.ts/.tsxも対象にする。
CSS_TOKEN_SCAN_SUFFIXES = (".css", ".ts", ".tsx")


def css_runtime_defined_tokens(files: list[str]) -> set[str]:
    """.ts/.tsxが実行時に設定するCSSカスタムプロパティ名の集合。"""
    out: set[str] = set()
    for f in files:
        if not f.endswith((".ts", ".tsx")):
            continue
        path = REPO_ROOT / f
        if path.exists():
            out |= set(CSS_VAR_RUNTIME_DEF_RE.findall(read_text(path)))
    return out


def find_undefined_css_tokens(files: list[str], all_files: list[str] | None = None) -> list[str]:
    """定義の無いCSSカスタムプロパティ参照を返す。

    `var(--color-text)`のように規約（`var(--color-*)`を使う）に従った見た目で通ってしまい、
    実際には未定義で継承値へ落ちる。SVGの`fill`だと継承値＝黒に固定され、ダークモードで
    文字が読めなくなる（改善計画T675）。フォールバック付き`var(--x, #fff)`も対象に含める:
    値としては壊れないが、未定義であること自体が隠れたままトークン名の綴り違いが残り、
    同じ役割の色が複数の実効値を持つ状態になる。

    `all_files`は実行時設定トークンを集める母集団（省略時は`files`）。CSS側からは
    定義が見えないため、走査対象が一部（ステージ済みファイル等）でも母集団は全体を渡す。
    """
    tokens_path = REPO_ROOT / GLOBAL_TOKENS_CSS
    if not tokens_path.exists():
        return []
    defined = set(CSS_VAR_DEF_RE.findall(read_text(tokens_path)))
    defined |= css_runtime_defined_tokens(all_files if all_files is not None else files)
    out = []
    for f in files:
        if not f.endswith(CSS_TOKEN_SCAN_SUFFIXES) or f == GLOBAL_TOKENS_CSS:
            continue
        path = REPO_ROOT / f
        if not path.exists():
            continue
        # そのファイル自身が定義するトークン（局所的な計算用）も定義済みとして扱う。
        text = read_text(path)
        local = set(CSS_VAR_DEF_RE.findall(text))
        for lineno, line in enumerate(text.splitlines(), 1):
            for token in CSS_VAR_REF_RE.findall(line):
                if token not in defined and token not in local:
                    out.append(f"{f}:{lineno}: 未定義のCSSトークン `{token}`（定義は{GLOBAL_TOKENS_CSS}）")
    return out


def check_plan_vs_tasks() -> list[str]:
    violations: list[str] = []
    for lineno, line in enumerate(read_text(IMPROVEMENT_PLAN).splitlines(), 1):
        m = PLAN_LINE_RE.match(line)
        if not m:
            continue
        checked, num = m.group(1) == "x", m.group(2)
        task_path = TASKS_DIR / f"T{num}.md"
        if not task_path.exists():
            violations.append(f"docs/improvement-plan.md:{lineno}: docs/tasks/T{num}.md が存在しない")
            continue
        kind = task_status_kind(task_path)
        if kind is None:
            violations.append(
                f"docs/tasks/T{num}.md: 行頭が「状態:」の行が無く[x]/[ ]と照合できない"
                "（`規模S。状態: 完了（…）` のように規模と同じ行へ書くと検出されない）"
            )
        elif checked and kind == "open":
            violations.append(f"docs/improvement-plan.md:{lineno}: T{num} は [x] だが docs/tasks/T{num}.md の「状態:」行は未完了のまま")
        elif not checked and kind == "done":
            violations.append(f"docs/improvement-plan.md:{lineno}: T{num} は [ ] だが docs/tasks/T{num}.md の「状態:」行は完了")
    return violations


# --- テストの空振り（絞り込んだ母集団が空でも通るループ） ---------------------
#
# 母集団が0件のとき、要素ごとのアサーションは1回も走らずテストは緑になる。緑であることが
# 「検査した」の証拠にならないため、母集団が空でないことを同じテストの中で確かめる。

TEST_FILE_RE = re.compile(r"(^|/)(test_[\w]+\.py|[\w.-]+\.test\.tsx?)$")
PY_FOR_RE = re.compile(r"^(\s*)for\s+[\w, ()]+\s+in\s+(.+?):\s*(#.*)?$")
TS_FOR_RE = re.compile(r"^(\s*)for\s+\(const\s+[\w, {}\[\]]+\s+of\s+(.+?)\)\s*\{\s*$")
# 「絞り込みを経て作られた」ことの印。空になりうる母集団はここから生まれる。
NARROWING_RE = re.compile(r"\.filter\(|\bfilter\(|\bif\b[^\n]*\bfor\b|\bfor\b[^\n]*\bif\b")
PY_TEST_DEF_RE = re.compile(r"^\s*(async\s+)?def\s+test_\w+")
TS_TEST_DEF_RE = re.compile(r"^\s*(it|test)(\.\w+)?\(")
ASSERTION_RE = re.compile(r"\bassert\b|expect\(")


def _nonempty_assertion_re(name: str) -> re.Pattern[str]:
    """`name`が空でないことを主張しているアサーションの形。"""
    n = re.escape(name)
    return re.compile(
        rf"assert\s+len\(\s*{n}\s*\)\s*(>\s*0|>=\s*1|[!=]=\s*[1-9])"
        rf"|assert\s+{n}\s*(,|$)"
        # vitestの`expect(値, "失敗時の説明")`第2引数も許す。
        rf"|expect\(\s*{n}\s*(,[^)]*)?\)\s*\.\s*not\s*\.\s*toHaveLength\(\s*0\s*\)"
        rf"|expect\(\s*{n}\s*(,[^)]*)?\)\s*\.\s*toHaveLength\(\s*[1-9]"
        rf"|expect\(\s*{n}\s*\.\s*length\s*(,[^)]*)?\)\s*\.\s*(toBeGreaterThan\(\s*0\s*\)|toBe\(\s*[1-9])"
    )


def _enclosing_test_block(lines: list[str], index: int) -> str:
    """`index`行を含むテスト1件ぶんの本文。見つからなければファイル全体。"""
    start = 0
    for i in range(index, -1, -1):
        if PY_TEST_DEF_RE.match(lines[i]) or TS_TEST_DEF_RE.match(lines[i]):
            start = i
            break
    else:
        return "\n".join(lines)
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = len(lines)
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped and len(lines[i]) - len(lines[i].lstrip()) <= indent:
            end = i
            break
    return "\n".join(lines[start:end])


def _binding_text(lines: list[str], index: int, name: str) -> str:
    """`index`より前にある`name`の代入の右辺。括弧が閉じるまでを1つの式として読む。"""
    pattern = re.compile(rf"^\s*(?:const|let|var)?\s*{re.escape(name)}\s*(?::[^=]+)?=\s*(.*)$")
    for i in range(index - 1, -1, -1):
        m = pattern.match(lines[i])
        if m is None:
            continue
        parts = [m.group(1)]

        def delta(s: str) -> int:
            return sum(s.count(c) for c in "([{") - sum(s.count(c) for c in ")]}")

        depth = delta(m.group(1))
        j = i + 1
        # 括弧が閉じていない間と、`.filter(...)`のように次の行がメソッド鎖の続きである間は
        # 同じ式として読む（鎖の継続は括弧では区切られない）。
        while j < index and (depth > 0 or lines[j].lstrip().startswith(".")):
            parts.append(lines[j])
            depth += delta(lines[j])
            j += 1
        return "\n".join(parts)
    return ""


def blank_multiline_literals(lines: list[str]) -> list[str]:
    """複数行の文字列リテラル（三連引用符・テンプレートリテラル）の中身を空行へ潰す。

    検知器自身のテストは「違反の例」をコード片の文字列として持つ。実行されないコード片を
    実物と区別できないと、検知器を試すテストを書くたびに自分自身が鳴る。行番号を保つため
    行数は変えない。
    """
    out, fence = [], None
    for line in lines:
        if fence is not None:
            out.append("")
            if fence in line:
                fence = None
            continue
        kept = ""
        rest = line
        while True:
            m = re.search(r'("""|\'\'\'|`)', rest)
            if m is None:
                kept += rest
                break
            kept += rest[: m.start()]
            quote = m.group(1)
            after = rest[m.end():]
            close = after.find(quote)
            if close < 0:  # 行内で閉じない＝次の行へ続く
                fence = quote
                break
            rest = after[close + len(quote):]  # 行内で閉じたリテラルを落として続行
        out.append(kept)
    return out


def find_vacuous_test_loops(test_files: list[str], revision: str | None = None) -> list[str]:
    """絞り込んだ母集団をループして検査するのに、空でないことを確かめていない箇所。

    ループとその直前の束縛・同じテスト内のアサーションを合わせて読む必要があるため、
    差分の追加行ではなくファイル1本を丸ごと見る。`revision`はその中身の出所
    （`""`=インデックス、`"HEAD"`、None=作業ツリー。doc_text_atと同じ契約）。
    """
    out: list[str] = []
    for f in sorted(set(test_files)):
        if not TEST_FILE_RE.search(f):
            continue
        text = doc_text_at(f, revision)
        if not text:
            continue
        lines = blank_multiline_literals(text.splitlines())
        for i, line in enumerate(lines):
            m = PY_FOR_RE.match(line) or TS_FOR_RE.match(line)
            if m is None:
                continue
            indent, iterable = m.group(1), m.group(2).strip()
            body = []
            for j in range(i + 1, len(lines)):
                if lines[j].strip() and not lines[j].startswith((indent + " ", indent + "\t")):
                    break
                body.append(lines[j])
            if not ASSERTION_RE.search("\n".join(body)):
                continue
            # `.items()`/`.values()`等の取り出しは母集団の大きさを変えないので剥がす。
            plain = re.sub(r"\.(items|values|keys|entries)\(\)\s*$", "", iterable)
            name = plain if re.fullmatch(r"[A-Za-z_]\w*", plain) else None
            if not NARROWING_RE.search(iterable):
                if name is None or not NARROWING_RE.search(_binding_text(lines, i, name)):
                    continue
            else:
                # その場で絞り込む書き方は、空でないことを主張する相手（名前）を持たない。
                # 一度変数へ束ねてから確かめる形にする必要がある。
                name = None
            block = _enclosing_test_block(lines, i)
            if name and _nonempty_assertion_re(name).search(block):
                continue
            shown = iterable if len(iterable) <= 60 else iterable[:57] + "..."
            out.append(f"{f}:{i + 1}: 絞り込んだ母集団 `{shown}` が空でも通る（空でないことを同じテストで確かめる）")
    return out


def check_dead_doc_links(md_files: list[str]) -> list[str]:
    out = []
    existing_history = {p.name for p in HISTORY_DIR.glob("*.md")}
    existing_tasks = {p.name for p in TASKS_DIR.glob("*.md")}
    for f in md_files:
        p = REPO_ROOT / f
        # history/ 配下は当時の記録（書き換えない）のため対象外
        if not p.exists() or f.startswith(".claude/commands/review/history/"):
            continue
        for lineno, line in enumerate(read_text(p).splitlines(), 1):
            for name in HISTORY_REF_RE.findall(line):
                if name not in existing_history and name not in KNOWN_MISSING_HISTORY:
                    out.append(f"{f}:{lineno}: history/{name} が存在しない")
            for n in TASK_FILE_MENTION_RE.findall(line):
                if f"T{n}.md" not in existing_tasks:
                    out.append(f"{f}:{lineno}: docs/tasks/T{n}.md が存在しない")
    return out


def diff_added_lines(pathspec: str, base_ref: str | None = None) -> dict[str, list[tuple[int, str]]]:
    """追加行を {ファイル: [(行番号, 行)]} で返す。

    base_ref省略時は `git diff --cached`（pre-commit用、ステージ済み変更）。
    base_ref指定時は `git diff base_ref..HEAD`（CI用、そのref以降にHEADへ積まれた変更）。
    """
    diff_args = ["diff", "--cached", "-U0"] if base_ref is None else ["diff", f"{base_ref}..HEAD", "-U0"]
    out: dict[str, list[tuple[int, str]]] = defaultdict(list)
    current, lineno = None, 0
    for line in git(*diff_args, "--", pathspec).splitlines():
        if line.startswith("+++ "):
            current = line[4:].removeprefix("b/")
        elif line.startswith("@@"):
            m = re.search(r"\+(\d+)", line)
            lineno = int(m.group(1)) if m else 0
        elif line.startswith("+") and not line.startswith("+++") and current:
            out[current].append((lineno, line[1:]))
            lineno += 1
    return out


def gather_added_source_lines(base_ref: str | None) -> dict[str, list[tuple[int, str]]]:
    """SOURCE_COMMENT_PATHSPECS全体の追加行を集め、is_impl_file（テスト等を除外）で絞る。"""
    out: dict[str, list[tuple[int, str]]] = {}
    for spec in SOURCE_COMMENT_PATHSPECS:
        for path, lines in diff_added_lines(spec, base_ref).items():
            if is_impl_file(path):
                out[path] = lines
    return out


# 検知器ごとに、どの実行経路で「違反」として数える（exit codeへ入れる）か。
#
# `--staged`（pre-commitフック）と`--since`（CIのdocs-consistency.yml）は**同じ集合**を
# 強制しなければならない。片側にしか無い検知器は「ローカルでは止まるのにCIでは素通り」に
# なり、フックを手動インストールしていないセッション・コンテナからは無検査で入る。
# この一致は`scripts/tests/test_review_checks.py`が固定し、実際の配線漏れは下の
# `cmd_docs`が実行時に自己申告する（表に足しただけで各分岐へ繋いでいない場合に落ちる）。
#
# `full`（範囲指定なしの全件スキャン）だけは既存分が残る検知器を参考表示に留める。
DETECTOR_ENFORCEMENT: dict[str, frozenset[str]] = {
    "dead_file_refs": frozenset({"staged", "since", "full"}),
    "dead_identifier_refs": frozenset({"staged", "since", "full"}),
    "narrative": frozenset({"staged", "since", "full"}),
    # 既存分の一掃（T567）が終わるまで、全件スキャンでは参考表示に留める。
    "source_narrative": frozenset({"staged", "since"}),
    "redis_skeleton": frozenset({"staged", "since", "full"}),
    "bare_basemodel": frozenset({"staged", "since", "full"}),
    "undeclared_dead_refs": frozenset({"staged", "since", "full"}),
    # 免除した段落の中身は常に参考表示（0件で黙らないためのもので、ブロックはしない）。
    "undeclared_dead_refs_exempted": frozenset(),
    "undocumented_files": frozenset({"staged", "since", "full"}),
    "plan_vs_tasks": frozenset({"staged", "since", "full"}),
    "dead_doc_links": frozenset({"staged", "since", "full"}),
    "undefined_css_tokens": frozenset({"staged", "since", "full"}),
    "vacuous_test_loops": frozenset({"staged", "since", "full"}),
    # 参考表示のみ（README「記載粒度」節は1リンクまで許可）。
    "task_links": frozenset(),
    # 参考表示のみ。節が完了済みフォローアップの記録であることもあり、残りかどうかは
    # 人にしか分からない（docs/tasks/T751.md）。[x]化の瞬間に目へ入れるのが目的。
    "unfiled_deferrals": frozenset(),
}


def unwired_detectors(mode: str, wired: set[str]) -> list[str]:
    """`mode`で強制すると宣言されているのに、その経路へ繋がれていない検知器。

    表へ足しただけ・分岐から外しただけでは件数0のまま静かに素通りするため、
    表と配線のずれ自体を違反として扱う。
    """
    return sorted(k for k, modes in DETECTOR_ENFORCEMENT.items() if mode in modes and k not in wired)


def cmd_docs(args: argparse.Namespace) -> int:
    files = git_files()
    all_docs = module_docs()
    modules_text = "\n".join(read_text(p) for p in all_docs)
    mode = "staged" if args.staged else ("since" if args.since else "full")
    sections: list[tuple[str, str, list[str]]] = []  # (検知器キー, 見出し, 行)

    if args.staged:
        staged = [l for l in git("diff", "--cached", "--name-only").splitlines() if l]
        doc_lines = diff_added_lines("docs/modules/*.md")
        doc_lines = {k: v for k, v in doc_lines.items() if not k.endswith("README.md")}
        added = [l for l in git("diff", "--cached", "--name-only", "--diff-filter=A").splitlines() if l]
        sections.append(("dead_file_refs", "docs/modules の死んだ参照（ステージ済み追加行）",
                         find_dead_file_refs(doc_lines, files + added)))
        sections.append(("dead_identifier_refs", "docs/modules の死んだ識別子参照（ステージ済み追加行）",
                         find_dead_identifier_refs(doc_lines, source_corpus(files + added))))
        sections.append(("narrative", "docs/modules の記載粒度違反（ステージ済み追加行）",
                         find_narrative_violations(doc_lines)))
        source_lines = gather_added_source_lines(None)
        sections.append(("source_narrative", "ソースコードの経緯コメント（ステージ済み追加行、docs/comments.md参照）",
                         find_source_narrative_violations(source_lines)))
        sections.append(("redis_skeleton", "Redis骨格の自前実装（ステージ済み追加行、docs/caching.md参照）",
                         find_redis_skeleton_violations(source_lines)))
        sections.append(("bare_basemodel", "素のBaseModel継承（ステージ済み追加行、docs/tasks/T721.md参照）",
                         find_bare_basemodel_violations(source_lines)))
        arch_lines = diff_added_lines(ARCHITECTURE_DOC)
        sections.append(("undeclared_dead_refs", "architecture.md が撤去済みの名前を断りなく名指し（ステージ済み追加行）",
                         find_undeclared_dead_refs(arch_lines, files + added, source_corpus(files + added), revision="")))
        sections.append((
            "undeclared_dead_refs_exempted",
            "architecture.md の免除した段落の中に残る実在しない名前（参考、ステージ済み追加行）",
            find_dead_refs_inside_exempted_paragraphs(
                arch_lines, files + added, source_corpus(files + added), revision="")))
        sections.append(("undocumented_files", "新規実装ファイルの docs/modules 記載漏れ（ステージ済み新規ファイル）",
                         find_undocumented_files(added, modules_text, files + added)))
        sections.append(("plan_vs_tasks", "improvement-plan.md [x]/[ ] と docs/tasks「状態:」の不一致",
                         check_plan_vs_tasks()))
        sections.append(("unfiled_deferrals", "[x]化したタスクの、別タスクへ渡していない残り（参考、人が判断する）",
                         find_unfiled_deferrals(None)))
        md_staged = [s for s in staged if s.endswith(".md")]
        sections.append(("dead_doc_links", "history/・docs/tasks への死んだリンク（ステージ済み.md）",
                         check_dead_doc_links(md_staged)))
        sections.append(("undefined_css_tokens", "未定義のCSSトークン（ステージ済み.css/.ts/.tsx）",
                         find_undefined_css_tokens(
                             [s for s in staged if s.endswith(CSS_TOKEN_SCAN_SUFFIXES)], files + added)))
        sections.append(("vacuous_test_loops", "空の母集団でも通るテストのループ（ステージ済みテスト）",
                         find_vacuous_test_loops(staged + added, revision="")))
    else:
        doc_lines = {rel(p): list(enumerate(read_text(p).splitlines(), 1)) for p in all_docs}
        sections.append(("dead_file_refs", "docs/modules の死んだ参照（全件）", find_dead_file_refs(doc_lines, files)))
        sections.append(("dead_identifier_refs", "docs/modules の死んだ識別子参照（全件）",
                         find_dead_identifier_refs(doc_lines, source_corpus(files))))
        sections.append(("narrative", "docs/modules の記載粒度違反（全件）", find_narrative_violations(doc_lines)))
        sections.append(("task_links", "docs/modules の Txxx リンク（参考、README「記載粒度」節は1リンクまで許可）",
                         count_task_links(doc_lines)))
        arch_path = REPO_ROOT / ARCHITECTURE_DOC
        if args.since:
            added = [l for l in git("diff", "--diff-filter=A", "--name-only", f"{args.since}..HEAD").splitlines() if l]
            title = f"新規実装ファイルの docs/modules 記載漏れ（{args.since} 以降の新規ファイル）"
            # 経緯コメント・architecture.mdの断りなき名指しはいずれも既存分が残る
            # （T567・T724）。--sinceで新規追加分だけに絞れる場合のみ違反件数へ含める。
            source_lines = gather_added_source_lines(args.since)
            sections.append((
                "source_narrative",
                f"ソースコードの経緯コメント（{args.since} 以降の追加行、docs/comments.md参照）",
                find_source_narrative_violations(source_lines)))
            arch_since = diff_added_lines(ARCHITECTURE_DOC, args.since)
            sections.append((
                "undeclared_dead_refs",
                f"architecture.md が撤去済みの名前を断りなく名指し（{args.since} 以降の追加行）",
                find_undeclared_dead_refs(arch_since, files, source_corpus(files), revision="HEAD")))
            sections.append((
                "undeclared_dead_refs_exempted",
                f"architecture.md の免除した段落の中に残る実在しない名前（参考、{args.since} 以降の追加行）",
                find_dead_refs_inside_exempted_paragraphs(arch_since, files, source_corpus(files), revision="HEAD")))
        else:
            added = files
            title = "実装ファイルの docs/modules 記載漏れ（全件）"
            all_source_lines = {
                rel(p): list(enumerate(read_text(p).splitlines(), 1))
                for p in (REPO_ROOT / f for f in files if is_impl_file(f))
                if p.exists()
            }
            source_lines = all_source_lines
            sections.append(("source_narrative", "ソースコードの経緯コメント（参考、全件。新規分の強制は--staged/--since参照）",
                             find_source_narrative_violations(all_source_lines)))
            arch_all = {ARCHITECTURE_DOC: list(enumerate(read_text(arch_path).splitlines(), 1))}
            sections.append((
                "undeclared_dead_refs",
                "architecture.md が撤去済みの名前を断りなく名指し（全件）",
                find_undeclared_dead_refs(arch_all, files, source_corpus(files))))
            sections.append((
                "undeclared_dead_refs_exempted",
                "architecture.md の免除した段落の中に残る実在しない名前（参考、全件）",
                find_dead_refs_inside_exempted_paragraphs(arch_all, files, source_corpus(files))))
        sections.append(("undocumented_files", title, find_undocumented_files(added, modules_text, files)))
        sections.append(("redis_skeleton", "Redis骨格の自前実装（docs/caching.md参照）",
                         find_redis_skeleton_violations(source_lines)))
        sections.append(("bare_basemodel", "素のBaseModel継承（全件、docs/tasks/T721.md参照）",
                         find_bare_basemodel_violations({
                             rel(p): list(enumerate(read_text(p).splitlines(), 1))
                             for p in (REPO_ROOT / f for f in files if f.startswith("backend/app/"))
                             if p.exists()
                         })))
        sections.append(("plan_vs_tasks", "improvement-plan.md [x]/[ ] と docs/tasks「状態:」の不一致",
                         check_plan_vs_tasks()))
        if args.since:
            sections.append((
                "unfiled_deferrals",
                f"[x]化したタスクの、別タスクへ渡していない残り（{args.since} 以降、参考、人が判断する）",
                find_unfiled_deferrals(args.since)))
        md_files = [f for f in files if f.endswith(".md") and (f.startswith((".claude/", "docs/")) or f == "CLAUDE.md")]
        sections.append(("dead_doc_links", "history/・docs/tasks への死んだリンク（.claude・docs 全件）",
                         check_dead_doc_links(md_files)))
        sections.append(("undefined_css_tokens", "未定義のCSSトークン（全件）", find_undefined_css_tokens(files, files)))
        if args.since:
            changed = [l for l in git("diff", "--name-only", f"{args.since}..HEAD").splitlines() if l]
            sections.append((
                "vacuous_test_loops",
                f"空の母集団でも通るテストのループ（{args.since} 以降に変更されたテスト）",
                find_vacuous_test_loops(changed, revision="HEAD")))
        else:
            sections.append(("vacuous_test_loops", "空の母集団でも通るテストのループ（全件）",
                             find_vacuous_test_loops(files)))

    total = 0
    for key, title, lines in sections:
        counts = mode in DETECTOR_ENFORCEMENT[key]
        mark = f"{len(lines)}件" if lines else "0件"
        # `--keys`は検知器キーを見出しへ出す（`mutate`が節と検知器を機械的に対応づけるため）。
        label = f"[{key}] {title}" if args.keys else title
        print(f"## {label}: {mark}")
        for l in lines:
            print(f"  - {l}")
        if counts:
            total += len(lines)
    print()

    # 表で「この経路で強制する」と宣言した検知器が、実際にこの分岐へ繋がれているか。
    # 繋ぎ忘れると件数0のまま静かに素通りするため、表と配線のずれ自体を違反として扱う。
    unwired = unwired_detectors(mode, {key for key, _, _ in sections})
    if unwired:
        print(f"## 配線されていない検知器（{mode}）: {', '.join(unwired)}")
        print("DETECTOR_ENFORCEMENTが強制すると宣言しているが、この経路のsectionsへ繋がれていない。")
        return 1

    if total:
        print(f"違反 {total}件（docs/modules/README.md「記載粒度」節・consistency.md「設計 ↔ 実装」節を参照して是正）")
        return 1
    print("違反なし")
    return 0


# --- size -------------------------------------------------------------------

def cmd_size(args: argparse.Namespace) -> int:
    files = git_files()
    counts = {f: count_lines(REPO_ROOT / f) for f in files if is_impl_file(f) and (REPO_ROOT / f).exists()}
    arch = "docs/architecture.md"
    if (REPO_ROOT / arch).exists():
        counts[arch] = count_lines(REPO_ROOT / arch)
    baseline = json.loads(read_text(SIZE_BASELINE)) if SIZE_BASELINE.exists() else {}
    prev: dict[str, int] = baseline.get("files", {})
    thresholds: dict[str, int] = baseline.get("thresholds", {})
    top_n = args.top
    groups = {
        "backend": sorted((f for f in counts if f.startswith("backend/")), key=lambda f: -counts[f])[:top_n],
        "frontend": sorted((f for f in counts if f.startswith("frontend/")), key=lambda f: -counts[f])[:top_n],
        "docs": [arch] if arch in counts else [],
    }
    watched = sorted(set(sum(groups.values(), [])) | set(thresholds) | set(prev), key=lambda f: -counts.get(f, 0))
    prev_top = set(baseline.get("top", []))
    cur_top = set(sum(groups.values(), []))

    print(f"## 規模ウォッチ表（対象 {git('rev-parse', '--short', 'HEAD').strip()}、"
          f"前回 {baseline.get('commit', '記録なし')} / {baseline.get('date', '-')}）")
    print("| ファイル | 今回 | 前回 | 増分 | 閾値 | 発火 |")
    print("|---|---:|---:|---:|---:|---|")
    fired = []
    for f in watched:
        cur = counts.get(f)
        if cur is None:
            print(f"| {f} | 削除済み | {prev.get(f, '-')} | - | - | - |")
            continue
        p = prev.get(f)
        delta = f"{cur - p:+d}" if p is not None else "新規"
        reasons = []
        if p is not None and p > 0 and (cur - p) / p >= 0.15:
            reasons.append(f"+{(cur - p) / p * 100:.0f}%")
        if p is not None and p < 1000 <= cur:
            reasons.append("1,000行超過")
        if f in cur_top and f not in prev_top and prev_top:
            reasons.append("上位に新規登場")
        th = thresholds.get(f)
        if th and cur >= th:
            reasons.append(f"Keep List閾値{th:,}超過")
        if reasons:
            fired.append(f)
        print(f"| {f} | {cur:,} | {p if p is not None else '-'} | {delta} | {th if th else '-'} | {'・'.join(reasons)} |")
    print()
    print(f"発火 {len(fired)}件: " + (", ".join(fired) if fired else "なし")
          + "（発火したファイルは complexity.md「規模ウォッチ」節に従い KEEP/分割/閾値付きKEEP へ分類する）")

    if args.update:
        new = {
            "date": dt.date.today().isoformat(),
            "commit": git("rev-parse", "--short", "HEAD").strip(),
            "top": sorted(cur_top),
            "files": {f: counts[f] for f in watched if f in counts},
            "thresholds": thresholds,
        }
        SIZE_BASELINE.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"前回値ファイルを更新: {rel(SIZE_BASELINE)}")
    return 0


# --- metrics ----------------------------------------------------------------

def venv_python() -> str | None:
    for cand in (REPO_ROOT / "backend/.venv/Scripts/python.exe", REPO_ROOT / "backend/.venv/bin/python"):
        if cand.exists():
            return str(cand)
    return None


def npx() -> str | None:
    return shutil.which("npx.cmd") or shutil.which("npx")


def npx_cli_path(npm: str) -> Path | None:
    """npm同梱の`npx-cli.js`の実体。

    `shutil.which("npm")`が返すのはPATH上のシンボリックリンク（POSIX）かシム
    （Windows）で、OSによってその先の並びが違う。**パスを組み立てて当てにいかず、
    候補を順に確かめて実在するものを返す**——POSIXでリンクを解決するとnpm本体の
    `bin/npm-cli.js`そのものになるため、そこから改めて`node_modules/npm/bin`を足すと
    二重になる（存在しないパスになり、コピペ検出が常にスキップされる）。
    """
    resolved = Path(npm).resolve()
    candidates = [
        # npm本体のbin/（POSIXでリンクを解決した後。npx-cli.jsはnpm-cli.jsの隣にある）
        resolved.parent / "npx-cli.js",
        # シムの隣にnode_modulesがある並び（Windowsのnpm同梱シム等）
        resolved.parent / "node_modules" / "npm" / "bin" / "npx-cli.js",
    ]
    return next((c for c in candidates if c.exists()), None)


def latest_history_date(kind: str | None = None) -> dt.date | None:
    dates = []
    for p in HISTORY_DIR.glob("*.md"):
        m = re.match(r"(\d{4}-\d{2}-\d{2})_([A-Za-z0-9\-]+)\.md$", p.name)
        if m and (kind is None or m.group(2) == kind):
            dates.append(dt.date.fromisoformat(m.group(1)))
    return max(dates) if dates else None


def cmd_metrics(args: argparse.Namespace) -> int:
    since = args.since or (latest_history_date("metrics") or latest_history_date())
    print(f"# 定量メトリクス（{dt.date.today().isoformat()}、対象 {git('rev-parse', '--short', 'HEAD').strip()}、"
          f"churn起点 {since}）\n")

    # 1. 規模
    print("## 1. 規模")
    impl = {f: count_lines(REPO_ROOT / f) for f in git_files() if is_impl_file(f) and (REPO_ROOT / f).exists()}
    tests = {
        f: count_lines(REPO_ROOT / f) for f in git_files()
        if (REPO_ROOT / f).exists() and (
            f.startswith("backend/tests/") and f.endswith(".py")
            or (f.startswith(("frontend/src/", "frontend/e2e/")) and re.search(r"\.(test|spec)\.tsx?$", f))
        )
    }
    b_impl = sum(v for f, v in impl.items() if f.startswith("backend/"))
    f_impl = sum(v for f, v in impl.items() if f.startswith("frontend/"))
    b_test = sum(v for f, v in tests.items() if f.startswith("backend/"))
    f_test = sum(v for f, v in tests.items() if f.startswith("frontend/"))
    print(f"- 実装本体（行、空行・コメント込み）: backend/app {b_impl:,}・frontend/src {f_impl:,}・合計 {b_impl + f_impl:,}")
    print(f"- テスト（行）: backend/tests {b_test:,}・frontend {f_test:,}・合計 {b_test + f_test:,}")
    print(f"- 実装本体:テスト比 = 1 : {(b_test + f_test) / max(1, b_impl + f_impl):.2f}")
    print(f"- ファイル数: 実装 backend {sum(f.startswith('backend/') for f in impl)}・frontend "
          f"{sum(f.startswith('frontend/') for f in impl)}／テスト backend "
          f"{sum(f.startswith('backend/') for f in tests)}・frontend {sum(f.startswith('frontend/') for f in tests)}")
    if args.full and npx():
        print("- cloc:")
        out = run([npx(), "--yes", "cloc", ".", "--quiet",
                   "--exclude-dir=node_modules,.venv,venv,.next,dist,build,.git,coverage,.pytest_cache,__pycache__,.turbo,htmlcov",
                   "--exclude-ext=json,lock,svg,png,jpg,jpeg,ico,pbf,mbtiles,parquet"], check=False)
        print("```\n" + out.strip() + "\n```")

    # 2. churn
    print("\n## 2. 変更頻度（churn）")
    log = git("log", f"--since={since}", "--name-only", "--pretty=format:")
    commits = git("log", f"--since={since}", "--oneline").count("\n")
    names = [l for l in log.splitlines() if l]
    freq = defaultdict(int)
    for n in names:
        freq[n] += 1
    print(f"- コミット数: {commits}／変更ファイル数（ユニーク）: {len(freq)}")
    print("- 上位10: " + "、".join(f"`{f}` {c}" for f, c in sorted(freq.items(), key=lambda x: -x[1])[:10]))

    # 3〜5（重い項目は --full のみ）
    if args.full:
        print("\n## 3. テスト規模")
        py = venv_python()
        if py:
            out = run([py, "-m", "pytest", "-q", "-m", "not postgis", "--collect-only"], cwd=REPO_ROOT / "backend", check=False)
            tail = [l for l in out.splitlines() if "selected" in l or "deselected" in l or "tests collected" in l]
            print("- backend pytest --collect-only: " + (tail[-1] if tail else out.strip().splitlines()[-1:] or "取得失敗"))
        if npx() and (REPO_ROOT / "frontend/node_modules").exists():
            out = run([npx(), "vitest", "list"], cwd=REPO_ROOT / "frontend", check=False)
            print(f"- frontend vitest list: {sum(1 for l in out.splitlines() if l.strip())}件")
        print("\n## 4. 静的検査")
        if npx() and (REPO_ROOT / "frontend/node_modules").exists():
            out = run([npx(), "tsc", "--noEmit"], cwd=REPO_ROOT / "frontend", check=False)
            print(f"- tsc --noEmit: {sum(1 for l in out.splitlines() if 'error TS' in l)}エラー")
            out = run([npx(), "eslint", "."], cwd=REPO_ROOT / "frontend", check=False)
            summary = [l for l in out.splitlines() if "problem" in l]
            print(f"- eslint: {summary[-1].strip() if summary else '0 problems'}")
        print("\n## 5. 依存関係")
        npm = shutil.which("npm.cmd") or shutil.which("npm")
        if npm:
            out = run([npm, "audit", "--json"], cwd=REPO_ROOT / "frontend", check=False)
            try:
                v = json.loads(out)["metadata"]["vulnerabilities"]
                print(f"- npm audit: critical {v.get('critical', 0)} / high {v.get('high', 0)} / "
                      f"moderate {v.get('moderate', 0)} / low {v.get('low', 0)}")
            except (ValueError, KeyError):
                print("- npm audit: 取得失敗")
    else:
        print("\n（テスト件数・tsc/eslint・npm audit は --full で計測）")
    return 0


# --- trigger ----------------------------------------------------------------

TRIGGER_DAYS = 14
TRIGGER_IMPL_LINES = 20_000


def latest_target_commit() -> tuple[str | None, str | None]:
    """history/ の直近 all/consistency/overall ファイルから対象コミットSHAを取る。"""
    cands = []
    for p in HISTORY_DIR.glob("*.md"):
        m = re.match(r"(\d{4}-\d{2}-\d{2})_(all|consistency|overall)\.md$", p.name)
        if m:
            cands.append((m.group(1), p))
    for _, p in sorted(cands, reverse=True):
        for line in read_text(p).splitlines()[:40]:
            if "対象コミット" in line:
                m = re.search(r"`([0-9a-f]{7,40})`", line)
                if m:
                    return m.group(1), p.name
    return None, None


def cmd_trigger(args: argparse.Namespace) -> int:
    today = dt.date.today()
    last = latest_history_date()
    days = (today - last).days if last else None
    sha, src = latest_target_commit()
    lines = None
    if sha and git("cat-file", "-t", sha, check=False).strip() == "commit":
        stat = git("diff", "--shortstat", f"{sha}..HEAD", "--",
                   "backend/app", "frontend/src", ":!frontend/src/**/*.test.*", ":!frontend/src/**/*.spec.*",
                   ":!frontend/src/types/generated", check=False)
        nums = [int(x) for x in re.findall(r"(\d+) (?:insertion|deletion)", stat)]
        lines = sum(nums)
    fired = []
    print("## 周期レビュー トリガー判定")
    print(f"- 前回レビュー（history/ 最新日付）: {last}（{days}日経過、閾値 {TRIGGER_DAYS}日）")
    if days is not None and days >= TRIGGER_DAYS:
        fired.append("日数")
    if lines is not None:
        print(f"- 実装コード（テスト・生成物除く）の変更行数（{sha[:7]}..HEAD、{src} の対象コミット起点）: "
              f"{lines:,}行（閾値 {TRIGGER_IMPL_LINES:,}）")
        if lines >= TRIGGER_IMPL_LINES:
            fired.append("変更行数")
    else:
        print("- 変更行数: 直近レビューの対象コミットを特定できず未計測")
    print("- 分割元タスク（複数のTxxxへ分割する規模Lのタスク）の完了直後かは自動判定できない。該当すれば量に関係なく実施する")
    print()
    print("判定: " + (f"**該当（{'・'.join(fired)}）** → /review:all（最低限 /review:consistency）を実施する" if fired
                   else "未該当"))
    return 0


# --- duplication ------------------------------------------------------------

# jscpdへ渡す検出条件。小さすぎるとimport列・定型のガード節が大量に引っかかるため、
# 「意味のあるまとまりが写された」と言える下限にする。
JSCPD_MIN_LINES = 5
JSCPD_MIN_TOKENS = 60
JSCPD_IGNORE = ",".join([
    "**/node_modules/**", "**/types/generated/**", "**/__pycache__/**", "**/.next/**",
])
# テスト・スクリプトも対象に含める。実装だけを見ていると、同じ骨格がテスト側へ写された
# ぶんを見落とす（外部APIクライアント・Redisキャッシュのテストが実際にそうなっている）。
JSCPD_TARGETS = ["backend/app", "backend/tests", "backend/scripts", "frontend/src", "scripts"]


def cmd_duplication(args: argparse.Namespace) -> int:
    """コピペ検出（jscpd）。前回値との差分を見て「新しい写経が増えたか」を判定する。

    **これで捕まるのは完全一致のクローンだけ**である。「同じ決まりごとが各所で少しずつ
    違う形に書かれている」型（設定値の直書き・組み立て規則の手書き）は原理的に検出
    できないため、これだけを根拠に「写経は無い」と結論してはならない
    （docs/tasks/T648.md参照）。
    """
    out_dir = REPO_ROOT / ".jscpd-report"
    # Windowsのnpxはバッチファイル（npx.cmd）で、shell=Falseのsubprocessからは起動できない
    # （WinError 193）。npm同梱のnpx-cli.jsをnodeで直接実行して、OS差を吸収する。
    node = shutil.which("node")
    npm = shutil.which("npm")
    if node is None or npm is None:
        print("## コピペ検出: スキップしました（node/npmが見つかりません）")
        return 0
    npx_cli = npx_cli_path(npm)
    if npx_cli is None:
        print(f"## コピペ検出: スキップしました（npx-cli.jsが見つかりません: npm={npm}）")
        return 0
    cmd = [
        node, str(npx_cli), "--yes", "jscpd@4",
        "--min-lines", str(JSCPD_MIN_LINES), "--min-tokens", str(JSCPD_MIN_TOKENS),
        "--reporters", "json", "--output", str(out_dir), "--silent",
        "--ignore", JSCPD_IGNORE, *JSCPD_TARGETS,
    ]
    try:
        run(cmd, check=False, timeout=900)
    except (FileNotFoundError, RuntimeError, subprocess.TimeoutExpired) as exc:
        # npx未導入・ネットワーク不通の環境ではスキップする（pre-commit-api-contractが
        # backend/.venv未検出時にスキップするのと同じ扱い）。
        print(f"## コピペ検出: スキップしました（jscpdを実行できません: {exc}）")
        return 0
    report = out_dir / "jscpd-report.json"
    if not report.exists():
        print("## コピペ検出: スキップしました（jscpdのレポートが生成されませんでした）")
        return 0
    data = json.loads(read_text(report))
    stats = data.get("statistics", {}).get("total", {})
    all_duplicates = data.get("duplicates", [])
    # 同一ファイル内の重複は数えない。写経とは「同じ理由で変わるものが分かれて書かれている」
    # ことであり、1ファイル内に似たテストケースやアイコン定義が並ぶのはそれに当たらない
    # （むしろ1件ずつ独立して読める方がよい）。ファイルをまたぐものだけを監視する。
    duplicates = [d for d in all_duplicates if d["firstFile"]["name"] != d["secondFile"]["name"]]
    within_file = len(all_duplicates) - len(duplicates)
    duplicated_lines = sum(d["lines"] for d in duplicates)
    total_lines = stats.get("lines", 0)
    percentage = round(100 * duplicated_lines / total_lines, 2) if total_lines else 0.0

    baseline = json.loads(read_text(DUPLICATION_BASELINE)) if DUPLICATION_BASELINE.exists() else {}
    prev_clones = baseline.get("clones")

    print(f"## コピペ検出（jscpd、min-lines={JSCPD_MIN_LINES} min-tokens={JSCPD_MIN_TOKENS}）")
    print(f"- 対象: {' / '.join(JSCPD_TARGETS)}（テスト・スクリプトを含む）")
    print(f"- ファイルをまたぐクローン: {len(duplicates)}件"
          + (f"（前回 {prev_clones}件 / {baseline.get('date', '-')}）" if prev_clones is not None else "（前回記録なし）"))
    print(f"- 重複行: {duplicated_lines}行 / {total_lines}行（{percentage}%）")
    print(f"- 同一ファイル内の重複 {within_file}件は数えない（似たテストケース・アイコン定義の並びは写経ではない）")
    print()
    if duplicates:
        print("| 行数 | 箇所A | 箇所B |")
        print("|---:|---|---|")
        for d in sorted(duplicates, key=lambda x: -x["lines"])[: args.top]:
            a, b = d["firstFile"], d["secondFile"]
            fa = str(Path(a["name"])).replace(os.sep, "/")
            fb = str(Path(b["name"])).replace(os.sep, "/")
            print(f"| {d['lines']} | `{fa}:{a['start']}` | `{fb}:{b['start']}` |")
        print()

    print("**この検出の限界**: 完全一致のクローンしか見つからない。設定値の直書き・組み立て規則の")
    print("手書きのように「同じ決まりごとが少しずつ違う形で書かれている」型は捕まらない。")

    if args.update:
        DUPLICATION_BASELINE.write_text(
            json.dumps({
                "commit": git("rev-parse", "--short", "HEAD").strip(),
                "date": dt.date.today().isoformat(),
                "clones": len(duplicates),
                "duplicated_lines": duplicated_lines,
                "percentage": percentage,
            }, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
        print(f"\n（{DUPLICATION_BASELINE.relative_to(REPO_ROOT)} を更新しました）")
    elif prev_clones is not None and len(duplicates) > prev_clones:
        print(f"\n判定: **増加（{prev_clones} → {len(duplicates)}件）** → 増えた箇所を確認する")
    return 0


# --- main -------------------------------------------------------------------

# --- mutate（ガードの実効性監査） -------------------------------------------
#
# 検知器は、鳴らなくなっても静かに「0件」を出し続ける。CIのpathspecが解決先を外していて
# 常にexit 0だった実績・`--staged`分岐にしか無い検知器がCIから抜けていた実績があり、
# **「検知器がある」ことと「検知器が鳴る」ことは別物**である。わざと違反を1件入れて
# 本当に落ちるかを、pre-commit経路（`--staged`）とCI経路（`--since`）の両方で確かめる。
#
# 検査は**使い捨てのworktreeの中だけ**で行い、呼び出し元の作業ツリーは一切変更しない
# （並行セッションが同じツリーを触りうる、CLAUDE.md「作業ツリーの安全」）。編集中の
# 検知器を試せるよう、追跡ファイルの未コミット変更だけはworktreeへ持ち込む。
#
# `DETECTOR_ENFORCEMENT`が強制すると宣言する検知器に違反の作り方が無ければNO-CASEとして
# 落とす——検知器を足したときにここへ1件足すことを、この監査自身が要求する。

GUARD_PROBE_TS = "frontend/src/lib/zzzGuardProbe.ts"
GUARD_PROBE_TEST_TS = "frontend/src/lib/zzzGuardProbe.test.ts"
GUARD_PROBE_PY = "backend/app/services/zzz_guard_probe.py"
# 実在しない識別子の綴りは実行時に組み立てる。このファイル自身が実在判定のコーパス
# （`source_corpus`はscripts/も読む）に入っているため、綴りをそのまま書くと
# 「実装に存在する名前」になってしまい、実在判定の検知器が鳴らない。
GUARD_PROBE_IDENT = "zzz" + "GuardProbe" + "Ident"


def guard_probe_post_stage(wt: Path) -> dict[str, "Callable[[], None]"]:
    """検知器キー → ステージ後に**作業ツリーだけ**を書き換える手順（省略可）。

    pre-commitはインデックスを検査する契約なので、ステージ後に作業ツリーを触っても結果は
    変わってはいけない。「作業ツリーを読んでしまう」実装をここで露見させる
    ——`git add -A`しかしない手順では、インデックスと作業ツリーが常に同じで区別がつかない。
    """
    arch = wt / ARCHITECTURE_DOC

    def declare_removed_in_worktree_only() -> None:
        # ステージ済みの違反行と同じ段落へ、作業ツリーでだけ撤去の断りを足す。
        text = read_text(arch)
        arch.write_text(
            text.replace(
                f"`{GUARD_PROBE_IDENT}`が現在の実装で値を組み立てる。",
                f"`{GUARD_PROBE_IDENT}`は撤去済み。",
            ),
            encoding="utf-8",
        )

    return {"undeclared_dead_refs": declare_removed_in_worktree_only}


def guard_probe_mutations(wt: Path) -> dict[str, "Callable[[], None]"]:
    """検知器キー → その検知器だけが拾うはずの違反を1件作る手順。"""
    module_doc = next(
        p for p in sorted((wt / "docs/modules").rglob("*.md")) if p.name != "README.md"
    )
    arch = wt / ARCHITECTURE_DOC
    plan = wt / "docs/improvement-plan.md"

    def append(path: Path, text: str) -> None:
        path.write_text(read_text(path) + text, encoding="utf-8")

    def write(rel: str, text: str) -> None:
        path = wt / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def flip_plan_checkbox() -> None:
        text = read_text(plan)
        m = re.search(r"^- \[ \] \[T(\d{3,4})\]\(tasks/T\d{3,4}\.md\)", text, re.M)
        if m is None:
            raise RuntimeError("docs/improvement-plan.md に未完了行が無く、状態照合を試せない")
        flipped = m.group(0).replace("- [ ]", "- [x]")
        plan.write_text(text[: m.start()] + flipped + text[m.end():], encoding="utf-8")

    return {
        "dead_file_refs": lambda: append(module_doc, "\n存在しない`Map/zzzGuardProbeFile.ts`を参照する。\n"),
        "dead_identifier_refs": lambda: append(module_doc, f"\n`{GUARD_PROBE_IDENT}`が処理する。\n"),
        "narrative": lambda: append(module_doc, "\n以前はこの方式ではなく別の形だった。\n"),
        "dead_doc_links": lambda: append(module_doc, "\n詳細は[T9999](../../tasks/T9999.md)参照。\n"),
        "undeclared_dead_refs": lambda: append(arch, f"\n`{GUARD_PROBE_IDENT}`が現在の実装で値を組み立てる。\n"),
        "plan_vs_tasks": flip_plan_checkbox,
        # 参考出力なのでDETECTOR_ENFORCEMENTは空だが、違反の作り方は定義しておく
        # （`mutate --case`で単体で試せるようにするため）。
        "undeclared_dead_refs_exempted": lambda: append(
            arch, f"\n`zzzGoneName`は撤去済み。`{GUARD_PROBE_IDENT}`が現在の実装で値を組み立てる。\n"),
        "source_narrative": lambda: write(
            GUARD_PROBE_TS, "// 改善計画T999でこの形に変更した。\nexport const zzzGuardProbe = 1;\n"),
        "undocumented_files": lambda: write(GUARD_PROBE_TS, "export const zzzGuardProbe = 1;\n"),
        "undefined_css_tokens": lambda: write(
            GUARD_PROBE_TS, 'export const zzzGuardProbe = "var(--zzz-guard-probe-token)";\n'),
        "redis_skeleton": lambda: write(
            GUARD_PROBE_PY,
            "from app.infrastructure.redis_client import get_redis_client_or_none\n\n\n"
            "async def zzz_guard_probe():\n    return get_redis_client_or_none()\n"),
        "bare_basemodel": lambda: write(
            GUARD_PROBE_PY,
            "from pydantic import BaseModel\n\n\nclass ZzzGuardProbe(BaseModel):\n    value: int = 0\n"),
        "vacuous_test_loops": lambda: write(
            GUARD_PROBE_TEST_TS,
            'import { expect, it } from "vitest";\n\n'
            'it("zzz guard probe", () => {\n'
            "  const picked = [1, 2, 3].filter((n) => n > 9);\n"
            "  for (const n of picked) {\n"
            "    expect(n).toBeGreaterThan(0);\n"
            "  }\n"
            "});\n"),
    }


def probe_section_count(stdout: str, key: str) -> int | None:
    """`docs --keys`の出力から、その検知器の節が報告した件数を読む。節が無ければNone。"""
    m = re.search(rf"^## \[{re.escape(key)}\] .*: (\d+)件$", stdout, re.M)
    return int(m.group(1)) if m else None


def cmd_mutate(args: argparse.Namespace) -> int:
    declared = sorted(k for k, modes in DETECTOR_ENFORCEMENT.items() if modes)
    if args.case:
        if args.case not in DETECTOR_ENFORCEMENT:
            print(f"未知の検知器キー: {args.case}（既知: {', '.join(sorted(DETECTOR_ENFORCEMENT))}）")
            return 2
        declared = [args.case]

    tmp = Path(tempfile.mkdtemp(prefix="rc-guard-"))
    wt = tmp / "wt"
    rows: list[tuple[str, str, str, str]] = []
    try:
        git("worktree", "add", "--detach", "--quiet", str(wt), "HEAD")

        def wt_run(*cmd: str) -> subprocess.CompletedProcess:
            return subprocess.run(cmd, cwd=str(wt), capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")

        # 編集中の検知器を試せるよう、追跡ファイルの未コミット変更をworktreeへ持ち込む。
        diff = git("diff", "HEAD")
        if diff.strip():
            applied = subprocess.run(
                ["git", "apply", "-"], cwd=str(wt), input=diff, capture_output=True,
                text=True, encoding="utf-8", errors="replace")
            if applied.returncode != 0:
                print("## 未コミット変更をworktreeへ適用できませんでした（追跡ファイルのみ対象）")
                print(applied.stderr.strip()[:400])
                return 1
        wt_run("git", "add", "-A")
        wt_run("git", "-c", "user.email=guard@local", "-c", "user.name=guard",
               "commit", "-q", "-m", "guard audit base", "--no-verify")
        base = wt_run("git", "rev-parse", "HEAD").stdout.strip()
        mutations = guard_probe_mutations(wt)
        post_stage = guard_probe_post_stage(wt)

        for key in declared:
            mutate = mutations.get(key)
            if mutate is None:
                rows.append((key, "NO-CASE", "-", "違反の作り方が未定義（guard_probe_mutationsへ1件足す）"))
                continue
            for mode, label in (("staged", "pre-commit"), ("since", "CI")):
                if mode not in DETECTOR_ENFORCEMENT[key]:
                    rows.append((key, "SKIP", label, "この経路では強制しない宣言"))
                    continue
                wt_run("git", "reset", "-q", "--hard", base)
                wt_run("git", "clean", "-fdq")
                try:
                    mutate()
                except Exception as exc:  # noqa: BLE001 違反を作れないこと自体を結果として出す
                    rows.append((key, "SETUP-FAIL", label, str(exc)[:80]))
                    continue
                wt_run("git", "add", "-A")
                if mode == "staged" and key in post_stage:
                    post_stage[key]()
                check = ["--staged"]
                if mode == "since":
                    wt_run("git", "-c", "user.email=guard@local", "-c", "user.name=guard",
                           "commit", "-q", "-m", "guard audit probe", "--no-verify")
                    check = ["--since", base]
                proc = wt_run(sys.executable, "scripts/review_checks.py", "docs", "--keys", *check)
                found = probe_section_count(proc.stdout, key)
                if found is None:
                    rows.append((key, "MISS", label, "この経路の検査項目に存在しない"))
                elif found == 0:
                    rows.append((key, "MISS", label, "検査はあるが0件（見逃し）"))
                elif proc.returncode == 0:
                    rows.append((key, "WARN", label, f"{found}件検知するがexit 0（参考扱い）"))
                else:
                    rows.append((key, "PASS", label, f"{found}件 exit={proc.returncode}"))
    finally:
        git("worktree", "remove", "--force", str(wt), check=False)
        shutil.rmtree(tmp, ignore_errors=True)
        git("worktree", "prune", check=False)

    print("## ガードの実効性監査（わざと違反を入れて落ちるか）")
    print()
    print("| 検知器 | 経路 | 判定 | 詳細 |")
    print("|---|---|---|---|")
    for key, verdict, label, detail in rows:
        print(f"| `{key}` | {label} | {verdict} | {detail} |")
    print()
    bad = [r for r in rows if r[1] not in ("PASS", "SKIP")]
    if bad:
        print(f"鳴らない検知器 {len(bad)}件。検知器があることと鳴ることは別物のため、これは違反として扱う。")
        return 1
    print(f"全{len(rows)}件PASS（検知器は実際に鳴る）")
    return 0


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("docs", help="docs/modules・improvement-plan・history の機械的整合性チェック")
    p.add_argument("--since", help="記載漏れ・ソースコード経緯コメントのチェックをこのref以降の追加分へ限定する")
    p.add_argument("--staged", action="store_true", help="pre-commit用: ステージ済み変更に関係する項目のみ")
    p.add_argument("--keys", action="store_true", help="見出しへ検知器キーを出す（mutateが節を対応づけるため）")
    p.set_defaults(func=cmd_docs)
    p = sub.add_parser("mutate", help="ガードの実効性監査（わざと違反を入れて落ちるか試す）")
    p.add_argument("--case", help="この検知器キーだけを試す（既定: 全件）")
    p.set_defaults(func=cmd_mutate)
    p = sub.add_parser("size", help="規模ウォッチ（complexity.md）")
    p.add_argument("--top", type=int, default=5)
    p.add_argument("--update", action="store_true", help="前回値ファイル（history/size_watch.json）を今回値で更新する")
    p.set_defaults(func=cmd_size)
    p = sub.add_parser("metrics", help="定量メトリクス（metrics.md）")
    p.add_argument("--since", help="churnの起点日（既定: history/ の直近metricsファイル日付）")
    p.add_argument("--full", action="store_true", help="テスト件数・tsc/eslint・npm audit も計測する（数分）")
    p.set_defaults(func=cmd_metrics)
    p = sub.add_parser("duplication", help="コピペ検出（complexity.md）")
    p.add_argument("--top", type=int, default=10, help="表に出す上位件数")
    p.add_argument("--update", action="store_true", help="前回値ファイル（history/duplication.json）を今回値で更新する")
    p.set_defaults(func=cmd_duplication)
    p = sub.add_parser("trigger", help="周期レビューのトリガー判定")
    p.set_defaults(func=cmd_trigger)
    args = parser.parse_args(argv)
    os.chdir(REPO_ROOT)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
