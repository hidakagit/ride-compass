// @vitest-environment node
/**
 * テストが共有の足場（`src/testing`の組み立て関数・代役・待ちの道具）と同じ役のものを自分のファイルに写さず、
 * 自前のモジュールを差し替えないことを見る（.claude/rules/testing-frontend.md「確かめる高さ（frontend）」の
 * 「差し替えてよいのは次の境界だけ」・testing-scaffold.md「フェイクの数は、実装の外向き参照の写し」の「共有フェイクへ出すのは3箇所目から」。
 * backend の同じ検査は`backend/tests/structure/test_scaffold_copies.py`）。
 *
 * 母集団は`frontend/src`（この検査のディレクトリを除く）と`frontend/e2e`の全`.ts(x)`で、TypeScriptの構文木で読む。
 * `src/testing`の`*.test.ts(x)`でないファイルを共有の足場、`*.test.ts(x)`と`e2e`のファイルをテストとして読む
 * （`e2e`の`*.spec.ts`でないファイルは e2e の足場だが、`src/testing`を迂回すれば違反に数える）。違反は次の4つ:
 *
 * 1. 最上位の定義の写し: テストと足場の最上位の関数・`const`で、名前を除いた本体が同じものが3つ以上のファイルにある。
 *    値（関数でない`const`）は、葉（名前・リテラル）が5つ以上のものだけ。2つまでは落とさない（3箇所目から足場へ出す決まり）。
 * 2. 組み立て関数の迂回: `src/testing`の公開関数のうち、既定値を埋めて上書きを受ける組み立て関数（返すオブジェクト
 *    リテラルが上書きの展開を持つもの）について、そのリテラルが持つ項目（展開を除く）を全部持つオブジェクトリテラルを、
 *    `src/testing`の外のテストに書く。
 * 3. 足場の代役の迂回: 足場が代役を持つ外部のモジュール（`vi.mock(<名前>, () => import("@/testing/…"))`の形で
 *    差し替えられるもの）を、別の中身で`vi.mock`するか、足場が代役として出す名前の型（`Map`等）へ値を`as`で当てる。
 * 4. 自前のモジュールの差し替え: `@/`か相対のパスで指す`src`のモジュールを`vi.mock`する。差し替えてよい境界のうち、
 *    環境変数の読み取り口（`process.env`を読むモジュール）とファイルを落とす関数（`URL.createObjectURL`を呼ぶ
 *    モジュール）は除く。子の部品の差し替え（差し替えの中身が部品の名前（大文字で始まり、全部が大文字でない名前）
 *    だけを置き換えるもの）も除く——testing-frontend.md は条件（子の中身がテスト環境に無い境界を要し、境界の側で差し替え
 *    られない）を満たす子の差し替えを許し、その条件は構文木から決まらない。
 *
 * **判定しない形**: 関数の中の定義。組み立て関数の項目の一部だけを持つリテラル（関心のある項目だけを書いた入力）と、
 * 上書きを受けない部品の関数（`routeThrough`等、型の一部を組むもの）。代役の無い型（`FilterSpecification`等の値の型）への`as`。
 * 葉が5つ未満の値。`e2e-live`・`capture`（別のランナーの道具で、`src/testing`の足場を使わない）。
 */
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

import { SRC_ROOT, removeTree, walkTree, writeTree } from "./sourceTree";

const MIN_VALUE_LEAVES = 5;
const MIN_COPIES = 3;

type Source = { path: string; file: ts.SourceFile };
type Finding = { file: string; line: number; reason: string };

const isTest = (path: string) => /\.test\.tsx?$/.test(path) || path.startsWith("e2e/");
const isScaffold = (path: string) => path.startsWith("src/testing/") && !/\.test\.tsx?$/.test(path);

function readSources(root: string): Source[] {
  const paths = ["src", "e2e"].flatMap((top) =>
    existsSync(join(root, top))
      ? walkTree(join(root, top))
          .filter(({ path, isDirectory }) => !isDirectory && /\.tsx?$/.test(path) && !path.startsWith("structure/"))
          .map(({ path }) => `${top}/${path}`)
      : [],
  );
  return paths.map((path) => ({
    path,
    file: ts.createSourceFile(
      path,
      readFileSync(join(root, path), "utf8"),
      ts.ScriptTarget.Latest,
      true,
      path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS,
    ),
  }));
}

const printer = ts.createPrinter({ removeComments: true });
const lineOf = (file: ts.SourceFile, node: ts.Node) => file.getLineAndCharacterOfPosition(node.getStart()).line + 1;

function leaves(node: ts.Node): number {
  let count = ts.isIdentifier(node) || ts.isLiteralExpression(node) || ts.isTemplateLiteralToken(node) ? 1 : 0;
  ts.forEachChild(node, (child) => {
    count += leaves(child);
  });
  return count;
}

function unwrap(node: ts.Expression): ts.Expression {
  let current = node;
  while (ts.isParenthesizedExpression(current) || ts.isAsExpression(current) || ts.isSatisfiesExpression(current)) {
    current = current.expression;
  }
  return current;
}

/** 最上位の定義の (名前, 行, 本体の形)。 */
function definitions({ file }: Source): { name: string; line: number; shape: string }[] {
  const out: { name: string; line: number; shape: string }[] = [];
  for (const statement of file.statements) {
    if (ts.isFunctionDeclaration(statement) && statement.name && statement.body) {
      const shape = [...statement.parameters, statement.type, statement.body]
        .map((node) => (node ? printer.printNode(ts.EmitHint.Unspecified, node, file) : ""))
        .join("|");
      out.push({ name: statement.name.text, line: lineOf(file, statement), shape });
    } else if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        if (!ts.isIdentifier(declaration.name) || !declaration.initializer) continue;
        const value = unwrap(declaration.initializer);
        const isFunction = ts.isArrowFunction(value) || ts.isFunctionExpression(value);
        if (!isFunction && leaves(value) < MIN_VALUE_LEAVES) continue;
        out.push({
          name: declaration.name.text,
          line: lineOf(file, declaration),
          shape: printer.printNode(ts.EmitHint.Expression, declaration.initializer, file),
        });
      }
    }
  }
  return out;
}

function copiedDefinitions(sources: Source[]): Finding[] {
  const places = new Map<string, Map<string, Finding>>();
  for (const source of sources.filter(({ path }) => isTest(path) || isScaffold(path))) {
    for (const { name, line, shape } of definitions(source)) {
      const files = places.get(shape) ?? new Map<string, Finding>();
      if (!files.has(source.path)) files.set(source.path, { file: source.path, line, reason: name });
      places.set(shape, files);
    }
  }
  return [...places.values()]
    .filter((files) => files.size >= MIN_COPIES)
    .flatMap((files) =>
      [...files.values()].map((found) => ({ ...found, reason: `${found.reason}（${files.size}ファイル）` })),
    );
}

function propertyNames(literal: ts.ObjectLiteralExpression): string[] {
  return literal.properties.flatMap((property) =>
    (ts.isPropertyAssignment(property) ||
      ts.isShorthandPropertyAssignment(property) ||
      ts.isMethodDeclaration(property)) &&
    (ts.isIdentifier(property.name) || ts.isStringLiteral(property.name))
      ? [property.name.text]
      : [],
  );
}

/** `src/testing`の公開の組み立て関数（返すリテラルが展開を持つもの）の名前と、返すリテラルの項目。 */
function builders(sources: Source[]): { name: string; keys: string[] }[] {
  return sources
    .filter(({ path }) => isScaffold(path))
    .flatMap(({ file }) =>
      file.statements.flatMap((statement) => {
        if (!ts.isFunctionDeclaration(statement) || !statement.name || !statement.body) return [];
        if (!statement.modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword)) return [];
        const returned = statement.body.statements.find(ts.isReturnStatement)?.expression;
        const literal = returned && unwrap(returned);
        return literal && ts.isObjectLiteralExpression(literal) && literal.properties.some(ts.isSpreadAssignment)
          ? [{ name: statement.name.text, keys: propertyNames(literal) }]
          : [];
      }),
    );
}

function bypassedBuilders(sources: Source[]): Finding[] {
  const known = builders(sources).filter(({ keys }) => keys.length > 0);
  const findings: Finding[] = [];
  for (const { path, file } of sources.filter(({ path }) => isTest(path) && !path.startsWith("src/testing/"))) {
    const visit = (node: ts.Node) => {
      if (ts.isObjectLiteralExpression(node)) {
        const names = new Set(propertyNames(node));
        for (const { name, keys } of known) {
          if (keys.every((key) => names.has(key)))
            findings.push({ file: path, line: lineOf(file, node), reason: name });
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(file);
  }
  return findings;
}

function viMocks(file: ts.SourceFile): { specifier: string; factory: ts.Expression | undefined; node: ts.Node }[] {
  const out: { specifier: string; factory: ts.Expression | undefined; node: ts.Node }[] = [];
  const visit = (node: ts.Node) => {
    if (
      ts.isCallExpression(node) &&
      ts.isPropertyAccessExpression(node.expression) &&
      ts.isIdentifier(node.expression.expression) &&
      node.expression.expression.text === "vi" &&
      node.expression.name.text === "mock" &&
      node.arguments[0] &&
      ts.isStringLiteral(node.arguments[0])
    ) {
      out.push({ specifier: node.arguments[0].text, factory: node.arguments[1], node });
    }
    ts.forEachChild(node, visit);
  };
  visit(file);
  return out;
}

/** 差し替えの中身が返すオブジェクトが、部品の名前（`MapView`等。`MAX_ZOOM`等の定数でない大文字始まり）だけを置き換えるか。 */
function replacesOnlyComponents(factory: ts.Expression | undefined): boolean {
  if (!factory || !(ts.isArrowFunction(factory) || ts.isFunctionExpression(factory))) return false;
  let body: ts.Node = factory.body;
  if (ts.isBlock(body)) {
    const last = body.statements.at(-1);
    if (!last || !ts.isReturnStatement(last) || !last.expression) return false;
    body = last.expression;
  }
  while (ts.isParenthesizedExpression(body)) body = body.expression;
  if (!ts.isObjectLiteralExpression(body)) return false;
  const names = body.properties.flatMap((property) =>
    ts.isSpreadAssignment(property) ? [] : [property.name && ts.isIdentifier(property.name) ? property.name.text : ""],
  );
  return names.length > 0 && names.every((name) => /^[A-Z]/.test(name) && name !== name.toUpperCase());
}

/** `() => import("@/testing/…")`の形の差し替えなら、読む足場のパス（`src/testing/…`）。 */
function scaffoldImported(factory: ts.Expression | undefined): string | undefined {
  if (!factory || !ts.isArrowFunction(factory) || !ts.isExpression(factory.body)) return undefined;
  const body = unwrap(factory.body);
  return ts.isCallExpression(body) &&
    body.expression.kind === ts.SyntaxKind.ImportKeyword &&
    ts.isStringLiteral(body.arguments[0]) &&
    body.arguments[0].text.startsWith("@/testing/")
    ? `src/${body.arguments[0].text.slice(2)}`
    : undefined;
}

/** ファイルが`export`する名前（`export { A as B }`は`B`）。 */
function exportedNames(file: ts.SourceFile): string[] {
  return file.statements.flatMap((statement) => {
    if (ts.isExportDeclaration(statement) && statement.exportClause && ts.isNamedExports(statement.exportClause)) {
      return statement.exportClause.elements.map((element) => element.name.text);
    }
    const named = statement as ts.Node & { name?: ts.Node };
    return ts.canHaveModifiers(statement) &&
      ts.getModifiers(statement)?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword) &&
      named.name &&
      ts.isIdentifier(named.name)
      ? [named.name.text]
      : [];
  });
}

function bypassedStandIns(sources: Source[]): Finding[] {
  const byPath = new Map(sources.map((source) => [source.path, source.file]));
  const standIns = new Map<string, Set<string>>();
  for (const { file } of sources) {
    for (const { specifier, factory } of viMocks(file)) {
      const scaffold = byPath.get(`${scaffoldImported(factory)}.ts`);
      if (scaffold) standIns.set(specifier, new Set(exportedNames(scaffold)));
    }
  }
  const findings: Finding[] = [];
  for (const { path, file } of sources.filter(({ path }) => isTest(path) && !path.startsWith("src/testing/"))) {
    for (const { specifier, factory, node } of viMocks(file)) {
      if (standIns.has(specifier) && !scaffoldImported(factory)) {
        findings.push({ file: path, line: lineOf(file, node), reason: `vi.mock("${specifier}")` });
      }
    }
    const standInTypes = new Set(
      file.statements.flatMap((statement) =>
        ts.isImportDeclaration(statement) &&
        ts.isStringLiteral(statement.moduleSpecifier) &&
        standIns.has(statement.moduleSpecifier.text) &&
        statement.importClause?.namedBindings &&
        ts.isNamedImports(statement.importClause.namedBindings)
          ? statement.importClause.namedBindings.elements
              .filter((element) =>
                standIns
                  .get((statement.moduleSpecifier as ts.StringLiteral).text)!
                  .has((element.propertyName ?? element.name).text),
              )
              .map((element) => element.name.text)
          : [],
      ),
    );
    const visit = (node: ts.Node) => {
      if (
        ts.isAsExpression(node) &&
        ts.isTypeReferenceNode(node.type) &&
        ts.isIdentifier(node.type.typeName) &&
        standInTypes.has(node.type.typeName.text)
      ) {
        findings.push({ file: path, line: lineOf(file, node), reason: `as ${node.type.typeName.text}` });
      }
      ts.forEachChild(node, visit);
    };
    visit(file);
  }
  return findings;
}

/** `from`（`src/…`のファイル）から`specifier`で指す`src`のモジュールのパス。`src`の外・パッケージは undefined。 */
function resolveOwn(from: string, specifier: string, paths: Set<string>): string | undefined {
  let base: string;
  if (specifier.startsWith("@/")) base = `src/${specifier.slice(2)}`;
  else if (specifier.startsWith(".")) {
    const parts = from.split("/").slice(0, -1);
    for (const part of specifier.split("/")) {
      if (part === "..") parts.pop();
      else if (part !== ".") parts.push(part);
    }
    base = parts.join("/");
  } else return undefined;
  return [`${base}.ts`, `${base}.tsx`, `${base}/index.ts`, `${base}/index.tsx`].find((path) => paths.has(path));
}

function ownModuleMocks(sources: Source[]): Finding[] {
  const byPath = new Map(sources.map((source) => [source.path, source]));
  const paths = new Set(byPath.keys());
  const isBoundary = (path: string) => /process\.env\b|URL\.createObjectURL\b/.test(byPath.get(path)!.file.text);
  return sources
    .filter(({ path }) => isTest(path))
    .flatMap(({ path, file }) =>
      viMocks(file).flatMap(({ specifier, factory, node }) => {
        const target = resolveOwn(path, specifier, paths);
        return target && !isBoundary(target) && !replacesOnlyComponents(factory)
          ? [{ file: path, line: lineOf(file, node), reason: specifier }]
          : [];
      }),
    );
}

function scaffoldViolations(root: string) {
  const sources = readSources(root);
  return {
    copies: copiedDefinitions(sources),
    builders: bypassedBuilders(sources),
    standIns: bypassedStandIns(sources),
    ownMocks: ownModuleMocks(sources),
  };
}

const lines = (findings: Finding[]) => findings.map(({ file, line, reason }) => `${file}:${line}: ${reason}`).sort();

describe("共有の足場の写し", () => {
  const found = scaffoldViolations(join(SRC_ROOT, ".."));

  it("同じ本体の最上位の定義が3つ以上のファイルに無い（共有の足場`src/testing`へ1つにまとめる）", () => {
    expect(lines(found.copies)).toEqual([]);
  });

  it("`src/testing`の組み立て関数が返す項目を全部、外のテストで手書きしない（組み立て関数へ変えたい項目だけを渡す）", () => {
    expect(lines(found.builders)).toEqual([]);
  });

  it("足場が代役を持つ外部のモジュールを、別の中身で差し替えたり、その型へ自前の値を当てたりしない", () => {
    expect(lines(found.standIns)).toEqual([]);
  });

  it("自前のモジュールを差し替えない（境界の表の読み取り口・ファイルを落とす関数・子の部品を除く）", () => {
    expect(lines(found.ownMocks)).toEqual([]);
  });
});

describe("検査が効いていること", () => {
  const within = (files: Record<string, string>) => {
    const root = writeTree(files);
    try {
      const sources = readSources(root);
      return {
        copies: lines(copiedDefinitions(sources)),
        builders: lines(bypassedBuilders(sources)),
        standIns: lines(bypassedStandIns(sources)),
        ownMocks: lines(ownModuleMocks(sources)),
      };
    } finally {
      removeTree(root);
    }
  };

  it("名前の違う同じ関数・葉が5つ以上の同じ値を3ファイルで落とし、2ファイルの写しと葉が5つ未満の値は落とさない", () => {
    const helper = (name: string) => `const ${name} = (text: string) => new Date(\`\${text}+09:00\`);\n`;
    const table = `const TABLE = { a: 1, b: 2, c: 3 };\nconst SMALL = { a: 1 };\nfunction twice(x: number) { return x * 2; }\n`;
    expect(
      within({
        "src/a.test.ts": helper("jst") + table,
        "src/b.test.ts": helper("at") + table,
        "e2e/c.ts": helper("jst") + "const TABLE = { a: 1, b: 2, c: 3 };\n",
      }),
    ).toMatchObject({
      copies: [
        "e2e/c.ts:1: jst（3ファイル）",
        "e2e/c.ts:2: TABLE（3ファイル）",
        "src/a.test.ts:1: jst（3ファイル）",
        "src/a.test.ts:2: TABLE（3ファイル）",
        "src/b.test.ts:1: at（3ファイル）",
        "src/b.test.ts:2: TABLE（3ファイル）",
      ],
    });
  });

  it("組み立て関数の項目を全部持つリテラルを落とし、一部だけのリテラル・上書きを受けない関数・`src/testing`の中は落とさない", () => {
    const builder = `export function makeSegment(o = {}) {\n  return { start: 0, end: 0, ...o };\n}\n`;
    const part = `export function shape() {\n  return { start: 0, end: 0 };\n}\n`;
    expect(
      within({
        "src/testing/segments.ts": builder + part + `export const SEGMENT = { start: 1, end: 2 };\n`,
        "src/a.test.ts": `const full = { start: 1, end: 2, extra: 3 };\nconst part = { start: 1 };\n`,
        "e2e/fixtures.ts": `export const segment = () => ({ start, end });\n`,
      }),
    ).toMatchObject({ builders: ["e2e/fixtures.ts:1: makeSegment", "src/a.test.ts:1: makeSegment"] });
  });

  it("足場が代役を持つモジュールを別の中身で差し替える形と代役の型へ当てる形を落とし、足場を読む差し替えと値の型は落とさない", () => {
    expect(
      within({
        "src/testing/lib.ts": `class StandIn {}\nexport { StandIn as Map };\nexport function addProtocol() {}\n`,
        "src/a.test.ts": `vi.mock("maplibre-gl", () => import("@/testing/lib"));\n`,
        "src/b.test.ts": [
          `import type { Map as LibreMap, FilterSpecification } from "maplibre-gl";`,
          `vi.mock("maplibre-gl", () => ({ addProtocol }));`,
          `const map = {} as unknown as LibreMap;`,
          `const filter = [] as FilterSpecification;`,
        ].join("\n"),
      }),
    ).toMatchObject({ standIns: ['src/b.test.ts:2: vi.mock("maplibre-gl")', "src/b.test.ts:3: as LibreMap"] });
  });

  it("自前のモジュールの差し替えを@/と相対のパスで落とし、環境変数の読み取り口・ファイルを落とす関数・子の部品・パッケージは落とさない", () => {
    expect(
      within({
        "src/hooks/useValue.ts": `export const useValue = () => 1;\n`,
        "src/lib/env.ts": `export const base = () => process.env.BASE;\n`,
        "src/lib/save.ts": `export const save = (blob: Blob) => URL.createObjectURL(blob);\n`,
        "src/hooks/useValue.test.ts": [
          `vi.mock("@/hooks/useValue");`,
          `vi.mock("./useValue");`,
          `vi.mock("@/lib/env");`,
          `vi.mock("../lib/save");`,
          `vi.mock("embla-carousel-react");`,
          `vi.mock("@/hooks/useValue", () => ({ ValueView: () => null }));`,
          `vi.mock("@/hooks/useValue", async () => ({ ...(await vi.importActual("@/hooks/useValue")), ValueView: () => null }));`,
          `vi.mock("@/hooks/useValue", () => ({ ValueView: () => null, useValue: () => 2 }));`,
          `vi.mock("@/hooks/useValue", () => ({ MAX_VALUE: 2 }));`,
        ].join("\n"),
      }),
    ).toMatchObject({
      ownMocks: [
        "src/hooks/useValue.test.ts:1: @/hooks/useValue",
        "src/hooks/useValue.test.ts:2: ./useValue",
        "src/hooks/useValue.test.ts:8: @/hooks/useValue",
        "src/hooks/useValue.test.ts:9: @/hooks/useValue",
      ],
    });
  });
});
