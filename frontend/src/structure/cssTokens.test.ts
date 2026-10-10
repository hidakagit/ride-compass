// @vitest-environment node
/**
 * `frontend/src`のCSSカスタムプロパティの参照が、どれも定義を持つかを見る。
 *
 * 定義が無い参照は継承値へ落ちる（SVGの`fill`なら黒に固定され、ダークモードで読めなくなる）。
 * フォールバック付きの参照も対象にする——値は壊れないが、綴り違いが隠れたまま同じ役割の色が
 * 複数の実効値を持つ。
 *
 * 参照: `.css`の`var(--x`・`theme(--x`（コメントの中は除く）と、`.ts`・`.tsx`の文字列（JSXの属性・
 * テンプレートを含む）の中の同じ形。
 * 参照が定義を持つとは、次のどれかに名前があること（設計の正本は
 * docs/modules/frontend/frontend-design-system.md「存在しないトークン名を書かない」）:
 * - `app/globals.css`の宣言`--x:`と`@property --x`
 * - 参照と同じ`.css`ファイルの、同じ形の宣言（ほかの`.css`ファイルの宣言は数えない）
 * - `.ts`・`.tsx`で、名前だけを引用符で囲んだ文字列`"--x"`（styleのキー・`setProperty`へ渡す名前等、
 *   実行時に要素へ置く名前）
 * - `package.json`の`dependencies`の各パッケージの入口のファイルに、名前だけを引用符で囲んで
 *   書かれたもの（UIライブラリが自分の要素へ実行時に置く名前）。Tailwindの既定のテーマは
 *   `devDependencies`なので数えない。使うなら`globals.css`の`@theme`へ定義する
 *
 * 見ないもの: 名前を式で組み立てた参照（テンプレートの`${}`を名前の途中に挟む）。
 * `getPropertyValue("--x")`のような名前だけの文字列での読み取り（定義と見分けられない）。
 * 定義が要素の木の中で参照に届くか（どのセレクタ・どの要素に置いたか）。
 * Stylelintの未定義の参照を落とすプラグインは`.css`しか読まず、`.tsx`の任意値の参照を見ないので
 * 代わりにならない。この検査の本文は、参照の形の文字列を書かずに組み立てる（自分も走査されるため）。
 */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import ts from "typescript";
import { afterEach, describe, expect, it } from "vitest";

import { removeTree, SRC_ROOT, walkTree, writeTree } from "./sourceTree";

const NAME = "--[\\w-]+";
const REFERENCE = new RegExp(`\\b(?:var|theme)\\(\\s*(${NAME})`, "g");
const CSS_DEFINITION = new RegExp(`(?:@property\\s+(${NAME}))|(${NAME})\\s*:`, "g");
const QUOTED_NAME = new RegExp(`["'\`](${NAME})["'\`]`, "g");
const BARE_NAME = new RegExp(`^${NAME}$`);

type Reference = { file: string; token: string };
type Scan = { global: Set<string>; local: Map<string, Set<string>>; references: Reference[] };

const GLOBAL_STYLESHEET = "app/globals.css";

function stringTexts(fileName: string, text: string): string[] {
  const source = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true);
  const texts: string[] = [];
  const visit = (node: ts.Node) => {
    if (
      ts.isStringLiteral(node) ||
      ts.isNoSubstitutionTemplateLiteral(node) ||
      ts.isTemplateHead(node) ||
      ts.isTemplateMiddle(node) ||
      ts.isTemplateTail(node)
    ) {
      texts.push(node.text);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return texts;
}

function scanTokens(root: string): Scan {
  const global = new Set<string>();
  const local = new Map<string, Set<string>>();
  const references: Reference[] = [];
  for (const { path, isDirectory } of walkTree(root)) {
    if (isDirectory) continue;
    const text = readFileSync(join(root, path), "utf8");
    let texts: string[];
    if (path.endsWith(".css")) {
      texts = [text.replace(/\/\*[\s\S]*?\*\//g, "")];
      const declared = new Set([...texts[0].matchAll(CSS_DEFINITION)].map((m) => m[1] ?? m[2]));
      local.set(path, declared);
      if (path === GLOBAL_STYLESHEET) declared.forEach((name) => global.add(name));
    } else if (/\.(ts|tsx|mts)$/.test(path)) {
      // 参照も名前だけの定義も「--」を含むので、含まないファイルは構文木を作らずに飛ばす（作るのが所要の大半を占める）。
      texts = text.includes("--") ? stringTexts(path, text) : [];
      for (const t of texts) if (BARE_NAME.test(t)) global.add(t);
    } else {
      continue;
    }
    for (const t of texts) for (const m of t.matchAll(REFERENCE)) references.push({ file: path, token: m[1] });
  }
  if (!local.has(GLOBAL_STYLESHEET)) throw new Error(`${GLOBAL_STYLESHEET}が無い`);
  return { global, local, references };
}

/** `exports`の`"."`から、読み込みに使われる入口を取る（`require`の解決が断るESM専用のパッケージ向け）。 */
function exportedEntry(packageJson: string): string | undefined {
  const dot = JSON.parse(readFileSync(packageJson, "utf8")).exports?.["."];
  const entry = typeof dot === "string" ? dot : (dot?.import ?? dot?.default);
  return typeof entry === "string" ? join(dirname(packageJson), entry) : undefined;
}

function dependencyDefinitions(projectRoot: string): Set<string> {
  const packageJson = join(projectRoot, "package.json");
  const require = createRequire(packageJson);
  const definitions = new Set<string>();
  for (const name of Object.keys(JSON.parse(readFileSync(packageJson, "utf8")).dependencies ?? {})) {
    let entry: string | undefined;
    try {
      entry = require.resolve(name);
    } catch {
      entry = exportedEntry(join(projectRoot, "node_modules", name, "package.json"));
    }
    if (!entry) throw new Error(`${name}の入口が見つからない`);
    for (const m of readFileSync(entry, "utf8").matchAll(QUOTED_NAME)) definitions.add(m[1]);
  }
  return definitions;
}

function undefinedReferences({ global, local, references }: Scan, projectRoot: string): Reference[] {
  const fromDependencies = dependencyDefinitions(projectRoot);
  return references.filter(
    ({ file, token }) => !global.has(token) && !local.get(file)?.has(token) && !fromDependencies.has(token),
  );
}

const ref = (name: string, fallback?: string) => `var(${"-"}-${name}${fallback ? `, ${fallback}` : ""})`;
const themeRef = (name: string) => `theme(${"-"}-${name})`;

describe("CSSカスタムプロパティの参照", () => {
  it("frontend/srcのものはどれも定義を持つ", () => {
    const projectRoot = join(SRC_ROOT, "..");
    const scan = scanTokens(SRC_ROOT);
    expect(scan.references.length).toBeGreaterThan(0);
    expect(undefinedReferences(scan, projectRoot)).toEqual([]);
  });

  describe("わざと作った木で", () => {
    let root = "";
    afterEach(() => removeTree(root));

    const project = (files: Record<string, string>) =>
      writeTree({ "package.json": "{}", "src/app/globals.css": "", ...files });

    it("定義の無い参照を、フォールバック付き・theme()も含めて出す", () => {
      root = project({
        "src/a.css": `:root { --color-a: red; }\n.x { color: ${ref("color-a")}; fill: ${ref("color-b", "red")}; }\n@media (max-width: ${themeRef("bp")}) {}`,
      });
      expect(undefinedReferences(scanTokens(join(root, "src")), root)).toEqual([
        { file: "a.css", token: "--color-b" },
        { file: "a.css", token: "--bp" },
      ]);
    });

    it("globals.cssと同じファイルの宣言だけを数え、ほかのCSSファイルの宣言は数えない", () => {
      root = project({
        "src/app/globals.css": `@theme { --color-g: red; }`,
        "src/b.css": `.b { --b-only: 1px; width: ${ref("b-only")}; }`,
        "src/c.css": `.c { color: ${ref("color-g")}; width: ${ref("b-only")}; }`,
      });
      expect(undefinedReferences(scanTokens(join(root, "src")), root)).toEqual([{ file: "c.css", token: "--b-only" }]);
    });

    it("tsxの属性・テンプレート・styleのキーを読み、コメントは読まない", () => {
      root = project({
        "src/a.tsx": [
          `// ${ref("in-comment")}`,
          `const n = 1;`,
          `export const A = () => <div style={{ "--tint": "1" }} className="bg-[${ref("tint")}] text-[${ref("typo")}]" />;`,
          `export const b = \`w-[\${n}px] h-[${ref("tmpl")}]\`;`,
        ].join("\n"),
        "src/app/globals.css": `/* ${ref("css-comment")} */ @property --tmpl { syntax: "*"; inherits: false; }`,
      });
      expect(undefinedReferences(scanTokens(join(root, "src")), root)).toEqual([{ file: "a.tsx", token: "--typo" }]);
    });

    it("dependenciesのパッケージが入口で置く名前を定義に数え、devDependenciesのものは数えない", () => {
      root = project({
        "package.json": JSON.stringify({
          dependencies: { "cjs-lib": "1", "esm-lib": "1" },
          devDependencies: { "dev-lib": "1" },
        }),
        "node_modules/cjs-lib/package.json": JSON.stringify({ main: "index.js" }),
        "node_modules/cjs-lib/index.js": `el.style.setProperty("--cjs-size", "1px");`,
        "node_modules/esm-lib/package.json": JSON.stringify({ exports: { ".": { import: "./index.mjs" } } }),
        "node_modules/esm-lib/index.mjs": `const style = { "--esm-size": "1px" };`,
        "node_modules/dev-lib/package.json": JSON.stringify({ main: "index.js" }),
        "node_modules/dev-lib/index.js": `el.style.setProperty("--dev-size", "1px");`,
        "src/a.css": `.x { width: ${ref("cjs-size")}; height: ${ref("esm-size")}; top: ${ref("dev-size")}; }`,
      });
      expect(undefinedReferences(scanTokens(join(root, "src")), root)).toEqual([
        { file: "a.css", token: "--dev-size" },
      ]);
    });
  });
});
