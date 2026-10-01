import { mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/** 検査の母集団の根（`frontend/src`）。 */
export const SRC_ROOT = fileURLToPath(new URL("..", import.meta.url));

export type TreeEntry = { path: string; isDirectory: boolean };

/** `root`配下の全エントリ。`path`は`root`からの相対パスで、区切りは`/`。 */
export function walkTree(root: string, dir = ""): TreeEntry[] {
  return readdirSync(join(root, dir), { withFileTypes: true }).flatMap((entry) => {
    const path = dir ? `${dir}/${entry.name}` : entry.name;
    return entry.isDirectory()
      ? [{ path, isDirectory: true }, ...walkTree(root, path)]
      : [{ path, isDirectory: false }];
  });
}

/** 相対パス→本文の組を一時ディレクトリへ書き、その根を返す。消すのは`removeTree`。 */
export function writeTree(files: Record<string, string>): string {
  const root = mkdtempSync(join(tmpdir(), "structure-"));
  for (const [path, text] of Object.entries(files)) {
    mkdirSync(dirname(join(root, path)), { recursive: true });
    writeFileSync(join(root, path), text);
  }
  return root;
}

export function removeTree(root: string): void {
  rmSync(root, { recursive: true, force: true });
}
