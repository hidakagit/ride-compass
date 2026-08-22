// 風の格子点マップ（改善計画T178フォローアップ）のデータ層。DOM/MapLibreを一切知らない
// 純粋関数のみを持つ（precipitationNowcast.tsと同型）。実際のフェッチ・地図への反映は
// page.tsx/MapView.tsxが行う。
//
// 当初は`@openmeteo/weather-map-layer`（気象庁MSM由来、Open-Meteo配信のom://プロトコル）で
// 矢印を描画していたが、(1) ライブラリ本体・内部の.omファイルデコーダともGPL-2.0-onlyで
// GPLv2依存が避けられない、(2) 矢印の長さがライブラリ側でズームレベル依存に固定され自由に
// 表現できない、という2つの制約に実機で行き当たった。ユーザー判断（2026-08-20「自前実装案で
// 進めて」）により、既存のOpen-Meteo REST API経由の地点評価（weather_client.py:
// get_forecast_many、CC-BY-4.0・GPL無関係）と同じ仕組みでバックエンドが関東本土の固定格子点を
// サンプリングするAPI（GET /api/weather/wind-grid）を新設し、フロントはその結果を
// MapLibre標準のsymbolレイヤー（矢印アイコンを独自定義、向き・長さ・色すべて自由に設定可能）で
// 描画する方式へ切り替えた。
//
// T183（動的気象レイヤーの再設計、実機フィードバック「動的レイヤについては今後もデータ追加が
// あり得るので、それも見据えて拡張性がある設計にしてほしい」）で、風・降水を共通契約
// （dynamicWeather.ts）へ揃えた。このファイルはDynamicWeatherFrame/DynamicWeatherRenderPayload
// を組み立てる薄いラッパーのみを持つ（実際のGeoJSON構築・色/サイズの式化はwindFrames/
// windRenderPayload、MapView.tsx側）。

import type { DynamicWeatherFrame, DynamicWeatherRenderPayload } from "@/components/Map/dynamicWeather";
import type { WindGridPoint } from "@/types/weather";
import windGridConfig from "@/types/generated/wind-grid-config.json";

/** "YYYY-MM-DDTHH:MM"（Open-Meteoのtimezone=Asia/Tokyo指定によるJST・オフセット無し表記）を
 * JSTとして解釈するDateへ変換する。オフセット無しのままDateへ渡すとブラウザのローカル
 * タイムゾーンとして解釈されてしまう（日本国外の閲覧環境で時刻がずれる）ため、明示的に
 * +09:00を付与する。降水延長予報（precipitationNowcast.ts）も同じ格子点マップ由来の時刻を
 * パースするため、このファイルからexportして共有する。 */
export function parseJstTime(time: string): Date {
  return new Date(`${time}+09:00`);
}

/** Open-Meteoのhourly.timeは常にその日の00:00始まりのため、フェッチ時刻によっては
 * 半日近く過去の時刻が配列の前半を占める。gridを「現在時刻の属する時間帯」以降だけへ
 * 切り詰め、スライダーの左端（index 0）が常に「現在」になるようにする（実機フィードバック
 * 「過去の風を気にすることはアプリの性質上ない、デフォルト位置を左端に」）。「現在」の
 * 定義は「最も近い時刻」ではなく「現在時刻以下で最も新しい時刻」（＝現在が属する1時間）
 * とする。最も近い時刻だと現在時刻が正時をわずかに過ぎただけで次の1時間へ丸められ、
 * 本来の現在時間帯を消してしまうため。全格子点で時刻配列が共通という前提のもと、grid[0]の
 * 時刻で1回だけindexを求め、全格子点の4つの並行配列（times/wind_speed_ms/
 * wind_direction_deg/precipitation_mm）へ同じindexを適用する。空配列・全フレームが
 * 未来（＝ぴったり境界）ならそのまま返す。 */
export function trimWindGridToCurrentAndFuture(grid: readonly WindGridPoint[], now: Date = new Date()): WindGridPoint[] {
  if (grid.length === 0) return [];
  const times = grid[0].times;
  const nowMs = now.getTime();
  let startIndex = 0;
  for (let i = 0; i < times.length; i++) {
    if (parseJstTime(times[i]).getTime() <= nowMs) startIndex = i;
  }
  if (startIndex === 0) return grid.slice();
  return grid.map((point) => ({
    ...point,
    times: point.times.slice(startIndex),
    wind_speed_ms: point.wind_speed_ms.slice(startIndex),
    wind_direction_deg: point.wind_direction_deg.slice(startIndex),
    precipitation_mm: point.precipitation_mm.slice(startIndex),
  }));
}

/** 新しく取得した格子（next）に、前回の格子（previous）のうちnextに無い地点だけを
 * 補って返す（実機フィードバック「画面端が塗られないことがある」）。バックエンド
 * （GET /api/weather/wind-grid・wind-grid-detail）はOpen-Meteo側の失敗（429等、この
 * セッション中にも実際に発生）で個別地点の取得に失敗すると、その地点をレスポンスから
 * 丸ごと除外する「取得失敗は握りつぶす」方針（api/routers/weather.py参照）のため、
 * 再取得のたびにどの地点が欠けるかが変わりうる。前回成功していた地点をそのまま
 * 残すことで、1地点の一時的な失敗が地図上の「その場所だけ描画されていない」穴として
 * 見えてしまうのを防ぐ（多少古い値が残る方が穴が開くより実用上マシという判断。
 * バックエンド側のstale fallback＝weather_client.pyのSTALE_FALLBACK_MAX_AGE_SECONDSと
 * 同じ考え方をフロント側にも及ぼす）。地点の同一性は緯度経度（固定ラティス由来でどちらも
 * 同じ丸め精度）で判定する。呼び出し側は生（trim前）の格子を渡すこと（trim後は「現在」の
 * 位置が取得のたびにずれ、古い地点だけindexの意味が食い違ってしまうため）。 */
export function mergeWindGridKeepingStale(
  previous: readonly WindGridPoint[],
  next: readonly WindGridPoint[]
): WindGridPoint[] {
  const nextKeys = new Set(next.map((point) => `${point.latitude},${point.longitude}`));
  const staleCarryOver = previous.filter((point) => !nextKeys.has(`${point.latitude},${point.longitude}`));
  return [...next, ...staleCarryOver];
}

// 風速→色の対応。矢印のicon-color（MapView.tsx）・地図チップの凡例（page.tsx、実機
// フィードバック「風と雨の凡例も欲しい」）の2箇所で同じ配色を使うための単一の情報源
// （2箇所以上に同じ配色を書くと片方だけ直して食い違う事故が起きうるため1箇所へ集約）。
// MapLibre非依存の生データとして持ち、MapLibre補間式への組み立ては呼び出し側
// （MapView.tsx）が行う（このファイル自体はDOM/MapLibreを知らない、ファイル冒頭の
// コメント参照）。
//
// 実機フィードバック「風の色分けをもっと細かくして。ロードバイクで走れない強風域は
// 粒度粗く。微風からそこまでは粒度を細かくして」を受け、気象庁も使う国際的なビューフォート
// 風力階級（0.3m/s刻みではなくBf1〜6の実際の境界値）を刻み幅に採用した: 0（無風、後述の
// WIND_CALM_THRESHOLD_MS未満は非表示）〜Bf6上限13.8m/s（「傘をさすのが困難」）までは
// Bf階級ごとに色を変え、この帯（ロードバイクで通常走行できる範囲）を細かく塗り分ける。
// Bf7開始13.9m/s（「風に向かって歩くのが困難」、ロードバイクでの走行が現実的でなくなる
// 目安）以降は帯を大きく空けた2段階（Bf7上限17.1m/s・Bf9上限24.4m/s）だけにとどめ、
// 「走れないほど強い」こと自体が伝わればよく細かい差は重要でないという判断を反映する。
export const WIND_SPEED_COLOR_STOPS: readonly { speedMs: number; color: string }[] = [
  { speedMs: 0, color: "#7dd3fc" }, // 無風に近い
  { speedMs: 1.5, color: "#38bdf8" }, // Bf1上限
  { speedMs: 3.3, color: "#22d3ee" }, // Bf2上限
  { speedMs: 5.4, color: "#34d399" }, // Bf3上限
  { speedMs: 7.9, color: "#a3e635" }, // Bf4上限
  { speedMs: 10.7, color: "#facc15" }, // Bf5上限
  { speedMs: 13.8, color: "#f97316" }, // Bf6上限（ロードバイクで走行できる目安の上限）
  { speedMs: 17.1, color: "#dc2626" }, // Bf7上限（走行困難域、ここから粒度は粗くする）
  { speedMs: 24.4, color: "#7f1d1d" }, // Bf9上限（暴風、これ以上は同じ色のまま）
];

// この風速未満は「無風」として矢印を描画しない（MapView.tsx参照）。実機確認
// （2026-08-20、王子周辺で実測0.70〜0.81m/s）で当初の1.0m/sだと関東でごく普通に起きる
// 弱風でも矢印が全滅したため、この値まで引き下げた経緯がある。
export const WIND_CALM_THRESHOLD_MS = 0.3;

// 地図チップの凡例（page.tsx）用に、上記の生データへラベルを付けたもの。数値は
// WIND_SPEED_COLOR_STOPS/WIND_CALM_THRESHOLD_MSからそのまま持ってくるため、閾値・色を
// 変えてもここは自動で追従する（片側importで単一の情報源を保つ）。地図の色分け自体は
// WIND_SPEED_COLOR_STOPSの9段階そのままだが、凡例は「ロードバイクで走行が難しい強風域」の
// 中の細かい差（Bf7/Bf9境界）まで1行ずつ並べても実用上の情報量が薄いため、その帯は
// 1行へまとめている（凡例上の粒度も「そこから先は粗い」という体験に合わせる）。
export const WIND_SPEED_LEGEND_LEVELS: readonly { key: string; label: string; color: string }[] = [
  { key: "calm", label: `無風（矢印なし、${WIND_CALM_THRESHOLD_MS}m/s未満）`, color: "#9ca3af" },
  { key: "bf1", label: "微風", color: WIND_SPEED_COLOR_STOPS[0].color },
  { key: "bf2", label: `そよ風（〜${WIND_SPEED_COLOR_STOPS[1].speedMs}m/s）`, color: WIND_SPEED_COLOR_STOPS[1].color },
  { key: "bf3", label: `心地よい風（〜${WIND_SPEED_COLOR_STOPS[2].speedMs}m/s）`, color: WIND_SPEED_COLOR_STOPS[2].color },
  { key: "bf4", label: `やや強い風（〜${WIND_SPEED_COLOR_STOPS[3].speedMs}m/s）`, color: WIND_SPEED_COLOR_STOPS[3].color },
  { key: "bf5", label: `強い風・向かい風がこたえ始める（〜${WIND_SPEED_COLOR_STOPS[4].speedMs}m/s）`, color: WIND_SPEED_COLOR_STOPS[4].color },
  { key: "bf6", label: `かなり強い風（〜${WIND_SPEED_COLOR_STOPS[5].speedMs}m/s）`, color: WIND_SPEED_COLOR_STOPS[5].color },
  {
    key: "unrideable",
    label: `ロードバイクでの走行が難しい強風域（${WIND_SPEED_COLOR_STOPS[6].speedMs}m/s以上）`,
    color: WIND_SPEED_COLOR_STOPS[6].color,
  },
];

export interface WindPointFeatureProperties {
  /** 風速（m/s） */
  speed: number;
  /** 矢印の向き（度、MapLibreのicon-rotate用に「風が吹いていく方向」＝気象学的な風向
   * （吹いてくる方向）+180した値。北=0、時計回り）。 */
  bearing: number;
}

/** grid（バックエンドから取得した格子点一覧）のframeIndex番目の時刻ぶんを、MapLibreの
 * GeoJSON sourceへそのまま渡せるFeatureCollectionへ変換する。frameIndexが範囲外、または
 * 値が欠損している格子点はスキップする（1点の欠損で全体を落とさない）。 */
function windGridToFeatureCollection(
  grid: readonly WindGridPoint[],
  frameIndex: number
): GeoJSON.FeatureCollection<GeoJSON.Point, WindPointFeatureProperties> {
  const features: GeoJSON.Feature<GeoJSON.Point, WindPointFeatureProperties>[] = [];
  for (const point of grid) {
    const speed = point.wind_speed_ms[frameIndex];
    const direction = point.wind_direction_deg[frameIndex];
    if (speed == null || direction == null) continue;
    features.push({
      type: "Feature",
      geometry: { type: "Point", coordinates: [point.longitude, point.latitude] },
      properties: { speed, bearing: (direction + 180) % 360 },
    });
  }
  return { type: "FeatureCollection", features };
}

/** grid[0]の時刻配列を、動的気象レイヤー共通のフレーム列（dynamicWeather.ts参照）へ変換する。
 * refはgrid各点のtimes/wind_speed_ms/wind_direction_deg内のindexを指し、windRenderPayloadへ
 * そのまま渡す。全格子点で時刻配列が共通という前提（同じforecast_days・timezoneで一括取得
 * しているため）のもと、grid[0]だけを見る。 */
export function windFrames(grid: readonly WindGridPoint[]): DynamicWeatherFrame<number>[] {
  const times = grid[0]?.times ?? [];
  return times.map((time, index) => ({ time: parseJstTime(time), ref: index }));
}

/** windFramesが返したref（times内のindex）から、地図へ渡す描画ペイロード（gridMark、
 * 格子中央にマーク＝矢印を出す表現）を組み立てる。 */
export function windRenderPayload(grid: readonly WindGridPoint[], ref: number): DynamicWeatherRenderPayload {
  return { kind: "gridMark", geojson: windGridToFeatureCollection(grid, ref) };
}

// 格子間隔（度）。改善計画T198（統合レビュー2026-08-22指摘F-B）以前は
// backend/app/domain/wind_grid.pyの同名定数を「値を合わせること」というコメントのみで
// 手動複製していたが、APIレスポンス自体には間隔情報が含まれない（点の配列のみ）ため
// 気づかれないままズレうる手動同期ペアだった。他の生成物（axis-catalog.json等）と同じ
// 片側importへ揃え、backend/scripts/export_openapi.pyが書き出すwind-grid-config.jsonを
// 単一の情報源とする。降水延長予報のgridFill表現（precipitationNowcast.ts）がセルの
// 1辺の長さとして使う。
export const WIND_GRID_SPACING_DEG = windGridConfig.spacing_deg;
export const WIND_GRID_DETAIL_SPACING_DEG = windGridConfig.detail_spacing_deg;

export interface MapViewport {
  west: number;
  south: number;
  east: number;
  north: number;
  zoom: number;
}

export interface Bbox {
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
}

// 詳細格子（改善計画T180）を出す最低ズーム。これ未満は広域の粗い格子（既存のgetWindGrid）
// だけで足りると判断（狭い範囲を詳細に見るための機能のため）。
export const WIND_DETAIL_MIN_ZOOM = 10;

// ズーム依存の詳細格子間隔（T185、実機フィードバック「拡大率が大きいとgridFillの格子が
// ゴワゴワして気になる。拡大率によって格子サイズも大きく（風の矢印と同じ）補正する汎用的な
// 拡張はできない？」）。風の矢印のicon-size（ズームに応じて表示サイズを拡大、MapView.tsx:
// zoomAndPropertyIconSizeExpression）はピクセル単位の記号なのでこの補正で足りるが、
// gridFillのセルは「1格子点が担当する実面積」を表す図形のため、表示サイズだけを縮めても
// 隙間ができるだけで解決しない。根本原因は「同じ間隔の格子が、ズームインするほど画面上の
// 面積を大きく占めて色の段差（ゴワゴワ）が目立つ」ことなので、ズームが進むほど格子間隔
// 自体を細かくする。段階は離散値のみ（連続値にすると閲覧者ごとにラティスの絶対座標が
// わずかにずれ、generate_wind_grid_detail_pointsのキャッシュ共有が効かなくなるため）。
// 間隔の値そのものはwind-grid-config.json（detail_allowed_spacings_deg、backend/app/
// domain/wind_grid.py: WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEGが単一の情報源、改善計画T198）
// から取る。zoom境界（10/13/16/19、ICON_ZOOM_SCALE_STOPS・MapView.tsxと同じ刻み）は
// 地図の見た目に関するUI側の判断のためフロント固有の定数として持つ。
const WIND_GRID_DETAIL_SPACING_ZOOM_BREAKPOINTS: readonly number[] = [WIND_DETAIL_MIN_ZOOM, 13, 16, 19];
export const WIND_GRID_DETAIL_SPACING_STOPS: readonly { zoom: number; spacingDeg: number }[] =
  WIND_GRID_DETAIL_SPACING_ZOOM_BREAKPOINTS.map((zoom, i) => ({
    zoom,
    spacingDeg: windGridConfig.detail_allowed_spacings_deg[i],
  }));

/** 現在のズームから、詳細格子を要求するときの格子間隔（度）を求める。WIND_GRID_DETAIL_
 * SPACING_STOPSのうちzoom以下の段階で最も細かい（配列は昇順前提）ものを返す。zoomが
 * 最初の段階未満のときはWIND_GRID_DETAIL_SPACING_DEG（最も粗い段階）を返す（呼び出し側は
 * WIND_DETAIL_MIN_ZOOM以上でしか使わない想定だが、単体では境界を知らない関数として
 * フォールバックを持たせておく）。 */
export function windGridDetailSpacingDegForZoom(zoom: number): number {
  let spacingDeg = WIND_GRID_DETAIL_SPACING_DEG;
  for (const stop of WIND_GRID_DETAIL_SPACING_STOPS) {
    if (zoom >= stop.zoom) spacingDeg = stop.spacingDeg;
  }
  return spacingDeg;
}

// 1回のリクエストで許容するbboxの最大幅・高さ（度）を、格子間隔から逆算する係数。
// wind-grid-config.jsonのdetail_max_points（900、backend/app/domain/wind_grid.py:
// WIND_GRID_DETAIL_MAX_POINTSが単一の情報源）に対し、1辺25間隔（26×26=676点）で
// 余裕を持たせる（以前の固定値0.5度＝0.02度間隔×25と同じ安全率を、間隔が変わっても保つ）。
// 25という係数自体は「間隔から逆算する安全率」という設計判断でありconfigの値そのものの
// 複製ではないため定数のまま持つが、windLayer.test.tsが
// `(WIND_DETAIL_MAX_BBOX_SPAN_SIDE_INTERVALS + 1) ** 2 <= windGridConfig.detail_max_points`
// を検証し、backend側の上限が下がった場合に安全率が崩れていないかをテストで検知する。
export const WIND_DETAIL_MAX_BBOX_SPAN_SIDE_INTERVALS = 25;

/** 現在のビューポートから、詳細格子APIへ渡すbboxを求める。ビューポートがクリップ幅より
 * 狭ければビューポートそのまま、広ければ中心を基準に最大幅へクリップする（上記コメント参照）。
 * spacingDegが細かいほどクリップ幅も比例して狭くなる（windGridDetailSpacingDegForZoom参照、
 * 同じ点数上限に対して間隔なりの面積で収める）。 */
export function clampWindDetailBbox(viewport: MapViewport, spacingDeg: number): Bbox {
  const halfSpan = (spacingDeg * WIND_DETAIL_MAX_BBOX_SPAN_SIDE_INTERVALS) / 2;
  const centerLon = (viewport.west + viewport.east) / 2;
  const centerLat = (viewport.south + viewport.north) / 2;
  return {
    minLon: Math.max(viewport.west, centerLon - halfSpan),
    minLat: Math.max(viewport.south, centerLat - halfSpan),
    maxLon: Math.min(viewport.east, centerLon + halfSpan),
    maxLat: Math.min(viewport.north, centerLat + halfSpan),
  };
}

