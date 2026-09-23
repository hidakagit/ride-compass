import { expect, test, type Page } from "@playwright/test";
import { installApiMocks } from "./fixtures";

// 地図（MapLibre）が実ブラウザでしか見せない挙動。単体テストの代役地図はWorker・描画・
// スタイル検証を持たないため、ここでしか確かめられない。

/** 描けたかを見分けるための塗り色。基礎地図・アプリのUIが使わない色にする。 */
const PROBE_FILL = { r: 255, g: 0, b: 255 };

/**
 * 地図のcanvasが見えている範囲のうち、`PROBE_FILL`で塗られた画素の割合。
 * MapLibreは既定で描画バッファを保持しないため`toDataURL`は空を返す。画面の写しを取り、
 * ページの2D canvasで画素へ戻して数える。
 */
async function probeFillRatio(page: Page): Promise<number> {
  const canvas = page.locator("canvas.maplibregl-canvas");
  const png = (await canvas.screenshot()).toString("base64");
  return page.evaluate(
    async ({ png, fill }) => {
      const image = new Image();
      image.src = `data:image/png;base64,${png}`;
      await image.decode();
      const scratch = document.createElement("canvas");
      scratch.width = image.width;
      scratch.height = image.height;
      const context = scratch.getContext("2d");
      if (!context) return 0;
      context.drawImage(image, 0, 0);
      const { data } = context.getImageData(0, 0, image.width, image.height);
      let hits = 0;
      for (let i = 0; i < data.length; i += 4) {
        if (
          Math.abs(data[i] - fill.r) < 8 &&
          Math.abs(data[i + 1] - fill.g) < 8 &&
          Math.abs(data[i + 2] - fill.b) < 8
        ) {
          hits += 1;
        }
      }
      return hits / (data.length / 4);
    },
    { png, fill: PROBE_FILL },
  );
}

// 「描けた」＝GeoJSONソースの面が画素として出たこと。GeoJSONの取り込みはWorkerが行うため、
// Workerの読み込みに失敗すると（本番ビルドでWorkerのURLが404になる等）canvasは残ったまま
// この色が1画素も出ない。DOMの状態・canvasの有無・サイズは、その状態でも変わらない。
test("地図が描ける（Workerが動き、ソースの面が画素になる）", async ({ page }) => {
  await installApiMocks(page);
  await page.route("**/api/basemap/**", (route) =>
    route.fulfill({
      json: {
        version: 8,
        sources: {
          probe: {
            type: "geojson",
            data: {
              type: "Feature",
              properties: {},
              geometry: {
                type: "Polygon",
                coordinates: [
                  [
                    [-179, -85],
                    [179, -85],
                    [179, 85],
                    [-179, 85],
                    [-179, -85],
                  ],
                ],
              },
            },
          },
        },
        layers: [
          {
            id: "probe",
            type: "fill",
            source: "probe",
            paint: { "fill-color": `rgb(${PROBE_FILL.r}, ${PROBE_FILL.g}, ${PROBE_FILL.b})` },
          },
        ],
      },
    }),
  );

  await page.goto("/");

  // 地図の上にはチップ・パネル等が重なるため、全面ではなく過半を条件にする。
  await expect.poll(() => probeFillRatio(page), { timeout: 20_000 }).toBeGreaterThan(0.5);
});
