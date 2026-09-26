// @vitest-environment node
/**
 * 要素ごとに検査するテストが、空の母集団で何も確かめずに通らないことの検査
 * （規約は docs/conventions/testing.md パターン6。backend側は`tests/structure/test_vacuous_loops.py`）。
 *
 * 母集団が0件になると、要素ごとの`expect`は1回も走らずテストは緑になる。
 *
 * 性質は「絞り込んだ後の要素にしか届かないアサーション」で、絞り込みの書き方によらない。
 * 母集団はソースから導く——`frontend/src`配下の全`*.test.ts(x)`をTypeScriptの構文木で読み、
 * `it`/`test`のコールバックの中の要素ごとの検査を数える:
 *
 * - 本体に`expect(...)`がある`for...of`・`.forEach(...)`と、空なら真になる量化
 *   （`expect(xs.every(...)).toBe(true)`・`expect(xs.some(...)).toBe(false)`等）
 * - 絞り込みがその場にある: 反復対象が`.filter(...)`を経ている、またはループ本体の条件
 *   （`if`の片側だけに`expect`がある・`continue`等で抜ける）を通らないと`expect`へ届かない。
 *   絞り込んだ後の母集団に名前が無く、空でないことを主張できないため常に違反になる
 * - 絞り込みが名前の宣言にある: 反復対象が名前（か、引数の無いその呼び出し）なら、同じ
 *   コールバック（無ければファイル直下）でのその名前の`const`/`let`宣言を見る。
 *   `Object.entries/values/keys(...)`・`.entries()/.values()/.keys()`は件数を変えないので剥がして読む。
 *   同じコールバックに、その名前が空でないことの主張
 *   （`expect(xs).not.toHaveLength(0)`・`expect(xs).toHaveLength(3)`・
 *   `expect(xs.length).toBeGreaterThan(0)`・`toBeGreaterThanOrEqual(1)`・`toBe(3)`）が無ければ違反
 */
import { mkdtempSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";

import ts from "typescript";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");
const TEST_FILE = /\.test\.tsx?$/;
const SIZE_PRESERVING = new Set(["entries", "values", "keys"]);

type Flow = "asserts" | "exits" | "falls";
type Callback = ts.ArrowFunction | ts.FunctionExpression;

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

function isExpectCall(node: ts.Node): node is ts.CallExpression {
  return ts.isCallExpression(node) && ts.isIdentifier(node.expression) && node.expression.text === "expect";
}

function containsExpect(node: ts.Node): boolean {
  return some(node, isExpectCall);
}

function isNarrowing(node: ts.Node): boolean {
  return some(
    node,
    (n) => ts.isCallExpression(n) && ts.isPropertyAccessExpression(n.expression) && n.expression.name.text === "filter",
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

/** 1つの要素が文の並びを通ったとき、`expect`へ必ず届くか。
 *
 * 入れ子のループは、その中身を自分の母集団として別に数えるため、`expect`を含めば届くとみなす。 */
function flow(statements: readonly ts.Statement[]): Flow {
  for (const statement of statements) {
    if (ts.isIfStatement(statement)) {
      const branches = [
        flow([statement.thenStatement]),
        statement.elseStatement ? flow([statement.elseStatement]) : "falls",
      ];
      if (branches.includes("exits")) return "exits";
      if (branches.every((branch) => branch === "asserts")) return "asserts";
      continue;
    }
    if (ts.isContinueStatement(statement) || ts.isBreakStatement(statement) || ts.isReturnStatement(statement)) {
      return "exits";
    }
    const inner = ts.isBlock(statement) ? statement : ts.isTryStatement(statement) ? statement.tryBlock : undefined;
    if (inner !== undefined) {
      const result = flow(inner.statements);
      if (result !== "falls") return result;
      continue;
    }
    if (containsExpect(statement)) return "asserts";
  }
  return "falls";
}

function bodyFlow(body: ts.Statement | ts.ConciseBody): Flow {
  if (ts.isBlock(body)) return flow(body.statements);
  return ts.isExpression(body) ? (containsExpect(body) ? "asserts" : "falls") : flow([body as ts.Statement]);
}

function isTestCallback(node: ts.Node): node is Callback {
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

/** 母集団を名指す名前。名前そのものか、母集団を返す引数の無い呼び出し（`rows()`）。 */
function populationName(node: ts.Expression): string | undefined {
  if (ts.isIdentifier(node)) return node.text;
  if (ts.isCallExpression(node) && node.arguments.length === 0 && ts.isIdentifier(node.expression)) {
    return node.expression.text;
  }
  return undefined;
}

function isSubject(node: ts.Expression, name: string, viaLength: boolean): boolean {
  if (viaLength) {
    return (
      ts.isPropertyAccessExpression(node) && node.name.text === "length" && populationName(node.expression) === name
    );
  }
  return populationName(node) === name;
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
    if (!isExpectCall(target)) return false;
    const subject = target.arguments[0];
    if (subject === undefined) return false;
    const [argument] = n.arguments;
    if (isSubject(subject, name, false)) {
      if (matcher !== "toHaveLength") return false;
      return negated
        ? argument !== undefined && ts.isNumericLiteral(argument) && argument.text === "0"
        : positiveNumber(argument, 1);
    }
    if (isSubject(subject, name, true) && !negated) {
      if (matcher === "toBeGreaterThan") return positiveNumber(argument, 0);
      if (matcher === "toBeGreaterThanOrEqual" || matcher === "toBe") return positiveNumber(argument, 1);
    }
    return false;
  });
}

/** `expect(x)`の後ろの照合が、`x`を真と主張するなら true・偽と主張するなら false。 */
function expectedTruth(expectCall: ts.CallExpression): boolean | undefined {
  let access = expectCall.parent;
  let negated = false;
  if (ts.isPropertyAccessExpression(access) && access.name.text === "not") {
    negated = true;
    access = access.parent;
  }
  if (!ts.isPropertyAccessExpression(access) || !ts.isCallExpression(access.parent)) return undefined;
  const matcher = access.name.text;
  const [argument] = access.parent.arguments;
  let truth: boolean | undefined;
  if (matcher === "toBeTruthy") truth = true;
  else if (matcher === "toBeFalsy") truth = false;
  else if (["toBe", "toEqual", "toStrictEqual"].includes(matcher) && argument !== undefined) {
    if (argument.kind === ts.SyntaxKind.TrueKeyword) truth = true;
    if (argument.kind === ts.SyntaxKind.FalseKeyword) truth = false;
  }
  return truth === undefined ? undefined : truth !== negated;
}

/** 空なら真になる量化（`every`を真・`some`を偽と主張する）の反復対象。 */
function quantified(expectCall: ts.CallExpression): ts.Expression | undefined {
  const [subject] = expectCall.arguments;
  if (subject === undefined || !ts.isCallExpression(subject) || !ts.isPropertyAccessExpression(subject.expression)) {
    return undefined;
  }
  const quantifier = subject.expression.name.text;
  const truth = expectedTruth(expectCall);
  if ((quantifier === "every" && truth === true) || (quantifier === "some" && truth === false)) {
    return subject.expression.expression;
  }
  return undefined;
}

/** `.forEach(cb)`の反復対象とコールバック。 */
function forEachLoop(node: ts.Node): { iterable: ts.Expression; body: ts.ConciseBody } | undefined {
  if (!ts.isCallExpression(node) || !ts.isPropertyAccessExpression(node.expression)) return undefined;
  if (node.expression.name.text !== "forEach") return undefined;
  const [callback] = node.arguments;
  if (callback === undefined || !(ts.isArrowFunction(callback) || ts.isFunctionExpression(callback))) return undefined;
  return { iterable: node.expression.expression, body: callback.body };
}

function parameterNames(callback: Callback): Set<string> {
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
    const check = (callback: Callback, node: ts.Node, iterable: ts.Expression, guarded: boolean) => {
      const population = stripSizePreserving(iterable);
      if (isNarrowing(population)) {
        out.push(`${where(node)}: その場で絞り込んだ母集団を検査している（名前へ束ねて空でないことを確かめる）`);
        return;
      }
      if (guarded) {
        out.push(
          `${where(node)}: ループの中の条件を通った要素にしか届かないアサーションがある（絞り込みを名前へ束ねて空でないことを確かめる）`,
        );
        return;
      }
      const name = populationName(population);
      if (name === undefined || parameterNames(callback).has(name)) return;
      const local = declarations(callback, name, node.getStart(), false);
      const bound = local.length > 0 ? local : declarations(source, name, node.getStart(), true);
      if (bound.some(isNarrowing) && !assertsNonempty(callback, name)) {
        out.push(`${where(node)}: 絞り込んだ母集団 \`${name}\` が空でも通る（空でないことを同じテストで確かめる）`);
      }
    };
    const inspect = (callback: Callback) => {
      const visit = (node: ts.Node): void => {
        if (node !== callback && isTestCallback(node)) return;
        const each = forEachLoop(node);
        if (ts.isForOfStatement(node) && containsExpect(node.statement)) {
          check(callback, node, node.expression, bodyFlow(node.statement) !== "asserts");
        } else if (each !== undefined && containsExpect(each.body)) {
          check(callback, node, each.iterable, bodyFlow(each.body) !== "asserts");
        } else if (isExpectCall(node)) {
          const iterable = quantified(node);
          if (iterable !== undefined) check(callback, node, iterable, false);
        }
        ts.forEachChild(node, visit);
      };
      ts.forEachChild(callback, visit);
    };
    const find = (node: ts.Node): void => {
      if (isTestCallback(node)) inspect(node);
      ts.forEachChild(node, find);
    };
    find(source);
  }
  return out;
}

describe("要素ごとの検査の母集団", () => {
  it("テストは空でないことを確かめてから要素ごとに検査する", () => {
    const violations = vacuousLoops(SRC);
    expect(violations, `docs/conventions/testing.md パターン6:\n  ${violations.join("\n  ")}`).toEqual([]);
  });

  it("空になりうる母集団を、絞り込みの書き方によらず捕まえる", () => {
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
        'it("guarded", () => {',
        "  for (const v of ALL) {",
        "    if (v > 5) expect(v).toBe(1);",
        "  }",
        "  ALL.forEach((v) => {",
        "    if (v <= 5) return;",
        "    expect(v).toBe(1);",
        "  });",
        "});",
        'it("quantified", () => {',
        "  expect(ALL.filter((v) => v > 5).every((v) => v > 0)).toBe(true);",
        "  expect(ALL.filter((v) => v > 5).some((v) => v < 0)).toBe(false);",
        "  const rows = () => ALL.filter((v) => v > 5);",
        "  expect(rows().every((v) => v > 0)).toBeTruthy();",
        "});",
        "",
      ].join("\n"),
    );

    expect(vacuousLoops(root)).toEqual([
      "lib/sample.test.ts:5: 絞り込んだ母集団 `picked` が空でも通る（空でないことを同じテストで確かめる）",
      "lib/sample.test.ts:10: その場で絞り込んだ母集団を検査している（名前へ束ねて空でないことを確かめる）",
      "lib/sample.test.ts:13: ループの中の条件を通った要素にしか届かないアサーションがある（絞り込みを名前へ束ねて空でないことを確かめる）",
      "lib/sample.test.ts:16: ループの中の条件を通った要素にしか届かないアサーションがある（絞り込みを名前へ束ねて空でないことを確かめる）",
      "lib/sample.test.ts:22: その場で絞り込んだ母集団を検査している（名前へ束ねて空でないことを確かめる）",
      "lib/sample.test.ts:23: その場で絞り込んだ母集団を検査している（名前へ束ねて空でないことを確かめる）",
      "lib/sample.test.ts:25: 絞り込んだ母集団 `rows` が空でも通る（空でないことを同じテストで確かめる）",
    ]);
  });

  it("空でないことを確かめた母集団と、全要素がexpectへ届くループは通す", () => {
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
        "  expect(picked.every((v) => v > 0)).toBe(true);",
        "});",
        'it("module level", () => {',
        "  expect(BIG).not.toHaveLength(0);",
        "  for (const [i, v] of BIG.entries()) expect(v).toBeGreaterThan(i);",
        "});",
        'it("function returning the population", () => {',
        "  const rows = () => ALL.filter((v) => v > 0);",
        "  expect(rows()).not.toHaveLength(0);",
        "  expect(rows().every((v) => v > 0)).toBe(true);",
        "});",
        'it("every element reaches expect", () => {',
        "  for (const v of ALL) {",
        "    if (v > 1) expect(v).toBeGreaterThan(1);",
        "    else expect(v).toBe(1);",
        "  }",
        "  ALL.forEach((v) => expect(v).toBeGreaterThan(0));",
        "  expect(ALL.filter((v) => v > 5).some((v) => v > 0)).toBe(true);",
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
