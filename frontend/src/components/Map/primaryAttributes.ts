// 一次属性（生データ）のカタログ。
//
// 一次属性の正式名（label）はaxis-catalog.jsonのprimary_attributes[]が単一ソース。
// このファイルが独自に持つのは、UI固有の対応（対応する表示レイヤーID）だけ（片側import）。
//
// 「2次軸→材料の一次属性一覧」（推定指標レイヤーON時の観測データレイヤー連動ON・
// 推定グループの展開UIに材料一覧を出す）は、backendのGET /api/axis-catalogが軸ごとに
// 解決して返すprimary_attribute_ids（SecondaryAxisSummary.primaryAttributeIds、
// secondaryAxes.ts参照）を呼び出し側が使う——GUI作成軸を含む全軸に対して同じ経路で
// 動く。このファイルにはprimaryAttributeIdsToLayerIds（一次属性id列→表示レイヤーid列への
// 変換、PRIMARY_ATTRIBUTE_LAYER_IDSを引くだけの純粋関数）だけを残す。

import type { MapLayerId } from "./mapLayers";
import primaryAttributeCatalog from "@/types/generated/primary-attributes.json";

interface CatalogPrimaryAttribute {
  attr_id: string;
  label: string;
}

export interface PrimaryAttribute {
  attrId: string;
  /** 正式名（サイドバー・研究タブで使う）。axis-catalog.json由来 */
  label: string;
}

/** 一次属性の一覧（正式名付き）。`primary-attributes.json`（backendのレジストリ宣言から
 * 生成、DBを読まない）をそのまま反映する。 */
export const PRIMARY_ATTRIBUTES: readonly PrimaryAttribute[] = (
  primaryAttributeCatalog as CatalogPrimaryAttribute[]
).map((attr) => ({ attrId: attr.attr_id, label: attr.label }));

/** attr_id→正式名の辞書（区間インスペクタ・研究タブが引く）。 */
export const PRIMARY_ATTRIBUTE_LABELS: Record<string, string> = Object.fromEntries(
  PRIMARY_ATTRIBUTES.map((attr) => [attr.attrId, attr.label]),
);

// 一次属性→表示レイヤーIDの対応（Partial: キーが無い＝表示レイヤー無し）。highway/surfaceは
// 「道路情報」（road）から分割された論理2レイヤー（roadType/roadSurface、物理描画は
// 1本の線レイヤーへ合成、mapLayers.ts参照）を指す。tunnelはタイルへの焼き込み自体は
// night軸の材料として持つが専用の色分けレイヤーも別途持つ。oneway（一方通行）はどの
// 評価軸のinputsにも属さない（表示専用の一次属性）が、独立レイヤー自体は持つ。
export const PRIMARY_ATTRIBUTE_LAYER_IDS: Partial<Record<string, MapLayerId>> = {
  highway: "highway",
  surface: "surface",
  elevation: "elevation",
  stop_poi: "stop_poi",
  accident_point: "accident_point",
  supply_poi: "supply_poi",
  tunnel: "tunnel",
  oneway: "oneway",
  landcover: "landcover",
};

// 表示レイヤーを意図的に持たない一次属性。**どれがそれに当たるかは下の
// `PRIMARY_ATTRIBUTES_WITHOUT_LAYER`が正本**で、ここへ並べると1つ増えたときに
// この注釈だけが古くなる。cycleway
// （highway_is_cycleway/cycleway_has_track等の正規化フラグ材料4種が参照する一次属性。
// 複数の軸が参照するため、
// domain/registry_defaults.pyでshared=Trueとして登録されている）は一次属性としては
// 存在するが、地図上に単独では表示しない（地図表示は評価軸bicycle_infra_quality側に
// 委ねる。ramp軸が地図レンズを自動で得るため、一次属性の側に専用レイヤーを足さない）。
// PRIMARY_ATTRIBUTE_LAYER_IDSにキーが無いことが「未対応（漏れ）」なのか「意図的にレイヤー
// 無し」なのかを区別できないため、後者をここへ明示する（ドリフト検知テスト参照）。
export const PRIMARY_ATTRIBUTES_WITHOUT_LAYER: ReadonlySet<string> = new Set([
  "lanes",
  "maxspeed",
  "lit",
  "intersection",
  "bicycle_access",
  "motor_vehicle_access",
  "geometry",
  "cycleway",
]);

/** 一次属性id列のうち、表示レイヤーを持つものだけをMapLayerIdの重複無し配列で返す
 * （推定指標レイヤーON時の観測データレイヤー連動ON用）。複数の一次属性が同じ表示
 * レイヤーへ集約される場合（1レイヤーが複数属性を表す場合）は1件にまとめる。引数は
 * attrId列（呼び出し側がSecondaryAxisSummary.primaryAttributeIds等、実行時カタログから
 * 既に持っている値）を受け取り、GUI作成軸を含む全軸に対して同じ関数で動く。 */
export function primaryAttributeIdsToLayerIds(attrIds: readonly string[]): readonly MapLayerId[] {
  const layerIds = attrIds
    .map((attrId) => PRIMARY_ATTRIBUTE_LAYER_IDS[attrId])
    .filter((layerId): layerId is MapLayerId => layerId !== undefined);
  return Array.from(new Set(layerIds));
}
