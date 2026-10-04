r"""起こし直したテストを機械で監査する。報告の自己申告を鵜呑みにしないため。

テストを「実装から起こし直す」手順（docs/conventions/testing.md）は、守ったかどうかが
成果物の見た目からは分からない。旧版を写しても、他モジュールへ結びついても、テストは
緑になる。この監査は、守れていれば必ず満たすはずの5点を外から測る。

- ① 実装を変えていないか（テストの起こし直しで実装が変わったら、それは別の作業）
- ② テストからの`app.*`直接import（対象モジュールと、対象の公開シグネチャが要求する型だけ）
- ③ テストが触る`<対象>.X`の内訳（自ファイル定義／他モジュール由来）。他モジュール由来は
  1件ずつ「差し替えのseamか、責務外か」を人が言う。`scripts/`の道具はテストが`sys.path`へ足して
  素で`import <道具名>`するので、その名前も対象として読む
- ④ 実装へ1行も入らないテスト（`--cov-context=test`で実測する。**静的解析は誤検知する**
  ——`setattr(mod, ...)`の形やヘルパ経由を数え落とした実績が2回ある）
- ⑤ 行・分岐カバレッジ
- ⑥ 対象の公開の名前ごとの`app`・`scripts`・`benchmarks`での参照数（対象の外/中）と、どちらも0の
  「テストからしか使われない候補」。ASTで数えるので、文字列で指す参照とフレームワークが規約で呼ぶものは0に見える

**機械化できないものは残る。** 「そのテストは要るか」の3問と、「本番で作れない入力を
使っていないか」の突き合わせは、対象ごとに値域の導出が要るため人が読む。

実行方法（backendディレクトリから。テストは母集団——対象のモジュール名を書くテスト全部——を並べて渡す）:
    .venv\Scripts\python.exe scripts\audit_test_rewrite.py app/domain/routing.py tests/test_routing.py
    .venv\Scripts\python.exe scripts\audit_test_rewrite.py app/domain/geo.py tests/test_geo.py tests/test_region.py
    .venv\Scripts\python.exe scripts\audit_test_rewrite.py --no-jit app/domain/routing.py tests/test_routing.py
    .venv\Scripts\python.exe scripts\audit_test_rewrite.py --backend ../.claude/worktrees/agent-x/backend \
        app/infrastructure/wbgt_client.py tests/test_wbgt_client.py
    .venv\Scripts\python.exe scripts\audit_test_rewrite.py --ref origin/master app/domain/traffic.py tests/test_traffic.py

`--ref`は起こし直す前の値を同じ実行で測る。その版を一時の作業ツリーへ取り出して同じ母集団で④⑤を測り、
前と後の行・分岐カバレッジと、後で新たに未到達になった行・分岐を並べる。作業ツリーは終わるときに消す
（テストが落ちても）。前の版のテスト名は出さない（起こし直しの手順1〜3では旧版を開かないため）。
その版に無いテストファイルは前の測りから外し、外したことを出す。PostGISのテストは、前の版でも今の
作業ツリーと同じテスト用DBへ繋ぐ（一時の作業ツリー専用のDBは、作業ツリーを消しても残るため作らせない）。

`--no-jit`は`NUMBA_DISABLE_JIT=1`を立てる。`njit`の中はcoverage.pyが追えないため、
JITを通る対象はこれを付けないと⑤が実態より低く出る。

カバレッジは対象の親ディレクトリを`--cov`に渡して測り、報告と④を対象ファイルへ絞る。
ドット記法の`--cov`はcoverage.pyが対象の親パッケージを収集より前にimportするため、
api層の対象ではconftestのimportでnumpyが2度読み込まれて収集ごと落ちる。ファイルのパスを
渡すと何も報告されない。`postgis`の印のテストは、テスト用DBのサーバーへ繋がるときだけ
含めて測り、繋がらなければ外したことを出す。
"""

import argparse
import ast
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import asyncpg
from coverage import CoverageData

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch._common import asyncpg_dsn  # noqa: E402  sys.pathを通した後に読む


def module_symbols(path: Path) -> tuple[set[str], dict[str, str]]:
    """実装ファイルの最上位で「定義されたもの」と「importされたもの」を分ける。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    defined: set[str] = set()
    imported: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            defined.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, ast.ImportFrom):
            imported.update({a.asname or a.name: node.module or "" for a in node.names})
        elif isinstance(node, ast.Import):
            imported.update({a.asname or a.name.split(".")[0]: a.name for a in node.names})
    return defined, imported


def app_imports(tree: ast.AST) -> list[tuple[str, str, str]]:
    """テストからの`app.*`直接import。`(表示用の行, 束縛された名前, importしたもののドット記法)`で返す。

    表示とドット記法は`as`の前の元の名前で書き、束縛された名前は③の内訳の照合にだけ使う。
    """
    out: list[tuple[str, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app"):
            for a in node.names:
                out.append((f"from {node.module} import {a.name}", a.asname or a.name, f"{node.module}.{a.name}"))
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("app"):
                    out.append((f"import {a.name}", a.asname or a.name.split(".")[0], a.name))
    return out


def public_names(tree: ast.Module) -> list[tuple[str, str]]:
    """実装の公開の名前。`(表示名, 参照を数える名前)`で返す。

    最上位の関数・クラス・代入と、公開のクラスの`_`で始まらないメソッド（表示は`クラス.メソッド`）。
    """
    out: list[tuple[str, str]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
        else:
            continue
        out.extend((name, name) for name in names if not name.startswith("_"))
        if isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            out.extend(
                (f"{node.name}.{item.name}", item.name)
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and not item.name.startswith("_")
            )
    return out


def name_references(tree: ast.AST) -> dict[str, int]:
    """名前として読む箇所・属性として読む箇所・`from … import <名前>`を、名前ごとに数える。"""
    counts: dict[str, int] = defaultdict(int)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            counts[node.id] += 1
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            counts[node.attr] += 1
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                counts[a.name] += 1
    return counts


def report_test_only_names(backend: Path, implementation: str) -> None:
    """公開の名前ごとに`app`・`scripts`・`benchmarks`での参照数（対象の外/中）を出し、どちらも0の名前を候補に並べる。"""
    impl_tree = ast.parse((backend / implementation).read_text(encoding="utf-8"))
    inside = name_references(impl_tree)
    outside: dict[str, int] = defaultdict(int)
    for directory in ("app", "scripts", "benchmarks"):
        for path in sorted((backend / directory).rglob("*.py")):
            if path.relative_to(backend).as_posix() != implementation:
                for name, count in name_references(ast.parse(path.read_text(encoding="utf-8"))).items():
                    outside[name] += count
    names = public_names(impl_tree)
    print("\n⑥ 公開の名前の参照（app・scripts・benchmarks。対象の外 / 中）")
    print("     数え方の穴: 文字列で指す参照（getattr・setattr・importlib・文字列の注釈等）は数えない。"
          "デコレータやフレームワークが規約で呼ぶもの（ルーター・バリデータ等）は参照0に見える。"
          "メソッドは同じ名前の別の属性への参照も数える")
    for label, name in names:
        print(f"     {label:<48} 外 {outside[name]:>3} / 中 {inside[name]:>3}")
    candidates = [label for label, name in names if outside[name] == 0 and inside[name] == 0]
    print(f"   テストからしか使われない候補（外にも中にも参照が無い）: {len(candidates)}個"
          + (f"（{', '.join(candidates)}）" if candidates else ""))


def bare_import_alias(tree: ast.AST, name: str) -> str | None:
    """`sys.path`へ足したディレクトリから素で`import <name>`したときの束縛名（`scripts/`の道具を読む形）。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == name:
                    return a.asname or a.name
    return None


def touched_attributes(tree: ast.AST, alias: str) -> dict[str, int]:
    """テストが`alias.X`として触った属性。

    **属性アクセスだけを数えない。** `monkeypatch.setattr(alias, "X", ...)`は属性を
    文字列で指すため、素朴な走査から漏れる（実績: 1件と報告して実際は3件だった）。
    """
    touched: dict[str, int] = defaultdict(int)
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == alias:
            touched[node.attr] += 1
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name in {"setattr", "delattr", "getattr"} and len(node.args) >= 2:
                target, attr = node.args[0], node.args[1]
                if (
                    isinstance(target, ast.Name)
                    and target.id == alias
                    and isinstance(attr, ast.Constant)
                    and isinstance(attr.value, str)
                ):
                    touched[attr.value] += 1
    return dict(touched)


def monkeypatch_seams(tree: ast.AST) -> set[str]:
    """`monkeypatch.setattr`の第2引数の文字列（差し替えた属性の名前）。testing.mdの seams 数はこのユニーク数。"""
    return {
        node.args[1].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "setattr"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "monkeypatch"
        and len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, str)
    }


def unresolved_attribute_calls(tree: ast.AST, alias: str) -> list[int]:
    """`setattr(alias, name, ...)`のように属性を変数で指す呼び出しの行番号。

    ③の内訳はこれを数えられない（ループで差し替える形が典型）。黙って0件にせず、
    行番号を出して人が読む。
    """
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if name in {"setattr", "delattr", "getattr"} and len(node.args) >= 2:
                target, attr = node.args[0], node.args[1]
                if isinstance(target, ast.Name) and target.id == alias and not isinstance(attr, ast.Constant):
                    lines.append(node.lineno)
    return sorted(set(lines))


def names_in_string_constants(tree: ast.AST, names: set[str]) -> set[str]:
    """テストに文字列として現れる、対象モジュールの最上位の名前。

    属性アクセスと`setattr`の文字列とは独立した2通り目の数え方で、変数で指して差し替える
    名前（辞書のキーやループの並びに書かれる）はこちらにだけ現れる。
    """
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in names
    }


def passed_test_ids(pytest_output: str) -> set[str]:
    """`-rA`の要約から、実行されたテストのnode idを取る。

    `PASSED`の行はnode idだけを持つ。`XFAIL`・`XPASS`の行は` - 理由`が続くが、パラメータの
    idも` - `を含みうるため、理由の区切りはこの2つにだけ当てる。
    """
    ids: set[str] = set()
    for line in pytest_output.splitlines():
        outcome, _, rest = line.partition(" ")
        if outcome == "PASSED" and "::" in rest:
            ids.add(rest.strip())
        elif outcome in {"XFAIL", "XPASS"} and "::" in rest:
            ids.add(rest.rsplit(" - ", 1)[0].strip())
    return ids


def tests_that_never_enter_the_implementation(
    coverage_db: Path, implementation: str, executed: set[str]
) -> tuple[list[str], int]:
    """`--cov-context=test`の記録から、対象ファイルの行を1度も実行しないテストを引く。

    **分母は実行されたテストの一覧から取る。** coverage.pyは何も記録しなかった文脈を
    記録に残さないため、記録だけを分母にすると、実装へ入らないテストほど分母からも消える。
    """
    entered: set[str] = set()
    if coverage_db.exists():
        data = CoverageData(basename=str(coverage_db))
        data.read()
        target = implementation.replace("\\", "/")
        for path in data.measured_files():
            if path.replace("\\", "/").endswith(target):
                entered.update(
                    context.split("|")[0]
                    for contexts in data.contexts_by_lineno(path).values()
                    for context in contexts
                    if "::" in context
                )
    return sorted(executed - entered), len(executed)


def test_database_unreachable(backend: Path) -> str | None:
    """PostGISのテストが繋ぐDBのサーバーへ繋がらない理由。繋がればNone。

    行き先はテストと同じ規則（`tests/conftest.py: postgis_database_url`）から取る。作業ツリー
    専用のDBは最初のpytestの実行が作るため、`TEST_DATABASE_URL`が無ければサーバーの管理DBで確かめる。
    conftestは子プロセスで読む（このファイルからimportすると、型検査の対象外のtestsをmypyが辿る）。
    """
    url = os.environ.get("TEST_DATABASE_URL") or subprocess.run(
        [sys.executable, "-c", "from tests.conftest import TEST_DATABASE_MAINTENANCE as url; print(url)"],
        cwd=backend, capture_output=True, text=True, check=True,
    ).stdout.strip()

    async def connect() -> None:
        conn = await asyncpg.connect(asyncpg_dsn(url), timeout=5)
        await conn.close()

    try:
        asyncio.run(connect())
    except Exception as exc:  # noqa: BLE001 繋がらない理由はそのまま出す
        return f"{type(exc).__name__}: {exc}"
    return None


def worktree_test_database_url(backend: Path) -> str:
    """作業ツリーのPostGISのテストが繋ぐDBのURL（無ければ作る）。テストと同じ規則で、子プロセスで決める。"""
    return os.environ.get("TEST_DATABASE_URL") or subprocess.run(
        [sys.executable, "-c", "from tests.conftest import _prepare_worktree_database as p; print(p())"],
        cwd=backend, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    ).stdout.strip().splitlines()[-1]


@dataclass(frozen=True)
class Measurement:
    """1つの版の④⑤。"""

    covered_lines: int
    statements: int
    covered_branches: int
    branches: int
    missing_lines: frozenset[int]
    missing_branches: frozenset[tuple[int, int]]
    dead: list[str]
    executed: int


def rate(covered: int, total: int) -> str:
    return f"{'100' if total == 0 else f'{covered / total * 100:.1f}'}%（{covered}/{total}）"


def line_ranges(lines: set[int] | frozenset[int]) -> str:
    """連続する行番号を`12-15`にまとめる。"""
    out: list[list[int]] = []
    for n in sorted(lines):
        if out and out[-1][1] == n - 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return ", ".join(f"{a}" if a == b else f"{a}-{b}" for a, b in out) or "なし"


def run_pytest(
    backend: Path, tests: list[str], cov_dir: str, env: dict[str, str], with_postgis: bool, report: Path
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", *tests, "-q", "-rA", *([] if with_postgis else ["-m", "not postgis"]),
         "-p", "no:randomly",
         f"--cov={cov_dir}", "--cov-branch", "--cov-context=test", "--cov-report=term-missing",
         f"--cov-report=json:{report}"],
        cwd=backend, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def measurement(backend: Path, report: Path, implementation: str, pytest_output: str) -> Measurement:
    """pytestの実行が残したカバレッジから、対象ファイルの④⑤を読む。

    `--cov`に親ディレクトリを渡すので、テストが1行も通らなかった実装も報告に載る。
    """
    files = json.loads(report.read_text(encoding="utf-8"))["files"]
    data = next(f for path, f in files.items() if path.replace("\\", "/") == implementation)
    summary = data["summary"]
    dead, executed = tests_that_never_enter_the_implementation(
        backend / ".coverage", implementation, passed_test_ids(pytest_output)
    )
    return Measurement(
        covered_lines=summary["covered_lines"],
        statements=summary["num_statements"],
        covered_branches=summary["covered_branches"],
        branches=summary["num_branches"],
        missing_lines=frozenset(data["missing_lines"]),
        missing_branches=frozenset((a, b) for a, b in data["missing_branches"]),
        dead=dead,
        executed=executed,
    )


@contextmanager
def checkout(backend: Path, ref: str, parent: Path) -> Iterator[Path]:
    """版`ref`を一時の作業ツリーへ取り出し、そのbackendを渡す。抜けるとき（テストが落ちても・中断されても）消す。"""
    root = parent / "before"
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(root), ref],
        cwd=backend, capture_output=True, text=True, encoding="utf-8", errors="replace", check=True,
    )
    try:
        yield root / "backend"
    finally:
        removed = subprocess.run(
            ["git", "worktree", "remove", "--force", str(root)],
            cwd=backend, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if removed.returncode != 0:
            print(f"一時の作業ツリーを消せなかった: {root}（git worktree remove --force で消す）"
                  f"\n     {removed.stderr.strip()}", file=sys.stderr)


def compare_with_ref(
    backend: Path, ref: str, tests: list[str], implementation: str, cov_dir: str,
    env: dict[str, str], with_postgis: bool, after: Measurement, work: Path,
) -> int:
    """版`ref`の同じ母集団で④⑤を測り、後の値と並べる。前の版のテスト名は出さない。"""
    print(f"\n前の版（{ref}）を一時の作業ツリーへ取り出して④⑤を測っています…")
    if with_postgis:
        env = dict(env, TEST_DATABASE_URL=worktree_test_database_url(backend))
    try:
        with checkout(backend, ref, work) as before_backend:
            present = [test for test in tests if (before_backend / test).exists()]
            absent = [test for test in tests if test not in present]
            if absent:
                print(f"     前の版に無いテスト（前の測りから外した）: {' '.join(absent)}")
            if not present:
                print("     前の版に母集団のテストが1本も無い。前の値は測れない", file=sys.stderr)
                return 1
            if not (before_backend / implementation).exists():
                print(f"     前の版に対象の実装が無い: {implementation}", file=sys.stderr)
                return 1
            report = work / "before.json"
            result = run_pytest(before_backend, present, cov_dir, env, with_postgis, report)
            if result.returncode != 0:
                print("     前の版のテストが緑でない。前の値は当てにならない（旧版のテスト名は落ちたものだけ出す）:",
                      file=sys.stderr)
                for line in (result.stdout + "\n" + result.stderr).splitlines():
                    if line.startswith(("FAILED ", "ERROR ")) or (
                        "::" not in line and re.search(r"\d+ (passed|failed|errors?)\b", line)
                    ):
                        print("     " + line, file=sys.stderr)
                return 1
            before = measurement(before_backend, report, implementation, result.stdout)
    except subprocess.CalledProcessError as exc:
        print(f"     前の版を取り出せない: {' '.join(exc.cmd)}\n     {exc.stderr.strip()}", file=sys.stderr)
        return 1

    print(f"\n前（{ref}）→ 後（作業ツリー）")
    print(f"     テスト: {before.executed}本 → {after.executed}本")
    print(f"     行:     {rate(before.covered_lines, before.statements)} → {rate(after.covered_lines, after.statements)}")
    print(f"     分岐:   {rate(before.covered_branches, before.branches)}"
          f" → {rate(after.covered_branches, after.branches)}")
    print(f"     ④ 実装へ1行も入らないテスト: {len(before.dead)} → {len(after.dead)}")
    same_implementation = subprocess.run(
        ["git", "diff", "--quiet", ref, "--", implementation], cwd=backend, capture_output=True,
    ).returncode == 0
    if not same_implementation:
        print(f"     実装が {ref} と違うため、行番号は前と後で対応しない。新たに未到達になった行は出さない")
        return 0
    lines = after.missing_lines - before.missing_lines
    branches = after.missing_branches - before.missing_branches
    print(f"     後で新たに未到達になった行: {line_ranges(lines)}")
    print("     後で新たに未到達になった分岐: "
          + (", ".join(f"{a}->{b}" for a, b in sorted(branches)) or "なし"))
    if lines or branches:
        print("     ← 下がった箇所ごとに、なぜ見なくてよいかを1行書く（testing.md「既存テストを直さず、実装から起こし直す」）")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="起こし直したテストを機械で監査する")
    parser.add_argument("implementation", help="実装ファイル（backendディレクトリからの相対パス）")
    parser.add_argument("tests", nargs="+", help="テストファイル（同上）。母集団を並べて渡す")
    parser.add_argument("--backend", default=".", help="別の作業ツリーのbackendディレクトリ（既定: .）")
    parser.add_argument("--no-jit", action="store_true", help="NUMBA_DISABLE_JIT=1で測る")
    parser.add_argument("--ref", help="前の値を測る版（例: origin/master）。後の値と並べる")
    args = parser.parse_args()

    not_python = [test for test in args.tests if not test.endswith(".py")]
    if not_python:
        print(f".py でないテスト: {' '.join(not_python)}", file=sys.stderr)
        print("母集団は grep に --include='*.py' を付けて出し直す", file=sys.stderr)
        return 1
    backend = Path(args.backend).resolve()
    impl_path = backend / args.implementation
    for path in (impl_path, *(backend / test for test in args.tests)):
        if not path.exists():
            print(f"見つからない: {path}", file=sys.stderr)
            return 1
    implementation = args.implementation.replace("\\", "/")
    module = implementation.removesuffix(".py").replace("/", ".")
    cov_dir = implementation.rsplit("/", 1)[0]

    print(f"対象:     {args.implementation}")
    print(f"テスト:   {' '.join(args.tests)}")
    print(f"--cov:    {cov_dir}（親ディレクトリで測り、対象ファイルへ絞る）")
    unreachable = test_database_unreachable(backend)
    if unreachable:
        print(f"postgis:  **外す**（テスト用DBに繋がらない: {unreachable}）")
    else:
        print("postgis:  含める（テスト用DBに繋がる）")
    print("=" * 78)

    # --- ① 実装を変えていないか ---
    status = subprocess.run(
        ["git", "status", "--short", "--", args.implementation],
        cwd=backend, capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout.strip()
    print(f"\n① 実装の変更: {'**あり** → ' + status if status else 'なし'}")

    defined, imported = module_symbols(impl_path)
    for test in args.tests:
        tree = ast.parse((backend / test).read_text(encoding="utf-8"))
        print(f"\n--- {test}")
        seams = monkeypatch_seams(tree)
        print(f"   seams（monkeypatch.setattrの第2引数のユニーク数）: {len(seams)}"
              + (f"（{', '.join(sorted(seams))}）" if seams else ""))

        # --- ② app.* 直接import ---
        imports = app_imports(tree)
        print(f"② テストからの app.* 直接import: {len(imports)}本")
        for line, _, _ in imports:
            print(f"     {line}")
        if imports:
            print("     ← 許されるのは対象モジュールと、対象の公開シグネチャが要求する型だけ。")
            print("       他モジュールの関数・サービス・例外・定数は対象の名前空間経由で触ること")

        # --- ③ <対象>.X の内訳 ---
        alias = next((name for _, name, path in imports if path == module), None) or bare_import_alias(
            tree, module.rsplit(".", 1)[-1]
        )
        if alias is None and imports:
            alias = imports[0][1]
        if alias is None:
            print("③ 対象モジュールをimportしていない"
                  "（ファイル名が指すモジュールを検証していない可能性）")
            continue
        touched = touched_attributes(tree, alias)
        own = sorted(a for a in touched if a in defined)
        foreign = sorted((a, imported[a]) for a in touched if a in imported and a not in defined)
        unknown = sorted(a for a in touched if a not in defined and a not in imported)
        print(f"③ テストが触る {alias}.X: 自ファイル定義 {len(own)}種"
              f" / 他モジュール由来 {len(foreign)}種 / 判定不能 {len(unknown)}種")
        for name, source in foreign:
            print(f"     {alias}.{name:<32} <- {source}  ({touched[name]}回)"
                  "  ← seamか責務外かを言うこと")
        for name in unknown:
            print(f"     {alias}.{name}  （判定不能）")
        unresolved = unresolved_attribute_calls(tree, alias)
        if unresolved:
            candidates = sorted(names_in_string_constants(tree, defined | set(imported)) - set(touched))
            print(f"     属性を変数で指す呼び出し {len(unresolved)}か所（行 {', '.join(map(str, unresolved))}）"
                  "は上の内訳に入っていない")
            print(f"     テストに文字列で現れる {alias} の名前（上に無いもの）: {', '.join(candidates) or 'なし'}")

    report_test_only_names(backend, implementation)

    # --- ④⑤ カバレッジ ---
    print("\n④⑤ カバレッジを測っています…")
    env = dict(os.environ, PYTHONUTF8="1")
    if args.no_jit:
        env["NUMBA_DISABLE_JIT"] = "1"
    with tempfile.TemporaryDirectory(prefix="ridecompass-audit-") as work_dir:
        work = Path(work_dir)
        report = work / "after.json"
        result = run_pytest(backend, args.tests, cov_dir, env, not unreachable, report)
        lines = result.stdout.splitlines()
        for line in lines:
            if line.replace("\\", "/").startswith(implementation + " ") or (
                line.startswith("=") and (" passed" in line or " failed" in line or " error" in line)
            ):
                print("     " + line.strip())
        if result.returncode != 0:
            print("\n     テストが緑でない。監査の残りは当てにならない。pytestの出力の末尾:", file=sys.stderr)
            for line in (lines + result.stderr.splitlines())[-15:]:
                print("     " + line, file=sys.stderr)
            return 1

        after = measurement(backend, report, implementation, result.stdout)
        print(f"\n④ 実装へ1行も入らないテスト: {len(after.dead)} / {after.executed}")
        for name in after.dead:
            print("     " + (name if len(args.tests) > 1 else name.split("::", 1)[1]))

        if args.ref and compare_with_ref(
            backend, args.ref, args.tests, implementation, cov_dir, env, not unreachable, after, work
        ):
            return 1

    print("\n" + "=" * 78)
    print("機械化できないもの（人が読む）:"
          " 「そのテストは要るか」の3問 / 本番で作れない入力の突き合わせ")
    return 0


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    raise SystemExit(main())
