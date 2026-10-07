import { expect, test } from "@playwright/test";
import { catalogEntry, tileInput } from "@/testing/catalogAxes";
import {
  MOBILE_VIEWPORT,
  axisCatalogFixture,
  doneJobFixture,
  generateRoutes,
  openMobileApp,
  routeGenerateResponseFixture,
} from "./fixtures";

// モバイル（390px）で、要素が幅に収まり押せること（パターン4 観点1）。要素は画面外へ
// 出てもアクセシビリティツリーに残るため、役割・名前では捕まらない。幅と座標を実測する。

test("モバイル: 観測値の取得に失敗してもヘッダーが幅に収まり、メニューが押せる", async ({ page }) => {
  await openMobileApp(page, {
    routes: (page) =>
      page.route("**/api/weather/amedas*", (route) =>
        route.fulfill({ status: 503, json: { detail: "アメダス観測値の取得に失敗しました" } }),
      ),
  });

  // 一般画面にはリクエストIDを含む長い文言を出さない。
  await expect(page.getByText("観測値を取得できません")).toBeVisible();
  await expect(page.getByText(/\[req:/)).toHaveCount(0);

  const header = page.locator("header").first();
  const size = await header.evaluate((el) => ({ scrollWidth: el.scrollWidth, clientWidth: el.clientWidth }));
  expect(size.scrollWidth).toBeLessThanOrEqual(size.clientWidth);

  const menu = await page.getByRole("button", { name: "メニュー" }).boundingBox();
  expect(menu).not.toBeNull();
  expect((menu?.x ?? 0) + (menu?.width ?? 0)).toBeLessThanOrEqual(MOBILE_VIEWPORT.width);
});

/** 段階が細かく、凡例の1行（「とても少ない（0.125〜0.375箇所/km）」）が長くなる軸。
 * 本番の軸名・値は使わない。 */
const FINE_STEP_AXIS_LABEL = "段階の細かい軸";

// レンズの凡例は段階の細かい軸ほど1行が長い。グリッドのセルに収まらないと、値の右側が読めなくなる。
test("モバイル: レンズの凡例が、段階の細かい軸でも幅に収まる", async ({ page }) => {
  await openMobileApp(page, {
    routes: (page) =>
      page.route("**/api/axis-catalog*", (route) =>
        route.fulfill({
          json: axisCatalogFixture([
            {
              ...catalogEntry({
                axis_id: "fine_steps",
                label: FINE_STEP_AXIS_LABEL,
                raw_value_unit: "箇所/km",
                display_band_labels_override: [
                  "ほとんど無い",
                  "とても少ない",
                  "かなり少ない",
                  "やや少ない",
                  "ふつう",
                  "やや多い",
                  "かなり多い",
                  "とても多い",
                  "非常に多い",
                ],
                display: {
                  kind: "ramp",
                  tile_inputs: [tileInput({ property: "v", weight: 1 })],
                  thresholds: [0.125, 0.375, 0.625, 0.875, 1.125, 1.375, 1.625, 1.875],
                },
              }),
              default_weight: 0,
            },
          ]),
        }),
      ),
  });

  await page.getByRole("button", { name: /^地図の色分け:/ }).click();
  await page.getByRole("radio", { name: FINE_STEP_AXIS_LABEL }).click();
  await page.getByRole("button", { name: /^地図の色分け:/ }).click();
  await expect(page.getByLabel("凡例の全段階をまとめて表示/非表示")).toBeVisible();

  const rows = await page.evaluate(() => {
    const header = [...document.querySelectorAll("label")].find((el) => el.textContent?.trim() === "凡例");
    const list = header?.parentElement?.lastElementChild;
    return [...((list?.children ?? []) as HTMLCollectionOf<HTMLElement>)].map((row) => ({
      label: row.textContent?.trim() ?? "",
      overflowPx: row.scrollWidth - row.clientWidth,
      beyondViewportPx: Math.round(row.getBoundingClientRect().right - window.innerWidth),
    }));
  });

  expect(rows.length).toBeGreaterThan(0);
  expect(rows.filter((row) => row.overflowPx > 0 || row.beyondViewportPx > 0)).toEqual([]);
});

/** 候補0件の理由。1行に収まらない長さにして、折り返した全体が見えるかを見る（本番の文は使わない）。 */
const LONG_NO_CANDIDATES_REASON =
  "出発地の近くに、条件に合う道路がありませんでした。距離を変えるか、除外した道路の種類を減らしてから試してください。";

// 押した「生成」の結果の1行は、「ルート設定」の本文をどこまで送っていても、▷を押したその場で読める所に出る。
// 本文の中に置くと、送った分だけ画面の外へ出てもアクセシビリティツリーには残るので、座標で見る。
test("モバイル: 候補0件の理由が、「ルート設定」の本文を下へ送っても見出しの下で幅に収まって見える", async ({
  page,
}) => {
  await openMobileApp(page, {
    // 本文が箱に収まらず送れる高さ（いちばん低いシート）にする（高さを決めていないと中身に合わせて伸びる）。
    storedState: { "ridecompass:mobile-sheet-height-vh": "20" },
    routes: (page) =>
      page.route("**/api/routes/generate/*", (route) =>
        route.fulfill({
          json: doneJobFixture({
            ...routeGenerateResponseFixture(),
            routes: [],
            no_candidates_reason: LONG_NO_CANDIDATES_REASON,
          }),
        }),
      ),
  });
  const sheet = await generateRoutes(page);
  const note = sheet.getByText(LONG_NO_CANDIDATES_REASON);
  await expect(note).toBeVisible();

  // 本文（スクロールする箱）を一番下まで送る。
  const scrolled = await sheet.evaluate((dialog) => {
    const body = [...dialog.querySelectorAll<HTMLElement>("*")].find(
      (el) => getComputedStyle(el).overflowY === "auto" && el.scrollHeight > el.clientHeight,
    );
    if (!body) return false;
    body.scrollTop = body.scrollHeight;
    return true;
  });
  expect(scrolled).toBe(true);

  const placement = await note.evaluate((el) => {
    const box = el.getBoundingClientRect();
    const dialogBox = el.closest('[role="dialog"]')?.getBoundingClientRect();
    const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
    return {
      insideSheet: dialogBox !== undefined && box.top >= dialogBox.top && box.bottom <= dialogBox.bottom,
      withinWidth: box.left >= 0 && box.right <= window.innerWidth && el.scrollWidth <= el.clientWidth,
      onTop: hit !== null && el.contains(hit),
    };
  });
  expect(placement).toEqual({ insideSheet: true, withinWidth: true, onTop: true });
});
