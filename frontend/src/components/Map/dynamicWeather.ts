// 動的気象レイヤー（風・降水など、時刻スライダーで表示内容が変わる格子ベースのレイヤー）の
// 共通契約（T183再設計、実機フィードバック「動的レイヤについては今後もデータ追加があり得る
// ので、それも見据えて拡張性がある設計、実装にしてほしい」）。設計の柱は4つ:
//
// 1. **格子単位は統一**: 全レイヤーが同じ固定ラティス（backend/app/domain/wind_grid.py:
//    WIND_GRID_BBOX、フロント側の対応値はwindLayer.ts: WIND_GRID_SPACING_DEG/
//    WIND_GRID_DETAIL_SPACING_DEG）を共有する。フェッチも共有（hooks/useWeatherGrid.ts、
//    1回のOpen-Meteo呼び出しで全要素ぶんの値を取る）。
// 2. **表現は限られた種類のみ**: 格子中央にマークを出す（gridMark、風パターン）、
//    格子を指定色で塗る（gridFill、雨パターン）、配信元が描画済みの画像を重ねる
//    （rasterTile、気象庁ナウキャスト等）に加え、配信元がMapbox Vector Tile（.pbf）で
//    配信する地物をMapLibre標準のvectorソース+line/fillレイヤーでそのまま描画する
//    （vectorTile、洪水キキクル。改善計画T416）。vectorTileは配信元のタイルが地物の
//    プロパティに表示値（例: 危険度レベル）を埋め込み済みのため、gridFill/gridMarkと違い
//    feature-stateやGeoJSON変換によるJS側の値差し込みが不要——MapLibreのpaint式
//    （["get", プロパティ名]）だけで色分けできる点がrasterTileとの主な違い（rasterTileは
//    配信元が色分け済みの画像そのもの、vectorTileは配信元が地物+属性値を配信しこちら側で
//    色分けする）。新しい要素はこの4種のどれかを選ぶだけで、独自の描画方式は増やさない。
// 3. **時間経過はスライドバー1本**: ONの全レイヤーのフレーム時刻を統合した1本のタイムライン
//    （mergeFrameTimes）を共有スライダーへ渡す。各レイヤーは選択時刻に対応する自分のフレームを
//    描画し、**選択時刻が自分のデータ範囲外なら何も描画しない**（frameIndexForTime、
//    従来の「端のフレームへクランプして古いデータを見せ続ける」挙動の廃止）。
// 4. **データ取得の差異はデータ層で吸収**: 1要素につきデータソースはN個あり得る
//    （例: 降水=気象庁ナウキャスト+自前格子）。各要素のデータ層モジュール
//    （precipitationNowcast.ts等）がソースを1本のフレーム列へ統合し、フレームごとの
//    描画内容（DynamicWeatherRenderPayload）を返す。表示層（page.tsx/MapView.tsx）は
//    ペイロードのkindしか見ず、どのソース由来かを一切意識しない。
//
// **新しい動的要素を追加する1本道**:
//   (1) バックエンド: wind_grid.pyのWindGridPointへ値フィールドを追加し、
//       weather_client.pyのWIND_GRID_VARIABLESへOpen-Meteo変数を足す（フェッチは相乗り）
//   (2) データ層: 要素モジュールを新設し、フレーム列（DynamicWeatherFrame[]）と
//       ペイロード関数（ref→DynamicWeatherRenderPayload）を実装する
//   (3) MapView.tsx: DYNAMIC_WEATHER_RENDERERSへ描画スペック（raster/gridFill/gridMark/
//       vectorTileの宣言と配色・アイコン）を1エントリ追加する
//   (4) mapLayers.ts: 地図チップを追加し、MapLayerId・CHIP_DYNAMIC_WEATHER_LAYER_IDSへ
//       1行足す
//
// このファイル自体はDOM/MapLibreを知らない純粋なデータ層（windLayer.ts等と同じ方針）。

import type { MapLayerId } from "@/components/Map/mapLayers";

// 動的気象レイヤーの一覧（単一の情報源、MapView.tsx: DYNAMIC_WEATHER_RENDERERS・
// page.tsxのdynamicWeather組み立ての両方がこの配列を見る）。新しい要素を追加するときは
// ここへidを1つ足す（mapLayers.tsのMapLayerIdにも同名を追加しておくこと）。全要素が
// チップ（layerVisibility）でON/OFFする（常時マウント・チップ無しの要素は持たない）。
export const CHIP_DYNAMIC_WEATHER_LAYER_IDS = [
  "precipitationNowcast",
  "windVector",
  // 災害。雷ナウキャスト（thns）・竜巻発生確度ナウキャスト（trns）・雷放電位置データ
  // （liden）・キキクル4種（土砂災害・大雨・浸水・洪水）の7要素を名前付きソースとして
  // 持つ1グループ（MapView.tsx: DYNAMIC_WEATHER_RENDERERSのdisasterグループ参照）。
  // 線状降水帯予測マップはrasrf系統（降水短時間予報と同じ）のため災害ではなく「降水」
  // チップの一部として扱う。洪水キキクルのみ配信元がベクタタイル（.pbf）形式のため、
  // vectorTile kind（本ファイル冒頭コメント参照）で描画する。
  "disaster",
] as const satisfies readonly MapLayerId[];

export const DYNAMIC_WEATHER_LAYER_IDS = CHIP_DYNAMIC_WEATHER_LAYER_IDS;
export type DynamicWeatherLayerId = (typeof DYNAMIC_WEATHER_LAYER_IDS)[number];

/** フレーム1つぶんの描画内容。表示層はこのkindだけで描画方法を決める（データソースの
 * 区別はここへ到達する前にデータ層が吸収済み）。 */
export type DynamicWeatherRenderPayload =
  | { kind: "rasterTile"; tileUrlTemplate: string }
  | { kind: "gridFill"; geojson: GeoJSON.FeatureCollection }
  | { kind: "gridMark"; geojson: GeoJSON.FeatureCollection }
  // 配信元のMapbox Vector Tile（.pbf）をそのままMapLibreのvectorソースへ渡す（改善計画
  // T416）。色分けに使うプロパティ名・source-layer名等の静的なスタイル定義は
  // MapView.tsx側のDynamicWeatherVectorSpecが持ち、ここではURLテンプレートだけを運ぶ
  // （rasterTileと対称的な役割分担）。
  | { kind: "vectorTile"; tileUrlTemplate: string };

/** 1グループ（=1 DynamicWeatherLayerId）配下の名前付きソースを識別するキー。グループ内で
 * 一意であればよい（改善計画T432、「1レイヤーID=1 kind」制約の解消。単一ソースしか
 * 持たないグループも"main"という1キーだけを持つ——ソース1つならキー省略可、という特例は
 * 設けず呼び出し側の分岐を増やさない）。 */
export type DynamicWeatherSourceId = string;

/** 1ソースぶんの表示状態。visible/payloadどちらか欠けても非表示
 * （MapView.tsx: applyDynamicWeatherState参照）。 */
export interface DynamicWeatherSourceState {
  visible: boolean;
  payload: DynamicWeatherRenderPayload | undefined;
}

/** 1グループぶんの状態。ソースキー→状態（改善計画T432）。 */
export type DynamicWeatherGroupState = Partial<Record<DynamicWeatherSourceId, DynamicWeatherSourceState>>;

/** targetがnowからwindowMsミリ秒先までの範囲内か（改善計画T432、線状降水帯予測マップ用）。
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

/** ONの全レイヤーのフレーム時刻を統合し、昇順・重複排除した1本のタイムラインを返す
 * （共有スライダーの目盛り）。降水ナウキャスト（5分刻み）と格子予報（1時間刻み）が
 * 混ざると「近い将来は細かく、遠い将来は粗い」目盛りが自然にできる。 */
export function mergeFrameTimes(frameLists: readonly (readonly { time: Date }[])[]): Date[] {
  const byMs = new Map<number, Date>();
  for (const frames of frameLists) {
    for (const frame of frames) {
      if (!byMs.has(frame.time.getTime())) byMs.set(frame.time.getTime(), frame.time);
    }
  }
  return [...byMs.values()].sort((a, b) => a.getTime() - b.getTime());
}

/** 共有スライダーの表示用時刻ラベル（JST）。タイムラインは約48時間先まで日付をまたぐため
 * 常に日付を含める（レイヤーごとのラベル形式差を表示層へ持ち込まない）。WeatherPanel
 * の左端インジケータ上に1行で出す「正確な日時」用（実機フィードバック「今の位置の正しい
 * 日時は左端ではなく上に出して」）。 */
export function formatDynamicFrameTime(time: Date): string {
  return `${formatDynamicFrameDate(time)} ${formatDynamicFrameHourMinute(time)}`;
}

/** 日付のみ（JST、月/日）。formatDynamicFrameTimeが内部で使う。 */
function formatDynamicFrameDate(time: Date): string {
  return time.toLocaleDateString("ja-JP", { month: "numeric", day: "numeric", timeZone: "Asia/Tokyo" });
}

/** 時刻のみ（日付無し、JST、HH:mm）。WeatherPanelのルーラー目盛りラベル
 * （実機フィードバック「目盛りは日付部分は不要、時刻のみ」）のうち、正時のコマ用。 */
export function formatDynamicFrameHourMinute(time: Date): string {
  return time.toLocaleTimeString("ja-JP", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Tokyo" });
}

/** 分のみ（2桁、0埋め、JST）。ルーラー目盛りラベルのうち、正時でない密な区間
 * （降水ナウキャストの5分刻み等）のコマ用（実機フィードバック「時刻も細いところは
 * 分だけにする」）。JSTはUTC+9:00ちょうどで分のずれが無いため、getUTCMinutes()がそのまま
 * JSTの分と一致する（page.tsxのhourMark判定と同じ理由、実行環境のローカルタイムゾーンに
 * 左右されない）。 */
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

/** 対象時刻に対応するフレームのindexを返す。**対象時刻がこのレイヤーのデータ範囲
 * （先頭〜末尾フレーム）の外なら null**（=そのレイヤーは描画しない。要件「該当時間データが
 * ない場合、地図には描画しない」。従来は端のフレームへクランプし、例えばナウキャストの
 * 範囲を超えた時刻でも最後の雨雲画像を出し続けていた）。範囲内なら最も近いフレームを返す
 * （フレーム間隔の中間時刻は近い方のフレームが「その時間帯の値」を代表する）。 */
export function frameIndexForTime(frames: readonly { time: Date }[], target: Date): number | null {
  if (frames.length === 0) return null;
  const targetMs = target.getTime();
  const firstMs = frames[0].time.getTime();
  const lastMs = frames[frames.length - 1].time.getTime();
  if (targetMs < firstMs - FRAME_RANGE_EPSILON_MS || targetMs > lastMs + FRAME_RANGE_EPSILON_MS) return null;
  return nearestTimeIndex(
    frames.map((f) => f.time),
    target
  );
}

/** 格子点配列を1件ずつ辿り、extractが値を取れた点だけをFeatureへ変換してFeatureCollection
 * へ積む共通ループ（改善計画T466: precipitationNowcast.ts・windPenalty.ts・windLayer.tsの
 * 3ファイルが「格子点配列→frameIndex/refぶんの値を抜く→欠損はスキップ→Feature push」という
 * ほぼ同型のfor文を独立実装していたのを統合）。extractがnullを返した点（値未取得・欠損）は
 * スキップする（1点の欠損で全体を落とさない、という3ファイル共通の方針）。ジオメトリ形状
 * （Point/Polygon）・プロパティの中身は呼び出し側のbuildFeatureに委ねるため、格子種別ごとの
 * 意味的な違いはこのファイルへ持ち込まない。 */
export function gridToFeatureCollection<TPoint, TValue, TGeometry extends GeoJSON.Geometry, TProps>(
  grid: readonly TPoint[],
  extract: (point: TPoint) => TValue | null,
  buildFeature: (point: TPoint, value: TValue) => GeoJSON.Feature<TGeometry, TProps>
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
