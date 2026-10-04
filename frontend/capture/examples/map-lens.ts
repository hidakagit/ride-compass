import type { CaptureScript } from "../context";

// 脚本の例: 地図の塗りを、位置と倍率を決めてレンズごとに撮る（本番の画面か、作業ツリーの版を本物の backend へ向けて）。
//   node frontend/scripts/capture.mjs --app production --script frontend/capture/examples/map-lens.ts
//   node frontend/scripts/capture.mjs --api <本番の backend> --script frontend/capture/examples/map-lens.ts

const script: CaptureScript = async ({ open, chooseLens, shot }) => {
  await open({ point: { latitude: 35.681, longitude: 139.767 }, zoom: 15 });
  for (const lens of ["勾配", "舗装質"]) {
    await chooseLens(lens);
    await shot(lens);
  }
};

export default script;
