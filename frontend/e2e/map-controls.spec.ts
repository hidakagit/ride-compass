import { expect, test, type Page } from "@playwright/test";
import { installApiMocks, openMobileApp, openMobileSheet, seedStoredState } from "./fixtures";
import { WIDTHS } from "./states";

// 地図の右の列（拡大・縮小から、現在地まで）のボタンが、ほかの部品の下に潜らず押せ、継ぎ目の間隔が揃うこと（パターン4 観点1）。
// 押す所の大きさ（24px四方）は全状態の走査が両方の幅で見るので、ここでは重なりと間隔だけを見る。どちらも実寸と重なりの順番で
// 決まり、単体テストでは見えない。押す点（中心）のヒットテストがボタン自身か子孫を返せば、上に何も重なっていない。
// 間隔は、方位のボタンから下の継ぎ目が全部 `--map-ctrl-stack-gap` であること（拡大・縮小・方位は MapLibre の1つの枠に
// 隙間なく並ぶので見ない）。ボタンを包む要素が行の箱の分だけ高くなると、その継ぎ目だけ広がる。

const RIGHT_COLUMN = /^(拡大|縮小|ドラッグで地図を回転|走行方位を設定|出発時刻|想定速度|現在地に移動)/;

type ColumnButton = { name: string; onTop: boolean; top: number; bottom: number };

/** 右の列のボタンの名前・押す点で最前面にあるか・上端と下端（上から順）。 */
async function rightColumnButtons(page: Page): Promise<ColumnButton[]> {
  const buttons = await page.getByRole("button", { name: RIGHT_COLUMN }).all();
  const measured = await Promise.all(
    buttons.map((button) =>
      button.evaluate((el) => {
        const box = el.getBoundingClientRect();
        const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
        return {
          name: el.getAttribute("aria-label") ?? "",
          onTop: hit !== null && el.contains(hit),
          top: box.top,
          bottom: box.bottom,
        };
      }),
    ),
  );
  return measured.sort((a, b) => a.top - b.top);
}

async function expectColumnSound(page: Page) {
  const column = await rightColumnButtons(page);
  // 現在地が列の末尾まで並んでいること（見つからない名前を素通りさせない）。
  expect(column.map(({ name }) => name)).toEqual(
    expect.arrayContaining(["拡大", "縮小", "走行方位を設定", "現在地に移動"]),
  );
  expect(column.at(-1)?.name).toBe("現在地に移動");
  expect(column.filter(({ onTop }) => !onTop)).toEqual([]);

  const stackGap = await page.evaluate(() =>
    parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--map-ctrl-stack-gap")),
  );
  expect(stackGap).toBeGreaterThan(0);
  const fromCompass = column.slice(column.findIndex(({ name }) => name.startsWith("ドラッグで地図を回転")));
  expect(fromCompass.length).toBeGreaterThan(4);
  const seams = fromCompass.slice(1).map((button, i) => ({
    seam: `${fromCompass[i].name} → ${button.name}`,
    gap: Math.round((button.top - fromCompass[i].bottom) * 10) / 10,
  }));
  expect(seams.filter(({ gap }) => Math.abs(gap - stackGap) > 0.5)).toEqual([]);
}

test("スマホ: ルート設定のシートを開いても、地図の右の列のボタンはほかの部品の下に潜らず、継ぎ目の間隔が揃う", async ({
  page,
}) => {
  await openMobileApp(page);
  await expect(page.getByText("地図を読み込み中…")).toBeHidden({ timeout: 15_000 });
  await openMobileSheet(page, "ルート設定");
  await expectColumnSound(page);
});

test("PC: 地図の右の列のボタンはほかの部品の下に潜らず、継ぎ目の間隔が揃う", async ({ page }) => {
  await installApiMocks(page);
  await page.setViewportSize(WIDTHS.desktop);
  await seedStoredState(page, { "ridecompass:first-visit-intro-closed": "true" });
  await page.goto("/");
  await expect(page.getByText("地図を読み込み中…")).toBeHidden({ timeout: 15_000 });
  await expectColumnSound(page);
});
