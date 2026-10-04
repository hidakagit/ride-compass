import type { CaptureScript } from "../context";

// 脚本の例: 道路の種類のレイヤーを ON にして凡例の内訳を開き、内訳の行の説明も開いて撮る。
//   node frontend/scripts/capture.mjs --app production --script frontend/capture/examples/legend.ts

const script: CaptureScript = async ({ open, openLegend, shot }) => {
  await open({ layers: ["highway"] });
  const legend = await openLegend("道路の種類");
  await shot("道路の種類の内訳");
  await openLegend("道路の種類", "幹線道路");
  await shot("道路の種類の内訳の説明", legend);
};

export default script;
