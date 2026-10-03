import { expect, type Locator, type Page } from "@playwright/test";
import path from "node:path";
import * as fixtures from "../e2e/fixtures";
import { installMapFinder } from "../e2e-live/live";

// 脚本（scripts/capture-screen.mjs の --script）が受け取る口。

export interface ScreenContext {
  page: Page;
  /** e2e/fixtures.ts の段取りと応答（openMobileSheet・generateRoutes・doneJobFixture 等）。 */
  fixtures: typeof fixtures;
  /**
   * 既定のモック（e2e/fixtures.ts: installApiMocks）を入れてアプリを開き、地図の覆いが外れるまで待つ。
   * `routes` は既定のモックの後・開く前に呼ぶ（後から登録したルートが先に当たるので、応答の上書きはここで足す）。
   * 初回の案内は閉じた状態で開く。
   */
  open(options?: { storedState?: Record<string, string>; routes?: (page: Page) => Promise<unknown> }): Promise<void>;
  /** 地図の上の経度・緯度の点を押す。その点が画面の外か、地図の上に別の部品が重なっていれば止める。 */
  clickMap(lngLat: [number, number]): Promise<void>;
  /** 今の画面（`target` を渡せばその要素だけ）を撮り、書いたファイルを返す。 */
  shot(name: string, target?: Locator): Promise<string>;
}

export type ScreenScript = (context: ScreenContext) => Promise<void>;

export function screenContext(page: Page, out: string): ScreenContext {
  let count = 0;
  return {
    page,
    fixtures,
    async open({ storedState, routes } = {}) {
      await fixtures.installApiMocks(page);
      if (routes) await routes(page);
      await page.addInitScript(installMapFinder);
      await fixtures.seedStoredState(page, { "ridecompass:first-visit-intro-closed": "true", ...storedState });
      await page.goto("/");
      await expect(page.locator(".maplibregl-map")).toBeVisible({ timeout: 30_000 });
      await expect(page.getByText("地図を読み込み中…")).toBeHidden({ timeout: 30_000 });
    },
    async clickMap(lngLat) {
      const point = await page.evaluate((at) => {
        const map = window.__liveMap();
        const projected = map.project(at);
        const box = map.getCanvas().getBoundingClientRect();
        const x = box.left + projected.x;
        const y = box.top + projected.y;
        const inside = x >= 0 && y >= 0 && x < window.innerWidth && y < window.innerHeight;
        return { x, y, onMap: inside && document.elementFromPoint(x, y) === map.getCanvas() };
      }, lngLat);
      if (!point.onMap) {
        throw new Error(
          `地図の点 ${lngLat.join(",")}（画面の ${Math.round(point.x)},${Math.round(point.y)}）は押せない`,
        );
      }
      await page.mouse.click(point.x, point.y);
    },
    async shot(name, target) {
      count += 1;
      const file = path.join(out, `${count}-${name.replace(/[\\/:*?"<>|\s]+/g, "_")}.png`);
      await (target ?? page).screenshot({ path: file });
      console.log(`[capture] ${file}`);
      return file;
    },
  };
}
