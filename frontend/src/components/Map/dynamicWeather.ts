// 動的気象レイヤー（風・降水など、時刻スライダーで表示内容が変わる格子ベースのレイヤー）の
// 共通契約。設計の柱は4つ（詳細はdocs/modules/frontend/dynamic-weather-layers.md
// 「共通契約（4本柱）」節参照）:
//
// 1. **格子単位は統一**: 全レイヤーが同じ固定ラティス（backend/app/domain/wind_grid.py:
//    WIND_GRID_BBOX、フロント側の対応値はwindLayer.ts: WIND_GRID_SPACING_DEG/
//    WIND_GRID_DETAIL_SPACING_DEG）を共有する。フェッチも共有（hooks/useWeatherGrid.ts、
//    1回のMSM読み出しで全要素ぶんの値を取る）。
// 2. **表現は限られた種類のみ**: 格子中央にマークを出す（gridMark、風パターン）、
//    格子を指定色で塗る（gridFill、雨パターン）、配信元が描画済みの画像を重ねる
//    （rasterTile、気象庁ナウキャスト等）に加え、配信元がMapbox Vector Tile（.pbf）で
//    配信する地物をMapLibre標準のvectorソース+line/fillレイヤーでそのまま描画する
//    （vectorTile、洪水キキクル）。vectorTileは配信元のタイルが地物の
//    プロパティに表示値（例: 危険度レベル）を埋め込み済みのため、gridFill/gridMarkと違い
//    feature-stateやGeoJSON変換によるJS側の値差し込みが不要——MapLibreのpaint式
//    （["get", プロパティ名]）だけで色分けできる点がrasterTileとの主な違い（rasterTileは
//    配信元が色分け済みの画像そのもの、vectorTileは配信元が地物+属性値を配信しこちら側で
//    色分けする）。新しい要素はこの4種のどれかを選ぶだけで、独自の描画方式は増やさない。
// 3. **時間経過はスライドバー1本**: ONの全レイヤーのフレーム時刻を統合した1本のタイムライン
//    （mergeFrameTimes）を共有スライダーへ渡す。各レイヤーは選択時刻に対応する自分のフレームを
//    描画し、**選択時刻が自分のデータ範囲外なら何も描画しない**（frameIndexForTime）。
// 4. **データ取得の差異はデータ層で吸収**: 1要素につきデータソースはN個あり得る
//    （例: 降水=気象庁ナウキャスト+自前格子）。各要素のデータ層モジュール
//    （precipitationNowcast.ts等）がソースを1本のフレーム列へ統合し、フレームごとの
//    描画内容（DynamicWeatherRenderPayload）を返す。表示層（page.tsx/MapView.tsx）は
//    ペイロードのkindしか見ず、どのソース由来かを一切意識しない。
//
// 新しい動的要素を足す手順は、docs/modules/frontend/dynamic-weather-layers.md
// 「新しい動的要素を追加する1本道」節が持つ。
//
// このファイル自体はDOM/MapLibreを知らない純粋なデータ層（windLayer.ts等と同じ方針）。

import { mapDisplay } from "@/types/generated/mapDisplay";
import { parseJmaTileElement } from "@/components/Map/jmaNowcastFrames";

type DisasterFetchGroup = (typeof DISASTER_SOURCES)[number]["fetchGroup"];

interface DynamicWeatherSourceState {
  visible: boolean;
  payload: DynamicWeatherRenderPayload | undefined;
}

/** 動的気象のチップ。**源泉が配る**（`backend/app/domain/map_display.py: WEATHER_LAYER_GROUPS`）
 * ——1つのチップが複数の名前付きソースを束ねるため、どれがチップかは配信側が決める。
 *
 * 線状降水帯予測マップはrasrf系統（降水短時間予報と同じ）のため災害ではなく「降水」チップの
 * 一部として扱う。洪水キキクルのみ配信元がベクタタイル（.pbf）形式で、vectorTile kindで描く。 */
export type DynamicWeatherLayerId = (typeof mapDisplay.weatherLayerGroups)[number];

/** フレーム1つぶんの描画内容。表示層はこのkindだけで描画方法を決める（データソースの
 * 区別はここへ到達する前にデータ層が吸収済み）。 */
export type DynamicWeatherRenderPayload =
  | { kind: "rasterTile"; tileUrlTemplate: string }
  | { kind: "gridFill"; geojson: GeoJSON.FeatureCollection }
  | { kind: "gridMark"; geojson: GeoJSON.FeatureCollection }
  // 配信元のMapbox Vector Tile（.pbf）をそのままMapLibreのvectorソースへ渡す。色分けに
  // 使うプロパティ名・source-layer名等の静的なスタイル定義は描き方の宣言
  // （`features/map/scene/groups/weather.ts`）が持ち、ここではURLテンプレートだけを運ぶ。
  | { kind: "vectorTile"; tileUrlTemplate: string };

/** 災害グループの名前付きソース。**このリストが唯一の情報源**で、凡例（▶パネルの
 * 「表示する情報」）・フェッチの有効判定・描画の表示状態の3つがここを見る。3箇所へ
 * 独立に書くと、片方を改名したときチェックを外しても面が消えなくなる。
 *
 * `fetchGroup`は1本の`targetTimes.json`を共有する単位。同じグループの要素がすべて
 * 非表示なら、そのフェッチ自体を行わない。 */
const DISASTER_SOURCES = [
  { key: "heavyRain", fetchGroup: "risk" },
  { key: "landslide", fetchGroup: "risk" },
  { key: "inundation", fetchGroup: "risk" },
  { key: "flood", fetchGroup: "risk" },
  { key: "thunder", fetchGroup: "thunder" },
  { key: "tornado", fetchGroup: "thunder" },
  { key: "liden", fetchGroup: "liden" },
] as const;

export type DisasterSourceKey = (typeof DISASTER_SOURCES)[number]["key"];

/** そのフェッチ単位に属するソースキー。 */
export function disasterSourceKeys(fetchGroup: DisasterFetchGroup): readonly DisasterSourceKey[] {
  return DISASTER_SOURCES.filter((source) => source.fetchGroup === fetchGroup).map((source) => source.key);
}

/** 1グループ（=1 DynamicWeatherLayerId）配下の名前付きソースを識別するキー。グループ内で
 * 一意であればよい。単一ソースしか持たないグループも"main"という1キーだけを持つ
 * ——ソース1つならキー省略可、という特例は設けず呼び出し側の分岐を増やさない。 */
type DynamicWeatherSourceId = string;

/** 1グループぶんの状態。ソースキー→状態。 */
export type DynamicWeatherGroupState = Partial<Record<DynamicWeatherSourceId, DynamicWeatherSourceState>>;

/** targetがnowからwindowMsミリ秒先までの範囲内か（線状降水帯予測マップ用）。
 * frameIndexForTimeと違いフレーム列を前提とせず、単発スナップショットが「表示すべき時間窓」に
 * 入っているかだけを判定する。下限側にもFRAME_RANGE_EPSILON_MSの余裕を持たせ、境界ちょうど
 * （例: targetが厳密にnowと同時刻）で浮動小数の丸めに揺られないようにする。 */
export function isWithinFutureWindow(target: Date, now: Date, windowMs: number): boolean {
  const diffMs = target.getTime() - now.getTime();
  return diffMs >= -FRAME_RANGE_EPSILON_MS && diffMs <= windowMs;
}

/** 動的レイヤーの時刻フレーム。refはそのレイヤーのデータ層だけが解釈する内部参照
 * （降水なら「ナウキャストのindex」か「格子のindex」か等）。表示層はtimeしか見ない。 */
export interface DynamicWeatherFrame<TRef = unknown> {
  time: Date;
  ref: TRef;
}

/** 共有スライダーの表示用時刻ラベル（JST）。タイムラインは約48時間先まで日付をまたぐため
 * 常に日付を含める（レイヤーごとのラベル形式差を表示層へ持ち込まない）。WeatherPanel
 * の左端インジケータ上に1行で出す「正確な日時」用。 */
export function formatDynamicFrameTime(time: Date): string {
  return `${formatDynamicFrameDate(time)} ${formatDynamicFrameHourMinute(time)}`;
}

/** 日付のみ（JST、月/日）。formatDynamicFrameTimeが内部で使う。 */
function formatDynamicFrameDate(time: Date): string {
  return time.toLocaleDateString("ja-JP", { month: "numeric", day: "numeric", timeZone: "Asia/Tokyo" });
}

/** 時刻のみ（日付無し、JST、HH:mm）。WeatherPanelのルーラー目盛りラベルのうち、
 * 正時のコマ用。 */
export function formatDynamicFrameHourMinute(time: Date): string {
  return time.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tokyo" });
}

/** 分のみ（2桁、0埋め、JST）。ルーラー目盛りラベルのうち、正時でない密な区間
 * （降水ナウキャストの5分刻み等）のコマ用。JSTはUTC+9:00ちょうどで分のずれが無いため、
 * getUTCMinutes()がそのまま
 * JSTの分と一致する（departureTimeline.tsのhourMark判定と同じ理由、実行環境の
 * ローカルタイムゾーンに左右されない）。 */
export function formatDynamicFrameMinuteOnly(time: Date): string {
  return String(time.getUTCMinutes()).padStart(2, "0");
}

/** timesの中で対象時刻に最も近いindex。空配列なら0（スライダーのつまみ位置導出用。
 * 範囲外でも端へクランプする——スライダーの見た目としては端が正しい位置のため）。 */
export function nearestTimeIndex(times: readonly Date[], target: Date): number {
  if (times.length === 0) return 0;
  const targetMs = target.getTime();
  let bestIndex = 0;
  let bestDiffMs = Infinity;
  for (let i = 0; i < times.length; i++) {
    const diffMs = Math.abs(times[i].getTime() - targetMs);
    if (diffMs < bestDiffMs) {
      bestDiffMs = diffMs;
      bestIndex = i;
    }
  }
  return bestIndex;
}

// フレーム列の範囲判定に使う許容幅。境界ちょうど（スライダーの目盛りがフレーム時刻そのもの）で
// 浮動小数・ミリ秒の丸めに揺られないための小さな余裕。
const FRAME_RANGE_EPSILON_MS = 1000;
// 観測が届くまでの遅れとして許す幅（observationIndexForTime）。配信の遅れの実績値へ余裕を
// 足した上限で、これを超えて先を指していれば利用者が意図して未来を選んでいるとみなす。
const OBSERVATION_DELAY_TOLERANCE_MS = 20 * 60 * 1000;

/** 対象時刻に対応するフレームのindexを返す。**対象時刻がこのレイヤーのデータ範囲
 * （先頭〜末尾フレーム）の外なら null**（=そのレイヤーは描画しない。範囲を超えた時刻で
 * 古いフレーム[例: 最後の雨雲画像]を出し続けることを避けるため）。範囲内なら最も近い
 * フレームを返す
 * （フレーム間隔の中間時刻は近い方のフレームが「その時間帯の値」を代表する）。 */
export function frameIndexForTime(frames: readonly { time: Date }[], target: Date): number | null {
  if (frames.length === 0) return null;
  const targetMs = target.getTime();
  const firstMs = frames[0].time.getTime();
  const lastMs = frames[frames.length - 1].time.getTime();
  if (targetMs < firstMs - FRAME_RANGE_EPSILON_MS || targetMs > lastMs + FRAME_RANGE_EPSILON_MS) return null;
  return nearestTimeIndex(
    frames.map((f) => f.time),
    target,
  );
}

/** 予測を持たないレイヤー（観測だけが届く）が、共有時刻に対して出すフレームのindex。
 *
 * 配信元の観測は「今」より必ず遅れて届くため、共有時刻が最新フレームより後ろになるのが
 * 常態であり、**範囲外なら描かない**という`frameIndexForTime`の規約をそのまま当てると、
 * この種のレイヤーは常に何も描かれない。
 *
 * 遅れのぶんは最新の観測を出し、それ以上先（利用者が出発時刻を選んだ等）を指していれば
 * 描かない——「1時間後の落雷」は存在せず、古い観測をその時刻の値として出すのは誤り。
 */
export function observationIndexForTime(
  frames: readonly { time: Date }[],
  target: Date,
  toleranceMs: number = OBSERVATION_DELAY_TOLERANCE_MS,
): number | null {
  if (frames.length === 0) return null;
  const lastMs = frames[frames.length - 1].time.getTime();
  const targetMs = target.getTime();
  if (targetMs > lastMs + toleranceMs) return null;
  if (targetMs > lastMs) return frames.length - 1;
  return frameIndexForTime(frames, target);
}

/** 格子点配列を1件ずつ辿り、extractが値を取れた点だけをFeatureへ変換してFeatureCollection
 * へ積む共通ループ（precipitationNowcast.ts・windLayer.ts等が「格子点配列→frameIndex/ref
 * ぶんの値を抜く→欠損はスキップ→Feature push」という同型のfor文をそれぞれ使うため
 * 共通化してある）。extractがnullを返した点（値未取得・欠損）はスキップする
 * （1点の欠損で全体を落とさない方針）。ジオメトリ形状
 * （Point/Polygon）・プロパティの中身は呼び出し側のbuildFeatureに委ねるため、格子種別ごとの
 * 意味的な違いはこのファイルへ持ち込まない。 */
export function gridToFeatureCollection<TPoint, TValue, TGeometry extends GeoJSON.Geometry, TProps>(
  grid: readonly TPoint[],
  extract: (point: TPoint) => TValue | null,
  buildFeature: (point: TPoint, value: TValue) => GeoJSON.Feature<TGeometry, TProps>,
): GeoJSON.FeatureCollection<TGeometry, TProps> {
  const features: GeoJSON.Feature<TGeometry, TProps>[] = [];
  for (const point of grid) {
    const value = extract(point);
    if (value == null) continue;
    features.push(buildFeature(point, value));
  }
  return { type: "FeatureCollection", features };
}

/** 格子点(lat, lon)を中心とする1辺spacingDegの正方形セル（閉じたリング）。gridFill表現
 * （格子を指定色で塗る）のジオメトリ生成に使う。 */
export function gridCellRing(latitude: number, longitude: number, spacingDeg: number): GeoJSON.Position[] {
  const half = spacingDeg / 2;
  return [
    [longitude - half, latitude - half],
    [longitude + half, latitude - half],
    [longitude + half, latitude + half],
    [longitude - half, latitude + half],
    [longitude - half, latitude - half],
  ];
}

/** 配信元のタイルが返らなくなっている要素を、いま表示しているグループ（チップ）。
 *
 * `failures`は要素id→失敗したフレームの要素配下URL（`jmaTileProtocol.ts`）。表示中の
 * payloadが指すURLと突き合わせるため、フレームが進んで取得できるようになった要素や、
 * そもそも表示していない要素は当たらない。
 *
 * タイルを配信元から直接引く表現（rasterTile・vectorTile）だけが対象で、格子やGeoJSONを
 * 自前のfetchで取る表現はフェッチ自身のloading/errorが既に状態を持っている。 */
export function tileDeliveryFailureLayerIds(
  groups: Partial<Record<DynamicWeatherLayerId, DynamicWeatherGroupState>>,
  failures: ReadonlyMap<string, string>,
): DynamicWeatherLayerId[] {
  if (failures.size === 0) return [];
  const failed: DynamicWeatherLayerId[] = [];
  for (const [layerId, group] of Object.entries(groups) as [DynamicWeatherLayerId, DynamicWeatherGroupState][]) {
    const hit = Object.values(group ?? {}).some((source) => {
      if (!source?.visible) return false;
      const payload = source.payload;
      if (payload?.kind !== "rasterTile" && payload?.kind !== "vectorTile") return false;
      const ref = parseJmaTileElement(payload.tileUrlTemplate);
      return ref !== null && failures.get(ref.element) === ref.prefix;
    });
    if (hit) failed.push(layerId);
  }
  return failed;
}
