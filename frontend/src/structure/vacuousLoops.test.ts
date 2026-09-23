// @vitest-environment node
/**
 * 絞り込んだ母集団をループして検査するテストが、母集団が空でないことを確かめていることの検査
 * （規約は docs/conventions/testing.md パターン6。backend側は`tests/structure/test_vacuous_loops.py`）。
 *
 * 母集団が0件になると、ループの中の`expect`は1回も走らずテストは緑になる。
 *
 * 母集団はソースから導く——`frontend/src`配下の全`*.test.ts(x)`をTypeScriptの構文木で読み、
 * `it`/`test`のコールバックの中で次の形をした`for...of`を数える:
 *
 * - ループ本体に`expect(...)`がある
 * - 反復対象が`.filter(...)`を経ている。反復対象が名前なら、同じコールバック（無ければ
 *   ファイル直下）でのその名前の`const`/`let`宣言を見る。`Object.entries/values/keys(...)`・
 *   `.entries()/.values()/.keys()`は件数を変えないので剥がして読む
 * - 同じコールバックに、その名前が空でないことの主張が無い
 *   （`expect(xs).not.toHaveLength(0)`・`expect(xs).toHaveLength(3)`・
 *   `expect(xs.length).toBeGreaterThan(0)`・`toBeGreaterThanOrEqual(1)`・`toBe(3)`）
 *
 * その場で絞り込む書き方（`for (const x of xs.filter(...))`）は主張する相手の名前を持たない
 * ため、常に違反になる。
 */
import { mkdtempSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");
const TEST_FILE = /\.test\.tsx?$/;
const SIZE_PRESERVING = new Set(["entries", "values", "keys"]);

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return walk(full);
    return TEST_FILE.test(name) ? [full] : [];
  });
}

function some(node: ts.Node, predicate: (n: ts.Node) => boolean): boolean {
  if (predicate(node)) return true;
  return ts.forEachChild(node, (child) => (some(child, predicate) ? true : undefined)) ?? false;
}

function isNarrowing(node: ts.Node): boolean {
  return some(
    node,
    (n) =>
      ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression) && n.expression.name.text === "filter",
  );
}

function stripSizePreserving(node: ts.Expression): ts.Expression {
  if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression)) {
    const callee = node.expression;
    if (!SIZE_PRESERVING.has(callee.name.text)) return node;
    if (node.arguments.length === 0) return callee.expression;
    if (ts.isIdentifier(callee.expression) && callee.expression.text === "Object" && node.arguments.length === 1) {
      return node.arguments[0];
    }
  }
  return node;
}

function isTestCallback(node: ts.Node): node is ts.ArrowFunction | ts.FunctionExpression {
  if (!(ts.isArrowFunction(node) || ts.isFunctionExpression(node))) return false;
  const call = node.parent;
  if (!ts.isCallExpression(call) || !call.arguments.includes(node)) return false;
  let callee: ts.Expression = call.expression;
  while (ts.isPropertyAccessExpression(callee) || ts.isCallExpression(callee)) callee = callee.expression;
  return ts.isIdentifier(callee) && (callee.text === "it" || callee.text === "test");
}

function declarations(scope: ts.Node, name: string, before: number, direct: boolean): ts.Expression[] {
  const out: ts.Expression[] = [];
  const visit = (node: ts.Node) => {
    if (node.getStart() >= before) return;
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.name.text === name && node.initializer) {
      out.push(node.initializer);
    }
    if (!direct) ts.forEachChild(node, visit);
  };
  if (direct && ts.isSourceFile(scope)) {
    for (const statement of scope.statements) {
      if (ts.isVariableStatement(statement)) statement.declarationList.declarations.forEach(visit);
    }
  } else {
    ts.forEachChild(scope, visit);
  }
  return out;
}

function isSubject(node: ts.Expression, name: string, viaLength: boolean): boolean {
  if (viaLength) {
    return (
      ts.isPropertyAccessExpression(node) &&
      node.name.text === "length" &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === name
    );
  }
  return ts.isIdentifier(node) && node.text === name;
}

function positiveNumber(node: ts.Expression | undefined, min: number): boolean {
  return node !== undefined && ts.isNumericLiteral(node) && Number(node.text) >= min;
}

function assertsNonempty(callback: ts.Node, name: string): boolean {
  return some(callback, (n) => {
    if (!ts.isCallExpression(n) || !ts.isPropertyAccessExpression(n.expression)) return false;
    const matcher = n.expression.name.text;
    let target = n.expression.expression;
    let negated = false;
    if (ts.isPropertyAccessExpression(target) && target.name.text === "not") {
      negated = true;
      target = target.expression;
    }
    if (!ts.isCallExpression(target) || !ts.isIdentifier(target.expression) || target.expression.text !== "expect") {
      return false;
    }
    const subject = target.arguments[0];
    if (subject === undefined) return false;
    const [argument] = n.arguments;
    if (isSubject(subject, name, false)) {
      if (matcher !== "toHaveLength") return false;
      return negated ? argument !== undefined && ts.isNumericLiteral(argument) && argument.text === "0" : positiveNumber(argument, 1);
    }
    if (isSubject(subject, name, true) && !negated) {
      if (matcher === "toBeGreaterThan") return positiveNumber(argument, 0);
      if (matcher === "toBeGreaterThanOrEqual" || matcher === "toBe") return positiveNumber(argument, 1);
    }
    return false;
  });
}

function parameterNames(callback: ts.ArrowFunction | ts.FunctionExpression): Set<string> {
  const names = new Set<string>();
  for (const parameter of callback.parameters) {
    some(parameter.name, (n) => {
      if (ts.isIdentifier(n)) names.add(n.text);
      return false;
    });
  }
  return names;
}

export function vacuousLoops(root: string): string[] {
  const out: string[] = [];
  for (const file of walk(root).sort()) {
    const source = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true);
    const where = (node: ts.Node) =>
      `${relative(root, file).replaceAll("\\", "/")}:${source.getLineAndCharacterOfPosition(node.getStart()).line + 1}`;
    const inspect = (callback: ts.ArrowFunction | ts.FunctionExpression) => {
      const visit = (node: ts.Node): void => {
        if (node !== callback && isTestCallback(node)) return;
        if (ts.isForOfStatement(node)) check(callback, node);
        ts.forEachChild(node, visit);
      };
      ts.forEachChild(callback, visit);
    };
    const check = (callback: ts.ArrowFunction | ts.FunctionExpression, loop: ts.ForOfStatement) => {
      const expects = some(
        loop.statement,
        (n) => ts.isCallExpression(n) && ts.isIdentifier(n.expression) && n.expression.text === "expect",
      );
      if (!expects) return;
      const iterable = stripSizePreserving(loop.expression);
      if (isNarrowing(iterable)) {
        out.push(`${where(loop)}: その場で絞り込んだ母集団をループしている（名前へ束ねて空でないことを確かめる）`);
        return;
      }
      if (!ts.isIdentifier(iterable)) return;
      const name = iterable.text;
      if (parameterNames(callback).has(name)) return;
      const local = declarations(callback, name, loop.getStart(), false);
      const bound = local.length > 0 ? local : declarations(source, name, loop.getStart(), true);
      if (bound.some(isNarrowing) && !assertsNonempty(callback, name)) {
        out.push(`${where(loop)}: 絞り込んだ母集団 \`${name}\` が空でも通る（空でないことを同じテストで確かめる）`);
      }
    };
    const find = (node: ts.Node): void => {
      if (isTestCallback(node)) inspect(node);
      ts.forEachChild(node, find);
    };
    find(source);
  }
  return out;
}

describe("絞り込んだ母集団のループ", () => {
  it("テストは空でないことを確かめてからループする", () => {
    const violations = vacuousLoops(SRC);
    expect(violations, `docs/conventions/testing.md パターン6:\n  ${violations.join("\n  ")}`).toEqual([]);
  });

  it("空になりうる母集団を確かめずにループするテストを捕まえる", () => {
    const root = mkdtempSync(join(tmpdir(), "vacuous-"));
    mkdirSync(join(root, "lib"));
    writeFileSync(
      join(root, "lib", "sample.test.ts"),
      [
        'import { expect, it } from "vitest";',
        "const ALL = [1, 2, 3];",
        'it("picked", () => {',
        "  const picked = ALL.filter((v) => v > 5);",
        "  for (const v of picked) {",
        "    expect(v).toBeGreaterThan(0);",
        "  }",
        "});",
        'it("inline", () => {',
        "  for (const v of ALL.filter((v) => v > 5)) expect(v).toBe(1);",
        "});",
        "",
      ].join("\n"),
    );

    expect(vacuousLoops(root)).toEqual([
      "lib/sample.test.ts:5: 絞り込んだ母集団 `picked` が空でも通る（空でないことを同じテストで確かめる）",
      "lib/sample.test.ts:10: その場で絞り込んだ母集団をループしている（名前へ束ねて空でないことを確かめる）",
    ]);
  });

  it("空でないことを確かめた母集団は通す", () => {
    const root = mkdtempSync(join(tmpdir(), "vacuous-"));
    writeFileSync(
      join(root, "ok.test.ts"),
      [
        'import { expect, it } from "vitest";',
        "const ALL = [1, 2, 3];",
        "const BIG = ALL.filter((v) => v > 1);",
        'it("length", () => {',
        "  const picked = ALL.filter((v) => v > 0);",
        "  expect(picked.length).toBeGreaterThan(0);",
        "  for (const v of picked) expect(v).toBeGreaterThan(0);",
        "});",
        'it("module level", () => {',
        "  expect(BIG).not.toHaveLength(0);",
        "  for (const [i, v] of BIG.entries()) expect(v).toBeGreaterThan(i);",
        "});",
        'it.each([[1]])("given by the caller", (picked) => {',
        "  for (const v of picked) expect(v).toBe(1);",
        "});",
        "",
      ].join("\n"),
    );

    expect(vacuousLoops(root)).toEqual([]);
  });
});
