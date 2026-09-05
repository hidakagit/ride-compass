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
// 風と共通の格子点マップ（windLayer.ts、自前実装・Open-Meteo REST API経由・約48時間先
// まで）が相乗りで返すprecipitation_mmを使って延長する。この延長予報とナウキャストの間に
// 気象庁 降水短時間予報（rasrf、60分〜15時間先、数値予報モデルによる予測）を挿入し、
// 3段構成にしている——rasrfの範囲まではJMA公式データ（精度が高い方から: ナウキャスト
// [実況の外挿]→rasrf[数値予報モデル]）、それ以降はOpen-Meteoの粗いモデル予報という
// 優先順位。「降水」の地図チップ・時刻スライダーは1つのままとし、3ソースの統合をこの
// ファイル（precipitationFrames）が担い、表示層（page.tsx/MapView.tsx）へはdynamicWeather.ts
// の共通契約（DynamicWeatherFrame/DynamicWeatherRenderPayload）だけを渡す。

import {
  gridCellRing,
  gridToFeatureCollection,
  type DynamicWeatherFrame,
  type DynamicWeatherRenderPayload,
} from "@/components/Map/dynamicWeather";
import { JMA_TILE_BASE_URL, fetchJmaTargetTimes, parseValidtime, trimToCurrentAndFuture, type JmaNowcastFrame } from "@/components/Map/jmaNowcastFrames";
import { fetchJson } from "@/lib/fetchJson";
import { tileBaseUrl } from "@/lib/tileBaseUrl";
import { parseJstTime } from "@/components/Map/windLayer";
import type { WindGridPoint } from "@/types/weather";

export type NowcastFrame = JmaNowcastFrame;

// parseValidtime・trimToCurrentAndFuture（jmaNowcastFrames.tsで定義、
// 雷ナウキャストと共有する汎用ロジック）はこのファイルからも既存の呼び出し元（page.tsx）
// の import パスを変えずに使えるよう再エクスポートする。
export { parseValidtime, trimToCurrentAndFuture };

const TARGET_TIMES_N1_URL = `${JMA_TILE_BASE_URL}/jmatile/data/nowc/targetTimes_N1.json`;
const TARGET_TIMES_N2_URL = `${JMA_TILE_BASE_URL}/jmatile/data/nowc/targetTimes_N2.json`;

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
// 組み合わせになりうるため、**必ずelements.includes("rasrf")で絞り込んでから**
// 「異なるvalidtimeの種類数が複数ある最新のbasetime」を選ぶ（絞り込み後は同一
// (basetime, validtime, member)にrasrf行が高々1つのため、複数行の優先順位付けは不要）。
const RASRF_TARGET_TIMES_URL = `${JMA_TILE_BASE_URL}/jmatile/data/rasrf/targetTimes.json`;

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

/** rawの中から、指定member・rasrf搭載行に絞ったうえで、最も新しい「異なるvalidtimeを
 * 複数持つbasetime」（＝完全な予報ラン、単発の中間ランではない）のフレームだけを返す。
 * 該当が無ければ空配列。 */
function latestFullRunFrames(raw: readonly RawRasrfTargetTime[], member: string): RawRasrfTargetTime[] {
  const entries = raw.filter((e) => e.member === member && e.elements.includes("rasrf"));
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
  const data = await fetchJson<unknown>(RASRF_TARGET_TIMES_URL, {
    timeoutMs: 15000,
    category: "api:jma-nowcast-times",
    errorLabel: "降水短時間予報の時刻一覧",
  });
  if (!Array.isArray(data)) throw new Error("降水短時間予報の時刻一覧の形式が想定と異なります");
  const raw = data as RawRasrfTargetTime[];

  const byValidtime = new Map<string, RasrfFrame>();
  for (const e of latestFullRunFrames(raw, "none")) {
    byValidtime.set(e.validtime, { basetime: e.basetime, validtime: e.validtime, isForecast: true, member: e.member });
  }
  for (const e of latestFullRunFrames(raw, "immed")) {
    byValidtime.set(e.validtime, { basetime: e.basetime, validtime: e.validtime, isForecast: true, member: e.member });
  }
  return [...byValidtime.values()].sort((a, b) => a.validtime.localeCompare(b.validtime));
}

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
// （https://www.jma.go.jp/jma/kishou/know/yougo_hp/amehyo.html）と同じ。
// 同ページに公式区分の無い20mm/h未満は、0.4/2/4/10mm/hの4段階境界と「ポツポツ」
// 「パラパラ」「ザーッ」「ザーザー」という体感表現を採用する——気象庁の「雨の程度を
// 表すことば」ページにも載っている一般的な天気アプリの慣用表現であり、特定アプリ固有の
// ものではない（ブランド固有のアイコン・配色までは再現しない）。10mm/h未満を
// 0.4/2/4mm/hの境界で3段階、10〜20mm/hをさらに1段（「弱い雨」からの独立表示ではなく
// 気象庁の用語「ザーザー」寄りの体感表現に統一）へ細分化している。一方で色そのものは
// 気象庁がタイル配色のカラーコードを公開していないため、同庁のナウキャスト・レーダー系
// 地図で一般的な「弱い＝青→強い＝紫」の配色慣習に沿った近似値であり、実際のタイル画像の
// 色と厳密には一致しない（凡例としての目安）。地図チップの凡例
// （PRECIPITATION_INTENSITY_LEVELS）と延長予報の塗り（MapView.tsx側のfill-color）の
// 両方がこの配列を単一の情報源として使う（windLayer.tsのWIND_SPEED_COLOR_STOPSと同じ
// 「片側import」の考え方）。
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

// 降水強度の凡例（地図チップ、page.tsx）。
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
  return `${tileBaseUrl()}${JMA_TILE_BASE_URL}/jmatile/data/nowc/${frame.basetime}/none/${frame.validtime}/surf/hrpns/{z}/{x}/{y}.png`;
}

/** 降水短時間予報のラスタタイルURLテンプレート。ナウキャストと異なりmemberがURLパスに
 * そのまま入る（"immed"/"none"、fetchRasrfFrames参照）。 */
function rasrfTileUrlTemplate(frame: RasrfFrame): string {
  return `${tileBaseUrl()}${JMA_TILE_BASE_URL}/jmatile/data/rasrf/${frame.basetime}/${frame.member}/${frame.validtime}/surf/rasrf/{z}/{x}/{y}.png`;
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
  return gridToFeatureCollection(
    grid,
    (point) => point.precipitation_mm[frameIndex] ?? null,
    (point, mmPerHour) => ({
      type: "Feature",
      geometry: { type: "Polygon", coordinates: [gridCellRing(point.latitude, point.longitude, spacingDeg)] },
      properties: { mmPerHour },
    })
  );
}

/** 降水フレームの内部参照。sourceが"nowcast"なら気象庁ナウキャスト（実況〜60分先、
 * 5分刻み、レーダー実況の外挿）由来でindexはnowcastFrames内のindex、"rasrf"なら気象庁
 * 降水短時間予報（60分〜15時間先、数値予報モデルによる予測）由来で
 * indexはrasrfFrames内のindex、"extended"なら風と共通の格子点マップ（Open-Meteo経由、
 * 15時間先以降・約48時間先まで・1時間刻み）由来でindexはそのgridのtimes/precipitation_mm
 * 内のindexを指す。3段は精度の性質が異なる（nowcast=実況外挿で直近ほど高信頼、
 * rasrf=数値予報モデルによる予測、extended=Open-Meteoの粗いモデル予報）。
 * precipitationRenderPayloadだけがこの型を解釈する（表示層はDynamicWeatherFrameのtimeしか
 * 見ない、ファイル冒頭のコメント参照）。 */
export type PrecipitationFrameRef =
  | { source: "nowcast"; index: number }
  | { source: "rasrf"; index: number }
  | { source: "extended"; index: number };

/** 気象庁ナウキャスト（0〜60分）・降水短時間予報（60分〜15時間先）・
 * 風と共通の格子点マップ由来の延長予報（15時間先以降、約48時間先まで）を1つのフレーム列へ
 * 統合する（データ取得層での差異吸収、ファイル冒頭のコメント参照）。各段は前段の最終フレーム
 * より後の時刻だけを採用する（近い将来の二重表示を避ける、nowcast→rasrfの境界も
 * rasrf→extendedの境界も同じ考え方）。rasrfFramesが空（取得失敗等）の場合はnowcastの
 * 直後からextendedを採用する形へ自然にフォールバックする。 */
export function precipitationFrames(
  nowcastFrames: readonly NowcastFrame[],
  rasrfFrames: readonly RasrfFrame[],
  extendedGrid: readonly WindGridPoint[]
): DynamicWeatherFrame<PrecipitationFrameRef>[] {
  const nowcastPart: DynamicWeatherFrame<PrecipitationFrameRef>[] = nowcastFrames.map((frame, index) => ({
    time: parseValidtime(frame.validtime),
    ref: { source: "nowcast", index },
  }));
  const lastNowcastMs =
    nowcastFrames.length > 0 ? parseValidtime(nowcastFrames[nowcastFrames.length - 1].validtime).getTime() : -Infinity;

  const rasrfPart: DynamicWeatherFrame<PrecipitationFrameRef>[] = [];
  let lastRasrfMs = lastNowcastMs;
  rasrfFrames.forEach((frame, index) => {
    const parsedTime = parseValidtime(frame.validtime);
    if (parsedTime.getTime() <= lastNowcastMs) return;
    rasrfPart.push({ time: parsedTime, ref: { source: "rasrf", index } });
    lastRasrfMs = Math.max(lastRasrfMs, parsedTime.getTime());
  });

  const extendedTimes = extendedGrid[0]?.times ?? [];
  const extendedPart: DynamicWeatherFrame<PrecipitationFrameRef>[] = [];
  extendedTimes.forEach((time, index) => {
    const parsedTime = parseJstTime(time);
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
  nowcastFrames: readonly NowcastFrame[],
  rasrfFrames: readonly RasrfFrame[],
  extendedGrid: readonly WindGridPoint[],
  spacingDeg: number,
  ref: PrecipitationFrameRef
): DynamicWeatherRenderPayload | undefined {
  if (ref.source === "nowcast") {
    const frame = nowcastFrames[ref.index];
    return frame ? { kind: "rasterTile", tileUrlTemplate: nowcastTileUrlTemplate(frame) } : undefined;
  }
  if (ref.source === "rasrf") {
    const frame = rasrfFrames[ref.index];
    return frame ? { kind: "rasterTile", tileUrlTemplate: rasrfTileUrlTemplate(frame) } : undefined;
  }
  if (extendedGrid.length === 0) return undefined;
  return { kind: "gridFill", geojson: precipitationGridToCellFeatureCollection(extendedGrid, ref.index, spacingDeg) };
}
