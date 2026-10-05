import { readFile } from "node:fs/promises";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { MAP_CONTRACT, type MapReading, type MapStep } from "@/testing/mapTrace/recordingMap.contract";

// 本物の MapLibre（パターン4 観点2）が、単体テストの地図の代役（`src/testing/mapTrace/recordingMap.ts`）と同じ呼び出しで
// 同じものを載せること。代役の側は `recordingMap.test.ts` が同じ呼び出しと期待値で流す。本物は WebGL を要するので、ここでしか作れない。
// 本物はアプリを通さず、空のスタイルの地図を1枚だけ作る（見たいのは代役が真似る口の振る舞いで、アプリの描き方ではない）。

/** 本物を読み込むための架空のオリジン。配布物は `node_modules` から返す。 */
const ORIGIN = "https://maplibre.test";
const DIST = path.join(process.cwd(), "node_modules/maplibre-gl/dist");

async function openRealMap(page: Page): Promise<void> {
  await page.route(`${ORIGIN}/**`, async (route) => {
    const name = new URL(route.request().url()).pathname.slice(1);
    if (name === "") {
      await route.fulfill({
        contentType: "text/html",
        body: `<div id="map" style="width:400px;height:300px"></div>
<script type="module">
import * as maplibregl from "./maplibre-gl.mjs";
const map = new maplibregl.Map({ container: "map", style: { version: 8, sources: {}, layers: [] } });
map.on("load", () => { window.realMap = map; });
</script>`,
      });
      return;
    }
    await route.fulfill({ contentType: "text/javascript", body: await readFile(path.join(DIST, name)) });
  });
  await page.goto(`${ORIGIN}/`);
  await page.waitForFunction(() => "realMap" in window);
}

for (const { name, steps, expected } of MAP_CONTRACT) {
  test(`本物の地図: ${name}`, async ({ page }) => {
    await openRealMap(page);

    const reading = await page.evaluate(
      async ({ steps, expected }: { steps: readonly MapStep[]; expected: MapReading }) => {
        type Callable = Record<string, (...args: unknown[]) => unknown>;
        const map = (window as unknown as { realMap: Callable & import("maplibre-gl").Map }).realMap;
        // 名指しした相手が無い等で断った呼び出しは、エラーの出来事になる。聞かないと画面のコンソールへ出るだけなので聞いて捨てる
        // （断ったことは、載っているものに出る）。
        map.on("error", () => {});
        for (const { call, args, source } of steps) {
          const target = (source === undefined ? map : map.getSource(source)) as unknown as Callable;
          target[call](...args);
        }
        // 地物の状態の消去は、次の描画で効く。
        await new Promise((resolve) => {
          map.once("idle", resolve);
          map.triggerRepaint();
        });
        const result: MapReading = {
          layers: (map.getStyle().layers ?? []).map(({ id }) => {
            const names = Object.keys(expected.layers.find((l) => l.id === id)?.paint ?? {});
            return {
              id,
              visibility: (map.getLayoutProperty(id, "visibility") as string | undefined) ?? "visible",
              paint: Object.fromEntries(
                names.map((name) => [
                  name,
                  map.getPaintProperty(id, name as Parameters<typeof map.getPaintProperty>[1]),
                ]),
              ),
              filter: map.getFilter(id) ?? undefined,
            };
          }),
          featureStates: expected.featureStates.map(({ source, id }) => ({
            source,
            id,
            state: { ...map.getFeatureState({ source, id }) },
          })),
          sourceData: await Promise.all(
            expected.sourceData.map(async ({ source }) => ({
              source,
              data: await (map.getSource(source) as import("maplibre-gl").GeoJSONSource).getData(),
            })),
          ),
        };
        return result;
      },
      { steps, expected },
    );

    expect(reading).toEqual(expected);
  });
}
