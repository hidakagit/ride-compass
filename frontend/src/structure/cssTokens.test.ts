// @vitest-environment node
/**
 * 定義の無いCSSカスタムプロパティ参照を見つける検査。
 *
 * 規約どおりの綴りに見えても、定義が無ければ継承値へ落ちる。SVGの`fill`だと継承値＝黒に
 * 固定され、ダークモードで文字が読めなくなる。フォールバックを伴う参照も対象にする
 * ——値としては壊れないが、未定義であること自体が隠れたまま綴り違いが残り、同じ役割の色が
 * 複数の実効値を持つ状態になる。
 *
 * この検査自身がトークン参照の文字列を本文へ書かないのは、走査対象に自分が入るため。
 *
 * 母集団はソースから導く（`frontend/src`配下の`.css`・`.ts`・`.tsx`全件）。
 */
import { mkdtempSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");
const GLOBAL_TOKENS = join(SRC, "app", "globals.css");
const SCANNED = [".css", ".ts", ".tsx"];
// UIライブラリが自分の要素へ実行時に設定するトークンの名前空間（定義はnode_modules側）。
// 名前空間で丸ごと許すため、自前の`--color-*`等の綴り違いはこれまでどおり見つかる。
const VENDOR_PREFIXES = ["--radix-"];

const TOKENS_CSS = `:root {
  --color-known: #fff;
}
`;

const REF = /var\(\s*(--[A-Za-z0-9_-]+)\s*[,)]/g;
const DEF = /^\s*(--[A-Za-z0-9_-]+)\s*:/gm;
// .ts/.tsxが実行時にstyleへ設定するトークン（トークンだけを引用符で囲んだ文字列）。
const RUNTIME_DEF = /["'](--[A-Za-z0-9_-]+)["']/g;

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return walk(full);
    return SCANNED.some((suffix) => name.endsWith(suffix)) ? [full] : [];
  });
}

function matches(text: string, re: RegExp): string[] {
  return [...text.matchAll(new RegExp(re.source, re.flags))].map((m) => m[1]);
}

export function undefinedCssTokens(root: string, globalTokens: string): string[] {
  const files = walk(root);
  const defined = new Set(matches(readFileSync(globalTokens, "utf8"), DEF));
  for (const file of files) {
    if (!file.endsWith(".ts") && !file.endsWith(".tsx")) continue;
    for (const token of matches(readFileSync(file, "utf8"), RUNTIME_DEF)) defined.add(token);
  }

  const out: string[] = [];
  for (const file of files) {
    if (file === globalTokens) continue;
    const text = readFileSync(file, "utf8");
    const local = new Set(matches(text, DEF));
    text.split("\n").forEach((line, index) => {
      for (const token of matches(line, REF)) {
        if (VENDOR_PREFIXES.some((prefix) => token.startsWith(prefix))) continue;
        if (defined.has(token) || local.has(token)) continue;
        out.push(`${relative(root, file).replaceAll("\\", "/")}:${index + 1}: ${token}`);
      }
    });
  }
  return out;
}

describe("CSSトークン", () => {
  it("参照しているトークンがすべて定義されている", () => {
    expect(undefinedCssTokens(SRC, GLOBAL_TOKENS)).toEqual([]);
  });

  it("未定義の参照を見つける（わざと1件置いて捕まえる）", () => {
    const dir = mkdtempSync(join(tmpdir(), "css-tokens-"));
    const tokens = join(dir, "globals.css");
    writeFileSync(tokens, TOKENS_CSS, "utf8");
    const ref = (name: string) => `.a { color: ${"var("}${name}); }`;
    writeFileSync(join(dir, "ok.css"), ref("--color-known"), "utf8");
    writeFileSync(join(dir, "ng.css"), ref("--color-typo"), "utf8");

    expect(undefinedCssTokens(dir, tokens)).toEqual(["ng.css:1: --color-typo"]);
  });
});
