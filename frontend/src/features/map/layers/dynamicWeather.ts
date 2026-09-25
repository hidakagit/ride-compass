// 動的気象レイヤー（時刻で中身が変わる格子・タイルのレイヤー）のデータ層。共通の契約（格子の共有・表現の種類・
// 時刻の1本のスライダー・データの差はデータ層で吸収）と、要素を足す手順は
// docs/modules/frontend/dynamic-weather-layers.mdが持つ。

import { mapDisplay } from "@/types/generated/mapDisplay";
import { parseJmaTileElement } from "@/features/map/layers/jmaTileIndex";
import { nearestTimeIndex } from "@/lib/time";

interface DynamicWeatherSourceState {
  visible: boolean;
  payload: DynamicWeatherRenderPayload | undefined;
}

/** 動的気象のチップ（1つのチップが複数の名前付きソースを束ねる。どれがチップかは源泉が決める）。 */
export type DynamicWeatherLayerId = (typeof mapDisplay.weatherLayerGroups)[number];

/** 1コマの描画内容。表示層はkindだけで描き方を決める（どの配信元由来かはデータ層が吸収済み）。 */
export type DynamicWeatherRenderPayload =
  | { kind: "rasterTile"; tileUrlTemplate: string }
  | { kind: "gridFill"; geojson: GeoJSON.FeatureCollection }
  | { kind: "gridMark"; geojson: GeoJSON.FeatureCollection }
  // 配信元のベクタタイルをそのまま渡す（色分けに使うプロパティ名等は描き方の宣言が持つ）。
  | { kind: "vectorTile"; tileUrlTemplate: string };

/** 災害のチップの名前付きソース。 */
export type DisasterSourceKey = Extract<(typeof mapDisplay.weatherElements)[number], { group: "disaster" }>["source"];

/** グループの中の名前付きソースのキー。ソースが1つのグループも1キーを持つ（特例を作らない）。 */
type DynamicWeatherSourceId = string;

/** 1グループぶんの状態。ソースキー→状態。 */
export type DynamicWeatherGroupState = Partial<Record<DynamicWeatherSourceId, DynamicWeatherSourceState>>;

/** 対象の時刻が今から`windowMs`先までの窓に入るか（コマの列を持たない単発の配信用）。 */
export function isWithinFutureWindow(target: Date, now: Date, windowMs: number): boolean {
  const diffMs = target.getTime() - now.getTime();
  return diffMs >= -FRAME_RANGE_EPSILON_MS && diffMs <= windowMs;
}

/** 時刻のコマ。`ref`はそのレイヤーのデータ層だけが読む参照（表示層は`time`しか見ない）。 */
export interface DynamicWeatherFrame<TRef = unknown> {
  time: Date;
  ref: TRef;
}

// 範囲の判定の許容幅（目盛りがコマの時刻そのものの境界で、丸めに揺られないように）。
const FRAME_RANGE_EPSILON_MS = 1000;

/** 対象の時刻に最も近いコマ。データの範囲の外ならnull（描かない——範囲外で最後のコマを出し続けない）。 */
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

/** 観測だけが届くレイヤーのコマ。観測は必ず遅れて届くので、遅れのぶん（源泉が宣言する）は最新の観測を出し、
 * それより先を指していれば描かない（古い観測を先の時刻の値として出さない）。 */
export function observationIndexForTime(
  frames: readonly { time: Date }[],
  target: Date,
  toleranceMs: number,
): number | null {
  if (frames.length === 0) return null;
  const lastMs = frames[frames.length - 1].time.getTime();
  const targetMs = target.getTime();
  if (targetMs > lastMs + toleranceMs) return null;
  if (targetMs > lastMs) return frames.length - 1;
  return frameIndexForTime(frames, target);
}

/** 格子点のうち値が取れた点だけを地物にする（1点の欠けで全体を落とさない）。 */
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

/** 格子点を中心とする1辺`spacingDeg`の正方形（閉じたリング）。 */
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

/** 配信元のタイルが返らなくなっている要素を、いま表示しているチップ。表示中のコマのURLと突き合わせるので、コマが
 * 進んで取れるようになった要素や表示していない要素は当たらない。自前で取る表現はフェッチ自身が状態を持つので対象外。 */
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
