import { expect, test } from "@playwright/test";
import { MOBILE_VIEWPORT, generateRoutes, openMobileApp, openMobileSheet } from "./fixtures";

// モバイル（390px）の導線は下部タブバーとボトムシートで、デスクトップ用の
// smoke.spec.tsが通る経路とは別物。主用途（走行中のスマホ）側の最小疎通を押さえる。
test("モバイル: ルート生成→「ルート結果」シートに候補が並ぶ", async ({ page }) => {
  await openMobileApp(page);
  await generateRoutes(page, { distanceKm: 20 });

  const outcome = await openMobileSheet(page, "ルート結果");
  await expect(outcome.getByRole("tab", { name: /^1 20\.3km/ })).toBeVisible();
  await expect(outcome.getByRole("tab", { name: /^2 19\.8km/ })).toBeVisible();
});

// ヘッダーの溢れは、要素自体はariaツリーに存在するため役割・名前ベースの検査では
// 捕まらない（画面外にあっても見つかってしまう）。幅と座標を実測して押さえる。
test("モバイル: 観測値の取得に失敗してもヘッダーが幅に収まり、メニューが押せる", async ({ page }) => {
  await openMobileApp(page);
  // installApiMocksより後に登録して優先させる（Playwrightは後勝ち）。
  await page.route("**/api/weather/amedas*", (route) =>
    route.fulfill({ status: 503, json: { detail: "アメダス観測値の取得に失敗しました" } })
  );
  await page.reload();

  // 一般画面にはリクエストIDを含む長い文言を出さない。
  await expect(page.getByText("観測値なし")).toBeVisible();
  await expect(page.getByText(/\[req:/)).toHaveCount(0);

  const header = page.locator("header").first();
  const size = await header.evaluate((el) => ({ scrollWidth: el.scrollWidth, clientWidth: el.clientWidth }));
  expect(size.scrollWidth).toBeLessThanOrEqual(size.clientWidth);

  const menu = await page.getByRole("button", { name: "メニュー" }).boundingBox();
  expect(menu).not.toBeNull();
  expect((menu?.x ?? 0) + (menu?.width ?? 0)).toBeLessThanOrEqual(MOBILE_VIEWPORT.width);
});

// 生成に関わる操作は「ルート生成」ボタンがある場所でだけ受け付ける。ルート結果で候補線を
// 選ぼうとして外すたびに経由地が増えるのを防ぐ（T781）。
test("モバイル: ルート結果を見ている間は地図タップでピンが置かれない", async ({ page }) => {
  await openMobileApp(page);

  const settings = await openMobileSheet(page, "ルート設定");
  await settings.getByRole("button", { name: "目的地", exact: true }).click();
  await page.locator(".app-map-pane canvas").click({ position: { x: 180, y: 150 } });
  await expect(settings.getByText("目的地を変更")).toBeVisible();

  const outcome = await openMobileSheet(page, "ルート結果");
  await page.locator(".app-map-pane canvas").click({ position: { x: 220, y: 200 } });
  await page.waitForTimeout(400);
  await expect(outcome.getByText(/📍/)).toHaveCount(0);

  const settingsAgain = await openMobileSheet(page, "ルート設定");
  await page.locator(".app-map-pane canvas").click({ position: { x: 240, y: 220 } });
  await expect(settingsAgain.getByText(/📍\s*1/)).toBeVisible({ timeout: 5000 });
});
