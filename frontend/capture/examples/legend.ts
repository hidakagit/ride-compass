import type { CaptureScript } from "../context";

// 脚本の例: 路面の種類のレイヤーを ON にして凡例の内訳を開き、内訳の行の説明も開いて撮る。
//   node frontend/scripts/capture.mjs --app production --script frontend/capture/examples/legend.ts

const script: CaptureScript = async ({ open, openLegend, shot }) => {
  await open({ layers: ["surface"] });
  const legend = await openLegend("路面の種類");
  await shot("路面の種類の内訳");
  await openLegend("路面の種類", "舗装");
  await shot("路面の種類の内訳の説明", legend);
};

export default script;
