// 風と降水が共有する格子点マップの扱い（今より前の時刻を落とす・取り損ねた地点を補う・詳細格子の
// 間隔と範囲）と、風の矢印の描き方。DOM/MapLibreを一切知らない純粋関数のみを持つ。
//
// 気象庁MSM（msm_client.py: read_series）を格子点へ補間した値を使い、
// バックエンドが関東本土の固定格子点をサンプリングするAPI（GET /api/weather/wind-grid）を
// フロントが叩き、MapLibre標準のsymbolレイヤー（矢印アイコンを独自定義、向き・長さ・色
// すべて自由に設定可能）で描画する。時系列は`weatherSources.ts`が源泉の宣言から作る。

import palette from "@/types/generated/palette.json";
import type { Bbox } from "@/services/weatherApi";
import weatherScales from "@/types/generated/weather-scales.json";
import { gridToFeatureCollection, type DynamicWeatherRenderPayload } from "@/features/map/layers/dynamicWeather";
import type { WindGridPoint } from "@/types/weather";
import windGridConfig from "@/types/generated/wind-grid-config.json";
import { parseJstLocalValue } from "@/lib/time";
import { buildRangeLegendBands, type MapColorLegendBand } from "@/lib/mapDisplay/mapColorLegend";

/** 時刻配列は通常「現在時刻の正時」から始まるが、フェッチから時間が経てば先頭が過去に
 * なりうる。gridを「現在時刻の属する時間帯」以降だけへ
 * 切り詰め、スライダーの左端（index 0）が常に「現在」になるようにする。「現在」の
 * 定義は「最も近い時刻」ではなく「現在時刻以下で最も新しい時刻」（＝現在が属する1時間）
 * とする。最も近い時刻だと現在時刻が正時をわずかに過ぎただけで次の1時間へ丸められ、
 * 本来の現在時間帯を消してしまうため。全格子点で時刻配列が共通という前提のもと、grid[0]の
 * 時刻で1回だけindexを求め、全格子点の4つの並行配列（times/wind_speed_ms/
 * wind_direction_deg/precipitation_mm）へ同じindexを適用する。空配列・全フレームが
 * 未来（＝ぴったり境界）ならそのまま返す。 */
export function trimWindGridToCurrentAndFuture(
  grid: readonly WindGridPoint[],
  now: Date = new Date(),
): WindGridPoint[] {
  if (grid.length === 0) return [];
  const times = grid[0].times;
  const nowMs = now.getTime();
  let startIndex = 0;
  for (let i = 0; i < times.length; i++) {
    if (parseJstLocalValue(times[i]).getTime() <= nowMs) startIndex = i;
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
 * 補って返す。バックエンド（GET /api/weather/wind-grid・wind-grid-detail）は
 * 個別地点の取得に失敗すると、その地点をレスポンスから
 * 丸ごと除外する「取得失敗は握りつぶす」方針（api/routers/weather.py参照）のため、
 * 再取得のたびにどの地点が欠けるかが変わりうる。前回成功していた地点をそのまま
 * 残すことで、1地点の一時的な失敗が地図上の「その場所だけ描画されていない」穴として
 * 見えてしまうのを防ぐ（多少古い値が残る方が穴が開くより実用上マシという判断。
 * バックエンドが古い値を残して穴を防ぐのと同じ考え方をフロント側にも及ぼす）。地点の同一性は緯度経度（固定ラティス由来でどちらも
 * 同じ丸め精度）で判定する。呼び出し側は生（trim前）の格子を渡すこと（trim後は「現在」の
 * 位置が取得のたびにずれ、古い地点だけindexの意味が食い違ってしまうため）。 */
export function mergeWindGridKeepingStale(
  previous: readonly WindGridPoint[],
  next: readonly WindGridPoint[],
): WindGridPoint[] {
  const nextKeys = new Set(next.map((point) => `${point.latitude},${point.longitude}`));
  const staleCarryOver = previous.filter((point) => !nextKeys.has(`${point.latitude},${point.longitude}`));
  return [...next, ...staleCarryOver];
}

// 風速→色の対応。矢印のicon-color（MapView.tsx）・地図チップの凡例（page.tsx）の
// 2箇所で同じ配色を使うための単一の情報源
// （2箇所以上に同じ配色を書くと片方だけ直して食い違う事故が起きうるため1箇所へ集約）。
// MapLibre非依存の生データとして持ち、MapLibre補間式への組み立ては呼び出し側
// （MapView.tsx）が行う（このファイル自体はDOM/MapLibreを知らない、ファイル冒頭の
// コメント参照）。
//
// 気象庁も使う国際的なビューフォート風力階級（0.3m/s刻みではなくBf1〜6の実際の境界値）を
// 刻み幅に採用した: 0（無風、後述の
// WIND_CALM_THRESHOLD_MS未満は非表示）〜Bf6上限13.8m/s（「傘をさすのが困難」）までは
// Bf階級ごとに色を変え、この帯（ロードバイクで通常走行できる範囲）を細かく塗り分ける。
// Bf7開始13.9m/s（「風に向かって歩くのが困難」、ロードバイクでの走行が現実的でなくなる
// 目安）以降は帯を大きく空けた2段階（Bf7上限17.1m/s・Bf9上限24.4m/s）だけにとどめ、
// 「走れないほど強い」こと自体が伝わればよく細かい差は重要でないという判断を反映する。
//
// `name`は段ごとの体感表現（ビューフォート風力階級の呼び名を、自転車で走るときの感じ方へ
// 寄せたもの）。**段の宣言そのものに持たせる**——別の配列に並べて添字で引くと、段を足した
// ときに呼び名を足し忘れても型は通り、凡例に`undefined`が出る。
export const WIND_SPEED_COLOR_STOPS: readonly { speedMs: number; color: string; name: string }[] =
  weatherScales.wind_speed.map((stop) => ({ speedMs: stop.value, color: stop.color, name: stop.name }));

// この風速未満は「無風」として矢印を描画しない（MapView.tsx参照）。1.0m/s程度だと
// 関東でごく普通に起きる弱風でも矢印が全滅するため、この値にしている。
export const WIND_CALM_THRESHOLD_MS = 0.3;

// 風速の色の段（WIND_SPEED_COLOR_STOPS）は**帯の下限**で、地図はこの配列をそのまま
// step式へ組み立てて塗る（`features/map/scene/groups/weather.ts`）。凡例もこの配列から
// 帯の範囲を書き出すため、地図に出る色と凡例の行は1対1で対応する。矢印を出さない無風の範囲も
// 1行として先頭に置き、最初の色の帯はその上から始まる。
//
// **行を束ねないこと。** 束ねた行は、地図が塗り分けている複数の帯を1つの色見本で代表する
// ことになり、束ねた中の値が見本と食い違う。粒度を粗くしたいなら段自体を減らす。
export const WIND_SPEED_LEGEND_LEVELS: readonly MapColorLegendBand[] = buildRangeLegendBands(
  [WIND_CALM_THRESHOLD_MS, ...WIND_SPEED_COLOR_STOPS.slice(1).map((stop) => stop.speedMs)],
  [palette.semantic.no_data, ...WIND_SPEED_COLOR_STOPS.map((stop) => stop.color)],
  "m/s",
  ["無風・矢印なし", ...WIND_SPEED_COLOR_STOPS.map((stop) => stop.name)],
);

interface WindPointFeatureProperties {
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
  frameIndex: number,
): GeoJSON.FeatureCollection<GeoJSON.Point, WindPointFeatureProperties> {
  return gridToFeatureCollection(
    grid,
    (point) => {
      const speed = point.wind_speed_ms[frameIndex];
      const direction = point.wind_direction_deg[frameIndex];
      return speed == null || direction == null ? null : ({ speed, direction } as const);
    },
    (point, { speed, direction }) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [point.longitude, point.latitude] },
      properties: { speed, bearing: (direction + 180) % 360 },
    }),
  );
}

/** 格子の`index`番目の時刻の風を、格子点ごとの矢印（gridMark）にする。 */
export function windArrows(grid: readonly WindGridPoint[], index: number): DynamicWeatherRenderPayload {
  return { kind: "gridMark", geojson: windGridToFeatureCollection(grid, index) };
}

// 格子間隔（度）。backend/app/domain/wind_grid.pyの同名定数と一致させる必要があるが、
// APIレスポンス自体には間隔情報が含まれない（点の配列のみ）。他の生成物
// （axis-catalog.json等）と同じ片側importへ揃え、backend/scripts/export_openapi.pyが
// 書き出すwind-grid-config.jsonを単一の情報源とする。降水延長予報のgridFill表現
// （precipitationNowcast.ts）がセルの1辺の長さとして使う。
export const WIND_GRID_SPACING_DEG = windGridConfig.spacing_deg;

export interface MapViewport {
  west: number;
  south: number;
  east: number;
  north: number;
  zoom: number;
}

// 詳細格子を出す最低ズーム。これ未満は広域の粗い格子（既存のgetWindGrid）
// だけで足りると判断（狭い範囲を詳細に見るための機能のため）。
export const WIND_DETAIL_MIN_ZOOM = 10;

// ズーム依存の詳細格子間隔。風の矢印のicon-size（ズームに応じて表示サイズを拡大、MapView.tsx:
// 記号の拡大式）はピクセル単位の記号なのでこの補正で足りるが、
// gridFillのセルは「1格子点が担当する実面積」を表す図形のため、表示サイズだけを縮めても
// 隙間ができるだけで解決しない。根本原因は「同じ間隔の格子が、ズームインするほど画面上の
// 面積を大きく占めて色の段差（ゴワゴワ）が目立つ」ことなので、ズームが進むほど格子間隔
// 自体を細かくする。段階は離散値のみ（連続値にすると閲覧者ごとにラティスの絶対座標が
// わずかにずれ、generate_wind_grid_detail_pointsのキャッシュ共有が効かなくなるため）。
// 間隔の値そのものはwind-grid-config.json（detail_allowed_spacings_deg、backend/app/
// domain/wind_grid.py: WIND_GRID_DETAIL_ALLOWED_SPACINGS_DEGが単一の情報源）
// から取る。zoom境界（10/13/16/19、記号の拡大曲線と同じ刻み）は
// 地図の見た目に関するUI側の判断のためフロント固有の定数として持つ。
const WIND_GRID_DETAIL_SPACING_ZOOM_BREAKPOINTS: readonly number[] = [WIND_DETAIL_MIN_ZOOM, 13, 16, 19];
const WIND_GRID_DETAIL_SPACING_STOPS: readonly { zoom: number; spacingDeg: number }[] =
  WIND_GRID_DETAIL_SPACING_ZOOM_BREAKPOINTS.map((zoom, i) => ({
    zoom,
    spacingDeg: windGridConfig.detail_allowed_spacings_deg[i],
  }));

/** 現在のズームから、詳細格子を要求するときの格子間隔（度）を求める。
 * WIND_GRID_DETAIL_SPACING_STOPSのうちzoom以下の段階で最も細かい（配列は昇順前提）もの。
 * 詳細格子を取るのはWIND_DETAIL_MIN_ZOOM以上だけなので、最初の段階が最も粗い間隔になる。 */
export function windGridDetailSpacingDegForZoom(zoom: number): number {
  let spacingDeg = WIND_GRID_DETAIL_SPACING_STOPS[0].spacingDeg;
  for (const stop of WIND_GRID_DETAIL_SPACING_STOPS) {
    if (zoom >= stop.zoom) spacingDeg = stop.spacingDeg;
  }
  return spacingDeg;
}

// 1回のリクエストで許容するbboxの最大幅・高さ（度）を、格子間隔から逆算する係数。
// wind-grid-config.jsonのdetail_max_points（900、backend/app/domain/wind_grid.py:
// WIND_GRID_DETAIL_MAX_POINTSが単一の情報源）に対し、1辺25間隔（26×26=676点）で
// 余裕を持たせる（以前の固定値0.5度＝0.02度間隔×25と同じ安全率を、間隔が変わっても保つ）。
// 25という係数自体は「間隔から逆算する安全率」という設計判断で、configの値の複製ではない。
// ただし**点数の上限を超えられない形で持つ**——`min`で挟んでおけば、backend側の上限が
// 下がっても自動で従う。見張る検査は要らない（超える状態を作れないため）。
const WIND_DETAIL_MAX_BBOX_SPAN_SIDE_INTERVALS = Math.min(
  25,
  Math.floor(Math.sqrt(windGridConfig.detail_max_points)) - 1,
);

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
