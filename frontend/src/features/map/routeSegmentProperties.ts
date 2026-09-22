/** 押された区間から読み戻した値を、元の形へ戻す。
 *
 * MapLibreはGeoJSONソースの地物のプロパティを内部表現へ移すとき、プリミティブしか保持
 * できない仕様のためオブジェクトをJSON文字列へ直す。押したときに読み戻す側で戻す。
 */
import type { RouteSegmentDetail } from "@/types/route";

// 区間featureのproperties型。形状はfeature.geometry側に持たせるため、propertiesからは
// geometryを除外する（クリック時のポップアップ表示に必要な値だけを残す）。
export type RouteSegmentProperties = Omit<RouteSegmentDetail, "geometry">;

// RouteSegmentPropertiesのうちオブジェクト値を持つフィールド。MapLibreはGeoJSONソースの
// feature.propertiesをvector tile相当の内部表現へ変換する際、プリミティブ型
// （string/number/boolean）しか保持できないvector tile仕様の制約でオブジェクト値を
// JSON文字列へ自動的にシリアライズする。segmentsToFeatureCollectionが渡す時点では
// 素のオブジェクトだが、クリック時にqueryRenderedFeatures経由で読み戻すと文字列化されて
// いるため、handleRouteSegmentClickでここへ列挙した各フィールドをパースし直す。
// 新しいオブジェクト型フィールドを追加するときはこの配列へも追加すること
// （material_valuesの追加漏れで実際に実行時エラーが起きた）。
const ROUTE_SEGMENT_OBJECT_PROPERTY_KEYS = ["axis_difficulties", "axis_contributions", "material_values"] as const;

/** クリック時にqueryRenderedFeatures経由で読み戻したfeature.properties（ROUTE_SEGMENT_
 * OBJECT_PROPERTY_KEYS参照のとおりオブジェクト型フィールドが文字列化されている）を、
 * 元のオブジェクトへ復元する。文字列化されていなければそのまま返す。 */
export function restoreRouteSegmentProperties(raw: RouteSegmentProperties): RouteSegmentProperties {
  const restored = { ...raw };
  for (const key of ROUTE_SEGMENT_OBJECT_PROPERTY_KEYS) {
    const value = restored[key];
    if (typeof value === "string") {
      restored[key] = JSON.parse(value) as Record<string, number>;
    }
  }
  return restored;
}
