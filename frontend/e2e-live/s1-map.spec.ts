import { expect, test } from "@playwright/test";
import {
  allLayersOn,
  branch,
  chooseLens,
  currentLensLabel,
  expectNoOwnFailures,
  externalErrors,
  fetchCatalog,
  notApplicable,
  openLive,
  renderedRoads,
  reportExternal,
  roadSourceId,
  settleMap,
} from "./live";
import materialCatalog from "@/types/generated/material-catalog.json";

/** 道の詳細が必ず持つ行（路面の区分）の項目名。名前は材料カタログが持つ。 */
const SURFACE_ROW_LABEL = materialCatalog.find((material) => material.material_id === "surface_class")!.name;

// S1 地図の描画（生成前）。実データが式・部品へ入って初めて壊れるもの（公開軸の材料がタイルに無く地図に出ない、
// 専用レイヤーの軸が出ない・巻き添えで消える、取得の失敗が空で返る、道を押すと例外で開かない）を見る。
// 幹: 起点を現在地として与え、全レイヤーONで開く。枝: 下のC〜G。

test("S1 地図の描画（生成前）", async ({ page }) => {
  const catalog = await fetchCatalog();
  const axes = catalog.axes;
  expect(axes.length, "公開軸が1件も無い").toBeGreaterThan(0);
  const statsBefore = await externalErrors();

  const watch = await openLive(page, { storedState: allLayersOn() });
  const source = await roadSourceId(page);

  // C: 地図のエラー（取得の失敗も含む）が0件。
  expect.soft(watch.mapErrors, "[map:error]（取得の失敗を含む）").toEqual([]);

  // D: 表示範囲の路面タイルに道が1件以上。公開軸ごとに、その軸がタイルから読む材料のどれかを持つ道が1件以上
  // （材料ごとに求めると、踏切のように範囲に実在しないものが欠陥に見える。材料ごとの不在は「該当なし」で出す）。
  const tileRoads = [...watch.roadTiles.values()].flat();
  expect(tileRoads.length, "取得した路面タイルに道が無い").toBeGreaterThan(0);
  const carries = (road: Record<string, unknown>, property: string) =>
    road[property] !== undefined && road[property] !== null;
  const tileAxes = axes.filter((axis) => axis.display.tile_inputs.length > 0);
  expect(tileAxes.length, "タイルから材料を読む公開軸が1件も無い").toBeGreaterThan(0);
  for (const axis of tileAxes) {
    const inputs = axis.display.tile_inputs.map((input) => input.property);
    const carriers = tileRoads.filter((road) => inputs.some((p) => carries(road, p))).length;
    expect
      .soft(carriers, `「${axis.label}」の材料（${inputs.join("・")}）を持つ道が路面タイルに無い`)
      .toBeGreaterThan(0);
    for (const property of inputs.filter((p) => !tileRoads.some((road) => carries(road, p)))) {
      notApplicable(`材料 ${property}`, "表示範囲の路面タイルにこの材料を持つ道が無い");
    }
  }

  // E→F: 公開軸のレンズを1つずつ選ぶ → その軸の値を持つ道が描かれている。
  const originalLens = await currentLensLabel(page);
  for (const axis of axes) {
    await branch(
      page,
      `レンズ「${axis.label}」`,
      async () => {
        const errorsBefore = watch.mapErrors.length;
        const valuesBefore = watch.wayValues.length;
        await chooseLens(page, axis.label);
        await settleMap(page);
        const drawn = await renderedRoads(page, source);
        expect.soft(drawn.length, `「${axis.label}」: 道が描かれていない`).toBeGreaterThan(0);
        if (axis.dedicated_way_value_layer) {
          // 専用レイヤーの軸は、道ごとの値をタイルとは別の経路で受け取る。値を受け取り、それが描かれている道を指すこと。
          const received = watch.wayValues.slice(valuesBefore).filter((entry) => entry.axisId === axis.axis_id);
          const wayIds = new Set(received.flatMap((entry) => Object.keys(entry.values)));
          expect.soft(wayIds.size, `「${axis.label}」: 道ごとの値を1件も受け取っていない`).toBeGreaterThan(0);
          const drawnWithValue = drawn.filter((road) => wayIds.has(String(road.osm_way_id))).length;
          expect.soft(drawnWithValue, `「${axis.label}」: 値を受け取った道が1本も描かれていない`).toBeGreaterThan(0);
        } else {
          const inputs = axis.display.tile_inputs.map((input) => input.property);
          const carriers = drawn.filter((road) => inputs.some((p) => road[p] !== undefined && road[p] !== null));
          expect
            .soft(carriers.length, `「${axis.label}」: 材料（${inputs.join("・")}）を持つ道が描かれていない`)
            .toBeGreaterThan(0);
        }
        expect.soft(watch.mapErrors.slice(errorsBefore), `「${axis.label}」を選んだあとの[map:error]`).toEqual([]);
      },
      () => chooseLens(page, originalLens),
    );
  }

  // G: 道を1本押す → 道の詳細が開き、例外・エラー表示が無い。
  await branch(
    page,
    "道を押す",
    async () => {
      const point = await page.evaluate((road) => {
        const map = window.__liveMap();
        const canvas = map.getCanvas().getBoundingClientRect();
        for (const feature of map.queryRenderedFeatures().filter((f) => f.source === road)) {
          if (feature.geometry.type !== "LineString") continue;
          const coordinates = feature.geometry.coordinates;
          const [lng, lat] = coordinates[Math.floor(coordinates.length / 2)];
          const { x, y } = map.project([lng, lat]);
          const client = { x: canvas.left + x, y: canvas.top + y };
          // 地図の上に重なる部品（チップ・パネル）の下ではなく、地図そのものが押される点だけを使う。
          if (document.elementFromPoint(client.x, client.y) !== map.getCanvas()) continue;
          // 全レイヤーONでは道の上に点（事故・POI）が重なる。押して一番上に来るのが道である点だけを使う。
          if (map.queryRenderedFeatures([x, y])[0]?.source === road) return client;
        }
        return null;
      }, source);
      expect(point, "押せる位置に描かれた道が無い").not.toBeNull();
      const errorsBefore = watch.pageErrors.length;
      await page.mouse.click(point!.x, point!.y);
      await expect(page.locator(".maplibregl-popup")).toBeVisible({ timeout: 10_000 });
      // 開いたのが道の詳細であること（道の詳細は路面の区分の行を必ず持つ。属性は畳んで開くので、開いてから見る）。
      // 描画の例外はエラー境界（app/error.tsx）が受けてページの例外にならないので、中身が出たかで見る。
      const popup = page.locator(".maplibregl-popup");
      await popup.getByText("この道の属性", { exact: true }).click();
      await expect(popup.getByText(SURFACE_ROW_LABEL, { exact: true })).toBeVisible();
      await settleMap(page);
      expect.soft(watch.pageErrors.slice(errorsBefore), "道を押したあとのページの例外").toEqual([]);
      await expect.soft(page.locator(".maplibregl-popup").getByRole("alert")).toHaveCount(0);
    },
    async () => {
      await page.keyboard.press("Escape");
      if (await page.locator(".maplibregl-popup").isVisible()) {
        await page.locator(".maplibregl-popup-close-button").click();
      }
      await expect(page.locator(".maplibregl-popup")).toBeHidden();
    },
  );

  expectNoOwnFailures(watch);
  reportExternal(watch, statsBefore, await externalErrors());
});
