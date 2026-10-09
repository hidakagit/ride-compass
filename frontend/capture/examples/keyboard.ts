import type { CaptureScript } from "../context";

// 脚本の例: スマホの幅で目的地の欄に打って候補が出たところを、キーボードが出た画面に見立てて撮る（候補は脚本が返す応答）。
// 地図の塗りは本物の backend でしか出ないので、作業ツリーの版を本物の backend へ向けて撮る。
//   node frontend/scripts/capture.mjs --size 390x844 --api <本番の backend> --script frontend/capture/examples/keyboard.ts

const candidates = ["浅草寺", "浅草駅", "浅草橋駅", "浅草文化観光センター", "浅草演芸ホール"].map((name, index) => ({
  kind: "facility",
  level: "point",
  name,
  area: "台東区浅草",
  latitude: 35.71 + index * 0.002,
  longitude: 139.79 + index * 0.002,
}));

const script: CaptureScript = async ({ page, fixtures, open, settle, shot, shotWithKeyboard, expect }) => {
  await open({
    routes: (p) => p.route("**/api/place-search*", (route) => route.fulfill({ json: { candidates } })),
  });
  const settings = await fixtures.openMobileSheet(page, "ルート設定");
  await settings.getByRole("radio", { name: "目的地", exact: true }).click();
  const field = settings.getByRole("searchbox", { name: "目的地を住所・施設で探す" });
  await field.fill("浅草");
  await field.press("Enter");
  await expect(settings.getByRole("list", { name: "地点の候補" })).toBeVisible();
  await settle();
  await shot("候補が出た");
  await shotWithKeyboard("候補が出た（キーボードあり）", field);
};

export default script;
