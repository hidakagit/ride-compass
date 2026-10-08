import { expect, test, type Page } from "@playwright/test";
import { installApiMocks, openMobileApp, openMobileSheet, seedStoredState } from "./fixtures";
import { WIDTHS } from "./states";

// 地図の右の列（拡大・縮小から、まとめて戻すまで）のボタンが、ほかの部品の下に潜らず押せること（パターン4 観点1）。
// 押す所の大きさ（24px四方）は全状態の走査が両方の幅で見るので、ここでは重なりだけを見る。重なりは実寸と重なりの順番で
// 決まり、単体テストでは見えない。押す点（中心）のヒットテストがボタン自身か子孫を返せば、上に何も重なっていない。

const RIGHT_COLUMN = /^(拡大|縮小|ドラッグで地図を回転|走行方位を設定|出発時刻|想定速度|現在地に移動|まとめて戻す)/;

/** 右の列のボタンの名前と、押す点で最前面にあるか。 */
async function rightColumnHits(page: Page): Promise<{ name: string; onTop: boolean }[]> {
  const buttons = await page.getByRole("button", { name: RIGHT_COLUMN }).all();
  return Promise.all(
    buttons.map((button) =>
      button.evaluate((el) => {
        const box = el.getBoundingClientRect();
        const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
        return { name: el.getAttribute("aria-label") ?? "", onTop: hit !== null && el.contains(hit) };
      }),
    ),
  );
}

function expectAllOnTop(hits: { name: string; onTop: boolean }[]) {
  // 現在地とまとめて戻すが列の末尾まで並んでいること（見つからない名前を素通りさせない）。
  expect(hits.map(({ name }) => name)).toEqual(
    expect.arrayContaining(["拡大", "縮小", "走行方位を設定", "現在地に移動", "まとめて戻す"]),
  );
  expect(hits.filter(({ onTop }) => !onTop)).toEqual([]);
}

test("スマホ: ルート設定のシートを開いても、地図の右の列のボタンはほかの部品の下に潜らない", async ({ page }) => {
  await openMobileApp(page);
  await expect(page.getByText("地図を読み込み中…")).toBeHidden({ timeout: 15_000 });
  await openMobileSheet(page, "ルート設定");
  expectAllOnTop(await rightColumnHits(page));
});

test("PC: 地図の右の列のボタンはほかの部品の下に潜らない", async ({ page }) => {
  await installApiMocks(page);
  await page.setViewportSize(WIDTHS.desktop);
  await seedStoredState(page, { "ridecompass:first-visit-intro-closed": "true" });
  await page.goto("/");
  await expect(page.getByText("地図を読み込み中…")).toBeHidden({ timeout: 15_000 });
  expectAllOnTop(await rightColumnHits(page));
});
