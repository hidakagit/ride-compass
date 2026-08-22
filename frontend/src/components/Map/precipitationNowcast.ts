// 気象庁 降水ナウキャストのタイル・時刻一覧クライアント（改善計画T170/T171）。
//
// 実況（targetTimes_N1、basetime=validtime、5分毎更新）と60分先までの予測
// （targetTimes_N2、basetimeは最新実行時刻で固定・validtimeが5分刻みで先へ進む）を
// 1つの時系列へ束ねる。タイルURLの構造はbosai系（気象庁の非公式API、公式サポート無し。
// 政府標準利用規約準拠・出典明記で利用可）の実際の通信を確認して得た（2026-08-20、
// Playwrightでhttps://www.jma.go.jp/bosai/nowc/ のネットワークリクエストを観測）。
// CORS設定が無いためcanvas経由のピクセル読み取りはできないが、MapLibreのラスタタイルとして
// 表示するだけなら問題なく読み込める（同じくPlaywrightで実機確認済み）。
//
// T183（動的気象レイヤーの再設計）で、気象庁ナウキャスト（+60分が上限、JMA提供APIの
// 仕様上の制約で回避不可）より先の時間帯を、風と共通の格子点マップ（windLayer.ts、
// 自前実装・Open-Meteo REST API経由・約48時間先まで）が相乗りで返すprecipitation_mmを
// 使って延長した。「降水」の地図チップ・時刻スライダーは1つのまま（ユーザー要望「アイコンは
// 1つ。ただし内部は時間によって使い分けて」「1要素でもデータの取り方が複数あり得る。
// これはデータ取得層Nだが、差異はデータ取得層で吸収。画面表示時にはそれは意識しない
// ようにしたい」）とし、2ソースの統合をこのファイル（precipitationFrames）が担い、
// 表示層（page.tsx/MapView.tsx）へはdynamicWeather.tsの共通契約（DynamicWeatherFrame/
// DynamicWeatherRenderPayload）だけを渡す。

import { gridCellRing, type DynamicWeatherFrame, type DynamicWeatherRenderPayload } from "@/components/Map/dynamicWeather";
import { fetchJmaTargetTimes, parseValidtime, trimToCurrentAndFuture, type JmaNowcastFrame } from "@/components/Map/jmaNowcastFrames";
import { parseJstTime } from "@/components/Map/windLayer";
import type { WindGridPoint } from "@/types/weather";

export type NowcastFrame = JmaNowcastFrame;

// parseValidtime・trimToCurrentAndFuture（改善計画T204でjmaNowcastFrames.tsへ抽出、
// 雷ナウキャストと共有する汎用ロジック）はこのファイルからも既存の呼び出し元（page.tsx）
// の import パスを変えずに使えるよう再エクスポートする。
export { parseValidtime, trimToCurrentAndFuture };

const TARGET_TIMES_N1_URL = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N1.json";
const TARGET_TIMES_N2_URL = "https://www.jma.go.jp/bosai/jmatile/data/nowc/targetTimes_N2.json";

/** 実況・予測を合わせた時系列を、validtime昇順（過去→未来）で返す。片方の取得だけ
 * 失敗しても、もう片方が使えるなら部分的な時系列を返す（両方失敗したときだけ例外）。 */
export async function fetchNowcastFrames(): Promise<NowcastFrame[]> {
  const results = await Promise.allSettled([
    fetchJmaTargetTimes(TARGET_TIMES_N1_URL, "降水ナウキャスト"),
    fetchJmaTargetTimes(TARGET_TIMES_N2_URL, "降水ナウキャスト"),
  ]);
  const [n1, n2] = results;
  if (n1.status === "rejected" && n2.status === "rejected") {
    throw n1.reason;
  }
  const frames: NowcastFrame[] = [
    ...(n1.status === "fulfilled" ? n1.value.map((t) => ({ ...t, isForecast: false })) : []),
    ...(n2.status === "fulfilled" ? n2.value.map((t) => ({ ...t, isForecast: true })) : []),
  ];
  frames.sort((a, b) => a.validtime.localeCompare(b.validtime));
  return frames;
}

// 降水強度→色の対応。20mm/h以上の境界値（mm/h）は気象庁公式の「雨の強さと降り方」の分類
// （https://www.jma.go.jp/jma/kishou/know/yougo_hp/amehyo.html、2026-08-20確認）と同じ。
// 同ページに公式区分の無い20mm/h未満は、実機フィードバック「雨の凡例をもっと細かく」
// （他の天気アプリの雨雲レーダー凡例画面を参考画像として提示された。0.4/2/4/10mm/hの
// 4段階境界と「ポツポツ」「パラパラ」「ザーッ」「ザーザー」という体感表現は、気象庁の
// 「雨の程度を表すことば」ページにも載っている一般的な天気アプリの慣用表現であり
// 特定アプリ固有のものではないためこちらでも採用。ブランド固有のアイコン・配色までは
// 再現しない）を受け、10mm/h未満を0.4/2/4mm/hの境界で3段階、10〜20mm/hをさらに1段
// （「弱い雨」からの独立表示ではなく気象庁の用語「ザーザー」寄りの体感表現に統一）へ
// 細分化している。一方で色そのものは気象庁がタイル配色のカラーコードを公開していないため、
// 同庁のナウキャスト・レーダー系地図で一般的な「弱い＝青→強い＝紫」の配色慣習に沿った
// 近似値であり、実際のタイル画像の色と厳密には一致しない（凡例としての目安）。地図チップの
// 凡例（PRECIPITATION_INTENSITY_LEVELS）とT183の延長予報の塗り（MapView.tsx側の
// fill-color）の両方がこの配列を単一の情報源として使う（windLayer.tsのWIND_SPEED_COLOR_
// STOPSと同じ「片側import」の考え方）。
export const PRECIPITATION_COLOR_STOPS: readonly { mmPerHour: number; color: string }[] = [
  { mmPerHour: 0, color: "#e0f2fe" },
  { mmPerHour: 0.4, color: "#bae6fd" },
  { mmPerHour: 2, color: "#7dd3fc" },
  { mmPerHour: 4, color: "#38bdf8" },
  { mmPerHour: 10, color: "#3b82f6" },
  { mmPerHour: 20, color: "#eab308" },
  { mmPerHour: 30, color: "#f97316" },
  { mmPerHour: 50, color: "#dc2626" },
  { mmPerHour: 80, color: "#9333ea" },
];

// 延長予報の塗り（gridFill）でこの値未満は「ほぼ降水なし」として非表示にする（windLayer.tsの
// WIND_CALM_THRESHOLD_MSと同じ考え方）。0（完全な無降水）まで含めると格子点624点ぶんの
// セルが常時全域を埋め尽くしてしまうため、視覚的なノイズを避ける小さな閾値を設ける。
export const PRECIPITATION_NONE_THRESHOLD_MM = 0.1;

// 降水強度の凡例（地図チップ、page.tsx、実機フィードバック「風と雨の凡例も欲しい」）。
// 数値はPRECIPITATION_COLOR_STOPSからそのまま持ってくるため、境界値・色を変えてもここは
// 自動で追従する（windLayer.tsのWIND_SPEED_LEGEND_LEVELSと同じパターン）。
export const PRECIPITATION_INTENSITY_LEVELS: readonly { key: string; label: string; color: string }[] = [
  {
    key: "negligible",
    label: `ごく弱い雨（${PRECIPITATION_COLOR_STOPS[1].mmPerHour}mm/h未満）`,
    color: PRECIPITATION_COLOR_STOPS[0].color,
  },
  {
    key: "pattering",
    label: `ポツポツ（${PRECIPITATION_COLOR_STOPS[1].mmPerHour}〜${PRECIPITATION_COLOR_STOPS[2].mmPerHour}mm/h）`,
    color: PRECIPITATION_COLOR_STOPS[1].color,
  },
  {
    key: "drizzling",
    label: `パラパラ（${PRECIPITATION_COLOR_STOPS[2].mmPerHour}〜${PRECIPITATION_COLOR_STOPS[3].mmPerHour}mm/h）`,
    color: PRECIPITATION_COLOR_STOPS[2].color,
  },
  {
    key: "showering",
    label: `ザーッ（${PRECIPITATION_COLOR_STOPS[3].mmPerHour}〜${PRECIPITATION_COLOR_STOPS[4].mmPerHour}mm/h）`,
    color: PRECIPITATION_COLOR_STOPS[3].color,
  },
  {
    key: "pouring",
    label: `ザーザー（${PRECIPITATION_COLOR_STOPS[4].mmPerHour}〜${PRECIPITATION_COLOR_STOPS[5].mmPerHour}mm/h）`,
    color: PRECIPITATION_COLOR_STOPS[4].color,
  },
  {
    key: "strong",
    label: `強い雨（${PRECIPITATION_COLOR_STOPS[5].mmPerHour}〜${PRECIPITATION_COLOR_STOPS[6].mmPerHour}mm/h）`,
    color: PRECIPITATION_COLOR_STOPS[5].color,
  },
  {
    key: "intense",
    label: `激しい雨（${PRECIPITATION_COLOR_STOPS[6].mmPerHour}〜${PRECIPITATION_COLOR_STOPS[7].mmPerHour}mm/h）`,
    color: PRECIPITATION_COLOR_STOPS[6].color,
  },
  {
    key: "very-intense",
    label: `非常に激しい雨（${PRECIPITATION_COLOR_STOPS[7].mmPerHour}〜${PRECIPITATION_COLOR_STOPS[8].mmPerHour}mm/h）`,
    color: PRECIPITATION_COLOR_STOPS[7].color,
  },
  { key: "violent", label: `猛烈な雨（${PRECIPITATION_COLOR_STOPS[8].mmPerHour}mm/h以上）`, color: PRECIPITATION_COLOR_STOPS[8].color },
];

/** 降水ナウキャストのラスタタイルURLテンプレート（{z}/{x}/{y}はMapLibreが実際の値へ
 * 展開するプレースホルダ、置換せずそのまま埋め込む）。 */
function nowcastTileUrlTemplate(frame: NowcastFrame): string {
  return `https://www.jma.go.jp/bosai/jmatile/data/nowc/${frame.basetime}/none/${frame.validtime}/surf/hrpns/{z}/{x}/{y}.png`;
}

export interface PrecipitationGridCellProperties {
  /** 降水量（mm/h相当）。 */
  mmPerHour: number;
}

/** grid（風と共通の格子点マップ、windLayer.ts参照）のframeIndex番目の時刻ぶんの降水量を、
 * 各格子点を中心とする1辺spacingDegの正方形セル（gridCellRing、dynamicWeather.ts参照）の
 * FeatureCollectionへ変換する。frameIndexが範囲外、または値が欠損している格子点はスキップ
 * する（1点の欠損で全体を落とさない）。「ほぼ降水なし」の間引き（PRECIPITATION_NONE_
 * THRESHOLD_MM）はここでは行わない（風の矢印と同じくMapLibre側のfilterに任せる）。 */
function precipitationGridToCellFeatureCollection(
  grid: readonly WindGridPoint[],
  frameIndex: number,
  spacingDeg: number
): GeoJSON.FeatureCollection<GeoJSON.Polygon, PrecipitationGridCellProperties> {
  const features: GeoJSON.Feature<GeoJSON.Polygon, PrecipitationGridCellProperties>[] = [];
  for (const point of grid) {
    const mmPerHour = point.precipitation_mm[frameIndex];
    if (mmPerHour == null) continue;
    features.push({
      type: "Feature",
      geometry: { type: "Polygon", coordinates: [gridCellRing(point.latitude, point.longitude, spacingDeg)] },
      properties: { mmPerHour },
    });
  }
  return { type: "FeatureCollection", features };
}

/** 降水フレームの内部参照。sourceが"nowcast"なら気象庁ナウキャスト（実況〜60分先、
 * 5分刻み）由来でindexはnowcastFrames内のindex、"extended"なら風と共通の格子点マップ
 * （自前実装、約48時間先まで・1時間刻み）由来でindexはそのgridのtimes/precipitation_mm内の
 * indexを指す。precipitationRenderPayloadだけがこの型を解釈する（表示層はDynamicWeatherFrame
 * のtimeしか見ない、ファイル冒頭のコメント参照）。 */
export type PrecipitationFrameRef = { source: "nowcast"; index: number } | { source: "extended"; index: number };

/** 気象庁ナウキャスト（0〜60分、5分刻み）と風と共通の格子点マップ由来の延長予報
 * （60分以降、約48時間先まで・1時間刻み）を1つのフレーム列へ統合する（データ取得層での
 * 差異吸収、ファイル冒頭のコメント参照）。extendedGridはnowcastの最終フレーム以前の時刻を
 * 含みうる（windGridは常に「現在」から始まるため）が、ナウキャストと重複する近い将来を
 * 延長予報側でも出すと同じ時間帯が二重に見えて紛らわしいため、ナウキャストの最終フレームより
 * 後の時刻だけを延長側として採用する。 */
export function precipitationFrames(
  nowcastFrames: readonly NowcastFrame[],
  extendedGrid: readonly WindGridPoint[]
): DynamicWeatherFrame<PrecipitationFrameRef>[] {
  const nowcastPart: DynamicWeatherFrame<PrecipitationFrameRef>[] = nowcastFrames.map((frame, index) => ({
    time: parseValidtime(frame.validtime),
    ref: { source: "nowcast", index },
  }));

  const lastNowcastMs =
    nowcastFrames.length > 0 ? parseValidtime(nowcastFrames[nowcastFrames.length - 1].validtime).getTime() : -Infinity;
  const extendedTimes = extendedGrid[0]?.times ?? [];
  const extendedPart: DynamicWeatherFrame<PrecipitationFrameRef>[] = [];
  extendedTimes.forEach((time, index) => {
    const parsedTime = parseJstTime(time);
    if (parsedTime.getTime() <= lastNowcastMs) return;
    extendedPart.push({ time: parsedTime, ref: { source: "extended", index } });
  });

  return [...nowcastPart, ...extendedPart];
}

/** precipitationFramesが返したrefから、地図へ渡す描画ペイロードを組み立てる。sourceで
 * rasterTile（気象庁ナウキャストのタイル）とgridFill（延長予報、格子を色で塗る）を
 * 切り替える——「アイコンは1つ。ただし内部は時間によって使い分けて」というユーザー要望を
 * ここで実現する。spacingDegはextendedGridの実際の格子間隔（度）を呼び出し側が渡す
 * （useWeatherGrid.tsのeffectiveGridSpacingDeg、T185でズーム依存の詳細間隔になったため、
 * このファイル自身は「粗いか詳細か」の判定を持たず、渡された値をそのまま使うだけにする）。 */
export function precipitationRenderPayload(
  nowcastFrames: readonly NowcastFrame[],
  extendedGrid: readonly WindGridPoint[],
  spacingDeg: number,
  ref: PrecipitationFrameRef
): DynamicWeatherRenderPayload | undefined {
  if (ref.source === "nowcast") {
    const frame = nowcastFrames[ref.index];
    return frame ? { kind: "rasterTile", tileUrlTemplate: nowcastTileUrlTemplate(frame) } : undefined;
  }
  if (extendedGrid.length === 0) return undefined;
  return { kind: "gridFill", geojson: precipitationGridToCellFeatureCollection(extendedGrid, ref.index, spacingDeg) };
}
