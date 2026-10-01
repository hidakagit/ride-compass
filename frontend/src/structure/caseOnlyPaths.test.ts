// @vitest-environment node
/**
 * `frontend/src`に、大文字小文字だけが違う2つの名前が並んでいないかを見る。
 *
 * 大文字小文字を区別しないファイルシステム（開発機のWindows）では、`Foo.tsx`と`foo.ts`の
 * `./Foo`・`./foo`が同じファイルへ解決され、ディレクトリ`Foo/`と`foo/`は1つに重なる。区別する
 * ファイルシステム（CIのLinux）では別物として解決されて通るので、CIの型検査もビルドも落ちない。
 *
 * 違反: 拡張子を書かずにimportできるファイル（`.ts`・`.tsx`等）は拡張子を外した名前、
 * ディレクトリはその名前、ほかのファイルは拡張子までの名前で比べ、大文字小文字を畳むと同じで
 * 綴りが違う組。
 * 違反でない: 綴りまで同じ名前どうし（`foo.ts`と`foo.css`、`foo.ts`と`foo/`）。
 *
 * 見ないもの: importの綴りとファイルの綴りの食い違い（CIのLinuxで`tsc --noEmit`が解決できずに落ちる）。
 * `forceConsistentCasingInFileNames`は同じファイルを別の綴りで読んだときだけ落とし、別々の
 * 2ファイルは見ないので、この検査の代わりにならない。
 */
import { afterEach, describe, expect, it } from "vitest";

import { removeTree, SRC_ROOT, type TreeEntry, walkTree, writeTree } from "./sourceTree";

const EXTENSIONLESS_IMPORT = /\.(d\.ts|ts|tsx|mts|cts|js|jsx|mjs|cjs)$/;

/** 大文字小文字だけが違う綴りの組（それぞれ綴りの昇順）。 */
function caseOnlyPaths(entries: readonly TreeEntry[]): string[][] {
  const spellings = new Map<string, Set<string>>();
  for (const { path, isDirectory } of entries) {
    const name = isDirectory ? path : path.replace(EXTENSIONLESS_IMPORT, "");
    const key = name.toLowerCase();
    spellings.set(key, (spellings.get(key) ?? new Set()).add(name));
  }
  return [...spellings.values()].filter((names) => names.size > 1).map((names) => [...names].sort());
}

describe("大文字小文字だけが違う名前", () => {
  it("frontend/srcに無い", () => {
    const entries = walkTree(SRC_ROOT);
    expect(entries.map((e) => e.path)).toContain("structure/caseOnlyPaths.test.ts");
    expect(caseOnlyPaths(entries)).toEqual([]);
  });

  describe("わざと作った木で", () => {
    let root = "";
    afterEach(() => removeTree(root));

    it("拡張子を書かずにimportできる2ファイルの組を出す", () => {
      root = writeTree({ "a/Foo.tsx": "", "a/foo.ts": "", "b/bar.d.ts": "", "b/Bar.js": "" });
      expect(caseOnlyPaths(walkTree(root))).toEqual([
        ["a/Foo", "a/foo"],
        ["b/Bar", "b/bar"],
      ]);
    });

    it("ディレクトリとファイルの組を出す", () => {
      root = writeTree({ "Map/index.ts": "", "map.ts": "" });
      expect(caseOnlyPaths(walkTree(root))).toEqual([["Map", "map"]]);
    });

    it("拡張子を書いて読むファイルは拡張子まで比べる", () => {
      root = writeTree({ "a/Foo.css": "", "a/foo.json": "", "b/Logo.svg": "", "b/logo.ts": "" });
      expect(caseOnlyPaths(walkTree(root))).toEqual([]);
      // 大文字小文字を区別しないファイルシステムには書けない組なので、木を作らずに渡す
      const files = ["c/Logo.svg", "c/logo.SVG"].map((path) => ({ path, isDirectory: false }));
      expect(caseOnlyPaths(files)).toEqual([["c/Logo.svg", "c/logo.SVG"]]);
    });

    it("綴りまで同じ名前どうしは出さない", () => {
      root = writeTree({ "foo.ts": "", "foo.css": "", "foo/index.ts": "", "Bar.tsx": "", "Bar.test.tsx": "" });
      expect(caseOnlyPaths(walkTree(root))).toEqual([]);
    });
  });
});
