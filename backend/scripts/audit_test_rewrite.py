r"""起こし直したテストを機械で監査する。報告の自己申告を鵜呑みにしないため。

テストを「実装から起こし直す」手順（docs/conventions/testing.md）は、守ったかどうかが
成果物の見た目からは分からない。旧版を写しても、他モジュールへ結びついても、テストは
緑になる。この監査は、守れていれば必ず満たすはずの5点を外から測る。

- ① 実装を変えていないか（テストの起こし直しで実装が変わったら、それは別の作業）
- ② テストからの`app.*`直接import（対象モジュールと、対象の公開シグネチャが要求する型だけ）
- ③ テストが触る`<対象>.X`の内訳（自ファイル定義／他モジュール由来）。他モジュール由来は
  1件ずつ「差し替えのseamか、責務外か」を人が言う
- ④ 実装へ1行も入らないテスト（`--cov-context=test`で実測する。**静的解析は誤検知する**
  ——`setattr(mod, ...)`の形やヘルパ経由を数え落とした実績が2回ある）
- ⑤ 行・分岐カバレッジ

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
渡すと何も報告されない。測るのは`-m "not postgis"`のテストだけ。
"""

import argparse
import ast
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

from coverage import CoverageData


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


def app_imports(tree: ast.AST) -> list[tuple[str, str]]:
    """テストからの`app.*`直接import。`(表示用の行, 束縛された名前)`で返す。"""
    out: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app"):
            for a in node.names:
                out.append((f"from {node.module} import {a.asname or a.name}", a.asname or a.name))
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("app"):
                    out.append((f"import {a.name}", a.asname or a.name.split(".")[0]))
    return out


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


def main() -> int:
    parser = argparse.ArgumentParser(description="起こし直したテストを機械で監査する")
    parser.add_argument("implementation", help="実装ファイル（backendディレクトリからの相対パス）")
    parser.add_argument("tests", nargs="+", help="テストファイル（同上）。母集団を並べて渡す")
    parser.add_argument("--backend", default=".", help="別の作業ツリーのbackendディレクトリ（既定: .）")
    parser.add_argument("--no-jit", action="store_true", help="NUMBA_DISABLE_JIT=1で測る")
    args = parser.parse_args()

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
        for line, _ in imports:
            print(f"     {line}")
        print("     ← 許されるのは対象モジュールと、対象の公開シグネチャが要求する型だけ。")
        print("       他モジュールの関数・サービス・例外・定数は対象の名前空間経由で触ること")

        # --- ③ <対象>.X の内訳 ---
        alias = next((name for _, name in imports if module.endswith(name)), None)
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

    # --- ④⑤ カバレッジ ---
    print("\n④⑤ カバレッジを測っています…")
    env = dict(os.environ, PYTHONUTF8="1")
    if args.no_jit:
        env["NUMBA_DISABLE_JIT"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *args.tests, "-q", "-rA", "-m", "not postgis", "-p", "no:randomly",
         f"--cov={cov_dir}", "--cov-branch", "--cov-context=test", "--cov-report=term-missing"],
        cwd=backend, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
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

    dead, total = tests_that_never_enter_the_implementation(
        backend / ".coverage", implementation, passed_test_ids(result.stdout)
    )
    print(f"\n④ 実装へ1行も入らないテスト: {len(dead)} / {total}")
    for name in dead:
        print("     " + (name if len(args.tests) > 1 else name.split("::", 1)[1]))

    print("\n" + "=" * 78)
    print("機械化できないもの（人が読む）:"
          " 「そのテストは要るか」の3問 / 本番で作れない入力の突き合わせ")
    return 0


if __name__ == "__main__":
    from _stdio import use_utf8_stdio

    use_utf8_stdio()
    raise SystemExit(main())
