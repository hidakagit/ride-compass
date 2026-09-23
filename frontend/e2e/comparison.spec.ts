// 研究モードの「比較」タブ（ComparisonPanel）が、狭い画面で値の列まで読めること
// （パターン4 観点1）。表の列幅は実寸でしか決まらず、vitest（happy-dom）では捕まらない。
import { expect, test } from "@playwright/test";
import { catalogAxis } from "@/components/Map/__fixtures__/catalogAxes";
import {
  MOBILE_VIEWPORT,
  axisCatalogFixture,
  generateRoutes,
  openMobileApp,
  openMobileSheet,
  routeGenerateResponseFixture,
} from "./fixtures";

const RESEARCH_MODE_ENABLED = { "ridecompass:research-enabled": "1" };

/** 行見出しになる軸。区切りの無い英字の並びを含み、折り返せる位置が少ない。 */
const LONG_AXIS_ID = "long_heading_axis";
const LONG_AXIS_LABEL = "一時停止・徐行の密度（stop_and_yield_points_per_kilometre）";

test("モバイル: 比較表は、長い行見出しがあっても横スクロール無しで値の列まで読める", async ({ page }) => {
  const response = routeGenerateResponseFixture();
  response.conditions.route_preference = { [LONG_AXIS_ID]: 1 };
  response.routes = response.routes.map((route) => ({ ...route, axis_difficulties: { [LONG_AXIS_ID]: 42 } }));

  await openMobileApp(page, {
    storedState: RESEARCH_MODE_ENABLED,
    routes: async (page) => {
      await page.route("**/api/axis-catalog*", (route) =>
        route.fulfill({
          json: axisCatalogFixture([
            {
              ...catalogAxis({ axis_id: LONG_AXIS_ID, label: LONG_AXIS_LABEL, display: { label: LONG_AXIS_LABEL } }),
              default_weight: 1,
            },
          ]),
        }),
      );
      await page.route("**/api/routes/generate/*", (route) =>
        route.fulfill({ json: { status: "done", result: response, error: null } }),
      );
    },
  });

  // 比べる相手ができる2回目の生成まで進める。
  await generateRoutes(page, { distanceKm: 20 });
  await generateRoutes(page, { distanceKm: 22 });
  const outcome = await openMobileSheet(page, "ルート結果");
  await outcome.getByRole("tab", { name: "比較" }).click();

  const table = outcome.getByRole("table");
  await expect(table).toBeVisible();
  await expect(table.getByRole("rowheader", { name: LONG_AXIS_LABEL })).toBeVisible();
  // 値の列（右端）が画面内に収まっていること。行見出しが横へ伸びると、ここが画面外へ出る。
  const box = await table.boundingBox();
  expect(box).not.toBeNull();
  expect((box?.x ?? 0) + (box?.width ?? 0)).toBeLessThanOrEqual(MOBILE_VIEWPORT.width);
});
