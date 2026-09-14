// 研究モードの「比較」タブ（ComparisonPanel）。狭い画面で値の列が読めることと、比べる
// 相手がいない間に空白へならないことを、実際の描画幅で確かめる（T762）。
// 幅の破綻はvitest（happy-dom、実寸を返さない）では捕まらない。
import { expect, test } from "@playwright/test";
import { MOBILE_VIEWPORT, generateRoutes, openMobileApp, openMobileSheet } from "./fixtures";

const RESEARCH_MODE_ENABLED = { "ridecompass:research-enabled": "1" };

test("モバイル: 比較タブは、相手がいない間は案内を出し、2回目以降は横スクロール無しで読める", async ({ page }) => {
  await openMobileApp(page, { storedState: RESEARCH_MODE_ENABLED });

  await generateRoutes(page, { distanceKm: 20 });
  const outcome = await openMobileSheet(page, "ルート結果");
  await outcome.getByRole("tab", { name: "比較" }).click();

  // 1回目の生成後は比べる相手がいない。表の代わりに次にすることを出す（空白にしない）。
  await expect(outcome.getByText(/もう1回生成すると/)).toBeVisible();

  await generateRoutes(page, { distanceKm: 22 });
  await openMobileSheet(page, "ルート結果");
  // 生成すると候補タブへ戻るため、比較タブを開き直す。
  await outcome.getByRole("tab", { name: "比較" }).click();

  const table = outcome.getByRole("table");
  await expect(table).toBeVisible();
  // 値の列（右端）が画面内に収まっていること。行見出しが横へ伸びると、ここが画面外へ出る。
  const box = await table.boundingBox();
  expect(box).not.toBeNull();
  expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(MOBILE_VIEWPORT.width);
});

test("モバイル: 比較タブを開いたまま生成すると、新しい候補が表示される", async ({ page }) => {
  await openMobileApp(page, { storedState: RESEARCH_MODE_ENABLED });

  await generateRoutes(page, { distanceKm: 20 });
  const outcome = await openMobileSheet(page, "ルート結果");
  await outcome.getByRole("tab", { name: "比較" }).click();
  await expect(outcome.getByText(/もう1回生成すると/)).toBeVisible();

  await generateRoutes(page, { distanceKm: 22 });
  await openMobileSheet(page, "ルート結果");

  // 比較表ではなく候補が出ている（押した操作の結果が見えないまま前の表が残らない）。
  await expect(outcome.getByRole("tab", { name: "比較", selected: true })).toHaveCount(0);
});
