import type { ScreenScript } from "../screen";

// 脚本の例: スマホの幅で生成して、ルート結果のシートを撮る。
//   node frontend/scripts/capture-screen.mjs --script frontend/capture/examples/route-result.ts

const script: ScreenScript = async ({ page, fixtures, open, shot }) => {
  await open();
  await fixtures.generateRoutes(page);
  const sheet = await fixtures.openMobileSheet(page, "ルート結果");
  await shot("ルート結果");
  await shot("ルート結果のシート", sheet);
};

export default script;
