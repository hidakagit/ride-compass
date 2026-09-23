import { expect, type Page, type Response } from "@playwright/test";
import { VectorTile } from "@mapbox/vector-tile";
import { PbfReader } from "pbf";
import { mapDisplay } from "@/types/generated/mapDisplay";
import regionTileConfig from "@/types/generated/region-tile-config.json";
import { installPageHelpers } from "../e2e/states";

// 実backend・開発DBへ向けて回すe2eの共通の段取りと観測（docs/conventions/testing.md パターン4「走らせ方」）。
// 期待値は値そのものではなく性質（1件以上ある・2つの出どころが食い違わない・エラー0件）で書く。

/** 手元のbackend。アプリのビルドが埋め込む向け先（`NEXT_PUBLIC_API_URL`の既定）と同じ。 */
export const LIVE_API = process.env.E2E_LIVE_API ?? "http://localhost:8000";

/** 起点。開発DBの取込範囲はリポジトリに記録が無いので、範囲から推測せず環境変数で与える。既定はアプリの既定地点。 */
export const LIVE_POINT = (() => {
  const [latitude, longitude] = (process.env.E2E_LIVE_POINT ?? "35.7597,139.7387").split(",").map(Number);
  return { latitude, longitude };
})();

export const LIVE_VIEWPORT = { width: 390, height: 812 };

export interface CatalogAxis {
  axis_id: string;
  label: string;
  display: { kind: string; tile_inputs: { property: string }[] };
  dedicated_way_value_layer: boolean;
  dynamic_way_value_needs_time: boolean;
}

export interface Catalog {
  axes: CatalogAxis[];
  tile_versions: Record<string, string>;
}

export async function fetchCatalog(): Promise<Catalog> {
  const response = await fetch(`${LIVE_API}/api/axis-catalog`);
  if (!response.ok) throw new Error(`軸カタログの取得に失敗: ${response.status}`);
  return (await response.json()) as Catalog;
}

export function tileOf(z: number, { latitude, longitude }: { latitude: number; longitude: number }) {
  const n = 2 ** z;
  const x = Math.floor(((longitude + 180) / 360) * n);
  const rad = (latitude * Math.PI) / 180;
  const y = Math.floor(((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * n);
  return { z, x, y };
}

/** 路面タイル（MVT）の地物ごとのプロパティ。 */
export function decodeRoadTile(body: Buffer): Record<string, unknown>[] {
  const tile = new VectorTile(new PbfReader(body));
  const layer = tile.layers[regionTileConfig.road_surface.layer_name];
  if (!layer) return [];
  return Array.from({ length: layer.length }, (_, i) => layer.feature(i).properties);
}

/** ページで起きた失敗の記録。`[map:error]`は取得の失敗（sourceIdを持つもの）も含めて数える。 */
export interface Watch {
  mapErrors: string[];
  pageErrors: string[];
  /** アプリがbackendから受け取った、backend自前の処理の失敗（429と、502・503・504以外の5xx、本文を解釈できない応答）。 */
  backendFailures: string[];
  /** backendが上流（外部の配信元・キャッシュ）の失敗として返した502・503・504（HTTPの定義で上流の失敗を表す）。合否に入れない。 */
  gatewayFailures: string[];
  roadTiles: Map<string, Record<string, unknown>[]>;
  wayValues: { axisId: string; url: string; values: Record<string, number> }[];
  jmaTiles: { url: string; body: Buffer }[];
  generated: { routes: unknown[]; no_candidates_reason: string | null }[];
}

const ROAD_TILE = /\/api\/region\/road-surface-tiles\/(\d+)\/(\d+)\/(\d+)\.pbf/;
const WAY_VALUES = /\/api\/region\/dynamic-way-values\/([^/]+)\//;

async function record(watch: Watch, response: Response): Promise<void> {
  const url = response.url();
  const isBackend = url.startsWith(LIVE_API) || /\/api\//.test(new URL(url).pathname);
  const status = response.status();
  if (isBackend && [502, 503, 504].includes(status)) watch.gatewayFailures.push(`${status} ${url}`);
  else if (isBackend && (status >= 500 || status === 429)) watch.backendFailures.push(`${status} ${url}`);
  if (!response.ok()) return;
  const road = ROAD_TILE.exec(url);
  const wayValues = WAY_VALUES.exec(url);
  const isJmaTile = url.includes("/api/jma-tile/") && url.endsWith(".png");
  const isGeneration = url.includes("/api/routes/generate/");
  if (!road && !wayValues && !isJmaTile && !isGeneration) return;
  let body: Buffer;
  try {
    body = await response.body();
  } catch {
    // ページを離れた後に本文を読もうとした応答は数えない（本文が無いことは失敗の記録に入らない）。
    return;
  }
  try {
    if (road) watch.roadTiles.set(`${road[1]}/${road[2]}/${road[3]}`, decodeRoadTile(body));
    else if (wayValues) watch.wayValues.push({ axisId: wayValues[1], url, values: JSON.parse(body.toString("utf-8")) });
    else if (isJmaTile) watch.jmaTiles.push({ url, body });
    else {
      const job = JSON.parse(body.toString("utf-8"));
      if (job.status === "done" && job.result) watch.generated.push(job.result);
    }
  } catch (error) {
    watch.backendFailures.push(`本文を解釈できない ${url}: ${String(error)}`);
  }
}

/**
 * 実backendへ向けてモバイル幅でアプリを開き、地図の読み込みが終わるまで待つ。
 * 起点はブラウザの現在地として、レイヤーのON/OFF等は保存状態として与える（利用者の操作を真似ない）。
 */
export async function openLive(page: Page, { storedState = {} }: { storedState?: Record<string, string> } = {}) {
  const watch: Watch = {
    mapErrors: [],
    pageErrors: [],
    backendFailures: [],
    gatewayFailures: [],
    roadTiles: new Map(),
    wayValues: [],
    jmaTiles: [],
    generated: [],
  };
  page.on("console", (message) => {
    if (message.text().includes("[map:error]")) watch.mapErrors.push(message.text());
  });
  page.on("pageerror", (error) => watch.pageErrors.push(String(error)));
  page.on("response", (response) => void record(watch, response));

  await page.context().grantPermissions(["geolocation"]);
  await page.context().setGeolocation(LIVE_POINT);
  await page.setViewportSize(LIVE_VIEWPORT);
  await page.addInitScript(installPageHelpers);
  await page.addInitScript(installMapFinder);
  await page.addInitScript((items) => {
    for (const [key, value] of Object.entries(items)) window.localStorage.setItem(key, value);
  }, storedState);

  await page.goto("/");
  await expect(page.getByRole("button", { name: "メニュー" })).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("地図を読み込み中…")).toBeHidden({ timeout: 60_000 });
  await settleMap(page);
  return watch;
}

/** 全レイヤーONとデバッグログ（`[map:error]`を読むため）の保存状態。出どころは`map-runtime.spec.ts`と同じ宣言。 */
export function allLayersOn(): Record<string, string> {
  return {
    "ridecompass:debug-enabled": "1",
    "ridecompass:layer-visibility": JSON.stringify(Object.fromEntries(mapDisplay.layerIds.map((id) => [id, true]))),
  };
}

declare global {
  interface Window {
    __liveMap(): import("maplibre-gl").Map;
  }
}

/**
 * 地図のインスタンスを、描画しているReactの部品の参照（useRef）から探す関数をページへ入れる。
 * アプリは地図を外へ公開していないので、テストのために入口を足さず、Reactが要素へ付ける内部の印（`__reactFiber$`）から
 * 祖先の部品のフックを辿る。Reactの内部の形が変わると見つからず、そのときは例外で止まる（黙って空を返さない）。
 */
function installMapFinder(): void {
  window.__liveMap = () => {
    const container = document.querySelector(".maplibregl-map");
    const key = container && Object.keys(container).find((k) => k.startsWith("__reactFiber$"));
    type Hook = { memoizedState: unknown; next: Hook | null };
    type Fiber = { memoizedState: unknown; return: Fiber | null };
    let fiber = key ? ((container as unknown as Record<string, Fiber>)[key] ?? null) : null;
    for (; fiber; fiber = fiber.return) {
      let hook = fiber.memoizedState as Hook | null;
      while (hook && typeof hook === "object" && "next" in hook) {
        const state = hook.memoizedState as { current?: { queryRenderedFeatures?: unknown } } | null;
        if (state && typeof state === "object" && typeof state.current?.queryRenderedFeatures === "function") {
          return state.current as unknown as import("maplibre-gl").Map;
        }
        hook = hook.next;
      }
    }
    throw new Error("地図のインスタンスが見つからない（Reactの内部の形が変わった可能性）");
  };
}

/**
 * 地図の全ソースのタイルが読み終わるまで待つ。MapLibreの`idle`は、動き続けるレイヤー（時刻で進む気象の表示等）が
 * あると来ないので使わない。読み終わらないソースは名前を出して落とす。
 */
export async function settleMap(page: Page): Promise<void> {
  const pending = await page.evaluate(async () => {
    const map = window.__liveMap();
    const unloaded = () => Object.keys(map.getStyle().sources).filter((id) => !map.isSourceLoaded(id));
    const deadline = performance.now() + 45_000;
    let streak = 0;
    while (performance.now() < deadline) {
      streak = unloaded().length === 0 ? streak + 1 : 0;
      if (streak >= 3) return [];
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
    return unloaded();
  });
  expect(pending, "45秒たっても読み終わらない地図のソース").toEqual([]);
  await page.evaluate(() => window.__e2e.settle());
}

/** 路面タイルのソースのid（スタイルのうち、タイルのURLが路面タイルの経路を指すもの）。 */
export async function roadSourceId(page: Page): Promise<string> {
  const id = await page.evaluate(() => {
    const sources = window.__liveMap().getStyle().sources;
    return (
      Object.entries(sources).find(([, source]) =>
        ((source as { tiles?: string[] }).tiles ?? []).some((url) => url.includes("/road-surface-tiles/")),
      )?.[0] ?? null
    );
  });
  expect(id, "路面タイルのソースがスタイルに無い").not.toBeNull();
  return id!;
}

/** いま描かれている路面の地物のプロパティ（画面に出ている範囲）。 */
export async function renderedRoads(page: Page, sourceId: string): Promise<Record<string, unknown>[]> {
  return page.evaluate(
    (source) =>
      window
        .__liveMap()
        .queryRenderedFeatures()
        .filter((feature) => feature.source === source)
        .map((feature) => feature.properties),
    sourceId,
  );
}

/**
 * 幹の終点から枝を1本見て、元へ戻す。戻せたかはT1078と同じ指紋（開閉の値と倍率）で確かめ、戻らなければ違反として落とす。
 * 枝の失敗（`expect.soft`）は他の枝を止めない。
 */
export async function branch(page: Page, name: string, body: () => Promise<void>, restore: () => Promise<void>) {
  const before = (await page.evaluate(() => window.__e2e.settle())).fp;
  const started = Date.now();
  try {
    await body();
  } catch (error) {
    expect.soft(String(error), `枝「${name}」が例外で止まった`).toBe("");
  }
  await restore();
  const after = (await page.evaluate(() => window.__e2e.settle())).fp;
  console.log(`[e2e-live] 枝「${name}」 ${((Date.now() - started) / 1000).toFixed(1)}秒`);
  expect(after, `枝「${name}」のあと元の状態へ戻らない`).toBe(before);
}

/** 前提が成り立たず判定しなかった枝を、黙って緑にせずログへ出す。 */
export function notApplicable(name: string, reason: string): void {
  console.log(`[e2e-live] 該当なし: ${name}（${reason}）`);
}

/** 後始末の検査: backendの外部呼び出しのカテゴリごとのエラーの増え方。合否には入れず「外部要因」として必ず出す。 */
export async function externalErrors(): Promise<Record<string, number>> {
  const stats = (await (await fetch(`${LIVE_API}/api/debug/stats`)).json()) as {
    external: Record<string, { errors: number }>;
  };
  return Object.fromEntries(Object.entries(stats.external).map(([category, s]) => [category, s.errors]));
}

export function reportExternal(watch: Watch, before: Record<string, number>, after: Record<string, number>): void {
  if (watch.gatewayFailures.length > 0) {
    console.log(
      `[e2e-live] 外部要因（backendが上流の失敗として返した応答。合否に入れない）: ${watch.gatewayFailures.join(", ")}`,
    );
  }
  const grown = Object.entries(after)
    .map(([category, errors]) => [category, errors - (before[category] ?? 0)] as const)
    .filter(([, delta]) => delta > 0);
  console.log(
    grown.length === 0
      ? "[e2e-live] 外部要因: なし"
      : `[e2e-live] 外部要因（backendの外部呼び出しのエラーの増分。合否に入れない）: ${grown.map(([c, d]) => `${c} +${d}`).join(", ")}`,
  );
}

/** 幹の最後に見る、自前の失敗の不在（ページの例外・backendの5xx/429・解釈できない本文）。 */
export function expectNoOwnFailures(watch: Watch): void {
  expect.soft(watch.pageErrors, "ページの例外").toEqual([]);
  expect
    .soft(watch.backendFailures, "backend自前の失敗（429と、502・503・504以外の5xx、本文を解釈できない応答）")
    .toEqual([]);
}

/** レンズを選ぶ（ピルを押して選択肢を押す。選ぶとポップオーバーは閉じる）。選択肢の名前には「未使用」等の印が続くので、ラベルの要素で当てる。 */
export async function chooseLens(page: Page, label: string): Promise<void> {
  await page.getByRole("button", { name: /^レンズ: / }).click();
  const group = page.getByRole("radiogroup", { name: "レンズ" });
  await group
    .getByRole("radio")
    .filter({ has: page.getByText(label, { exact: true }) })
    .click();
  await expect(group).toBeHidden();
}

export async function currentLensLabel(page: Page): Promise<string> {
  const name = await page.getByRole("button", { name: /^レンズ: / }).getAttribute("aria-label");
  return /^レンズ: (.*)（タップで変更）$/.exec(name ?? "")?.[1] ?? "";
}
