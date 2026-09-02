import type { Page } from "@playwright/test";
import type { RouteCandidate, RouteGenerateResponse } from "@/types/route";
import type { AmedasObservation, WeatherConditions } from "@/types/weather";

// CIのE2Eスモークテストは「実バックエンド＋実外部API（openrouteservice/Open-Meteo/
// OpenFreeMap）」には依存しない。APIコントラクトの正しさはCIのapi-contractジョブ
// （OpenAPIドリフト検知）が別途担保しており、E2Eはフロントの画面挙動（生成→表示、
// レイヤー切替）だけを決定的に検証する。バックエンドプロセスの起動・DB・APIキーが
// 不要になるぶん、CIが速く安定する。

const API_BASE = "http://localhost:8000";

// キーはaxis_id（改善計画T221 Stage B、backend AXIS_DEFINITIONS参照）。
// RoutePreferenceWeightsはindex signature型のため旧キーでも型検査を通ってしまう
// （コンパイルではドリフト検知できない）。実キー集合の正はaxis-catalog.jsonの
// preference_defaults（evaluationAxes.test.tsが照合）。
const ROUTE_PREFERENCE = {
  gradient: 1,
  surface_q: 1,
  wind: 1,
  stop_density: 1,
  car_stress: 1,
  accident: 1,
  night: 0,
};

// backend/app/domain/route.py RouteCandidate相当の最小フィクスチャ（1候補）。
// geometryは往復可能な閉じたループの体裁のみ整える（実座標としての精度は問わない）。
function makeRouteCandidate(id: string, directionLabel: string, distanceKm: number): RouteCandidate {
  return {
    id,
    direction_label: directionLabel,
    distance_km: distanceKm,
    geometry: {
      type: "LineString",
      coordinates: [
        [139.7387, 35.7597],
        [139.75, 35.765],
        [139.7387, 35.7597],
      ],
    },
    elevation_gain_m: 120,
    min_elevation_m: 10,
    max_elevation_m: 45,
    max_gradient_percent: 6.5,
    wind_score: -1.2,
    road_score: 82,
    segments: null,
    overall_difficulty: 35,
    axis_difficulties: {},
    axis_contributions: {},
  };
}

// 戻り値にRouteGenerateResponse型注釈を付け、バックエンドの実際の必須フィールド
// （GenerationConditions等）が増えてもTypeScriptがこのモックの欠落を検知できるようにする
// （consistencyレビュー2026-08-23 F-2: 型注釈が無かったため、T225でconditionsへ
// penalty_strength/max_average_grade_percentが必須化された際もこのモックだけ
// 追従漏れになっていた）。
export function routeGenerateResponseFixture(): RouteGenerateResponse {
  return {
    routes: [makeRouteCandidate("route-1", "北", 20.3), makeRouteCandidate("route-2", "南", 19.8)],
    engine: "openrouteservice",
    no_candidates_reason: null,
    conditions: {
      latitude: 35.7597,
      longitude: 139.7387,
      distance_km: 20,
      distance_tolerance_km: 5,
      route_preference: ROUTE_PREFERENCE,
      penalty_strength: 1.0,
      max_average_grade_percent: null,
      hard_filters: { no_bicycle: true, motorway: true, trunk: true },
      max_routes: 8,
      waypoints: null,
      destination: null,
      generated_at: new Date().toISOString(),
    },
  };
}

// 戻り値へWeatherConditions型注釈を付ける（改善計画T385フォローアップ2のCI障害を受けて追加）:
// このフィクスチャは型注釈が無かったためbackendのWeatherConditionsへ新規フィールドを追加
// しても構造的部分型でコンパイルが通ってしまい、フィールド欠落に気づけなかった。
// TodayOutlook.tsx側は「today_periodsは常に配列（Noneではない）」というbackend契約を
// 前提に`.length`へ無条件アクセスするため、このフィクスチャがtoday_periods自体を
// 持たない（undefined）とE2E実行時にTypeErrorで描画が丸ごと落ちる
// （「element was detached from the DOM, retrying」の形でCIに現れた）。型注釈により
// 今後のフィールド追加時はtscがこのフィクスチャの更新漏れを検知する。
export function weatherConditionsFixture(): WeatherConditions {
  return {
    temperature_c: 18.5,
    apparent_temperature_c: null,
    wind_speed_ms: 2.1,
    wind_direction_deg: 90,
    wind_direction_label: "東",
    wind_gusts_ms: null,
    precipitation_probability_percent: 10,
    precipitation_mm: null,
    uv_index: null,
    observed_at: new Date().toISOString(),
    weather_code: null,
    is_day: null,
    sunrise: null,
    sunset: null,
    precipitation_probability_max_percent: null,
    wind_speed_max_ms: null,
    temperature_max_c: null,
    temperature_min_c: null,
    uv_index_max: null,
    today_periods: [],
  };
}

// 最寄りアメダス観測所の実測値フィクスチャ（改善計画T387フォローアップ）。/api/weather*の
// 汎用ワイルドカード（後述installApiMocks）はWeatherConditions型のweatherConditionsFixture()を
// 返すため、フィールド名が異なるAmedasObservation（station_id/station_name等）を使う
// /api/weather/amedasには専用ルートが必要——無いとWeatherPanel（常設ヘッダー）が
// undefinedフィールドだらけの誤った形のデータを受け取ることになる（型注釈が無いと
// tscでは検知できない。weatherConditionsFixtureの型注釈導入の経緯コメント参照）。
export function amedasObservationFixture(): AmedasObservation {
  return {
    station_id: "44132",
    station_name: "東京",
    latitude: 35.69,
    longitude: 139.76,
    observed_at: new Date().toISOString(),
    temperature_c: 18.5,
    apparent_temperature_c: null,
    wind_speed_ms: 2.1,
    wind_direction_deg: 90,
    wind_direction_label: "東",
    precipitation_10min_mm: null,
    sunshine_10min_minutes: null,
    sunrise: null,
    sunset: null,
  };
}

// MapLibreのスタイル読み込み先（MapView.tsx: MAP_STYLE）。sources/layersを空にして
// 外部タイル・グリフ・スプライトへの追加リクエストが発生しない自己完結スタイルにする
// （地図の見た目は検証対象外、UI操作の疎通のみが目的）。
function emptyMapStyleFixture() {
  return { version: 8, sources: {}, layers: [] };
}

/**
 * バックエンド・外部APIへの依存を断ち切るネットワークモックを登録する。
 * 各テストの冒頭（page.goto前）で呼ぶ。
 */
export async function installApiMocks(page: Page): Promise<void> {
  await page.route(`${API_BASE}/health`, (route) =>
    route.fulfill({ json: { status: "ok" } })
  );

  await page.route(`${API_BASE}/api/weather*`, (route) =>
    route.fulfill({ json: weatherConditionsFixture() })
  );
  // /api/weather*より後に登録し、Playwrightのルート優先順位（後から登録した方が先に
  // マッチ判定される）で/api/weather/amedasだけこちらを優先させる。
  await page.route(`${API_BASE}/api/weather/amedas*`, (route) =>
    route.fulfill({ json: amedasObservationFixture() })
  );

  // 改善計画T265: ルート生成はバックグラウンドジョブ化された。POST（ジョブ投稿）は
  // 即座にjob_idを返し、GET .../generate/{job_id}（ポーリング）は1回目から
  // status="done"を返す（e2eはUI操作の疎通確認が目的で、待ち状態の遷移自体は
  // frontend/src/services/routeApi.test.tsが検証するためここでは再現しない）。
  await page.route(`${API_BASE}/api/routes/generate`, (route) =>
    route.fulfill({ status: 202, json: { job_id: "e2e-fake-job" } })
  );
  await page.route(`${API_BASE}/api/routes/generate/*`, (route) =>
    route.fulfill({ json: { status: "done", result: routeGenerateResponseFixture(), error: null } })
  );

  // 基礎地図スタイル（/api/basemap/styles/liberty）と、それ以外のbasemap配下
  // （タイル等、空スタイルなら通常発生しない）をまとめて空スタイルで応答する。
  await page.route("**/api/basemap/**", (route) =>
    route.fulfill({ json: emptyMapStyleFixture() })
  );

  // 道路情報レイヤーのベクタタイル。空スタイル配下ではソース登録自体は行われるため
  // （MapView.tsxがstyledata後にaddSourceする）、要求されたら空バイナリで応答する。
  await page.route("**/api/region/road-surface-tiles/**", (route) =>
    route.fulfill({ status: 204, body: Buffer.alloc(0) })
  );
}
