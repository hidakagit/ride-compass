// 画面が backend の宣言を持ち直している形の候補を、構文木から列挙する（.claude/commands/review.md「構造の問い」の frontend の母集団）。
//
//   node scripts/structure-population.mjs [--axis-catalog <JSONのファイル>]
//
// 母集団は src の .ts・.tsx のうち、テスト（*.test.ts(x)）・テストの足場（src/testing・src/structure）・生成物（src/types/generated）を除いたもの。
// 出すのは候補で、判じない（偶然の一致・型で縛られた分岐が混ざる）。どれを直すかは読む人が決める。
//   (a) 文字列リテラル∩生成物の識別子: 式の中の文字列リテラルで、値が生成物の文字列の値（識別子の形のもの）と同じもの。
//       import の指定子・型の位置・オブジェクトの鍵の位置は除く。
//   (b) 画面の文∩本番の軸名・現象の語: 日本語を含む文字列・テンプレートの断片・JSX の文のうち、語を含むもの。語は生成物の
//       名前（鍵が label の日本語の値で3字以上）と、--axis-catalog で渡した軸カタログ（本番の backend の /api/axis-catalog の応答）の
//       軸の label・chip_label。渡さなければ軸名は入らない。
//   (c) 重み・閾値の文脈の数値リテラル（関数の中を含む）: 0・1 を除く数値で、比べる式の片側・`||`／`??` の右・Math.min／max の引数か、
//       名前が重み・閾値・上下限を表す宣言・引数の既定・代入の値になっているもの。
//   (d) 宣言の意味の鍵を名指す分岐: 文字列リテラルと、鍵を表す名前（key・id・kind 等）の値を比べる式・そうした値で分ける switch の case と、
//       値の並び（values・keys 等）が文字列・真偽の字句を含むかを見る `includes`。

import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";
import ts from "typescript";

const frontendRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const srcRoot = path.join(frontendRoot, "src");
const generatedRoot = path.join(srcRoot, "types", "generated");

const { values } = parseArgs({
  options: { "axis-catalog": { type: "string" } },
});

function walk(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? walk(full) : [full];
  });
}

const EXCLUDED_DIRS = ["testing", "structure", path.join("types", "generated")].map(
  (dir) => path.join(srcRoot, dir) + path.sep,
);
const sources = walk(srcRoot).filter(
  (file) => /\.tsx?$/.test(file) && !/\.test\.tsx?$/.test(file) && !EXCLUDED_DIRS.some((dir) => file.startsWith(dir)),
);

const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/;
const JAPANESE = /[぀-ヿ㐀-鿿]/;

/** 生成物の文字列の値と、その値を持つ鍵（配列の要素なら外側の鍵）。.ts の生成物は構文木から、.json は値の木から取る。
 * openapi.json・api.d.ts は API の型で、宣言の値を持たない。 */
function generatedStrings() {
  const strings = [];
  const visitJson = (value, key) => {
    if (typeof value === "string") strings.push({ value, key });
    else if (Array.isArray(value)) value.forEach((item) => visitJson(item, key));
    else if (value && typeof value === "object") Object.entries(value).forEach(([k, v]) => visitJson(v, k));
  };
  for (const file of walk(generatedRoot)) {
    const name = path.basename(file);
    if (name === "openapi.json" || name === "api.d.ts") continue;
    const text = readFileSync(file, "utf-8");
    if (name.endsWith(".json")) {
      visitJson(JSON.parse(text), null);
      continue;
    }
    const visit = (node) => {
      if (ts.isStringLiteral(node) && !(ts.isPropertyAssignment(node.parent) && node.parent.name === node)) {
        let owner = node.parent;
        while (ts.isArrayLiteralExpression(owner)) owner = owner.parent;
        strings.push({
          value: node.text,
          key: ts.isPropertyAssignment(owner) ? owner.name.getText().replaceAll('"', "") : null,
        });
      }
      ts.forEachChild(node, visit);
    };
    visit(ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true));
  }
  return strings;
}

const generated = generatedStrings();
const generatedIdentifiers = new Set(generated.map(({ value }) => value).filter((value) => IDENTIFIER.test(value)));

function axisCatalogWords() {
  if (!values["axis-catalog"]) return [];
  const catalog = JSON.parse(readFileSync(values["axis-catalog"], "utf-8"));
  return catalog.axes.flatMap((axis) => [axis.label, axis.chip_label]).filter(Boolean);
}

/** 現象の語は、生成物が名前として配る値（鍵が label）のうち3字以上のもの。2字以下は「風」「時間」のような一般語と区別できない。 */
const phenomenonWords = generated
  .filter(({ value, key }) => key === "label" && JAPANESE.test(value) && value.length >= 3)
  .map(({ value }) => value);
const words = [...new Set([...phenomenonWords, ...axisCatalogWords()])].sort((a, b) => b.length - a.length);

const KEY_NAME =
  /^(key|id|kind|role|source|group|property|level|type|tier|category|layerId|axisId|attrId)$|(Id|Key|_id|_key|_kind)$/;
const LIMIT_NAME = /weight|threshold|min|max|limit|ratio|share|bound|floor|ceil|cap|tolerance|eps|default/i;
const COMPARISON = new Set([
  ts.SyntaxKind.LessThanToken,
  ts.SyntaxKind.LessThanEqualsToken,
  ts.SyntaxKind.GreaterThanToken,
  ts.SyntaxKind.GreaterThanEqualsToken,
  ts.SyntaxKind.EqualsEqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsEqualsToken,
  ts.SyntaxKind.EqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsToken,
]);
const EQUALITY = new Set([
  ts.SyntaxKind.EqualsEqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsEqualsToken,
  ts.SyntaxKind.EqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsToken,
]);

/** 式の最後の名前（`a.b.key` なら key、`x` なら x、`a["key"]` なら key）。 */
function lastName(node) {
  if (ts.isIdentifier(node)) return node.text;
  if (ts.isPropertyAccessExpression(node)) return node.name.text;
  if (ts.isElementAccessExpression(node) && ts.isStringLiteral(node.argumentExpression))
    return node.argumentExpression.text;
  if (
    ts.isNonNullExpression(node) ||
    ts.isParenthesizedExpression(node) ||
    ts.isAsExpression(node) ||
    ts.isSatisfiesExpression(node)
  )
    return lastName(node.expression);
  return null;
}

function isTypePosition(node) {
  for (let current = node.parent; current; current = current.parent) {
    if (ts.isTypeNode(current)) return true;
    if (ts.isExpression(current) || ts.isStatement(current)) return false;
  }
  return false;
}

function isStringLike(node) {
  return ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node);
}

/** 宣言の値の並び（行の`values`・鍵の並び）の名前。 */
const VALUE_LIST_NAME = /(values|keys|ids|kinds)$/i;

function isLiteralValue(node) {
  return isStringLike(node) || node.kind === ts.SyntaxKind.TrueKeyword || node.kind === ts.SyntaxKind.FalseKeyword;
}

/** 数値リテラルが置かれた文脈（(c) に当たらなければ null）。 */
function numericContext(literal) {
  let node = literal;
  if (ts.isPrefixUnaryExpression(node.parent) && node.parent.operator === ts.SyntaxKind.MinusToken) node = node.parent;
  const parent = node.parent;
  if (ts.isBinaryExpression(parent)) {
    const op = parent.operatorToken.kind;
    if (COMPARISON.has(op)) return "比べる式";
    if ((op === ts.SyntaxKind.BarBarToken || op === ts.SyntaxKind.QuestionQuestionToken) && parent.right === node)
      return "既定の値";
    if (op === ts.SyntaxKind.EqualsToken && LIMIT_NAME.test(lastName(parent.left) ?? "")) return "名前の付いた値";
  }
  if (ts.isCallExpression(parent) && /^(min|max|clamp)$/i.test(lastName(parent.expression) ?? ""))
    return "上下限の引数";
  if (
    (ts.isVariableDeclaration(parent) ||
      ts.isPropertyAssignment(parent) ||
      ts.isParameter(parent) ||
      ts.isBindingElement(parent)) &&
    parent.initializer === node &&
    ts.isIdentifier(parent.name) &&
    LIMIT_NAME.test(parent.name.text)
  )
    return "名前の付いた値";
  if (ts.isPropertyAssignment(parent) && parent.initializer === node && LIMIT_NAME.test(parent.name.getText()))
    return "名前の付いた値";
  return null;
}

const found = { a: [], b: [], c: [], d: [] };

for (const file of sources) {
  const text = readFileSync(file, "utf-8");
  const source = ts.createSourceFile(
    file,
    text,
    ts.ScriptTarget.Latest,
    true,
    file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const where = (node) =>
    `${path.relative(frontendRoot, file).replaceAll("\\", "/")}:${source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1}`;
  const push = (kind, node, detail) => found[kind].push(`${where(node)}\t${detail}`);

  const visit = (node) => {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node) || ts.isImportTypeNode(node)) return;

    if (isStringLike(node) && !isTypePosition(node)) {
      const isKey =
        (ts.isPropertyAssignment(node.parent) || ts.isPropertySignature(node.parent)) && node.parent.name === node;
      if (!isKey && generatedIdentifiers.has(node.text)) push("a", node, JSON.stringify(node.text));
    }

    const phrase =
      ts.isStringLiteral(node) ||
      ts.isNoSubstitutionTemplateLiteral(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node) ||
      ts.isJsxText(node)
        ? node.text
        : null;
    if (phrase && JAPANESE.test(phrase) && !isTypePosition(node)) {
      const hits = words.filter((word) => phrase.includes(word));
      if (hits.length > 0) push("b", node, `${hits.join("・")}\t${phrase.trim().slice(0, 60)}`);
    }

    if (ts.isNumericLiteral(node)) {
      const value = Number(node.text);
      const context = value === 0 || value === 1 ? null : numericContext(node);
      if (context) push("c", node, `${node.text}\t${context}\t${node.parent.getText(source).slice(0, 60)}`);
    }

    if (ts.isBinaryExpression(node) && EQUALITY.has(node.operatorToken.kind)) {
      const [literal, other] = isStringLike(node.left) ? [node.left, node.right] : [node.right, node.left];
      if (isStringLike(literal) && KEY_NAME.test(lastName(other) ?? ""))
        push("d", node, node.getText(source).slice(0, 80));
    }
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      node.expression.name.text === "includes" &&
      VALUE_LIST_NAME.test(lastName(node.expression.expression) ?? "") &&
      node.arguments.length === 1 &&
      isLiteralValue(node.arguments[0])
    ) {
      push("d", node, node.getText(source).slice(0, 80));
    }
    if (ts.isCaseClause(node) && isStringLike(node.expression)) {
      const switched = node.parent.parent.expression;
      if (KEY_NAME.test(lastName(switched) ?? ""))
        push("d", node, `case ${node.expression.getText(source)}（${switched.getText(source)}）`);
    }

    ts.forEachChild(node, visit);
  };
  visit(source);
}

const LABELS = {
  a: "(a) 文字列リテラル∩生成物の識別子",
  b: "(b) 画面の文∩本番の軸名・現象の語",
  c: "(c) 重み・閾値の文脈の数値リテラル",
  d: "(d) 宣言の意味の鍵を名指す分岐",
};
for (const kind of Object.keys(found)) {
  console.log(
    `## ${LABELS[kind]}: ${found[kind].length}件${kind === "b" && !values["axis-catalog"] ? "（軸名なし: --axis-catalog を渡していない）" : ""}`,
  );
  for (const line of found[kind]) console.log(line);
}
