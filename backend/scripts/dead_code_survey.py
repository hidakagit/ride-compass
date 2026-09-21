r"""本番の入力から到達しない定義を出す（[T968](../../docs/records/tasks/T968.md)段階1）。

**「怪しそうな書き方」をgrepして母集団を作らない。** 症状や少数の事例の特徴から母集団を
決めると、そこに無いものは定義上見つからない。本番の入力の源流から参照をたどり、たどり
着かない定義を孤立点として出す。

**テストは源流に含めない。** 「誰からも呼ばれていない」ではなく「本番の入力から到達
しない」を出すのが目的で、テストを源流に入れるとテストが延命している実装が見えなくなる。

完全性はインスタンスを全部見たことではなく、次の2つに依る。どちらも短い表として出力する
ので、人が読んで「これが抜けている」と言える。

- (a) エントリポイントの列挙が閉じていること（`--show-entrypoints`）
- (b) 参照の辺が動的な呼び出しを取りこぼさないこと（`--show-dynamic`）

**曖昧なものは生きている側へ倒す。** 同名の定義が複数モジュールにあるときは全部へ辺を
張る。孤立点として出たものは「確からしい」側に寄り、見落とし（本当は死んでいるのに出ない）
が増える。処分の作業では、出たものを疑うより出ないものを疑うほうが高くつくため。

実行方法（backendディレクトリから）:
    .venv\Scripts\python.exe scripts\dead_code_survey.py
    .venv\Scripts\python.exe scripts\dead_code_survey.py --show-entrypoints
    .venv\Scripts\python.exe scripts\dead_code_survey.py --check compute_edge_costs_bulk
"""

import argparse
import ast
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"

#: 源流を持つディレクトリ。`app/`の中は入口から辿った結果だけが生き、ここは入口そのもの。
ENTRY_DIRS = ("scripts", "benchmarks")

#: 偽陽性になる定義。列挙の時点で除かないと出力の大半がこれで埋まる。
#: - FastAPIのルートハンドラ: デコレータで登録され、コードからは参照されない
#: - SQLAlchemyの宣言モデル: メタクラス経由で`Base.metadata`へ入る
#: - Pydanticのモデル: FastAPIの引数・戻り値の型注釈から使われる
FASTAPI_ROUTE_DECORATORS = ("get", "post", "put", "patch", "delete", "head", "options")
ORM_BASE_NAMES = ("Base", "DeclarativeBase")
PYDANTIC_BASE_NAMES = ("BaseModel",)


@dataclass
class Definition:
    """モジュール直下の定義1件。"""

    module: str
    name: str
    kind: str  # "function" | "class" | "assign"
    lineno: int
    path: Path
    refs: set[str] = field(default_factory=set)  # この定義の本体が参照する名前
    is_entrypoint: bool = False
    exempt_reason: str = ""  # 空でなければ孤立点として報告しない
    runs_without_reference: bool = False  # デコレータ・メタクラス経由で実行される

    @property
    def qualname(self) -> str:
        return f"{self.module}.{self.name}"


def module_name(path: Path) -> str:
    return ".".join(path.relative_to(BACKEND_ROOT).with_suffix("").parts)


def _strip_docstrings(node: ast.AST) -> ast.AST:
    """docstringを落とす。**これを残すと辺が嘘になる**。

    docstringは名前を説明のために並べる。「この関数はテストからしか呼ばれない」と
    書いた一文がそのまま辺になり、当の関数を生かしてしまう。ASTを使っても文字列定数を
    辿れば同じ穴が開く。
    """
    for child in ast.walk(node):
        if not isinstance(child, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        body = getattr(child, "body", None)
        if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)):
            child.body = body[1:]
    return node


def _referenced_names(node: ast.AST) -> set[str]:
    """本体が参照する名前。`ast.Name`・`ast.Attribute`の属性名・`import`の別名を拾う。

    **テキストのgrepでは取りこぼす**——docstringやコメント内の言及を「使用」と数えて
    しまい、死んでいる定義が生きていると判定される（T956で実測）。
    """
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute):
            names.add(child.attr)
        elif isinstance(child, ast.alias):
            names.add((child.asname or child.name).split(".")[-1])
        elif isinstance(child, ast.Constant) and isinstance(child.value, str):
            # SQL文字列やレジストリのキーに名前が埋まることがある。単語として現れたら
            # 辺を張る（曖昧なものは生きている側へ倒す方針）。
            for token in child.value.replace("(", " ").replace(")", " ").replace(".", " ").split():
                if token.isidentifier():
                    names.add(token)
    return names


def _decorator_names(node: ast.AST) -> list[str]:
    decorators: list[str] = []
    for decorator in getattr(node, "decorator_list", []):
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute):
            decorators.append(target.attr)
        elif isinstance(target, ast.Name):
            decorators.append(target.id)
    return decorators


def _base_names(node: ast.ClassDef) -> list[str]:
    bases: list[str] = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            bases.append(base.id)
        elif isinstance(base, ast.Attribute):
            bases.append(base.attr)
    return bases


def _exempt_reason(node: ast.AST) -> str:
    """列挙から除く理由。空なら除かない。"""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        decorators = _decorator_names(node)
        if any(name in FASTAPI_ROUTE_DECORATORS for name in decorators):
            return "FastAPIのルートハンドラ（デコレータ登録）"
        if "register_adapter" in decorators:
            return "取込アダプタ（レジストリ登録）"
        if "fixture" in decorators:
            return "pytestのfixture"
    if isinstance(node, ast.ClassDef):
        bases = _base_names(node)
        if any(name in ORM_BASE_NAMES for name in bases):
            return "SQLAlchemyの宣言モデル（メタクラス経由）"
        if any(name in PYDANTIC_BASE_NAMES for name in bases):
            return "Pydanticモデル（型注釈から使われる）"
    return ""


def collect_definitions(paths: list[Path]) -> dict[str, list[Definition]]:
    """モジュール直下の公開定義を集める（名前 → 同名の定義たち）。"""
    by_name: dict[str, list[Definition]] = defaultdict(list)
    for path in paths:
        tree = _strip_docstrings(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        module = module_name(path)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # **非公開もノードにする。** 登録しないと、非公開の定義やテーブルが
                # 参照している公開定義への辺が切れ、生きているものが孤立点に見える
                # （`_PATH_POLICIES`が参照する`PERMANENT`等で実測）。
                private = node.name.startswith("_")
                definition = Definition(
                    module=module,
                    name=node.name,
                    kind="class" if isinstance(node, ast.ClassDef) else "function",
                    lineno=node.lineno,
                    path=path,
                    refs=_referenced_names(node),
                    exempt_reason=_exempt_reason(node) or ("非公開" if private else ""),
                )
                definition.runs_without_reference = bool(_exempt_reason(node))
                by_name[node.name].append(definition)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if not isinstance(target, ast.Name):
                        continue
                    by_name[target.id].append(Definition(
                        module=module,
                        name=target.id,
                        kind="assign",
                        lineno=node.lineno,
                        path=path,
                        refs=_referenced_names(node),
                        exempt_reason="非公開" if target.id.startswith("_") else "",
                    ))
    return by_name


def module_level_refs(path: Path) -> set[str]:
    """モジュールの**直下**（定義の外）が参照する名前。

    ここが入口側の辺になる——`scripts/`のトップレベルやルーターの登録など、定義の中では
    なくモジュールを読み込んだ時点で走るもの。
    """
    tree = _strip_docstrings(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # 定義そのものではなく、デコレータと既定値・基底クラスだけがモジュール直下で走る。
            for decorator in getattr(node, "decorator_list", []):
                names |= _referenced_names(decorator)
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    names |= _referenced_names(base)
            continue
        names |= _referenced_names(node)
    return names


def find_unresolvable_dynamic_refs(paths: list[Path]) -> list[tuple[str, int, str]]:
    """**名前を組み立てる動的参照**を列挙する（辿れないもの）。

    名前が文字列リテラルなら辺を張れる（`getattr(x, "name")`は拾える、実測）。拾えないのは
    名前を組み立てる形——`getattr(x, "p_" + kind)`・f-string・`globals()[...]`。ここに
    現れたモジュールの定義は、孤立点として出ても**消す前に人が確かめる**。出ないものを
    疑えるようにするのが、この一覧の役目。
    """
    found: list[tuple[str, int, str]] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        module = module_name(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in ("getattr", "setattr", "hasattr") and len(node.args) >= 2:
                    name_arg = node.args[1]
                    if not (isinstance(name_arg, ast.Constant) and isinstance(name_arg.value, str)):
                        found.append((module, node.lineno, f"{node.func.id}(名前を組み立てている)"))
            if isinstance(node, ast.Subscript):
                value = node.value
                if isinstance(value, ast.Call) and isinstance(value.func, ast.Name)                         and value.func.id in ("globals", "locals", "vars"):
                    found.append((module, node.lineno, f"{value.func.id}()[...]"))
    return sorted(found)


def find_entrypoints(by_name: dict[str, list[Definition]], app_files: list[Path]) -> list[Definition]:
    """源流。**この表が閉じていることが完全性の根拠**なので、短く保って人が読めるようにする。"""
    entrypoints: list[Definition] = []
    for definitions in by_name.values():
        for definition in definitions:
            module = definition.module
            reason = ""
            if module.startswith(tuple(f"{d}." for d in ENTRY_DIRS)):
                reason = "実行可能スクリプト"
            elif module.startswith("app.api.routers.") and definition.exempt_reason.startswith("FastAPI"):
                reason = "APIのエンドポイント"
            elif module == "app.main":
                reason = "アプリの起動（lifespan）"
            elif module.startswith("app.batch.") and definition.name in ("main", "run"):
                reason = "バッチの入口"
            if not reason and definition.runs_without_reference:
                # デコレータ・メタクラス・型注釈から使われるものは、コードからの参照が
                # 無くても**本番で実行される**。報告から除くだけでは足りない——
                # 源流に入れないと、そこから呼ばれる実装が丸ごと孤立点に見える
                # （取込アダプタと、それが使う`latitude_from_raw`等で実測）。
                reason = definition.exempt_reason
            if reason:
                definition.is_entrypoint = True
                definition.exempt_reason = definition.exempt_reason or reason
                entrypoints.append(definition)
    return entrypoints


def reachable(by_name: dict[str, list[Definition]], seeds: list[Definition],
              seed_names: set[str], trace: dict[str, str] | None = None) -> set[str]:
    """源流から辿れる定義のqualname。

    名前で解決する——**同名が複数あれば全部へ辺を張る**（曖昧なものは生きている側へ）。
    """
    visited: set[str] = set()
    queue: list[Definition] = list(seeds)
    if trace is not None:
        for definition in seeds:
            trace.setdefault(definition.qualname, f"源流: {definition.exempt_reason}")
    for name in seed_names:
        for definition in by_name.get(name, []):
            queue.append(definition)
            if trace is not None:
                trace.setdefault(definition.qualname, "源流のモジュール直下が参照")
    while queue:
        definition = queue.pop()
        if definition.qualname in visited:
            continue
        visited.add(definition.qualname)
        for name in definition.refs:
            for target in by_name.get(name, []):
                if target.qualname not in visited:
                    if trace is not None:
                        trace.setdefault(target.qualname, definition.qualname)
                    queue.append(target)
    return visited


def main() -> int:
    parser = argparse.ArgumentParser(description="本番の入口から到達しない定義を出す")
    parser.add_argument("--show-entrypoints", action="store_true", help="源流の表を出す")
    parser.add_argument("--show-dynamic", action="store_true",
                        help="名前を組み立てる動的参照（辿れないもの）を出す")
    parser.add_argument("--check", default=None, help="この名前が到達可能かだけを答える")
    parser.add_argument("--why", default=None,
                        help="この名前を生きていると判定した経路を源流まで遡って出す")
    args = parser.parse_args()

    app_files = sorted(APP_ROOT.rglob("*.py"))
    entry_files = [
        path for directory in ENTRY_DIRS
        for path in sorted((BACKEND_ROOT / directory).rglob("*.py"))
    ]
    by_name = collect_definitions(app_files + entry_files)

    entrypoints = find_entrypoints(by_name, app_files)
    # 入口のモジュール直下が参照する名前も源流に含める（スクリプトのトップレベル、
    # ルーターの登録、lifespanが組み立てるもの）。
    seed_names: set[str] = set()
    for path in entry_files + [APP_ROOT / "main.py"]:
        if path.exists():
            seed_names |= module_level_refs(path)
    for path in sorted((APP_ROOT / "api" / "routers").rglob("*.py")):
        seed_names |= module_level_refs(path)

    if args.show_dynamic:
        dynamic = find_unresolvable_dynamic_refs(app_files + entry_files)
        print(f"## 名前を組み立てる動的参照: {len(dynamic)}件")
        print("（ここに現れるモジュールの定義は、孤立点として出ても消す前に人が確かめる）")
        for module, lineno, kind in dynamic:
            print(f"  {module}:{lineno}  {kind}")
        return 0

    if args.show_entrypoints:
        print(f"## 源流（{len(entrypoints)}件）")
        by_reason: dict[str, list[Definition]] = defaultdict(list)
        for definition in entrypoints:
            by_reason[definition.exempt_reason].append(definition)
        for reason, definitions in sorted(by_reason.items()):
            print(f"\n### {reason}（{len(definitions)}件）")
            for definition in sorted(definitions, key=lambda d: d.qualname)[:200]:
                print(f"  {definition.qualname}")
        return 0

    trace: dict[str, str] = {}
    live = reachable(by_name, entrypoints, seed_names, trace)

    if args.why:
        hits = by_name.get(args.why, [])
        if not hits:
            print(f"{args.why}: 定義が見つからない")
            return 1
        for definition in hits:
            if definition.qualname not in live:
                print(f"{definition.qualname} → 到達しない")
                continue
            print(f"{definition.qualname} → 到達する。経路:")
            current = definition.qualname
            for _ in range(50):
                previous = trace.get(current)
                if previous is None:
                    break
                print(f"    ← {previous}")
                if previous.startswith("源流"):
                    break
                current = previous
        return 0

    if args.check:
        hits = by_name.get(args.check, [])
        if not hits:
            print(f"{args.check}: 定義が見つからない")
            return 1
        for definition in hits:
            state = "到達する" if definition.qualname in live else "到達しない"
            print(f"{definition.qualname} ({definition.kind}) → {state}")
        return 0

    # 孤立点をテストが参照しているか。**処分の仕方が変わる**——テストからも参照されない
    # ものはその場で消せる。テストからのみ参照されるものは、テストが状態を初期化・観測
    # するための正当な口か、実装の取り残しかの判断が要る（段階4）。
    test_files = sorted((BACKEND_ROOT / "tests").rglob("*.py"))
    referenced_by_tests: dict[str, int] = defaultdict(int)
    for path in test_files:
        try:
            tree = _strip_docstrings(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        except SyntaxError:
            continue
        for name in _referenced_names(tree):
            referenced_by_tests[name] += 1

    isolated = [
        definition
        for definitions in by_name.values()
        for definition in definitions
        if definition.qualname not in live
        and not definition.exempt_reason
        and definition.module.startswith("app.")
    ]
    total = sum(len(v) for v in by_name.values() if v and v[0].module.startswith("app."))
    print(f"## 本番の入口から到達しない定義: {len(isolated)}件（app配下の公開定義 約{total}件）")
    by_module: dict[str, list[Definition]] = defaultdict(list)
    for definition in isolated:
        by_module[definition.module].append(definition)
    for module, definitions in sorted(by_module.items()):
        print(f"\n### {module}")
        for definition in sorted(definitions, key=lambda d: d.lineno):
            hits = referenced_by_tests.get(definition.name, 0)
            mark = f"テスト{hits}ファイル" if hits else "**テストからも参照なし**"
            print(f"  {definition.lineno:5d}  {definition.kind:8s} {definition.name:32s} {mark}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
