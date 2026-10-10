import type { CaptureScript } from "../context";

// 脚本の例: ルート設定の出発地を、置いた位置の辺りの応答を替えて撮る（作業ツリーの版を本物の backend へ向けて）。
// patch は本物の応答が失敗でも替えた本文を成功として返すので、本番の backend にまだ無い経路の応答もこの形で替えられる。
//   node frontend/scripts/capture.mjs --api <本番の backend> --script frontend/capture/examples/place-area.ts

const script: CaptureScript = async ({ page, fixtures, open, patch, settle, shot }) => {
  await patch("**/api/place-area*", () => ({ area: "仮の辺り" }));
  await open();
  const mobile = (page.viewportSize()?.width ?? 1280) < 768;
  const scope = mobile ? await fixtures.openMobileSheet(page, "ルート設定") : page;
  const origin = scope.getByRole("region", { name: "出発地", exact: true });
  await origin.getByText("仮の辺り").waitFor();
  await settle();
  await shot("出発地", origin);
};

export default script;
