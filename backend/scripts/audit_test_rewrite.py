r"""起こし直したテストを機械で監査する。報告の自己申告を鵜呑みにしないため。

テストを「実装から起こし直す」手順（.claude/rules/testing.md）は、守ったかどうかが
成果物の見た目からは分からない。旧版を写しても、他モジュールへ結びついても、テストは
緑になる。この監査は、守れていれば必ず満たすはずの5点を外から測る。

- ① 実装を変えていないか（テストの起こし直しで実装が変わったら、それは別の作業）
- ② テストからの`app.*`直接import（対象モジュールと、対象の公開シグネチャが要求する型だけ）
- ③ テストが触る`<対象>.X`の内訳（自ファイル定義／他モジュール由来）。他モジュール由来は
  1件ずつ「差し替えのseamか、責務外か」を人が言う。`scripts/`の道具はテストが`sys.path`へ足して
  素で`import <道具名>`するので、その名前も対象として読む
- ④ 実装へ1行も入らないテストと、入るがそのテストだけが通す行が0行のテスト（`--cov-context=test`で
  実測する。**静的解析は誤検知する**——`setattr(mod, ...)`の形やヘルパ経由を数え落とした実績が2回ある）
- ⑤ 行・分岐カバレッジと、テストファイルごとの項目・`test_`の関数・行（空行とコメントを除く）の数
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
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import asyncpg
from coverage import CoverageData

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.batch.common import asyncpg_dsn  # noqa: E402  sys.pathを通した後に読む


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


def lines_by_test(coverage_db: Path, implementation: Path) -> dict[str, set[int]]:
    """`--cov-context=test`の記録から、テストごとに対象ファイルで実行した行を引く。

    coverage.pyは何も記録しなかった文脈を記録に残さないため、実装へ入らないテストはここに現れない。
    """
    lines: dict[str, set[int]] = defaultdict(set)
    if coverage_db.exists():
        data = CoverageData(basename=str(coverage_db))
        data.read()
        for path in data.measured_files():
            if Path(path).resolve() == implementation:
                for line, contexts in data.contexts_by_lineno(path).items():
                    for context in contexts:
                        if "::" in context:
                            lines[context.split("|")[0]].add(line)
    return lines


def tests_without_own_lines(executed: set[str], lines: dict[str, set[int]]) -> tuple[list[str], list[str]]:
    """実装へ1行も入らないテスト（④）と、入るがそのテストだけが通す行を持たないテスト。

    **分母は実行されたテストの一覧から取る。** 記録だけを分母にすると、実装へ入らないテストほど分母からも消える。
    """
    reached: dict[int, int] = defaultdict(int)
    for test_lines in lines.values():
        for line in test_lines:
            reached[line] += 1
    dead = sorted(executed - lines.keys())
    shared = sorted(
        test for test in executed & lines.keys() if all(reached[line] > 1 for line in lines[test])
    )
    return dead, shared


def test_file_sizes(backend: Path, tests: list[str], executed: set[str]) -> dict[str, tuple[int, int, int]]:
    """テストファイルごとの（実行した項目の数, `test_`で始まる関数の数, 空行とコメントだけの行を除いた行数）。"""
    sizes: dict[str, tuple[int, int, int]] = {}
    for test in tests:
        source = (backend / test).read_text(encoding="utf-8")
        functions = sum(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_")
            for node in ast.walk(ast.parse(source))
        )
        lines = sum(bool(line.strip()) and not line.strip().startswith("#") for line in source.splitlines())
        sizes[test] = (sum(test_id.split("::", 1)[0] == test for test_id in executed), functions, lines)
    return sizes


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


@dataclass(frozen=True)
class Measurement:
    """④⑤の測った値。"""

    covered_lines: int
    statements: int
    covered_branches: int
    branches: int
    missing_lines: frozenset[int]
    missing_branches: frozenset[tuple[int, int]]
    dead: list[str]
    without_own_lines: list[str]
    executed: int
    test_files: dict[str, tuple[int, int, int]]


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
         f"--cov={cov_dir}", "--cov-branch", "--cov-context=test",
         f"--cov-report=json:{report}"],
        cwd=backend, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def measurement(
    backend: Path, report: Path, implementation: str, tests: list[str], pytest_output: str
) -> Measurement:
    """pytestの実行が残したカバレッジから、対象ファイルの④⑤とテストファイルごとの数を読む。

    `--cov`に親ディレクトリを渡すので、テストが1行も通らなかった実装も報告に載る。報告の鍵は、backendの外
    （`../scripts/`）の実装では絶対パスになるため、解決したパスで引く。
    """
    target = (backend / implementation).resolve()
    files = json.loads(report.read_text(encoding="utf-8"))["files"]
    data = next(f for path, f in files.items() if (backend / path).resolve() == target)
    summary = data["summary"]
    executed = passed_test_ids(pytest_output)
    dead, without_own_lines = tests_without_own_lines(executed, lines_by_test(backend / ".coverage", target))
    return Measurement(
        covered_lines=summary["covered_lines"],
        statements=summary["num_statements"],
        covered_branches=summary["covered_branches"],
        branches=summary["num_branches"],
        missing_lines=frozenset(data["missing_lines"]),
        missing_branches=frozenset((a, b) for a, b in data["missing_branches"]),
        dead=dead,
        without_own_lines=without_own_lines,
        executed=len(executed),
        test_files=test_file_sizes(backend, tests, executed),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="起こし直したテストを機械で監査する")
    parser.add_argument("implementation", help="実装ファイル（backendディレクトリからの相対パス）")
    parser.add_argument("tests", nargs="+", help="テストファイル（同上）。母集団を並べて渡す")
    parser.add_argument("--backend", default=".", help="別の作業ツリーのbackendディレクトリ（既定: .）")
    parser.add_argument("--no-jit", action="store_true", help="NUMBA_DISABLE_JIT=1で測る")
    args = parser.parse_args()

    not_python = [test for test in args.tests if not test.endswith(".py")]
    if not_python:
        print(f".py でないテスト: {' '.join(not_python)}", file=sys.stderr)
        print("母集団は grep に --include='*.py' を付けて出し直す", file=sys.stderr)
        return 1
    backend = Path(args.backend).resolve()
    impl_path = backend / args.implementation
    if not impl_path.exists():
        print(f"見つからない: {impl_path}", file=sys.stderr)
        return 1
    tests = [test.replace("\\", "/") for test in args.tests]
    missing = [test for test in tests if not (backend / test).exists()]
    if missing:
        print(f"見つからない: {' '.join(missing)}", file=sys.stderr)
        return 1
    implementation = args.implementation.replace("\\", "/")
    module = implementation.removesuffix(".py").replace("/", ".")
    cov_dir = implementation.rsplit("/", 1)[0]

    print(f"対象:     {args.implementation}")
    print(f"テスト:   {' '.join(tests)}")
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
    for test in tests:
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
        report = work / "measured.json"
        result = run_pytest(backend, tests, cov_dir, env, not unreachable, report)
        lines = result.stdout.splitlines()
        for line in lines:
            if line.startswith("=") and (" passed" in line or " failed" in line or " error" in line):
                print("     " + line.strip())
        if result.returncode != 0:
            print("\n     テストが緑でない。監査の残りは当てにならない。pytestの出力の末尾:", file=sys.stderr)
            for line in (lines + result.stderr.splitlines())[-15:]:
                print("     " + line, file=sys.stderr)
            return 1

        measured = measurement(backend, report, implementation, tests, result.stdout)
        print(f"\n④ 実装へ1行も入らないテスト: {len(measured.dead)} / {measured.executed}")
        for name in measured.dead:
            print("     " + (name if len(tests) > 1 else name.split("::", 1)[1]))
        print(f"   実装へ入るが、そのテストだけが通す行が0行のテスト: {len(measured.without_own_lines)} / {measured.executed}")
        for name in measured.without_own_lines:
            print("     " + (name if len(tests) > 1 else name.split("::", 1)[1]))
        print(f"\n⑤ 行:   {rate(measured.covered_lines, measured.statements)}"
              f"  未到達: {line_ranges(measured.missing_lines)}")
        print(f"   分岐: {rate(measured.covered_branches, measured.branches)}  未到達: "
              + (", ".join(f"{a}->{b}" for a, b in sorted(measured.missing_branches)) or "なし"))
        for test, (items, functions, test_lines) in measured.test_files.items():
            print(f"   {test}: 項目 {items}  test_の関数 {functions}  行 {test_lines}（空行とコメントを除く）")

    print("\n" + "=" * 78)
    print("機械化できないもの（人が読む）:"
          " 「そのテストは要るか」の3問 / 本番で作れない入力の突き合わせ")
    return 0


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    raise SystemExit(main())
