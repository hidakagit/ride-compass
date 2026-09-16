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
from typing import Callable, NamedTuple

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


MODULE_REDEFINITION_PREFIXES = ("backend/app/", "backend/tests/", "backend/scripts/", "scripts/")


def python_sources(paths) -> dict[str, str]:
    """`MODULE_REDEFINITION_PREFIXES`配下の.pyを {パス: 全文} で返す。"""
    out = {}
    for path in paths:
        if not path.endswith(".py") or not path.startswith(MODULE_REDEFINITION_PREFIXES):
            continue
        full = REPO_ROOT / path
        if full.exists():
            out[path] = read_text(full)
    return out


def find_module_level_redefinitions(sources: dict[str, str]) -> list[str]:
    """モジュール直下で同じ名前を2回以上定義しているもの。

    後の定義が前を上書きするため、**値が同じなら観測できる違いが何も出ない**。撤去や
    分割で切り出しすぎた塊を貼り直したときに生まれ、テストも`ruff`も落ちない
    （F811は未使用の関数・クラス・importの再定義しか見ず、モジュール直下の変数再代入は
    正当なPythonとして扱う）。2組が別々に編集されると、後の定義だけが効いて前の編集が
    静かに巻き戻る。

    条件分岐（`if`/`try`）の下の定義は、環境ごとに片方だけが走る正当な形のため見ない
    （モジュールの`body`直下だけを対象にする）。
    """
    out = []
    for path, text in sorted(sources.items()):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        seen: dict[str, list[int]] = defaultdict(list)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                seen[node.name].append(node.lineno)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        seen[target.id].append(node.lineno)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    seen[node.target.id].append(node.lineno)
        for name, linenos in seen.items():
            if len(linenos) > 1:
                where = "・".join(str(n) for n in linenos)
                out.append(f"{path}:{linenos[0]} `{name}` をモジュール直下で{len(linenos)}回定義（行 {where}）")
    return out


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


# webアプリが読み込む層から`app/batch`をモジュールトップでimportすると、バッチへ依存を1行
# 足しただけで本番webが起動時に落ちる。本番webイメージは`requirements.txt`しか入れない一方、
# batchは`requirements-batch.txt`限定の依存（rasterio等）を使うためで、テストとCIはbatch依存が
# 入っているため緑のまま通る（本番でクラッシュループになった実績があり、docs/tasks/T630.md・
# docs/tasks/T814.md参照）。関数内の遅延importは起動時に評価されないため対象外。
WEB_LAYER_DIRS = (
    "backend/app/api/",
    "backend/app/services/",
    "backend/app/infrastructure/",
    "backend/app/domain/",
)
BATCH_TOPLEVEL_IMPORT_RE = re.compile(r"^(?:from|import)\s+app\.batch\b")


def find_web_layer_batch_imports(source_lines: dict[str, list[tuple[int, str]]]) -> list[str]:
    out = []
    for path, lines in source_lines.items():
        if not path.startswith(WEB_LAYER_DIRS):
            continue
        for lineno, line in lines:
            if BATCH_TOPLEVEL_IMPORT_RE.match(line):
                out.append(
                    f"{path}:{lineno}: webアプリが読む層が`app.batch`をモジュールトップでimportしている"
                    "（batch専用依存を連鎖で引き込み本番webだけ起動できなくなる。共有したい値は"
                    "`domain/derived_data_versions.py`のようにdomainへ置くか、関数内へ遅延させる）"
                )
    return out


# 材料解決の経路がway_tagsから読んでよいキーは、取込時の許可リスト
# （`domain/osm_adapter.py: ALLOWED_WAY_TAGS`）に載っているものだけ。highway/surface/oneway
# は専用列でtags jsonbに入らないため、ここから読むと材料が全区間で欠損する。
MATERIAL_TAG_READER_FILES = (
    "backend/app/domain/axis_inspector.py",
    "backend/app/domain/material_catalog.py",
    "backend/app/domain/recipe.py",
)
WAY_TAG_READ_RES = (
    re.compile(r'\b(?:ctx\.)?(?:way_)?tags\.get\(\s*"([^"]+)"'),
    re.compile(r'tag_value_is\(\s*(?:ctx\.)?(?:way_)?tags\s*,\s*"([^"]+)"'),
)


def allowed_way_tags() -> set[str]:
    """取込時にtags jsonbへ残すキー（`ALLOWED_WAY_TAGS`）を実装から読む。"""
    text = read_text(REPO_ROOT / "backend/app/domain/osm_adapter.py")
    start = text.find("ALLOWED_WAY_TAGS")
    end = text.find("def _filter_allowed_tags", start)
    if start < 0 or end < 0:
        return set()
    return set(re.findall(r'"([^"]+)",', text[start:end]))


def find_way_tag_allowlist_violations(source_lines: dict[str, list[tuple[int, str]]]) -> list[str]:
    """材料解決の経路が、tags jsonbに入らないキーをway_tagsから読んでいる箇所。"""
    allowed = allowed_way_tags()
    if not allowed:
        return []
    out = []
    for path, lines in source_lines.items():
        if path not in MATERIAL_TAG_READER_FILES:
            continue
        for lineno, line in lines:
            for pattern in WAY_TAG_READ_RES:
                for m in pattern.finditer(line):
                    key = m.group(1)
                    if key not in allowed:
                        out.append(
                            f"{path}:{lineno}: way_tagsから`{key}`を読んでいる"
                            "（ALLOWED_WAY_TAGSに無いキーはtags jsonbへ入らず、材料が常に欠損する。"
                            "専用列なら引数で渡す。docs/tasks/T753.md参照）"
                        )
    return out


# docs/documentation.md「要素が1つ増えたときに嘘になる文は数え上げている」の機械的な手掛かり。
# 増減しうる集合の大きさを表す助数詞だけを見る（長さ・時間・回数のように増えても嘘に
# ならない単位は最初から入れない）。「1つ」は「1箇所へ寄せる」のような書き方が大半のため
# 2以上に限る。**参考表示に留める**——実測した内訳はdocs/tasks/T824.mdにある。
COUNTED_UNITS = (
    "個|種類|種|値|箇所|つ|パターン|カテゴリ|段階|レイヤー|材料|キャッシュ|メソッド"
    "|軸|分位|要素|状態|系統|コマ|グループ|チップ|フラグ|エンドポイント|テーブル"
)
COUNT_NARRATIVE_RE = re.compile(
    rf"(?<![0-9a-zA-Z.])(?:[2-9]|[1-9][0-9]|[二三四五六七八九十])\s*(?:\*\*)?(?:{COUNTED_UNITS})"
)
# 記録として残す文書（当時の数をそのまま持つ）と、タスクの個票は対象外。
COUNT_NARRATIVE_EXEMPT = ("docs/tasks/", "docs/improvement-plan.md", "zero-base-review", "-review-2026-")


def find_count_narratives(
    source_lines: dict[str, list[tuple[int, str]]],
    doc_lines: dict[str, list[tuple[int, str]]],
) -> list[str]:
    """個数を書いている行（参考表示）。ソースはコメント部分だけを見る。"""
    out: list[str] = []
    for path, lines in sorted(source_lines.items()):
        jsx_state: dict[str, bool] = {}
        for lineno, line in lines:
            text = comment_only(line, path, jsx_state)
            m = COUNT_NARRATIVE_RE.search(text) if text else None
            if m:
                out.append(f"{path}:{lineno}: 「{m.group(0)}」 {text.strip()[:80]}")
    for path, lines in sorted(doc_lines.items()):
        if any(part in path for part in COUNT_NARRATIVE_EXEMPT):
            continue
        for lineno, line in lines:
            m = COUNT_NARRATIVE_RE.search(line)
            if m:
                out.append(f"{path}:{lineno}: 「{m.group(0)}」 {line.strip()[:80]}")
    return out


# map.setStyle()はカスタムのsource/layerを全て捨てるため、その後の再描画から辿り着けない
# 描画は「消えたまま戻らない」。再描画の入口と、それが守るべきファイルを指す。
MAP_REDRAW_FILE = "frontend/src/components/Map/MapView.tsx"
MAP_REDRAW_ENTRY = "redrawAllLayers"
# トップレベル宣言の行頭。字下げされたもの（関数内の入れ子）は外側の宣言の一部として扱う。
TOP_LEVEL_DEF_RE = re.compile(
    r"^(?:export\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:function|const|let|var|class|type|interface|enum)\s+([A-Za-z_$][\w$]*)"
)


def blank_ts_noncode(text: str) -> str:
    """TS/TSXのコメントと文字列リテラルを空白へ置き換える（オフセットと行数は保つ）。"""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                out[i] = " "
                i += 1
        elif c == "/" and i + 1 < n and text[i + 1] == "*":
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                if text[i] != "\n":
                    out[i] = " "
                i += 1
            for _ in range(2):
                if i < n:
                    out[i] = " "
                    i += 1
        elif c in "\"'`":
            quote = c
            i += 1
            while i < n:
                if text[i] == "\\":
                    out[i] = " "
                    if i + 1 < n and text[i + 1] != "\n":
                        out[i + 1] = " "
                    i += 2
                    continue
                if text[i] == quote:
                    i += 1
                    break
                if text[i] != "\n":
                    out[i] = " "
                i += 1
        else:
            i += 1
    return "".join(out)


def top_level_segments(code: str) -> tuple[dict[str, str], dict[str, int]]:
    """トップレベル宣言ごとの本文（次の宣言の直前まで）と開始行。"""
    lines = code.splitlines()
    starts = [(i, m.group(1)) for i, l in enumerate(lines) if (m := TOP_LEVEL_DEF_RE.match(l))]
    body: dict[str, str] = {}
    line_of: dict[str, int] = {}
    for pos, (idx, name) in enumerate(starts):
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        body[name] = body.get(name, "") + "\n" + "\n".join(lines[idx:end])
        line_of.setdefault(name, idx + 1)
    return body, line_of


# 再描画（map.setStyle()）で失われる副作用。ソースの新設だけでなく、レイヤーの追加や
# filter・feature-state・visibilityで持つ表示状態も、スタイルごと消えて初期値へ戻る。
# 母集団を「sourceを作る宣言」に限ると、既存ソースの上に載せた表示状態は検査の外に落ちる
# （T868の道の強調がその形で見逃された。docs/tasks/T871.md）。
MAP_REDRAW_SIDE_EFFECTS = (
    ".addSource(",
    ".addLayer(",
    ".setFilter(",
    ".setFeatureState(",
    "setLayerVisibility(",
)


# 入口のファイルが同じディレクトリから取り込むモジュール。母集団をこの経路で広げる。
MAP_REDRAW_LOCAL_IMPORT_RE = re.compile(r'from "(?:@/components/Map/|\./)([\w.]+)"')


def find_map_redraw_gaps() -> list[str]:
    # 呼び出し側が結果を持ち回るため、キャッシュした実体は渡さず複製を返す。
    # リポジトリの位置をキーへ含めるのは、テストが`REPO_ROOT`へ一時ディレクトリを
    # 差し込むため（差し替えたのに前の結果が返る状態を作らない）。
    return list(_find_map_redraw_gaps(str(REPO_ROOT)))


@functools.lru_cache(maxsize=4)
def _find_map_redraw_gaps(repo_root: str) -> list[str]:
    """map.setStyle()後の再描画から辿り着けない、描画の副作用を持つ宣言。

    到達は「トップレベル宣言の本文にその名前が現れるか」で見る（呼び出しに限らず、
    コールバックとして渡す形も辿れるようにするため）。オーバーレイ登録表の`ensure`だけは
    名前で呼ばれないため、`.ensure(`を呼ぶ経路からは表に載る`ensure`すべてへ辿れるものと
    して扱う。

    **母集団は入口の1ファイルに限らない**。描画の担当を別ファイルへ分けると、分けた先の
    宣言が丸ごと検知の外へ出る——入口から呼ばれなくなっても誰も気づかない。入口が同じ
    ディレクトリから取り込んでいるモジュールを母集団へ足し、到達判定はモジュール境界を
    跨いで1つのグラフとして行う。
    """
    path = REPO_ROOT / MAP_REDRAW_FILE
    if not path.exists():
        return [f"{MAP_REDRAW_FILE} が見つからない（検知器の対象がずれている）"]
    source = read_text(path)
    parts = [(MAP_REDRAW_FILE, source), *map_redraw_local_modules(source, path.parent)]
    return map_redraw_gaps_in("\n".join(text for _, text in parts), parts)


def rel_if_inside_repo(path: Path) -> str:
    try:
        return rel(path)
    except ValueError:
        return path.as_posix()


def map_redraw_local_modules(source: str, directory: Path) -> list[tuple[str, str]]:
    """入口のファイルが`directory`から取り込んでいるモジュールの、パスと中身。"""
    out = []
    for name in sorted(set(MAP_REDRAW_LOCAL_IMPORT_RE.findall(source))):
        for suffix in (".ts", ".tsx"):
            candidate = directory / (name + suffix)
            if candidate.exists():
                out.append((rel_if_inside_repo(candidate), read_text(candidate)))
                break
    return out


def map_redraw_gaps_in(source: str, parts: list[tuple[str, str]] | None = None) -> list[str]:
    """`find_map_redraw_gaps`の本体（テストが合成したソースにも掛けられるよう分けてある）。

    `parts`は連結前の(パス, 中身)。渡すと、連結後の行番号を元のファイルと行へ戻して報告する
    ——どのファイルを見ればよいかが分からないと、検知しても直しにくい。
    """
    code = blank_ts_noncode(source)
    body, line_of = top_level_segments(code)
    if MAP_REDRAW_ENTRY not in body:
        return [
            f"{MAP_REDRAW_FILE}: トップレベルに`{MAP_REDRAW_ENTRY}`が無い"
            "（再描画の入口が辿れないと、この検知器は何も守れない）"
        ]
    names = set(body)
    ensure_values = set(re.findall(r"\bensure:\s*([A-Za-z_$][\w$]*)", code)) & names

    reachable: set[str] = set()
    stack = [MAP_REDRAW_ENTRY]
    while stack:
        current = stack.pop()
        if current in reachable or current not in body:
            continue
        reachable.add(current)
        segment = body[current]
        stack.extend(n for n in names if n not in reachable and re.search(rf"\b{re.escape(n)}\b", segment))
        if ".ensure(" in segment:
            stack.extend(ensure_values)

    owners = {n for n, b in body.items() if any(m in b for m in MAP_REDRAW_SIDE_EFFECTS)}

    def where(line: int) -> str:
        if not parts:
            return f"{MAP_REDRAW_FILE}:{line}"
        offset = 0
        for path, text in parts:
            count = text.count("\n") + 1
            if line <= offset + count:
                return f"{path}:{line - offset}"
            offset += count
        return f"{MAP_REDRAW_FILE}:{line}"
    return [
        f"{where(line_of[name])}: `{name}`が再描画で失われる副作用を持つが、"
        f"`{MAP_REDRAW_ENTRY}`から辿れない"
        "（map.setStyle()後に作り直されず、そのレイヤーは消えたまま戻らない。"
        "docs/tasks/T825.md参照）"
        for name in sorted(owners - reachable, key=lambda n: line_of[n])
    ]


# テストの足場（フェイク・フィクスチャ組み立て）が、同じ名前で複数のテストファイルへ
# 定義されている状態。書く前に既にあるものへ気づくための参考表示で、正当に分ける判断
# （記録する呼び出しが違う等）もあるためブロックはしない（docs/tasks/T771.md）。
SCAFFOLD_DEF_RES = (
    re.compile(r"^(?:export\s+)?(?:async\s+)?function\s+((?:make|fake|stub|build|create)[A-Za-z0-9_]*)\s*\(", re.M),
    re.compile(r"^const\s+((?:make|fake|stub|build|create)[A-Za-z0-9_]*)\s*=\s*(?:\(|async|function)", re.M),
)


def find_duplicate_test_scaffolds(test_files: list[str]) -> list[str]:
    by_name: dict[str, list[str]] = {}
    for path in test_files:
        if "/testing/" in path:
            continue
        text = read_text(REPO_ROOT / path)
        for pattern in SCAFFOLD_DEF_RES:
            for name in pattern.findall(text):
                by_name.setdefault(name, [])
                if path not in by_name[name]:
                    by_name[name].append(path)
    return [
        f"`{name}`が{len(paths)}ファイルに定義されている（{', '.join(sorted(paths))}）"
        "——同じ用途の足場が既にあるかを見てから書く。共有するなら frontend/src/testing へ"
        for name, paths in sorted(by_name.items())
        if len(paths) > 1
    ]


PLAN_DOC = "docs/improvement-plan.md"
OPEN_PLAN_LINE_RE = re.compile(r"^- \[ \] \[T(\d{3,4})\]\(tasks/T\d{3,4}\.md\)\.?\s*(.*)$")
# 漢字・カタカナの連なりと、英数字の識別子。ひらがなだけの語は助詞・語尾が大半のため採らない。
PLAN_TERM_RE = re.compile(r"[一-龥]{2,}|[ァ-ヴー]{3,}|[A-Za-z_][A-Za-z0-9_]{2,}")
# 台帳のほぼ全行に出る語。共通していても近さの手掛かりにならない。
PLAN_TERM_STOPWORDS = frozenset({
    "規模", "起票", "完了", "未着手", "実装", "対応", "検討", "調査", "判断", "保留", "見送り",
    "追加", "修正", "改善", "対策", "整理", "統一", "共通", "汎用", "機能", "表示", "設定",
    "結果", "本番", "現状", "既存", "新設", "撤去", "全体", "以上", "以下", "場合", "自体",
    "ユーザー", "トリガー", "タスク", "パネル", "ルート", "フロント", "バック", "コード",
    "レビュー", "テスト", "ドキュメント", "リファクタ", "md", "tsx", "ts", "py",
})


def plan_entry_terms(title: str) -> set[str]:
    """台帳1行から、近さの手掛かりになる語だけを抜き出す。"""
    head = re.split(r"\s規模|（|\(", title)[0]
    body = title if len(head) < 6 else head
    return {t for t in PLAN_TERM_RE.findall(body) if t not in PLAN_TERM_STOPWORDS}


def open_plan_entries(text: str) -> dict[str, str]:
    """未完了（`- [ ]`）の台帳行を {Txxx: 見出し} で返す。"""
    entries: dict[str, str] = {}
    for line in text.splitlines():
        m = OPEN_PLAN_LINE_RE.match(line.strip())
        if m:
            entries[f"T{m.group(1)}"] = m.group(2)
    return entries


def find_plan_entry_overlap(added_lines: list[str], existing_text: str, min_shared: int = 2) -> list[str]:
    """新しく足した未完了エントリと語が重なる、既存の未完了エントリ。

    重複した起票・関連タスクの見落としは、起票の瞬間に既存を見ないと後から気づけない
    （台帳は数百行あり、`/task:next`は候補を優先度順に出すだけで近さを見ない）。
    判断は人がする——別々に進めるのが正しいこともあるため、参考表示に留める。
    """
    existing = open_plan_entries(existing_text)
    out: list[str] = []
    for line in added_lines:
        m = OPEN_PLAN_LINE_RE.match(line.strip())
        if not m:
            continue
        new_id, title = f"T{m.group(1)}", m.group(2)
        terms = plan_entry_terms(title)
        if not terms:
            continue
        hits = []
        for other_id, other_title in existing.items():
            if other_id == new_id:
                continue
            shared = terms & plan_entry_terms(other_title)
            if len(shared) >= min_shared:
                hits.append((len(shared), other_id, sorted(shared)))
        for _, other_id, shared in sorted(hits, reverse=True)[:3]:
            out.append(
                f"{new_id}と{other_id}が「{'・'.join(shared)}」を共有している"
                "——重複していないか、片方へ寄せられないかを見てから起票する"
            )
    return out


FILE_TOKEN_RE = re.compile(
    r"`([A-Za-z0-9_./@\-]+\.(?:py|ts|tsx|css|json|yml|yaml|sql|sh|md|js|mjs|toml|txt))`"
)
TASK_LINK_RE = re.compile(r"\[T(\d{3,4})\]\(")
TASK_FILE_MENTION_RE = re.compile(r"\bT(\d{3,4})\.md\b")
HISTORY_REF_RE = re.compile(r"history/(\d{4}-\d{2}-\d{2}_[A-Za-z0-9_\-]+\.md)")
PLAN_LINE_RE = re.compile(r"^- \[( |x)\] \[T(\d{3,4})\]\(tasks/T(\d{3,4})\.md\)")
TASK_FILE_RE = re.compile(r"T(\d{3,4})\.md$")
TASK_HEADING_RE = re.compile(r"^#\s*T(\d{3,4})\b")


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


# 1回の実行中にファイルは変わらない（検査は読むだけ）。同じファイルを何度も読み直すのが
# 所要の一角を占めるため内容を保持する。書き換えたファイルを同じ実行内で読み直す用途には
# 使えない——その必要が出たら`read_text.cache_clear()`を呼ぶこと。
@functools.lru_cache(maxsize=None)
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


# 箇条書き・番号付きリストの項目の先頭。空行を挟まず別の話題が並ぶため、ここで区切らないと
# 1項目の撤去の断りがリスト全体を免除してしまう（docs/tasks/T743.md）。
LIST_ITEM_START_RE = re.compile(r"^\s*(?:[-*+]|\d+\.)\s")


def paragraphs_with_removal_marker(doc: str, revision: str | None = None) -> set[int]:
    """撤去等の断りを含む段落に属する行番号。

    判定の単位は物理行ではなく段落にする。この文書は編集の都合で1文が複数行へ
    折り返されるため、行で見ると「名前」と「撤去済み」が別の行へ落ちただけで違反になる
    ——読み手が受け取る単位は段落であって、折り返し位置ではない。段落の切れ目は空行と、
    リスト項目の先頭（空行を挟まず別の話題が並ぶ書き方のため）。

    `revision`は行番号の出所（`""`＝インデックス、`"HEAD"`、Noneなら作業ツリー）。
    """
    text = doc_text_at(doc, revision)
    if not text:
        return set()
    marked: set[int] = set()
    start, buffer = 1, []

    def flush() -> None:
        if buffer and ARCHITECTURE_REMOVED_MARKER_RE.search("\n".join(buffer)):
            marked.update(range(start, start + len(buffer)))

    for lineno, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            flush()
            buffer = []
            continue
        if buffer and LIST_ITEM_START_RE.match(line):
            flush()
            buffer, start = [], lineno
        if not buffer:
            start = lineno
        buffer.append(line)
    flush()
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


# --- ソースコード内のコメント（docs/modulesと同じ基準で識別子の死活を見る） -------
#
# コメントが名指しする識別子は、それ自体がソース全文の一部のため`identifier_exists`から
# 見れば常に「実在する」。改名・撤去に取り残されたコメントを拾うには、**コメントを除いた
# 本文**を母集団にする必要がある。

#: コメントの中身だけを取り出せる拡張子と、その行コメントの始まり。
_LINE_COMMENT_MARKERS = {
    ".ts": ("//",), ".tsx": ("//",), ".js": ("//",), ".mjs": ("//",),
    ".css": (), ".sql": ("--",), ".sh": ("#",),
}
def _python_comment_lines(text: str) -> set[int]:
    """コメント・文字列リテラルだけの文（docstring）が占める行番号。

    `tokenize`と`ast`で正確に取る（文字列中の`#`をコメントと誤認しない）。docstringは
    モジュール・クラス・関数の先頭に限らず**値として使われない文字列文すべて**を見る
    ——属性の説明として直後へ置く形が広く使われており、そこを残すと母集団が汚れる。
    """
    import ast
    import io
    import tokenize

    lines: set[int] = set()
    try:
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.COMMENT:
                lines.add(token.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return lines
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return lines
    for node in ast.walk(tree):
        if not isinstance(node, ast.Expr):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            lines.update(range(value.lineno, (value.end_lineno or value.lineno) + 1))
    return lines


def _block_comment_lines(text: str, markers: tuple[str, ...]) -> set[int]:
    """`/* ... */`のブロックと、行頭から始まる行コメントが占める行番号。

    ブロックは開始から終了まで**状態として追う**。途中行が`*`で始まるとは限らず
    （日本語の続き行など）、行頭だけを見ると本文として母集団へ残ってしまう。
    """
    lines: set[int] = set()
    in_block = False
    for lineno, line in enumerate(text.splitlines(), 1):
        stripped = line.lstrip()
        if in_block:
            lines.add(lineno)
            if "*/" in line:
                in_block = False
            continue
        if "/*" in line:
            lines.add(lineno)
            in_block = "*/" not in line.split("/*", 1)[1]
            continue
        if markers and stripped.startswith(markers):
            lines.add(lineno)
    return lines


@functools.lru_cache(maxsize=None)
def split_source_comments(path: str, text: str) -> tuple[list[tuple[int, str]], str]:
    """(コメント行, コメントを除いた本文)。拡張子ごとの素朴な規則で分ける。

    行の途中から始まる行コメント（`x = 1  // 説明`）は本文側へ残す。取りこぼす方向の
    割り切りで、**誤検知を出さない**ことを優先する。
    """
    suffix = Path(path).suffix
    if suffix == ".py":
        marked = _python_comment_lines(text)
    else:
        marked = _block_comment_lines(text, _LINE_COMMENT_MARKERS.get(suffix, ()))
    comment_lines: list[tuple[int, str]] = []
    code_lines: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        (comment_lines.append((lineno, line)) if lineno in marked else code_lines.append(line))
    return comment_lines, "\n".join(code_lines)


def corpus_files(files: list[str], include_tests: bool = False) -> list[str]:
    return [
        f for f in files
        if f.startswith(SOURCE_CORPUS_PREFIXES) and f.endswith(SOURCE_CORPUS_SUFFIXES)
        and (include_tests or not SOURCE_CORPUS_EXCLUDE_RE.search(f))
        and (REPO_ROOT / f).exists()
    ]


# 外部システムの語彙。**このリポジトリのコードには存在しなくて当然**で、改名の取り残しでは
# ない。コメントが外部の仕様を説明するために名指しするもので、綴りを変えると説明が嘘になる。
EXTERNAL_VOCABULARY = frozenset({
    "zoomUse",                # JMAの配信設定JSONが持つフィールド名
    "maxNativeZoom",
    "n_live_tup",             # PostgreSQL pg_stat_user_tables の列
    "__asyncpg_stmt_N__",     # asyncpgが内部で付けるprepared statement名
    "to_shape",               # geoalchemy2の変換関数
    "onPressedChange",        # Radix UIのprop
    "composeEventHandlers",   # Radix UIの内部ヘルパ
    "flood_mesh",             # 国交省ハザードマップのレイヤーid
    "flood_riskline",
    "inland_flood",
    "BackgroundTasks",        # FastAPIのクラス
    "toll_booth",             # OSMのタグ値
    "guard_rail",
    "jersey_barrier",
})


def find_source_comment_dead_identifier_refs(files: list[str], scope: list[str] | None = None) -> list[str]:
    """ソースコードのコメントが名指しする識別子のうち、実装のどこにも綴りが無いもの。

    母集団はコメントを除いた本文。コメント同士が互いを「実在する」と支え合うのを防ぐ。
    改名・撤去のたびに、取り残されたコメントがその場で分かる。
    """
    # 母集団にはテストも含める。コメントはテスト側の部品（`FakeRoadGraphRepository`等）を
    # 正当に名指しするため、除くと正しい記述が違反になる。実測: 除くと46件、含めると31件。
    comment_lines: dict[str, list[tuple[int, str]]] = {}
    code_parts: list[str] = []
    for f in corpus_files(files, include_tests=True):
        comments, code = split_source_comments(f, read_text(REPO_ROOT / f))
        comment_lines[f] = comments
        code_parts.append(code)
    corpus = "\n".join(code_parts)
    # 走査するのは実装のコメントだけ（テストのコメントは母集団には要るが、対象にすると
    # テスト内の旧名まで一度に抱え込む。そちらは別タスクで扱う）。
    targets = corpus_files(files if scope is None else scope)
    hits = find_dead_identifier_refs(
        {f: comment_lines[f] for f in targets if f in comment_lines}, corpus
    )
    return sorted(h for h in hits if not any(f"`{name}`" in h for name in EXTERNAL_VOCABULARY))


def source_corpus(files: list[str]) -> str:
    """識別子の実在判定に使うソース全文（実装・スクリプト）。"""
    return _source_corpus(str(REPO_ROOT), tuple(files))


@functools.lru_cache(maxsize=8)
def _source_corpus(repo_root: str, files: tuple[str, ...]) -> str:
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


# import文が持ち込む名前（`from x import y`・`import {y} from "x"`のy）。テスト本体は
# corpusから外しているため、**テストだけが使う外部APIの名前**（式評価器・テストクライアント
# 等）が「実装に存在しない」と判定される。import文に現れる名前は、自前か依存先かを問わず
# 解決できる実在の名前なので救済する——テスト本体の**アサーションや文字列**に残る旧名は
# import文には現れないため、改名の取り残しを見逃す側には効かない（docs/tasks/T722.md）。
IMPORTED_NAME_RE = re.compile(
    r"^\s*from\s+[\w.]+\s+import\s+([^\n#]+)"
    r"|^\s*import\s+([\w.,\s]+)$"
    r"|^\s*import\s*\{([^}]*)\}\s*from"
    r"|^\s*import\s+(\w+)\s*,?\s*(?:\{[^}]*\})?\s*from",
    re.M,
)


@functools.cache
def imported_names() -> frozenset[str]:
    # `REPO_ROOT`がgit管理下でない場合（テストが一時ディレクトリを差し込む）は空集合。
    # 救済が減る＝検知が厳しくなる方向なので、見逃しには倒れない。
    names: set[str] = set()
    for f in (line for line in git("ls-files", check=False).splitlines() if line):
        if not f.endswith((".py", ".ts", ".tsx")) or "/types/generated/" in f:
            continue
        path = REPO_ROOT / f
        if not path.exists():
            continue
        for m in IMPORTED_NAME_RE.finditer(read_text(path)):
            blob = next((g for g in m.groups() if g), "")
            for part in blob.replace("(", " ").replace(")", " ").split(","):
                token = part.strip().split(" as ")[0].strip().rsplit(".", 1)[-1].strip()
                if re.fullmatch(r"[A-Za-z_]\w*", token):
                    names.add(token)
    return frozenset(names)


CORPUS_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@functools.lru_cache(maxsize=8)
def _corpus_words(corpus: str) -> frozenset[str]:
    return frozenset(CORPUS_WORD_RE.findall(corpus))


def corpus_words(corpus: str) -> frozenset[str]:
    """corpusに単語として現れる綴りの集合（包含判定の速い側）。"""
    return _corpus_words(corpus)


def identifier_exists(token: str, corpus: str) -> bool:
    """その綴りが実装にあるか。

    `.env`で設定する環境変数名（`WEATHER_RATE_LIMIT_PER_MINUTE`等）は、実装側には
    pydantic `Settings`の小文字フィールドとしてしか現れない。そこだけを救済する
    ——corpus全体で小文字形を探すと、`AXIS_DEFINITIONS`がモジュール名
    `axis_definitions.py`に一致してしまうように、**撤去しても常に存在する**定数が
    大量にできる（実測: 文書が名指しするSCREAMING_SNAKE定数173件のうち32件が、
    緩和のせいで検知不能だった。救済が要るのは10件だけ）。

    import文に現れる名前も救済する（`IMPORTED_NAME_RE`の項参照）。
    """
    # 判定は綴りの包含（短い綴りが、それを含むより長い名前の一部でも「実在する」）。
    # corpusは実装全文の連結で数MBあり、そこへ毎回inを走らせるとトークン数×corpus長の
    # オーダーになる。
    # corpusを一度だけ単語へ割った集合を先に見て、単語として在る綴りはそこで確定させる
    # ——集合に在れば包含も必ず成り立つので、判定は変わらない。集合に無いものだけが
    # 包含判定へ落ちる（他の単語の一部として現れる場合と、本当に無い場合）。
    if token in corpus_words(corpus):
        return True
    if token in corpus:
        return True
    if token in imported_names():
        return True
    return token.isupper() and "_" in token and token.lower() in settings_field_names()


# コードフェンス内は識別子をバッククォート無しで書く場所。データフロー図・コード例という
# 「機構の全体像を最も具体的に述べる箇所」がそこに集まるため、バッククォート付きだけを
# 母集団にすると図だけが恒久的に検査の外に残る（docs/tasks/T871.md）。
FENCE_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def fenced_line_numbers(doc: str) -> set[int]:
    """その文書のコードフェンス（```）の内側にある行番号。

    ファイル全体から求める——`--staged`では追加行しか渡らず、断片からはフェンスの開閉を
    追えない。
    """
    path = REPO_ROOT / doc
    if not path.exists():
        return set()
    inside = False
    out: set[int] = set()
    for lineno, line in enumerate(read_text(path).splitlines(), 1):
        if line.lstrip().startswith("```"):
            inside = not inside
            continue
        if inside:
            out.add(lineno)
    return out


def find_dead_identifier_refs(
    doc_lines: dict[str, list[tuple[int, str]]], corpus: str, *, include_fenced: bool = False
) -> list[str]:
    """docs/modulesが名指しする識別子のうち、実装のどこにも綴りが無いもの。

    ファイル名の実在（find_dead_file_refs）だけでは、ファイルは残ったまま中の関数・定数が
    改名・削除された参照を検出できない。綴りの単純な包含判定で、改名の取り残しを拾う。

    `include_fenced`はdocs/modules専用。コードフェンスの内側を裸の綴りまで見るため、
    工程名・タスク番号を図へ書く文書（architecture.md・レビュー手順書）へ当てると
    識別子でない語を拾う（実測: architecture.mdで17件、いずれも誤検知）。
    """
    out = []
    for doc, lines in doc_lines.items():
        fenced = fenced_line_numbers(doc) if include_fenced else frozenset()
        for lineno, line in lines:
            tokens = set(DOC_IDENT_RE.findall(line)) | set(DOC_QUALIFIED_IDENT_RE.findall(line))
            if lineno in fenced:
                tokens |= set(FENCE_IDENT_RE.findall(line))
            for token in sorted(tokens):
                if looks_like_identifier(token) and not identifier_exists(token, corpus):
                    out.append(f"{doc}:{lineno}: `{token}` が実装に存在しない")
    return out


# レビュー手順書（.claude/commands/）は全レビューが最初に読む。撤去済みの機構を現行として
# 記述していると、その陳腐化がすべてのレビューへ伝播する（docs/tasks/T743.md）。
REVIEW_COMMAND_DOC_PREFIX = ".claude/commands/"
# 記録として残す文書（当時の名前をそのまま持つ）。
REVIEW_COMMAND_DOC_EXEMPT = ("/history/", "/_history.md")
# Claude Codeのツール名・ツール入力のフィールド名。プロジェクトの実装には存在しない。
AGENT_TOOL_NAMES = frozenset({
    "ReportFindings", "Grep", "Glob", "Read", "Edit", "Write", "Bash", "Task", "TodoWrite",
    "AskUserQuestion", "failure_scenario", "short_summary",
})


def review_command_docs(files: list[str]) -> list[str]:
    return [
        f for f in files
        if f.startswith(REVIEW_COMMAND_DOC_PREFIX) and f.endswith(".md")
        and not any(part in f for part in REVIEW_COMMAND_DOC_EXEMPT)
    ]


def find_review_doc_dead_refs(files: list[str], scope: list[str] | None = None) -> list[str]:
    """レビュー手順書が名指しする識別子のうち、実装に存在しないもの。

    段落に撤去の断りがあれば免除する（architecture.mdと同じ単位）——「旧◯◯は撤去済み」と
    書くのは正しい記述で、名前を出さずには書けない。
    """
    corpus = source_corpus(files)
    targets = review_command_docs(files if scope is None else scope)
    out: list[str] = []
    for doc in sorted(targets):
        path = REPO_ROOT / doc
        if not path.exists():
            continue
        exempt = paragraphs_with_removal_marker(doc)
        lines = [(n, l) for n, l in enumerate(read_text(path).splitlines(), 1) if n not in exempt]
        for hit in find_dead_identifier_refs({doc: lines}, corpus):
            if any(f"`{name}`" in hit for name in AGENT_TOOL_NAMES):
                continue
            out.append(hit)
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
# UIライブラリが自分の要素へ実行時に設定するトークンの名前空間。定義はnode_modules側に
# あり、globals.cssにもリポジトリ内の.ts/.tsxにも現れない（例: Radixのポップオーバーが
# 測った空き幅`--radix-popover-content-available-width`）。名前空間で丸ごと許すため、
# 自前の`--color-*`等の綴り違いはこれまでどおり検知される。
CSS_VENDOR_TOKEN_PREFIXES = ("--radix-",)


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
                if token.startswith(CSS_VENDOR_TOKEN_PREFIXES):
                    continue
                if token not in defined and token not in local:
                    out.append(f"{f}:{lineno}: 未定義のCSSトークン `{token}`（定義は{GLOBAL_TOKENS_CSS}）")
    return out


# --- テストが書き換える環境変数を、他の実装も読んでいる ------------------------
#
# frontendのvitestは`pool: "vmThreads"`で走るため、`process.env`はテストファイルをまたいで
# 共有される。あるテストが環境変数を立てている間に別ファイルが同じ変数を読むと、後者の
# 期待値が静かに変わる（フルスイートでだけ落ちるテストになる。docs/tasks/T777.md）。
# 「そのテストが対象にしている実装」だけが読む変数なら、立てても他へ波及しないので許す。

TEST_ENV_WRITE_RE = re.compile(
    r"""(?:process\.env\.([A-Z][A-Z0-9_]*)\s*=|delete\s+process\.env\.([A-Z][A-Z0-9_]*)"""
    r"""|vi\.stubEnv\(\s*["']([A-Z][A-Z0-9_]*)["']|process\.env\s*=)"""
)
IMPL_ENV_READ_RE = re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)")


def find_cross_file_env_writes(files: list[str]) -> list[str]:
    """テストが書き換える環境変数を、そのテスト自身の対象以外の実装も読んでいる箇所。"""
    fronts = [f for f in files if f.startswith("frontend/src/") and f.endswith((".ts", ".tsx"))]
    impls = [f for f in fronts if not TEST_FILE_RE.search(f)]
    readers: dict[str, set[str]] = {}
    for f in impls:
        for name in IMPL_ENV_READ_RE.findall(read_text(REPO_ROOT / f)):
            readers.setdefault(name, set()).add(f)
    out: list[str] = []
    for f in sorted(f for f in fronts if TEST_FILE_RE.search(f)):
        text = read_text(REPO_ROOT / f)
        subject = f.replace(".test.tsx", ".tsx").replace(".test.ts", ".ts")
        for lineno, line in enumerate(text.splitlines(), 1):
            m = TEST_ENV_WRITE_RE.search(line)
            if m is None:
                continue
            name = m.group(1) or m.group(2) or m.group(3)
            if name is None:  # `process.env = {...}`（丸ごと差し替え）は常に他ファイルへ波及する
                out.append(f"{f}:{lineno}: `process.env`ごと差し替えている（ファイル間で共有されるため他のテストの期待値を変える）")
                continue
            others = sorted(readers.get(name, set()) - {subject})
            if others:
                out.append(
                    f"{f}:{lineno}: `{name}`を書き換えているが、{others[0]}も読む"
                    "（読む側をモックするか、判断を引数で受ける純関数へ出す。docs/testing.md参照）"
                )
    return out


# --- タスク番号の一貫性 -------------------------------------------------------
#
# タスク番号は台帳のラベル・そのリンク先・タスクファイルの見出しの3箇所に散る。2つの
# セッションが同じ番号を独立に採ると、リンク先のファイルには後から書いた側の本文だけが残り、
# 先に載ったエントリは本文を失ったまま台帳に並ぶ——ファイル自体は存在するため、状態照合
# （`check_plan_vs_tasks`）も含めどの検査も通ってしまう。


def check_task_numbering() -> list[str]:
    violations: list[str] = []
    first_line_of: dict[str, int] = {}
    for lineno, line in enumerate(read_text(IMPROVEMENT_PLAN).splitlines(), 1):
        m = PLAN_LINE_RE.match(line)
        if not m:
            continue
        num, linked = m.group(2), m.group(3)
        if linked != num:
            violations.append(
                f"docs/improvement-plan.md:{lineno}: ラベルはT{num}だがリンク先はtasks/T{linked}.md"
                "（振り直しの置換漏れ）"
            )
        if num in first_line_of:
            violations.append(
                f"docs/improvement-plan.md:{lineno}: T{num} は{first_line_of[num]}行目でも使われている"
                "（番号衝突。後から載った側を空き番号へ振り直す。CLAUDE.md「作業ツリーの安全」節参照）"
            )
        else:
            first_line_of[num] = lineno
    for task_path in sorted(TASKS_DIR.glob("T*.md")):
        name = TASK_FILE_RE.search(task_path.name)
        if not name:
            continue
        heading = next((ln for ln in read_text(task_path).splitlines() if ln.startswith("# ")), "")
        head_num = TASK_HEADING_RE.match(heading)
        if head_num is None:
            violations.append(
                f"docs/tasks/{task_path.name}: 先頭の見出しが「# T{name.group(1)}. …」の形になっていない"
            )
        elif head_num.group(1) != name.group(1):
            violations.append(
                f"docs/tasks/{task_path.name}: 見出しがT{head_num.group(1)}でファイル名と一致しない"
                "（振り直しの置換漏れ、または別タスクの本文で上書きした）"
            )
    return violations


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
    for task_path in sorted(TASKS_DIR.glob("T*.md")):
        name = TASK_FILE_RE.search(task_path.name)
        if not name:
            continue
        heading = next((ln for ln in read_text(task_path).splitlines() if ln.startswith("# ")), "")
        head_num = TASK_HEADING_RE.match(heading)
        if head_num is None:
            violations.append(f"docs/tasks/{task_path.name}: 先頭の見出しが「# T{name.group(1)}. …」の形になっていない")
        elif head_num.group(1) != name.group(1):
            violations.append(
                f"docs/tasks/{task_path.name}: 見出しがT{head_num.group(1)}でファイル名と一致しない"
                "（振り直しの置換漏れ、または別タスクの本文で上書きした）"
            )
    return violations


# --- 文書が定数名の隣へ書いた数値と実装のずれ ---------------------------------
#
# 「`NAME`（600）」のように定数名とその値を並べて書くと、定数を変えたときに文書側は何も
# 壊れない。名前で突き合わせれば値のずれは機械的に分かる。名前の**直後**に現れる数値だけを
# 見る——同じ文の中に別の定数の値が並ぶ書き方が普通にあるため、行内の全数値と比べると
# 誤検知ばかりになる。

CODE_CONSTANT_RE = re.compile(
    r"^\s*(?:export\s+)?(?:const\s+)?(_?[A-Z][A-Z0-9_]{3,})\s*(?::\s*[\w\[\]|, ]+)?\s*=\s*"
    r"(-?\d+(?:\.\d+)?)\s*(?:;|$|#|//)",
    re.M,
)
# 名前のすぐ後ろ（括弧・等号・「は」・コロン）に来る数値。
DOC_CONSTANT_VALUE_RE = re.compile(
    r"(?<![A-Za-z0-9])(_?[A-Z][A-Z0-9_]{3,})(?![A-Za-z0-9_])`?\s*(?:[（(=＝:：]|は)\s*(-?\d+(?:\.\d+)?)")
# 単位の読み替え（秒↔分・ミリ秒↔秒・秒↔時間）。文書は人が読む単位で書くことがある。
CONSTANT_UNIT_FACTORS = (1.0, 60.0, 1000.0, 3600.0, 0.001, 1.0 / 60.0)
# 当時の記録（書き換えない文書）。現在の値と違っていて正しい。
HISTORY_EXEMPT_DOC_PREFIXES = (
    ".claude/commands/review/history/",
    "docs/improvement-plan-archive/",
    "docs/tasks/",
)


def code_numeric_constants(files: list[str]) -> dict[str, tuple[str, float]]:
    out: dict[str, tuple[str, float]] = {}
    for f in files:
        if not f.endswith((".py", ".ts", ".tsx")) or "/types/generated/" in f:
            continue
        path = REPO_ROOT / f
        if not path.exists():
            continue
        for m in CODE_CONSTANT_RE.finditer(read_text(path)):
            out.setdefault(m.group(1), (f, float(m.group(2))))
    return out


def find_doc_constant_drift(files: list[str], scope: list[str] | None = None) -> list[str]:
    """文書が定数名の直後へ書いた数値が、実装の値と合わない箇所。"""
    constants = code_numeric_constants(files)
    if not constants:
        return []
    out: list[str] = []
    for f in sorted(set(scope if scope is not None else files)):
        if not f.endswith(".md") or f.startswith(HISTORY_EXEMPT_DOC_PREFIXES):
            continue
        path = REPO_ROOT / f
        if not path.exists():
            continue
        for lineno, line in enumerate(read_text(path).splitlines(), 1):
            for name, written in DOC_CONSTANT_VALUE_RE.findall(line):
                if name not in constants:
                    continue
                src, actual = constants[name]
                if any(abs(float(written) * factor - actual) < 1e-9 for factor in CONSTANT_UNIT_FACTORS):
                    continue
                out.append(
                    f"{f}:{lineno}: `{name}` を {written} と書いているが実装は {actual:g}（{src}）")
    return out


# --- 現在の軸定義に無いaxis_idを現行として名指しする箇所 -----------------------
#
# 軸はDBの行データで、軸スタジオのGUIから追加・削除できる。GUIで作り直した軸は生成された
# 別のaxis_idを持つため、**軸そのものは今もあるのに、コード・文書が名指ししているidだけが
# 消える**。デプロイを伴わない操作なのでどこも壊れず、説明だけが静かに嘘になる
# （`dead_identifier_refs`はソース中の綴りを実在と見なすため、コメントで言及され続けている
# 軸idは「実在する」側へ数える）。正本はスナップショット（実DBのダンプ）に置く。

AXIS_SNAPSHOT = "backend/fixtures/axis_definitions_snapshot.json"
AXIS_ID_USE_RE = re.compile(r'axis_id\s*[:=]\s*"([a-z][a-z0-9_]+)"')
# 説明の中で現行として名指しされうるのは複合語の軸idだけ。1語のidは普通名詞と区別できない。
AXIS_MENTION_TARGET_DOCS = ("docs/modules/", "CLAUDE.md", ARCHITECTURE_DOC)


def live_axis_ids() -> set[str]:
    try:
        snapshot = json.loads(read_text(REPO_ROOT / AXIS_SNAPSHOT))
    except (OSError, json.JSONDecodeError):
        return set()
    return {entry["definition"]["axis_id"] for entry in snapshot.get("axes", [])}


def historical_axis_ids() -> frozenset[str]:
    """スナップショットのgit履歴から、これまでに実DBへ存在した軸idを集める。

    現行ソースの`axis_id="…"`だけを母集団にすると、**コードから完全に消えたidは母集団に
    入らない**——検査を書いた時点の実例を写した母集団と同じ形で、差が観測できるのは
    見逃した後になる（設計原則 構造仕様12）。「実際にDBへ存在したidの全体」という性質から
    導く。

    **限界**: スナップショット導入より前に廃止された軸は履歴に無い（例:
    `car_stress_bicycle_infra_adjustment`）。母集団を綴りの形から導く案も測ったが、
    材料id・テーブル名・サービス名が軸idと同じ命名規則を共有するため誤検知が
    実測117件（コメント内に限っても50件）になり採らなかった（docs/tasks/T871.md）。
    """
    # REPO_ROOTはmutateが一時worktreeへ差し替えるため、キャッシュのキーに含める。
    return _historical_axis_ids(str(REPO_ROOT))


# スナップショットの差分に現れた軸id。各リビジョンを`git show`で取り直すと、改訂の数だけ
# プロセスを起動して`docs`が数秒遅くなる（実測: 19改訂で3.7秒 → この形なら0.3秒。
# 得られる集合は同じ）。
SNAPSHOT_AXIS_ID_IN_DIFF_RE = re.compile(r'^[+-]\s*"axis_id":\s*"([a-z][a-z0-9_]+)"', re.M)


@functools.lru_cache(maxsize=4)
def _historical_axis_ids(repo_root: str) -> frozenset[str]:
    try:
        patch = git("log", "-p", "--format=", "--", AXIS_SNAPSHOT)
    except (RuntimeError, OSError):
        # gitの外（テストの一時ディレクトリ等）では履歴を辿れない。現行ソース由来の
        # 母集団だけで判定を続ける。
        return frozenset()
    return frozenset(SNAPSHOT_AXIS_ID_IN_DIFF_RE.findall(patch))


def removed_axis_ids(files: list[str]) -> set[str]:
    """軸idとして書かれた綴りのうち、現在のスナップショットに無いもの。

    母集団は2つの経路から作る: 現行ソースの`axis_id="…"`（テストのフィクスチャも含める
    ——消えたidを最後まで名指ししているのはたいていテスト）と、スナップショットの
    git履歴（`historical_axis_ids`。コードから完全に消えたidを拾う唯一の経路）。
    """
    live = live_axis_ids()
    if not live:
        return set()
    mentioned: set[str] = set(historical_axis_ids())
    for f in files:
        if not f.endswith((".py", ".ts", ".tsx")) or "/types/generated/" in f:
            continue
        path = REPO_ROOT / f
        if path.exists():
            mentioned |= set(AXIS_ID_USE_RE.findall(read_text(path)))
    return {a for a in mentioned - live if "_" in a}


# コメントの折り返しで次の行の頭に付く飾り（`#`・`*`・`//`と空白）。
COMMENT_WRAP_PREFIX_RE = re.compile(r"^[#*/\s]*")
COMMENT_WRAP_JOIN_RE = re.compile(r"\n[#*/\s]*")


def find_removed_axis_mentions(files: list[str], scope: list[str] | None = None) -> list[str]:
    """現在の軸定義に無いaxis_idを、現行の説明（docs/modules・architecture.md・実装）が名指し。

    .mdは段落に撤去の断りがあれば免除する（`paragraphs_with_removal_marker`、
    architecture.mdの既存の扱いと同じ単位）。実装コードのコメントは免除しない——
    撤去済みの名前を語る経緯コメント自体が`docs/comments.md`で禁じられている。
    """
    gone = removed_axis_ids(files)
    if not gone:
        return []
    # 全idを1本の選択肢へまとめ、1行につき1回の走査で済ませる。id1本ずつ`re.search`を
    # 回すと 行数×id数 のオーダーになり、全件モードで数十秒かかる。
    any_axis_re = re.compile(
        r"(?<![A-Za-z0-9_])(" + "|".join(re.escape(a) for a in sorted(gone)) + r")(?![A-Za-z0-9_])")
    candidates = scope if scope is not None else files
    out: list[str] = []
    for f in sorted(set(candidates)):
        is_doc = f.endswith(".md") and f.startswith(AXIS_MENTION_TARGET_DOCS)
        is_impl = f.startswith(IMPL_INCLUDE_PREFIXES) and is_impl_file(f)
        if not (is_doc or is_impl):
            continue
        path = REPO_ROOT / f
        if not path.exists():
            continue
        text = read_text(path)
        # 綴りがファイル内に1つも無ければ、行ごとの照合そのものが要らない。折り返しで
        # 割れた綴りを落とさないよう、実装側は下の`joined`と同じ規則で改行を畳んだ姿で
        # 見る（隣り合う2行の連結は、全行を畳んだ文字列の部分文字列になる）。
        probe = text if is_doc else COMMENT_WRAP_JOIN_RE.sub("", text)
        if not any(axis_id in probe for axis_id in gone):
            continue
        exempt = paragraphs_with_removal_marker(f) if is_doc else set()
        source_lines = text.splitlines()
        for lineno, line in enumerate(source_lines, 1):
            if lineno in exempt:
                continue
            # 実装コードのコメントは折り返しで識別子が2行に割れる。次の行の続きも繋いだ形で
            # 照合する（行単位だけを見ると、長いidほど検出から漏れる）。.mdは段落単位の
            # 免除判定があるため繋がない——繋ぐと段落をまたぎ、免除された段落の先頭が
            # 直前の段落の末尾行として報告される。
            joined = [line]
            if not is_doc and lineno < len(source_lines):
                joined.append(line + COMMENT_WRAP_PREFIX_RE.sub("", source_lines[lineno]))
            hit = {m.group(1) for c in joined for m in any_axis_re.finditer(c)}
            for axis_id in sorted(hit):
                out.append(
                    f"{f}:{lineno}: 現在の軸定義に無いaxis_id `{axis_id}` を現行として名指ししている"
                    "（軸スタジオで作り直されて別idになっている場合も含む）")
    return out


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
    "source_comment_dead_identifier_refs": frozenset({"staged", "since", "full"}),
    "narrative": frozenset({"staged", "since", "full"}),
    # 既存分の一掃（T567）が終わるまで、全件スキャンでは参考表示に留める。
    "source_narrative": frozenset({"staged", "since"}),
    "redis_skeleton": frozenset({"staged", "since", "full"}),
    "bare_basemodel": frozenset({"staged", "since", "full"}),
    "module_redefinition": frozenset({"staged", "since", "full"}),
    "web_layer_batch_import": frozenset({"staged", "since", "full"}),
    "undeclared_dead_refs": frozenset({"staged", "since", "full"}),
    # 免除した段落の中身は常に参考表示（0件で黙らないためのもので、ブロックはしない）。
    "undeclared_dead_refs_exempted": frozenset(),
    "undocumented_files": frozenset({"staged", "since", "full"}),
    "plan_vs_tasks": frozenset({"staged", "since", "full"}),
    "task_numbering": frozenset({"staged", "since", "full"}),
    "dead_doc_links": frozenset({"staged", "since", "full"}),
    "undefined_css_tokens": frozenset({"staged", "since", "full"}),
    "vacuous_test_loops": frozenset({"staged", "since", "full"}),
    "removed_axis_mentions": frozenset({"staged", "since", "full"}),
    "doc_constant_drift": frozenset({"staged", "since", "full"}),
    "review_doc_dead_refs": frozenset({"staged", "since", "full"}),
    "cross_file_env_writes": frozenset({"staged", "since", "full"}),
    "way_tag_allowlist": frozenset({"staged", "since", "full"}),
    "map_redraw_coverage": frozenset({"staged", "since", "full"}),
    # 参考表示のみ。誤検出が多く（実測はdocs/tasks/T824.md）ブロックには使えないが、
    # 書いた本人の目へ入れるだけで直せる型のため、追加行に対してだけ出す。
    "count_narrative": frozenset(),
    # 参考表示のみ（README「記載粒度」節は1リンクまで許可）。
    "task_links": frozenset(),
    # 参考表示のみ。節が完了済みフォローアップの記録であることもあり、残りかどうかは
    # 人にしか分からない（docs/tasks/T751.md）。[x]化の瞬間に目へ入れるのが目的。
    "unfiled_deferrals": frozenset(),
    # 参考表示のみ。同じ名前でも記録する呼び出しが違えば分けるのが正しいことがあり、
    # 人にしか決められない（docs/tasks/T771.md）。書く前に既存へ気づくのが目的。
    "duplicate_test_scaffold": frozenset(),
    # 参考表示のみ。近い語を持つ2件を別々に進めるのが正しいこともあり、人にしか決められない。
    # 起票の瞬間に既存の未完了エントリへ目を向けるのが目的。
    "plan_entry_overlap": frozenset(),
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
    # (検知器キー, 見出し, 行)。`--only`で選ばれなかった検知器は行がNoneになり、計算も
    # 出力もされない——キーだけは配線の検査へ残す。`mutate`は1回の実行で1つの検知器しか
    # 見ないため、他の検知器のためにソース全文を読み直す必要がない。
    sections: list[tuple[str, str, list[str] | None]] = []
    only = getattr(args, "only", None)

    def add(key: str, title: str, compute: "Callable[[], list[str]]") -> None:
        sections.append((key, title, None if (only and key != only) else compute()))

    if args.staged:
        staged = [l for l in git("diff", "--cached", "--name-only").splitlines() if l]
        doc_lines = diff_added_lines("docs/modules/*.md")
        doc_lines = {k: v for k, v in doc_lines.items() if not k.endswith("README.md")}
        added = [l for l in git("diff", "--cached", "--name-only", "--diff-filter=A").splitlines() if l]
        add("dead_file_refs", "docs/modules の死んだ参照（ステージ済み追加行）",
            lambda: find_dead_file_refs(doc_lines, files + added))
        add("dead_identifier_refs", "docs/modules の死んだ識別子参照（ステージ済み追加行）",
            lambda: find_dead_identifier_refs(doc_lines, source_corpus(files + added),
                                                   include_fenced=True))
        add("narrative", "docs/modules の記載粒度違反（ステージ済み追加行）",
            lambda: find_narrative_violations(doc_lines))
        source_lines = gather_added_source_lines(None)
        add("source_narrative", "ソースコードの経緯コメント（ステージ済み追加行、docs/comments.md参照）",
            lambda: find_source_narrative_violations(source_lines))
        add("redis_skeleton", "Redis骨格の自前実装（ステージ済み追加行、docs/caching.md参照）",
            lambda: find_redis_skeleton_violations(source_lines))
        add("bare_basemodel", "素のBaseModel継承（ステージ済み追加行、docs/tasks/T721.md参照）",
            lambda: find_bare_basemodel_violations(source_lines))
        add("module_redefinition", "モジュール直下で同じ名前を2回定義（ステージ済み.py、docs/tasks/T883.md参照）",
            lambda: find_module_level_redefinitions(python_sources(diff_added_lines("*.py"))))
        add("web_layer_batch_import", "webアプリが読む層からのapp.batchのトップレベルimport（ステージ済み追加行、docs/tasks/T814.md参照）",
            lambda: find_web_layer_batch_imports(source_lines))
        add("way_tag_allowlist", "許可リストに無いタグキーをway_tagsから読む（ステージ済み追加行、docs/tasks/T753.md参照）",
            lambda: find_way_tag_allowlist_violations(source_lines))
        add("map_redraw_coverage", "map.setStyle()後の再描画から辿れないレイヤー（docs/tasks/T825.md参照）",
            lambda: find_map_redraw_gaps())
        add("count_narrative", "個数を書いている行（参考、ステージ済み追加行、docs/documentation.md参照）",
            lambda: find_count_narratives(source_lines, diff_added_lines("docs/*.md")))
        arch_lines = diff_added_lines(ARCHITECTURE_DOC)
        add("undeclared_dead_refs", "architecture.md が撤去済みの名前を断りなく名指し（ステージ済み追加行）",
            lambda: find_undeclared_dead_refs(arch_lines, files + added, source_corpus(files + added), revision=""))
        add("undeclared_dead_refs_exempted", "architecture.md の免除した段落の中に残る実在しない名前（参考、ステージ済み追加行）",
            lambda: find_dead_refs_inside_exempted_paragraphs(
                arch_lines, files + added, source_corpus(files + added), revision=""))
        add("undocumented_files", "新規実装ファイルの docs/modules 記載漏れ（ステージ済み新規ファイル）",
            lambda: find_undocumented_files(added, modules_text, files + added))
        add("plan_vs_tasks", "improvement-plan.md [x]/[ ] と docs/tasks「状態:」の不一致",
            lambda: check_plan_vs_tasks())
        add("task_numbering", "タスク番号の衝突・台帳と見出しのずれ",
            lambda: check_task_numbering())
        add("unfiled_deferrals", "[x]化したタスクの、別タスクへ渡していない残り（参考、人が判断する）",
            lambda: find_unfiled_deferrals(None))
        add("plan_entry_overlap", "新しく足した未完了エントリと語が重なる既存エントリ（参考、人が判断する）",
            lambda: find_plan_entry_overlap(
                [l for _, l in diff_added_lines(PLAN_DOC).get(PLAN_DOC, [])],
                git("show", f"HEAD:{PLAN_DOC}", check=False) or read_text(REPO_ROOT / PLAN_DOC)))
        md_staged = [s for s in staged if s.endswith(".md")]
        add("dead_doc_links", "history/・docs/tasks への死んだリンク（ステージ済み.md）",
            lambda: check_dead_doc_links(md_staged))
        add("undefined_css_tokens", "未定義のCSSトークン（ステージ済み.css/.ts/.tsx）",
            lambda: find_undefined_css_tokens(
                             [s for s in staged if s.endswith(CSS_TOKEN_SCAN_SUFFIXES)], files + added))
        add("vacuous_test_loops", "空の母集団でも通るテストのループ（ステージ済みテスト）",
            lambda: find_vacuous_test_loops(staged + added, revision=""))
        add("removed_axis_mentions", "現在の軸定義に無いaxis_idを現行として名指し（ステージ済み）",
            lambda: find_removed_axis_mentions(files + added, scope=staged + added))
        add("doc_constant_drift", "文書が書いた定数値と実装のずれ（ステージ済み.md）",
            lambda: find_doc_constant_drift(files + added, scope=md_staged))
        add("review_doc_dead_refs", "レビュー手順書の死んだ識別子参照（ステージ済み）",
            lambda: find_review_doc_dead_refs(files + added, scope=md_staged))
        add("cross_file_env_writes", "テストが書き換える環境変数を他の実装も読む（docs/testing.md参照）",
            lambda: find_cross_file_env_writes(files + added))
        add("source_comment_dead_identifier_refs", "ソースコードのコメントが名指しする死んだ識別子（ステージ済み）",
            lambda: find_source_comment_dead_identifier_refs(files + added, scope=staged + added))
    else:
        doc_lines = {rel(p): list(enumerate(read_text(p).splitlines(), 1)) for p in all_docs}
        add("dead_file_refs", "docs/modules の死んだ参照（全件）",
            lambda: find_dead_file_refs(doc_lines, files))
        add("dead_identifier_refs", "docs/modules の死んだ識別子参照（全件）",
            lambda: find_dead_identifier_refs(doc_lines, source_corpus(files),
                                                   include_fenced=True))
        add("source_comment_dead_identifier_refs", "ソースコードのコメントが名指しする死んだ識別子（全件）",
            lambda: find_source_comment_dead_identifier_refs(files))
        add("narrative", "docs/modules の記載粒度違反（全件）",
            lambda: find_narrative_violations(doc_lines))
        add("task_links", "docs/modules の Txxx リンク（参考、README「記載粒度」節は1リンクまで許可）",
            lambda: count_task_links(doc_lines))
        arch_path = REPO_ROOT / ARCHITECTURE_DOC
        if args.since:
            added = [l for l in git("diff", "--diff-filter=A", "--name-only", f"{args.since}..HEAD").splitlines() if l]
            title = f"新規実装ファイルの docs/modules 記載漏れ（{args.since} 以降の新規ファイル）"
            # 経緯コメント・architecture.mdの断りなき名指しはいずれも既存分が残る
            # （T567・T724）。--sinceで新規追加分だけに絞れる場合のみ違反件数へ含める。
            source_lines = gather_added_source_lines(args.since)
            add("source_narrative", f"ソースコードの経緯コメント（{args.since} 以降の追加行、docs/comments.md参照）",
                lambda: find_source_narrative_violations(source_lines))
            arch_since = diff_added_lines(ARCHITECTURE_DOC, args.since)
            add("undeclared_dead_refs", f"architecture.md が撤去済みの名前を断りなく名指し（{args.since} 以降の追加行）",
                lambda: find_undeclared_dead_refs(arch_since, files, source_corpus(files), revision="HEAD"))
            add("undeclared_dead_refs_exempted", f"architecture.md の免除した段落の中に残る実在しない名前（参考、{args.since} 以降の追加行）",
                lambda: find_dead_refs_inside_exempted_paragraphs(arch_since, files, source_corpus(files), revision="HEAD"))
        else:
            added = files
            title = "実装ファイルの docs/modules 記載漏れ（全件）"
            all_source_lines = {
                rel(p): list(enumerate(read_text(p).splitlines(), 1))
                for p in (REPO_ROOT / f for f in files if is_impl_file(f))
                if p.exists()
            }
            source_lines = all_source_lines
            add("source_narrative", "ソースコードの経緯コメント（参考、全件。新規分の強制は--staged/--since参照）",
                lambda: find_source_narrative_violations(all_source_lines))
            arch_all = {ARCHITECTURE_DOC: list(enumerate(read_text(arch_path).splitlines(), 1))}
            add("undeclared_dead_refs", "architecture.md が撤去済みの名前を断りなく名指し（全件）",
                lambda: find_undeclared_dead_refs(arch_all, files, source_corpus(files)))
            add("undeclared_dead_refs_exempted", "architecture.md の免除した段落の中に残る実在しない名前（参考、全件）",
                lambda: find_dead_refs_inside_exempted_paragraphs(arch_all, files, source_corpus(files)))
        add("undocumented_files", title,
            lambda: find_undocumented_files(added, modules_text, files))
        add("redis_skeleton", "Redis骨格の自前実装（docs/caching.md参照）",
            lambda: find_redis_skeleton_violations(source_lines))
        add("module_redefinition", "モジュール直下で同じ名前を2回定義（全件、docs/tasks/T883.md参照）",
            lambda: find_module_level_redefinitions(python_sources(files)))
        add("bare_basemodel", "素のBaseModel継承（全件、docs/tasks/T721.md参照）",
            lambda: find_bare_basemodel_violations({
                             rel(p): list(enumerate(read_text(p).splitlines(), 1))
                             for p in (REPO_ROOT / f for f in files if f.startswith("backend/app/"))
                             if p.exists()
                         }))
        add("web_layer_batch_import", "webアプリが読む層からのapp.batchのトップレベルimport（全件、docs/tasks/T814.md参照）",
            lambda: find_web_layer_batch_imports({
                             rel(p): list(enumerate(read_text(p).splitlines(), 1))
                             for p in (REPO_ROOT / f for f in files if f.startswith("backend/app/"))
                             if p.exists()
                         }))
        add("way_tag_allowlist", "許可リストに無いタグキーをway_tagsから読む（全件、docs/tasks/T753.md参照）",
            lambda: find_way_tag_allowlist_violations({
                             rel(REPO_ROOT / f): list(enumerate(read_text(REPO_ROOT / f).splitlines(), 1))
                             for f in MATERIAL_TAG_READER_FILES
                             if (REPO_ROOT / f).exists()
                         }))
        add("map_redraw_coverage", "map.setStyle()後の再描画から辿れないレイヤー（全件、docs/tasks/T825.md参照）",
            lambda: find_map_redraw_gaps())
        add("duplicate_test_scaffold", "同じ名前のテスト足場が複数ファイルにある（参考、docs/tasks/T771.md参照）",
            lambda: find_duplicate_test_scaffolds([f for f in files if f.endswith(".test.ts") or f.endswith(".test.tsx")]),)
        add("plan_vs_tasks", "improvement-plan.md [x]/[ ] と docs/tasks「状態:」の不一致",
            lambda: check_plan_vs_tasks())
        add("task_numbering", "タスク番号の衝突・台帳と見出しのずれ",
            lambda: check_task_numbering())
        if args.since:
            add("unfiled_deferrals", f"[x]化したタスクの、別タスクへ渡していない残り（{args.since} 以降、参考、人が判断する）",
                lambda: find_unfiled_deferrals(args.since))
        md_files = [f for f in files if f.endswith(".md") and (f.startswith((".claude/", "docs/")) or f == "CLAUDE.md")]
        add("dead_doc_links", "history/・docs/tasks への死んだリンク（.claude・docs 全件）",
            lambda: check_dead_doc_links(md_files))
        add("undefined_css_tokens", "未定義のCSSトークン（全件）",
            lambda: find_undefined_css_tokens(files, files))
        if args.since:
            changed = [l for l in git("diff", "--name-only", f"{args.since}..HEAD").splitlines() if l]
            add("vacuous_test_loops", f"空の母集団でも通るテストのループ（{args.since} 以降に変更されたテスト）",
                lambda: find_vacuous_test_loops(changed, revision="HEAD"))
            add("removed_axis_mentions", f"現在の軸定義に無いaxis_idを現行として名指し（{args.since} 以降に変更されたファイル）",
                lambda: find_removed_axis_mentions(files, scope=changed))
            add("doc_constant_drift", f"文書が書いた定数値と実装のずれ（{args.since} 以降に変更された.md）",
                lambda: find_doc_constant_drift(files, scope=changed))
            add("review_doc_dead_refs", f"レビュー手順書の死んだ識別子参照（{args.since} 以降に変更された.md）",
                lambda: find_review_doc_dead_refs(files, scope=changed))
            add("cross_file_env_writes", "テストが書き換える環境変数を他の実装も読む（docs/testing.md参照）",
                lambda: find_cross_file_env_writes(files))
            add("map_redraw_coverage", "map.setStyle()後の再描画から辿れないレイヤー（docs/tasks/T825.md参照）",
                lambda: find_map_redraw_gaps())
            add("count_narrative", f"個数を書いている行（参考、{args.since} 以降の追加行、docs/documentation.md参照）",
                lambda: find_count_narratives(gather_added_source_lines(args.since),
                                                   diff_added_lines("docs/*.md", args.since)))
        else:
            add("vacuous_test_loops", "空の母集団でも通るテストのループ（全件）",
                lambda: find_vacuous_test_loops(files))
            add("removed_axis_mentions", "現在の軸定義に無いaxis_idを現行として名指し（全件）",
                lambda: find_removed_axis_mentions(files))
            add("doc_constant_drift", "文書が書いた定数値と実装のずれ（全件）",
                lambda: find_doc_constant_drift(files))
            add("review_doc_dead_refs", "レビュー手順書の死んだ識別子参照（全件）",
                lambda: find_review_doc_dead_refs(files))
            add("cross_file_env_writes", "テストが書き換える環境変数を他の実装も読む（全件、docs/testing.md参照）",
                lambda: find_cross_file_env_writes(files))

    total = 0
    for key, title, lines in sections:
        if lines is None:
            continue
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

    # 前回も発火して、個別閾値も付いていないファイル。分類（KEEP/分割/閾値付きKEEP）の
    # いずれも実行されなかったということで、安全弁が鳴りっぱなしになっている
    # （「結果ファイルへ次閾値を書いただけで`thresholds`へ書き戻さない」が実際の失敗の形）。
    stuck = [f for f in fired if f in set(baseline.get("fired", [])) and f not in thresholds]
    if stuck:
        print()
        print(f"## 2回連続で発火し、個別閾値も付いていない: {', '.join(stuck)}")
        print("前回の分類が`thresholds`へ書き戻されていないか、分割が実行されていない。"
              "どちらかを行うまで毎回同じファイルが発火し続ける（complexity.md「規模ウォッチ」節）。")

    if args.update:
        new = {
            "date": dt.date.today().isoformat(),
            "commit": git("rev-parse", "--short", "HEAD").strip(),
            "top": sorted(cur_top),
            "files": {f: counts[f] for f in watched if f in counts},
            "fired": sorted(fired),
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
# jscpdは既定で1,000行・100KBを超えるファイルを走査から外す。大きいファイルほど
# 「同じものが少しずつ増えた」結果である確率が高いのに、そこだけが対象外になる。
# 上限は上げてもいつか再び当たるもので、当たったことが出力に現れないと「クローン0件」と
# 「見ていない」が区別できないため、下の`unscanned_target_files`が走査されなかった
# ファイルをその都度導出して報告する。
JSCPD_MAX_LINES = 20_000
JSCPD_MAX_SIZE = "1mb"


def unscanned_target_files(scanned: set[str]) -> list[str]:
    """`JSCPD_TARGETS`の下にあるのに走査されなかったファイル。

    対象の拡張子は持たない。**jscpdが実際に読んだファイルの拡張子**から母集団を導く
    （手で並べると、jscpdが対応形式を増やしたときに検査の側が黙って狭くなる）。
    """
    handled = {Path(name).suffix for name in scanned}
    if not handled:
        return []
    ignored_dirs = {"node_modules", "__pycache__", ".next", "generated"}
    missing: list[str] = []
    for target in JSCPD_TARGETS:
        for root, dirs, files in os.walk(REPO_ROOT / target):
            dirs[:] = [d for d in dirs if d not in ignored_dirs]
            for name in files:
                path = Path(root) / name
                # `--min-lines`に満たないファイルは比べる相手を持ちようがなく、
                # 外れているのが正しい。
                if path.suffix not in handled:
                    continue
                if sum(1 for _ in path.open(encoding="utf-8", errors="ignore")) < JSCPD_MIN_LINES:
                    continue
                rel = path.relative_to(REPO_ROOT).as_posix()
                if rel not in scanned:
                    missing.append(rel)
    return sorted(missing)


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
        "--max-lines", str(JSCPD_MAX_LINES), "--max-size", JSCPD_MAX_SIZE,
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
    scanned = {name for fmt in data.get("statistics", {}).get("formats", {}).values()
               for name in fmt.get("sources", {})}
    unscanned = unscanned_target_files(scanned)
    print(f"- 走査したファイル: {len(scanned)}件"
          + (f" / **走査されなかったファイル: {len(unscanned)}件**" if unscanned else "（対象の取りこぼし無し）"))
    print()
    if unscanned:
        print("走査されなかったファイル（jscpdが黙って外したもの。ここが0件でないうちは、")
        print("クローン件数の前回比を母集団の欠けたまま読むことになる）:")
        print()
        for rel in unscanned:
            print(f"- `{rel}`（{(REPO_ROOT / rel).stat().st_size / 1024:.1f}KB）")
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
REVIEW_CONTEXT_DOC = ".claude/commands/review/context.md"
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
        # 直前に`guard_probe_mutations`が書き換えた後の姿が要るため、内容を保持する
        # `read_text`は使わない。
        text = arch.read_text(encoding="utf-8", errors="replace")
        arch.write_text(
            text.replace(
                f"`{GUARD_PROBE_IDENT}`が現在の実装で値を組み立てる。",
                f"`{GUARD_PROBE_IDENT}`は撤去済み。",
            ),
            encoding="utf-8",
        )

    return {"undeclared_dead_refs": declare_removed_in_worktree_only}


def drifted_constant_probe(wt: Path) -> str:
    """worktreeの中から実装が数値で持つ定数を1つ選ぶ（綴りを固定で書かない）。"""
    saved = globals()["REPO_ROOT"]
    try:
        globals()["REPO_ROOT"] = wt
        constants = code_numeric_constants([
            line for line in subprocess.run(
                ["git", "ls-files"], cwd=str(wt), capture_output=True, text=True,
                encoding="utf-8", errors="replace").stdout.splitlines() if line
        ])
    finally:
        globals()["REPO_ROOT"] = saved
    picked = next((n for n, (_, v) in sorted(constants.items()) if v != 999999), None)
    if picked is None:
        raise RuntimeError("数値の定数が1件も無く、この検知器の違反を作れない")
    return picked


def removed_axis_probe_id(wt: Path) -> str:
    """worktreeの中で「軸idとして書かれたが現在の軸定義には無い」綴りを1つ選ぶ。

    綴りを固定で書かない——検知器の母集団はスナップショットとテストのフィクスチャから
    導出されるため、固定の綴りは母集団が変わった瞬間に違反を作れなくなる。
    """
    saved = globals()["REPO_ROOT"]
    try:
        globals()["REPO_ROOT"] = wt
        gone = removed_axis_ids([
            line for line in subprocess.run(
                ["git", "ls-files"], cwd=str(wt), capture_output=True, text=True,
                encoding="utf-8", errors="replace").stdout.splitlines() if line
        ])
    finally:
        globals()["REPO_ROOT"] = saved
    if not gone:
        raise RuntimeError("現在の軸定義に無いaxis_idが1件も無く、この検知器の違反を作れない")
    return sorted(gone)[0]


def probe_fs(wt: Path) -> tuple[
    "Callable[[Path], str]", "Callable[[Path, str], None]", "Callable[[str, str], None]"
]:
    """プローブがworktreeを書き換えるための道具（読み・追記・新規作成）。

    ここは検査ではなく違反の作り込み側で、同じファイルを書き換えては読み直す。
    `read_text`は1回の実行中の内容を保持するため使わない。
    """

    def live_text(path: Path) -> str:
        return path.read_text(encoding="utf-8", errors="replace")

    def append(path: Path, text: str) -> None:
        path.write_text(live_text(path) + text, encoding="utf-8")

    def write(rel: str, text: str) -> None:
        path = wt / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    return live_text, append, write


def guard_probe_mutations(wt: Path) -> dict[str, "Callable[[], None]"]:
    """検知器キー → その検知器だけが拾うはずの違反を1件作る手順。"""
    module_doc = next(
        p for p in sorted((wt / "docs/modules").rglob("*.md")) if p.name != "README.md"
    )
    arch = wt / ARCHITECTURE_DOC
    plan = wt / "docs/improvement-plan.md"

    live_text, append, write = probe_fs(wt)

    def flip_plan_checkbox() -> None:
        text = live_text(plan)
        m = re.search(r"^- \[ \] \[T(\d{3,4})\]\(tasks/T\d{3,4}\.md\)", text, re.M)
        if m is None:
            raise RuntimeError("docs/improvement-plan.md に未完了行が無く、状態照合を試せない")
        flipped = m.group(0).replace("- [ ]", "- [x]")
        plan.write_text(text[: m.start()] + flipped + text[m.end():], encoding="utf-8")

    def duplicate_plan_number() -> None:
        """既にある未完了エントリと同じ番号のエントリを、別タイトルでもう1行足す。"""
        text = live_text(plan)
        m = re.search(r"^- \[ \] \[T(\d{3,4})\]\(tasks/T\d{3,4}\.md\)", text, re.M)
        if m is None:
            raise RuntimeError("docs/improvement-plan.md に未完了行が無く、番号衝突を試せない")
        clone = f"\n- [ ] [T{m.group(1)}](tasks/T{m.group(1)}.md). 別のセッションが同じ番号で起票した行 規模S\n"
        plan.write_text(text[: m.end()] + clone + text[m.end():], encoding="utf-8")

    return {
        "dead_file_refs": lambda: append(module_doc, "\n存在しない`Map/zzzGuardProbeFile.ts`を参照する。\n"),
        "dead_identifier_refs": lambda: append(module_doc, f"\n`{GUARD_PROBE_IDENT}`が処理する。\n"),
        "narrative": lambda: append(module_doc, "\n以前はこの方式ではなく別の形だった。\n"),
        "dead_doc_links": lambda: append(module_doc, "\n詳細は[T9999](../../tasks/T9999.md)参照。\n"),
        "undeclared_dead_refs": lambda: append(arch, f"\n`{GUARD_PROBE_IDENT}`が現在の実装で値を組み立てる。\n"),
        "plan_vs_tasks": flip_plan_checkbox,
        "task_numbering": duplicate_plan_number,
        # 参考出力なのでDETECTOR_ENFORCEMENTは空だが、違反の作り方は定義しておく
        # （`mutate --case`で単体で試せるようにするため）。
        "undeclared_dead_refs_exempted": lambda: append(
            arch, f"\n`zzzGoneName`は撤去済み。`{GUARD_PROBE_IDENT}`が現在の実装で値を組み立てる。\n"),
        "source_narrative": lambda: write(
            GUARD_PROBE_TS, "// 改善計画T999でこの形に変更した。\nexport const zzzGuardProbe = 1;\n"),
        "source_comment_dead_identifier_refs": lambda: write(
            GUARD_PROBE_TS,
            f"// `{GUARD_PROBE_IDENT}`が処理する。\nexport const zzzGuardProbe = 1;\n"),
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
        "module_redefinition": lambda: write(
            GUARD_PROBE_PY, "zzz_guard_probe = 1\n\n\nzzz_guard_probe = 1\n"),
        "web_layer_batch_import": lambda: write(
            GUARD_PROBE_PY,
            "from app.batch.precompute_way_landcover import ALGORITHM_VERSION\n\n\n"
            "zzz_guard_probe = ALGORITHM_VERSION\n"),
        # 再描画から辿れない位置へ、sourceを作る描画を1つ足す。
        "map_redraw_coverage": lambda: append(
            wt / MAP_REDRAW_FILE,
            '\nexport function zzzGuardProbeLayer(map: MapLibreMap) {\n'
            '  map.addSource("zzz-guard-probe", { type: "geojson", data: EMPTY_FEATURE_COLLECTION });\n'
            '}\n'),
        "way_tag_allowlist": lambda: append(
            wt / "backend/app/domain/axis_inspector.py",
            '\n\ndef _zzz_guard_probe(tags: dict[str, str]) -> str | None:\n    return tags.get("zzz_guard_probe")\n'),
        "review_doc_dead_refs": lambda: append(
            wt / REVIEW_CONTEXT_DOC, f"\n- `{GUARD_PROBE_IDENT}`が評価の値を組み立てる。\n"),
        "doc_constant_drift": lambda: append(
            module_doc, f"\n`{drifted_constant_probe(wt)}`（999999）がこの値を決める。\n"),
        "removed_axis_mentions": lambda: append(
            module_doc, f"\n`{removed_axis_probe_id(wt)}`の色分けは現行の実装が組み立てる。\n"),
        # 既存の実装（lib/apiBaseUrl.ts）が読む環境変数を、別のテストが書き換える形。
        # 実装側を足さずに済むよう、既に読まれている名前を使う。
        "cross_file_env_writes": lambda: write(
            GUARD_PROBE_TEST_TS,
            'import { it } from "vitest";\n\n'
            'it("zzz guard probe", () => {\n'
            '  process.env.NEXT_PUBLIC_API_URL = "https://example.test";\n'
            "});\n"),
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


class EdgeProbe(NamedTuple):
    """母集団の**外縁**へ置く違反（ネガティブケース）。

    `where`は母集団のどの外側かを1行で述べる。`detected`はいまの検知器がそこを拾えるかの
    **期待値**で、Falseは既知の穴。穴が埋まったときも、埋めたはずの穴がまた空いたときも、
    期待値との食い違いとしてこの監査が落ちる。`mode`はその穴が現れる実行経路。
    """

    where: str
    detected: bool
    mutate: "Callable[[], None]"
    mode: str = "staged"


def removed_axis_edge_id(wt: Path) -> str:
    """スナップショット履歴にあり現行の軸定義に無いidのうち、`_`を含まないものを1つ選ぶ。

    `removed_axis_ids`は`_`を含む綴りだけを母集団に採るため、ここで選んだidはその母集団の
    外側に落ちる。綴りを固定で書かない（外側かどうかは履歴から導く）。
    """
    saved = globals()["REPO_ROOT"]
    try:
        globals()["REPO_ROOT"] = wt
        gone = sorted(a for a in (historical_axis_ids() - live_axis_ids()) if "_" not in a)
    finally:
        globals()["REPO_ROOT"] = saved
    if not gone:
        raise RuntimeError("`_`を含まない撤去済みaxis_idが履歴に無く、外縁の違反を作れない")
    return gone[0]


def map_redraw_one_hop_module(wt: Path) -> Path:
    """再描画の入口が直接importしている同ディレクトリのモジュールを1つ選ぶ。

    そこからさらにimportさせれば入口から2ホップになり、1ホップ固定の母集団の外へ出る。
    """
    text = (wt / MAP_REDRAW_FILE).read_text(encoding="utf-8", errors="replace")
    for name in re.findall(r'from "\./([A-Za-z0-9_.]+)"', text):
        path = (wt / MAP_REDRAW_FILE).parent / f"{name}.ts"
        if path.exists():
            return path
    raise RuntimeError("再描画の入口が同ディレクトリの.tsをimportしておらず、2ホップを作れない")


def guard_probe_edges(wt: Path) -> dict[str, "EdgeProbe | str"]:
    """検知器キー → 母集団の外縁に置く違反、または外縁が無いことの宣言（その理由）。

    正例（`guard_probe_mutations`）は母集団の**内側**へ違反を置くため、母集団が狭すぎる
    ことを原理的に検出できない——プローブの素材そのものを母集団から取っている検知器では
    なおさらで、落ちるidはプローブにも選ばれない。外縁のケースは「拾うべきなのに今の
    母集団へ入らない位置」を1件ずつ固定し、穴が空いているかどうかを毎回測る。
    """
    _, append, write = probe_fs(wt)
    module_doc = next(
        p for p in sorted((wt / "docs/modules").rglob("*.md")) if p.name != "README.md"
    )
    module_readme = wt / "docs/modules/README.md"
    ident = GUARD_PROBE_IDENT

    def comment_only_identifier_in(doc: Path) -> "Callable[[], None]":
        """実装のコメントにしか無い名前を作り、`doc`がそれを現行として名指しする。"""

        def run() -> None:
            write(GUARD_PROBE_TS, f"// {ident}が値を組み立てる。\nexport const zzzGuardProbe = 1;\n")
            append(doc, f"\n`{ident}`が処理する。\n")

        return run

    def rename_documented_impl_file() -> None:
        """記載済みの実装ファイルを改名する（追加ではないため`--diff-filter=A`に出ない）。"""
        listed = subprocess.run(
            ["git", "ls-files", "frontend/src/lib"], cwd=str(wt), capture_output=True,
            text=True, encoding="utf-8", errors="replace").stdout.splitlines()
        picked = next((f for f in sorted(listed) if f.endswith(".ts") and ".test." not in f), None)
        if picked is None:
            raise RuntimeError("改名できる実装ファイルが無く、外縁の違反を作れない")
        subprocess.run(["git", "mv", picked, picked.replace(".ts", "ZzzGuardProbe.ts")],
                       cwd=str(wt), capture_output=True, text=True)

    def two_hop_layer() -> None:
        """入口から2ホップの位置へ、sourceを作る描画を1つ足す。"""
        probe = "frontend/src/components/Map/zzzGuardProbeLayers.ts"
        write(probe, 'import type { Map as MapLibreMap } from "maplibre-gl";\n\n'
                     "export function zzzGuardProbeLayer(map: MapLibreMap) {\n"
                     '  map.addSource("zzz-guard-probe", { type: "geojson", data: null });\n'
                     "}\n")
        hop = map_redraw_one_hop_module(wt)
        append(hop, '\nimport { zzzGuardProbeLayer } from "./zzzGuardProbeLayers";\n'
                    "export const zzzGuardProbeRef = zzzGuardProbeLayer;\n")

    return {
        "dead_file_refs": EdgeProbe(
            "docs/modules/README.md（名前で母集団から外れる）", False,
            lambda: append(module_readme, "\n存在しない`Map/zzzGuardProbeFile.ts`を参照する。\n")),
        "dead_identifier_refs": EdgeProbe(
            "実装のコメントにしか無い名前（実在判定corpusがコメント込み）", False,
            comment_only_identifier_in(module_doc)),
        "undeclared_dead_refs": EdgeProbe(
            "実装のコメントにしか無い名前（実在判定corpusがコメント込み）", False,
            comment_only_identifier_in(wt / ARCHITECTURE_DOC)),
        "source_comment_dead_identifier_refs": EdgeProbe(
            "バッククォートを付けずに綴った死んだ識別子", False,
            lambda: write(GUARD_PROBE_TS,
                          f"// {ident}が処理する。\nexport const zzzGuardProbe = 1;\n")),
        "narrative": EdgeProbe(
            "docs/modules/README.md（名前で母集団から外れる）", False,
            lambda: append(module_readme, "\n以前はこの方式ではなく別の形だった。\n")),
        "source_narrative": EdgeProbe(
            "backend/scripts/（実装の母集団はbackend/app・frontend/srcのみ）", False,
            lambda: write("backend/scripts/zzz_guard_probe.py",
                          "# 改善計画T999でこの形に変更した。\nzzz_guard_probe = 1\n")),
        "redis_skeleton": EdgeProbe(
            "backend/scripts/（バッチ補助もRedisを触りうる）", False,
            lambda: write("backend/scripts/zzz_guard_probe.py",
                          "from app.infrastructure.redis_client import get_redis_client_or_none\n\n\n"
                          "async def zzz_guard_probe():\n    return get_redis_client_or_none()\n")),
        "bare_basemodel": EdgeProbe(
            "backend/app配下の__init__.py（is_impl_fileが除外する）", False,
            lambda: write("backend/app/zzz_guard_probe/__init__.py",
                          "from pydantic import BaseModel\n\n\nclass ZzzGuardProbe(BaseModel):\n    value: int = 0\n")),
        "module_redefinition": EdgeProbe(
            "backend/benchmarks/（MODULE_REDEFINITION_PREFIXESの手書き4つの外）", False,
            lambda: write("backend/benchmarks/zzz_guard_probe.py",
                          "zzz_guard_probe = 1\n\n\nzzz_guard_probe = 1\n")),
        "web_layer_batch_import": EdgeProbe(
            "backend/app/main.py（WEB_LAYER_DIRSの手書き4つの外）", False,
            lambda: append(wt / "backend/app/main.py",
                           "\n\nfrom app.batch.precompute_way_landcover import ALGORITHM_VERSION\n\n"
                           "zzz_guard_probe = ALGORITHM_VERSION\n")),
        "way_tag_allowlist": EdgeProbe(
            "backend/app/domain/hard_filters.py（MATERIAL_TAG_READER_FILESの手書き3本の外）", False,
            lambda: append(wt / "backend/app/domain/hard_filters.py",
                           '\n\ndef _zzz_guard_probe(tags: dict[str, str]) -> str | None:\n'
                           '    return tags.get("zzz_guard_probe")\n')),
        "undocumented_files": EdgeProbe(
            "実装ファイルの改名（追加ではないため--diff-filter=Aに出ない）", False,
            rename_documented_impl_file),
        "dead_doc_links": EdgeProbe(
            "名前は実在するが相対パスが解決しないリンク", False,
            lambda: append(module_doc, "\n詳細は[T889](../tasks/T889.md)参照。\n")),
        "undefined_css_tokens": EdgeProbe(
            "トークンを定義するCSS自身（名前で母集団から外れる）", False,
            lambda: append(wt / GLOBAL_TOKENS_CSS,
                           "\n.zzz-guard-probe {\n  color: var(--zzz-guard-probe-token);\n}\n")),
        "vacuous_test_loops": EdgeProbe(
            "frontend/e2e/*.spec.ts（TEST_FILE_REはtest_*.pyと*.test.ts(x)だけ）", False,
            lambda: write("frontend/e2e/zzzGuardProbe.spec.ts",
                          'import { expect, test } from "@playwright/test";\n\n'
                          'test("zzz guard probe", () => {\n'
                          "  const picked = [1, 2, 3].filter((n) => n > 9);\n"
                          "  for (const n of picked) {\n"
                          "    expect(n).toBeGreaterThan(0);\n"
                          "  }\n"
                          "});\n")),
        "removed_axis_mentions": EdgeProbe(
            "アンダースコアを含まないaxis_id（記法で母集団から外れる）", False,
            lambda: append(module_doc,
                           f"\n`{removed_axis_edge_id(wt)}`の色分けは現行の実装が組み立てる。\n")),
        "doc_constant_drift": EdgeProbe(
            "実装コメントが書いた定数値（母集団は.mdのみ）", False,
            lambda: write(GUARD_PROBE_TS,
                          f"// {drifted_constant_probe(wt)}（999999）がこの値を決める。\n"
                          "export const zzzGuardProbe = 1;\n")),
        "review_doc_dead_refs": EdgeProbe(
            "CLAUDE.md（母集団は.claude/commands/**.mdのみ）", False,
            lambda: append(wt / "CLAUDE.md", f"\n- `{ident}`が評価の値を組み立てる。\n")),
        "cross_file_env_writes": EdgeProbe(
            "backendのテスト（母集団はfrontend/src/**のみ）", False,
            lambda: write("backend/tests/test_zzz_guard_probe.py",
                          "import os\n\n\ndef test_zzz_guard_probe():\n"
                          '    os.environ["DATABASE_URL"] = "postgresql://zzz/guard"\n')),
        "map_redraw_coverage": EdgeProbe(
            "入口から2ホップ先のモジュール（母集団は1ホップ固定）", False, two_hop_layer),
        "plan_vs_tasks": "母集団は台帳の全行とdocs/tasksの全ファイルで、外側が無い",
        "task_numbering": "母集団は台帳の全行とdocs/tasksの全ファイルで、外側が無い",
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
    edge_rows: list[tuple[str, str, str, str]] = []
    try:
        git("worktree", "add", "--detach", "--quiet", str(wt), "HEAD")

        def wt_run(*cmd: str) -> subprocess.CompletedProcess:
            return subprocess.run(cmd, cwd=str(wt), capture_output=True, text=True,
                                  encoding="utf-8", errors="replace")

        # 編集中の検知器を試せるよう、追跡ファイルの未コミット変更をworktreeへ持ち込む。
        diff = git("diff", "HEAD")
        if diff.strip():
            # パッチはバイト列で渡す。テキストで渡すとWindowsで改行がCRLFへ変換され、
            # LFで生成されたパッチの文脈行が1行も一致しなくなる。
            applied = subprocess.run(
                ["git", "apply", "-"], cwd=str(wt), input=diff.encode("utf-8"),
                capture_output=True)
            if applied.returncode != 0:
                print("## 未コミット変更をworktreeへ適用できませんでした（追跡ファイルのみ対象）")
                print(applied.stderr.decode("utf-8", "replace").strip()[:400])
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
                # 見るのはこの検知器の節だけなので、他の検知器のためにソース全文を
                # 読み直させない（1プローブあたりの所要がそのまま42倍になる）。
                proc = wt_run(sys.executable, "scripts/review_checks.py", "docs",
                              "--keys", "--only", key, *check)
                found = probe_section_count(proc.stdout, key)
                if found is None:
                    rows.append((key, "MISS", label, "この経路の検査項目に存在しない"))
                elif found == 0:
                    rows.append((key, "MISS", label, "検査はあるが0件（見逃し）"))
                elif proc.returncode == 0:
                    rows.append((key, "WARN", label, f"{found}件検知するがexit 0（参考扱い）"))
                else:
                    rows.append((key, "PASS", label, f"{found}件 exit={proc.returncode}"))

        edges = guard_probe_edges(wt)
        for key in declared:
            edge = edges.get(key)
            if edge is None:
                edge_rows.append(
                    (key, "NO-EDGE", "-", "外縁のケースが未定義（guard_probe_edgesへ1件足す）"))
                continue
            if isinstance(edge, str):
                edge_rows.append((key, "N/A", "-", edge))
                continue
            wt_run("git", "reset", "-q", "--hard", base)
            wt_run("git", "clean", "-fdq")
            try:
                edge.mutate()
            except Exception as exc:  # noqa: BLE001 違反を作れないこと自体を結果として出す
                edge_rows.append((key, "SETUP-FAIL", edge.mode, str(exc)[:80]))
                continue
            wt_run("git", "add", "-A")
            check: list[str] = []
            if edge.mode == "staged":
                check = ["--staged"]
            elif edge.mode == "since":
                wt_run("git", "-c", "user.email=guard@local", "-c", "user.name=guard",
                       "commit", "-q", "-m", "guard audit edge", "--no-verify")
                check = ["--since", base]
            proc = wt_run(sys.executable, "scripts/review_checks.py", "docs",
                          "--keys", "--only", key, *check)
            detected = bool(probe_section_count(proc.stdout, key))
            if detected == edge.detected:
                edge_rows.append(
                    (key, "COVERED" if detected else "GAP", edge.mode, edge.where))
            else:
                edge_rows.append((
                    key, "CHANGED", edge.mode,
                    f"期待={'検知' if edge.detected else '見逃し'} 実際="
                    f"{'検知' if detected else '見逃し'}: {edge.where}"))
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
    print("## 母集団の外縁（拾うべきなのに母集団へ入らない位置）")
    print()
    print("| 検知器 | 経路 | 判定 | 外縁 |")
    print("|---|---|---|---|")
    for key, verdict, label, detail in edge_rows:
        print(f"| `{key}` | {label} | {verdict} | {detail} |")
    print()

    bad = [r for r in rows if r[1] not in ("PASS", "SKIP")]
    edge_bad = [r for r in edge_rows if r[1] in ("NO-EDGE", "SETUP-FAIL", "CHANGED")]
    gaps = [r for r in edge_rows if r[1] == "GAP"]
    if gaps:
        print(f"既知の穴 {len(gaps)}件（期待どおり見逃す。埋めたら`detected=True`へ更新すること）。")
    if bad or edge_bad:
        if bad:
            print(f"鳴らない検知器 {len(bad)}件。検知器があることと鳴ることは別物のため、これは違反として扱う。")
        if edge_bad:
            print(f"外縁の期待値と実際が食い違う、または外縁が未定義 {len(edge_bad)}件。")
        return 1
    print(f"正例 全{len(rows)}件PASS（検知器は実際に鳴る）／外縁 全{len(edge_rows)}件が期待どおり")
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
    p.add_argument("--only", help="この検知器だけを実行する（mutateが1件ずつ試すため。配線の検査は全件のまま）")
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
