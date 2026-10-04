import type { CaptureScript } from "../context";

// 脚本の例: モックの軸カタログを、重みを持つ軸3つと走行モデルの較正値に替えて、ルート設定の重みと想定速度の説明を撮る（モックの応答）。
//   node frontend/scripts/capture.mjs --script frontend/capture/examples/axis-catalog.ts

const script: CaptureScript = async ({ page, fixtures, catalogAxes, open, shot }) => {
  const catalog = fixtures.axisCatalogFixture(
    ["坂", "路面", "交通"].map((axisId, index) =>
      catalogAxes.rampEntry(axisId, [50], { category: "推定", default_weight: index + 1 }),
    ),
  );
  catalog.client_tuning = {
    "speed.mass_kg": 80,
    "speed.cda_m2": 0.32,
    "speed.max_descent_kmh": 50,
    "speed.walking_kmh": 6,
  };
  await open({ routes: (p) => p.route("**/api/axis-catalog*", (route) => route.fulfill({ json: catalog })) });
  const sheet = await fixtures.openMobileSheet(page, "ルート設定");
  await sheet.getByRole("tab", { name: "重み" }).click();
  await shot("ルート設定の重み", sheet);
  await page.getByRole("button", { name: "ルート設定", exact: true }).click();
  await page.getByRole("button", { name: /^想定速度: / }).click();
  await page.getByRole("button", { name: "想定速度の説明" }).click();
  await shot("想定速度の説明");
};

export default script;
