import type { CaptureScript } from "../context";

// 脚本の例: デスクトップの幅で、地図の上の部品の下に来る点へ、地図を寄せてから目的地を置いて撮る（モックの応答）。
//   node frontend/scripts/capture.mjs --size 1280x800 --script frontend/capture/examples/map-click-hidden.ts

const script: CaptureScript = async ({ page, expect, open, clickMap, clickVisible, settle, shot }) => {
  await open();
  await page.getByRole("button", { name: "目的地: 未設定", exact: true }).click();
  await page.getByRole("button", { name: "目的地を地図で選ぶ" }).click();
  // 地図の左上の隅の点はレイヤーの切り替えの下にあり、clickMap では押せない。
  const hidden = await page.evaluate(() => window.__liveMap().unproject([40, 30]).toArray() as [number, number]);
  await expect(clickMap(hidden)).rejects.toThrow("押せない");
  await clickVisible(hidden);
  await expect(page.getByRole("button", { name: "目的地を地図で置き直す" })).toBeVisible();
  await settle();
  await shot("部品の下の点に置いた目的地");
};

export default script;
