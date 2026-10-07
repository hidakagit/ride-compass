import type { CaptureScript } from "../context";

// 脚本の例: 路面のレイヤーを ON にして描かれた道を1本押し、道の詳細を撮る（本番の画面か、作業ツリーの版を本物の backend へ向けて）。
//   node frontend/scripts/capture.mjs --app production --script frontend/capture/examples/road-detail.ts
//   node frontend/scripts/capture.mjs --api <本番の backend> --script frontend/capture/examples/road-detail.ts

const script: CaptureScript = async ({ page, expect, open, clickFeature, settle, shot }) => {
  await open({ layers: ["surface"] });
  await clickFeature("road");
  const popup = page.locator(".maplibregl-popup");
  await expect(popup).toBeVisible();
  await popup.getByText("この道の属性", { exact: true }).click();
  await settle();
  await shot("道の詳細");
};

export default script;
