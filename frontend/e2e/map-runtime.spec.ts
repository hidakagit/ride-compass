import { expect, test, type CDPSession, type Page } from "@playwright/test";
import { MOBILE_VIEWPORT, installApiMocks, openMobileApp, openMobileSheet } from "./fixtures";

// 地図（MapLibre）が実ブラウザでしか見せない挙動（パターン4 観点2）。単体テストの代役地図は
// Worker・描画・スタイル検証・`idle`・canvasへの実クリックを持たないため、ここでしか確かめられない。

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

// 初期表示の覆い（「地図を読み込み中…」）はMapLibreの"idle"で外すが、idleは表示中の
// すべての取得が落ち着くまで来ない。取得が終わらないソースが1つでもあると、地図が
// 描けていても覆いが残り「壊れている」ように見える。
test("タイル取得が終わらなくても地図の覆いは外れる", async ({ page }) => {
  await installApiMocks(page);
  await page.route("**/api/basemap/**", (route) =>
    route.fulfill({
      json: {
        version: 8,
        sources: { slow: { type: "raster", tiles: ["https://slow.invalid/{z}/{x}/{y}.png"], tileSize: 256 } },
        layers: [{ id: "slow", type: "raster", source: "slow" }],
      },
    }),
  );
  // 応答しない（fulfillもabortもしない）ことで取得を宙吊りにする。
  await page.route("https://slow.invalid/**", () => {});

  await page.goto("/");

  const overlay = page.getByText("地図を読み込み中…");
  await expect(overlay).toBeVisible({ timeout: 5000 });
  await expect(overlay).toBeHidden({ timeout: 12_000 });
});

// 生成に関わる操作は「ルート生成」ボタンがある場所でだけ受け付ける。ルート結果で候補線を
// 選ぼうとして外すたびに経由地が増えるのを防ぐ。canvasへの実クリックがMapLibreの
// clickとして届いた上で、受け付けるかどうかが画面の状態で分かれることを見る。
test("モバイル: ルート結果を見ている間は地図タップでピンが置かれない", async ({ page }) => {
  await openMobileApp(page);

  const settings = await openMobileSheet(page, "ルート設定");
  await settings.getByRole("button", { name: "目的地", exact: true }).click();
  await page.locator(".app-map-pane canvas").click({ position: { x: 180, y: 150 } });
  await expect(settings.getByRole("button", { name: "目的地を置き直す" })).toBeVisible();

  // 経由地を置ける状態にしてから「ルート結果」へ移る。結果を見ている間は、置ける状態の
  // ままでも地図のタップでピンが増えない。
  await settings.getByRole("button", { name: "経由地を追加" }).click();
  await openMobileSheet(page, "ルート結果");
  await page.locator(".app-map-pane canvas").click({ position: { x: 220, y: 200 } });
  await page.waitForTimeout(400);

  // 戻ってきても「置ける状態」は保たれている（離れている間だけ置けない）。経由地が増えて
  // いないことは、件数>0のときだけ出るクリアボタンが無いことで見る。
  const settingsAgain = await openMobileSheet(page, "ルート設定");
  await expect(settingsAgain.getByRole("button", { name: "経由地の指定をやめる" })).toBeVisible();
  await expect(settingsAgain.getByRole("button", { name: "経由地をクリア" })).toHaveCount(0);
  await page.locator(".app-map-pane canvas").click({ position: { x: 240, y: 220 } });
  await expect(settingsAgain.getByRole("button", { name: "経由地をクリア" })).toBeVisible({ timeout: 5000 });
});

/** 2本の指を(x, y)の左右に置き、外へ開く。Input.synthesizePinchGestureはページの拡大を再現しない
 * （docs/conventions/testing.md パターン4）。 */
async function pinchOpen(client: CDPSession, x: number, y: number): Promise<void> {
  const fingers = (spread: number) => [
    { x: x - 2 - spread, y, id: 1 },
    { x: x + 2 + spread, y, id: 2 },
  ];
  await client.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: fingers(0) });
  for (let step = 1; step <= 12; step += 1) {
    await client.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: fingers(step * 8) });
  }
  await client.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
}

// ページの拡大が許されている（viewportにmaximum-scaleを置かない）ため、地図の上に重なる部品が
// touch-action: noneを持たないと、そこから始まったピンチをブラウザがページ全体の拡大として扱う
// （パターン4 観点2）。touch-actionはタッチの始点の要素と祖先で決まり、計算後のCSSの値を
// 読むだけでは効いているかが分からないので、実際に2本指のタッチを送って見る。
test.describe("タッチ端末", () => {
  test.use({ viewport: MOBILE_VIEWPORT, isMobile: true, hasTouch: true });

  // 母集団は、地図の範囲を格子で走査して最前面に当たった、地図のcanvas以外の部品全部。
  test("地図の上に重なる部品から始めたピンチは、ページ全体の拡大にならない", async ({ page }) => {
    // 部品ごとに2本指の操作を送るため、既定の30秒では足りない。
    test.setTimeout(180_000);
    await openMobileApp(page);
    await expect(page.getByText("地図を読み込み中…")).toBeHidden({ timeout: 15_000 });

    const targets = await page.evaluate(() => {
      const pane = document.querySelector(".app-map-pane")?.getBoundingClientRect();
      const canvas = document.querySelector("canvas.maplibregl-canvas");
      // 部品（押せる要素）ごとに1点。部品の中の子要素は、その部品と同じtouch-actionの祖先を持つ。
      const found = new Map<Element, { x: number; y: number; label: string }>();
      if (!pane) return [];
      for (let y = pane.top + 4; y < Math.min(pane.bottom, window.innerHeight); y += 8) {
        for (let x = pane.left + 4; x < Math.min(pane.right, window.innerWidth); x += 8) {
          const element = document.elementFromPoint(x, y);
          if (!element || element === canvas) continue;
          const owner = element.closest("button, a, [role], label, input") ?? element;
          if (found.has(owner)) continue;
          const box = owner.getBoundingClientRect();
          const center = { x: box.left + box.width / 2, y: box.top + box.height / 2 };
          const hit = document.elementFromPoint(center.x, center.y);
          const point = hit && owner.contains(hit) ? center : { x, y };
          const name = owner.getAttribute("aria-label") ?? owner.textContent?.trim().slice(0, 16) ?? "";
          found.set(owner, {
            ...point,
            label: `${element.tagName.toLowerCase()} in ${owner.tagName.toLowerCase()} "${name}"`,
          });
        }
      }
      return [...found.values()];
    });
    expect(targets.length).toBeGreaterThan(0);

    const client = await page.context().newCDPSession(page);
    const zoomedFrom: string[] = [];
    for (const target of targets) {
      await pinchOpen(client, target.x, target.y);
      await page.waitForTimeout(200);
      const scale = await page.evaluate(() => window.visualViewport?.scale ?? 1);
      if (scale !== 1) {
        zoomedFrom.push(`${target.label} (${Math.round(target.x)},${Math.round(target.y)}) → ×${scale.toFixed(2)}`);
        // 拡大されたままだと次の部品の座標がずれるので、倍率を戻す。戻らなければ残りは測れない。
        await client.send("Emulation.setPageScaleFactor", { pageScaleFactor: 1 });
        await page.waitForTimeout(200);
        const restored = await page.evaluate(() => window.visualViewport?.scale ?? 1);
        if (restored !== 1) {
          zoomedFrom.push(`（倍率を戻せないため、残り${targets.length - targets.indexOf(target) - 1}件は未検査）`);
          break;
        }
      }
    }
    expect(zoomedFrom).toEqual([]);
  });

  // 上の検査は部品の上のピンチを止めるだけなので、地図そのもののピンチが地図の拡大として
  // 届き続けていることを併せて見る。地図のズームはデバッグログの"zoomend"で読む。
  test("地図の上で始めたピンチは、ページではなく地図を拡大する", async ({ page }) => {
    const zoomEnds: string[] = [];
    page.on("console", (message) => {
      if (message.text().includes("[map:viewport] zoomend")) zoomEnds.push(message.text());
    });
    await openMobileApp(page, { storedState: { "ridecompass:debug-enabled": "1" } });
    await expect(page.getByText("地図を読み込み中…")).toBeHidden({ timeout: 15_000 });

    const point = await page.evaluate(() => {
      const canvas = document.querySelector("canvas.maplibregl-canvas");
      const box = canvas?.getBoundingClientRect();
      if (!canvas || !box) return null;
      // 指を左右に60pxずつ開くので、その幅がcanvasの上に収まる点を中央から探す。
      for (let dy = 0; dy < box.height / 2; dy += 8) {
        for (const y of [box.top + box.height / 2 + dy, box.top + box.height / 2 - dy]) {
          const x = box.left + box.width / 2;
          if ([-80, 0, 80].every((dx) => document.elementFromPoint(x + dx, y) === canvas)) return { x, y };
        }
      }
      return null;
    });
    expect(point).not.toBeNull();

    const client = await page.context().newCDPSession(page);
    await pinchOpen(client, point!.x, point!.y);
    await expect.poll(() => zoomEnds.length, { timeout: 5000 }).toBeGreaterThan(0);
    expect(await page.evaluate(() => window.visualViewport?.scale ?? 1)).toBe(1);
  });
});
