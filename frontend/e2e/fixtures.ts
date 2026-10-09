import { expect, type Locator, type Page } from "@playwright/test";
import type { components } from "@/types/generated/api";
import type { RouteCandidate, RouteGenerateJobStatusResponse } from "@/types/route";
import { catalogEntry, catalogResponse, tileInput } from "@/testing/catalogAxes";
import {
  makeGenerationConditions,
  makeRouteCandidate as makeCandidate,
  makeRouteSegment,
} from "@/testing/routeFixtures";
import type {
  AmedasObservation,
  FloodForecasts,
  WbgtStatus,
  WeatherConditions,
  WeatherWarnings,
} from "@/types/weather";
import regionTileConfig from "@/types/generated/region-tile-config.json";
import nextConfig from "../next.config";

// CIのE2Eスモークテストは「実バックエンド＋実外部API（
// OpenFreeMap）」には依存しない。APIコントラクトの正しさはCIのapi-contractジョブ
// （OpenAPIドリフト検知）が別途担保しており、E2Eはフロントの画面挙動（生成→表示、
// レイヤー切替）だけを決定的に検証する。バックエンドプロセスの起動・DB・APIキーが
// 不要になるぶん、CIが速く安定する。

const API_BASE = "http://localhost:8000";

// backend/app/domain/route.py RouteCandidate相当の最小フィクスチャ（1候補）。
function makeSegment(index: number, coordinates: [number, number][]) {
  return makeRouteSegment({
    geometry: { type: "LineString", coordinates },
    start_latitude: coordinates[0][1],
    start_longitude: coordinates[0][0],
    end_latitude: coordinates[coordinates.length - 1][1],
    end_longitude: coordinates[coordinates.length - 1][0],
    cumulative_distance_km: index * 10,
    distance_km: 10,
    difficulty: 20 + index * 30,
  });
}

// geometryは往復可能な閉じたループの体裁のみ整える（実座標としての精度は問わない）。
// 所要時間は本物の生成が必ず付ける（無いと候補の行の所要時間が描かれず、走査がその配置を見ない）。
function makeRouteCandidate(
  id: string,
  directionLabel: string,
  distanceKm: number,
  durationSeconds: number,
): RouteCandidate {
  return makeCandidate({
    id,
    direction_label: directionLabel,
    distance_km: distanceKm,
    estimated_duration_seconds: durationSeconds,
    geometry: {
      type: "LineString",
      coordinates: [
        [139.7387, 35.7597],
        [139.75, 35.765],
        [139.7387, 35.7597],
      ],
    },
    elevation_gain_m: 120,
    // 選択中候補の区間色分け線は区間が無いと描かれない。
    // 地図の描画に関わる検証（縁取り等）が成り立つよう、最小限の2区間を持たせる。
    segments: [
      makeSegment(0, [
        [139.7387, 35.7597],
        [139.75, 35.765],
      ]),
      makeSegment(1, [
        [139.75, 35.765],
        [139.7387, 35.7597],
      ]),
    ],
    overall_difficulty: { average: 35, load: 700 },
  });
}

type DoneJob = Extract<RouteGenerateJobStatusResponse, { status: "done" }>;

/** 生成のジョブの完了の応答（ポーリングの1回目から完了を返す）。 */
export function doneJobFixture(result: DoneJob["result"] = routeGenerateResponseFixture()): DoneJob {
  return { status: "done", result };
}

// 戻り値に画面が受け取る生成結果の型を付け、backendの必須フィールド（GenerationConditions等）が
// 増えたときに、このモックの欠落を型検査が知らせるようにする。
export function routeGenerateResponseFixture(): DoneJob["result"] {
  return {
    routes: [makeRouteCandidate("route-1", "北", 20.3, 66 * 60), makeRouteCandidate("route-2", "南", 19.8, 60 * 60)],
    no_candidates_reason: null,
    conditions: makeGenerationConditions({
      latitude: 35.7597,
      longitude: 139.7387,
      distance_km: 20,
      distance_tolerance_km: 5,
      penalty_strength: 1.0,
      hard_filters: { no_bicycle: true, motorway: true, trunk: true },
      max_routes: 8,
      assumed_speed_kmh: 20,
      start_time: "2026-09-05T09:30:00+09:00",
      generated_at: new Date().toISOString(),
    }),
  };
}

// 戻り値の型をbackendのWeatherConditionsに固定する。backendが欄を足したとき、型が無いと
// 構造的部分型でtscが通り、欄の欠けたフィクスチャで画面がE2Eの実行中に落ちる。
function weatherConditionsFixture(): WeatherConditions {
  return {
    precipitation_mm: null,
    twilight: null,
    precipitation_max_mm: null,
    wind_speed_max_ms: null,
    temperature_range: null,
    today_periods: [],
    today_period_interval_hours: 2,
  };
}

// 最寄りアメダス観測所の実測値フィクスチャ。/api/weather*の汎用ワイルドカード（後述installApiMocks）は
// WeatherConditionsの形を返すため、形の違うAmedasObservationを使う/api/weather/amedasには専用ルートが
// 要る——無いと常設ヘッダーが欄の欠けたデータを受け取り、tscでは気づけない。
function amedasObservationFixture(): AmedasObservation {
  return {
    station_name: "観測所",
    observed_at: "2026-01-01T12:00:00+09:00",
    temperature_c: 18.5,
    apparent_temperature_c: null,
    wind_speed_ms: 2.1,
    wind_direction: { deg: 90, label: "東" },
    precipitation_10min_mm: null,
    weather_code: null,
    twilight: null,
  };
}

// 基礎地図スタイル（MapView.tsx: mapStyleUrl）の応答。sources/layersを空にして
// 外部タイル・グリフ・スプライトへの追加リクエストが発生しない自己完結スタイルにする
// （地図の見た目は検証対象外、UI操作の疎通のみが目的）。
function emptyMapStyleFixture() {
  return { version: 8, sources: {}, layers: [] };
}

/** `GET /api/axis-catalog`の応答。世代は本物のbackendと同じく全種類を返し（無いと凡例が配信情報を取得できない表示になる）、
 * 軸と世代以外（尺度・調整値・事故の収録年）は空で返す。型は契約のもので、項目を欠いた応答を作れない（欠けると、
 * 本物のbackendなら必ず来る値が画面で`undefined`になる）。 */
export function axisCatalogFixture(
  axes: ReturnType<typeof catalogEntry>[],
): components["schemas"]["AxisCatalogResponse"] {
  const tile_versions = Object.fromEntries(regionTileConfig.tile_version_kinds.map((kind) => [kind, "e2e"]));
  return catalogResponse(axes, { tile_versions });
}

/** 既定の軸カタログ。アプリが軸一覧を引ける最小の1軸だけを持つ。 */
export function defaultAxisCatalogFixture(): components["schemas"]["AxisCatalogResponse"] {
  return axisCatalogFixture([
    {
      ...catalogEntry({
        axis_id: "ramp",
        map_paint: {
          tiles: { kind: "ramp", tile_inputs: [tileInput({ property: "v", weight: 1 })], thresholds: [50] },
        },
      }),
      default_weight: 0,
    },
  ]);
}

/**
 * バックエンド・外部APIへの依存を断ち切るネットワークモックを登録する。
 * 各テストの冒頭（page.goto前）で呼ぶ。ここの応答はアプリを起動して画面を進めるための
 * 既定値であり、テストが判定する値を持たせない（.claude/rules/testing.md パターン4）。
 * テストが自分の値を返すときは、この後に同じURLへ`page.route`を登録する（後から登録した
 * ルートが先に当たる）。
 */
export async function installApiMocks(page: Page): Promise<void> {
  // 現在地を渡す。位置が取れない間は出発地が仮の地点のままで、生成が断られる。地点は候補の線の始点。
  await page.context().grantPermissions(["geolocation"]);
  await page.context().setGeolocation({ latitude: 35.7597, longitude: 139.7387 });

  await page.route(`${API_BASE}/health`, (route) => route.fulfill({ json: { status: "ok" } }));

  await page.route(`${API_BASE}/api/weather*`, (route) => route.fulfill({ json: weatherConditionsFixture() }));
  // /api/weather*より後に登録し、Playwrightのルート優先順位（後から登録した方が先に
  // マッチ判定される）で/api/weather/amedasだけこちらを優先させる。
  await page.route(`${API_BASE}/api/weather/amedas*`, (route) => route.fulfill({ json: amedasObservationFixture() }));
  // 警告バッジ3種は「警告なし」の成功応答にする。応答しないと取得失敗の印がヘッダーに出る。
  const noWarnings: WeatherWarnings = { warnings: [] };
  const noWbgt: WbgtStatus = { reading: null };
  const noFlood: FloodForecasts = { forecasts: [] };
  await page.route(`${API_BASE}/api/weather/warnings*`, (route) => route.fulfill({ json: noWarnings }));
  await page.route(`${API_BASE}/api/weather/wbgt*`, (route) => route.fulfill({ json: noWbgt }));
  await page.route(`${API_BASE}/api/weather/flood-forecast*`, (route) => route.fulfill({ json: noFlood }));

  // ルート生成はジョブで動く。POST（ジョブ投稿）は
  // 即座にjob_idを返し、GET .../generate/{job_id}（ポーリング）は1回目から
  // status="done"を返す（e2eはUI操作の疎通確認が目的で、待ち状態の遷移自体は
  // frontend/src/features/route/routeApi.test.tsが検証するためここでは再現しない）。
  await page.route(`${API_BASE}/api/routes/generate`, (route) =>
    route.fulfill({ status: 202, json: { job_id: "e2e-fake-job" } }),
  );
  await page.route(`${API_BASE}/api/routes/generate/*`, (route) => route.fulfill({ json: doneJobFixture() }));

  await page.route(`${API_BASE}/api/axis-catalog*`, (route) => route.fulfill({ json: defaultAxisCatalogFixture() }));

  // 地点の詳しくが、置いた位置の辺りを引く。辺り無し（境界の外）で答える。
  await page.route(`${API_BASE}/api/place-area*`, (route) => route.fulfill({ json: { area: null } }));

  // Next.jsのrewritesでbackendへ中継される経路（タイル・時刻一覧等）。モックしないと、E2Eの
  // サーバーの中継が接続拒否をログへ出し続ける。経路は next.config.ts の宣言から取り、中身無しで
  // 返す。応答に中身が要る経路は、この後で個別に上書きする（後から登録したルートが先に当たる）。
  for (const { source } of await rewriteRules()) {
    await page.route(`**${source.replace("/:path*", "/**")}`, (route) =>
      route.fulfill({ status: 204, body: Buffer.alloc(0) }),
    );
  }

  // 基礎地図スタイル（/api/basemap/styles/liberty）と、それ以外のbasemap配下
  // （タイル等、空スタイルなら通常発生しない）をまとめて空スタイルで応答する。
  await page.route("**/api/basemap/**", (route) => route.fulfill({ json: emptyMapStyleFixture() }));

  // 気象庁の時刻一覧は配列が要る。空の配列（取得できたが時刻が無い）で返す。
  await page.route(
    (url) => url.pathname.startsWith("/api/jma-tile/") && url.pathname.includes("/targetTimes"),
    (route) => route.fulfill({ json: [] }),
  );
}

async function rewriteRules(): Promise<{ source: string }[]> {
  const rules = (await nextConfig.rewrites?.()) ?? [];
  return Array.isArray(rules)
    ? rules
    : [...(rules.beforeFiles ?? []), ...(rules.afterFiles ?? []), ...(rules.fallback ?? [])];
}

// ここから下は「UIを見たい場所まで進める」導線のヘルパー。テストごとに書き直すと、
// UIの中身とは無関係な段取り（シートを開く・生成の完了を待つ）で落ちて時間を使うため、
// 1箇所へ集約する。

/** スマホ縦持ち相当。useIsMobile（CSSの`--breakpoint-mobile`以下で立つ`--is-mobile`の旗）のモバイル分岐に入る幅。 */
export const MOBILE_VIEWPORT = { width: 390, height: 812 };

/** モバイルの下部タブバーが持つシート。値はタブのラベル兼シートのアクセシブル名。 */
export type MobileSheetName = "ルート設定" | "ルート結果";

/**
 * localStorageの初期値を流し込む（goto前に呼ぶ）。保存される画面状態（レイヤーのON/OFF・
 * シートの高さ・重みづけ等、page.tsxのStorage key定数）は、クリックで作らずここで与える。
 * 値はuseStoredStateのserializeが書く形式そのもの（キーによって生文字列とJSONがある）。
 */
export async function seedStoredState(page: Page, entries: Record<string, string>): Promise<void> {
  await page.addInitScript((items) => {
    for (const [key, value] of Object.entries(items)) {
      window.localStorage.setItem(key, value);
    }
  }, entries);
}

/**
 * モバイル幅でアプリを開く（APIモックの登録・ビューポート設定・goto）。
 * `routes`は既定のモックの後・goto前に呼ばれる——テストが判定に使う応答はここで上書きする。
 * 呼んだ直後は、まだクリックが効かない（ハイドレーション前の）可能性がある——
 * 操作はopenMobileSheet等のヘルパー経由で行う。
 * 初回の案内（地図の上に重なる）は閉じた状態で開く。
 */
export async function openMobileApp(
  page: Page,
  { storedState, routes }: { storedState?: Record<string, string>; routes?: (page: Page) => Promise<unknown> } = {},
): Promise<void> {
  await installApiMocks(page);
  if (routes) await routes(page);
  await page.setViewportSize(MOBILE_VIEWPORT);
  await seedStoredState(page, { "ridecompass:first-visit-intro-closed": "true", ...storedState });
  await page.goto("/");
}

/**
 * 下部シートを開く（既に開いていれば何もしない）。タブの再タップは閉じる操作なので、
 * 開閉状態を見てから押す。ハイドレーション前のクリックは画面に何も起こさないため、
 * 「押して開くまで」を再試行する（固定のwaitForTimeoutを置かない）。
 */
export async function openMobileSheet(page: Page, name: MobileSheetName) {
  const sheet = page.getByRole("dialog", { name });
  await expect(async () => {
    if (!(await sheet.isVisible())) {
      await page.getByRole("button", { name, exact: true }).click();
    }
    await expect(sheet).toBeVisible({ timeout: 2000 });
  }).toPass({ timeout: 30_000 });
  return sheet;
}

/**
 * 「ルート設定」シートから距離を指定してルートを生成し、完了まで待つ。生成中は
 * ボタンの名前が「生成中...」へ変わるため、「ルート生成」が再び押せることが完了の合図。
 * @public 撮影の脚本が口（`capture/context.ts`の`fixtures`）越しに呼ぶ。knipは口越しの呼び出しを辿れない。
 */
export async function generateRoutes(page: Page, { distanceKm = 20 }: { distanceKm?: number } = {}) {
  const sheet = await openMobileSheet(page, "ルート設定");
  await sheet.getByLabel("距離").fill(String(distanceKm));
  await runGeneration(sheet);
  return sheet;
}

/** 「ルート生成」を押し、生成が終わってボタンが再び押せるまで待つ。`scope`はボタンを含む範囲
 * （スマホ幅はシート、それ以外は画面）。 */
export async function runGeneration(scope: Page | Locator): Promise<void> {
  await scope.getByRole("button", { name: "ルート生成" }).click();
  await expect(scope.getByRole("button", { name: "ルート生成" })).toBeEnabled({ timeout: 60_000 });
}

declare global {
  interface Window {
    __liveMap(): import("maplibre-gl").Map;
    __liveScene(): import("@/features/map/scene/mapScene").MapScene;
  }
}

/**
 * 地図のインスタンスと、地図に載っているべきものの宣言（scene）を、描画しているReactの部品の参照（useRef）から探す関数を
 * ページへ入れる。アプリは地図を外へ公開していないので、テストのために入口を足さず、Reactが要素へ付ける内部の印
 * （`__reactFiber$`）から祖先の部品のフックを辿る。Reactの内部の形が変わると見つからず、そのときは例外で止まる（黙って空を返さない）。
 */
export function installMapFinder(): void {
  const findRef = (what: string, holds: (current: Record<string, unknown>) => boolean) => {
    const container = document.querySelector(".maplibregl-map");
    const key = container && Object.keys(container).find((k) => k.startsWith("__reactFiber$"));
    type Hook = { memoizedState: unknown; next: Hook | null };
    type Fiber = { memoizedState: unknown; return: Fiber | null };
    let fiber = key ? ((container as unknown as Record<string, Fiber>)[key] ?? null) : null;
    for (; fiber; fiber = fiber.return) {
      let hook = fiber.memoizedState as Hook | null;
      while (hook && typeof hook === "object" && "next" in hook) {
        const state = hook.memoizedState as { current?: Record<string, unknown> } | null;
        if (state && typeof state === "object" && state.current && holds(state.current)) return state.current;
        hook = hook.next;
      }
    }
    throw new Error(`${what}が見つからない（Reactの内部の形が変わった可能性）`);
  };
  window.__liveMap = () =>
    findRef("地図のインスタンス", (current) => typeof current.queryRenderedFeatures === "function") as never;
  // 地図の部品は、いまのpropsの参照（MapView.tsx: latest）に scene を持つ。
  window.__liveScene = () =>
    findRef("地図の scene", (current) => Array.isArray((current.scene as { layers?: unknown })?.layers)).scene as never;
}

/**
 * 地図に描かれた、押すと詳細や選択が開くもの（scene が当たり判定の対象 `target` を宣言したレイヤーの地物）を1つ押す
 * （`installMapFinder`を入れたページで）。押す点は、地図そのものが押され（上に部品が重ならない）、そこで一番上に来る
 * 押せる地物が `target` のものである点に限る——アプリはその地物を開く（ルートの線は道・点より上の段にある）。
 * 対象の名前は scene の宣言から読むので、当たり判定を足せばここを変えずに押せる。押せなければ理由を出して止める。
 */
export async function clickFeature(page: Page, target: string): Promise<void> {
  const found = await page.evaluate((wanted) => {
    const map = window.__liveMap();
    const layers = window.__liveScene().layers;
    const targets = [...new Set(layers.flatMap((layer) => layer.hitTargets))];
    if (!targets.includes(wanted)) return { error: `いまの地図に無い。押せる対象: ${targets.join(" / ")}` };
    const carrying = layers.filter((layer) => layer.hitTargets.includes(wanted));
    const shown = carrying.filter((layer) => layer.visible && map.getLayer(layer.spec.id));
    if (shown.length === 0) {
      const hidden = carrying.map((layer) => layer.spec.id).join(" / ");
      return { error: `持つレイヤーが全部非表示（${hidden}。レイヤーの表示を ON にする）` };
    }
    const own = new Set(shown.map((layer) => layer.spec.id));
    const interactive = layers
      .filter((layer) => layer.hitTargets.length > 0 && map.getLayer(layer.spec.id))
      .map((layer) => layer.spec.id);
    const canvas = map.getCanvas();
    const box = canvas.getBoundingClientRect();
    const features = map.queryRenderedFeatures({ layers: [...own] });
    for (const feature of features) {
      const geometry = feature.geometry;
      const vertices: number[][] =
        geometry.type === "Point"
          ? [geometry.coordinates]
          : geometry.type === "LineString"
            ? geometry.coordinates
            : geometry.type === "MultiLineString"
              ? geometry.coordinates.flat()
              : [];
      // 線の端は別の道と接するので、真ん中の頂点から外へ向かって試す。
      const middle = Math.floor(vertices.length / 2);
      const order = vertices.map((_, i) => middle + (i % 2 === 0 ? i / 2 : -(i + 1) / 2));
      for (const index of order) {
        const vertex = vertices[index];
        if (!vertex) continue;
        const { x, y } = map.project([vertex[0], vertex[1]]);
        const client = { x: box.left + x, y: box.top + y };
        if (client.x < 0 || client.y < 0 || client.x >= window.innerWidth || client.y >= window.innerHeight) continue;
        if (document.elementFromPoint(client.x, client.y) !== canvas) continue;
        const top = map.queryRenderedFeatures([x, y], { layers: interactive })[0];
        if (top && own.has(top.layer.id)) return { point: client };
      }
    }
    return {
      error:
        features.length === 0
          ? "画面に描かれていない（位置・倍率を変える）"
          : `描かれた ${features.length} 件のどれも、地図の見えている所で一番上に来ない（位置・倍率を変える）`,
    };
  }, target);
  if ("error" in found) throw new Error(`地図の「${target}」を押せない: ${found.error}`);
  await page.mouse.click(found.point.x, found.point.y);
}

/** 地図の上の経度・緯度の点を押す（`installMapFinder`を入れたページで）。その点が画面の外か、地図の上に別の部品が重なっていれば止める。 */
export async function clickMap(page: Page, lngLat: [number, number]): Promise<void> {
  const point = await page.evaluate((at) => {
    const map = window.__liveMap();
    const projected = map.project(at);
    const box = map.getCanvas().getBoundingClientRect();
    const x = box.left + projected.x;
    const y = box.top + projected.y;
    const inside = x >= 0 && y >= 0 && x < window.innerWidth && y < window.innerHeight;
    return { x, y, onMap: inside && document.elementFromPoint(x, y) === map.getCanvas() };
  }, lngLat);
  if (!point.onMap) {
    throw new Error(`地図の点 ${lngLat.join(",")}（画面の ${Math.round(point.x)},${Math.round(point.y)}）は押せない`);
  }
  await page.mouse.click(point.x, point.y);
}
