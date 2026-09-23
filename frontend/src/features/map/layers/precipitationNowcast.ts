// 気象庁 降水ナウキャストのタイル・時刻一覧クライアント。
//
// 実況（targetTimes_N1、basetime=validtime、5分毎更新）と60分先までの予測
// （targetTimes_N2、basetimeは最新実行時刻で固定・validtimeが5分刻みで先へ進む）を
// 1つの時系列へ束ねる。タイルURLの構造はbosai系（気象庁の非公式API、公式サポート無し。
// 政府標準利用規約準拠・出典明記で利用可）の実際の通信を観測して得た。
// CORS設定が無いためcanvas経由のピクセル読み取りはできないが、MapLibreのラスタタイルとして
// 表示するだけなら問題なく読み込める。
//
// 気象庁ナウキャスト（+60分が上限、JMA提供APIの仕様上の制約で回避不可）より先の時間帯を、
// 風と共通の格子点マップ（windLayer.ts、自前実装・気象庁MSM由来・1〜3日先
// まで）が相乗りで返すprecipitation_mmを使って延長する。この延長予報とナウキャストの間に
// 気象庁 降水短時間予報（rasrf、60分〜15時間先、数値予報モデルによる予測）を挿入し、
// 3段構成にしている——rasrfの範囲まではJMA公式データ（精度が高い方から: ナウキャスト
// [実況の外挿]→rasrf[数値予報モデル]）、それ以降はMSMの粗いモデル予報という
// 優先順位。「降水」の地図チップ・時刻スライダーは1つのままとし、3ソースの統合をこの
// ファイル（precipitationFrames）が担い、表示層（page.tsx/MapView.tsx）へはdynamicWeather.ts
// の共通契約（DynamicWeatherFrame/DynamicWeatherRenderPayload）だけを渡す。

import weatherScales from "@/types/generated/weather-scales.json";
import { buildRangeLegendBands, type MapColorLegendBand } from "@/lib/mapDisplay/mapColorLegend";
import {
  gridCellRing,
  gridToFeatureCollection,
  type DynamicWeatherFrame,
  type DynamicWeatherRenderPayload,
} from "@/features/map/layers/dynamicWeather";
import {
  fetchJmaNowcastFrames,
  fetchJmaTargetTimes,
  jmaDelivery,
  parseValidtime,
  type JmaNowcastFrame,
  jmaTilePayload,
} from "@/features/map/layers/jmaNowcastFrames";
import { parseJstLocalValue } from "@/lib/time";
import type { WindGridPoint } from "@/types/weather";

/** 降水の`main`ラスタの時刻の段（源泉`precipitationNowcast/main`の配信要素の並び。近い時刻から）。
 * 段ごとに時刻一覧の読み方が違う（実況の外挿と数値予報のラン）ため、段はここで名指す。 */
const MAIN_SOURCE = "precipitationNowcast/main";
const NOWCAST_STAGE = 0;
const SHORT_RANGE_STAGE = 1;

// 気象庁 降水短時間予報（rasrf）。ナウキャスト（実況の外挿、60分先が上限）とは異なり
// 数値予報モデルによる正真正銘の「予測」で、最大15時間先まで存在する。
// targetTimes.jsonは`member`フィールドを持ち、"immed"（直近0〜6時間、高頻度更新の
// 詳細予報）と"none"（7〜15時間先、毎正時更新の延長予報）の2系統が混在する。ナウキャストの
// N1/N2と違い、同じmember内にも「毎正時の完全な複数validtime群」と「10分毎の中間ランが
// 返す単発validtime（basetime===validtime）」が混在するため、単純に「最新basetime」を
// 取るだけでは不十分——中間ランを拾うと1フレームしか得られない。**加えて**、同じ
// targetTimes.jsonには線状降水帯予測マップ（sjfcstmap、rasrfとは別プロダクト）も混在し、
// 同一(basetime, validtime, member)に対しrasrf無し・sjfcstmapのみのelementsを持つ行が
// 別途存在しうる（本番相当データで114行中73行がelementsにrasrfを含まないsjfcstmap単体
// 行だった）。これらは「異なるvalidtimeの
// 種類数」を数える際にノイズになる上、そのままタイルURLを組み立てるとrasrf画像が存在しない
// 組み合わせになりうるため、**必ず降水短時間予報の要素idを持つ行へ絞り込んでから**
// 「異なるvalidtimeの種類数が複数ある最新のbasetime」を選ぶ（絞り込み後は同一
// (basetime, validtime, member)にrasrf行が高々1つのため、複数行の優先順位付けは不要）。

interface RawRasrfTargetTime {
  basetime: string;
  validtime: string;
  member: string;
  elements: string[];
}

export interface RasrfFrame extends JmaNowcastFrame {
  /** タイルURLのパス階層（"immed"=直近0〜6時間、"none"=7〜15時間先）。ナウキャストの
   * URLは常にmember="none"固定だったため`JmaNowcastFrame`自体には無いフィールド。 */
  member: string;
}

/** rawの中から、指定member・その要素を載せた行に絞ったうえで、最も新しい「異なるvalidtimeを
 * 複数持つbasetime」（＝完全な予報ラン、単発の中間ランではない）のフレームだけを返す。
 * 該当が無ければ空配列。 */
function latestFullRunFrames(
  raw: readonly RawRasrfTargetTime[],
  elementId: string,
  member: string,
): RawRasrfTargetTime[] {
  const entries = raw.filter((e) => e.member === member && e.elements.includes(elementId));
  const validtimesByBasetime = new Map<string, Set<string>>();
  for (const e of entries) {
    if (!validtimesByBasetime.has(e.basetime)) validtimesByBasetime.set(e.basetime, new Set());
    validtimesByBasetime.get(e.basetime)!.add(e.validtime);
  }
  const fullRunBasetimes = [...validtimesByBasetime.entries()]
    .filter(([, validtimes]) => validtimes.size > 1)
    .map(([basetime]) => basetime);
  if (fullRunBasetimes.length === 0) return [];
  const latestBasetime = fullRunBasetimes.sort().at(-1);
  return entries.filter((e) => e.basetime === latestBasetime);
}

/** 降水短時間予報の時刻一覧を取得し、直近0〜6時間（member="immed"）と7〜15時間先
 * （member="none"）それぞれの最新の完全な予報ランを1本の時系列へ統合する。両者は
 * validtimeの範囲が重ならない設計だが、念のためvalidtime重複時は
 * より詳細なimmed側を優先する（Map.setで後勝ちにするため、noneを先に積む）。 */
export async function fetchRasrfFrames(): Promise<RasrfFrame[]> {
  const delivery = jmaDelivery(MAIN_SOURCE, SHORT_RANGE_STAGE);
  const raw = await fetchJmaTargetTimes<RawRasrfTargetTime>(delivery, "降水短時間予報");

  const byValidtime = new Map<string, RasrfFrame>();
  for (const e of latestFullRunFrames(raw, delivery.id, "none")) {
    byValidtime.set(e.validtime, { basetime: e.basetime, validtime: e.validtime, isForecast: true, member: e.member });
  }
  for (const e of latestFullRunFrames(raw, delivery.id, "immed")) {
    byValidtime.set(e.validtime, { basetime: e.basetime, validtime: e.validtime, isForecast: true, member: e.member });
  }
  return [...byValidtime.values()].sort((a, b) => a.validtime.localeCompare(b.validtime));
}

/** 実況・予測を合わせた時系列。実況と予測は別々の時刻一覧に載り、片方の取得だけ失敗しても、
 * もう片方が使えるなら部分的な時系列を返す（両方失敗したときだけ例外、`fetchJmaTargetTimes`）。 */
export function fetchNowcastFrames(): Promise<JmaNowcastFrame[]> {
  return fetchJmaNowcastFrames(MAIN_SOURCE, "降水ナウキャスト");
}

// 降水強度→色の段（帯の下限）と段の呼び名。値・色・呼び名は源泉（backend
// `domain/weather_display.py`）が持ち、延長予報の塗り（`features/map/scene/groups/weather.ts`）と
// 地図チップの凡例の両方がこの並びを使う。気象庁はタイル配色のカラーコードを公開していないため、
// 色はナウキャスト等のタイル画像の色と厳密には一致しない（凡例としての目安）。
export const PRECIPITATION_COLOR_STOPS: readonly { mmPerHour: number; color: string; name: string }[] =
  weatherScales.precipitation.map((stop) => ({ mmPerHour: stop.value, color: stop.color, name: stop.name }));

// 延長予報の塗り（gridFill）でこの値未満は「ほぼ降水なし」として非表示にする（windLayer.tsの
// WIND_CALM_THRESHOLD_MSと同じ考え方）。0（完全な無降水）まで含めると格子点ぶんのセルが
// 常時全域を埋め尽くしてしまうため、視覚的なノイズを避ける小さな閾値を設ける。
export const PRECIPITATION_NONE_THRESHOLD_MM = 0.1;

/** 降水強度の凡例（地図チップ）。色の段1つにつき1行。 */
export const PRECIPITATION_INTENSITY_LEVELS: readonly MapColorLegendBand[] = buildRangeLegendBands(
  PRECIPITATION_COLOR_STOPS.slice(1).map((stop) => stop.mmPerHour),
  PRECIPITATION_COLOR_STOPS.map((stop) => stop.color),
  "mm/h",
  PRECIPITATION_COLOR_STOPS.map((stop) => stop.name),
);

interface PrecipitationGridCellProperties {
  /** 降水量（mm/h相当）。 */
  mmPerHour: number;
}

/** grid（風と共通の格子点マップ、windLayer.ts参照）のframeIndex番目の時刻ぶんの降水量を、
 * 各格子点を中心とする1辺spacingDegの正方形セル（gridCellRing、dynamicWeather.ts参照）の
 * FeatureCollectionへ変換する。frameIndexが範囲外、または値が欠損している格子点はスキップ
 * する（1点の欠損で全体を落とさない）。「ほぼ降水なし」の間引き
 * （PRECIPITATION_NONE_THRESHOLD_MM）はここでは行わない（風の矢印と同じくMapLibre側のfilterに任せる）。 */
function precipitationGridToCellFeatureCollection(
  grid: readonly WindGridPoint[],
  frameIndex: number,
  spacingDeg: number,
): GeoJSON.FeatureCollection<GeoJSON.Polygon, PrecipitationGridCellProperties> {
  return gridToFeatureCollection(
    grid,
    (point) => point.precipitation_mm[frameIndex] ?? null,
    (point, mmPerHour) => ({
      type: "Feature",
      geometry: { type: "Polygon", coordinates: [gridCellRing(point.latitude, point.longitude, spacingDeg)] },
      properties: { mmPerHour },
    }),
  );
}

/** 降水フレームの内部参照。気象庁ナウキャスト（実況〜60分先、5分刻み、レーダー実況の外挿）と
 * 降水短時間予報（60分〜15時間先、数値予報モデルによる予測）はタイルを描くフレームそのもの、
 * 延長予報（風と共通の格子点マップ、MSM由来・1時間刻み）は格子のtimes/precipitation_mm内のindex。
 * 延長予報だけindexなのは、描くときの格子（ズーム依存の詳細格子になりうる）がフレーム列を
 * 作った格子と別物になりうるため。precipitationRenderPayloadだけがこの型を解釈する
 * （表示層はDynamicWeatherFrameのtimeしか見ない）。 */
type PrecipitationFrameRef =
  | { source: "nowcast"; frame: JmaNowcastFrame }
  | { source: "shortRange"; frame: RasrfFrame }
  | { source: "extended"; index: number };

/** 気象庁ナウキャスト（0〜60分）・降水短時間予報（60分〜15時間先）・
 * 風と共通の格子点マップ由来の延長予報（15時間先以降、約48時間先まで）を1つのフレーム列へ
 * 統合する（データ取得層での差異吸収、ファイル冒頭のコメント参照）。各段は前段の最終フレーム
 * より後の時刻だけを採用する（近い将来の二重表示を避ける、nowcast→rasrfの境界も
 * rasrf→extendedの境界も同じ考え方）。rasrfFramesが空（取得失敗等）の場合はnowcastの
 * 直後からextendedを採用する形へ自然にフォールバックする。 */
export function precipitationFrames(
  nowcastFrames: readonly JmaNowcastFrame[],
  rasrfFrames: readonly RasrfFrame[],
  extendedGrid: readonly WindGridPoint[],
): DynamicWeatherFrame<PrecipitationFrameRef>[] {
  const nowcastPart: DynamicWeatherFrame<PrecipitationFrameRef>[] = nowcastFrames.map((frame) => ({
    time: parseValidtime(frame.validtime),
    ref: { source: "nowcast", frame },
  }));
  const lastNowcastMs =
    nowcastFrames.length > 0 ? parseValidtime(nowcastFrames[nowcastFrames.length - 1].validtime).getTime() : -Infinity;

  const rasrfPart: DynamicWeatherFrame<PrecipitationFrameRef>[] = [];
  let lastRasrfMs = lastNowcastMs;
  rasrfFrames.forEach((frame) => {
    const parsedTime = parseValidtime(frame.validtime);
    if (parsedTime.getTime() <= lastNowcastMs) return;
    rasrfPart.push({ time: parsedTime, ref: { source: "shortRange", frame } });
    lastRasrfMs = Math.max(lastRasrfMs, parsedTime.getTime());
  });

  const extendedTimes = extendedGrid[0]?.times ?? [];
  const extendedPart: DynamicWeatherFrame<PrecipitationFrameRef>[] = [];
  extendedTimes.forEach((time, index) => {
    const parsedTime = parseJstLocalValue(time);
    if (parsedTime.getTime() <= lastRasrfMs) return;
    extendedPart.push({ time: parsedTime, ref: { source: "extended", index } });
  });

  return [...nowcastPart, ...rasrfPart, ...extendedPart];
}

/** precipitationFramesが返したrefから、地図へ渡す描画ペイロードを組み立てる。sourceで
 * rasterTile（気象庁ナウキャスト・降水短時間予報のタイル）とgridFill（延長予報、格子を
 * 色で塗る）を切り替える——地図チップ・時刻スライダーは1つのまま、内部で描画方式を
 * 使い分ける。spacingDegはextendedGridの実際の格子間隔（度）を呼び出し側が渡す
 * （useWeatherGrid.tsのeffectiveGridSpacingDeg、ズーム依存の詳細間隔になりうるため、
 * このファイル自身は「粗いか詳細か」の判定を持たず、渡された値をそのまま使うだけにする）。 */
export function precipitationRenderPayload(
  extendedGrid: readonly WindGridPoint[],
  spacingDeg: number,
  ref: PrecipitationFrameRef,
): DynamicWeatherRenderPayload {
  if (ref.source === "nowcast") {
    const { basetime, validtime } = ref.frame;
    return jmaTilePayload(MAIN_SOURCE, { basetime, member: "none", validtime }, NOWCAST_STAGE);
  }
  // 降水短時間予報はナウキャストと異なりmemberがURLパスにそのまま入る（"immed"/"none"、fetchRasrfFrames参照）。
  if (ref.source === "shortRange") return jmaTilePayload(MAIN_SOURCE, ref.frame, SHORT_RANGE_STAGE);
  return { kind: "gridFill", geojson: precipitationGridToCellFeatureCollection(extendedGrid, ref.index, spacingDeg) };
}
