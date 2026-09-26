// @vitest-environment node
/**
 * 大文字小文字だけが違うパス（モジュール名・ディレクトリ）を見つける検査。
 *
 * 大文字小文字を区別しないファイルシステム（開発機のWindows）では、`Foo.tsx`と`foo.ts`の
 * `./Foo`・`./foo`が同じファイルへ解決され、`tsc --noEmit`と`next build`が落ちる。区別する
 * ファイルシステム（CIのLinux）では別のファイルとして解決されて通るため、型検査もビルドも
 * これを見られない。
 *
 * 母集団はソースから導く（`frontend/src`配下の全ファイルと全ディレクトリ）。ファイルは
 * モジュールとして解決される名前（`.ts`・`.tsx`等の拡張子を外したもの）で比べる。
 */
import { readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");
const MODULE_EXTENSION = /(\.d\.ts|\.[cm]?[jt]sx?)$/;

/** `root`からの相対パス。ディレクトリは末尾に`/`を付ける。 */
function walk(root: string, dir = root): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    const path = relative(root, full).replaceAll("\\", "/");
    return statSync(full).isDirectory() ? [`${path}/`, ...walk(root, full)] : [path];
  });
}

export function caseOnlyPaths(paths: readonly string[]): string[][] {
  const spellings = new Map<string, Set<string>>();
  for (const path of paths) {
    const name = path.replace(MODULE_EXTENSION, "");
    const key = name.toLowerCase();
    spellings.set(key, (spellings.get(key) ?? new Set()).add(name));
  }
  return [...spellings.values()].filter((names) => names.size > 1).map((names) => [...names].sort());
}

describe("大文字小文字だけが違うパス", () => {
  it("frontend/src に無い", () => {
    const paths = walk(SRC);
    expect(paths).not.toHaveLength(0);
    expect(
      caseOnlyPaths(paths),
      "大文字小文字を区別しない開発機で同じものへ解決される。どちらかを別の名前にする",
    ).toEqual([]);
  });

  it("拡張子の違うモジュール名とディレクトリの衝突を捕まえ、同じ綴りは通す", () => {
    expect(
      caseOnlyPaths([
        "Profile/",
        "Profile/Profile.tsx",
        "Profile/profile.ts",
        "Profile/profile.module.css",
        "lib/",
        "lib/a.ts",
        "Lib/",
        "Lib/b.ts",
        "same.ts",
        "same.tsx",
        "same.d.ts",
      ]),
    ).toEqual([
      ["Profile/Profile", "Profile/profile"],
      ["Lib/", "lib/"],
    ]);
  });
});
