import { expect, type Locator, type Page } from "@playwright/test";
import path from "node:path";
import { mapDisplay } from "@/types/generated/mapDisplay";
import * as fixtures from "../e2e/fixtures";
import { installPageHelpers } from "../e2e/states";
import { LIVE_POINT, chooseLens, installMapFinder, settleMap } from "../e2e-live/live";

// 脚本（scripts/capture.mjs の --script）が受け取る口。脚本はこの口だけを使い、何も読み込まない（型の読み込みは実行時に
// 消えるのでよい）。そのため作業ツリーの外に置いても、読み込みの解決に頼らずに動く。

interface OpenOptions {
  /** 現在地（出発地）。既定は、モックなら e2e/fixtures.ts: installApiMocks の地点、本物の backend なら e2e-live/live.ts: LIVE_POINT。 */
  point?: { latitude: number; longitude: number };
  /** 開いたあとに寄せる地図の倍率。 */
  zoom?: number;
  /** ON にするレイヤーの id（mapDisplay.layers）。渡さないレイヤーは既定の表示のまま。 */
  layers?: string[];
  /** 開く前に入れる保存状態（localStorage）。 */
  storedState?: Record<string, string>;
  /** 開く前・モックの後に呼ぶ（後から登録したルートが先に当たるので、応答の上書きはここで足す）。 */
  routes?: (page: Page) => Promise<unknown>;
}

export interface CaptureContext {
  page: Page;
  expect: typeof expect;
  /** e2e/fixtures.ts の段取りと応答（openMobileSheet・generateRoutes・doneJobFixture 等）。 */
  fixtures: typeof fixtures;
  /** アプリを開き、地図の全ソースの読み終わりまで待つ。初回の案内は閉じた状態で開く。 */
  open(options?: OpenOptions): Promise<void>;
  /** 地図の色分け（レンズ）を名前で選び、読み終わりまで待つ。選べなければ、選べる名前を並べて止まる。 */
  chooseLens(label: string): Promise<void>;
  /**
   * チップの名前で凡例の内訳を開き、その内訳を返す。チップが畳んだまとまりの中にあれば開く。`row` を渡せば、その行の説明も開く。
   * 開けなければ、選べる名前を並べて止まる。
   */
  openLegend(chip: string, row?: string): Promise<Locator>;
  /** 地図の上の経度・緯度の点を押す。その点が画面の外か、地図の上に別の部品が重なっていれば止める。 */
  clickMap(lngLat: [number, number]): Promise<void>;
  /**
   * URL が glob に当たる応答の本文を `transform` の返した JSON に替える。本物の応答を取ってから本文だけを替えるので、CORS 等の
   * ヘッダーは本物のまま残る（ヘッダーの無い応答で返すと、別オリジンの backend への取得としてブラウザが捨てる）。
   * 本物の backend へ向けたときに使う（モックの応答を替えるなら open の routes で page.route を足す）。
   */
  patch(glob: string, transform: (json: unknown) => unknown): Promise<void>;
  /** 地図の全ソースの読み終わりまで待つ。 */
  settle(): Promise<void>;
  /** 今の画面（`target` を渡せばその要素だけ）を撮り、書いたファイルを返す。 */
  shot(name: string, target?: Locator): Promise<string>;
}

export type CaptureScript = (context: CaptureContext) => Promise<void>;

function fileName(name: string): string {
  return name.replace(/[\\/:*?"<>|\s]+/g, "_");
}

/** 選び損ねた直後に呼ぶので、選択肢が閉じていれば開く。 */
async function lensLabels(page: Page): Promise<string[]> {
  const group = page.getByRole("radiogroup", { name: "地図の色分け" });
  if (!(await group.isVisible())) await page.getByRole("button", { name: /^地図の色分け: / }).click();
  const labels = await group.getByRole("radio").allInnerTexts();
  return labels.map((label) => label.replace(/\s+/g, " ").trim());
}

async function ariaLabels(scope: Page | Locator, suffix: string): Promise<string[]> {
  const labels = await scope
    .getByRole("button", { name: new RegExp(`${suffix}$`) })
    .evaluateAll((buttons) => buttons.map((button) => button.getAttribute("aria-label") ?? ""));
  return labels.filter((label) => label.endsWith(suffix)).map((label) => label.slice(0, -suffix.length));
}

export function captureContext(page: Page, { out, mocked }: { out: string; mocked: boolean }): CaptureContext {
  let count = 0;
  const settle = () => settleMap(page);
  return {
    page,
    expect,
    fixtures,
    settle,
    async open({ point, zoom, layers = [], storedState, routes } = {}) {
      const layerIds: string[] = mapDisplay.layers.map(({ id }) => id);
      const unknown = layers.filter((id) => !layerIds.includes(id));
      if (unknown.length > 0) {
        throw new Error(`知らないレイヤー: ${unknown.join(" / ")}。選べるレイヤー: ${layerIds.join(" / ")}`);
      }
      if (mocked) await fixtures.installApiMocks(page);
      if (point || !mocked) {
        await page.context().grantPermissions(["geolocation"]);
        await page.context().setGeolocation(point ?? LIVE_POINT);
      }
      if (routes) await routes(page);
      await page.addInitScript(installPageHelpers);
      await page.addInitScript(installMapFinder);
      await fixtures.seedStoredState(page, {
        "ridecompass:first-visit-intro-closed": "true",
        ...(layers.length > 0
          ? { "ridecompass:layer-visibility": JSON.stringify(Object.fromEntries(layers.map((id) => [id, true]))) }
          : {}),
        ...storedState,
      });
      await page.goto("/");
      await expect(page.locator(".maplibregl-map")).toBeVisible({ timeout: 60_000 });
      await expect(page.getByText("地図を読み込み中…")).toBeHidden({ timeout: 60_000 });
      await settle();
      if (zoom !== undefined) {
        await page.evaluate((z) => window.__liveMap().jumpTo({ zoom: z }), zoom);
        await settle();
      }
    },
    async chooseLens(label) {
      try {
        await chooseLens(page, label);
      } catch (error) {
        throw new Error(`レンズ「${label}」を選べない。選べるレンズ: ${(await lensLabels(page)).join(" / ")}`, {
          cause: error,
        });
      }
      await settle();
    },
    async openLegend(chip, row) {
      const trigger = page.getByRole("button", { name: `${chip}の凡例`, exact: true });
      const seen = new Set<string>();
      // まとまりの外のチップはそのまま出ているので、まず開かずに探し、無ければまとまりを1つずつ開く（開けるのは同時に1つ）。
      for (const group of [null, ...mapDisplay.overlayGroups]) {
        if (group) {
          const header = page.getByRole("button", { name: group.label, exact: true });
          if ((await header.getAttribute("aria-expanded")) === "false") await header.click();
        }
        if (await trigger.isVisible()) break;
        for (const name of await ariaLabels(page, "の凡例")) seen.add(name);
      }
      if (!(await trigger.isVisible())) {
        throw new Error(`凡例「${chip}」を開けない。選べる凡例: ${[...seen].join(" / ")}`);
      }
      const panel = page.getByRole("dialog", { name: `${chip}の内訳` });
      if (!(await panel.isVisible())) await trigger.click();
      await expect(panel).toBeVisible();
      if (row !== undefined) {
        const info = panel.getByRole("button", { name: `${row}の説明を表示`, exact: true });
        if (!(await info.isVisible())) {
          const rows = await ariaLabels(panel, "の説明を表示");
          throw new Error(`凡例「${chip}」の行「${row}」の説明を開けない。説明のある行: ${rows.join(" / ")}`);
        }
        await info.click();
      }
      return panel;
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
    async patch(glob, transform) {
      await page.route(glob, async (route) => {
        const response = await route.fetch();
        await route.fulfill({ response, json: await transform(await response.json()) });
      });
    },
    async shot(name, target) {
      count += 1;
      const file = path.join(out, `${count}-${fileName(name)}.png`);
      await (target ?? page).screenshot({ path: file });
      console.log(`[capture] ${file}`);
      return file;
    },
  };
}
