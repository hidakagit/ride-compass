// 一次属性（生データ）のカタログ（改善計画T163〜T168「地図レイヤー階層の次数反転」）。
//
// 一次属性の正式名（label）はaxis-catalog.jsonのprimary_attributes[]（T163でbackendが
// 書き出し）が単一ソース。このファイルが独自に持つのは、UI固有の対応（地図チップの略名・
// 対応する表示レイヤーID）だけ（片側import）。
//
// 改善計画T308: 「2次軸→材料の一次属性一覧」（推定指標レイヤーON時の観測データレイヤー
// 連動ON=T167・推定グループの展開UIに材料一覧を出す）は、以前はここ（axisMaterials/
// attrConsumers/axisMaterialLayerIds、ビルド時静的axis-catalog.jsonのregistry.py:
// AxisSpec.inputs由来）が担っていたが、GUI作成軸を含まなかったため撤去した。代わりに
// backendのGET /api/axis-catalogが軸ごとに解決して返す primary_attribute_ids
// （SecondaryAxisSummary.primaryAttributeIds、secondaryAxes.ts参照）を呼び出し側が使う。
// このファイルにはprimaryAttributeIdsToLayerIds（一次属性id列→表示レイヤーid列への
// 変換、PRIMARY_ATTRIBUTE_LAYER_IDSを引くだけの純粋関数）だけを残す。

import type { MapLayerId } from "./mapLayers";
import axisCatalog from "@/types/generated/axis-catalog.json";

interface CatalogPrimaryAttribute {
  attr_id: string;
  label: string;
  shared: boolean;
}

export interface PrimaryAttribute {
  attrId: string;
  /** 正式名（サイドバー・研究タブで使う）。axis-catalog.json由来 */
  label: string;
  shared: boolean;
}

/** 一次属性の一覧（正式名付き）。axis-catalog.json: primary_attributes[]をそのまま反映する。 */
export const PRIMARY_ATTRIBUTES: readonly PrimaryAttribute[] = (
  axisCatalog.primary_attributes as CatalogPrimaryAttribute[]
).map((attr) => ({ attrId: attr.attr_id, label: attr.label, shared: attr.shared }));

/** attr_id→正式名の辞書（区間インスペクタ・研究タブが引く）。 */
export const PRIMARY_ATTRIBUTE_LABELS: Record<string, string> = Object.fromEntries(
  PRIMARY_ATTRIBUTES.map((attr) => [attr.attrId, attr.label]),
);

// 地図チップの略名（4文字以下、2026-08-19ユーザー承認の確定命名表）。正式名（上記）とは
// 別に、地図上は文字数に応じてチップ幅が伸びる制約（MapOverlayControls.module.css:
// .iconChip）があるため短縮する。全一次属性ぶんを持つ（レイヤーの有無に関わらず、T167の
// 材料一覧表示で薄字ラベルとして使うため）。
export const PRIMARY_ATTRIBUTE_CHIP_LABELS: Record<string, string> = {
  highway: "道路種別",
  lanes: "車線数",
  maxspeed: "制限速度",
  cycleway: "インフラ",
  surface: "路面",
  bicycle_access: "自転車",
  motor_vehicle_access: "車両可否",
  lit: "街灯",
  tunnel: "トンネル",
  designation: "指定路線",
  elevation: "標高",
  stop_poi: "停止要因",
  supply_poi: "補給休憩",
  accident_point: "事故地点",
  intersection: "交差点",
  geometry: "区間形状",
  oneway: "一方通行",
};

// 一次属性→表示レイヤーIDの対応（Partial: キーが無い＝表示レイヤー無し）。改善計画T163の
// 確定命名表どおり。highway/surfaceはT165で「道路情報」（road）から分割された論理2レイヤー
// （roadType/roadSurface、物理描画は1本の線レイヤーへ合成、mapLayers.ts参照）を指す。
export const PRIMARY_ATTRIBUTE_LAYER_IDS: Partial<Record<string, MapLayerId>> = {
  highway: "roadType",
  surface: "roadSurface",
  designation: "designation",
  elevation: "elevation",
  stop_poi: "stopPoi",
  accident_point: "accidents",
  supply_poi: "supplyPoi",
  // 改善計画: 地図上に描画可能な状態で保持している要素の洗い出しで判明した「観測配下に
  // レイヤーが無いまま」を解消（tunnelはタイルへの焼き込み自体はnight軸の材料として
  // 元々あったが、専用の色分けレイヤーは持っていなかった）。
  tunnel: "tunnel",
  // 改善計画T289: 一方通行はどの評価軸のinputsにも属さない（表示専用の一次属性）ため
  // axisMaterials経由の連動ON（T167）対象にはならないが、独立レイヤー自体は持つ。
  oneway: "oneway",
};

// 表示レイヤーを意図的に持たない一次属性（改善計画T163の確定命名表で「なし」と明示した4件、
// +評価軸から参照されないbicycle_access・区間の共通コンテキストgeometry）。tunnelは上記の
// 追加でこの一覧から外れた（litは引き続きレイヤー無し）。改善計画T347: cycleway
// （highway_is_cycleway/cycleway_has_track等の正規化フラグ材料4種が参照する一次属性。
// car_stress軸の内部補正と新設の公開軸bicycle_infra_qualityの両方が参照するため、
// domain/registry_defaults.pyでshared=Trueとして登録されている）は専用レイヤー
// （旧bicycleInfra）自体を廃止したためここへ加えた——一次属性としては引き続き存在するが、
// 地図上に単独では表示しない（地図表示は評価軸bicycle_infra_quality側に委ねる。
// show_map_icon=falseのため専用レイヤーは持たない）。
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
 * （T167: 推定指標レイヤーON時の観測データレイヤー連動ON用）。複数の一次属性が同じ
 * 表示レイヤーへ集約される場合（1レイヤーが複数属性を表す場合）は1件にまとめる。
 * 改善計画T308: 引数を軸id（静的カタログの逆引き）からattrId列（呼び出し側が
 * SecondaryAxisSummary.primaryAttributeIds等、実行時カタログから既に持っている値）へ
 * 変更した——GUI作成軸を含む全軸に対して同じ関数で動くようにするため。 */
export function primaryAttributeIdsToLayerIds(attrIds: readonly string[]): readonly MapLayerId[] {
  const layerIds = attrIds
    .map((attrId) => PRIMARY_ATTRIBUTE_LAYER_IDS[attrId])
    .filter((layerId): layerId is MapLayerId => layerId !== undefined);
  return Array.from(new Set(layerIds));
}
