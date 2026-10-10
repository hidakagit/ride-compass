"""文が宣言の事実を手で書いている形の候補を列挙する（.claude/commands/review.md「構造の問い」の、利用者に見える文の母集団）。

    python scripts/prose_copies.py

frontend の文∩宣言の名前は `frontend/scripts/structure-population.mjs` の (b) が持ち、ここは backend の文と、
走行モデル・難易度の数え方を述べる文を見る。出すのは候補で、判じない（外の製品の名前・宣言そのものの説明が混ざる）。
どれを直すかは読む人が決める。

backend の文は宣言（`backend/app/domain`）の文字列の字句（f 文字列の地の部分を含む。docstring・コメントは除く）のうち日本語を含むもの。
  (1) 文∩宣言の名前: 生成物（`frontend/src/types/generated/`。API の型の2本を除く）の、鍵が `label` の日本語の値で
      3字以上のものを含む文。その名前そのものを宣言する字句（値が名前と同じもの・`label=` の値）は除く。
  (2) 文∩色・寸法・時間幅の語: 色の名前・線の描き方・大小の語、数字と単位（分・時間・日・px・m・km・%）を含む文。
  (3) 説明∩同じ行の値: 1つの呼び出しの中で、説明の文が、同じ呼び出しのほかの文字列（`values` の並び・位置で
      渡した値を含む）のうち英数字の3字以上のものを含む。
frontend と backend の文:
  (4) 走行モデル・難易度の数え方を述べる文: 所要時間の語（所要・走行時間・速度・速さ）と道や天気の条件の語
      （坂・勾配・風・路面）を同じ行に持つ文と、平均・負荷・総量の語と距離・区間の語を同じ行に持つ文。frontend は
      `frontend/src` の .ts・.tsx（テスト・テストの足場・生成物を除く）の行で、コメントの行（`//`・`*`・`/*`・`{/*` で
      始まる行）を除く。
拾わない形（性質に当たりうるのに上に入らない。0件でも無いとは言えず、使う人が読んで見る）:
  - 言い換え: 名前を別の語で書いた文（語の表の別名。`.claude/rules/screen.md`「画面の語」）は (1) に当たらない。
  - 数字を語で書いた時間幅・大きさ（「半日」「倍」等）は (2) に当たらない。
  - 説明が値を言い換えて書いた形（値 `grade1` を「1」と書く等）と、説明の補足を別の宣言で書いた形
    （同じ分類の補足を2つの宣言が持つ）は (3) に当たらない。
  - (4) は行で見るので、行をまたいで続く文の後ろの行と、語を別の語で書いた文（「上り」等）は当たらない。
  - 宣言の外の backend の文（API・services の応答のエラーの `detail` 等）と、実行時の応答の文（軸カタログ等、DB から
    来る文）は、どれにも当たらない。
"""

import ast
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DOMAIN = ROOT / "backend" / "app" / "domain"
FRONTEND_SRC = ROOT / "frontend" / "src"
GENERATED = FRONTEND_SRC / "types" / "generated"

JAPANESE = re.compile(r"[぀-ヿ㐀-鿿]")
NAME_KEYS = {"label"}
LOOK = re.compile(
    r"(?:濃い|薄い|明るい|暗い)?(?:紫|水色|灰色|赤|青|緑|黄色|橙|黒|白)|破線|実線|点線|太く|細く|大きく|小さく"
    r"|\d+(?:\.\d+)?\s*(?:分|時間|日|px|m|km|%)"
)
VALUE_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,}$")
TRAVEL_TIME = re.compile(r"所要|走行時間|速度|速さ")
TRAVEL_CONDITION = re.compile(r"坂|勾配|風|路面")
DIFFICULTY_TOTAL = re.compile(r"平均|負荷|総量")
DIFFICULTY_SPAN = re.compile(r"距離|区間")
FRONTEND_EXCLUDED = [FRONTEND_SRC / name for name in ("testing", "structure", Path("types") / "generated")]
COMMENT_LINE = ("//", "*", "/*", "{/*")


def generated_names() -> list[str]:
    """生成物が名前として配る値。.ts の生成物は `export const X = <JSON> as const;` の形で書かれる。"""
    names: set[str] = set()

    def visit(value: object, key: str | None) -> None:
        if isinstance(value, str):
            if key in NAME_KEYS and JAPANESE.search(value) and len(value) >= 3:
                names.add(value)
        elif isinstance(value, list):
            for item in value:
                visit(item, key)
        elif isinstance(value, dict):
            for k, v in value.items():
                visit(v, k)

    for path in sorted(GENERATED.iterdir()):
        if path.name in ("openapi.json", "api.d.ts"):
            continue
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".ts":
            text = text[text.index("= ") + 2 : text.rindex(" as const;")]
        visit(json.loads(text), None)
    return sorted(names, key=lambda name: (-len(name), name))


def docstring_nodes(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def phrase(node: ast.AST) -> str | None:
    """文の字句（f 文字列は地の部分をつないだもの）。文でなければ None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(part.value for part in node.values if isinstance(part, ast.Constant))
    return None


def name_declarations(tree: ast.AST) -> set[int]:
    """名前そのものを宣言する字句（`label=` の値）。"""
    return {
        id(keyword.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        for keyword in node.keywords
        if keyword.arg in NAME_KEYS
    }


def string_values(node: ast.AST) -> Iterator[str]:
    """呼び出しの引数の中の文字列（並びの要素を含む）。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        yield node.value
    elif isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        for element in node.elts:
            yield from string_values(element)


LABELS = {
    "1": "(1) backend の文∩宣言の名前",
    "2": "(2) backend の文∩色・寸法・時間幅の語",
    "3": "(3) backend の説明∩同じ行の値",
    "4": "(4) 走行モデル・難易度の数え方を述べる文",
}


def describes_model(text: str) -> bool:
    """(4) の文か。"""
    return bool((TRAVEL_TIME.search(text) and TRAVEL_CONDITION.search(text))
                or (DIFFICULTY_TOTAL.search(text) and DIFFICULTY_SPAN.search(text)))


def backend_findings(names: list[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {kind: [] for kind in LABELS}
    for path in sorted(BACKEND_DOMAIN.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        skip = docstring_nodes(tree)
        declared = name_declarations(tree)
        inner = {id(part) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for part in node.values}
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if id(node) in skip or id(node) in inner:
                continue
            text = phrase(node)
            if text is None or not JAPANESE.search(text):
                continue
            where = f"{rel}:{node.lineno}"
            shown = text.strip().replace("\n", " ")[:70]
            hits = [] if id(node) in declared else [name for name in names if name in text and name != text]
            if hits:
                found["1"].append(f"{where}\t{'・'.join(hits)}\t{shown}")
            looks = sorted({match.group(0) for match in LOOK.finditer(text)})
            if looks:
                found["2"].append(f"{where}\t{'・'.join(looks)}\t{shown}")
            if describes_model(text):
                found["4"].append(f"{where}\t{shown}")
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            arguments = [*node.args, *(keyword.value for keyword in node.keywords)]
            for argument in arguments:
                text = phrase(argument)
                if text is None or not JAPANESE.search(text):
                    continue
                others = {
                    value
                    for other in arguments
                    if other is not argument
                    for value in string_values(other)
                    if VALUE_TOKEN.match(value)
                }
                hits = sorted(value for value in others if value in text)
                if hits:
                    shown = text.strip().replace("\n", " ")[:70]
                    found["3"].append(f"{rel}:{argument.lineno}\t{'・'.join(hits)}\t{shown}")
    return found


def frontend_findings() -> list[str]:
    found = []
    for path in sorted(FRONTEND_SRC.rglob("*.ts*")):
        if path.suffix not in (".ts", ".tsx") or re.search(r"\.test\.tsx?$", path.name):
            continue
        if any(path.is_relative_to(excluded) for excluded in FRONTEND_EXCLUDED):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            text = line.strip()
            if text.startswith(COMMENT_LINE) or not JAPANESE.search(text):
                continue
            if describes_model(text):
                found.append(f"{rel}:{number}\t{text[:70]}")
    return found


def main() -> int:
    found = backend_findings(generated_names())
    found["4"] += frontend_findings()
    for kind, lines in found.items():
        print(f"## {LABELS[kind]}: {len(lines)}件")
        for line in lines:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
