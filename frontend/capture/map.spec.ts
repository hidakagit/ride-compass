import { test, type Page, type Route } from "@playwright/test";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { mapDisplay } from "@/types/generated/mapDisplay";
import { chooseLens, openLive, settleMap } from "../e2e-live/live";

// 地図の画面を撮る段。入口は scripts/capture-map.mjs で、引数はそこが CAPTURE_OPTIONS に詰めて渡す。
// 起点は E2E_LIVE_POINT（e2e-live/live.ts: LIVE_POINT）、宛先は playwright.capture.config.ts が決める。

interface CaptureOptions {
  lenses: string[];
  layers: string[];
  out: string;
  viewport: { width: number; height: number };
  zoom: number | null;
  theme: "light" | "dark" | null;
  replace: { glob: string; file: string }[];
}

const options = JSON.parse(process.env.CAPTURE_OPTIONS ?? "null") as CaptureOptions;

/**
 * 応答を差し替える。本物の応答を取ってから本文だけを替えるので、CORS 等のヘッダーは本物のまま残る
 * （ヘッダーの無い応答で返すと、別オリジンの backend への取得としてブラウザが捨てる）。
 */
async function replace(route: Route, file: string): Promise<void> {
  const response = await route.fetch();
  if (file.endsWith(".json")) {
    await route.fulfill({ response, body: await readFile(file) });
    return;
  }
  const transform = (await import(pathToFileURL(file).href)).default as (json: unknown) => unknown;
  await route.fulfill({ response, json: await transform(await response.json()) });
}

/** 選べるレンズの名前。選び損ねた直後に呼ぶので、選択肢が閉じていれば開く。 */
async function lensLabels(page: Page): Promise<string[]> {
  const group = page.getByRole("radiogroup", { name: "地図の色分け" });
  if (!(await group.isVisible())) await page.getByRole("button", { name: /^地図の色分け: / }).click();
  const labels = await group.getByRole("radio").allInnerTexts();
  return labels.map((label) => label.replace(/\s+/g, " ").trim());
}

test("地図を撮る", async ({ page }) => {
  test.skip(!options, "CAPTURE_OPTIONS が無い（scripts/capture-map.mjs から起こす）");
  for (const { glob, file } of options.replace) await page.route(glob, (route) => replace(route, file));
  const layerIds: string[] = mapDisplay.layers.map(({ id }) => id);
  const unknown = options.layers.filter((id) => !layerIds.includes(id));
  if (unknown.length > 0) {
    throw new Error(`知らないレイヤー: ${unknown.join(" / ")}。選べるレイヤー: ${layerIds.join(" / ")}`);
  }
  if (options.theme) await page.emulateMedia({ colorScheme: options.theme });
  const visibility = JSON.stringify(Object.fromEntries(options.layers.map((id) => [id, true])));
  await openLive(page, { storedState: { "ridecompass:layer-visibility": visibility }, viewport: options.viewport });
  if (options.zoom !== null) {
    await page.evaluate((zoom) => window.__liveMap().jumpTo({ zoom }), options.zoom);
    await settleMap(page);
  }

  const shots = options.lenses.length > 0 ? options.lenses : [null];
  for (const [index, lens] of shots.entries()) {
    if (lens) {
      try {
        await chooseLens(page, lens);
      } catch (error) {
        throw new Error(`レンズ「${lens}」を選べない。選べるレンズ: ${(await lensLabels(page)).join(" / ")}`, {
          cause: error,
        });
      }
      await settleMap(page);
    }
    const name = `${index + 1}-${(lens ?? "地図").replace(/[\\/:*?"<>|\s]+/g, "_")}.png`;
    const file = path.join(options.out, name);
    await page.screenshot({ path: file });
    console.log(`[capture] ${file}`);
  }
});
