/** maplibre-glのWorkerを静的配信できる場所へ複製する。
 *
 * maplibre-glはWorkerのURLを ``new URL(`./${file}`, import.meta.url)`` で解決するため、
 * Next.jsのバンドラ（Turbopack/Webpackのいずれも）が解決先を静的に追えず、Workerが空の
 * ページを読み込んで地図が永久に描画されない。`setWorkerUrl`でここへ複製したURLを
 * 指すことで、バンドラの解決を経由しない。
 *
 * Workerはsharedチャンクを**自分のURLからの相対**でimportするため、2本を同じ
 * ディレクトリへ置く。複製物はリポジトリへ置かない（node_modulesが正）。
 */
import { copyFile, mkdir } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const WORKER_FILES = ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"];

const require = createRequire(import.meta.url);
const distDir = dirname(require.resolve("maplibre-gl/dist/maplibre-gl.mjs"));
const publicDir = join(dirname(dirname(fileURLToPath(import.meta.url))), "public", "maplibre");

await mkdir(publicDir, { recursive: true });
for (const file of WORKER_FILES) {
  await copyFile(join(distDir, file), join(publicDir, file));
}
console.log(`maplibre worker: ${WORKER_FILES.join(", ")} -> ${publicDir}`);
