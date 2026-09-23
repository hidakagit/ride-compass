/** 押された区間から読み戻した値を、元の形へ戻す。
 *
 * MapLibreはGeoJSONソースの地物のプロパティを内部表現へ移すとき、プリミティブしか保持
 * できない仕様のためオブジェクトをJSON文字列へ直す。押したときに読み戻す側で戻す。
 */
import type { RouteSegmentDetail } from "@/types/route";

// 区間featureのproperties型。形状はfeature.geometry側に持たせるため、propertiesからは
// geometryを除外する（クリック時のポップアップ表示に必要な値だけを残す）。
type RouteSegmentProperties = Omit<RouteSegmentDetail, "geometry">;

/** オブジェクト値を持つフィールド（型から導く）。 */
type ObjectPropertyKey = {
  [K in keyof RouteSegmentProperties]: RouteSegmentProperties[K] extends Record<string, number> ? K : never;
}[keyof RouteSegmentProperties];

// 読み戻したときに文字列へ直っているフィールド。**過不足は型検査が止める**——オブジェクト値の
// フィールドを足して書き忘れると、そのフィールドだけ文字列のまま読まれ、使う側で実行時エラーになる。
const OBJECT_PROPERTY_KEYS = Object.keys({
  axis_difficulties: true,
  axis_contributions: true,
  material_values: true,
  axis_raw_values: true,
} satisfies Record<ObjectPropertyKey, true>) as ObjectPropertyKey[];

/** 押された区間から読み戻したプロパティ（オブジェクト値のフィールドがJSON文字列になっている）。 */
export type SerializedRouteSegmentProperties = Omit<RouteSegmentProperties, ObjectPropertyKey> &
  Record<ObjectPropertyKey, string>;

/** 読み戻したプロパティを、元のオブジェクトへ戻す。 */
export function restoreRouteSegmentProperties(raw: SerializedRouteSegmentProperties): RouteSegmentProperties {
  const objects = Object.fromEntries(
    OBJECT_PROPERTY_KEYS.map((key) => [key, JSON.parse(raw[key]) as Record<string, number>]),
  ) as Pick<RouteSegmentProperties, ObjectPropertyKey>;
  return { ...raw, ...objects };
}
