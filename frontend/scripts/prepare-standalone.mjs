// output: standalone（frontend/next.config.ts）のビルド成果物（.next/standalone）は
// .next/static・publicを自動では含まない。本番Dockerfile（frontend/Dockerfile）はCOPYで
// 個別に配置しており、ローカル/CIのE2E（playwright.config.ts）で本番と同じ
// `node .next/standalone/server.js`エントリポイントを再現するには同じ配置が要る
// （`next start`ではstandalone構成に固有の問題を検知できない）。DockerfileのCOPYと同じ処理をNode標準の
// fs.cpで行う（Windows/Linux両対応、追加パッケージ不要）。
import { cp } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

await cp(
  path.join(frontendRoot, ".next", "static"),
  path.join(frontendRoot, ".next", "standalone", ".next", "static"),
  { recursive: true },
);
await cp(path.join(frontendRoot, "public"), path.join(frontendRoot, ".next", "standalone", "public"), {
  recursive: true,
});
