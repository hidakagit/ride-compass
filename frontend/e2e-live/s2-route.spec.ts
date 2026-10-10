import { expect, test } from "@playwright/test";
import { openMobileSheet } from "../e2e/fixtures";
import {
  branch,
  chooseLens,
  currentLensLabel,
  expectNoOwnFailures,
  externalErrors,
  fetchCatalog,
  openLive,
  reportExternal,
  routeSegmentsPainted,
  settleMap,
} from "./live";

// S2 ルート生成（生成後）。実グラフでしか出ない探索の欠陥（並行する道・取込範囲の端で生成が落ちる）と、
// 実データの区間を押したときの例外、作ったあとにレンズを替えるとルートの区間が全部「データなし」になる欠陥（実際の応答が
// 区間に載せる値と、レンズが塗る値の食い違い）を見る。
// 幹: S1と同じ地点で開き、距離を指定して生成を1回。枝: 下のC〜E。

interface Segment {
  geometry: { coordinates: [number, number][] } | null;
}

test("S2 ルート生成（生成後）", async ({ page }) => {
  const catalog = await fetchCatalog();
  expect(catalog.axes.length, "公開軸が1件も無い").toBeGreaterThan(0);
  const statsBefore = await externalErrors();
  // デバッグログは`[map:error]`を読むため。
  const watch = await openLive(page, { storedState: { "ridecompass:debug-enabled": "1" } });

  const settings = await openMobileSheet(page, "ルート設定");
  const distanceKm = 15;
  await settings.getByLabel("距離").fill(String(distanceKm));
  const started = Date.now();
  await settings.getByRole("button", { name: "ルート生成" }).click();
  // 生成は探索範囲の区間の数に比例して数秒〜数十秒かかる。
  await expect(settings.getByRole("button", { name: "ルート生成" })).toBeEnabled({ timeout: 240_000 });
  console.log(`[e2e-live] 生成（${distanceKm}km） ${((Date.now() - started) / 1000).toFixed(1)}秒`);
  await page.getByRole("button", { name: "ルート設定", exact: true }).click();
  await expect(settings).toBeHidden();
  await settleMap(page);

  // C: 候補が1件以上、エラー表示が無い。
  const result = watch.generated.at(-1);
  expect(result, "生成の完了の応答を受け取っていない").toBeDefined();
  expect.soft(result!.routes.length, `候補が0件（理由: ${result!.no_candidates_reason}）`).toBeGreaterThan(0);
  // 中身の無いalert（Next.jsの画面遷移の読み上げ用）は数えない。
  await expect.soft(page.getByRole("alert").filter({ hasText: /\S/ })).toHaveCount(0);

  // D: ルート線の区間を押す → 押した点にルート線が描かれていて、押したあとに例外が無い。
  const segments = ((result!.routes[0] as { segments?: Segment[] } | undefined)?.segments ?? []).filter(
    (segment) => (segment.geometry?.coordinates.length ?? 0) > 1,
  );
  if (segments.length === 0) {
    expect.soft(segments.length, "候補1の区間に形が無い").toBeGreaterThan(0);
  } else {
    await branch(
      page,
      "ルート線の区間を押す",
      async () => {
        // 区間の形の点のうち、いま地図そのものが押される（シート・部品に覆われていない）最初の点を押す。
        const coordinates = segments.flatMap((segment) => segment.geometry!.coordinates);
        const point = await page.evaluate((targets) => {
          const map = window.__liveMap();
          const canvas = map.getCanvas().getBoundingClientRect();
          for (const target of targets) {
            const { x, y } = map.project(target);
            const client = { x: canvas.left + x, y: canvas.top + y };
            if (document.elementFromPoint(client.x, client.y) !== map.getCanvas()) continue;
            const routeHits = map
              .queryRenderedFeatures([x, y])
              .filter((feature) => feature.source.includes("route")).length;
            return { ...client, routeHits };
          }
          return null;
        }, coordinates);
        expect(point, "区間のどの点も地図の上で押せない（部品に覆われている）").not.toBeNull();
        expect.soft(point!.routeHits, "押す点にルート線が描かれていない").toBeGreaterThan(0);
        const errorsBefore = watch.pageErrors.length;
        await page.mouse.click(point!.x, point!.y);
        await settleMap(page);
        expect.soft(watch.pageErrors.slice(errorsBefore), "区間を押したあとのページの例外").toEqual([]);
      },
      async () => {
        const opened = page.getByRole("dialog", { name: "ルート結果" });
        if (await opened.isVisible()) await page.getByRole("button", { name: "ルート結果", exact: true }).click();
        await expect(opened).toBeHidden();
      },
    );
  }

  // E: 公開軸のレンズを1つずつ選ぶ → ルートの区間のうち、その軸の値で塗られた（「データなし」でない）ものが1つ以上。
  // 区間ごとの値の有無は実データで変わるので、全区間が欠けたときだけ落とす。
  const originalLens = await currentLensLabel(page, catalog);
  for (const axis of catalog.axes) {
    await branch(
      page,
      `ルートをレンズ「${axis.label}」で塗る`,
      async () => {
        await chooseLens(page, axis.label);
        await settleMap(page);
        const { drawn, withValue } = await routeSegmentsPainted(page);
        expect.soft(drawn, `「${axis.label}」: ルートの区間が描かれていない`).toBeGreaterThan(0);
        expect.soft(withValue, `「${axis.label}」: ルートの区間が全部「データなし」`).toBeGreaterThan(0);
      },
      () => chooseLens(page, originalLens),
    );
  }

  expectNoOwnFailures(watch);
  reportExternal(watch, statsBefore, await externalErrors());
});
