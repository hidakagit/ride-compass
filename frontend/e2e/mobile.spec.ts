import { expect, test } from "@playwright/test";
import { FINE_STEP_AXIS_LABEL, MOBILE_VIEWPORT, generateRoutes, openMobileApp, openMobileSheet } from "./fixtures";

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
    route.fulfill({ status: 503, json: { detail: "アメダス観測値の取得に失敗しました" } }),
  );
  await page.reload();

  // 一般画面にはリクエストIDを含む長い文言を出さない。
  await expect(page.getByText("観測値を取得できません")).toBeVisible();
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
  await expect(settings.getByRole("button", { name: "目的地を置き直す" })).toBeVisible();

  // 経由地を置ける状態にしてから「ルート結果」へ移る。結果を見ている間は、置ける状態の
  // ままでも地図のタップでピンが増えない。
  await settings.getByRole("button", { name: "経由地を追加" }).click();
  await openMobileSheet(page, "ルート結果");
  await page.locator(".app-map-pane canvas").click({ position: { x: 220, y: 200 } });
  await page.waitForTimeout(400);

  // 戻ってきても「置ける状態」は保たれている（離れている間だけ置けない）。経由地が増えて
  // いないことは、件数>0のときだけ出るクリアボタンが無いことで見る。
  const settingsAgain = await openMobileSheet(page, "ルート設定");
  await expect(settingsAgain.getByRole("button", { name: "経由地の指定をやめる" })).toBeVisible();
  await expect(settingsAgain.getByRole("button", { name: "経由地をクリア" })).toHaveCount(0);
  await page.locator(".app-map-pane canvas").click({ position: { x: 240, y: 220 } });
  await expect(settingsAgain.getByRole("button", { name: "経由地をクリア" })).toBeVisible({ timeout: 5000 });
});

// レンズの凡例は段階の細かい軸ほど1行が長い。2列グリッド＋`white-space: nowrap`は、幅が
// 足りないと行がセルからはみ出し、値の右側が読めなくなる。要素はariaツリーに存在するため
// 役割・名前ベースでは捕まらない（ヘッダーの溢れと同じ）。幅を実測して押さえる。
test("モバイル: レンズの凡例が、段階の細かい軸でも幅に収まる", async ({ page }) => {
  await openMobileApp(page);

  await page.getByRole("button", { name: /^レンズ:/ }).click();
  await page.getByRole("radio", { name: FINE_STEP_AXIS_LABEL }).click();
  await page.getByRole("button", { name: /^レンズ:/ }).click();
  await expect(page.getByLabel("凡例の全段階をまとめて表示/非表示")).toBeVisible();

  const rows = await page.evaluate(() => {
    const header = [...document.querySelectorAll("label")].find((el) => el.textContent?.trim() === "凡例");
    const list = header?.parentElement?.lastElementChild;
    return [...((list?.children ?? []) as HTMLCollectionOf<HTMLElement>)].map((row) => ({
      label: row.textContent?.trim() ?? "",
      overflowPx: row.scrollWidth - row.clientWidth,
      beyondViewportPx: Math.round(row.getBoundingClientRect().right - window.innerWidth),
    }));
  });

  expect(rows.length).toBeGreaterThan(0);
  expect(rows.filter((row) => row.overflowPx > 0 || row.beyondViewportPx > 0)).toEqual([]);
});
