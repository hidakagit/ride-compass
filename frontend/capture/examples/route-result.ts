import type { CaptureScript } from "../context";

// 脚本の例: スマホの幅で生成して、ルート結果のシートを撮る（モックの応答）。
//   node frontend/scripts/capture.mjs --script frontend/capture/examples/route-result.ts

const script: CaptureScript = async ({ page, fixtures, open, shot }) => {
  await open();
  await fixtures.generateRoutes(page);
  const sheet = await fixtures.openMobileSheet(page, "ルート結果");
  await shot("ルート結果");
  await shot("ルート結果のシート", sheet);
};

export default script;
