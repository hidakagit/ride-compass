import type { CaptureScript } from "../context";

// 脚本の例: 管理画面の「較正値」タブを、管理APIの応答を走行モデルの2件に替えて撮る（モックの応答）。
//   node frontend/scripts/capture.mjs --script frontend/capture/examples/admin-tuning.ts

const parameter = (id: string, label: string, unit: string, value: number, defaultValue: number) => ({
  id,
  label,
  unit,
  description: "",
  default: defaultValue,
  minimum: 0,
  maximum: 200,
  effect: "immediate",
  effect_title: "次のルート生成から効く",
  value,
  overridden: value !== defaultValue,
});

const script: CaptureScript = async ({ openAdmin, shot }) => {
  const tuning = [
    parameter("speed.mass_kg", "総質量", "kg", 72, 80),
    parameter("speed.cda_m2", "空気抵抗 CdA", "m²", 0.32, 0.32),
  ];
  const panel = await openAdmin({
    tab: "較正値",
    routes: (p) => p.route("**/admin/api/tuning", (route) => route.fulfill({ json: tuning })),
  });
  await panel.getByText("総質量").waitFor();
  await shot("較正値", panel);
};

export default script;
