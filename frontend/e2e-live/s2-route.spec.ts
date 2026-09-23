import { expect, test } from "@playwright/test";
import { openMobileSheet } from "../e2e/fixtures";
import { branch, expectNoOwnFailures, externalErrors, openLive, reportExternal, settleMap } from "./live";

// S2 ルート生成（生成後）。実グラフでしか出ない探索の欠陥（並行する道・取込範囲の端で生成が落ちる）と、
// 実データの区間を押したときの例外、実際の軸名での比較表の横はみ出しを見る。
// 幹: S1と同じ地点で開き、距離を指定して生成を1回。枝: 下のC〜E→F。

interface Segment {
  geometry: { coordinates: [number, number][] } | null;
}

test("S2 ルート生成（生成後）", async ({ page }) => {
  const statsBefore = await externalErrors();
  // 比較タブは研究モードで、生成を2回したときに出る。
  const watch = await openLive(page, {
    storedState: { "ridecompass:debug-enabled": "1", "ridecompass:research-enabled": "1" },
  });

  const settings = await openMobileSheet(page, "ルート設定");
  for (const distanceKm of [15, 16]) {
    await settings.getByLabel("距離").fill(String(distanceKm));
    const started = Date.now();
    await settings.getByRole("button", { name: "ルート生成" }).click();
    // 冷えたキャッシュでの初回の生成は、タイル材料の読み出しで数十秒以上かかる。
    await expect(settings.getByRole("button", { name: "ルート生成" })).toBeEnabled({ timeout: 240_000 });
    console.log(`[e2e-live] 生成（${distanceKm}km） ${((Date.now() - started) / 1000).toFixed(1)}秒`);
  }
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

  // E→F: 比較タブを開く → 実際の軸名の行見出しでページもシートも横にはみ出さない。
  await branch(
    page,
    "比較タブ",
    async () => {
      const sheet = await openMobileSheet(page, "ルート結果");
      await sheet.getByRole("tab", { name: "比較" }).click();
      await expect(sheet.getByRole("tab", { name: "比較" })).toHaveAttribute("aria-selected", "true");
      await page.evaluate(() => window.__e2e.settle());
      const widths = await page.evaluate(() => {
        const dialog = [...document.querySelectorAll('[role="dialog"]')].find(
          (el) => el.getAttribute("aria-label") === "ルート結果" || el.textContent?.includes("比較"),
        );
        return {
          page: document.scrollingElement!.scrollWidth,
          viewport: window.innerWidth,
          sheet: dialog ? dialog.scrollWidth - dialog.clientWidth : 0,
        };
      });
      expect.soft(widths.page, "比較タブでページが横にスクロールする").toBeLessThanOrEqual(widths.viewport + 1);
      expect.soft(widths.sheet, "比較タブでシートの中身が横にはみ出す").toBeLessThanOrEqual(1);
    },
    async () => {
      const sheet = page.getByRole("dialog", { name: "ルート結果" });
      const tabs = sheet.getByRole("tab");
      if ((await tabs.count()) > 0) await tabs.first().click();
      await page.getByRole("button", { name: "ルート結果", exact: true }).click();
      await expect(sheet).toBeHidden();
    },
  );

  expectNoOwnFailures(watch);
  reportExternal(watch, statsBefore, await externalErrors());
});
