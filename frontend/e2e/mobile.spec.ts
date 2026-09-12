import { expect, test } from "@playwright/test";
import { generateRoutes, openMobileApp, openMobileSheet } from "./fixtures";

// モバイル（390px）の導線は下部タブバーとボトムシートで、デスクトップ用の
// smoke.spec.tsが通る経路とは別物。主用途（走行中のスマホ）側の最小疎通を押さえる。
test("モバイル: ルート生成→「ルート結果」シートに候補が並ぶ", async ({ page }) => {
  await openMobileApp(page);
  await generateRoutes(page, { distanceKm: 20 });

  const outcome = await openMobileSheet(page, "ルート結果");
  await expect(outcome.getByRole("tab", { name: /^1 20\.3 km/ })).toBeVisible();
  await expect(outcome.getByRole("tab", { name: /^2 19\.8 km/ })).toBeVisible();
});
