// @vitest-environment node
/**
 * 要素ごとに確かめるテストが、母集団が空のとき何も確かめずに通る形になっていないかを見る
 * （規約は .claude/rules/testing-structure.md パターン6。backend の同じ検査は
 * `backend/tests/structure/test_vacuous_loops.py`）。
 *
 * 母集団は`frontend/src`配下の全`*.test.ts(x)`で、TypeScriptの構文木で読む。
 *
 * 要素ごとの確かめ:
 * - 本体に`expect(...)`・`assert(...)`がある`for...of`・`for...in`・`.forEach(...)`
 * - 空なら真になる量化（`expect(xs.every(...)).toBe(true)`・`expect(xs.some(...)).toBe(false)`と、
 *   `toBeTruthy`・`toBeFalsy`・`.not`で同じ意味になるもの）
 *
 * 違反（どれか1つ）:
 * 1. 反復対象がその場で`.filter(...)`を経ている（絞った後の母集団に名前が無く、空でないことを主張できない）
 * 2. ループ本体の条件を通らないと確かめに届かない——片側にだけ確かめがある`if`・三項・`catch`・
 *    `&&`/`||`/`??`の右側、または本体の`continue`・`break`・`return`（入れ子の関数の中のものは除く）
 * 3. 反復対象の名前が`.filter(...)`で束ねられていて、同じ関数（テストのコールバック）に、その名前か、
 *    件数を変えずにそれを写した名前が空でないことの主張が無い。主張として読む形:
 *    `expect(xs).toHaveLength(n)`（n>0）・`expect(xs).not.toHaveLength(0)`・
 *    `expect(xs.length).toBeGreaterThan(n)`（n>=0）・`toBeGreaterThanOrEqual(n)`（n>=1）・`toBe(n)`（n>0）・
 *    `.not.toBe(0)`
 *
 * 件数を変えない写し（`.map`・`.sort`・`.toSorted`・`.reverse`・`.entries()`等・`Object.entries/values/keys`・
 * `Array.from`・`[...xs]`）は剥がして読み、名前は引数の無い呼び出し（`xs()`）も含めて、外側の
 * スコープの`const`/`let`/`function`宣言へ辿る。
 *
 * 見ないもの: 反復対象が関数の引数のループ（母集団は呼び出し側が決める）。量化のコールバックの中の
 * 条件（`xs.every((x) => !cond || ok)`）。上に無い形の空でないことの主張（`expect(xs).toEqual([...])`等）は
 * 読まないので、そのときは上の形の主張を1行足す。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

import { SRC_ROOT, walkTree } from "./sourceTree";

type Finding = { file: string; line: number; reason: string };

const FILTERED_HERE = "反復対象がその場で絞り込まれている";
const GATED = "本体の条件を通らないと確かめに届かない";
const NOT_ASSERTED = "絞り込んだ名前が空でないことの主張が同じ関数に無い";

const ASSERTION_ROOTS = new Set(["expect", "assert"]);
const SAME_COUNT_METHODS = new Set(["map", "sort", "toSorted", "reverse", "toReversed", "entries", "values", "keys"]);
const SAME_COUNT_FUNCTIONS = new Set(["Object.entries", "Object.values", "Object.keys", "Array.from"]);

function unwrap(node: ts.Expression): ts.Expression {
  let current = node;
  while (
    ts.isParenthesizedExpression(current) ||
    ts.isAsExpression(current) ||
    ts.isNonNullExpression(current) ||
    ts.isSatisfiesExpression(current)
  ) {
    current = current.expression;
  }
  return current;
}

function calleeName(call: ts.CallExpression): string {
  const callee = call.expression;
  if (ts.isIdentifier(callee)) return callee.text;
  if (ts.isPropertyAccessExpression(callee) && ts.isIdentifier(callee.expression)) {
    return `${callee.expression.text}.${callee.name.text}`;
  }
  return "";
}

function isAssertionCall(node: ts.Node): boolean {
  if (!ts.isCallExpression(node)) return false;
  let root: ts.Expression = node.expression;
  while (ts.isPropertyAccessExpression(root) || ts.isCallExpression(root)) root = root.expression;
  return ts.isIdentifier(root) && ASSERTION_ROOTS.has(root.text);
}

const isFunctionLike = (node: ts.Node) =>
  ts.isArrowFunction(node) ||
  ts.isFunctionExpression(node) ||
  ts.isFunctionDeclaration(node) ||
  ts.isMethodDeclaration(node);
const isLoop = (node: ts.Node) =>
  ts.isForOfStatement(node) ||
  ts.isForInStatement(node) ||
  ts.isForStatement(node) ||
  ts.isWhileStatement(node) ||
  ts.isDoStatement(node);

/** 入れ子の関数・ループへは入らずに、`node`の下を辿る。 */
function forEachOwn(node: ts.Node, visit: (child: ts.Node) => void): void {
  ts.forEachChild(node, (child) => {
    visit(child);
    if (!isFunctionLike(child) && !isLoop(child)) forEachOwn(child, visit);
  });
}

function containsAssertion(node: ts.Node): boolean {
  let found = false;
  const visit = (child: ts.Node) => {
    if (found) return;
    if (isAssertionCall(child)) found = true;
    else ts.forEachChild(child, visit);
  };
  visit(node);
  return found;
}

/** 反復対象を、件数を変えない写しを剥がしながら辿る。途中に`.filter`があれば`filtered`。 */
function strip(expression: ts.Expression): { base: ts.Expression; filtered: boolean } {
  let current = unwrap(expression);
  for (;;) {
    if (
      ts.isArrayLiteralExpression(current) &&
      current.elements.length === 1 &&
      ts.isSpreadElement(current.elements[0])
    ) {
      current = unwrap(current.elements[0].expression);
    } else if (
      ts.isCallExpression(current) &&
      SAME_COUNT_FUNCTIONS.has(calleeName(current)) &&
      current.arguments.length > 0
    ) {
      current = unwrap(current.arguments[0]);
    } else if (ts.isCallExpression(current) && ts.isPropertyAccessExpression(current.expression)) {
      const method = current.expression.name.text;
      if (method === "filter") return { base: current, filtered: true };
      if (!SAME_COUNT_METHODS.has(method)) return { base: current, filtered: false };
      current = unwrap(current.expression.expression);
    } else {
      return { base: current, filtered: false };
    }
  }
}

/** `xs`・`xs()`の名前。 */
function referencedName(expression: ts.Expression): string | undefined {
  if (ts.isIdentifier(expression)) return expression.text;
  if (ts.isCallExpression(expression) && expression.arguments.length === 0 && ts.isIdentifier(expression.expression)) {
    return expression.expression.text;
  }
  return undefined;
}

/** `from`から外側へ、`name`を宣言した式（関数なら返す式）を探す。 */
function declaredValue(name: string, from: ts.Node): ts.Expression | undefined {
  for (let scope: ts.Node | undefined = from.parent; scope; scope = scope.parent) {
    const statements = ts.isBlock(scope) || ts.isSourceFile(scope) ? scope.statements : undefined;
    for (const statement of statements ?? []) {
      if (ts.isVariableStatement(statement)) {
        for (const declaration of statement.declarationList.declarations) {
          if (ts.isIdentifier(declaration.name) && declaration.name.text === name && declaration.initializer) {
            return returnedValue(unwrap(declaration.initializer));
          }
        }
      }
      if (ts.isFunctionDeclaration(statement) && statement.name?.text === name && statement.body) {
        return singleReturn(statement.body);
      }
    }
  }
  return undefined;
}

function returnedValue(expression: ts.Expression): ts.Expression | undefined {
  if (!ts.isArrowFunction(expression) && !ts.isFunctionExpression(expression)) return expression;
  return ts.isBlock(expression.body) ? singleReturn(expression.body) : expression.body;
}

function singleReturn(body: ts.Block): ts.Expression | undefined {
  const returns = body.statements.filter(ts.isReturnStatement);
  return returns.length === 1 ? returns[0].expression : undefined;
}

/** 反復対象の名前を宣言へ辿り、`.filter`で束ねられていれば、その途中の名前を全部返す。 */
function filteredNames(iterable: ts.Expression, at: ts.Node): string[] | undefined {
  const names: string[] = [];
  let expression: ts.Expression | undefined = iterable;
  while (expression) {
    const { base, filtered } = strip(expression);
    if (filtered) return names;
    const name = referencedName(base);
    if (!name || names.includes(name)) return undefined;
    names.push(name);
    expression = declaredValue(name, at);
  }
  return undefined;
}

function numberLiteral(node: ts.Expression | undefined): number | undefined {
  return node && ts.isNumericLiteral(unwrap(node)) ? Number((unwrap(node) as ts.NumericLiteral).text) : undefined;
}

/** `expect(<subject>)[.not].<matcher>(<argument>)`を分解する。 */
function matcherCall(
  node: ts.Node,
): { subject: ts.Expression; negated: boolean; matcher: string; argument?: ts.Expression } | undefined {
  if (!ts.isCallExpression(node) || !ts.isPropertyAccessExpression(node.expression)) return undefined;
  let target = node.expression.expression;
  let negated = false;
  if (ts.isPropertyAccessExpression(target) && target.name.text === "not") {
    negated = true;
    target = target.expression;
  }
  if (!ts.isCallExpression(target) || calleeName(target) !== "expect" || target.arguments.length !== 1)
    return undefined;
  return {
    subject: unwrap(target.arguments[0]),
    negated,
    matcher: node.expression.name.text,
    argument: node.arguments[0],
  };
}

function assertsNonEmpty(node: ts.Node, names: readonly string[]): boolean {
  const call = matcherCall(node);
  if (!call) return false;
  const { subject, negated, matcher } = call;
  const n = numberLiteral(call.argument);
  if (n === undefined) return false;
  const named = (expression: ts.Expression) => {
    const name = referencedName(unwrap(expression));
    return name !== undefined && names.includes(name);
  };
  if (named(subject) && matcher === "toHaveLength") return negated ? n === 0 : n > 0;
  if (!ts.isPropertyAccessExpression(subject) || subject.name.text !== "length" || !named(subject.expression))
    return false;
  if (negated) return matcher === "toBe" && n === 0;
  if (matcher === "toBeGreaterThan") return n >= 0;
  if (matcher === "toBeGreaterThanOrEqual") return n >= 1;
  return matcher === "toBe" && n > 0;
}

function enclosingFunction(node: ts.Node): ts.Node {
  let current = node.parent;
  while (current && !isFunctionLike(current) && !ts.isSourceFile(current)) current = current.parent;
  return current;
}

function hasNonEmptyAssertion(scope: ts.Node, names: readonly string[]): boolean {
  let found = false;
  const visit = (node: ts.Node) => {
    if (found) return;
    if (assertsNonEmpty(node, names)) found = true;
    else ts.forEachChild(node, visit);
  };
  visit(scope);
  return found;
}

/** 確かめから本体まで遡り、片側にだけ確かめのある分岐を経るか。入れ子の関数・ループに入っていれば、その確かめは数えない。 */
function gatedOnOneSide(assertion: ts.Node, body: ts.Node): boolean {
  let child = assertion;
  for (let node = assertion.parent; node && node !== body; child = node, node = node.parent) {
    if (isFunctionLike(node) || isLoop(node)) return false;
    if (ts.isIfStatement(node) && child !== node.expression) {
      const other = child === node.thenStatement ? node.elseStatement : node.thenStatement;
      if (!other || !containsAssertion(other)) return true;
    }
    if (ts.isConditionalExpression(node) && child !== node.condition) {
      if (!containsAssertion(child === node.whenTrue ? node.whenFalse : node.whenTrue)) return true;
    }
    if (ts.isCatchClause(node)) return true;
    if (ts.isBinaryExpression(node) && child === node.right) {
      const kind = node.operatorToken.kind;
      if (
        kind === ts.SyntaxKind.AmpersandAmpersandToken ||
        kind === ts.SyntaxKind.BarBarToken ||
        kind === ts.SyntaxKind.QuestionQuestionToken
      ) {
        return true;
      }
    }
  }
  return false;
}

function isGated(body: ts.Node): boolean {
  let gated = false;
  const visit = (node: ts.Node) => {
    if (ts.isContinueStatement(node) || ts.isBreakStatement(node) || ts.isReturnStatement(node)) gated = true;
    if (isAssertionCall(node) && gatedOnOneSide(node, body)) gated = true;
  };
  visit(body);
  forEachOwn(body, visit);
  return gated;
}

/** 真偽値を主張する matcher なら、主張した値（`.not`の前）。 */
function assertedTruth(matcher: string, argument: ts.Expression | undefined): boolean | undefined {
  if (matcher === "toBeTruthy") return true;
  if (matcher === "toBeFalsy") return false;
  if (!["toBe", "toEqual", "toStrictEqual"].includes(matcher) || !argument) return undefined;
  if (argument.kind === ts.SyntaxKind.TrueKeyword) return true;
  if (argument.kind === ts.SyntaxKind.FalseKeyword) return false;
  return undefined;
}

type ElementCheck = { iterable: ts.Expression; body?: ts.Node };

function elementCheck(node: ts.Node): ElementCheck | undefined {
  if ((ts.isForOfStatement(node) || ts.isForInStatement(node)) && containsAssertion(node.statement)) {
    return { iterable: node.expression, body: node.statement };
  }
  if (
    ts.isCallExpression(node) &&
    ts.isPropertyAccessExpression(node.expression) &&
    node.expression.name.text === "forEach"
  ) {
    const callback = node.arguments[0];
    if (
      callback &&
      (ts.isArrowFunction(callback) || ts.isFunctionExpression(callback)) &&
      containsAssertion(callback.body)
    ) {
      return { iterable: node.expression.expression, body: callback.body };
    }
  }
  const call = matcherCall(node);
  if (!call || !ts.isCallExpression(call.subject) || !ts.isPropertyAccessExpression(call.subject.expression))
    return undefined;
  const quantifier = call.subject.expression.name.text;
  const truthy = assertedTruth(call.matcher, call.argument);
  if ((quantifier !== "every" && quantifier !== "some") || truthy === undefined) return undefined;
  // 空の配列では every が真・some が偽になるので、その向きを主張していれば空で素通りする
  if ((quantifier === "every") === (truthy !== call.negated)) {
    return { iterable: call.subject.expression.expression };
  }
  return undefined;
}

function findVacuousLoops(file: string, text: string): Finding[] {
  const source = ts.createSourceFile(
    file,
    text,
    ts.ScriptTarget.Latest,
    true,
    file.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
  );
  const findings: Finding[] = [];
  const report = (node: ts.Node, reason: string) =>
    findings.push({ file, line: source.getLineAndCharacterOfPosition(node.getStart()).line + 1, reason });
  const visit = (node: ts.Node) => {
    const check = elementCheck(node);
    if (check) {
      if (strip(check.iterable).filtered) report(node, FILTERED_HERE);
      else {
        const names = filteredNames(check.iterable, node);
        if (names && !hasNonEmptyAssertion(enclosingFunction(node), names)) report(node, NOT_ASSERTED);
      }
      if (check.body && isGated(check.body)) report(node, GATED);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return findings;
}

function findInTree(root: string): { files: string[]; findings: Finding[] } {
  const files = walkTree(root)
    .map(({ path }) => path)
    .filter((path) => /\.test\.tsx?$/.test(path));
  return { files, findings: files.flatMap((file) => findVacuousLoops(file, readFileSync(join(root, file), "utf8"))) };
}

/** 本文を1つのテストに包み、見つかった理由だけを返す。 */
const reasons = (body: string) =>
  findVacuousLoops("case.test.ts", `it("t", () => {\n${body}\n});`).map((f) => f.reason);

describe("要素ごとの確かめが空の母集団で素通りしない", () => {
  it("frontend/srcのテストに違反が無い", () => {
    const { files, findings } = findInTree(SRC_ROOT);
    expect(files).toContain("structure/vacuousLoops.test.ts");
    expect(findings).toEqual([]);
  });

  describe("その場の絞り込み", () => {
    it("for...of・forEach・量化の反復対象が.filterを経ていれば落とす", () => {
      expect(reasons(`for (const x of xs.filter(f)) expect(x).toBe(1);`)).toEqual([FILTERED_HERE]);
      expect(reasons(`Object.entries(xs.filter(f)).forEach(([k]) => { expect(k).toBe(1); });`)).toEqual([
        FILTERED_HERE,
      ]);
      expect(reasons(`expect(xs.filter(f).map(g).every(h)).toBe(true);`)).toEqual([FILTERED_HERE]);
      expect(reasons(`expect(xs.filter(f).some(h)).not.toBeTruthy();`)).toEqual([FILTERED_HERE]);
    });

    it("空でも偽にならない量化と、確かめの無いループは見ない", () => {
      expect(reasons(`expect(xs.filter(f).every(h)).toBe(false);`)).toEqual([]);
      expect(reasons(`expect(xs.filter(f).some(h)).toBe(true);`)).toEqual([]);
      expect(reasons(`for (const x of xs.filter(f)) total += x;`)).toEqual([]);
    });
  });

  describe("本体の条件", () => {
    it("片側にだけ確かめのある分岐と、要素を飛ばす文を落とす", () => {
      expect(reasons(`for (const x of xs) { if (x.a) expect(x).toBe(1); }`)).toEqual([GATED]);
      expect(reasons(`for (const x of xs) { if (x.a) {} else { expect(x).toBe(1); } }`)).toEqual([GATED]);
      expect(reasons(`for (const x of xs) { x.a && expect(x).toBe(1); }`)).toEqual([GATED]);
      expect(reasons(`for (const x of xs) { x.a ? expect(x).toBe(1) : null; }`)).toEqual([GATED]);
      expect(reasons(`for (const x of xs) { try { run(x); } catch { expect(x).toBe(1); } }`)).toEqual([GATED]);
      expect(reasons(`for (const x of xs) { if (!x.a) continue; expect(x).toBe(1); }`)).toEqual([GATED]);
      expect(reasons(`for (const x of xs) { if (!x.a) break; expect(x).toBe(1); }`)).toEqual([GATED]);
      expect(reasons(`for (const x of xs) { if (!x.a) return; expect(x).toBe(1); }`)).toEqual([GATED]);
      expect(reasons(`xs.forEach((x) => { if (!x.a) return; expect(x).toBe(1); });`)).toEqual([GATED]);
    });

    it("両側に確かめがある分岐・条件の中の確かめ・入れ子のループの中の分岐は、外のループの違反にしない", () => {
      expect(reasons(`for (const x of xs) { if (x.a) expect(x).toBe(1); else expect(x).toBe(2); }`)).toEqual([]);
      expect(reasons(`for (const x of xs) { if (expect(x).toBe(1)) {} }`)).toEqual([]);
      expect(reasons(`for (const x of xs) { expect(x).toBe(1); ys.forEach((y) => { if (y) return; }); }`)).toEqual([]);
      expect(reasons(`for (const x of xs) { for (const y of x.ys) { if (y) expect(y).toBe(1); } }`)).toEqual([GATED]);
    });
  });

  describe("名前で束ねた絞り込み", () => {
    it("同じ関数に空でないことの主張が無ければ落とす", () => {
      expect(reasons(`const ys = xs.filter(f);\nfor (const y of ys) expect(y).toBe(1);`)).toEqual([NOT_ASSERTED]);
      expect(reasons(`const ys = () => xs.filter(f);\nys().forEach((y) => { expect(y).toBe(1); });`)).toEqual([
        NOT_ASSERTED,
      ]);
      expect(reasons(`function ys() { return xs.filter(f); }\nexpect(ys().every(g)).toBe(true);`)).toEqual([
        NOT_ASSERTED,
      ]);
      expect(
        reasons(
          `const ys = xs.filter(f);\nconst zs = ys.map(g);\nfor (const z of Object.values(zs)) expect(z).toBe(1);`,
        ),
      ).toEqual([NOT_ASSERTED]);
    });

    it("外側のスコープの宣言へ辿り、主張は同じテストの中にだけ探す", () => {
      const source = [
        `const ys = xs.filter(f);`,
        `it("a", () => { expect(ys.length).toBeGreaterThan(0); });`,
        `it("b", () => { for (const y of ys) expect(y).toBe(1); });`,
      ].join("\n");
      expect(findVacuousLoops("case.test.ts", source)).toEqual([
        { file: "case.test.ts", line: 3, reason: NOT_ASSERTED },
      ]);
    });

    it("読める形の主張があれば通す", () => {
      const loop = `for (const z of zs) expect(z).toBe(1);`;
      const declared = `const ys = xs.filter(f);\nconst zs = ys.map(g);`;
      for (const assertion of [
        `expect(ys).toHaveLength(2);`,
        `expect(zs).not.toHaveLength(0);`,
        `expect(ys.length).toBeGreaterThan(0);`,
        `expect(zs.length).toBeGreaterThanOrEqual(1);`,
        `expect(ys.length).toBe(3);`,
        `expect(ys.length).not.toBe(0);`,
      ]) {
        expect(reasons(`${declared}\n${assertion}\n${loop}`)).toEqual([]);
      }
    });

    it("空でないことにならない主張・絞り込みの無い名前・関数の引数は、違反の有無を変えない", () => {
      const declared = `const ys = xs.filter(f);`;
      const loop = `for (const y of ys) expect(y).toBe(1);`;
      for (const assertion of [
        `expect(ys).toHaveLength(0);`,
        `expect(ys.length).toBeGreaterThanOrEqual(0);`,
        `expect(ys).toEqual([1]);`,
      ]) {
        expect(reasons(`${declared}\n${assertion}\n${loop}`)).toEqual([NOT_ASSERTED]);
      }
      expect(reasons(`const ys = xs.map(f);\nfor (const y of ys) expect(y).toBe(1);`)).toEqual([]);
      expect(findVacuousLoops("case.test.ts", `function check(ys) { for (const y of ys) expect(y).toBe(1); }`)).toEqual(
        [],
      );
    });
  });
});
