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

実行方法（backendディレクトリから）:
    .venv\Scripts\python.exe scripts\audit_test_rewrite.py app/domain/routing.py tests/test_routing.py
    .venv\Scripts\python.exe scripts\audit_test_rewrite.py --no-jit app/domain/routing.py tests/test_routing.py
    .venv\Scripts\python.exe scripts\audit_test_rewrite.py --backend ../.claude/worktrees/agent-x/backend \
        app/infrastructure/wbgt_client.py tests/test_wbgt_client.py

`--no-jit`は`NUMBA_DISABLE_JIT=1`を立てる。`njit`の中はcoverage.pyが追えないため、
JITを通る対象はこれを付けないと⑤が実態より低く出る。
"""

import argparse
import ast
import os
import sqlite3
import subprocess
import sys
from collections import defaultdict
from pathlib import Path


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


def tests_that_never_enter_the_implementation(coverage_db: Path) -> tuple[list[str], int]:
    """`--cov-context=test`の記録から、対象モジュールの行を1度も実行しないテストを引く。

    `--cov-branch`のとき記録は`line_bits`ではなく`arc`へ入る。両方を見ないと、
    「全件が実装へ入っていない」という嘘の答えが出る。
    """
    if not coverage_db.exists():
        return [], 0
    db = sqlite3.connect(coverage_db)
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    counts: dict[str, int] = {}
    for (context,) in db.execute("SELECT context FROM context"):
        if "::" in context:
            counts.setdefault(context.split("|")[0], 0)
    for table in ("line_bits", "arc"):
        if table not in tables:
            continue
        rows = db.execute(
            f"SELECT ctx.context, COUNT(*) FROM {table} x"
            " JOIN context ctx ON ctx.id = x.context_id GROUP BY ctx.context"
        )
        for context, n in rows:
            if "::" in context:
                key = context.split("|")[0]
                counts[key] = counts.get(key, 0) + n
    return sorted(k for k, v in counts.items() if v == 0), len(counts)


def main() -> int:
    parser = argparse.ArgumentParser(description="起こし直したテストを機械で監査する")
    parser.add_argument("implementation", help="実装ファイル（backendディレクトリからの相対パス）")
    parser.add_argument("test", help="テストファイル（同上）")
    parser.add_argument("--backend", default=".", help="別の作業ツリーのbackendディレクトリ（既定: .）")
    parser.add_argument("--no-jit", action="store_true", help="NUMBA_DISABLE_JIT=1で測る")
    args = parser.parse_args()

    backend = Path(args.backend).resolve()
    impl_path = backend / args.implementation
    test_path = backend / args.test
    for path in (impl_path, test_path):
        if not path.exists():
            print(f"見つからない: {path}", file=sys.stderr)
            return 1
    module = args.implementation.replace("\\", "/").removesuffix(".py").replace("/", ".")

    print(f"対象:     {args.implementation}")
    print(f"テスト:   {args.test}")
    print(f"モジュール指定: {module}（--covはドット記法。パス記法だと無報告になる）")
    print("=" * 78)

    # --- ① 実装を変えていないか ---
    status = subprocess.run(
        ["git", "status", "--short", "--", args.implementation],
        cwd=backend, capture_output=True, text=True, encoding="utf-8", errors="replace",
    ).stdout.strip()
    print(f"\n① 実装の変更: {'**あり** → ' + status if status else 'なし'}")

    tree = ast.parse(test_path.read_text(encoding="utf-8"))

    # --- ② app.* 直接import ---
    imports = app_imports(tree)
    print(f"\n② テストからの app.* 直接import: {len(imports)}本")
    for line, _ in imports:
        print(f"     {line}")
    print("     ← 許されるのは対象モジュールと、対象の公開シグネチャが要求する型だけ。")
    print("       他モジュールの関数・サービス・例外・定数は対象の名前空間経由で触ること")

    # --- ③ <対象>.X の内訳 ---
    alias = next((name for _, name in imports if module.endswith(name)), None)
    if alias is None and imports:
        alias = imports[0][1]
    if alias is None:
        print("\n③ 対象モジュールをimportしていない"
              "（ファイル名が指すモジュールを検証していない可能性）")
    else:
        defined, imported = module_symbols(impl_path)
        touched = touched_attributes(tree, alias)
        own = sorted(a for a in touched if a in defined)
        foreign = sorted((a, imported[a]) for a in touched if a in imported and a not in defined)
        unknown = sorted(a for a in touched if a not in defined and a not in imported)
        print(f"\n③ テストが触る {alias}.X: 自ファイル定義 {len(own)}種"
              f" / 他モジュール由来 {len(foreign)}種 / 判定不能 {len(unknown)}種")
        for name, source in foreign:
            print(f"     {alias}.{name:<32} <- {source}  ({touched[name]}回)"
                  "  ← seamか責務外かを言うこと")
        for name in unknown:
            print(f"     {alias}.{name}  （判定不能）")

    # --- ④⑤ カバレッジ ---
    print("\n④⑤ カバレッジを測っています…")
    env = dict(os.environ, PYTHONUTF8="1")
    if args.no_jit:
        env["NUMBA_DISABLE_JIT"] = "1"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", args.test, "-q", "-m", "not postgis", "-p", "no:randomly",
         f"--cov={module}", "--cov-branch", "--cov-context=test", "--cov-report=term-missing"],
        cwd=backend, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    tail = module.split(".")[-1]
    for line in result.stdout.splitlines():
        if tail in line or " passed" in line or " failed" in line or " error" in line:
            print("     " + line.strip())
    if result.returncode != 0:
        print("\n     テストが緑でない。監査の残りは当てにならない", file=sys.stderr)
        return 1

    dead, total = tests_that_never_enter_the_implementation(backend / ".coverage")
    print(f"\n④ 実装へ1行も入らないテスト: {len(dead)} / {total}")
    for name in dead:
        print("     " + name.split("::", 1)[1])

    print("\n" + "=" * 78)
    print("機械化できないもの（人が読む）:"
          " 「そのテストは要るか」の3問 / 本番で作れない入力の突き合わせ")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
