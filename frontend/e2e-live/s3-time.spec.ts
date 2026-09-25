import { expect, test, type Page } from "@playwright/test";
import { mapDisplay } from "@/types/generated/mapDisplay";
import {
  allLayersOn,
  branch,
  chooseLens,
  expectNoOwnFailures,
  externalErrors,
  fetchCatalog,
  notApplicable,
  openLive,
  reportExternal,
  settleMap,
  type Watch,
} from "./live";

// S3 時刻で変わる入力。実行した時刻に任せず、欠陥の境界から代表点を選ぶ: 日本時間とUTCで日付が異なる時間帯
// （日本時間0〜8時台）と同じ時間帯の1点ずつ、気象庁のタイルは偶数ズームと奇数ズームの1段ずつ。
// 幹: 全レイヤーONで開き、時刻を入力に取る軸のレンズを選ぶ。枝: 下のC〜E→F。

/** 翌日の日本時間`hour`時（datetime-localの値）。予報の範囲に収まり、実行した時刻に左右されない。 */
function tomorrowJst(hour: number): string {
  const jst = new Date(Date.now() + 9 * 3600_000 + 24 * 3600_000);
  return `${jst.toISOString().slice(0, 10)}T${String(hour).padStart(2, "0")}:00`;
}

async function setDeparture(page: Page, value: string): Promise<void> {
  await page.getByRole("button", { name: /^出発時刻: / }).click();
  await page.getByLabel("出発日時を直接指定").fill(value);
  await page.keyboard.press("Escape");
  await expect(page.getByLabel("出発日時を直接指定")).toBeHidden();
}

/** PNGの画像のうち、透明でない画素を1つでも持つものの数（ページのcanvasで復号する）。 */
async function imagesWithData(page: Page, bodies: Buffer[]): Promise<number> {
  return page.evaluate(
    async (pngs) => {
      let count = 0;
      for (const png of pngs) {
        const bitmap = await createImageBitmap(await (await fetch(`data:image/png;base64,${png}`)).blob());
        const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
        const context = canvas.getContext("2d")!;
        context.drawImage(bitmap, 0, 0);
        const { data } = context.getImageData(0, 0, bitmap.width, bitmap.height);
        for (let i = 3; i < data.length; i += 4) {
          if (data[i] > 0) {
            count += 1;
            break;
          }
        }
      }
      return count;
    },
    bodies.map((body) => body.toString("base64")),
  );
}

/**
 * 気象庁のタイルを偶数・奇数の両方のタイルのズームで取らせる、地図のズームの組（2段続き）。地図のズームとタイルの
 * ズームはタイルの大きさで1段ずれうるので、2段続きで回し、取れたタイルはURLのズームで分ける。宣言
 * （`mapDisplay.weatherElements`のタイルのズーム範囲）のすべての配信元タイルが、どちらの段でも上限を超えた拡大で
 * 前の画像を使い回さずに取り直す組のうち最も細かいもの。
 */
function mapZoomsForBothParities(): [number, number] {
  const tiles = mapDisplay.weatherElements.flatMap((element) => (element.tile ? [element.tile] : []));
  const first = Math.min(...tiles.map((tile) => tile.maxZoom)) - 2;
  expect(first, "偶数・奇数の両方を取り直すズームが宣言の範囲に無い").toBeGreaterThanOrEqual(
    Math.max(...tiles.map((tile) => tile.minZoom)),
  );
  return [first, first + 1];
}

/** 気象庁のタイルを、配信系統（URLからz/x/yを除いたもの）ごとに、タイルのズームの偶奇で分けてまとめる。 */
function bySource(tiles: Watch["jmaTiles"]): Map<string, { even: Buffer[]; odd: Buffer[] }> {
  const groups = new Map<string, { even: Buffer[]; odd: Buffer[] }>();
  for (const { url, body } of tiles) {
    const match = /^(.*)\/(\d+)\/\d+\/\d+\.png$/.exec(new URL(url).pathname);
    if (!match) continue;
    const group = groups.get(match[1]) ?? { even: [], odd: [] };
    (Number(match[2]) % 2 === 0 ? group.even : group.odd).push(body);
    groups.set(match[1], group);
  }
  return groups;
}

test("S3 時刻で変わる入力", async ({ page }) => {
  const catalog = await fetchCatalog();
  const timed = catalog.axes.filter((axis) => axis.dedicated_way_value_layer && axis.dynamic_way_value_needs_time);
  const statsBefore = await externalErrors();
  const watch = await openLive(page, { storedState: allLayersOn() });
  // 地図のタイルをブラウザのキャッシュから出さず、ズームごとに取り直させる（取り直した応答の中身を見る）。
  const client = await page.context().newCDPSession(page);
  await client.send("Network.setCacheDisabled", { cacheDisabled: true });

  const msmHealthy = process.env.E2E_LIVE_MSM_HEALTHY === "1";
  if (timed.length === 0) notApplicable("時刻を入力に取る軸", "カタログに該当する公開軸が無い");
  for (const axis of timed) {
    await chooseLens(page, axis.label);
    await settleMap(page);
    await page.getByRole("button", { name: /^出発時刻: / }).click();
    const original = await page.getByLabel("出発日時を直接指定").inputValue();
    await page.keyboard.press("Escape");
    for (const [name, hour] of [
      ["C 日本時間の深夜（UTCと日付が異なる）", 3],
      ["D 日本時間の日中", 12],
    ] as const) {
      await branch(
        page,
        `「${axis.label}」${name}`,
        async () => {
          if (!msmHealthy) {
            notApplicable(`「${axis.label}」${name}`, "backendの予報（MSM）が古い");
            return;
          }
          const before = watch.wayValues.length;
          await setDeparture(page, tomorrowJst(hour));
          await settleMap(page);
          await expect
            .poll(() => watch.wayValues.slice(before).filter((entry) => entry.axisId === axis.axis_id).length, {
              timeout: 15_000,
            })
            .toBeGreaterThan(0);
          const values = watch.wayValues
            .slice(before)
            .filter((entry) => entry.axisId === axis.axis_id)
            .flatMap((entry) => Object.keys(entry.values));
          expect.soft(values.length, `「${axis.label}」${name}: 道ごとの値を1件も受け取っていない`).toBeGreaterThan(0);
        },
        () => setDeparture(page, original),
      );
    }
  }

  const originalZoom = await page.evaluate(() => window.__liveMap().getZoom());
  // E→F: 偶数ズームで「データあり」の配信系統は、1段拡大（奇数ズーム）して取り直した画像にもデータがある。
  await branch(
    page,
    "E→F 気象庁のタイルの偶数・奇数ズーム",
    async () => {
      // 地図の既定のズームは気象庁のタイルの上限より細かく、どの段でも同じ上限のタイルを使い回すので、宣言から選ぶ。
      const from = watch.jmaTiles.length;
      for (const z of mapZoomsForBothParities()) {
        await page.evaluate((target) => window.__liveMap().jumpTo({ zoom: target }), z);
        await settleMap(page);
      }
      let judged = 0;
      for (const [source, { even, odd }] of bySource(watch.jmaTiles.slice(from))) {
        if ((await imagesWithData(page, even)) === 0) continue;
        if (odd.length === 0) {
          notApplicable(source, "奇数ズームのタイルを取っていない（偶数ズームの画像を拡大して使っている）");
          continue;
        }
        judged += 1;
        expect.soft(await imagesWithData(page, odd), `${source}: 奇数ズームでデータが消える`).toBeGreaterThan(0);
      }
      if (judged === 0)
        notApplicable("偶数・奇数ズーム", "偶数ズームでデータのある気象庁の配信系統が無い（天候による）");
    },
    async () => {
      await page.evaluate((z) => window.__liveMap().jumpTo({ zoom: z }), originalZoom);
      await settleMap(page);
    },
  );

  expectNoOwnFailures(watch);
  reportExternal(watch, statsBefore, await externalErrors());
});
