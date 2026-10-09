"""Pull Request の差分で変わった行を含む `app` の関数を、mutmut の関数の名前（mangled name）で出す。backend の下で打つ。

引数: 比べる版（ふつうは master との合流点のコミット）
出すもの: 1行に1つ、`app.domain.route.x_route_elevation_gain`・`app.services.x.xǁClassǁmethod` の形。
mutmut が変異を作るのはモジュールの直下の関数と、モジュールの直下のクラスのメソッドだけなので、それに合わせる
（入れ子の関数の行が変わったら、それを囲む直下の関数を出す）。行を消しただけの所は、消した位置を含む関数を出す。
"""
import ast
import re
import subprocess
import sys

HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def changed_lines(base):
    """ファイル（backend からのパス）ごとの、今の版で変わった行（消しただけの所は、その位置の行）。"""
    out = subprocess.run(["git", "diff", "-U0", "--no-color", base, "--", "app"], capture_output=True, text=True,
                         encoding="utf-8", check=True).stdout
    lines: dict[str, set[int]] = {}
    path = None
    for line in out.splitlines():
        if line.startswith("+++ "):
            path = line[6:] if line.startswith("+++ b/") else None
            if path is not None:
                path = path.removeprefix("backend/")
        elif path and path.endswith(".py"):
            m = HUNK.match(line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) or "1")
                lines.setdefault(path, set()).update(range(start, start + max(count, 1)))
    return lines


def module_of(path):
    module = path[:-3].replace("/", ".")
    return module.removesuffix(".__init__")


def functions(path, lines):
    """そのファイルの、変わった行を含む関数の mutmut の名前。"""
    tree = ast.parse(open(path, encoding="utf-8").read())
    module = module_of(path)

    def span(node):
        start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
        return set(range(start, (node.end_lineno or node.lineno) + 1))

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and span(node) & lines:
            yield f"{module}.x_{node.name}"
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and span(child) & lines:
                    yield f"{module}.xǁ{node.name}ǁ{child.name}"


def main():
    found = set()
    for path, lines in changed_lines(sys.argv[1]).items():
        try:
            found.update(functions(path, lines))
        except FileNotFoundError:
            continue  # ファイルごと消した
    print("\n".join(sorted(found)))


if __name__ == "__main__":
    main()
